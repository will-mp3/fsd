import io

import pytest
from PIL import Image, ImageDraw

from fsd.operator.frames import THUMBNAIL_WIDTH, changed, thumbnail
from fsd.platform.base import Frame, Rect

SIZE = (2560, 1600)
CARET = (1000, 800, 1001, 831)
CHECKBOX = (1200, 600, 1239, 639)
DIALOG = (800, 500, 1399, 899)


def screen(*boxes: tuple[int, int, int, int], size: tuple[int, int] = SIZE) -> Frame:
  image = Image.new("RGB", size, "white")
  draw = ImageDraw.Draw(image)
  for box in boxes:
    draw.rectangle(box, fill="black")
  buffer = io.BytesIO()
  image.save(buffer, format="PNG")
  return Frame(buffer.getvalue(), size[0], size[1], Rect(0, 0, size[0] / 2, size[1] / 2))


def test_thumbnail_is_fixed_width_and_keeps_aspect_ratio() -> None:
  # Comparison counts depend on this size; a change here recalibrates every threshold.
  small = thumbnail(screen())
  assert small.source == SIZE
  assert small.pixels is not None
  assert len(small.pixels) == THUMBNAIL_WIDTH * 160


def test_identical_frames_are_unchanged() -> None:
  # Baseline: the detector must not invent change.
  assert not changed(thumbnail(screen()), thumbnail(screen()))


def test_caret_blink_is_not_a_visible_change() -> None:
  # The false alarm that exact byte comparison suffers from.
  assert not changed(thumbnail(screen()), thumbnail(screen(CARET)))


def test_checkbox_toggle_is_a_visible_change() -> None:
  # The smallest real outcome the comparison must still catch.
  assert changed(thumbnail(screen()), thumbnail(screen(CHECKBOX)))


def test_dialog_is_a_visible_change() -> None:
  assert changed(thumbnail(screen()), thumbnail(screen(DIALOG)))


def test_different_dimensions_always_differ() -> None:
  # A display or filter change must never look identical.
  assert changed(thumbnail(screen()), thumbnail(screen(size=(1280, 800))))


@pytest.mark.parametrize("order", ["before", "after"])
def test_undecodable_frame_counts_as_changed(order: str) -> None:
  # A bad frame must never create a false stuck signal.
  good = thumbnail(screen())
  bad = thumbnail(Frame(b"not a png", *SIZE, Rect(0, 0, 1280, 800)))
  assert bad.pixels is None
  assert changed(bad, good) if order == "before" else changed(good, bad)
