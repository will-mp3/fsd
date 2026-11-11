from fsd.benchmark import contracts
from fsd.platform.base import Rect


def test_geometry_preserves_distinct_pixel_and_input_dimensions_in_json() -> None:
  geometry = contracts.FrameGeometry.model_validate_json(
    '{"width": 2560, "height": 1600, '
    '"screen_rect": {"x": 0.0, "y": 0.0, "width": 1280.0, "height": 800.0}}'
  )

  restored = contracts.FrameGeometry.model_validate_json(geometry.model_dump_json())

  assert restored.width == 2560
  assert restored.height == 1600
  assert restored.screen_rect == Rect(0.0, 0.0, 1280.0, 800.0)
