# Adapted from DataLab's backend/src/datalab/config.py (default_data_dir) at 6b6fdca.
"""Where UM-Codex keeps its own files: saved setups, and each launch's
generated config while it runs.

- macOS: ~/Library/Application Support/UM-Codex
- Windows: %LOCALAPPDATA%\\UM-Codex
- elsewhere (tests, CI): $XDG_DATA_HOME/um-codex

`UMCODEX_DATA_DIR` overrides it (for tests).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def default_data_dir(platform: str = sys.platform) -> Path:
    if platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "UM-Codex"
    if platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "UM-Codex"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "um-codex"


def data_dir() -> Path:
    return Path(os.environ.get("UMCODEX_DATA_DIR") or default_data_dir())
