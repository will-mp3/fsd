from pathlib import Path

import pytest

from fsd.benchmark import storage
from fsd.benchmark.contracts import BenchmarkError


def test_prepare_never_overwrites_a_trial(tmp_path: Path) -> None:
  root = tmp_path / "trial"
  storage.prepare_trial(root, "finder-rename")
  task_path = root / "task.json"
  assert task_path.is_file()
  original = task_path.read_bytes()

  with pytest.raises(BenchmarkError, match="already exists"):
    storage.prepare_trial(root, "finder-move")

  assert task_path.read_bytes() == original
  assert (root / "workspace" / "draft.txt").read_bytes() == b"Benchmark fixture.\n"
