"""What the UM-Codex app (Mac) and shortcuts (Windows) contain, and keeping
them up to date. The one place that says it: the installers write them with
`um-codex launchers --write`, and `um-codex update` (and `--rollback`) brings
them up to date with `um-codex launchers --refresh`, run by the version just
switched to. So the two can't drift apart.

- **Mac**: `UM-Codex.app` in /Applications or ~/Applications (the installer
  chooses), bundle id `edu.umich.umcodex`, no Dock icon (`LSUIElement`), its
  own copy of the icon, and a script that runs `<root>/bin/um-codex ui
  --detach` (the launcher window, in the browser). The Desktop shortcut is a
  link to the app, so it never needs rewriting.
- **Windows**: `UM-Codex.lnk` in the Start menu and on the Desktop: Windows
  PowerShell, hidden, runs `<root>\\bin\\um-codex.exe ui --detach`. Written
  and read through WScript.Shell, in a Windows PowerShell this starts
  (nothing to install).

Both run the command in `<root>/bin`, never a version's own folder: it runs
the version `current` names, so an update doesn't need a new launcher unless
the launcher itself changes (FORMAT).

A refresh only ever changes launchers that are this install's own (the app's
bundle id and its script naming this install's command; a shortcut whose
command line names this program folder), only where they already are, and
never through a link: something else of that name, another account's app, or
a launcher the person removed, is left as it is.

`<root>/launchers` records the FORMAT they were last written in, and whether
that worked. A launcher written by an older installer (alpha.1's opened
Terminal, `launch --from-app`) predates it, so the first `um-codex` or
`um-codex ui` of a newer version whose FORMAT differs refreshes them
(`refresh_if_differs`): an update made by alpha.1's own updater never
refreshed them. If that fails it says so once, then tries again at most once
a day, saying so only in the log.

FORMAT 1 (alpha.1's) can still be written: a rollback to a version without
the `launchers` command has the newer code that's rolling back write it, so
that version's launchers still open it.
"""

from __future__ import annotations

import base64
import contextlib
import difflib
import json
import logging
import os
import plistlib
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any

# 1: alpha.1's (Terminal, `launch --from-app`). 2: the launcher window, `ui --detach`.
FORMAT = 2
FORMATS = (1, 2)
NAME = "UM-Codex"
BUNDLE_ID = "edu.umich.umcodex"
FORMAT_KEY = "UMCodexLauncherFormat"
DESCRIPTION = "UM-Codex: Codex on U-M GPT Toolkit, in a Docker container"
MARKER = "launchers"
RETRY_SECONDS = 24 * 60 * 60
# For tests: stand-ins for /Applications (as the installers' tests), the
# Start menu's Programs folder and the Desktop, and for macOS's lsregister
# (empty: not run).
SYSTEM_APPS_ENV = "UMCODEX_SYSTEM_APPLICATIONS"
START_MENU_ENV = "UMCODEX_START_MENU"
DESKTOP_ENV = "UMCODEX_DESKTOP"
LSREGISTER_ENV = "UMCODEX_LSREGISTER"
LSREGISTER = (
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
)
BRANDING = Path(__file__).resolve().parent / "branding"

Say = Callable[[str], None]
log = logging.getLogger(__name__)


# ------------------------------------------------------------------ contents


def sh_quote(text: str) -> str:
    """Single-quoted for sh: `'\\''` for a quote, as in /Users/o'brien."""
    return "'" + text.replace("'", "'\\''") + "'"


def ps_quote(text: str) -> str:
    """For inside a single-quoted PowerShell string: each kind of single quote
    PowerShell accepts, doubled (as CodeGeneration.EscapeSingleQuotedStringContent)."""
    for quote in "'\u2018\u2019\u201a\u201b":
        text = text.replace(quote, quote * 2)
    return text


def mac_command(root: Path) -> Path:
    return root / "bin" / "um-codex"


def mac_icon() -> bytes | None:
    with contextlib.suppress(OSError):
        return (BRANDING / f"{NAME}.icns").read_bytes()
    return None


# alpha.1's app script (installer/macos/install.sh at v0.1.0-alpha.1), for FORMAT 1.
_ALPHA_1_SCRIPT = """#!/bin/sh
exec osascript - @COMMAND@ <<'OSA'
on run argv
  set command to (quoted form of item 1 of argv) & " launch --from-app"
  set wasRunning to application "Terminal" is running
  tell application "Terminal"
    if wasRunning then
      do script command
    else
      -- Starting Terminal opens its own first window: use that one, so
      -- there's one window, not that one plus another for UM-Codex.
      activate
      repeat 50 times
        if (count of windows) > 0 then exit repeat
        delay 0.1
      end repeat
      if (count of windows) > 0 then
        do script command in window 1
      else
        do script command
      end if
    end if
    activate
  end tell
end run
OSA
"""


def mac_app_files(root: Path, icon: bytes | None, fmt: int = FORMAT) -> dict[str, bytes]:
    """The app's files, by their path inside the bundle, in launcher format `fmt`."""
    extra = ""
    if fmt >= 2:
        extra = f"""  <key>LSUIElement</key><true/>
  <key>{FORMAT_KEY}</key><string>{fmt}</string>
"""
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>{NAME}</string>
  <key>CFBundleDisplayName</key><string>{NAME}</string>
  <key>CFBundleIdentifier</key><string>{BUNDLE_ID}</string>
  <key>CFBundleExecutable</key><string>{NAME}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>{NAME if icon is not None else ""}</string>
{extra}</dict></plist>
"""
    command = sh_quote(str(mac_command(root)))
    if fmt == 1:
        script = _ALPHA_1_SCRIPT.replace("@COMMAND@", command)
    else:
        # The launcher window (`um-codex ui --detach`): a page in the browser,
        # served by UM-Codex on this computer. It runs in the background, so
        # no Terminal window opens until a setup is started, and the app has
        # no Dock icon (LSUIElement).
        script = f"""#!/bin/sh
# Written by UM-Codex (launcher format {fmt}); `um-codex update` rewrites it.
exec {command} ui --detach
"""
    files = {
        "Contents/Info.plist": plist.encode("utf-8"),
        f"Contents/MacOS/{NAME}": script.encode("utf-8"),
    }
    if icon is not None:
        files[f"Contents/Resources/{NAME}.icns"] = icon
    return files


# The folders inside the bundle that are written to: never a link.
_APP_FOLDERS = ("Contents", "Contents/MacOS", "Contents/Resources")


class LinkRefused(OSError):
    """A folder that would be written in, or read from, is a link."""


def _is_link(path: Path) -> bool:
    try:
        return stat.S_ISLNK(os.lstat(path).st_mode)
    except FileNotFoundError:
        return False


def _real_folder(path: Path) -> None:
    """Raises LinkRefused unless `path` is a folder itself, not a link to one
    (made if it isn't there)."""
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        path.mkdir(parents=True)
        mode = os.lstat(path).st_mode
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise LinkRefused(f"{path} is a link or not a folder")


def write_file(path: Path, content: bytes, mode: int = 0o644) -> None:
    """Written whole, never through a link: a new file with a name of its own
    (mkstemp: O_CREAT|O_EXCL) in a folder that isn't a link, then renamed over
    `path` (which replaces a link there rather than following it)."""
    _real_folder(path.parent)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
            file.flush()
            if hasattr(os, "fchmod"):
                os.fchmod(file.fileno(), mode)
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def _read_inside(app: Path, name: str) -> bytes:
    """A file in the bundle, read only if neither it nor a folder on the way is a link."""
    parts = name.split("/")
    for depth in range(1, len(parts) + 1):
        if _is_link(app.joinpath(*parts[:depth])):
            raise LinkRefused(f"{app / name} is reached through a link")
    return (app / name).read_bytes()


def is_our_app(app: Path, root: Path) -> bool:
    """This install's UM-Codex.app: not a link, UM-Codex's bundle id, and a
    script that runs this install's command (alpha.1's names it too), so
    another account's app in a shared /Applications is never taken for ours."""
    if _is_link(app) or not app.is_dir():
        return False
    try:
        info = plistlib.loads(_read_inside(app, "Contents/Info.plist"))
        script = _read_inside(app, f"Contents/MacOS/{NAME}")
    except (OSError, ValueError, plistlib.InvalidFileException):
        return False
    if not isinstance(info, dict) or info.get("CFBundleIdentifier") != BUNDLE_ID:
        return False
    return sh_quote(str(mac_command(root))).encode("utf-8") in script


def register_app(app: Path) -> None:
    """Tells Launch Services to read the app again (LSUIElement, the icon).
    Best effort: skipped where lsregister isn't there."""
    program = os.environ.get(LSREGISTER_ENV, LSREGISTER)
    if sys.platform != "darwin" or not program or not os.path.isfile(program):
        return
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            [program, "-f", str(app)], capture_output=True, timeout=30, check=False, stdin=subprocess.DEVNULL
        )


@dataclass(frozen=True)
class Shortcut:
    """A Windows shortcut's settings, as WScript.Shell reads and writes them."""

    target: str
    arguments: str
    working_directory: str
    description: str
    icon_location: str
    window_style: int

    def to_json(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "arguments": self.arguments,
            "workingDirectory": self.working_directory,
            "description": self.description,
            "iconLocation": self.icon_location,
            "windowStyle": self.window_style,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Shortcut:
        style = data.get("windowStyle")
        return cls(
            target=str(data.get("target") or ""),
            arguments=str(data.get("arguments") or ""),
            working_directory=str(data.get("workingDirectory") or ""),
            description=str(data.get("description") or ""),
            icon_location=str(data.get("iconLocation") or ""),
            window_style=style if isinstance(style, int) else 0,
        )

    def same_as(self, other: Shortcut) -> bool:
        """Windows compares paths without case."""
        return (
            self.target.lower() == other.target.lower()
            and self.arguments == other.arguments
            and self.working_directory.lower() == other.working_directory.lower()
            and self.description == other.description
            and self.icon_location.lower() == other.icon_location.lower()
            and self.window_style == other.window_style
        )


def windows_powershell() -> Path:
    """Windows' own PowerShell 5.1, by full path (never looked up by name)."""
    # (Windows' environment variable names have no case.)
    system_root = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR") or r"C:\Windows"
    return Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def windows_terminal() -> str:
    """Windows Terminal's command (an app execution alias), if it's there:
    FORMAT 1's shortcuts opened in it."""
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return ""
    program = Path(local) / "Microsoft" / "WindowsApps" / "wt.exe"
    return str(program) if os.path.lexists(program) else ""


def windows_icon() -> bytes | None:
    with contextlib.suppress(OSError):
        return (BRANDING / f"{NAME}.ico").read_bytes()
    return None


def windows_marker(root: Path | PureWindowsPath) -> str:
    """What every UM-Codex shortcut's command line has: the program folder,
    single-quoted, then a backslash. alpha.1's (`'<root>\\current'`, and in
    Windows Terminal with each ";" written "\\;") and this one's
    (`'<root>\\bin\\um-codex.exe'`) alike."""
    return f"'{ps_quote(str(PureWindowsPath(root)))}\\"


def is_our_shortcut(shortcut: Shortcut, root: Path | PureWindowsPath) -> bool:
    marker = windows_marker(root).lower()
    arguments = shortcut.arguments.lower()
    return marker in arguments or marker.replace(";", r"\;") in arguments


def windows_shortcut(
    root: Path | PureWindowsPath,
    *,
    home: str,
    powershell: str,
    icon: bool,
    fmt: int = FORMAT,
    terminal: str = "",
) -> Shortcut:
    """The Start menu and Desktop shortcut. FORMAT 2: Windows PowerShell,
    hidden (it may show for a moment) and minimized, runs bin\\um-codex.exe,
    which runs the version `current` names, with PYTHONUTF8. FORMAT 1
    (alpha.1's install.ps1): Windows Terminal (`terminal`, each ";" as "\\;")
    or Windows PowerShell, -NoExit, runs `current`'s um-codex.exe `launch
    --from-app`. No double quotes inside -Command "..." (Windows can't have
    one in a path)."""
    root = PureWindowsPath(root)
    icon_file = root / "icons" / f"{NAME}.ico"
    icon_location = f"{icon_file},0" if icon else ""
    if fmt == 1:
        quoted = ps_quote(str(root))
        launch = (
            f"$Host.UI.RawUI.WindowTitle = '{NAME}'; "
            f"$v = ([string](Get-Content -LiteralPath '{quoted}\\current' -TotalCount 1)).Trim(); "
            f"$Env:PYTHONUTF8 = '1'; "
            f"& ('{quoted}\\versions\\' + $v + '\\Scripts\\um-codex.exe') launch --from-app"
        )
        arguments = f'-NoProfile -NoExit -Command "{launch}"'
        target = powershell
        if terminal:
            target = terminal
            arguments = f'-w new new-tab --title {NAME} -d "{home}" -- "{powershell}" {arguments}'.replace(
                ";", r"\;"
            )
        return Shortcut(target, arguments, home, DESCRIPTION, icon_location, 1)
    command = root / "bin" / "um-codex.exe"
    launch = f"$Env:PYTHONUTF8 = '1'; & '{ps_quote(str(command))}' ui --detach"
    return Shortcut(
        target=powershell,
        arguments=f'-NoProfile -WindowStyle Hidden -Command "{launch}"',
        working_directory=home,
        description=DESCRIPTION,
        icon_location=icon_location,
        window_style=7,  # minimized: the hidden PowerShell window doesn't flash up
    )


# ------------------------------------------------------------------ Windows Script Host, through PowerShell

# Reads the shortcuts at the paths given (and, with desktopName, the one of
# that name on the Desktop, which may be redirected, to OneDrive say), and says
# where the Desktop and the home folder are; or writes shortcuts. Its input
# and output are UTF-8 JSON in base64, so no path or setting is ever quoted on
# a command line or read in the console's code page.
_SHORTCUTS_PS = r"""
$ErrorActionPreference = 'Stop'
$in = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('@INPUT@')) | ConvertFrom-Json
$shell = New-Object -ComObject WScript.Shell
$out = @{ desktop = [Environment]::GetFolderPath('Desktop');
          home = [Environment]::GetFolderPath('UserProfile'); read = @(); wrote = @() }
$paths = @($in.read)
if ($in.desktopName -and $out.desktop) { $paths += Join-Path $out.desktop $in.desktopName }
foreach ($path in $paths) {
    if (-not $path) { continue }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
    $s = $shell.CreateShortcut($path)
    $out.read += , @{ path = $path; target = $s.TargetPath; arguments = $s.Arguments;
        workingDirectory = $s.WorkingDirectory; description = $s.Description;
        iconLocation = $s.IconLocation; windowStyle = [int]$s.WindowStyle }
}
foreach ($link in @($in.write)) {
    if (-not $link) { continue }
    try {
        $folder = Split-Path -Parent $link.path
        if (-not (Test-Path -LiteralPath $folder)) {
            New-Item -ItemType Directory -Force -Path $folder | Out-Null
        }
        $s = $shell.CreateShortcut($link.path)
        $s.TargetPath = $link.target
        $s.Arguments = $link.arguments
        $s.WorkingDirectory = $link.workingDirectory
        $s.Description = $link.description
        $s.WindowStyle = [int]$link.windowStyle
        if ($link.iconLocation) { $s.IconLocation = $link.iconLocation }
        $s.Save()
        $out.wrote += , @{ path = $link.path; error = '' }
    } catch {
        $out.wrote += , @{ path = $link.path; error = "$($_.Exception.Message)" }
    }
}
[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($out | ConvertTo-Json -Depth 5 -Compress)))
"""

ShortcutHost = Callable[[dict[str, Any]], dict[str, Any]]


class ShortcutError(RuntimeError):
    """Windows PowerShell couldn't read or write the shortcuts."""


def run_shortcut_host(request: dict[str, Any]) -> dict[str, Any]:
    """Runs _SHORTCUTS_PS in Windows PowerShell with `request` (read: paths;
    write: shortcuts), and returns what it says."""
    payload = base64.b64encode(json.dumps(request).encode("utf-8")).decode("ascii")
    script = _SHORTCUTS_PS.replace("@INPUT@", payload)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        done = subprocess.run(
            [str(windows_powershell()), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ShortcutError(f"Windows PowerShell couldn't run ({type(error).__name__}: {error})") from None
    lines = [line.strip() for line in done.stdout.splitlines() if line.strip()]
    if done.returncode != 0 or not lines:
        why = (done.stderr or done.stdout or "").strip().splitlines()
        raise ShortcutError(f"Windows PowerShell said: {why[0] if why else f'exit code {done.returncode}'}")
    try:
        answer = json.loads(base64.b64decode(lines[-1]).decode("utf-8"))
    except ValueError:
        raise ShortcutError("Windows PowerShell's answer wasn't readable.") from None
    if not isinstance(answer, dict):
        raise ShortcutError("Windows PowerShell's answer wasn't readable.")
    return answer


def _listed(value: Any) -> list[dict[str, Any]]:
    """PowerShell 5.1 may write a one-item list as the item itself."""
    if isinstance(value, dict):
        return [value]
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


# ------------------------------------------------------------------ refresh


@dataclass
class Report:
    changed: list[Path] = field(default_factory=list)
    current: list[Path] = field(default_factory=list)
    foreign: list[Path] = field(default_factory=list)
    failed: list[Path] = field(default_factory=list)
    # An older copy that couldn't be changed while another copy is up to date.
    skipped: list[Path] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


@dataclass(frozen=True)
class Record:
    """`<root>/launchers`: the format last written (or tried), whether it
    worked, and when."""

    format: int
    ok: bool
    at: float


class Launchers:
    """This install's app or shortcuts, for the program folder `root`, in
    launcher format `fmt` (FORMAT, or 1 for a rollback to alpha.1)."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        platform: str | None = None,
        say: Say = print,
        home: Path | None = None,
        shortcut_host: ShortcutHost = run_shortcut_host,
        fmt: int = FORMAT,
        now: Callable[[], float] = time.time,
    ) -> None:
        if root is None:
            from umcodex.update import install_root

            root = install_root()
        if fmt not in FORMATS:
            raise ValueError(f"no launcher format {fmt}")
        self.root = root
        self.platform = platform or sys.platform
        self.say = say
        self.home = home if home is not None else Path.home()
        self._host = shortcut_host
        self.format = fmt
        self.now = now

    # Where they are ----------------------------------------------------------

    def mac_apps(self) -> list[Path]:
        """Where the installer puts the app: /Applications, else ~/Applications."""
        system = Path(os.environ.get(SYSTEM_APPS_ENV) or "/Applications")
        return [system / f"{NAME}.app", self.home / "Applications" / f"{NAME}.app"]

    def _start_menu(self) -> Path:
        override = os.environ.get(START_MENU_ENV)
        if override:
            return Path(override) / f"{NAME}.lnk"
        app_data = os.environ.get("APPDATA") or str(self.home / "AppData" / "Roaming")
        return Path(app_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{NAME}.lnk"

    def _read_windows(self) -> tuple[list[Path], dict[str, Any]]:
        """The Start menu's and the Desktop's UM-Codex.lnk, and what's in them."""
        places = [self._start_menu()]
        desktop = os.environ.get(DESKTOP_ENV)
        if desktop:
            places.append(Path(desktop) / f"{NAME}.lnk")
            answer = self._host({"read": [str(p) for p in places]})
        else:
            answer = self._host({"read": [str(places[0])], "desktopName": f"{NAME}.lnk"})
            if answer.get("desktop"):
                places.append(Path(str(answer["desktop"])) / f"{NAME}.lnk")
        return places, answer

    @property
    def _what(self) -> str:
        return (
            "it opens UM-Codex's window in your browser"
            if self.format >= 2
            else "it opens UM-Codex in a Terminal window, as that version expects"
        )

    # The two commands --------------------------------------------------------

    def refresh(self, *, dry_run: bool = False, quiet: bool = False) -> Report:
        """Rewrite this install's own launchers, where they are, if they aren't
        what format `fmt` says. `quiet`: nothing said about launchers that are
        up to date or not there (at a launch)."""
        if self.platform == "darwin":
            report = self._refresh_mac(dry_run=dry_run, quiet=quiet)
        elif self.platform == "win32":
            report = self._refresh_windows(dry_run=dry_run, quiet=quiet)
        else:
            if not quiet:
                self.say("UM-Codex has an app or shortcuts only on Mac and Windows.")
            return Report()
        if report.failed:
            fix = (
                "Run the UM-Codex installer again to put it right"
                if self.platform == "darwin"
                else "Run the UM-Codex installer again to put them right"
            )
            self.say(
                f"{fix} (UM-Codex itself is installed and works: you can also run um-codex in a "
                "terminal), or run um-codex launchers --refresh to try again."
            )
        if not dry_run:
            self.remember(report.ok)
        return report

    def write(self, places: Sequence[Path]) -> Report:
        """The installers': write the app (Mac: a bundle folder) or shortcuts
        (Windows: .lnk files) at `places`, whatever is there (the installer has
        checked it's this install's own, or nothing)."""
        report = Report()
        if self.platform == "darwin":
            files = mac_app_files(self.root, mac_icon(), self.format)
            for app in places:
                error = self._write_mac(app, files)
                if error:
                    report.failed.append(app)
                    self.say(f"{app} couldn't be made ({error}).")
                else:
                    report.changed.append(app)
        elif self.platform == "win32":
            try:
                answer = self._host({"read": []})
            except ShortcutError as error:
                self.say(f"UM-Codex's shortcuts couldn't be made: {error}.")
                return Report(failed=list(places))
            self._write_windows(list(places), answer, report)
        else:
            self.say("UM-Codex has an app or shortcuts only on Mac and Windows.")
            return Report(failed=list(places))
        self.remember(report.ok)
        return report

    # What was written, and when ----------------------------------------------

    def record(self) -> Record | None:
        with contextlib.suppress(OSError, ValueError, TypeError, AttributeError):
            data = json.loads(_read_inside(self.root, MARKER).decode("utf-8"))
            fmt, ok, at = data.get("format"), data.get("ok"), data.get("at")
            if isinstance(fmt, int) and isinstance(ok, bool) and isinstance(at, int | float):
                return Record(fmt, ok, float(at))
        return None

    def remember(self, ok: bool) -> None:
        record = {"format": self.format, "ok": ok, "at": self.now()}
        try:
            write_file(self.root / MARKER, (json.dumps(record) + "\n").encode("utf-8"))
        except OSError:
            log.warning("recording the launchers' format failed", exc_info=True)

    # Mac ------------------------------------------------------------------------

    def _refresh_mac(self, *, dry_run: bool, quiet: bool) -> Report:
        report = Report()
        files = mac_app_files(self.root, mac_icon(), self.format)
        found = False
        problems: dict[Path, str] = {}
        for app in self.mac_apps():
            if not os.path.lexists(app):
                continue
            found = True
            if not is_our_app(app, self.root):
                report.foreign.append(app)
                if not quiet:
                    self.say(
                        f"{app} isn't this UM-Codex's own app (another app, or another account's "
                        "UM-Codex), so it was left alone."
                    )
                continue
            differ = self._mac_differences(app, files)
            if not differ:
                report.current.append(app)
                if not quiet:
                    self.say(f"{app} is up to date.")
                continue
            if dry_run:
                report.changed.append(app)
                self.say(f"Would bring {app} up to date ({self._what.replace('it opens', 'it would open')}):")
                for name in differ:
                    self._show_change(app, name, files[name])
                continue
            error = self._write_mac(app, files)
            if error:
                problems[app] = error
            else:
                report.changed.append(app)
                self.say(f"Brought {app} up to date ({self._what}).")
        good = report.current + report.changed
        for app, error in problems.items():
            if good:
                # A copy an earlier installer left elsewhere: the one in use is fine.
                report.skipped.append(app)
                self.say(
                    f"(An older copy, {app}, couldn't be changed ({error}); {good[0]} is up to date. "
                    "You can drag the older one to the Trash.)"
                )
            else:
                report.failed.append(app)
                self.say(f"{app} couldn't be brought up to date ({error}).")
        if not found and not quiet:
            self.say(
                f"There's no {NAME} app in /Applications or ~/Applications, so there was nothing to "
                "bring up to date. (The UM-Codex installer adds it.)"
            )
        return report

    @staticmethod
    def _mac_differences(app: Path, files: dict[str, bytes]) -> list[str]:
        differ = []
        for name, content in files.items():
            try:
                same = _read_inside(app, name) == content
                if same and name.startswith("Contents/MacOS/"):
                    same = os.access(app / name, os.X_OK)
            except OSError:
                same = False
            if not same:
                differ.append(name)
        return differ

    def _show_change(self, app: Path, name: str, new: bytes) -> None:
        """For a dry run: a text file's lines as they'd change; else its name."""
        path = app / name
        try:
            old = _read_inside(app, name)
        except LinkRefused:
            self.say(f"  {path} (reached through a link: it would be refused)")
            return
        except OSError:
            self.say(f"  {path} (new)")
            return
        try:
            old_text, new_text = old.decode("utf-8"), new.decode("utf-8")
        except UnicodeDecodeError:
            self.say(f"  {path} (replaced: {len(old)} bytes now, {len(new)} after)")
            return
        self.say(f"  {path}:")
        for line in difflib.unified_diff(
            old_text.splitlines(), new_text.splitlines(), "now", "after", n=0, lineterm=""
        ):
            if not line.startswith(("---", "+++")):
                self.say(f"    {line}")

    def _write_mac(self, app: Path, files: dict[str, bytes]) -> str:
        """Writes the app's files; "" when done, else what went wrong. Never
        through a link: the app and each folder in it must be folders themselves."""
        try:
            if _is_link(app):
                raise LinkRefused(f"{app} is a link")
            app.mkdir(exist_ok=True)
            for folder in _APP_FOLDERS:
                _real_folder(app / folder)
            for name, content in files.items():
                write_file(app / name, content, 0o755 if name.startswith("Contents/MacOS/") else 0o644)
            # So Finder and macOS read it afresh (the app was checked not to be a link).
            if os.utime in os.supports_follow_symlinks:
                os.utime(app, follow_symlinks=False)
            else:
                os.utime(app)
        except OSError as error:
            log.warning("writing %s failed", app, exc_info=True)
            return f"{type(error).__name__}: {error}"
        register_app(app)
        return ""

    # Windows ------------------------------------------------------------------

    def _wanted_shortcut(self, answer: dict[str, Any]) -> Shortcut:
        home = str(answer.get("home") or os.environ.get("USERPROFILE") or self.home)
        return windows_shortcut(
            self.root,
            home=home,
            powershell=str(windows_powershell()),
            icon=windows_icon() is not None,
            fmt=self.format,
            terminal=windows_terminal() if self.format == 1 else "",
        )

    def _icon_differs(self) -> bool:
        icon = windows_icon()
        if icon is None:
            return False
        try:
            return _read_inside(self.root, f"icons/{NAME}.ico") != icon
        except OSError:
            return True

    def _copy_icon(self) -> None:
        """The icon, kept beside bin\\ (an update removes version folders)."""
        icon = windows_icon()
        if icon is None:
            return
        _real_folder(self.root / "icons")
        write_file(self.root / "icons" / f"{NAME}.ico", icon)

    def _refresh_windows(self, *, dry_run: bool, quiet: bool) -> Report:
        report = Report()
        try:
            places, answer = self._read_windows()
        except ShortcutError as error:
            self.say(f"UM-Codex's shortcuts couldn't be checked: {error}.")
            return Report(failed=[self.root])
        wanted = self._wanted_shortcut(answer)
        existing = {item.get("path"): Shortcut.from_json(item) for item in _listed(answer.get("read"))}
        to_write: list[Path] = []
        for place in places:
            shortcut = existing.get(str(place))
            if shortcut is None:
                continue
            if not is_our_shortcut(shortcut, self.root):
                report.foreign.append(place)
                if not quiet:
                    self.say(f"{place} isn't UM-Codex's own shortcut, so it was left alone.")
                continue
            if shortcut.same_as(wanted) and not self._icon_differs():
                report.current.append(place)
                if not quiet:
                    self.say(f"{place} is up to date.")
                continue
            if dry_run:
                report.changed.append(place)
                self.say(
                    f"Would bring {place} up to date ({self._what.replace('it opens', 'it would open')}):"
                )
                self.say(f"  now:   {shortcut.target} {shortcut.arguments}")
                self.say(f"  after: {wanted.target} {wanted.arguments}")
                continue
            to_write.append(place)
        if not existing and not quiet:
            self.say(
                "There's no UM-Codex shortcut in the Start menu or on the Desktop, so there was nothing "
                "to bring up to date. (The UM-Codex installer adds them.)"
            )
        if to_write:
            self._write_windows(to_write, answer, report)
        return report

    def _write_windows(self, places: list[Path], answer: dict[str, Any], report: Report) -> None:
        wanted = self._wanted_shortcut(answer)
        try:
            self._copy_icon()
        except OSError as error:
            self.say(f"UM-Codex's icon couldn't be copied ({type(error).__name__}: {error}).")
        request = {"write": [{"path": str(place), **wanted.to_json()} for place in places]}
        try:
            written = _listed(self._host(request).get("wrote"))
            wrote = {item.get("path"): str(item.get("error") or "") for item in written}
        except ShortcutError as error:
            wrote = {str(place): str(error) for place in places}
        for place in places:
            error = wrote.get(str(place), "it wasn't written")
            if error:
                report.failed.append(place)
                self.say(f"{place} couldn't be brought up to date ({error}).")
            else:
                report.changed.append(place)
                self.say(f"Brought {place} up to date ({self._what}).")


# ------------------------------------------------------------------ at a launch


def refresh_if_differs(say: Say = print, *, launchers: Launchers | None = None) -> None:
    """At `um-codex` or `um-codex ui` of an installed version: if the
    launchers were last written in another FORMAT (or by an installer from
    before it was recorded), bring them up to date. If the last try for this
    FORMAT failed, try again at most once a day, and say so only in the log
    (the failure was said once already). Never raises."""
    try:
        if launchers is None:
            if sys.platform not in ("darwin", "win32"):
                return
            from umcodex.update import Layout, install_root

            if Layout(install_root()).running_version() is None:
                return  # a development copy: not the installed launchers' business
            launchers = Launchers(say=say)
        record = launchers.record()
        if record is not None and record.format == FORMAT:
            if record.ok or 0 <= launchers.now() - record.at < RETRY_SECONDS:
                return
            launchers.say = lambda line: log.info("launchers: %s", line)
        launchers.refresh(quiet=True)
    except Exception:
        log.warning("bringing the launchers up to date failed", exc_info=True)
