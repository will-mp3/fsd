"""Persisted per-app approval configuration."""

import os
from pathlib import Path


def default_store_path() -> Path:
  override = os.environ.get("FSD_CONFIG_DIR")
  if override:
    return Path(override) / "approvals.json"

  config_home = os.environ.get("XDG_CONFIG_HOME")
  base = Path(config_home) if config_home else Path.home() / ".config"
  return base / "fsd" / "approvals.json"
