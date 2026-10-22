import re

from fsd.operator.config import Settings
from fsd.operator.frames import Thumbnail
from fsd.operator.recovery import REFUSAL_HINTS, Recovery

A = Thumbnail((4, 1), bytes([0] * 4))
B = Thumbnail((4, 1), bytes([255] * 4))


def test_three_consecutive_refusals_escalate() -> None:
  recovery = Recovery(Settings())
  assert [recovery.refused() for _ in range(3)] == [False, False, True]


def test_performed_action_resets_streak_but_not_total() -> None:
  # Interleaved success must not hide a run that is refused over and over.
  recovery = Recovery(Settings(refusal_total_limit=5))
  results = []
  for _ in range(3):
    results.append(recovery.refused())
    results.append(recovery.refused())
    recovery.performed()
  assert results == [False, False, False, False, True, True]


def test_reset_clears_refusal_and_rejected_completion_budgets() -> None:
  recovery = Recovery(Settings(refusal_total_limit=3))
  assert not recovery.refused()
  assert not recovery.refused()
  assert recovery.refused()
  assert not recovery.rejected_done()
  recovery.reset()
  assert not recovery.refused()
  assert not recovery.refused()
  assert recovery.refused()
  assert not recovery.rejected_done()


def test_second_rejected_completion_escalates() -> None:
  recovery = Recovery(Settings())
  assert [recovery.rejected_done(), recovery.rejected_done()] == [False, True]


def test_first_observation_has_no_visible_change_value() -> None:
  seen = Recovery(Settings()).observe(A, None)
  assert seen.visible_change is None
  assert seen.progress is False
  assert seen.escalation == "continue"


def test_actions_without_change_warn_then_escalate() -> None:
  # The agent gets a chance to change approach before a human is asked.
  recovery = Recovery(Settings())
  escalations = [recovery.observe(A, None).escalation]
  escalations += [recovery.observe(A, A).escalation for _ in range(4)]
  assert escalations == ["continue", "continue", "warn", "continue", "escalate"]


def test_progress_to_a_new_screen_resets_warnings() -> None:
  recovery = Recovery(Settings())
  recovery.observe(A, None)
  recovery.observe(A, A)
  assert recovery.observe(A, A).escalation == "warn"
  seen = recovery.observe(B, A)
  assert seen.visible_change is True
  assert seen.progress is True
  recovery.observe(B, B)
  assert recovery.observe(B, B).escalation == "warn"


def test_oscillating_screens_warn_despite_visible_change() -> None:
  # Toggling between two screens changes pixels every step but goes nowhere.
  recovery = Recovery(Settings())
  sequence = [(A, None), (B, A), (A, B), (B, A), (A, B)]
  escalations = [recovery.observe(current, before).escalation for current, before in sequence]
  assert escalations == ["continue", "continue", "continue", "continue", "warn"]


def test_hints_cover_every_reason_and_name_no_app() -> None:
  # Bundle IDs are enforcement metadata, never agent input.
  assert set(REFUSAL_HINTS) == {"pointer_target", "keyboard_focus", "focus_changed"}
  assert all(re.search(r"\w+\.\w+\.\w+", hint) is None for hint in REFUSAL_HINTS.values())
