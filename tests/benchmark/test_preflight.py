from pathlib import Path

import pytest

from fsd.approval.store import ApprovalStore, ApprovalStoreError
from fsd.benchmark import runner
from fsd.benchmark.contracts import BenchmarkError
from fsd.benchmark.tasks import task_for, task_manifest
from fsd.platform.base import Capability, MissingPermission, PlatformError
from fsd.platform.fake import FakePlatform
from tests.benchmark.helpers import prepared_desktop


@pytest.mark.parametrize("task_id", ["finder-rename", "finder-move", "textedit-edit-save"])
@pytest.mark.parametrize("require_focus", [False, True])
def test_preflight_returns_the_prepared_task_without_starting_execution(
  tmp_path: Path, task_id: str, require_focus: bool
) -> None:
  root, platform, store = prepared_desktop(tmp_path, task_id)
  original_task = (root / "task.json").read_bytes()
  original_approvals = (tmp_path / "approvals.json").read_bytes()

  manifest, task = runner.preflight(root, platform, store, require_focus=require_focus)

  assert task == task_for(task_id)
  assert manifest == task_manifest(task)
  assert (root / "task.json").read_bytes() == original_task
  assert (tmp_path / "approvals.json").read_bytes() == original_approvals
  assert sorted(path.name for path in root.iterdir()) == ["task.json", "workspace"]
  assert platform.capture_calls == 0
  assert platform.actions == []


def test_focus_is_optional_before_readiness_and_required_afterward(tmp_path: Path) -> None:
  root, platform, store = prepared_desktop(tmp_path, "finder-rename")
  platform.frontmost = "another.app"

  runner.preflight(root, platform, store, require_focus=False)
  with pytest.raises(BenchmarkError, match="foreground"):
    runner.preflight(root, platform, store, require_focus=True)

  assert not (root / ".started").exists()
  assert platform.capture_calls == 0
  assert platform.actions == []


def test_preflight_refreshes_revoked_approval(tmp_path: Path) -> None:
  root, platform, store = prepared_desktop(tmp_path, "finder-rename")
  app_id = task_for("finder-rename").app_id
  ApprovalStore(tmp_path / "approvals.json").block(app_id)
  assert store.is_approved(app_id)

  with pytest.raises(BenchmarkError, match="approved"):
    runner.preflight(root, platform, store, require_focus=True)

  assert not store.is_approved(app_id)
  assert not (root / ".started").exists()
  assert platform.capture_calls == 0


def test_preflight_observes_new_approval_without_granting_it(tmp_path: Path) -> None:
  root, platform, store = prepared_desktop(tmp_path, "finder-rename")
  app_id = task_for("finder-rename").app_id
  store.block(app_id)
  ApprovalStore(tmp_path / "approvals.json").approve(app_id)
  original = (tmp_path / "approvals.json").read_bytes()

  runner.preflight(root, platform, store, require_focus=True)

  assert store.approved() == frozenset({app_id})
  assert (tmp_path / "approvals.json").read_bytes() == original


@pytest.mark.parametrize("remaining", [Capability.DISPLAY_CAPTURE, Capability.WINDOW_OWNER_LOOKUP])
def test_preflight_requires_both_mandatory_capabilities(
  tmp_path: Path, remaining: Capability
) -> None:
  root, platform, store = prepared_desktop(tmp_path, "finder-rename")
  platform.capabilities = frozenset({remaining})

  with pytest.raises(BenchmarkError, match="capture|ownership"):
    runner.preflight(root, platform, store, require_focus=True)

  assert not (root / ".started").exists()
  assert platform.capture_calls == 0


def test_preflight_rejects_missing_permissions(tmp_path: Path) -> None:
  root, _, store = prepared_desktop(tmp_path, "finder-rename")
  platform = FakePlatform(
    frontmost=task_for("finder-rename").app_id,
    missing_permissions=[MissingPermission("Screen Recording", "Enable in System Settings.")],
  )

  with pytest.raises(BenchmarkError, match="permissions"):
    runner.preflight(root, platform, store, require_focus=True)

  assert not (root / ".started").exists()
  assert platform.capture_calls == 0


@pytest.mark.parametrize("name", [".started", "run.json", "result.json", "frames", "events.jsonl"])
@pytest.mark.parametrize("symlink", [False, True])
def test_preflight_refuses_previous_execution_evidence(
  tmp_path: Path, name: str, symlink: bool
) -> None:
  root, platform, store = prepared_desktop(tmp_path, "finder-rename")
  existing = root / name
  target = tmp_path / "missing-target"
  if symlink:
    existing.symlink_to(target)
  else:
    existing.write_bytes(b"existing evidence")
  original_names = sorted(path.name for path in root.iterdir())

  with pytest.raises(BenchmarkError):
    runner.preflight(root, platform, store, require_focus=True)

  assert sorted(path.name for path in root.iterdir()) == original_names
  assert platform.capture_calls == 0
  if symlink:
    assert existing.is_symlink()
    assert not target.exists()
  else:
    assert existing.read_bytes() == b"existing evidence"


def test_preflight_rechecks_files_changed_during_readiness(tmp_path: Path) -> None:
  root, platform, store = prepared_desktop(tmp_path, "finder-rename")
  runner.preflight(root, platform, store, require_focus=False)
  (root / "workspace" / "draft.txt").write_bytes(b"owner edits")

  with pytest.raises(BenchmarkError, match="pristine"):
    runner.preflight(root, platform, store, require_focus=True)

  assert (root / "workspace" / "draft.txt").read_bytes() == b"owner edits"
  assert not (root / ".started").exists()
  assert platform.capture_calls == 0


@pytest.mark.parametrize("failure", ["permissions", "foreground", "approvals"])
def test_preflight_wraps_backend_and_approval_errors(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
  root, platform, store = prepared_desktop(tmp_path, "finder-rename")
  cause = (
    ApprovalStoreError("PRIVATE-DETAIL")
    if failure == "approvals"
    else PlatformError("PRIVATE-DETAIL")
  )

  def fail() -> None:
    raise cause

  if failure == "approvals":
    monkeypatch.setattr(store, "refresh", fail)
  else:
    method = "check_permissions" if failure == "permissions" else "frontmost_app"
    monkeypatch.setattr(platform, method, fail)

  with pytest.raises(BenchmarkError) as caught:
    runner.preflight(root, platform, store, require_focus=True)

  assert caught.value.__cause__ is cause
  assert "PRIVATE-DETAIL" not in str(caught.value)
  assert len(str(caught.value)) <= 200
  assert not (root / ".started").exists()
