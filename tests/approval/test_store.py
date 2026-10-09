import json
import os
import re
from pathlib import Path

import pytest

from fsd.approval.store import ApprovalStore, ApprovalStoreError, default_store_path


def test_default_path_honours_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
  monkeypatch.setenv("FSD_CONFIG_DIR", str(tmp_path / "override"))
  monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
  assert default_store_path() == tmp_path / "override" / "approvals.json"

  monkeypatch.delenv("FSD_CONFIG_DIR")
  assert default_store_path() == tmp_path / "xdg" / "fsd" / "approvals.json"

  monkeypatch.delenv("XDG_CONFIG_HOME")
  assert default_store_path() == Path.home() / ".config" / "fsd" / "approvals.json"


def test_missing_file_blocks_every_app_without_creating_a_file(tmp_path: Path) -> None:
  path = tmp_path / "approvals.json"
  store = ApprovalStore(path)
  assert not store.is_approved("com.apple.TextEdit")
  assert store.approved() == frozenset()
  assert not path.exists()


def test_loading_approvals_only_allows_listed_apps(tmp_path: Path) -> None:
  path = tmp_path / "approvals.json"
  path.write_text('{"version": 1, "approved": ["com.apple.TextEdit"]}', encoding="utf-8")
  store = ApprovalStore(path)
  assert store.is_approved("com.apple.TextEdit")
  assert not store.is_approved("com.apple.Notes")
  assert store.approved() == frozenset({"com.apple.TextEdit"})


@pytest.mark.parametrize(
  "content",
  [
    "not json",
    "[]",
    '{"version": 1}',
    '{"version": 1, "approved": [1, 2]}',
    '{"version": 1, "approved": "com.apple.TextEdit"}',
    '{"approved": []}',
    '{"version": 2, "approved": []}',
    '{"version": true, "approved": []}',
    '{"version": 1.0, "approved": []}',
  ],
)
def test_invalid_file_is_reported_without_overwriting_it(tmp_path: Path, content: str) -> None:
  path = tmp_path / "approvals.json"
  path.write_text(content, encoding="utf-8")
  with pytest.raises(ApprovalStoreError, match=re.escape(str(path))):
    ApprovalStore(path)
  assert path.read_text(encoding="utf-8") == content


def test_invalid_utf8_is_reported_as_a_store_error(tmp_path: Path) -> None:
  path = tmp_path / "approvals.json"
  path.write_bytes(b"\xff")
  with pytest.raises(ApprovalStoreError, match=re.escape(str(path))):
    ApprovalStore(path)


def test_unreadable_path_is_reported_as_a_store_error(tmp_path: Path) -> None:
  path = tmp_path / "approvals.json"
  path.mkdir()
  with pytest.raises(ApprovalStoreError, match=re.escape(str(path))):
    ApprovalStore(path)


def test_approval_persists_between_runs(tmp_path: Path) -> None:
  path = tmp_path / "nested" / "approvals.json"
  store = ApprovalStore(path)
  snapshot = store.approved()
  store.approve("com.apple.TextEdit")
  assert store.is_approved("com.apple.TextEdit")
  assert ApprovalStore(path).is_approved("com.apple.TextEdit")
  assert snapshot == frozenset()


def test_blocking_persists_and_preserves_other_approvals(tmp_path: Path) -> None:
  path = tmp_path / "approvals.json"
  store = ApprovalStore(path)
  store.approve("com.apple.TextEdit")
  store.approve("com.apple.Notes")
  store.block("com.apple.TextEdit")
  assert store.approved() == frozenset({"com.apple.Notes"})
  assert ApprovalStore(path).approved() == frozenset({"com.apple.Notes"})


def test_blocking_an_unknown_app_is_harmless(tmp_path: Path) -> None:
  path = tmp_path / "approvals.json"
  store = ApprovalStore(path)
  store.block("com.apple.TextEdit")
  assert store.approved() == frozenset()
  assert ApprovalStore(path).approved() == frozenset()


def test_saved_format_is_versioned_sorted_and_has_no_duplicates(tmp_path: Path) -> None:
  path = tmp_path / "approvals.json"
  store = ApprovalStore(path)
  store.approve("com.b")
  store.approve("com.a")
  store.approve("com.a")
  assert json.loads(path.read_text(encoding="utf-8")) == {
    "version": 1,
    "approved": ["com.a", "com.b"],
  }
  assert set(tmp_path.iterdir()) == {path}


@pytest.mark.parametrize("operation", ["approve", "block"])
def test_failed_replace_preserves_memory_and_disk(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
  path = tmp_path / "approvals.json"
  original = '{"version": 1, "approved": ["com.apple.TextEdit"]}'
  path.write_text(original, encoding="utf-8")
  store = ApprovalStore(path)

  def fail_replace(source: Path, destination: Path) -> None:
    raise OSError("simulated replacement failure")

  monkeypatch.setattr(os, "replace", fail_replace)
  with pytest.raises(ApprovalStoreError, match=re.escape(str(path))):
    if operation == "approve":
      store.approve("com.apple.Notes")
    else:
      store.block("com.apple.TextEdit")

  assert store.approved() == frozenset({"com.apple.TextEdit"})
  assert path.read_text(encoding="utf-8") == original
  assert set(tmp_path.iterdir()) == {path}


def test_failed_directory_creation_does_not_grant_approval(tmp_path: Path) -> None:
  parent = tmp_path / "config"
  path = parent / "approvals.json"
  store = ApprovalStore(path)
  parent.write_text("occupied", encoding="utf-8")
  with pytest.raises(ApprovalStoreError, match=re.escape(str(path))):
    store.approve("com.apple.TextEdit")
  assert store.approved() == frozenset()
  assert parent.read_text(encoding="utf-8") == "occupied"
