"""Persist a captured step; the JSON sidecar marks a completed artifact pair."""

import json
import os
from contextlib import suppress
from pathlib import Path
from tempfile import NamedTemporaryFile

from fsd.operator.contracts import Snapshot


def _atomic_write(target: Path, content: bytes) -> None:
  temporary: Path | None = None
  try:
    with NamedTemporaryFile(
      dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False
    ) as stream:
      temporary = Path(stream.name)
      stream.write(content)
    os.replace(temporary, target)
  finally:
    if temporary is not None:
      # Cleanup must not replace the original write/replace failure.
      with suppress(OSError):
        temporary.unlink(missing_ok=True)


def save_snapshot(root: Path, snapshot: Snapshot) -> None:
  folder = root / snapshot.run_id
  folder.mkdir(parents=True, exist_ok=True)
  metadata = folder / f"{snapshot.step}.json"
  if metadata.exists():
    # Reusing a completed identity could pair old JSON with a replacement PNG.
    raise FileExistsError("This captured step has already been archived.")
  content = json.dumps(snapshot.record, allow_nan=False, ensure_ascii=False).encode("utf-8") + b"\n"
  _atomic_write(folder / f"{snapshot.step}.png", snapshot.png)
  _atomic_write(metadata, content)
