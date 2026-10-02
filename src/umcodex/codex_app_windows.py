"""M6 on Windows (experimental): UM-Codex's copy of the Codex app there.

The app is the Microsoft Store (MSIX) package `OpenAI.Codex`. Its "Codex
Demo" launcher, which opens a separate copy on a Mac, is Mac only, so the
copy is started the way that launcher does it, by hand: the package's
ChatGPT.exe itself (CreateProcess), with CODEX_HOME and
CODEX_ELECTRON_USER_DATA_PATH in its environment and `--user-data-dir`.
Checked on 2026-10-02 with app 26.928.4866.0 (docs/DESIGN.md, M6):

- Run that way, the copy runs beside the person's own, with its own home
  and profile, but without the package's identity: what's tied to the
  package (its sandbox service, Computer Use) doesn't work in it. Sandbox
  mode needs neither. It shares the app's copied runtimes
  (%LOCALAPPDATA%\\OpenAI\\Codex) with the person's copy.
- Started by the package instead (its AUMID, Invoke-CommandInDesktopPackage),
  the app gets none of our environment and uses the person's ~/.codex: the
  hands-on test changed it that way. So that's never done here, and
  `check_paths` refuses a home or profile that would be the person's own.

So: the package is looked up afresh at every launch (a Store update moves
it) and its publisher checked; the copy is started only with folders under
UM-Codex's data folder; it's found again by its profile folder in its
command line, and stopped by its process id only.
"""

from __future__ import annotations

import contextlib
import json
import ntpath
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

Runner = Callable[..., subprocess.CompletedProcess]

PACKAGE = "OpenAI.Codex"
# The Store package's family and its publisher's certificate name, as
# Get-AppxPackage reports them (the family's suffix is a hash of the publisher).
FAMILY = "OpenAI.Codex_2p2nqsd0c76g0"
PUBLISHER = "CN=50BDFD77-8903-4850-9FFE-6E8522F64D5B"
EXE = "ChatGPT.exe"  # in the package's app\ folder

_VERSION = re.compile(rf"{re.escape(PACKAGE)}_(\d+(?:\.\d+)+)_", re.IGNORECASE)


def system_dir() -> PureWindowsPath:
    """Windows' System32 (a Windows path on any OS, so tests read the same)."""
    return PureWindowsPath(os.environ.get("SYSTEMROOT") or r"C:\Windows") / "System32"


def powershell() -> str:
    """Windows PowerShell, by its full path (never looked up by name)."""
    return str(system_dir() / "WindowsPowerShell" / "v1.0" / "powershell.exe")


def hidden() -> int:
    """No console window for a helper (0 where there's no such flag)."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _powershell(command: str, run: Runner, timeout: float = 30) -> subprocess.CompletedProcess | None:
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        return run(
            [powershell(), "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, creationflags=hidden(),
        )  # fmt: skip
    return None


# --- The app ---------------------------------------------------------------------


@dataclass(frozen=True)
class Package:
    folder: Path
    family: str
    publisher: str

    @property
    def exe(self) -> Path:
        return self.folder / "app" / EXE


def package(run: Runner = subprocess.run) -> Package | None:
    """The installed Store package, as Windows reports it now."""
    done = _powershell(
        f"Get-AppxPackage -Name {PACKAGE} | Select-Object -First 1 "
        "InstallLocation, PackageFamilyName, Publisher | ConvertTo-Json -Compress",
        run,
    )
    if done is None or done.returncode != 0 or not (done.stdout or "").strip():
        return None
    try:
        info = json.loads(done.stdout)
    except ValueError:
        return None
    if not isinstance(info, dict):
        return None
    folder, family, publisher = (info.get(k) for k in ("InstallLocation", "PackageFamilyName", "Publisher"))
    if not all(isinstance(v, str) and v for v in (folder, family, publisher)):
        return None
    return Package(Path(folder), family, publisher)  # type: ignore[arg-type]


def find_app(run: Runner = subprocess.run) -> Path | None:
    """The package's ChatGPT.exe, looked up afresh (never a saved path), and
    only when the package is OpenAI's Store package."""
    found = package(run)
    if found is None:
        return None
    if found.family.lower() != FAMILY.lower() or found.publisher != PUBLISHER:
        return None
    return found.exe if found.exe.is_file() else None


def version(app: Path) -> str | None:
    """The package's version, from its folder's name."""
    found = _VERSION.search(str(app))
    return found.group(1) if found else None


def is_windows_app(app: Path) -> bool:
    return app.name.lower() == EXE.lower()


def bundled_codex(app: Path, home: Path) -> tuple[Path, dict[str, str]]:
    """The app's own codex.exe, and a bare environment with a throwaway home."""
    root = str(system_dir().parent)
    env = {
        "CODEX_HOME": str(home), "HOME": str(home), "USERPROFILE": str(home),
        "SystemRoot": root, "PATH": str(system_dir()),
    }  # fmt: skip
    return app.parent / "resources" / "codex.exe", env


# --- Starting the copy -----------------------------------------------------------------


class UnsafePaths(ValueError):
    """The copy's home or profile would be the person's own."""


def _within(path: Path, folder: Path) -> bool:
    path_s, folder_s = os.path.normcase(str(path)), os.path.normcase(str(folder))
    return path_s == folder_s or path_s.startswith(folder_s.rstrip("\\/") + os.sep)


def check_paths(home: Path, user_data: Path, data: Path, person: Path, app_data: Path | None) -> None:
    """Refuse (UnsafePaths) unless the copy's CODEX_HOME and profile are
    inside UM-Codex's data folder and are neither the person's ~/.codex nor
    the app's own profile (%APPDATA%\\Codex...), nor hold them."""
    home, user_data, data = (Path(os.path.abspath(p)) for p in (home, user_data, data))
    theirs = [Path(os.path.abspath(person / ".codex"))]
    if app_data is not None:
        theirs += [Path(os.path.abspath(p)) for p in Path(app_data).glob("Codex*")]
        theirs.append(Path(os.path.abspath(Path(app_data) / "Codex")))
    for mine in (home, user_data):
        if not _within(mine, data) or mine == data:
            raise UnsafePaths(f"{mine} isn't inside UM-Codex's data folder")
        for other in theirs:
            if _within(mine, other) or _within(other, mine):
                raise UnsafePaths(f"{mine} would be the Codex app's own {other}")


# Variables that could lead the copy somewhere other than UM-Codex's own
# folders and local responder: Codex's own, OpenAI's, and proxies (the copy
# only talks to 127.0.0.1 and runs ssh, which doesn't use them).
_LEFT_OUT = ("CODEX_", "OPENAI_")
_PROXIES = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "FTP_PROXY", "ELECTRON_RUN_AS_NODE"}


def _left_out(key: str) -> bool:
    key = key.upper()
    return key.startswith(_LEFT_OUT) or key in _PROXIES


def open_command(
    app: Path, home: Path, user_data: Path, link: str | None, environ: dict[str, str]
) -> tuple[list[str], dict[str, str]]:
    """The copy: ChatGPT.exe itself, with its two variables set and the
    person's other CODEX_, OPENAI_ and proxy variables left out (nothing
    leads it elsewhere)."""
    env = {key: value for key, value in environ.items() if not _left_out(key)}
    # The app runs the first ssh.exe on its PATH. Git for Windows' (usr\bin,
    # OpenSSH 10.3) runs a ProxyCommand through /bin/sh or $SHELL, which
    # loses the Windows path's backslashes (seen 2026-10-02): so Windows'
    # own OpenSSH goes first, and SHELL is left out.
    path = next((value for key, value in env.items() if key.upper() == "PATH"), "")
    env = {key: value for key, value in env.items() if key.upper() not in ("PATH", "SHELL")}
    env["PATH"] = ";".join(part for part in (str(system_dir() / "OpenSSH"), path) if part)
    env["CODEX_HOME"] = str(home)
    env["CODEX_ELECTRON_USER_DATA_PATH"] = str(user_data)
    return [str(app), f"--user-data-dir={user_data}", *([link] if link else [])], env


def start(command: list[str], env: dict[str, str], popen: Callable[..., object]) -> None:
    """Started and left running (CreateProcess, detached: never the package's
    activation). Raises OSError."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0x8)
    flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
    popen(
        command,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )


# --- The running copy ------------------------------------------------------------------

# --user-data-dir=<folder> in a Windows command line: the whole argument
# quoted (as subprocess quotes one with a space), the value quoted, or bare.
_PROFILE_ARG = re.compile(r'"--user-data-dir=([^"]*)"|--user-data-dir="([^"]*)"|--user-data-dir=(\S+)')


def _same_folder(path: str) -> str:
    return ntpath.normcase(ntpath.normpath(path.strip()))


def _spellings(folder: Path) -> set[str]:
    """The folder as Windows may write it: as given, and its long and short
    (8.3) forms when Windows can tell them."""
    names = {str(folder)}
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        for call in (kernel32.GetLongPathNameW, kernel32.GetShortPathNameW):
            buffer = ctypes.create_unicode_buffer(1024)
            if call(str(folder), buffer, 1024):
                names.add(buffer.value)
    return {_same_folder(name) for name in names}


def profile_of(command_line: str) -> str | None:
    """The --user-data-dir of a main ChatGPT.exe process (None for its
    helpers, which have --type=, and for one without: the person's own)."""
    if " --type=" in command_line:
        return None
    found = _PROFILE_ARG.search(command_line)
    if found is None:
        return None
    return next(group for group in found.groups() if group is not None)


def _processes(run: Runner) -> list[tuple[int, str]]:
    done = _powershell(
        f"Get-CimInstance Win32_Process -Filter \"Name='{EXE}'\" | "
        'ForEach-Object { "$($_.ProcessId) $($_.CommandLine)" }',
        run,
    )
    found = []
    for line in (done.stdout or "").splitlines() if done is not None else []:
        pid, _, args = line.strip().partition(" ")
        if pid.isdigit():
            found.append((int(pid), args))
    return found


def find_copy(user_data: Path, run: Runner = subprocess.run, *, pid: int | None = None) -> int | None:
    """The PID of the copy's main process: a ChatGPT.exe whose --user-data-dir
    is the copy's profile folder (compared as Windows does: case, quotes,
    `..`, 8.3 names). With `pid`, only that process is considered."""
    ours = _spellings(user_data)
    for found, args in _processes(run):
        if pid is not None and found != pid:
            continue
        profile = profile_of(args)
        if profile is not None and _same_folder(profile) in ours:
            return found
    return None


RUNTIME_STAGING = "codex-runtime-install-*"  # the app's own download of its runtime


def runtime_update_running(home: Path, now: float, recent: float = 1800.0) -> bool:
    """Whether the app (ours or the person's) is updating its runtime in the
    shared ~/.cache/codex-runtimes now: a staging folder made within
    `recent` seconds (the app removes it when it's done). Its files can't
    tell: they're extracted with the archive's own old times (seen
    2026-10-02: a 500 MB download, then about 20,000 files). Stopping the
    copy then would leave a partial update (over 1 GB) behind."""
    with contextlib.suppress(OSError):
        for staging in (home / ".cache" / "codex-runtimes").glob(RUNTIME_STAGING):
            info = staging.stat()
            made = getattr(info, "st_birthtime", info.st_ctime)  # creation time on Windows
            if now - made < recent:
                return True
    return False


def bring_forward(pid: int, run: Runner = subprocess.run) -> bool:
    done = _powershell(f"(New-Object -ComObject WScript.Shell).AppActivate({int(pid)})", run, timeout=10)
    return done is not None and done.returncode == 0 and done.stdout.strip() == "True"


def stop(pid: int, user_data: Path, run: Runner = subprocess.run) -> bool:
    """End the copy (that process and its children) by its PID, only if that
    PID is still the copy's main process right now (a number can be reused)."""
    if find_copy(user_data, run, pid=pid) != pid:
        return False
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        run(
            [str(system_dir() / "taskkill.exe"), "/PID", str(int(pid)), "/T", "/F"],
            capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL, creationflags=hidden(),
        )  # fmt: skip
    # taskkill's own code isn't enough: with /T it reports a helper that was
    # already ending as a failure though the copy itself ended (live test).
    return find_copy(user_data, run, pid=pid) is None
