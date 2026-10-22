"""Visible-change detection using small grayscale thumbnails.

Thresholds are starting points for calibration using stage 2 traces.
"""

import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from fsd.platform.base import Frame

THUMBNAIL_WIDTH = 256
PIXEL_THRESHOLD = 24
CHANGED_FRACTION = 0.0002


@dataclass(frozen=True)
class Thumbnail:
  source: tuple[int, int]
  pixels: bytes | None


def thumbnail(frame: Frame) -> Thumbnail:
  source = (frame.width, frame.height)
  try:
    with Image.open(io.BytesIO(frame.png)) as image:
      gray = image.convert("L")
  except (UnidentifiedImageError, OSError, ValueError):
    return Thumbnail(source, None)

  height = max(1, round(gray.height * THUMBNAIL_WIDTH / gray.width))
  small = gray.resize((THUMBNAIL_WIDTH, height), Image.Resampling.BOX)
  return Thumbnail(source, small.tobytes())


def changed(before: Thumbnail, after: Thumbnail) -> bool:
  if before.source != after.source or before.pixels is None or after.pixels is None:
    return True
  if len(before.pixels) != len(after.pixels):
    return True

  moved = sum(
    1
    for old, new in zip(before.pixels, after.pixels, strict=True)
    if abs(old - new) > PIXEL_THRESHOLD
  )
  return moved >= CHANGED_FRACTION * len(before.pixels)
