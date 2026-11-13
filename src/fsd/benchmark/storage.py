from pathlib import Path

from fsd.archive import atomic_write
from fsd.benchmark.contracts import BenchmarkError, TaskManifest
from fsd.benchmark.fixtures import create_workspace
from fsd.benchmark.tasks import task_for, task_manifest


def prepare_trial(root: Path, task_id: str) -> TaskManifest:
  task = task_for(task_id)
  manifest = task_manifest(task)
  content = manifest.model_dump_json(indent=2).encode("utf-8") + b"\n"

  try:
    if root.is_symlink():
      raise BenchmarkError("The trial path must not be a symlink.")
    if not root.parent.is_dir():
      raise BenchmarkError("The trial parent directory must already exist.")
    root.mkdir()
  except FileExistsError as exc:
    raise BenchmarkError(
      "The benchmark trial already exists. Choose a fresh trial directory."
    ) from exc
  except OSError as exc:
    raise BenchmarkError("Could not create the benchmark trial directory.") from exc

  try:
    create_workspace(root / "workspace", task)
    atomic_write(root / "task.json", content)
  except OSError as exc:
    raise BenchmarkError("Could not prepare trial files; the partial trial was preserved.") from exc

  return manifest
