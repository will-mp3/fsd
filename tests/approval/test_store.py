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
