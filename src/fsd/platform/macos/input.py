"""Keyboard and mouse input helpers for macOS."""

import time

import Quartz

from fsd.platform.base import ScreenPoint, parse_combo

_EVENT_GAP_SECONDS = 0.01

# Shortcuts use ANSI key positions; literal text will use Unicode.
# fmt: off
KEYCODES: dict[str, int] = {
  "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
  "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
  "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25, "7": 26,
  "-": 27, "8": 28, "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35,
  "return": 36, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43,
  "/": 44, "n": 45, "m": 46, ".": 47, "tab": 48, "space": 49, "`": 50,
  "delete": 51, "escape": 53, "home": 115, "pageup": 116, "forwarddelete": 117,
  "end": 119, "pagedown": 121, "left": 123, "right": 124, "down": 125, "up": 126,
}
# fmt: on

_MODIFIER_FLAGS: dict[str, int] = {
  "cmd": Quartz.kCGEventFlagMaskCommand,
  "shift": Quartz.kCGEventFlagMaskShift,
  "alt": Quartz.kCGEventFlagMaskAlternate,
  "ctrl": Quartz.kCGEventFlagMaskControl,
}


def utf16_length(text: str) -> int:
  return len(text.encode("utf-16-le")) // 2


def _post(event: object) -> None:
  Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
  # Pace synthetic events so applications have time to process them.
  time.sleep(_EVENT_GAP_SECONDS)


def _keyboard_events(keycode: int) -> tuple[object, object]:
  # Create the release event before sending the corresponding press.
  down = Quartz.CGEventCreateKeyboardEvent(None, keycode, True)
  up = Quartz.CGEventCreateKeyboardEvent(None, keycode, False)
  if down is None or up is None:
    raise RuntimeError("Could not create keyboard event.")
  return down, up


def press_keys(combo: str) -> None:
  parsed = parse_combo(combo)
  if parsed.key not in KEYCODES:
    raise ValueError(f"Unknown key '{parsed.key}' in key combination {combo!r}.")

  flags = 0
  for modifier in parsed.modifiers:
    flags |= _MODIFIER_FLAGS[modifier]

  events = _keyboard_events(KEYCODES[parsed.key])
  for event in events:
    Quartz.CGEventSetFlags(event, flags)
    _post(event)


def type_text(text: str) -> None:
  for character in text:
    events = _keyboard_events(0)
    length = utf16_length(character)

    for event in events:
      # Literal text must not inherit shortcut modifiers
      Quartz.CGEventSetFlags(event, 0)
      Quartz.CGEventKeyboardSetUnicodeString(event, length, character)

    for event in events:
      _post(event)


def _mouse_event(event_type: int, point: ScreenPoint) -> object:
  event: object | None = Quartz.CGEventCreateMouseEvent(
    None, event_type, (point.x, point.y), Quartz.kCGMouseButtonLeft
  )
  if event is None:
    raise RuntimeError("Could not create mouse event.")

  # A plain click must not inherit modifiers such as Control.
  Quartz.CGEventSetFlags(event, 0)
  return event


def click(point: ScreenPoint) -> None:
  # Prepare the full action before moving or pressing the mouse.
  events = (
    _mouse_event(Quartz.kCGEventMouseMoved, point),
    _mouse_event(Quartz.kCGEventLeftMouseDown, point),
    _mouse_event(Quartz.kCGEventLeftMouseUp, point),
  )

  # Both button events belong to the same single click.
  for event in events[1:]:
    Quartz.CGEventSetIntegerValueField(event, Quartz.kCGMouseEventClickState, 1)

  for event in events:
    _post(event)


def scroll(point: ScreenPoint, dx: int, dy: int) -> None:
  move = _mouse_event(Quartz.kCGEventMouseMoved, point)
  event = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 2, dy, dx)
  if event is None:
    raise RuntimeError("Could not create scroll event.")

  Quartz.CGEventSetFlags(event, 0)
  Quartz.CGEventSetLocation(event, (point.x, point.y))

  # Scroll at the same point whose owner the action gate checked.
  _post(move)
  _post(event)
