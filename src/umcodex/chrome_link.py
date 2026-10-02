"""The person's Chrome connection, kept from UM-Codex's copies of the Codex app.

The Codex app's bundled Chrome plugin connects the ChatGPT browser extension
to the app through a native messaging host. Whenever the app installs or
reconciles that plugin, which it does at start (and again when its plugin
cache changes), it writes (26.928.40906's bootstrap, `DF` → `JF` and `AF`):
- the host's manifest, `com.openai.codexextension.json`, for the whole OS
  user: on a Mac in `~/Library/Application Support/Google/Chrome/
  NativeMessagingHosts/` (and Chromium's and Chrome for Testing's), pointing
  at the extension host inside *that copy's* plugin folder; on Windows in
  `%LOCALAPPDATA%\\OpenAI\\extension\\` (the registry key
  `HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\com.openai.codexextension`
  names that file, always the same one), pointing at the app package's own
  host (`codex-chrome-native-host.exe`), the same for every copy;
- an entry, per install (a hash of the host name, the app's resources and
  CODEX_HOME), in a shared registry, `chrome-native-hosts-v2.json`, in
  `~/Library/Application Support/OpenAI/Codex/` (Mac) or
  `%LOCALAPPDATA%\\OpenAI\\Codex\\` (Windows), with the copy's CODEX_HOME.

It does so for a plugin that's installed even when config.toml disables it
(the reconcile looks at `installed`, not `enabled`), and installs it when
the ChatGPT extension is in Chrome. So turning Chrome off in a copy's
config isn't enough: on a Mac every UM-Codex copy took the person's Chrome
connection over when it started (found on the maintainer's Mac, 2026-10-02).

So around each copy: `remember` the manifests before the copy opens (in the
copy's folder, `chrome-manifests.json`, kept until the final restore, never
overwritten by a later start, so a crash loses nothing); `restore` puts back
a manifest that now leads into UM-Codex's folder (or removes it if there
was none) while the copy runs (each poll) and when it's done, and leaves one
that leads elsewhere (the person's own app wrote it since); the copy's
entries leave the shared registry. On Windows the manifest never leads into
UM-Codex's folder, so only the registry entries are taken out.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

HOST_NAME = "com.openai.codexextension"
BACKUP = "chrome-manifests.json"
MAC_FOLDERS = ("Google/Chrome", "Chromium", "Google/ChromeForTesting", "Google/Chrome for Testing")


def _local_appdata(home: Path) -> Path:
    found = os.environ.get("LOCALAPPDATA")
    return Path(found) if found else home / "AppData" / "Local"


def manifests(home: Path | None = None, platform: str = sys.platform) -> list[Path]:
    """Where the app writes the extension's native host manifest."""
    home = home or Path.home()
    if platform == "win32":
        return [_local_appdata(home) / "OpenAI" / "extension" / f"{HOST_NAME}.json"]
    support = home / "Library" / "Application Support"
    return [support / f / "NativeMessagingHosts" / f"{HOST_NAME}.json" for f in MAC_FOLDERS]


def registry(home: Path | None = None, platform: str = sys.platform) -> Path:
    """The app's shared registry of Chrome native hosts (one entry per install)."""
    home = home or Path.home()
    if platform == "win32":
        return _local_appdata(home) / "OpenAI" / "Codex" / "chrome-native-hosts-v2.json"
    return home / "Library" / "Application Support" / "OpenAI" / "Codex" / "chrome-native-hosts-v2.json"


def inside(path: Path | str, folder: Path) -> bool:
    """Whether `path` is `folder` or in it, letter case and separators aside
    (a Mac's and Windows' disks usually ignore case)."""

    def norm(p: Path | str) -> str:
        return str(p).replace("\\", "/").casefold().rstrip("/")

    a, b = norm(path), norm(folder)
    return a == b or a.startswith(b + "/")


def _resolved(path: str) -> Path:
    try:
        return Path(path).resolve()
    except (OSError, RuntimeError):
        return Path(path)


def leads_into(manifest: Path, root: Path) -> bool:
    """Whether the manifest's host is in `root` (UM-Codex's folder)."""
    try:
        target = json.loads(manifest.read_text(encoding="utf-8"))["path"]
    except (OSError, ValueError, KeyError, TypeError, UnicodeDecodeError):
        return False
    return isinstance(target, str) and inside(_resolved(target), _resolved(str(root)))


def _replace(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.um-codex.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def remember(copy: Path, home: Path | None = None, platform: str = sys.platform) -> None:
    """Before a copy opens: what each manifest is now (None: none, or already
    UM-Codex's). A backup that wasn't restored yet is kept as it is."""
    backup = copy / BACKUP
    if backup.exists():
        return
    saved: dict[str, str | None] = {}
    for path in manifests(home, platform):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = None
        saved[str(path)] = None if text is None or leads_into(path, copy) else text
    copy.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        _replace(backup, json.dumps(saved).encode("utf-8"))
        os.chmod(backup, 0o600)


def restore(
    copy: Path,
    home: Path | None = None,
    *,
    root: Path | None = None,
    final: bool = True,
    platform: str = sys.platform,
) -> list[str]:
    """Put back the person's manifests that lead into `root` (default the
    copy's folder; uninstall passes the whole data folder), or remove them
    if there was none; take the copy's entries out of the shared registry
    when `final`. `final=False` (while the copy runs): the backup is kept for
    the next time. Lines saying what changed."""
    root = root or copy
    backup = copy / BACKUP
    try:
        saved = json.loads(backup.read_text(encoding="utf-8"))
        saved = saved if isinstance(saved, dict) else {}
    except (OSError, ValueError, UnicodeDecodeError):
        saved = {}
    changed = []
    for path in manifests(home, platform):
        if not leads_into(path, root):
            continue  # untouched, or the person's own app wrote it since
        before = saved.get(str(path))
        with contextlib.suppress(OSError):
            if isinstance(before, str) and not _text_leads_into(before, root):
                _replace(path, before.encode("utf-8"))
                changed.append(f"Put back Chrome's link to your own ChatGPT app ({path.parent.parent.name}).")
            else:
                path.unlink()
                changed.append(
                    f"Removed Chrome's link to UM-Codex's Codex window ({path.parent.parent.name})."
                )
    if final:
        forget_registry(root, home, platform)
        backup.unlink(missing_ok=True)
    for line in changed:
        log.info("%s", line)
    return changed


def restore_all(
    copies: list[Path], root: Path, home: Path | None = None, platform: str = sys.platform
) -> list[str]:
    """Uninstall: put back the person's manifests from whichever copy's
    backup holds them (one copy may have backed up another's), remove the
    rest that lead into `root`, take `root`'s entries out of the registry,
    and drop the backups."""
    saved: dict[str, str] = {}
    for copy in copies:
        try:
            backup = json.loads((copy / BACKUP).read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        for key, text in backup.items() if isinstance(backup, dict) else ():
            if isinstance(text, str) and not _text_leads_into(text, root):
                saved.setdefault(key, text)
    changed = []
    for path in manifests(home, platform):
        if not leads_into(path, root):
            continue
        with contextlib.suppress(OSError):
            if str(path) in saved:
                _replace(path, saved[str(path)].encode("utf-8"))
                changed.append(f"Put back Chrome's link to your own ChatGPT app ({path.parent.parent.name}).")
            else:
                path.unlink()
                changed.append(
                    f"Removed Chrome's link to UM-Codex's Codex window ({path.parent.parent.name})."
                )
    forget_registry(root, home, platform)
    for copy in copies:
        (copy / BACKUP).unlink(missing_ok=True)
    return changed


def _text_leads_into(text: str, root: Path) -> bool:
    try:
        target = json.loads(text)["path"]
    except (ValueError, KeyError, TypeError):
        return False
    return isinstance(target, str) and inside(_resolved(target), _resolved(str(root)))


def forget_registry(root: Path, home: Path | None = None, platform: str = sys.platform) -> bool:
    """Take the entries whose paths lead into `root` out of the app's shared
    registry; the rest, and the file's shape, are kept. A file of another
    shape is left alone. False when nothing was changed."""
    path = registry(home, platform)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return False
    entries = raw.get("entries") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return False
    folder = _resolved(str(root))

    def ours(entry: object) -> bool:
        paths = entry.get("paths") if isinstance(entry, dict) else None
        if not isinstance(paths, dict):
            return False
        return any(
            isinstance(paths.get(k), str) and inside(_resolved(paths[k]), folder)
            for k in ("codexHome", "extensionHostPath")
        )

    kept = [e for e in entries if not ours(e)]
    if len(kept) == len(entries):
        return False
    with contextlib.suppress(OSError):
        _replace(path, (json.dumps({**raw, "entries": kept}, indent=2) + "\n").encode("utf-8"))
        log.info("took UM-Codex's entries out of the Codex app's Chrome registry")
        return True
    return False


def forget(root: Path, home: Path | None = None, platform: str = sys.platform) -> list[str]:
    """Remove manifests that lead into `root` and that no backup can put
    back (uninstall, after `restore`): left, they'd point Chrome at a program
    that's gone."""
    removed = []
    for path in manifests(home, platform):
        if leads_into(path, root):
            with contextlib.suppress(OSError):
                path.unlink()
                removed.append(
                    f"Removed Chrome's link to UM-Codex's Codex window ({path.parent.parent.name})."
                )
    return removed
