# Adapted from IHS DataLab's backend/src/datalab/updater.py (Layout, the
# checks, installing beside the running version) at 6b6fdca. Simpler: no web
# app to stop, no database to back up, no restart helper. A terminal command
# runs it, and the next launch opens the new version.
"""`um-codex update`: install a newer signed release beside this one.

1. **Check** (releases.py): the newest release newer than this one, whose
   SHA256SUMS is signed by a key this package pins, and which lists the
   package, requirements.txt and images.json with GitHub's own checksums.
2. **Download and check** into `<app>/downloads/<version>/`: each file must
   match the signed SHA256SUMS; requirements.txt must pin every dependency
   by version and hash and name the package once, by its checksum;
   images.json must pin the agent and gateway images by digest and name
   exactly the images the new package itself runs. Nothing has changed yet.
3. **Install beside** in `<app>/versions/<version>/`, as the installers do
   (`uv venv`, then `uv pip install --no-config --require-hashes
   --only-binary :all: --default-index https://pypi.org/simple --link-mode
   copy -r requirements.txt`, with no `UV_*`, `PIP_*` or `PYTHON*` from the
   environment), check its `--version`, mark it `.complete`.
4. **Pull its images** with the new version's own `um-codex pull`.
5. **Switch**: `previous` names this version and `current` the new one (each
   one-line file replaced whole). On Windows `bin\\um-codex.exe` becomes a
   copy of the new version's own launcher (the running one is renamed aside).
6. **Prune** every other version folder.
7. **Refresh the launchers** (the Mac app, the Windows shortcuts) with the new
   version's own `um-codex launchers --refresh` (launchers.py): an older
   installer's are rewritten as this version writes them. If one can't be,
   the update still stands, and it says what to do.

If any step fails, what it installed is removed and this version stays the
one in use. It refuses while a launch is running (each holds a lock), and
`um-codex update --rollback` switches `current` and `previous` back.

At most once a day a launch checks too (`launch_notice`), for 3 seconds at
most, and prints one line when a newer release is out.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import httpx

from umcodex import __version__
from umcodex.launch import LaunchLock, launch_is_live, launches_dir
from umcodex.paths import app_dir, data_dir, default_data_dir
from umcodex.releases import (
    CheckProblem,
    ChecksumMismatch,
    NotConfigured,
    NotSigned,
    Offer,
    ReleaseSource,
    find_update,
    is_newer,
    parse_version,
    pinned_keys,
)

INSTALL_DIR_ENV = "UMCODEX_INSTALL_DIR"
PYPI = "https://pypi.org/simple"
AGENT_REPOSITORY = "ghcr.io/sripadalab-um/um-codex-agent"
# Environment variables a uv or Python subprocess never inherits: they could
# point it at another index, add one, or turn its checks off.
_UNSAFE_ENV = ("UV_", "PIP_")
_UNSAFE_NAMES = frozenset({"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "VIRTUAL_ENV"})
_REQUIREMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?==[A-Za-z0-9.+!_-]+")
_HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})")
_DIGEST = re.compile(r"[^@\s]+@sha256:[0-9a-f]{64}")
_COMPLETE = ".complete"
# The launch-time check: at most once a day, and never more than this long.
NOTICE_FILE = "update-check.json"
NOTICE_EVERY_SECONDS = 24 * 60 * 60
NOTICE_WAIT_SECONDS = 3.0
NO_CHECK_ENV = "UMCODEX_NO_UPDATE_CHECK"

Say = Callable[[str], None]


class Runner(Protocol):
    def __call__(
        self, command: Sequence[str], *, timeout: float, cwd: Path | None = None, capture: bool = True
    ) -> subprocess.CompletedProcess[str]: ...


class UpdateFailed(RuntimeError):
    """An update step failed. Its message is for the person; nothing was left half-done."""


def clean_environment() -> dict[str, str]:
    """This process's environment, without anything that steers uv, pip or
    Python, and with Python in UTF-8 mode (as the installers run it)."""
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith(_UNSAFE_ENV) and name.upper() not in _UNSAFE_NAMES
    }
    env["PYTHONUTF8"] = "1"
    return env


def run_command(
    command: Sequence[str], *, timeout: float, cwd: Path | None = None, capture: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a step. Captured steps (uv, --version) are quiet; the rest (pulling
    images) show their own progress in the terminal."""
    return subprocess.run(
        list(command),
        capture_output=capture,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        cwd=cwd,
        env=clean_environment(),
        stdin=subprocess.DEVNULL,
    )


# ------------------------------------------------------------------ layout


def install_root() -> Path:
    """Where the installers put UM-Codex's versions (`UMCODEX_INSTALL_DIR` in tests)."""
    override = os.environ.get(INSTALL_DIR_ENV)
    return Path(override) if override else app_dir()


class Layout:
    """The installed versions, side by side, as the installers lay them out.

    ```
    <root>/versions/<version>/   one Python environment per version; .complete when whole
    <root>/current               the version the launcher opens
    <root>/previous              the one it opened before the last switch
    <root>/bin/um-codex          the command: runs `current` (Mac: a shim;
                                 Windows: um-codex.exe, a copy of current's own launcher)
    <root>/downloads/<version>/  a release's files while it's being installed
    ```
    """

    def __init__(self, root: Path, *, windows: bool | None = None, prefix: Path | None = None) -> None:
        self.root = root
        self.windows = sys.platform == "win32" if windows is None else windows
        self._prefix = prefix if prefix is not None else Path(sys.prefix)

    @property
    def versions(self) -> Path:
        return self.root / "versions"

    @property
    def downloads(self) -> Path:
        return self.root / "downloads"

    @property
    def command(self) -> Path:
        return self.root / "bin" / ("um-codex.exe" if self.windows else "um-codex")

    def folder(self, version: str) -> Path:
        parsed = parse_version(version)
        if parsed is None or str(parsed) != version:
            raise UpdateFailed(f"{version!r} isn't a UM-Codex version.")
        return self.versions / version

    def executable(self, version: str) -> Path:
        folder = self.folder(version)
        return folder / "Scripts" / "um-codex.exe" if self.windows else folder / "bin" / "um-codex"

    def python(self, version: str) -> Path:
        folder = self.folder(version)
        return folder / "Scripts" / "python.exe" if self.windows else folder / "bin" / "python"

    def complete(self, version: str) -> bool:
        return (self.folder(version) / _COMPLETE).is_file()

    def recorded_sha256(self, version: str) -> str | None:
        """The package checksum `.complete` records for an installed version."""
        with contextlib.suppress(OSError, ValueError, AttributeError):
            record = json.loads((self.folder(version) / _COMPLETE).read_text(encoding="utf-8"))
            value = record.get("wheel_sha256")
            return value if isinstance(value, str) else None
        return None

    def running_version(self) -> str | None:
        """This process's version folder's name, if it runs from this layout."""
        with contextlib.suppress(OSError):
            prefix = self._prefix.resolve()
            if prefix.parent == self.versions.resolve() and (prefix / _COMPLETE).is_file():
                return prefix.name
        return None

    def pointer(self) -> tuple[str | None, str | None]:
        return _read_line(self.root / "current"), _read_line(self.root / "previous")

    def switch(self, to: str, previous: str | None) -> None:
        """Point the launchers at `to`. On Windows the command's copy comes
        first (if it can't be made, nothing has changed), then `previous`, so
        a switch cut off half way still names both, then `current`."""
        if not self.complete(to):
            raise UpdateFailed(f"UM-Codex {to} isn't installed completely.")
        if self.windows:
            self.install_command(to)
        if previous is not None:
            _write_line(self.root / "previous", previous)
        _write_line(self.root / "current", to)

    def restore(self, pointer: tuple[str | None, str | None]) -> None:
        current, previous = pointer
        if previous is None:
            (self.root / "previous").unlink(missing_ok=True)
        else:
            _write_line(self.root / "previous", previous)
        if current is not None:
            if self.windows and self.complete(current):
                self.install_command(current)
            _write_line(self.root / "current", current)

    def install_command(self, version: str) -> None:
        """Windows: `bin\\um-codex.exe`, a copy of `version`'s own launcher (as
        the installer's Install-Launcher). The one there may be running (it
        may be this very process), so it's renamed aside, not overwritten;
        copies moved aside earlier are removed once nothing runs them. The new
        copy is made beside it first (`.um-codex.exe.new`), so a copy that
        fails part way never leaves `bin` without a command."""
        target = self.command
        target.parent.mkdir(parents=True, exist_ok=True)
        for old in target.parent.glob(f"{target.name}.old-*"):
            with contextlib.suppress(OSError):
                old.unlink()
        fresh = target.with_name(f".{target.name}.new")
        shutil.copy2(self.executable(version), fresh)
        if target.exists():
            target.rename(target.with_name(f"{target.name}.old-{uuid.uuid4().hex}"))
        os.replace(fresh, target)

    def prune(self, keep: set[str]) -> list[str]:
        """Remove installed versions other than `keep` (and this process's own)."""
        removed: list[str] = []
        if not self.versions.is_dir():
            return removed
        running = self.running_version()
        for folder in self.versions.iterdir():
            name = folder.name
            if name in keep or name == running or folder.is_symlink() or not folder.is_dir():
                continue
            parsed = parse_version(name)
            if parsed is None or str(parsed) != name:
                continue  # not one of ours
            # Not a whole version any more, even if removing it stops part way.
            with contextlib.suppress(OSError):
                (folder / _COMPLETE).unlink(missing_ok=True)
            shutil.rmtree(folder, ignore_errors=True)
            if not folder.exists():
                removed.append(name)
        return removed


def _read_line(path: Path) -> str | None:
    with contextlib.suppress(OSError, UnicodeDecodeError):
        text = path.read_text(encoding="utf-8").strip()
        return text.splitlines()[0].strip() if text else None
    return None


def _write_line(path: Path, text: str) -> None:
    """A one-line file, written beside it and moved into place whole."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.new")
    temporary.write_text(text + "\n", encoding="utf-8")
    with temporary.open("rb+") as file:
        os.fsync(file.fileno())
    os.replace(temporary, path)


# ------------------------------------------------------------------ checks


@dataclass(frozen=True)
class Staged:
    """A release's files, downloaded and checked."""

    version: str
    folder: Path
    wheel: Path
    wheel_sha256: str
    requirements: Path
    images: dict[str, str]


def check_requirements(text: str, wheel: str, wheel_sha256: str) -> None:
    """`requirements.txt`, if it pins everything by hash: each dependency as
    `name==version` with sha256 hashes, and the one local file the release's
    package (`./<wheel>`) with exactly its checksum. No options (another
    index, `-e`, `-r`...), URLs or other files."""
    logical: list[str] = []
    current = ""
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].strip() if not raw.lstrip().startswith("#") else ""
        continued = line.endswith("\\")
        current = f"{current} {line.removesuffix('\\').strip()}".strip()
        if not continued:
            if current:
                logical.append(current)
            current = ""
    if current:
        logical.append(current)
    packages = 0
    for line in logical:
        head, _, tail = line.partition(" --hash=")
        hashes = _HASH.findall(f"--hash={tail}") if tail else []
        if tail and len(hashes) != len(tail.split()):
            raise ChecksumMismatch(f"requirements.txt has a line it shouldn't: {line[:80]!r}")
        requirement, _, marker = head.partition(";")
        requirement = requirement.strip()
        if "--" in marker or marker.strip().startswith("-"):
            raise ChecksumMismatch(f"requirements.txt has a line it shouldn't: {line[:80]!r}")
        if requirement == f"./{wheel}":
            if hashes != [wheel_sha256]:
                raise ChecksumMismatch("requirements.txt pins the package with another checksum.")
            packages += 1
            continue
        if not _REQUIREMENT.fullmatch(requirement) or not hashes:
            raise ChecksumMismatch(f"requirements.txt doesn't pin this by version and hash: {line[:80]!r}")
        if requirement.lower().startswith(("umcodex==", "umcodex[")):
            raise ChecksumMismatch("requirements.txt names UM-Codex itself from an index.")
    if packages != 1:
        raise ChecksumMismatch("requirements.txt doesn't name the release's package once.")


def check_images(images_json: bytes, wheel: Path) -> dict[str, str]:
    """`images.json`, if it pins the agent and gateway images by digest and
    names exactly the images the new package runs (its own images.json)."""
    try:
        images = json.loads(images_json)
    except ValueError:
        raise ChecksumMismatch("images.json isn't readable.") from None
    if not isinstance(images, dict) or set(images) != {"agent", "gateway"}:
        raise ChecksumMismatch("images.json doesn't list exactly the agent and gateway images.")
    for role, image in images.items():
        if not isinstance(image, str) or not _DIGEST.fullmatch(image):
            raise ChecksumMismatch(f"images.json doesn't pin the {role} image by digest.")
    if not images["agent"].startswith(f"{AGENT_REPOSITORY}@"):
        raise ChecksumMismatch(f"images.json's agent image isn't {AGENT_REPOSITORY}.")
    try:
        with zipfile.ZipFile(wheel) as package:
            runs = json.loads(package.read("umcodex/images.json"))
    except (KeyError, OSError, ValueError, zipfile.BadZipFile):
        raise ChecksumMismatch("The package doesn't say which images it runs.") from None
    if not isinstance(runs, dict) or {k: v for k, v in runs.items() if not k.startswith("_")} != images:
        raise ChecksumMismatch("images.json and the package name different images.")
    return images


# ------------------------------------------------------------------ updater


def find_uv(platform: str = sys.platform) -> str | None:
    """uv, as the installers left it: on Windows, the pinned one in UM-Codex's
    own folder (install.ps1); on a Mac, the one uv's installer puts in
    ~/.local/bin (install.sh), ahead of any other on PATH; else one on PATH."""
    if platform == "win32":
        pinned = default_data_dir(platform) / "uv" / "uv.exe"
        if pinned.is_file():
            return str(pinned)
    candidate = Path.home() / ".local" / "bin" / ("uv.exe" if platform == "win32" else "uv")
    if candidate.is_file():
        return str(candidate)
    return shutil.which("uv")


def running_launch(data: Path) -> bool:
    """Whether a launch of this data folder is running (each holds its lock)."""
    folder = launches_dir(data)
    if not folder.is_dir():
        return False
    return any(entry.is_dir() and launch_is_live(data, entry.name) for entry in folder.iterdir())


RUNNING = (
    "UM-Codex is running (Codex is open in another window). Quit Codex there first, then run "
    "um-codex update again."
)


class Updater:
    def __init__(
        self,
        *,
        layout: Layout | None = None,
        source: ReleaseSource | None = None,
        keys: Sequence[str] | None = None,
        current: str = __version__,
        run: Runner = run_command,
        uv: str | None = None,
        platform: str = sys.platform,
        data: Path | None = None,
        say: Say = print,
    ) -> None:
        self.platform = platform
        self.layout = layout or Layout(install_root(), windows=platform == "win32")
        self._source = source
        self._keys = keys
        self.current = current
        self._run = run
        self._uv = uv if uv is not None else find_uv(platform)
        self.data = data if data is not None else data_dir()
        self.say = say

    # The two commands --------------------------------------------------------

    def update(self) -> int:
        """`um-codex update`: 0 when updated or already the newest, 1 otherwise."""
        try:
            keys = pinned_keys(self._keys)
        except NotConfigured as error:
            self.say(str(error))
            return 1
        why = self.why_not()
        if why is not None:
            self.say(why)
            return 1
        with self._exclusive() as alone:
            if not alone:
                self.say("Another `um-codex update` is running. Wait for it to finish.")
                return 1
            self.say("Checking for a newer UM-Codex...")
            try:
                offer = find_update(self.source, self.current, keys)
            except CheckProblem as problem:
                self.say(f"Couldn't check for updates: {problem}")
                return 1
            except NotSigned as error:
                self.say(
                    f"A newer release was found, but it isn't signed by UM-Codex's release key ({error}), "
                    "so it wasn't installed. Tell the UM-Codex maintainer."
                )
                return 1
            except ChecksumMismatch as error:
                self.say(
                    f"A newer release was found, but its checksums don't add up ({error}), "
                    "so it wasn't installed."
                )
                return 1
            remember_check(self.data, offer.release.version if offer else None)
            if offer is None:
                self.say(f"UM-Codex {self.current} is the newest version.")
                return 0
            _close_launcher_window(self.data)
            try:
                self.install(offer)
            except UpdateFailed as failed:
                self.say(str(failed))
                return 1
            remember_check(self.data, None)
            self.refresh_launchers(offer.release.version)
            self.say("")
            self.say(f"Updated to UM-Codex {offer.release.version}. The next launch uses it.")
            self.say(f"(UM-Codex {self.current} is kept: `um-codex update --rollback` goes back to it.)")
            return 0

    def rollback(self) -> int:
        """`um-codex update --rollback`: switch `current` and `previous`."""
        why = self.why_not(need_uv=False)
        if why is not None:
            self.say(why)
            return 1
        with self._exclusive() as alone:
            if not alone:
                self.say("An `um-codex update` is running. Wait for it to finish.")
                return 1
            current, previous = self.layout.pointer()
            if previous is None or previous == current or not self.layout.complete(previous):
                self.say("There's no earlier version to go back to.")
                return 1
            _close_launcher_window(self.data)
            try:
                self.layout.switch(previous, previous=current)
            except OSError as error:
                self.say(f"Couldn't switch back ({type(error).__name__}: {error}). Nothing was changed.")
                with contextlib.suppress(OSError):
                    self.layout.restore((current, previous))
                return 1
            self.refresh_launchers(previous)
            self.say(f"UM-Codex {previous} is the one in use now; {current} is kept.")
            self.say("(`um-codex update --rollback` again switches back.)")
            # Its images are usually still here; if not, they're pulled now.
            if not self._pull(previous):
                self.say(
                    "Its container images couldn't all be downloaded: run `um-codex pull` "
                    "before the next launch."
                )
            return 0

    # The steps ---------------------------------------------------------------

    @property
    def source(self) -> ReleaseSource:
        if self._source is None:
            self._source = ReleaseSource()
        return self._source

    def why_not(self, *, need_uv: bool = True) -> str | None:
        """Why this UM-Codex can't update itself now, or None."""
        if self.platform not in ("darwin", "win32"):
            return "um-codex update works on Mac and Windows."
        if self.layout.running_version() is None:
            return (
                "This copy of UM-Codex wasn't installed by the UM-Codex installer (it's a development "
                "copy), so it can't update itself. Install new versions with the installer."
            )
        if need_uv and not self._uv:
            return "uv, which installs UM-Codex, wasn't found. Run the UM-Codex installer again."
        if running_launch(self.data):
            return RUNNING
        return None

    def install(self, offer: Offer) -> None:
        """Download, check, install beside, pull, switch, prune. Undone if a step fails."""
        release = offer.release
        version = release.version
        if not is_newer(version, self.current):
            raise UpdateFailed(f"UM-Codex {version} isn't newer than this one ({self.current}).")
        running = self.layout.running_version()
        self.say(f"UM-Codex {version} is available (this is {self.current}). Downloading it...")
        staged = self.download(offer)
        created = False
        pointer = self.layout.pointer()
        switched = False
        try:
            if self.layout.folder(version).resolve() == Path(sys.prefix).resolve():
                raise UpdateFailed("UM-Codex won't install over the version that's running.")
            reuse = (
                self.layout.complete(version) and self.layout.recorded_sha256(version) == staged.wheel_sha256
            )
            self.say(f"Installing UM-Codex {version} beside this one...")
            if reuse:
                try:
                    self._check_version(version)
                except UpdateFailed:
                    # Installed before, but it doesn't run now: installed afresh.
                    (self.layout.folder(version) / _COMPLETE).unlink(missing_ok=True)
                    shutil.rmtree(self.layout.folder(version), ignore_errors=True)
                    reuse = False
            if not reuse:
                created = True
                self._install_beside(staged)
            self.say("Downloading its container images...")
            if not self._pull(version):
                raise UpdateFailed(
                    f"Its container images couldn't be downloaded (is Docker Desktop running?). "
                    f"UM-Codex {self.current} is still the one in use; try again later."
                )
            if running_launch(self.data):
                raise UpdateFailed(f"{RUNNING} UM-Codex {self.current} is still the one in use.")
            switched = True
            self.layout.switch(version, previous=running or self.current)
        except BaseException as error:
            if switched:
                with contextlib.suppress(OSError):
                    self.layout.restore(pointer)
            if created:
                shutil.rmtree(self.layout.folder(version), ignore_errors=True)
            if isinstance(error, UpdateFailed | KeyboardInterrupt):
                raise
            if isinstance(error, Exception):
                raise UpdateFailed(
                    f"Installing UM-Codex {version} failed ({type(error).__name__}: {error}). "
                    f"UM-Codex {self.current} is still the one in use."
                ) from None
            raise
        finally:
            self._drop_download(staged.folder)
        # Older versions go; the new one and the one it replaces stay.
        self.layout.prune({version, running or self.current})

    def download(self, offer: Offer) -> Staged:
        """The release's files, each checked. Nothing else changes."""
        release = offer.release
        folder = self.layout.downloads / release.version
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        try:
            paths: dict[str, Path] = {}
            for asset in release.files:
                sha256 = offer.expected.get(asset.name)
                if sha256 is None:
                    raise ChecksumMismatch(f"There's no checksum for {asset.name}.")
                paths[asset.name] = folder / asset.name
                self.source.download(asset, paths[asset.name], sha256=sha256)
            wheel = paths[release.wheel.name]
            wheel_sha256 = offer.expected[release.wheel.name]
            requirements = paths[release.requirements.name]
            check_requirements(requirements.read_text(encoding="utf-8"), release.wheel.name, wheel_sha256)
            images = check_images(paths[release.images.name].read_bytes(), wheel)
        except CheckProblem as problem:
            self._drop_download(folder)
            raise UpdateFailed(
                f"Couldn't download UM-Codex {release.version} ({problem}). Nothing was changed."
            ) from None
        except (ChecksumMismatch, OSError) as error:
            self._drop_download(folder)
            raise UpdateFailed(
                f"UM-Codex {release.version}'s files didn't pass their checks ({error}). Nothing was changed."
            ) from None
        return Staged(release.version, folder, wheel, wheel_sha256, requirements, images)

    def _drop_download(self, folder: Path) -> None:
        """A release's downloaded files, and the downloads folder once it's empty."""
        shutil.rmtree(folder, ignore_errors=True)
        with contextlib.suppress(OSError):
            self.layout.downloads.rmdir()

    def _install_beside(self, staged: Staged) -> None:
        """Into `versions/<version>`, with the installers' own uv flags."""
        version = staged.version
        folder = self.layout.folder(version)
        if folder.exists():  # an earlier attempt that was cut off, or another package
            shutil.rmtree(folder)
        uv = self._uv
        assert uv is not None
        venv = [uv, "venv", "-q", "--no-config", "--python", "3.13"]
        if not self.layout.windows:
            # As install.sh: uv's own Python build, never one found on this Mac.
            venv += ["--python-preference", "only-managed"]
        self._must([*venv, str(folder)], "making its Python environment", 600)
        self._must(
            [
                uv,
                "pip",
                "install",
                "-q",
                "--no-config",
                # Every file checked against requirements.txt's hashes (the
                # package's own is in the signed SHA256SUMS), only wheels, and
                # only from PyPI.
                "--require-hashes",
                "--only-binary",
                ":all:",
                "--default-index",
                PYPI,
                # Copies, not hardlinks into uv's cache (a hardlink fails in a
                # cloud-synced or redirected folder).
                "--link-mode",
                "copy",
                "--python",
                str(self.layout.python(version)),
                # By its plain name, from its own folder: uv cuts a path at its
                # first space ("Application Support", "OneDrive - ...").
                "-r",
                staged.requirements.name,
            ],
            "installing the package",
            1800,
            cwd=staged.requirements.parent,
        )
        self._check_version(version)
        if hasattr(os, "sync"):
            os.sync()
        record = {
            "version": version,
            "wheel_sha256": staged.wheel_sha256,
            "installed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        _write_line(folder / _COMPLETE, json.dumps(record))

    def _check_version(self, version: str) -> None:
        result = self._must(
            [str(self.layout.executable(version)), "--version"], "checking the new version", 120
        )
        said = result.stdout.strip()
        if said != f"UM-Codex {version}":
            raise UpdateFailed(f"The installed UM-Codex says {said!r}, not {version}.")

    def refresh_launchers(self, version: str) -> bool:
        """The app or shortcuts, as `version` (now in use) writes them: its own
        `um-codex launchers --refresh`. Never fails the update or rollback; if
        they can't be rewritten, it says what to do."""
        try:
            done = self._run([str(self.layout.executable(version)), "launchers", "--refresh"], timeout=300)
        except (OSError, subprocess.SubprocessError) as error:
            done = subprocess.CompletedProcess([], 1, "", f"{type(error).__name__}: {error}")
        for line in (done.stdout or "").strip().splitlines():
            self.say(line)
        if done.returncode == 0:
            return True
        app = "app" if self.platform == "darwin" else "Start menu and Desktop shortcuts"
        if "launchers" in (done.stderr or "") and "invalid choice" in (done.stderr or ""):
            # A version from before launchers.py (0.1.0-alpha.1): this code,
            # newer, writes the launchers as that version's installer did
            # (launcher format 1: Terminal, `launch --from-app`).
            from umcodex.launchers import Launchers

            self.say(f"UM-Codex {version} opens in a terminal window: the UM-Codex {app} goes back to that.")
            older = Launchers(self.layout.root, platform=self.platform, say=self.say, fmt=1)
            report = older.refresh(quiet=True)
            if report.ok:
                return True
            how = self.layout.command
            self.say(
                f"The UM-Codex {app} won't open UM-Codex {version}. To start it, open "
                f"{'Terminal' if self.platform == 'darwin' else 'Windows PowerShell'} and run: {how} "
                "(or run um-codex update to go back to the newer version)."
            )
        else:
            for line in (done.stderr or "").strip().splitlines()[-5:]:
                self.say(f"  {line}")
            self.say(
                f"The UM-Codex {app} couldn't all be brought up to date (see above). UM-Codex "
                f"{version} is installed and works: run um-codex launchers --refresh to try again, or "
                "run the UM-Codex installer again."
            )
        return False

    def _pull(self, version: str) -> bool:
        """The version's own `um-codex pull`, its progress shown."""
        try:
            done = self._run([str(self.layout.executable(version)), "pull"], timeout=3600, capture=False)
        except (OSError, subprocess.SubprocessError):
            return False
        return done.returncode == 0

    def _must(
        self, command: list[str], what: str, timeout: float, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = self._run(command, timeout=timeout, cwd=cwd)
        except (OSError, subprocess.SubprocessError) as error:
            raise UpdateFailed(
                f"The update stopped while {what} ({type(error).__name__}). "
                f"UM-Codex {self.current} is still the one in use."
            ) from None
        if result.returncode != 0:
            for line in (result.stderr or result.stdout or "").strip().splitlines()[-15:]:
                self.say(f"  {line}")
            raise UpdateFailed(
                f"The update stopped while {what}. UM-Codex {self.current} is still the one in use."
            )
        return result

    @contextlib.contextmanager
    def _exclusive(self):
        """One update (or rollback) at a time."""
        lock = LaunchLock(self.layout.root / "update.lock")
        if not lock.acquire():
            yield False
            return
        try:
            yield True
        finally:
            lock.release()


def _close_launcher_window(data: Path) -> None:
    """A launcher window (`um-codex ui`) runs this version's code, and on
    Windows holds its files open: it's closed before a switch (the app opens
    the new version's next time)."""
    from umcodex.ui.server import close_running

    close_running(data)


# ------------------------------------------------------------------ at launch


def remember_check(data: Path, available: str | None, now: float | None = None) -> None:
    """When the last check was, and what it found (for the launch-time line)."""
    with contextlib.suppress(OSError):
        data.mkdir(parents=True, exist_ok=True)
        path = data / NOTICE_FILE
        temporary = path.with_name(f".{NOTICE_FILE}.new")
        record = {"checked_at": time.time() if now is None else now, "available": available}
        temporary.write_text(json.dumps(record) + "\n", encoding="utf-8")
        os.replace(temporary, path)


def _remembered(data: Path) -> tuple[float, str | None] | None:
    with contextlib.suppress(OSError, ValueError, AttributeError):
        record = json.loads((data / NOTICE_FILE).read_text(encoding="utf-8"))
        checked, available = record.get("checked_at"), record.get("available")
        if isinstance(checked, int | float):
            return float(checked), available if isinstance(available, str) else None
    return None


def launch_notice(
    say: Say = print,
    *,
    layout: Layout | None = None,
    keys: Sequence[str] | None = None,
    source: Callable[[], ReleaseSource] | None = None,
    current: str = __version__,
    data: Path | None = None,
    wait: float = NOTICE_WAIT_SECONDS,
    now: Callable[[], float] = time.time,
) -> None:
    """At a launch: one line if a newer release is out. GitHub is asked at most
    once a day, and the launch never waits more than `wait` seconds for it; a
    check that takes longer finishes in the background and is remembered for
    the next launch. Never asked for a development copy, or while no release
    key is pinned. Never raises."""
    try:
        if os.environ.get(NO_CHECK_ENV):
            return
        data = data if data is not None else data_dir()
        layout = layout or Layout(install_root())
        if layout.running_version() is None:
            return
        try:
            pinned = pinned_keys(keys)
        except NotConfigured:
            return
        remembered = _remembered(data)
        found: list[str | None] = []
        if remembered is not None and 0 <= now() - remembered[0] < NOTICE_EVERY_SECONDS:
            found.append(remembered[1])
        else:
            remember_check(data, remembered[1] if remembered else None, now())  # once a day, even offline

            def check() -> None:
                try:
                    # The launch waits `wait` at most; this may go on, in the background.
                    asked = source() if source else ReleaseSource(timeout=httpx.Timeout(10))
                    offer = find_update(asked, current, pinned)
                except Exception:  # offline, rate-limited, a bad release: nothing to say
                    return
                version = offer.release.version if offer else None
                remember_check(data, version, now())
                found.append(version)

            worker = threading.Thread(target=check, name="update-check", daemon=True)
            worker.start()
            worker.join(wait)
        version = found[0] if found else None
        if version and is_newer(version, current):
            say(f"UM-Codex {version} is available: run um-codex update")
    except Exception:  # a notice must never stop a launch
        return
