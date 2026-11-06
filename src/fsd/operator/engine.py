import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial

from fsd.approval.gate import ActionGate, GateRefused
from fsd.approval.store import ApprovalStore, ApprovalStoreError
from fsd.operator.client import DecisionClient, InferenceError, InvalidDecision
from fsd.operator.config import Settings
from fsd.operator.context import Session
from fsd.operator.contracts import (
  Action,
  Click,
  Decision,
  Event,
  Hold,
  Key,
  ModelResult,
  Reply,
  Scroll,
  TypeText,
  VerificationResult,
  Wait,
)
from fsd.operator.control import Control, RunCancelled, controlled
from fsd.operator.frames import Thumbnail, thumbnail
from fsd.operator.records import Purpose, StepRecord
from fsd.operator.recovery import STUCK_FEEDBACK, Recovery, refusal_hint
from fsd.platform.base import MANDATORY_CAPABILITIES, Frame, Platform, PlatformError
from fsd.platform.held_input import ReleaseError

EventSink = Callable[[Event], Awaitable[Reply | None]]
CORRECTION = "Your last response was invalid. Return only a valid schema object."


def correction_for(exc: InvalidDecision) -> str:
  if not exc.feedback:
    return CORRECTION
  return f"{CORRECTION}\nFix these errors:\n{exc.feedback}"


class RunLimit(Exception):
  pass


@dataclass
class Step:
  """One captured screen and the trace record it accumulates."""

  approved: frozenset[str]
  frame: Frame
  started: float
  trace: dict[str, object]
  record: StepRecord


def usage_metrics(result: ModelResult | VerificationResult) -> dict[str, object]:
  return {
    "encode_seconds": result.encode_seconds,
    "request_seconds": result.request_seconds,
    "input_tokens": result.input_tokens,
    "cached_input_tokens": result.cached_input_tokens,
    "output_tokens": result.output_tokens,
    "cost": result.cost,
  }


class Engine:
  def __init__(
    self,
    platform: Platform,
    store: ApprovalStore,
    client: DecisionClient,
    settings: Settings,
  ) -> None:
    self.platform = platform
    self.store = store
    self.client = client
    self.settings = settings
    self.gate = ActionGate(platform, store)
    self._active: object | None = None
    self.input_uncertain = False

  async def _execute(
    self,
    action: Action,
    frame: Frame,
    check: Callable[[], None],
    control: Control,
  ) -> None:
    check()
    if isinstance(action, Click):
      self.gate.click(frame.to_screen(action.x, action.y))
    elif isinstance(action, Scroll):
      self.gate.scroll(frame.to_screen(action.x, action.y), action.dx, action.dy)
    elif isinstance(action, TypeText):
      self.gate.type_text_checked(action.text, check)
    elif isinstance(action, Key):
      self.gate.press_keys(action.combo)
    elif isinstance(action, Hold):
      if action.duration_ms > self.settings.max_hold_ms:
        raise ValueError("Requested hold exceeds the configured limit.")
      self.gate.hold_key(action.key, action.duration_ms, check)
    elif isinstance(action, Wait):
      if action.duration_ms > self.settings.max_wait_ms:
        raise ValueError("Requested wait exceeds the configured limit.")
      deadline = time.monotonic() + action.duration_ms / 1000
      while time.monotonic() < deadline:
        check()
        await controlled(
          asyncio.sleep(min(0.02, max(0, deadline - time.monotonic()))),
          control,
          1,
        )

  async def run(
    self,
    goal: str,
    session: Session,
    control: Control,
    emit: EventSink,
  ) -> None:
    run_id = secrets.token_hex(8)
    if self.input_uncertain:
      await emit(
        Event(
          "failed",
          "Input release failed earlier. Check keyboard state and restart fsd.",
          metrics={"run_id": run_id},
        )
      )
      return
    if self._active is not None:
      raise RuntimeError("This engine already has an active run.")

    token = object()
    self._active = token
    step = 0
    pending: Step | None = None
    deadline = time.monotonic() + self.settings.active_seconds
    actions = 0
    failures = 0
    recovery = Recovery(self.settings)
    acted_on: Thumbnail | None = None
    last_decision: Decision | None = None
    last_observed_step: int | None = None

    def check() -> None:
      control.check()
      if self._active is not token:
        raise RunCancelled("Run was superseded")
      if time.monotonic() >= deadline:
        raise RunLimit("Active execution time limit reached.")

    def capture() -> Step:
      nonlocal pending
      if pending is not None:
        raise RuntimeError("The previous capture has not been recorded.")

      self.store.refresh()
      approved = self.store.approved()
      started = time.monotonic()
      frame = self.platform.capture()
      capture_seconds = time.monotonic() - started

      trace: dict[str, object] = {
        "run_id": run_id,
        "step": step,
        "frame_width": frame.width,
        "frame_height": frame.height,
        "frame_bytes": len(frame.png),
        "capture_seconds": capture_seconds,
      }
      shot = Step(approved, frame, started, trace, StepRecord(run_id, step, frame, approved))
      pending = shot
      shot.record.foreground_app = self.platform.frontmost_app()
      trace["bundle_id"] = shot.record.foreground_app
      return shot

    async def record(shot: Step, outcome: str) -> None:
      nonlocal pending, step
      if pending is not shot:
        raise RuntimeError("Cannot record a step that is not pending.")

      shot.trace["outcome"] = outcome
      event = Event(
        "metrics",
        "Step recorded",
        metrics=dict(shot.trace),
        snapshot=shot.record.snapshot(outcome, session.feedback, session.warning),
      )

      # Delivery may fail after the sink has already consumed the event.
      pending = None
      step += 1
      await emit(event)

    async def record_interruption(exc: BaseException) -> None:
      if pending is not None:
        pending.record.interruption = type(exc).__name__
        await record(pending, "interrupted")

    async def pause(message: str, *, limit: bool = False, note: str | None = None) -> None:
      nonlocal deadline, actions, failures, acted_on, last_decision
      control.check()
      started = time.monotonic()

      session.notice(message if note is None else note)

      while True:
        control.check()
        reply = await emit(Event("help", message, limit=limit, metrics={"run_id": run_id}))
        control.check()
        if reply is None or reply.cancel:
          raise RunCancelled("Run cancelled")
        if limit and not reply.extend:
          message = "Use /extend to grant another run budget, or /cancel."
          continue
        try:
          session.guide(reply.text or "User requested continuation; inspect the current screen.")
        except ValueError as exc:
          message = str(exc)
          continue
        break

      if limit:
        deadline = time.monotonic() + self.settings.active_seconds
        actions = 0
      else:
        deadline += time.monotonic() - started

      failures = 0
      recovery.reset()
      acted_on = None
      last_decision = None

    async def ask[T: (ModelResult, VerificationResult)](
      request: Callable[[str], Awaitable[T]], shot: Step, purpose: Purpose
    ) -> T | None:
      correction = ""
      for attempt in range(2):
        check()
        detail = shot.record.attempt(purpose, correction)
        try:
          result = await controlled(
            request(correction),
            control,
            max(0, deadline - time.monotonic()),
          )
          detail.complete(result.decision if isinstance(result, ModelResult) else result.verdict)
          return result
        except InvalidDecision as exc:
          detail.status = "invalid"
          detail.invalid_cause = exc.cause
          detail.feedback = exc.feedback
          shot.trace["invalid_cause"] = exc.cause
          if attempt:
            message = "The model returned two invalid responses; no action was performed."
            session.notice(message)
            shot.record.pause = message
            await record(shot, "invalid")
            control.check()
            await pause(message)
          correction = correction_for(exc)
        except (RunCancelled, TimeoutError, asyncio.CancelledError) as exc:
          detail.status = "interrupted"
          detail.error_type = type(exc).__name__
          raise
        except Exception as exc:
          detail.status = "error"
          detail.error_type = type(exc).__name__
          raise
      return None

    try:
      control.check()
      session.begin(goal)
      if not self.platform.capabilities >= MANDATORY_CAPABILITIES:
        raise PlatformError("Required main-display capture or window ownership is unavailable.")
      missing = self.platform.check_permissions()
      if missing:
        raise PlatformError(
          "Grant required permissions first: " + ", ".join(p.name for p in missing)
        )
      while True:
        try:
          check()
          if actions >= self.settings.action_limit:
            raise RunLimit("Action limit reached.")

          shot = capture()
          current = thumbnail(shot.frame)
          seen = recovery.observe(current, acted_on)
          acted_on = None

          if seen.visible_change is not None:
            shot.trace["visible_change"] = seen.visible_change
          if seen.progress:
            session.progressed()
          if seen.escalation != "continue":
            shot.trace["stuck"] = seen.escalation
            if last_decision is not None:
              session.strategy_failed(last_decision)
            if seen.escalation == "escalate":
              message = "Repeated attempts are not making progress. Guidance is needed."
              session.notice(message)
              shot.record.pause = message
              await record(shot, "help")
              await pause(message)
              continue
            session.warn(STUCK_FEEDBACK)

          observation = session.observe(shot.frame, shot.approved, shot.record.foreground_app)
          shot.record.observation = observation.text
          shot.record.previous_frame_step = last_observed_step if observation.previous else None
          last_observed_step = shot.record.step
          shot.trace["images_sent"] = 1 if observation.previous is None else 2
          result = await ask(partial(self.client.decide, observation, control), shot, "decision")
          if result is None:
            continue

          decision = result.decision
          shot.trace.update(usage_metrics(result))
          shot.trace["screenshot_to_decision_seconds"] = time.monotonic() - shot.started
          shot.trace["decision"] = decision.kind
          shot.trace["previous_result"] = decision.previous_result

          check()
          self.store.refresh()
          if shot.approved != self.store.approved():
            session.notice("App approvals changed. Reconsider using the new screenshot.")
            await record(shot, "approvals_changed")
            continue

          if decision.previous_result == "failure":
            failures += 1
          elif decision.previous_result == "success":
            failures = 0

          if decision.kind == "help":
            session.notes = decision.notes
            session.notice(decision.message)
            shot.record.pause = decision.message
            await record(shot, "help")
            await pause(decision.message)
            continue

          if decision.kind == "done":
            await record(shot, "claimed_done")
            check()

            settle = self.settings.verify_settle_ms / 1000
            if settle:
              await controlled(asyncio.sleep(settle), control, max(0, deadline - time.monotonic()))
            check()

            proof = capture()
            proof.trace["images_sent"] = 1
            proof.trace["decision"] = "verify"
            proof.record.goal = goal
            verification = await ask(
              partial(self.client.verify, goal, proof.frame, control), proof, "verification"
            )
            if verification is None:
              continue

            proof.trace.update(usage_metrics(verification))
            check()
            self.store.refresh()
            if proof.approved != self.store.approved():
              session.notice("App approvals changed. Reconsider using the new screenshot.")
              await record(proof, "approvals_changed")
              continue

            if verification.verdict.complete:
              await record(proof, "done")
              check()
              session.record(decision, "completed")
              await emit(Event("done", decision.message, metrics={"run_id": run_id}))
              return

            evidence = verification.verdict.evidence
            session.record(decision, "completion rejected: " + evidence)
            session.notice("Completion was not confirmed: " + evidence)
            rejected_limit = recovery.rejected_done()
            if rejected_limit:
              proof.record.pause = (
                "The task was reported complete twice, but the screen did not confirm it.\n"
                f"Verifier evidence: {evidence}"
              )
            await record(proof, "rejected_done")
            if proof.record.pause is not None:
              await pause(proof.record.pause)
            continue

          action = decision.action
          assert action is not None
          if failures >= self.settings.recovery_limit:
            message = "Repeated attempts are not making progress. Guidance is needed."
            session.notice(message)
            shot.record.pause = message
            await record(shot, "help")
            await pause(message)
            continue

          await emit(Event("progress", decision.message))
          check()
          self.store.refresh()
          if shot.approved != self.store.approved():
            session.notice("Approvals changed before execution; choose again from a fresh image.")
            await record(shot, "approvals_changed")
            continue

          before_owner = self.platform.frontmost_app()
          actions += 1
          shot.trace["action"] = action.kind
          started_action = time.monotonic()

          try:
            await self._execute(action, shot.frame, check, control)
          except ReleaseError:
            shot.record.execution_status = "release failed; input state uncertain"
            session.record(decision, "release failed; input state uncertain")
            raise
          except (GateRefused, ValueError) as exc:
            if isinstance(exc, GateRefused):
              hint = refusal_hint(exc.reason, exc.owner)
              shot.trace["refusal"] = exc.reason
              shot.record.refusal = {"reason": exc.reason, "owner": exc.owner}
            else:
              hint = str(exc)
              shot.trace["refusal"] = "limit"
              shot.record.refusal = {"reason": "limit", "owner": None}

            shot.record.execution_status = "refused: " + hint
            session.record(decision, "refused: " + hint)
            session.notice(hint)
            refused_limit = recovery.refused()
            if refused_limit:
              shot.record.pause = f"Actions keep being refused. Last refusal: {hint}"
            await record(shot, "refused")
            if shot.record.pause is not None:
              await pause(
                shot.record.pause,
                note="Repeated refusals; the owner was asked for help. " + hint,
              )
            continue
          except (RunCancelled, RunLimit, PlatformError, RuntimeError, ApprovalStoreError):
            shot.record.execution_status = "interrupted; input may have partially occurred"
            session.record(decision, "interrupted; input may have partially occurred")
            raise

          recovery.performed()
          acted_on = current
          last_decision = decision
          shot.record.execution_status = "performed; outcome awaits next observation"
          session.record(decision, "performed; outcome awaits next observation")
          await emit(
            Event(
              "action",
              f"Performed {action.kind}",
              metrics={
                "run_id": run_id,
                "action": action.kind,
                "execution_seconds": time.monotonic() - started_action,
                "screenshot_to_action_seconds": started_action - shot.started,
              },
            )
          )
          check()

          after_owner = self.platform.frontmost_app()
          if after_owner != before_owner and (
            after_owner is None or not self.store.is_approved(after_owner)
          ):
            target = after_owner if after_owner is not None else "an unidentified app"
            shot.record.pause = (
              f"The action changed focus to {target}, which is unapproved for input."
            )
            session.notice(shot.record.pause)
          await record(shot, "performed")
          check()
          if shot.record.pause is not None:
            await pause(shot.record.pause)

        except (RunLimit, TimeoutError) as exc:
          message = "The active run budget has been reached."
          if pending is not None:
            pending.record.pause = message
          session.notice(message)
          await record_interruption(exc)
          await pause(message, limit=True)

    except asyncio.CancelledError as exc:
      await record_interruption(exc)
      raise
    except RunCancelled as exc:
      await record_interruption(exc)
      await emit(
        Event(
          "cancelled",
          "Task cancelled; session remains open.",
          metrics={"run_id": run_id},
        )
      )
    except ReleaseError as exc:
      self.input_uncertain = True
      await record_interruption(exc)
      await emit(
        Event(
          "failed",
          str(exc) + " Check keyboard state and restart fsd before more input.",
          metrics={"run_id": run_id},
        )
      )
    except (InferenceError, PlatformError, ApprovalStoreError, ValueError, RuntimeError) as exc:
      await record_interruption(exc)
      await emit(Event("failed", str(exc), metrics={"run_id": run_id}))
    finally:
      if self._active is token:
        self._active = None
