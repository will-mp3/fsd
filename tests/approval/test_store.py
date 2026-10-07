from pathlib import Path

import pytest

from fsd.approval.store import default_store_path


def test_default_path_honours_environment(
  monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
  monkeypatch.setenv("FSD_CONFIG_DIR", str(tmp_path / "override"))
  monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
  assert default_store_path() == tmp_path / "override" / "approvals.json"

  monkeypatch.delenv("FSD_CONFIG_DIR")
  assert default_store_path() == tmp_path / "xdg" / "fsd" / "approvals.json"

  monkeypatch.delenv("XDG_CONFIG_HOME")
  assert default_store_path() == Path.home() / ".config" / "fsd" / "approvals.json"
