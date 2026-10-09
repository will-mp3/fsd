"""Persisted per-app approval configuration."""

import json
import os
from contextlib import suppress
from pathlib import Path
from tempfile import NamedTemporaryFile

_FORMAT_VERSION = 1


class ApprovalStoreError(Exception):
  """Approval data could not be read or written."""


def default_store_path() -> Path:
  override = os.environ.get("FSD_CONFIG_DIR")
  if override:
    return Path(override) / "approvals.json"

  config_home = os.environ.get("XDG_CONFIG_HOME")
  base = Path(config_home) if config_home else Path.home() / ".config"
  return base / "fsd" / "approvals.json"


class ApprovalStore:
  def __init__(self, path: Path) -> None:
    self._path = path
    self._approved = self._load()

  def is_approved(self, bundle_id: str) -> bool:
    return bundle_id in self._approved

  def approved(self) -> frozenset[str]:
    return frozenset(self._approved)

  def approve(self, bundle_id: str) -> None:
    self._save(self._approved | {bundle_id})

  def block(self, bundle_id: str) -> None:
    self._save(self._approved - {bundle_id})

  def _load(self) -> set[str]:
    try:
      data = json.loads(self._path.read_text(encoding="utf-8"))
    except FileNotFoundError:
      return set()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
      raise self._corrupt(str(exc)) from exc

    if not isinstance(data, dict):
      raise self._corrupt("expected a JSON object")

    version = data.get("version")
    if type(version) is not int or version != _FORMAT_VERSION:
      raise self._corrupt(f"expected format version {_FORMAT_VERSION}")

    approved = data.get("approved")
    if not isinstance(approved, list) or not all(isinstance(item, str) for item in approved):
      raise self._corrupt("expected an 'approved' list of bundle identifiers")

    return set(approved)

  def _save(self, approved: set[str]) -> None:
    payload = {"version": _FORMAT_VERSION, "approved": sorted(approved)}
    temporary: Path | None = None

    try:
      self._path.parent.mkdir(parents=True, exist_ok=True)

      # Keeping both files on the same filesystem permits atomic replacement.
      with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=self._path.parent,
        prefix=f".{self._path.name}.",
        suffix=".tmp",
        delete=False,
      ) as file:
        temporary = Path(file.name)
        json.dump(payload, file, indent=2)
        file.write("\n")

      os.replace(temporary, self._path)
      self._approved = approved
    except OSError as exc:
      raise ApprovalStoreError(f"Could not write approvals to {self._path}: {exc}") from exc
    finally:
      if temporary is not None:
        # Cleanup failure most not hide the original save error.
        with suppress(OSError):
          temporary.unlink(missing_ok=True)

  def _corrupt(self, detail: str) -> ApprovalStoreError:
    return ApprovalStoreError(
      f"The approval file {self._path} is unreadable ({detail}). "
      "Fix or delete it; deleting it blocks every app again."
    )
