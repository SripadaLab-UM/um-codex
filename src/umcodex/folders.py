# Adapted from DataLab's backend/src/datalab/sessions/inputs.py (private_place, _key,
# mount_name) and sessions/mounts.py at 6b6fdca, loosened for UM-Codex.
"""Which folders a launch may share with the container, and how.

DataLab only ever mounted folders read-only. UM-Codex also mounts writable
ones (Codex can change and delete files there), so these rules decide what
is never shared at all:
- the home folder itself, `/`, a whole drive, or anything holding a home folder;
- UM-Codex's own data folder;
- the key store, ~/.ssh, ~/.aws, ~/.config/gh, ~/.codex;
- Docker's own folders.

A folder inside, or holding, one of those is refused too. Every path is
resolved first, so a link can't widen what's shared. Subfolders of home
are fine.
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from umcodex.paths import app_dir, data_dir

_MAX_NAME_BYTES = 120
# Control, line-separator and text-direction characters: never in a mount name.
_UNPRINTABLE = re.compile(
    "[\\x00-\\x1f\\x7f\\u0085\\u061c\\u200b-\\u200f\\u2028-\\u202e\\u2060-\\u2069\\ufeff]"
)


class FolderRefused(ValueError):
    """The folder can't be shared. The message is a plain reason for the person."""


@dataclass(frozen=True)
class Checked:
    path: Path  # resolved
    warnings: tuple[str, ...] = ()


def protected_places(home: Path | None = None, platform: str = sys.platform) -> list[tuple[Path, str]]:
    """Folders never shared, with the reason given, before resolving."""
    home = home or Path.home()
    places: list[tuple[Path, str]] = [
        (home / ".ssh", "it holds your SSH keys"),
        (home / ".aws", "it holds your AWS credentials"),
        (home / ".config" / "gh", "it holds your GitHub sign-in"),
        (home / ".codex", "it holds Codex's own settings and sign-in on this computer"),
        (home / ".docker", "it's Docker's own folder"),
        (home / ".gnupg", "it holds your GPG keys"),
        (home / ".kube", "it holds your Kubernetes credentials"),
        (home / ".azure", "it holds your Azure credentials"),
        (home / ".config" / "gcloud", "it holds your Google Cloud credentials"),
        # Programs this computer runs later: code planted there would run on the host.
        (home / ".local" / "bin", "programs you run (UM-Codex's own command among them) are there"),
        (home / ".local" / "share" / "uv", "it holds the Python tools you run, UM-Codex among them"),
        (app_dir(platform), "it holds UM-Codex's own program files"),
    ]
    for variable in ("UV_TOOL_BIN_DIR", "XDG_BIN_HOME", "UV_TOOL_DIR"):
        if value := os.environ.get(variable):
            places.append((Path(value), "programs you run (UM-Codex's own command among them) are there"))
    if platform == "darwin":
        places += [
            (home / "Library" / "Keychains", "it's the keychain, where your keys are kept"),
            (home / "Library" / "LaunchAgents", "programs there start when you log in"),
            (home / "Library" / "Containers" / "com.docker.docker", "it's Docker's own folder"),
            (home / "Library" / "Group Containers" / "group.com.docker", "it's Docker's own folder"),
            (Path("/var/run"), "it holds Docker's control socket"),
            (Path("/Applications/Docker.app"), "it's Docker's own folder"),
        ]
    if platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        roaming = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        places += [
            (local / "Microsoft" / "Credentials", "it's Credential Manager, where your keys are kept"),
            (roaming / "Microsoft" / "Credentials", "it's Credential Manager, where your keys are kept"),
            (roaming / "Microsoft" / "Protect", "it holds Windows' encryption keys"),
            (
                roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup",
                "programs there start when you log in",
            ),
            (local / "Docker", "it's Docker's own folder"),
            (roaming / "Docker", "it's Docker's own folder"),
            (roaming / "Docker Desktop", "it's Docker's own folder"),
            (program_data / "Docker", "it's Docker's own folder"),
            (program_data / "DockerDesktop", "it's Docker's own folder"),
            (program_files / "Docker", "it's Docker's own folder"),
        ]
    return places


def parse_path_input(text: str) -> str:
    """What a person typed or dropped into the terminal, as a path string.

    Finder and Explorer drops add quotes or backslash-escaped spaces.
    """
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1]
    elif sys.platform != "win32" and "\\" in text and not Path(text).exists():
        text = re.sub(r"\\(.)", r"\1", text)
    return os.path.expanduser(text)


def check_folder(
    raw: str | Path,
    *,
    own_data: Path | None = None,
    home: Path | None = None,
    platform: str = sys.platform,
) -> Checked:
    """The resolved folder, or FolderRefused with a plain reason."""
    path = Path(raw)
    if not path.is_absolute():
        raise FolderRefused(f"{raw} isn't a full path. Give the whole path, like /Users/you/thesis.")
    if not path.exists():
        raise FolderRefused(f"{raw} doesn't exist.")
    real = Path(os.path.realpath(path))
    if not real.is_dir():
        raise FolderRefused(f"{raw} is a file, not a folder. Choose the folder it's in.")
    home_real = Path(os.path.realpath(home or Path.home()))
    if same(real, home_real):
        raise FolderRefused(
            "Your whole home folder can't be shared: it holds your keys and settings. "
            "Choose a folder inside it."
        )
    if real.parent == real or os.path.ismount(real):
        raise FolderRefused(f"{real} is a whole drive, which can't be shared. Choose a folder on it.")
    # Compared by name and by identity on disk (device and inode, for the
    # folder and each folder it's in): the same folder can have more than one
    # name (a Mac firmlink like /System/Volumes/Data/Users/..., or Windows'
    # \\localhost\C$\ and \\?\ forms), and a name alone would miss it.
    ids = _ids(real)
    home_ids = _ids(home_real)
    if (home_ids and ids and home_ids[0] == ids[0]) or same(real, home_real):
        raise FolderRefused(
            "Your whole home folder can't be shared: it holds your keys and settings. "
            "Choose a folder inside it."
        )
    if inside(home_real, real) or (ids and ids[0] in home_ids[1:]) or _holds_by_identity(real, home_real):
        raise FolderRefused(f"{real} holds your home folder, so it can't be shared.")
    mine = Path(os.path.realpath(own_data or data_dir()))
    if _related(real, ids, mine) is not None:
        raise FolderRefused(f"{real} is or holds UM-Codex's own data folder, which can't be shared.")
    for place, reason in protected_places(home, platform):
        relation = _related(real, ids, Path(os.path.realpath(place)))
        if relation == "in":
            raise FolderRefused(f"{place} can't be shared: {reason}.")
        if relation == "holds":
            raise FolderRefused(f"{real} can't be shared: it holds {place}, and {reason}.")
    warnings = ()
    if platform == "win32" and _network_drive(real):
        warnings = (
            f"{real} is on a network drive. It can be shared, but it may be slow, "
            "and Codex's changes there go straight to the network copy.",
        )
    return Checked(real, warnings)


def _ids(path: Path) -> list[tuple[int, int]]:
    """(device, inode) of `path` and of each folder it's in, as far as they exist."""
    found = []
    for each in (path, *path.parents):
        try:
            info = os.stat(each)
        except OSError:
            continue
        found.append((info.st_dev, info.st_ino))
    return found


def _related(real: Path, ids: list[tuple[int, int]], place: Path) -> str | None:
    """ "in" if `real` is `place` or inside it, "holds" if it holds it, else None."""
    if same(real, place) or inside(real, place):
        return "in"
    if inside(place, real):
        return "holds"
    place_ids = _ids(place)
    if not place_ids or not ids or not os.path.exists(place):
        return None
    if place_ids[0] in ids:
        return "in"
    if ids[0] in place_ids[1:] or _holds_by_identity(real, place):
        return "holds"
    return None


def _holds_by_identity(folder: Path, target: Path) -> bool:
    """Whether `target` is inside `folder` under another name: some tail of
    target's path, joined onto folder, is the same folder on disk (for
    example /System/Volumes/Data holds /Users/you as .../Data/Users/you)."""
    target_ids = _ids(target)
    if not target_ids:
        return False
    parts = target.parts[1:]
    for start in range(len(parts)):
        candidate = folder.joinpath(*parts[start:])
        try:
            info = os.stat(candidate)
        except OSError:
            continue
        if (info.st_dev, info.st_ino) == target_ids[0]:
            return True
    return False


@dataclass(frozen=True)
class Layout:
    """The checked folders of a launch and where each appears in the container."""

    working: Path
    writes: tuple[tuple[Path, str], ...]  # (host folder, container path)
    reads: tuple[tuple[Path, str], ...]
    notes: tuple[str, ...]


def plan(working: Path, writes: Sequence[Path], reads: Sequence[Path]) -> Layout:
    """Container paths for already-resolved folders, refusing overlaps that
    make no sense: the same folder twice, or read-only and writable at once."""
    seen: dict[str, str] = {key(working): "the working folder"}
    for folder in writes:
        if key(folder) in seen:
            raise FolderRefused(f"{folder} is listed twice (it's already {seen[key(folder)]}).")
        seen[key(folder)] = "a folder to write"
    for folder in reads:
        if key(folder) in seen:
            raise FolderRefused(
                f"{folder} can't be both read-only and writable (it's already {seen[key(folder)]})."
            )
        seen[key(folder)] = "a read-only folder"
    taken: set[str] = set()
    write_targets = tuple((f, "/mnt/write/" + mount_name(f.name, taken)) for f in writes)
    taken = set()
    read_targets = tuple((f, "/mnt/read/" + mount_name(f.name, taken)) for f in reads)
    notes = []
    writable = [(working, "/work"), *write_targets]
    for folder, _ in read_targets:
        for parent, target in writable:
            if inside(folder, parent):
                rel = Path(os.path.relpath(folder, parent)).as_posix()
                notes.append(
                    f"{folder} is read-only at its own place, but it's inside a writable folder, "
                    f"so Codex can still change it at {target}/{rel}."
                )
    return Layout(working, write_targets, read_targets, tuple(notes))


def mount_name(wanted: str, taken: set[str]) -> str:
    """A name under /mnt/write or /mnt/read that doesn't clash: 'data', then 'data-2', …"""
    base = _UNPRINTABLE.sub("", wanted).replace("/", "_").replace("\\", "_").replace(":", "_")
    base = base.strip().strip(".") or "folder"
    while len(base.encode()) > _MAX_NAME_BYTES:
        base = base[:-1]
    name, number = base, 2
    while name.casefold() in taken:
        name = f"{base}-{number}"
        number += 1
    taken.add(name.casefold())
    return name


def same(a: Path, b: Path) -> bool:
    return key(a) == key(b)


def inside(path: Path, folder: Path) -> bool:
    """Is `path` strictly inside `folder`?"""
    return key(path).startswith(key(folder).rstrip("/") + "/")


def key(path: Path) -> str:
    """Paths compared the way the disk does: Mac and Windows ignore case, and
    a Mac doesn't tell composed from decomposed accents (é and e + ́)."""
    text = unicodedata.normalize("NFC", str(path).replace("\\", "/"))
    return text.casefold() if sys.platform in ("darwin", "win32") else text


def _network_drive(path: Path) -> bool:
    text = str(path)
    if text.startswith(("\\\\", "//")):
        return True
    if sys.platform != "win32":
        return False
    import ctypes

    drive = path.drive + "\\"
    # DRIVE_REMOTE
    return ctypes.windll.kernel32.GetDriveTypeW(drive) == 4  # type: ignore[attr-defined]
