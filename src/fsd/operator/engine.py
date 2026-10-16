import asyncio
import time
from collections.abc import Awaitable, Callable

from fsd.approval.gate import ActionGate
from fsd.approval.store import ApprovalStore
from fsd.operator.client import DecisionClient
from fsd.operator.config import Settings
from fsd.operator.context import Session
from fsd.operator.contracts import (
  Action,
  Click,
  Event,
  Hold,
  Key,
  Reply,
  Scroll,
  TypeText,
  Wait,
)
from fsd.operator.control import Control, RunCancelled, controlled
from fsd.platform.base import MANDATORY_CAPABILITIES, Frame, Platform, PlatformError

EventSink = Callable[[Event], Awaitable[Reply | None]]


class RunLimit(Exception):
  pass


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
    if self.input_uncertain:
      await emit(
        Event(
          "failed",
          "Input release failed earlier. Check keyboard state and restart fsd.",
        )
      )
      return
    if self._active is not None:
      raise RuntimeError("This engine already has an active run.")

    token = object()
    self._active = token
    deadline = time.monotonic() + self.settings.active_seconds
    actions = 0
    failures = 0
    repeats = 0
    previous_signature: tuple[bytes, str] | None = None

    def check() -> None:
      control.check()
      if self._active is not token:
        raise RunCancelled("Run was superseded")
      if time.monotonic() >= deadline:
        raise RunLimit("Active execution time limit reached.")

    async def pause(message: str, *, limit: bool = False) -> None:
      nonlocal deadline, actions, failures, repeats, previous_signature
      started = time.monotonic()
      session.notice(message)
      while True:
        control.check()
        reply = await emit(Event("help", message, limit=limit))
        if reply is None or reply.cancel:
          raise RunCancelled("Run cancelled")
        if limit and not reply.extend:
          message = "Use /extend to grant another run budget, or /cancel."
          continue
        try:
          session.guide(
            reply.text or "User requested continuation; inspect the current screen."
          )
        except ValueError as exc:
          message = str(exc)
          continue
        break
      if limit:
        deadline = time.monotonic() + self.settings.active_seconds
        actions = 0
      else:
        deadline += time.monotonic() - started
      failures = repeats = 0
      previous_signature = None

    try:
      control.check()
      session.begin(goal)
      if not self.platform.capabilities >= MANDATORY_CAPABILITIES:
        raise PlatformError("Required filtered capture or window ownership is unavailable.")
      missing = self.platform.check_permissions()
      if missing:
        raise PlatformError(
          "Grant required permissions first: " + ", ".join(p.name for p in missing)
        )
    except RunCancelled:
      await emit(Event("cancelled", "Task cancelled; session remains open."))
    except (PlatformError, ValueError, RuntimeError) as exc:
      await emit(Event("failed", str(exc)))
    finally:
      if self._active is token:
        self._active = None
