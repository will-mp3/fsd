import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fsd.operator.contracts import Snapshot
from fsd.operator.records import StepRecord
from fsd.platform.base import Frame, Rect


def snapshot() -> Snapshot:
  return StepRecord("run", 0, Frame(b"png", 10, 10, Rect(0, 0, 10, 10)), frozenset()).snapshot(
    "interrupted", "", ""
  )


def test_archive_publishes_png_before_json_with_no_temporary_files(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  from fsd import archive

  replace = archive.os.replace
  targets: list[str] = []

  def observe(source: str | Path, target: str | Path) -> None:
    target = Path(target)
    if target.suffix == ".json":
      assert (target.parent / "0.png").read_bytes() == b"png"
      assert not target.exists()
    targets.append(target.name)
    replace(source, target)

  monkeypatch.setattr(archive.os, "replace", observe)
  archive.save_snapshot(tmp_path, snapshot())
  assert targets == ["0.png", "0.json"]
  folder = tmp_path / "run"
  assert sorted(p.name for p in folder.iterdir()) == ["0.json", "0.png"]
  assert json.loads((folder / "0.json").read_text()) == snapshot().record


@pytest.mark.parametrize("suffix", [".png", ".json"])
def test_failed_replacement_never_publishes_json_and_cleans_temporaries(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
  from fsd import archive

  replace = archive.os.replace

  def fail(source: str | Path, target: str | Path) -> None:
    if Path(target).suffix == suffix:
      raise OSError("replacement failed")
    replace(source, target)

  monkeypatch.setattr(archive.os, "replace", fail)
  with pytest.raises(OSError, match="replacement failed"):
    archive.save_snapshot(tmp_path, snapshot())
  folder = tmp_path / "run"
  assert not (folder / "0.json").exists()
  assert sorted(p.name for p in folder.iterdir()) == (["0.png"] if suffix == ".json" else [])


def test_failed_atomic_replacement_preserves_existing_file(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  from fsd import archive

  target = tmp_path / "artifact"
  target.write_bytes(b"old")

  def fail(source: str | Path, destination: str | Path) -> None:
    raise OSError("replace failed")

  monkeypatch.setattr(archive.os, "replace", fail)
  with pytest.raises(OSError, match="replace failed"):
    archive.atomic_write(target, b"new")
  assert target.read_bytes() == b"old"
  assert list(tmp_path.iterdir()) == [target]


def test_completed_pair_cannot_be_replaced_with_a_partial_retry(tmp_path: Path) -> None:
  from fsd import archive

  original = snapshot()
  archive.save_snapshot(tmp_path, original)
  with pytest.raises(FileExistsError):
    archive.save_snapshot(tmp_path, Snapshot("run", 0, b"changed", original.record))
  assert (tmp_path / "run" / "0.png").read_bytes() == b"png"
  assert json.loads((tmp_path / "run" / "0.json").read_text()) == original.record


@pytest.mark.parametrize("suffix", [".png", ".json"])
@pytest.mark.parametrize("operation", ["write", "close"])
def test_partial_write_or_close_failure_cleans_temp_without_publishing_a_pair(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str, operation: str
) -> None:
  from fsd import archive

  temporary_file = archive.NamedTemporaryFile

  @contextmanager
  def failing_file(**kwargs: Any) -> Iterator[Any]:
    with temporary_file(**kwargs) as stream:
      if f"0{suffix}" not in kwargs["prefix"]:
        yield stream
        return

      def partial_write(data: bytes) -> int:
        if operation == "write":
          stream.write(data[:2])
          raise OSError("partial write failed")
        return stream.write(data)

      yield SimpleNamespace(name=stream.name, write=partial_write)
      if operation == "close":
        raise OSError("close failed")

  monkeypatch.setattr(archive, "NamedTemporaryFile", failing_file)
  with pytest.raises(OSError, match="failed"):
    archive.save_snapshot(tmp_path, snapshot())
  folder = tmp_path / "run"
  assert sorted(p.name for p in folder.iterdir()) == (["0.png"] if suffix == ".json" else [])
