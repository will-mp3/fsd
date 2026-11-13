from pathlib import Path

from fsd.benchmark.contracts import TaskManifest
from fsd.benchmark.tasks import task_for, task_manifest


def prepare_trial(root: Path, task_id: str) -> TaskManifest:
  return task_manifest(task_for(task_id))