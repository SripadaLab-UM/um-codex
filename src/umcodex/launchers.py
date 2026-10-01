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

A refresh only ever changes launchers that are UM-Codex's own (the app's
bundle id; a shortcut whose command line names UM-Codex's program folder)
and only where they already are: something else of that name, or a launcher
the person removed, is left as it is.

`<root>/launchers` records the FORMAT they were last written in. A launcher
written by an older installer (alpha.1's opened Terminal, `launch
--from-app`) predates it, so the first `um-codex` or `um-codex ui` of a newer
version refreshes them once (`refresh_if_older`): an update made by alpha.1's
own updater never refreshed them.
"""

from __future__ import annotations

import base64
import contextlib
import difflib
import json
import logging
import os
import plistlib
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any

# 1: alpha.1's (Terminal, `launch --from-app`). 2: the launcher window, `ui --detach`.
FORMAT = 2
NAME = "UM-Codex"
BUNDLE_ID = "edu.umich.umcodex"
FORMAT_KEY = "UMCodexLauncherFormat"
DESCRIPTION = "UM-Codex: Codex on U-M GPT Toolkit, in a Docker container"
MARKER = "launchers"
# For tests: stand-ins for /Applications (as the installers' tests), the
# Start menu's Programs folder and the Desktop.
SYSTEM_APPS_ENV = "UMCODEX_SYSTEM_APPLICATIONS"
START_MENU_ENV = "UMCODEX_START_MENU"
DESKTOP_ENV = "UMCODEX_DESKTOP"
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


def mac_app_files(root: Path, icon: bytes | None) -> dict[str, bytes]:
    """The app's files, by their path inside the bundle."""
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>{NAME}</string>
  <key>CFBundleDisplayName</key><string>{NAME}</string>
  <key>CFBundleIdentifier</key><string>{BUNDLE_ID}</string>
  <key>CFBundleExecutable</key><string>{NAME}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>{NAME if icon is not None else ""}</string>
  <key>LSUIElement</key><true/>
  <key>{FORMAT_KEY}</key><string>{FORMAT}</string>
</dict></plist>
"""
    # The launcher window (`um-codex ui --detach`): a page in the browser,
    # served by UM-Codex on this computer. It runs in the background, so no
    # Terminal window opens until a setup is started, and the app has no Dock
    # icon (LSUIElement).
    script = f"""#!/bin/sh
# Written by UM-Codex (launcher format {FORMAT}); `um-codex update` rewrites it.
exec {sh_quote(str(mac_command(root)))} ui --detach
"""
    files = {
        "Contents/Info.plist": plist.encode("utf-8"),
        f"Contents/MacOS/{NAME}": script.encode("utf-8"),
    }
    if icon is not None:
        files[f"Contents/Resources/{NAME}.icns"] = icon
    return files


def is_our_app(app: Path) -> bool:
    """A UM-Codex.app the installer made (by its bundle id), not a link."""
    if app.is_symlink() or not app.is_dir():
        return False
    try:
        with (app / "Contents" / "Info.plist").open("rb") as file:
            info = plistlib.load(file)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return False
    return isinstance(info, dict) and info.get("CFBundleIdentifier") == BUNDLE_ID


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
    return marker in arguments or marker.replace(";", "\\;") in arguments


def windows_shortcut(root: Path | PureWindowsPath, *, home: str, powershell: str, icon: bool) -> Shortcut:
    """The Start menu and Desktop shortcut: Windows PowerShell, hidden (it may
    show for a moment) and minimized, runs bin\\um-codex.exe, which runs the
    version `current` names, with PYTHONUTF8. No double quotes inside
    -Command "..." (Windows can't have one in a path)."""
    root = PureWindowsPath(root)
    command = root / "bin" / "um-codex.exe"
    launch = f"$Env:PYTHONUTF8 = '1'; & '{ps_quote(str(command))}' ui --detach"
    icon_file = root / "icons" / f"{NAME}.ico"
    return Shortcut(
        target=powershell,
        arguments=f'-NoProfile -WindowStyle Hidden -Command "{launch}"',
        working_directory=home,
        description=DESCRIPTION,
        icon_location=f"{icon_file},0" if icon else "",
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

    @property
    def ok(self) -> bool:
        return not self.failed


class Launchers:
    """UM-Codex's app or shortcuts for the program folder `root`."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        platform: str | None = None,
        say: Say = print,
        home: Path | None = None,
        shortcut_host: ShortcutHost = run_shortcut_host,
    ) -> None:
        if root is None:
            from umcodex.update import install_root

            root = install_root()
        self.root = root
        self.platform = platform or sys.platform
        self.say = say
        self.home = home if home is not None else Path.home()
        self._host = shortcut_host

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

    # The two commands --------------------------------------------------------

    def refresh(self, *, dry_run: bool = False, quiet: bool = False) -> Report:
        """Rewrite UM-Codex's own launchers, where they are, if they aren't
        what this version writes. `quiet`: nothing said about launchers that
        are up to date or not there (at a launch)."""
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
        elif not dry_run:
            self.mark_written()
        return report

    def write(self, places: Sequence[Path]) -> Report:
        """The installers': write the app (Mac: a bundle folder) or shortcuts
        (Windows: .lnk files) at `places`, whatever is there (the installer has
        checked it's UM-Codex's own, or nothing)."""
        report = Report()
        if self.platform == "darwin":
            files = mac_app_files(self.root, mac_icon())
            for app in places:
                self._write_mac(app, files, report)
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
        if report.ok:
            self.mark_written()
        return report

    # The format they were written in ------------------------------------------

    def written_format(self) -> str | None:
        with contextlib.suppress(OSError, UnicodeDecodeError):
            return (self.root / MARKER).read_text(encoding="utf-8").strip() or None
        return None

    def mark_written(self) -> None:
        with contextlib.suppress(OSError):
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = self.root / f".{MARKER}.new"
            temporary.write_text(f"{FORMAT}\n", encoding="utf-8")
            os.replace(temporary, self.root / MARKER)

    # Mac ------------------------------------------------------------------------

    def _refresh_mac(self, *, dry_run: bool, quiet: bool) -> Report:
        report = Report()
        files = mac_app_files(self.root, mac_icon())
        found = False
        for app in self.mac_apps():
            if not app.exists() and not app.is_symlink():
                continue
            found = True
            if not is_our_app(app):
                report.foreign.append(app)
                if not quiet:
                    self.say(f"{app} isn't UM-Codex's own app, so it was left alone.")
                continue
            differ = self._mac_differences(app, files)
            if not differ:
                report.current.append(app)
                if not quiet:
                    self.say(f"{app} is up to date.")
                continue
            if dry_run:
                report.changed.append(app)
                self.say(f"Would bring {app} up to date (it would open UM-Codex's window in your browser):")
                for name in differ:
                    self._show_change(app / name, files[name])
                continue
            self._write_mac(app, files, report)
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
            path = app / name
            try:
                same = path.read_bytes() == content and not path.is_symlink()
                if same and name.startswith("Contents/MacOS/"):
                    same = os.access(path, os.X_OK)
            except OSError:
                same = False
            if not same:
                differ.append(name)
        return differ

    def _show_change(self, path: Path, new: bytes) -> None:
        """For a dry run: a text file's lines as they'd change; else its name."""
        try:
            old = path.read_bytes()
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

    def _write_mac(self, app: Path, files: dict[str, bytes], report: Report) -> None:
        try:
            for name, content in files.items():
                path = app / name
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(f".{path.name}.new")
                temporary.write_bytes(content)
                temporary.chmod(0o755 if name.startswith("Contents/MacOS/") else 0o644)
                os.replace(temporary, path)
            os.utime(app)  # so Finder and macOS read it afresh (the icon, LSUIElement)
        except OSError as error:
            report.failed.append(app)
            self.say(f"{app} couldn't be brought up to date ({type(error).__name__}: {error}).")
            log.warning("writing %s failed", app, exc_info=True)
            return
        report.changed.append(app)
        self.say(f"Brought {app} up to date (it opens UM-Codex's window in your browser).")

    # Windows ------------------------------------------------------------------

    def _wanted_shortcut(self, answer: dict[str, Any]) -> Shortcut:
        home = str(answer.get("home") or os.environ.get("USERPROFILE") or self.home)
        return windows_shortcut(
            self.root, home=home, powershell=str(windows_powershell()), icon=windows_icon() is not None
        )

    def _icon_differs(self) -> bool:
        icon = windows_icon()
        if icon is None:
            return False
        try:
            return (self.root / "icons" / f"{NAME}.ico").read_bytes() != icon
        except OSError:
            return True

    def _copy_icon(self) -> None:
        """The icon, kept beside bin\\ (an update removes version folders)."""
        icon = windows_icon()
        if icon is None:
            return
        folder = self.root / "icons"
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / f".{NAME}.ico.new"
        temporary.write_bytes(icon)
        os.replace(temporary, folder / f"{NAME}.ico")

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
                self.say(f"Would bring {place} up to date (it would open UM-Codex's window in your browser):")
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
                self.say(f"Brought {place} up to date (it opens UM-Codex's window in your browser).")


# ------------------------------------------------------------------ at a launch


def refresh_if_older(say: Say = print, *, launchers: Launchers | None = None) -> None:
    """At `um-codex` or `um-codex ui` of an installed version: if the
    launchers were last written in an older FORMAT (or by an installer from
    before it was recorded), bring them up to date once. Never raises."""
    try:
        if launchers is None:
            if sys.platform not in ("darwin", "win32"):
                return
            from umcodex.update import Layout, install_root

            if Layout(install_root()).running_version() is None:
                return  # a development copy: not the installed launchers' business
            launchers = Launchers(say=say)
        if launchers.written_format() == str(FORMAT):
            return
        launchers.refresh(quiet=True)
    except Exception:
        log.warning("bringing the launchers up to date failed", exc_info=True)
