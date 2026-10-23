"""Recovery feedback and escalation bookkeeping for one run."""

from collections import deque
from dataclasses import dataclass
from typing import Literal

from fsd.approval.gate import RefusalReason
from fsd.operator.config import Settings
from fsd.operator.frames import Thumbnail

RECENT_SCREENS = 6

# Filtered capture hides unapproved windows.
# Feedback must explain the refusal without exposing the identity of a hidden app.
REFUSAL_HINTS: dict[RefusalReason, str] = {
  "pointer_target": (
    "That point is covered by, or belongs to, a window you cannot act on. "
    "Choose another point or bring the target forward."
  ),
  "keyboard_focus": (
    "Keyboard focus is on a window you cannot see or use. Click inside the target window first."
  ),
  "focus_changed": ("Focus moved during input. Text may be partly entered; check before retrying."),
}

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
    self.reset()

  def reset(self) -> None:
    self._streak = 0
    self._refusals = 0
    self._unchanged = 0
    self._warnings = 0
    self._rejected = 0
    self._recent.clear()

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
