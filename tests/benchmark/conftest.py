from pathlib import Path

import pytest

from fsd.benchmark import storage
from tests.benchmark.helpers import example_run


@pytest.fixture
def started_trial(tmp_path: Path) -> tuple[Path, storage.TrialStorage]:
  root = tmp_path / "trial"
  storage.prepare_trial(root, "finder-rename")
  trial = storage.TrialStorage(root)
  trial.start(example_run())
  return root, trial
