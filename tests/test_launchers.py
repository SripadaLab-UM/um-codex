"""launchers.py: the Mac app and the Windows shortcuts, written by the
installers and brought up to date by `um-codex update`.

The Mac app is plain files, so it's checked here on any system, in temporary
folders (conftest.py points /Applications, the Start menu and the Desktop at
stand-ins; HOME is a temporary folder). The Windows shortcuts go through
Windows PowerShell and WScript.Shell: here a stand-in keeps them in a dict;
on Windows (CI's windows-installer job) the last tests make and read real
ones, in temporary folders.
"""

from __future__ import annotations

import functools
import os
import stat
import subprocess
import sys
from pathlib import Path, PureWindowsPath
from typing import Any

import pytest

from umcodex import cli, launchers
from umcodex.launchers import FORMAT, Launchers, Shortcut

ALPHA_1_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>UM-Codex</string>
  <key>CFBundleDisplayName</key><string>UM-Codex</string>
  <key>CFBundleIdentifier</key><string>edu.umich.umcodex</string>
  <key>CFBundleExecutable</key><string>UM-Codex</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>UM-Codex</string>
</dict></plist>
"""
# alpha.1's app script, as installer/macos/install.sh at v0.1.0-alpha.1 wrote
# it (@COMMAND@: the command, single-quoted).
ALPHA_1_SCRIPT = """#!/bin/sh
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


def alpha_1_script(root: Path) -> str:
    return ALPHA_1_SCRIPT.replace("@COMMAND@", launchers.sh_quote(str(root / "bin" / "um-codex")))


@pytest.fixture
def home() -> Path:
    """conftest.py's stand-in home folder, with an Applications folder."""
    folder = Path.home()
    (folder / "Applications").mkdir(exist_ok=True)
    return folder


@pytest.fixture
def system_apps() -> Path:
    return Path(os.environ[launchers.SYSTEM_APPS_ENV])


def alpha_1_app(folder: Path, root: Path, bundle: str = "edu.umich.umcodex") -> Path:
    """alpha.1's app for the install at `root`."""
    app = folder / "UM-Codex.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "Resources").mkdir()
    (app / "Contents" / "Info.plist").write_text(ALPHA_1_PLIST.replace("edu.umich.umcodex", bundle))
    script = app / "Contents" / "MacOS" / "UM-Codex"
    script.write_text(alpha_1_script(root))
    script.chmod(0o755)
    (app / "Contents" / "Resources" / "UM-Codex.icns").write_bytes(b"an older icon")
    return app


def mac(root: Path, home: Path, said: list[str]) -> Launchers:
    return Launchers(root, platform="darwin", say=said.append, home=home)


def record(root: Path) -> tuple[int, bool] | None:
    found = Launchers(root, platform="darwin").record()
    return (found.format, found.ok) if found else None


def assert_written(app: Path, root: Path) -> None:
    for name, content in launchers.mac_app_files(root, launchers.mac_icon()).items():
        assert (app / name).read_bytes() == content, name
    assert os.access(app / "Contents" / "MacOS" / "UM-Codex", os.X_OK)


# --- Mac -----------------------------------------------------------------------


def test_the_app_runs_bin_um_codex_ui_detach_with_no_dock_icon(tmp_path):
    files = launchers.mac_app_files(tmp_path / "app", b"icon")
    script = files["Contents/MacOS/UM-Codex"].decode()
    assert script.startswith("#!/bin/sh\n")
    assert script.endswith(f"\nexec '{tmp_path / 'app' / 'bin' / 'um-codex'}' ui --detach\n")
    assert "versions" not in script  # never a version's own folder
    plist = files["Contents/Info.plist"].decode()
    for line in (
        "<key>CFBundleIdentifier</key><string>edu.umich.umcodex</string>",
        "<key>CFBundleExecutable</key><string>UM-Codex</string>",
        "<key>CFBundleIconFile</key><string>UM-Codex</string>",
        "<key>LSUIElement</key><true/>",
        f"<key>UMCodexLauncherFormat</key><string>{FORMAT}</string>",
    ):
        assert line in plist, line
    assert files["Contents/Resources/UM-Codex.icns"] == b"icon"
    # Without an icon, none is named.
    assert "<string></string>" in launchers.mac_app_files(tmp_path, None)["Contents/Info.plist"].decode()


def test_format_1_is_alpha_1s_app_exactly(tmp_path):
    root = tmp_path / "o'brien" / "app"
    files = launchers.mac_app_files(root, b"icon", 1)
    assert files["Contents/Info.plist"].decode() == ALPHA_1_PLIST
    assert files["Contents/MacOS/UM-Codex"].decode() == alpha_1_script(root)


def test_refresh_rewrites_an_alpha_1_app_where_it_is(tmp_path, home, system_apps):
    root = tmp_path / "app"
    app = alpha_1_app(system_apps, root)
    said: list[str] = []
    report = mac(root, home, said).refresh()
    assert report.ok and report.changed == [app]
    assert_written(app, root)
    assert f"Brought {app} up to date" in "\n".join(said)
    assert record(root) == (FORMAT, True)
    # Nothing added in ~/Applications, where there was none; no temporary files left.
    assert not (home / "Applications" / "UM-Codex.app").exists()
    assert not [p for p in app.rglob(".*")] and not [p for p in root.glob(".*")]


def test_refresh_finds_the_app_in_your_own_applications(tmp_path, home):
    root = tmp_path / "app"
    app = alpha_1_app(home / "Applications", root)
    assert mac(root, home, []).refresh().changed == [app]
    assert_written(app, root)


def test_refresh_leaves_someone_elses_app_and_links_alone(tmp_path, home, system_apps):
    root = tmp_path / "app"
    theirs = alpha_1_app(system_apps, root, bundle="org.example.umcodex")
    elsewhere = alpha_1_app(tmp_path / "elsewhere", root)
    (home / "Applications" / "UM-Codex.app").symlink_to(elsewhere)
    said: list[str] = []
    report = mac(root, home, said).refresh()
    assert report.ok and report.changed == []
    assert report.foreign == [theirs, home / "Applications" / "UM-Codex.app"]
    assert (theirs / "Contents" / "MacOS" / "UM-Codex").read_text() == alpha_1_script(root)
    assert (elsewhere / "Contents" / "MacOS" / "UM-Codex").read_text() == alpha_1_script(root)
    assert "isn't this UM-Codex's own app" in "\n".join(said)


def test_another_accounts_app_in_a_shared_applications_is_left_alone(tmp_path, home, system_apps):
    root = tmp_path / "me" / "app"
    other = tmp_path / "someone-else" / "app"
    theirs = alpha_1_app(system_apps, other)  # UM-Codex's bundle id, their command
    assert not launchers.is_our_app(theirs, root) and launchers.is_our_app(theirs, other)
    report = mac(root, home, []).refresh()
    assert report.foreign == [theirs] and report.ok
    assert (theirs / "Contents" / "MacOS" / "UM-Codex").read_text() == alpha_1_script(other)


@pytest.mark.parametrize("folder", ["Contents", "Contents/MacOS"])
def test_a_link_inside_the_app_is_never_followed(tmp_path, home, system_apps, folder):
    root = tmp_path / "app"
    app = alpha_1_app(system_apps, root)
    # The folder moved elsewhere and a link put in its place.
    outside = tmp_path / "outside"
    (app / folder).rename(outside)
    (app / folder).symlink_to(outside)
    before = {p: p.read_bytes() for p in outside.rglob("*") if p.is_file()}
    said: list[str] = []
    report = mac(root, home, said).refresh()
    assert {p: p.read_bytes() for p in outside.rglob("*") if p.is_file()} == before
    assert sorted(outside.rglob("*")) == sorted(set(before) | {p for p in outside.rglob("*") if p.is_dir()})
    # Through a link it isn't even taken for ours; the installer's way refuses too.
    assert report.foreign == [app] and report.changed == []
    written = mac(root, home, said).write([app])
    assert not written.ok and "is a link" in "\n".join(said)
    assert {p: p.read_bytes() for p in outside.rglob("*") if p.is_file()} == before


def test_a_file_thats_a_link_is_replaced_not_written_through(tmp_path, home, system_apps):
    root = tmp_path / "app"
    app = alpha_1_app(system_apps, root)
    target = tmp_path / "someone's file"
    target.write_text("keep")
    (app / "Contents" / "Resources" / "UM-Codex.icns").unlink()
    (app / "Contents" / "Resources" / "UM-Codex.icns").symlink_to(target)
    assert mac(root, home, []).refresh().ok
    assert target.read_text() == "keep"
    assert not (app / "Contents" / "Resources" / "UM-Codex.icns").is_symlink()
    assert_written(app, root)


def test_refresh_is_idempotent(tmp_path, home, system_apps):
    root = tmp_path / "app"
    app = alpha_1_app(system_apps, root)
    mac(root, home, []).refresh()
    before = {p: p.stat().st_mtime_ns for p in app.rglob("*")}
    os.utime(app, (1, 1))
    said: list[str] = []
    report = mac(root, home, said).refresh()
    assert report.ok and report.changed == [] and report.current == [app]
    assert {p: p.stat().st_mtime_ns for p in app.rglob("*")} == before
    assert app.stat().st_mtime == 1  # not even touched
    assert said == [f"{app} is up to date."]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_a_script_that_lost_its_execute_bit_is_rewritten(tmp_path, home, system_apps):
    root = tmp_path / "app"
    app = alpha_1_app(system_apps, root)
    mac(root, home, []).refresh()
    (app / "Contents" / "MacOS" / "UM-Codex").chmod(0o644)
    assert mac(root, home, []).refresh().changed == [app]
    assert os.access(app / "Contents" / "MacOS" / "UM-Codex", os.X_OK)


def test_a_dry_run_says_what_would_change_and_changes_nothing(tmp_path, home, system_apps):
    root = tmp_path / "app"
    app = alpha_1_app(system_apps, root)
    said: list[str] = []
    report = mac(root, home, said).refresh(dry_run=True)
    assert report.changed == [app]
    text = "\n".join(said)
    assert f"Would bring {app} up to date" in text
    assert "+  <key>LSUIElement</key><true/>" in text
    assert f"+exec '{root / 'bin' / 'um-codex'}' ui --detach" in text
    assert f"-exec osascript - '{root / 'bin' / 'um-codex'}' <<'OSA'" in text
    assert "UM-Codex.icns (replaced:" in text
    assert (app / "Contents" / "MacOS" / "UM-Codex").read_text() == alpha_1_script(root)
    assert (app / "Contents" / "Info.plist").read_text() == ALPHA_1_PLIST
    assert not (root / "launchers").exists()


def test_with_no_app_nothing_is_added(tmp_path, home, system_apps):
    root = tmp_path / "app"
    said: list[str] = []
    assert mac(root, home, said).refresh().ok
    assert list(system_apps.iterdir()) == [] and list((home / "Applications").iterdir()) == []
    assert "There's no UM-Codex app" in "\n".join(said)
    assert record(root) == (FORMAT, True)


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="POSIX permissions")
def test_an_app_that_cant_be_rewritten_says_what_to_do(tmp_path, home, system_apps):
    root = tmp_path / "app"
    app = alpha_1_app(system_apps, root)
    (app / "Contents" / "MacOS").chmod(0o555)
    said: list[str] = []
    try:
        report = mac(root, home, said).refresh()
    finally:
        (app / "Contents" / "MacOS").chmod(0o755)
    assert not report.ok and report.failed == [app]
    text = "\n".join(said)
    assert f"{app} couldn't be brought up to date (PermissionError" in text
    assert "Run the UM-Codex installer again" in text and "um-codex launchers --refresh" in text
    assert record(root) == (FORMAT, False)  # tried again later


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="POSIX permissions")
def test_an_older_copy_that_cant_be_changed_is_skipped_when_another_is_current(tmp_path, home, system_apps):
    root = tmp_path / "app"
    stuck = alpha_1_app(system_apps, root)
    mine = home / "Applications" / "UM-Codex.app"
    assert mac(root, home, []).write([mine]).ok
    (stuck / "Contents" / "MacOS").chmod(0o555)
    said: list[str] = []
    try:
        report = mac(root, home, said).refresh()
    finally:
        (stuck / "Contents" / "MacOS").chmod(0o755)
    assert report.ok and report.current == [mine] and report.skipped == [stuck]
    text = "\n".join(said)
    assert (
        f"An older copy, {stuck}, couldn't be changed" in text and "drag the older one to the Trash" in text
    )
    assert "Run the UM-Codex installer again" not in text
    assert record(root) == (FORMAT, True)


@pytest.mark.skipif(sys.platform == "win32", reason="the Mac app's sh script")
def test_the_app_runs_from_a_folder_with_an_apostrophe(tmp_path, home, system_apps):
    root = tmp_path / "o'brien's" / "app"
    command = root / "bin" / "um-codex"
    command.parent.mkdir(parents=True)
    ran = tmp_path / "ran"
    command.write_text(f'#!/bin/sh\necho "$0 $*" > {launchers.sh_quote(str(ran))}\n')
    command.chmod(0o755)
    app = system_apps / "UM-Codex.app"
    assert Launchers(root, platform="darwin", say=lambda _: None, home=home).write([app]).ok
    assert launchers.is_our_app(app, root)
    subprocess.run([str(app / "Contents" / "MacOS" / "UM-Codex")], check=True, timeout=30)
    assert ran.read_text() == f"{command} ui --detach\n"


def test_write_makes_the_app_where_the_installer_says(tmp_path, home, system_apps):
    root = tmp_path / "app"
    app = system_apps / "UM-Codex.app"
    said: list[str] = []
    assert Launchers(root, platform="darwin", say=said.append, home=home).write([app]).ok
    assert_written(app, root)
    assert launchers.is_our_app(app, root)
    assert record(root) == (FORMAT, True)


@pytest.mark.skipif(sys.platform == "win32", reason="the Mac app")
def test_macos_is_told_to_read_the_app_again(tmp_path, home, system_apps, monkeypatch):
    log = tmp_path / "lsregister.log"
    fake = tmp_path / "lsregister"
    fake.write_text(f'#!/bin/sh\necho "$*" >> {launchers.sh_quote(str(log))}\n')
    fake.chmod(0o755)
    monkeypatch.setenv(launchers.LSREGISTER_ENV, str(fake))
    monkeypatch.setattr(launchers.sys, "platform", "darwin")
    root = tmp_path / "app"
    app = alpha_1_app(system_apps, root)
    mac(root, home, []).refresh()
    assert log.read_text() == f"-f {app}\n"
    mac(root, home, []).refresh()  # nothing written, nothing registered
    assert log.read_text() == f"-f {app}\n"
    monkeypatch.setenv(launchers.LSREGISTER_ENV, str(tmp_path / "missing"))
    assert mac(root, home, []).write([app]).ok  # no lsregister: still fine


# --- At a launch -----------------------------------------------------------------


def test_a_launch_refreshes_launchers_an_older_installer_wrote_once(tmp_path, home, system_apps):
    root = tmp_path / "app"
    app = alpha_1_app(system_apps, root)
    said: list[str] = []
    launchers.refresh_if_differs(said.append, launchers=mac(root, home, said))
    assert_written(app, root)
    assert said == [f"Brought {app} up to date (it opens UM-Codex's window in your browser)."]
    # Recorded: the next launch doesn't look again.
    (app / "Contents" / "MacOS" / "UM-Codex").write_text(alpha_1_script(root))
    launchers.refresh_if_differs(said.append, launchers=mac(root, home, said))
    assert (app / "Contents" / "MacOS" / "UM-Codex").read_text() == alpha_1_script(root)


def test_a_launch_refreshes_launchers_of_another_format(tmp_path, home, system_apps):
    root = tmp_path / "app"
    app = alpha_1_app(system_apps, root)
    Launchers(root, platform="darwin", home=home, fmt=1, say=lambda _: None).refresh()
    assert record(root) == (1, True)  # as a rollback to alpha.1 leaves it
    launchers.refresh_if_differs(lambda _: None, launchers=mac(root, home, []))
    assert_written(app, root)
    assert record(root) == (FORMAT, True)


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="POSIX permissions")
def test_a_failed_launch_refresh_says_so_once_then_retries_daily_in_the_log(
    tmp_path, home, system_apps, caplog
):
    root = tmp_path / "app"
    app = alpha_1_app(system_apps, root)
    (app / "Contents" / "MacOS").chmod(0o555)
    clock = [1_000_000.0]
    said: list[str] = []

    def launch() -> None:
        at = Launchers(root, platform="darwin", say=said.append, home=home, now=lambda: clock[0])
        launchers.refresh_if_differs(said.append, launchers=at)

    try:
        launch()
        assert "couldn't be brought up to date" in "\n".join(said)
        assert record(root) == (FORMAT, False)
        said.clear()
        clock[0] += 60 * 60  # an hour later: not tried
        launch()
        assert said == []
        assert (app / "Contents" / "MacOS" / "UM-Codex").read_text() == alpha_1_script(root)
        clock[0] += launchers.RETRY_SECONDS  # a day later: tried, quietly
        with caplog.at_level("INFO", logger="umcodex.launchers"):
            launch()
        assert said == []
        assert "couldn't be brought up to date" in caplog.text
        # Once it can be written, it is, and that's the end of it.
        (app / "Contents" / "MacOS").chmod(0o755)
        clock[0] += launchers.RETRY_SECONDS
        launch()
        assert_written(app, root)
        assert record(root) == (FORMAT, True)
    finally:
        (app / "Contents" / "MacOS").chmod(0o755)


def test_a_launch_says_nothing_when_theres_nothing_to_do(tmp_path, home):
    said: list[str] = []
    launchers.refresh_if_differs(said.append, launchers=mac(tmp_path / "app", home, said))
    assert said == []


def test_a_launch_never_fails_because_of_the_launchers(tmp_path, home, monkeypatch):
    def broken(self, **_: Any):
        raise RuntimeError("boom")

    monkeypatch.setattr(Launchers, "refresh", broken)
    launchers.refresh_if_differs(lambda _: None, launchers=mac(tmp_path / "app", home, []))


def test_a_development_copy_never_touches_the_launchers(monkeypatch):
    def refuse(*_: Any, **__: Any):
        raise AssertionError("refreshed from a development copy")

    monkeypatch.setattr(Launchers, "refresh", refuse)
    launchers.refresh_if_differs(refuse)  # this test run's Python isn't an installed version


def test_um_codex_and_um_codex_ui_check_the_launchers_first(monkeypatch):
    called: list[str] = []
    monkeypatch.setattr(launchers, "refresh_if_differs", lambda *a, **k: called.append("refresh"))
    from umcodex.ui import server

    monkeypatch.setattr(server, "detach", lambda open_browser: called.append("detach") or 0)
    assert cli.main(["ui", "--detach"]) == 0
    assert called == ["refresh", "detach"]


def test_the_tests_home_is_a_stand_in():
    # conftest.py: no test reaches the real ~/Applications or Desktop.
    assert "pytest" in str(Path.home()) or "tmp" in str(Path.home()).lower()


# --- The command -----------------------------------------------------------------


def test_the_command_dry_run(tmp_path, home, system_apps, monkeypatch, capsys):
    root = tmp_path / "app"
    monkeypatch.setenv("UMCODEX_INSTALL_DIR", str(root))
    monkeypatch.setattr(launchers, "Launchers", functools.partial(Launchers, platform="darwin", home=home))
    app = alpha_1_app(system_apps, root)
    assert cli.main(["launchers", "--refresh", "--dry-run"]) == 0
    assert f"Would bring {app} up to date" in capsys.readouterr().out
    assert (app / "Contents" / "MacOS" / "UM-Codex").read_text() == alpha_1_script(root)
    with pytest.raises(SystemExit):
        cli.main(["launchers", "--dry-run"])
    with pytest.raises(SystemExit):
        cli.main(["launchers", "--write", str(app), "--dry-run"])


# --- Windows, with a stand-in for WScript.Shell -------------------------------------

ROOT = PureWindowsPath(r"C:\Users\o'brien\AppData\Local\UM-Codex\app")


def alpha_1_shortcut(root: PureWindowsPath = ROOT, terminal: bool = True) -> Shortcut:
    """As alpha.1's install.ps1 wrote it: Windows Terminal (each ";" as "\\;")
    running Windows PowerShell, `launch --from-app`, -NoExit."""
    quoted = str(root).replace("'", "''")
    marker = f"'{quoted}\\current'"
    launch = (
        f"$Host.UI.RawUI.WindowTitle = 'UM-Codex'; $v = ([string](Get-Content -LiteralPath {marker} "
        f"-TotalCount 1)).Trim(); $Env:PYTHONUTF8 = '1'; & ('{quoted}\\versions\\' + $v + "
        "'\\Scripts\\um-codex.exe') launch --from-app"
    )
    powershell = r"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe"
    arguments = f'-NoProfile -NoExit -Command "{launch}"'
    if terminal:
        arguments = f'-w new new-tab --title UM-Codex -d "C:\\Users\\me" -- "{powershell}" {arguments}'
        arguments = arguments.replace(";", "\\;")
    target = r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\wt.exe" if terminal else powershell
    return Shortcut(target, arguments, r"C:\Users\me", launchers.DESCRIPTION, "", 1)


class FakeShell:
    """WScript.Shell's shortcuts, by path, as run_shortcut_host answers."""

    def __init__(self, desktop: str = "") -> None:
        self.links: dict[str, Shortcut] = {}
        self.desktop = desktop
        self.written: list[str] = []
        self.refuse = ""
        self.broken = False

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.broken:
            raise launchers.ShortcutError("Windows PowerShell said: blocked by policy")
        paths = list(request.get("read", []))
        if request.get("desktopName") and self.desktop:
            paths.append(str(Path(self.desktop) / request["desktopName"]))
        answer: dict[str, Any] = {"desktop": self.desktop, "home": r"C:\Users\me", "read": [], "wrote": []}
        answer["read"] = [{"path": p, **self.links[p].to_json()} for p in paths if p in self.links]
        for link in request.get("write", []):
            if self.refuse:
                answer["wrote"].append({"path": link["path"], "error": self.refuse})
                continue
            self.links[link["path"]] = Shortcut.from_json(link)
            self.written.append(link["path"])
            answer["wrote"].append({"path": link["path"], "error": ""})
        return answer


@pytest.fixture
def start_menu() -> Path:
    return Path(os.environ[launchers.START_MENU_ENV]) / "UM-Codex.lnk"


def windows(root: Path, shell: FakeShell, said: list[str]) -> Launchers:
    return Launchers(root, platform="win32", say=said.append, shortcut_host=shell)


def wanted(root: Path) -> Shortcut:
    return launchers.windows_shortcut(
        root, home=r"C:\Users\me", powershell=str(launchers.windows_powershell()), icon=True
    )


def test_the_shortcut_runs_bin_um_codex_exe_hidden():
    shortcut = launchers.windows_shortcut(ROOT, home=r"C:\Users\me", powershell="ps.exe", icon=True)
    assert shortcut.target == "ps.exe" and shortcut.window_style == 7
    assert shortcut.arguments == (
        "-NoProfile -WindowStyle Hidden -Command \"$Env:PYTHONUTF8 = '1'; "
        "& 'C:\\Users\\o''brien\\AppData\\Local\\UM-Codex\\app\\bin\\um-codex.exe' ui --detach\""
    )
    assert shortcut.icon_location == f"{ROOT}\\icons\\UM-Codex.ico,0"
    assert shortcut.working_directory == r"C:\Users\me"
    # PowerShell's other single quotes are doubled too.
    assert launchers.ps_quote("a\u2019b'c") == "a\u2019\u2019b''c"


@pytest.mark.parametrize("terminal", [True, False])
def test_alpha_1_shortcuts_are_ours_and_others_arent(terminal):
    assert launchers.is_our_shortcut(alpha_1_shortcut(ROOT, terminal), ROOT)
    other = PureWindowsPath(r"C:\Users\o'brien\AppData\Local\Other\app")
    assert not launchers.is_our_shortcut(alpha_1_shortcut(other, terminal), ROOT)
    # A folder with ";" in its name, in Windows Terminal's "\;".
    semi = PureWindowsPath(r"C:\Users\a;b\AppData\Local\UM-Codex\app")
    assert launchers.is_our_shortcut(alpha_1_shortcut(semi, terminal), semi)


def test_refresh_rewrites_alpha_1_shortcuts_on_the_start_menu_and_desktop(tmp_path, start_menu, monkeypatch):
    monkeypatch.delenv(launchers.DESKTOP_ENV)  # found the way Windows says (a OneDrive Desktop, say)
    root = tmp_path / "app"
    shell = FakeShell(desktop=str(tmp_path / "OneDrive" / "Desktop"))
    desktop = tmp_path / "OneDrive" / "Desktop" / "UM-Codex.lnk"
    old = alpha_1_shortcut(PureWindowsPath(root))
    shell.links = {str(start_menu): old, str(desktop): old}
    said: list[str] = []
    report = windows(root, shell, said).refresh()
    assert report.ok and report.changed == [start_menu, desktop]
    for place in (start_menu, desktop):
        assert shell.links[str(place)] == wanted(root)
    assert (root / "icons" / "UM-Codex.ico").read_bytes() == launchers.windows_icon()
    assert record(root) == (FORMAT, True)
    assert f"Brought {desktop} up to date" in "\n".join(said)


@pytest.mark.parametrize("terminal", [True, False])
def test_format_1_is_alpha_1s_shortcut_exactly(terminal):
    old = alpha_1_shortcut(ROOT, terminal)
    written = launchers.windows_shortcut(
        ROOT,
        home=r"C:\Users\me",
        powershell=r"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe",
        icon=False,
        fmt=1,
        terminal=old.target if terminal else "",
    )
    assert written == old


def test_a_rollback_to_alpha_1_writes_its_shortcuts(tmp_path, start_menu):
    root = tmp_path / "app"
    shell = FakeShell()
    shell.links = {str(start_menu): wanted(root)}
    report = Launchers(root, platform="win32", say=lambda _: None, shortcut_host=shell, fmt=1).refresh()
    assert report.changed == [start_menu]
    now = shell.links[str(start_menu)]
    assert "launch --from-app" in now.arguments and "-NoExit" in now.arguments
    assert launchers.is_our_shortcut(now, root)
    assert record(root) == (1, True)


def test_refresh_leaves_someone_elses_desktop_shortcut_alone(tmp_path, start_menu):
    root = tmp_path / "app"
    desktop = Path(os.environ[launchers.DESKTOP_ENV]) / "UM-Codex.lnk"
    shell = FakeShell()
    theirs = alpha_1_shortcut(PureWindowsPath(r"D:\Elsewhere\app"))
    shell.links = {str(start_menu): alpha_1_shortcut(PureWindowsPath(root)), str(desktop): theirs}
    said: list[str] = []
    report = windows(root, shell, said).refresh()
    assert report.changed == [start_menu] and report.foreign == [desktop]
    assert shell.links[str(desktop)] == theirs
    assert "isn't UM-Codex's own shortcut, so it was left alone" in "\n".join(said)


def test_a_removed_shortcut_isnt_put_back(tmp_path, start_menu):
    root = tmp_path / "app"
    shell = FakeShell()
    shell.links = {str(start_menu): alpha_1_shortcut(PureWindowsPath(root))}
    assert windows(root, shell, []).refresh().changed == [start_menu]
    assert shell.written == [str(start_menu)]  # no Desktop one


def test_refreshing_windows_shortcuts_is_idempotent(tmp_path, start_menu):
    root = tmp_path / "app"
    shell = FakeShell()
    shell.links = {str(start_menu): alpha_1_shortcut(PureWindowsPath(root))}
    windows(root, shell, []).refresh()
    said: list[str] = []
    report = windows(root, shell, said).refresh()
    assert report.current == [start_menu] and shell.written == [str(start_menu)]
    assert said == [f"{start_menu} is up to date."]


def test_a_windows_dry_run_changes_nothing(tmp_path, start_menu):
    root = tmp_path / "app"
    shell = FakeShell()
    old = alpha_1_shortcut(PureWindowsPath(root))
    shell.links = {str(start_menu): old}
    said: list[str] = []
    assert windows(root, shell, said).refresh(dry_run=True).changed == [start_menu]
    assert shell.links[str(start_menu)] == old and shell.written == []
    assert not (root / "icons").exists() and not (root / "launchers").exists()
    text = "\n".join(said)
    assert "launch --from-app" in text and "bin\\um-codex.exe' ui --detach" in text


def test_windows_shortcuts_that_cant_be_written_say_what_to_do(tmp_path, start_menu):
    root = tmp_path / "app"
    shell = FakeShell()
    shell.links = {str(start_menu): alpha_1_shortcut(PureWindowsPath(root))}
    shell.refuse = "Access is denied."
    said: list[str] = []
    report = windows(root, shell, said).refresh()
    assert report.failed == [start_menu]
    text = "\n".join(said)
    assert f"{start_menu} couldn't be brought up to date (Access is denied.)" in text
    assert "Run the UM-Codex installer again" in text
    assert record(root) == (FORMAT, False)
    shell.refuse, shell.broken = "", True
    said.clear()
    assert not windows(root, shell, said).refresh().ok
    assert "UM-Codex's shortcuts couldn't be checked: Windows PowerShell said: blocked by policy" in said[0]


def test_write_makes_the_shortcuts_the_installer_names(tmp_path, start_menu):
    root = tmp_path / "app"
    shell = FakeShell()
    desktop = tmp_path / "Desktop" / "UM-Codex.lnk"
    assert windows(root, shell, []).write([start_menu, desktop]).ok
    assert shell.links == {str(start_menu): wanted(root), str(desktop): wanted(root)}
    assert record(root) == (FORMAT, True)


# --- Windows, for real (CI's windows-installer job) ---------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="WScript.Shell")
def test_real_alpha_1_shortcuts_are_rewritten_and_others_left_alone(tmp_path):
    root = tmp_path / "o'brien" / "UM-Codex" / "app"
    root.mkdir(parents=True)
    start_menu = Path(os.environ[launchers.START_MENU_ENV]) / "UM-Codex.lnk"
    desktop = Path(os.environ[launchers.DESKTOP_ENV]) / "UM-Codex.lnk"
    old = alpha_1_shortcut(PureWindowsPath(root))
    theirs = alpha_1_shortcut(PureWindowsPath(tmp_path / "Other" / "app"), terminal=False)
    launchers.run_shortcut_host(
        {"write": [{"path": str(start_menu), **old.to_json()}, {"path": str(desktop), **theirs.to_json()}]}
    )
    said: list[str] = []
    report = Launchers(root, platform="win32", say=said.append).refresh()
    assert report.ok, said
    assert report.changed == [start_menu] and report.foreign == [desktop]
    read = launchers.run_shortcut_host({"read": [str(start_menu), str(desktop)]})
    found = {item["path"]: Shortcut.from_json(item) for item in launchers._listed(read["read"])}
    now = found[str(start_menu)]
    assert now.target.lower() == str(launchers.windows_powershell()).lower()
    assert now.arguments.endswith("\\bin\\um-codex.exe' ui --detach\"") and "o''brien" in now.arguments
    assert now.window_style == 7 and now.icon_location.lower().startswith(str(root).lower())
    assert found[str(desktop)].arguments == theirs.arguments
    # Again: nothing to do.
    assert Launchers(root, platform="win32", say=said.append).refresh().current == [start_menu]
    assert (root / "icons" / "UM-Codex.ico").is_file()
    assert stat.S_ISREG((root / "launchers").stat().st_mode)


@pytest.mark.skipif(
    sys.platform != "win32" or not os.environ.get("GITHUB_ACTIONS"),
    reason="changes where Windows says the Desktop is: only on a throwaway CI runner",
)
def test_a_redirected_desktop_is_found_where_windows_says(tmp_path, monkeypatch):
    """The Desktop as Windows reports it (a OneDrive Desktop, say), not a
    path UM-Codex guesses: the runner's Desktop is pointed at a temporary
    folder for this test, then put back."""
    import winreg  # type: ignore[import-not-found]

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
    desktop = tmp_path / "OneDrive - Michigan Medicine" / "Desktop"
    desktop.mkdir(parents=True)
    root = tmp_path / "app"
    root.mkdir()
    link = desktop / "UM-Codex.lnk"
    old = alpha_1_shortcut(PureWindowsPath(root), terminal=False)
    launchers.run_shortcut_host({"write": [{"path": str(link), **old.to_json()}]})
    monkeypatch.delenv(launchers.DESKTOP_ENV)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
        saved = winreg.QueryValueEx(key, "Desktop")
        winreg.SetValueEx(key, "Desktop", 0, winreg.REG_EXPAND_SZ, str(desktop))
        try:
            assert launchers.run_shortcut_host({"read": []})["desktop"].lower() == str(desktop).lower()
            said: list[str] = []
            report = Launchers(root, platform="win32", say=said.append).refresh()
        finally:
            winreg.SetValueEx(key, "Desktop", 0, saved[1], saved[0])
    assert report.ok and link in report.changed, said
    read = launchers.run_shortcut_host({"read": [str(link)]})
    [now] = [Shortcut.from_json(item) for item in launchers._listed(read["read"])]
    assert now.arguments.endswith("\\bin\\um-codex.exe' ui --detach\"")
