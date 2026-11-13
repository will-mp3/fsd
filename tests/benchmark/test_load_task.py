import json
from pathlib import Path

import pytest

from fsd.benchmark import storage
from fsd.benchmark.contracts import BenchmarkError
from fsd.benchmark.tasks import task_for


@pytest.mark.parametrize("task_id", ["textedit-edit-save", "finder-rename", "finder-move"])
def test_load_task_returns_the_canonical_task_without_rewriting_it(
  tmp_path: Path,
  task_id: str,
) -> None:
  root = tmp_path / "trial"
  prepared = storage.prepare_trial(root, task_id)
  original = (root / "task.json").read_bytes()

  manifest, task = storage.load_task(root)

  assert manifest == prepared
  assert task == task_for(task_id)
  assert (root / "task.json").read_bytes() == original


@pytest.mark.parametrize(
  ("field", "value"),
  [
    ("schema_version", 2),
    ("schema_version", True),
    ("task_version", 2),
    ("task_version", True),
    ("setup_protocol", 2),
    ("prompt", "Perform a different task."),
    ("app_id", "another.app"),
    ("initial_sha256", {}),
    ("directories", ["elsewhere"]),
    ("task_id", "finder-move"),
    ("task_id", "unknown-" + "x" * 5000),
    ("unexpected", "extra data"),
  ],
  ids=(
    "schema-version",
    "boolean-schema",
    "task-version",
    "boolean-task-version",
    "setup-version",
    "prompt",
    "app",
    "hashes",
    "paths",
    "other-known-task",
    "unknown-task",
    "extra-field",
  ),
)
def test_load_task_rejects_edited_definitions_without_repairing_them(
  tmp_path: Path,
  field: str,
  value: object,
) -> None:
  root = tmp_path / "trial"
  storage.prepare_trial(root, "finder-rename")
  task_path = root / "task.json"
  payload: dict[str, object] = json.loads(task_path.read_bytes())
  payload[field] = value
  changed = json.dumps(payload).encode("utf-8")
  task_path.write_bytes(changed)

  with pytest.raises(BenchmarkError) as caught:
    storage.load_task(root)

  assert len(str(caught.value)) <= 200
  assert task_path.read_bytes() == changed


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink", "oversized", "invalid-json"])
def test_load_task_rejects_unreadable_or_unsupported_manifest_files(
  tmp_path: Path,
  kind: str,
) -> None:
  root = tmp_path / "trial"
  storage.prepare_trial(root, "finder-rename")
  task_path = root / "task.json"
  original = task_path.read_bytes()
  if kind == "missing":
    task_path.unlink()
  elif kind == "directory":
    task_path.unlink()
    task_path.mkdir()
  elif kind == "symlink":
    target = tmp_path / "original.json"
    target.write_bytes(original)
    task_path.unlink()
    task_path.symlink_to(target)
  elif kind == "oversized":
    task_path.write_bytes(original + b" " * (1024 * 1024 + 1 - len(original)))
  else:
    task_path.write_bytes(b"{broken-json")

  with pytest.raises(BenchmarkError) as caught:
    storage.load_task(root)

  assert len(str(caught.value)) <= 200


def test_load_task_rejects_a_symlinked_trial_directory(tmp_path: Path) -> None:
  target = tmp_path / "original"
  storage.prepare_trial(target, "finder-rename")
  alias = tmp_path / "alias"
  alias.symlink_to(target, target_is_directory=True)

  with pytest.raises(BenchmarkError):
    storage.load_task(alias)

  assert alias.is_symlink()
