import pytest

from fsd.platform.base import (
    MANDATORY_CAPABILITIES,
    Capability,
    Frame,
    KeyCombo,
    Rect,
    ScreenPoint,
    WindowInfo,
    parse_combo,
    topmost_owner,
)


def test_mandatory_capabilities_are_capture_and_owner_lookup() -> None:
    assert MANDATORY_CAPABILITIES == {
        Capability.FILTERED_CAPTURE,
        Capability.WINDOW_OWNER_LOOKUP,
    }


def test_rect_contains_is_half_open() -> None:
    rect = Rect(10, 20, 100, 50)
    assert rect.contains(ScreenPoint(10, 20))
    assert rect.contains(ScreenPoint(109.9, 69.9))
    assert not rect.contains(ScreenPoint(110, 20))
    assert not rect.contains(ScreenPoint(10, 70))
    assert not rect.contains(ScreenPoint(9.9, 20))


def test_frame_maps_normalised_coordinates_through_display_scaling() -> None:
    frame = Frame(png=b"", width=3024, height=1964, screen_rect=Rect(0, 0, 1512, 982))
    assert frame.to_screen(0.5, 0.5) == ScreenPoint(756, 491)
    assert frame.to_screen(0, 0) == ScreenPoint(0, 0)


def test_frame_mapping_honours_screen_origin() -> None:
    frame = Frame(png=b"", width=100, height=100, screen_rect=Rect(200, 50, 400, 300))
    assert frame.to_screen(0.25, 1.0) == ScreenPoint(300, 350)


@pytest.mark.parametrize("nx, ny", [(-0.01, 0.5), (0.5, 1.01)])
def test_frame_mapping_rejects_coordinates_outside_the_frame(nx: float, ny: float) -> None:
    frame = Frame(png=b"", width=100, height=100, screen_rect=Rect(0, 0, 100, 100))
    with pytest.raises(ValueError, match="outside the frame"):
        frame.to_screen(nx, ny)


def test_parse_combo_splits_modifiers_from_key() -> None:
    assert parse_combo("Cmd+Shift+A") == KeyCombo(frozenset({"cmd", "shift"}), "a")
    assert parse_combo("return") == KeyCombo(frozenset(), "return")


@pytest.mark.parametrize("combo", ["", "cmd+", "cmd+shift", "a+b", "hyper+a"])
def test_parse_combo_rejects_malformed_input(combo: str) -> None:
    with pytest.raises(ValueError):
        parse_combo(combo)


def test_topmost_owner_returns_first_window_containing_the_point() -> None:
    windows = [
        WindowInfo("com.example.top", Rect(0, 0, 100, 100), 0),
        WindowInfo("com.example.under", Rect(0, 0, 500, 500), 0),
    ]
    assert topmost_owner(windows, ScreenPoint(50, 50)) == "com.example.top"
    assert topmost_owner(windows, ScreenPoint(200, 200)) == "com.example.under"


def test_topmost_owner_is_none_where_no_window_exists() -> None:
    windows = [WindowInfo("com.example.app", Rect(0, 0, 100, 100), 0)]
    assert topmost_owner(windows, ScreenPoint(900, 900)) is None
