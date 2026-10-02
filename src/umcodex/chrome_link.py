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
import stat
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


def _replace(path: Path, data: bytes, mode: int | None = None) -> None:
    """Write whole through a temporary file of its own beside it, then rename."""
    import tempfile

    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".um-codex.tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
        if mode is not None:
            os.chmod(name, mode)
        os.replace(name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(name)
        raise


def _live(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _read_backup(copy: Path) -> dict[str, str | None] | None:
    try:
        saved = json.loads((copy / BACKUP).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(saved, dict):
        return None
    return {k: v for k, v in saved.items() if isinstance(k, str) and (v is None or isinstance(v, str))}


def _write_backup(copy: Path, saved: dict[str, str | None]) -> None:
    copy.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        _replace(copy / BACKUP, json.dumps(saved).encode("utf-8"), mode=0o600)


def _refreshed(
    saved: dict[str, str | None], root: Path, home: Path | None, platform: str
) -> dict[str, str | None]:
    """The backup, with every manifest that doesn't lead into `root` (the
    data folder: either UM-Codex copy) taken as it is now: the person's own
    app may have rewritten it (a new version's path, say), and that's what
    must come back. One that leads into `root` keeps its saved entry."""
    fresh = dict(saved)
    for path in manifests(home, platform):
        if not leads_into(path, root):
            fresh[str(path)] = _live(path)
    return fresh


def remember(copy: Path, root: Path, home: Path | None = None, platform: str = sys.platform) -> None:
    """Before a copy opens: the person's manifests as they are now. `root` is
    the data folder, so neither UM-Codex copy's manifest is ever taken for
    the person's. A backup that wasn't restored yet keeps its entries for
    manifests that still lead into `root`; the others are refreshed."""
    _write_backup(copy, _refreshed(_read_backup(copy) or {}, root, home, platform))


def restore(
    copy: Path,
    root: Path,
    home: Path | None = None,
    *,
    final: bool = True,
    platform: str = sys.platform,
) -> list[str]:
    """Put back the person's manifests that now lead into `root` (the data
    folder: either UM-Codex copy), or remove them if there was none; refresh
    the backup for the others. The copy's entries leave the shared registry.
    `final=False` (while the copy runs): the backup is kept. When `final`, the
    backup goes only if every manifest that led into `root` was put back or
    removed; otherwise it's kept (and logged) for the next try. Lines saying
    what changed."""
    original = _read_backup(copy)
    saved = original or {}
    changed, failed = _put_back(saved, root, home, platform)
    forget_registry(root, home, platform)
    saved = _refreshed(saved, root, home, platform)
    if final and not failed:
        _hand_over(copy, root, saved)
        (copy / BACKUP).unlink(missing_ok=True)
    elif saved != original:
        _write_backup(copy, saved)
    if failed:
        log.warning("Chrome's link couldn't be put back for: %s; the backup is kept", ", ".join(failed))
    for line in changed:
        log.info("%s", line)
    return changed


def _hand_over(copy: Path, root: Path, saved: dict[str, str | None]) -> None:
    """Before a copy's backup goes: another UM-Codex copy's backup in the
    data folder that has no person's manifest for a place (it started while
    this copy's manifest was there) gets this one's, so it can put it back."""
    try:
        siblings = [d for d in root.iterdir() if d != copy and (d / BACKUP).is_file()]
    except OSError:
        return
    for sibling in siblings:
        theirs = _read_backup(sibling)
        if theirs is None:
            continue
        merged = dict(theirs)
        for key, text in saved.items():
            if isinstance(text, str) and not _text_leads_into(text, root) and merged.get(key) is None:
                merged[key] = text
        if merged != theirs:
            _write_backup(sibling, merged)


def _put_back(
    saved: dict[str, str | None], root: Path, home: Path | None, platform: str
) -> tuple[list[str], list[str]]:
    changed: list[str] = []
    failed: list[str] = []
    for path in manifests(home, platform):
        if not leads_into(path, root):
            continue  # untouched, or the person's own app wrote it since
        before = saved.get(str(path))
        try:
            if isinstance(before, str) and not _text_leads_into(before, root):
                _replace(path, before.encode("utf-8"))
                changed.append(f"Put back Chrome's link to your own ChatGPT app ({path.parent.parent.name}).")
            else:
                path.unlink()
                changed.append(
                    f"Removed Chrome's link to UM-Codex's Codex window ({path.parent.parent.name})."
                )
        except OSError:
            failed.append(str(path))
    return changed, failed


def restore_all(
    copies: list[Path], root: Path, home: Path | None = None, platform: str = sys.platform
) -> list[str]:
    """Uninstall: put back the person's manifests from whichever copy's
    backup holds them, remove the rest that lead into `root`, take `root`'s
    entries out of the registry, and drop the backups (kept if anything
    couldn't be restored)."""
    saved: dict[str, str | None] = {}
    for copy in copies:
        for key, text in (_read_backup(copy) or {}).items():
            if isinstance(text, str) and not _text_leads_into(text, root):
                saved.setdefault(key, text)
    changed, failed = _put_back(saved, root, home, platform)
    forget_registry(root, home, platform)
    if failed:
        log.warning("Chrome's link couldn't be put back for: %s; the backups are kept", ", ".join(failed))
    else:
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
    registry; the rest, the file's shape and its mode are kept. If the file
    changed between reading and writing (the app wrote it), it's read again
    once. A file of another shape is left alone. False when nothing changed."""
    path = registry(home, platform)
    folder = _resolved(str(root))

    def ours(entry: object) -> bool:
        paths = entry.get("paths") if isinstance(entry, dict) else None
        if not isinstance(paths, dict):
            return False
        return any(
            isinstance(paths.get(k), str) and inside(_resolved(paths[k]), folder)
            for k in ("codexHome", "extensionHostPath")
        )

    for _ in range(2):
        try:
            before = path.stat()
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return False
        entries = raw.get("entries") if isinstance(raw, dict) else None
        if not isinstance(entries, list):
            return False
        kept = [e for e in entries if not ours(e)]
        if len(kept) == len(entries):
            return False
        try:
            now = path.stat()
            if (now.st_mtime_ns, now.st_size) != (before.st_mtime_ns, before.st_size):
                continue  # written meanwhile: read it again
            text = json.dumps({**raw, "entries": kept}, indent=2) + "\n"
            _replace(path, text.encode("utf-8"), mode=stat.S_IMODE(before.st_mode))
        except OSError:
            return False
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
