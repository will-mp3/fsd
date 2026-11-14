from pathlib import Path

from fsd.approval.store import ApprovalStore, ApprovalStoreError
from fsd.benchmark.contracts import BenchmarkError, TaskManifest, TaskSpec
from fsd.benchmark.fixtures import validate_pristine
from fsd.benchmark.storage import load_task
from fsd.platform.base import MANDATORY_CAPABILITIES, Platform, PlatformError


def preflight(
  root: Path,
  platform: Platform,
  store: ApprovalStore,
  *,
  require_focus: bool,
) -> tuple[TaskManifest, TaskSpec]:
  try:
    manifest, task = load_task(root)
    validate_pristine(root / "workspace", task)

    for name in (".started", "run.json", "result.json", "frames", "events.jsonl"):
      try:
        (root / name).lstat()
      except FileNotFoundError:
        continue
      raise BenchmarkError("The trial already contains execution artifacts.")

    if not MANDATORY_CAPABILITIES.issubset(platform.capabilities):
      raise BenchmarkError("The platform must support display capture and window ownership lookup.")

    if platform.check_permissions():
      raise BenchmarkError("Required platform permissions are missing.")

    store.refresh()
    if not store.is_approved(task.app_id):
      raise BenchmarkError("The target app must already be approved for input.")

    if require_focus and platform.frontmost_app() != task.app_id:
      raise BenchmarkError("The target app must be the foreground app.")

  except ApprovalStoreError as exc:
    raise BenchmarkError("Could not refresh input approvals.") from exc
  except PlatformError as exc:
    raise BenchmarkError("Could not check platform readiness.") from exc
  except OSError as exc:
    raise BenchmarkError("Could not inspect the prepared trial.") from exc

  return manifest, task
