"""Recovery feedback and escalation bookkeeping for one run."""

from collections import deque
from dataclasses import dataclass
from typing import Literal

from fsd.approval.gate import RefusalReason
from fsd.operator.config import Settings
from fsd.operator.frames import Thumbnail, changed

RECENT_SCREENS = 6

REFUSAL_HINTS: dict[RefusalReason, str] = {
  "pointer_target": (
    "Input at that point is not approved. Choose a point owned by an approved app "
    "or bring the approved target forward."
  ),
  "keyboard_focus": (
    "Keyboard input is not approved for the focused app. "
    "Click inside an approved target window first."
  ),
  "focus_changed": ("Focus moved during input. Text may be partly entered; check before retrying."),
}


def refusal_hint(reason: RefusalReason, owner: str | None) -> str:
  target = owner if owner is not None else "unidentified app"
  return f"Current input owner: {target}. {REFUSAL_HINTS[reason]}"


STUCK_FEEDBACK = "Your recent actions produced no visible progress. Try a different approach."

Escalation = Literal["continue", "warn", "escalate"]


@dataclass(frozen=True)
class Seen:
  visible_change: bool | None
  progress: bool
  escalation: Escalation


class Recovery:
  def __init__(self, settings: Settings) -> None:
    self._settings = settings
    self._recent: deque[Thumbnail] = deque(maxlen=RECENT_SCREENS)
    self._window: deque[Thumbnail] = deque(maxlen=RECENT_SCREENS)
    self.reset()

  def reset(self) -> None:
    self._streak = 0
    self._refusals = 0
    self._unchanged = 0
    self._warnings = 0
    self._rejected = 0
    self._recent.clear()
    self._window.clear()

  def refused(self) -> bool:
    self._streak += 1
    self._refusals += 1
    return (
      self._streak >= self._settings.refusal_streak_limit
      or self._refusals >= self._settings.refusal_total_limit
    )

  def performed(self) -> None:
    self._streak = 0

  def rejected_done(self) -> bool:
    self._rejected += 1
    return self._rejected >= self._settings.rejected_done_limit

  def observe(self, current: Thumbnail, acted_on: Thumbnail | None) -> Seen:
    visible = None if acted_on is None else changed(acted_on, current)
    if visible is not None:
      self._unchanged = 0 if visible else self._unchanged + 1

    # Progress means reaching a screen not seen recently, so oscillating
    # between two screens does not count, event after a warning
    progress = bool(visible) and all(changed(earlier, current) for earlier in self._recent)
    repeats = sum(1 for earlier in self._window if not changed(earlier, current))
    self._recent.append(current)
    self._window.append(current)

    if progress:
      self._warnings = 0

    stuck = (
      self._unchanged >= self._settings.no_change_limit
      or repeats >= self._settings.repeat_screen_limit - 1
    )
    if not stuck:
      return Seen(visible, progress, "continue")

    # Restart warning evidence, retaining recent history so familiar
    # screens cannot reset the wanring budget by looking new.
    self._warnings += 1
    self._unchanged = 0
    self._window.clear()
    escalation: Escalation = (
      "escalate" if self._warnings >= self._settings.stuck_warning_limit else "warn"
    )
    return Seen(visible, progress, escalation)
