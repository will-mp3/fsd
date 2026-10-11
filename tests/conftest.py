import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
  if os.environ.get("FSD_LIVE") == "1":
    return
  skip = pytest.mark.skip(reason="set FSD_LIVE=1 to run tests against the real desktop")
  for item in items:
    if "live" in item.keywords:
      item.add_marker(skip)
