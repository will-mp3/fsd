from pathlib import Path

from fsd.archive import atomic_write
from fsd.benchmark.contracts import BenchmarkError, RunManifest, TaskManifest, TaskSpec
from fsd.benchmark.fixtures import ArtifactMismatch, create_workspace, read_regular
from fsd.benchmark.tasks import task_for, task_manifest

MAX_JSON_BYTES = 1024 * 1024


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


def load_task(root: Path) -> tuple[TaskManifest, TaskSpec]:
  try:
    content = read_regular(root, "task.json", MAX_JSON_BYTES)
  except (ArtifactMismatch, OSError) as exc:
    raise BenchmarkError("Could not read the prepared task manifest.") from exc

  if content is None:
    raise BenchmarkError("The trial has no prepared task manifest.")
  if len(content) > MAX_JSON_BYTES:
    raise BenchmarkError("The prepared task manifest exceeds the 1 MiB limit.")

  try:
    manifest = TaskManifest.model_validate_json(content)
  except ValueError as exc:
    raise BenchmarkError("Invalid or unsupported prepared task manifest.") from exc

  try:
    task = task_for(manifest.task_id)
  except BenchmarkError as exc:
    raise BenchmarkError("The prepared task refers to an unsupported benchmark task.") from exc

  if manifest != task_manifest(task):
    raise BenchmarkError("The prepared task does not match the built-in benchmark definition.")

  return manifest, task


class TrialStorage:
  def __init__(self, root: Path) -> None:
    self._root = root
    self._manifest: RunManifest | None = None

  def start(self, manifest: RunManifest) -> None:
    if self._manifest is not None:
      raise BenchmarkError("This storage instance has already started a trial.")

    prepared, _ = load_task(self._root)
    if manifest.task != prepared:
      raise BenchmarkError("The run manifest does not match the prepared task.")

    try:
      content = manifest.model_dump_json(indent=2).encode("utf-8") + b"\n"

      for name in ("run.json", "result.json", "frames", "events.jsonl"):
        path = self._root / name
        if path.exists() or path.is_symlink():
          raise BenchmarkError("The trial already contains execution artifacts.")

      # The permanent claim prevents reruns even if later publication fails
      with (self._root / ".started").open("x", encoding="utf-8") as stream:
        stream.write(manifest.trial_id + "\n")

      with (self._root / "events.jsonl").open("x", encoding="utf-8"):
        pass

      atomic_write(self._root / "run.json", content)
    except FileExistsError as exc:
      raise BenchmarkError(
        "The trial has already been claimed or contains execution artifacts."
      ) from exc
    except (OSError, ValueError) as exc:
      raise BenchmarkError(
        "Could not start the benchmark trial; any partial files were preserved."
      ) from exc

    self._manifest = manifest
