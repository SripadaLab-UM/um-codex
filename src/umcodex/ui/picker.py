# Adapted from DataLab's backend/src/datalab/sessions/picker.py at 6b6fdca
# (with its Windows bring-to-front fix, 5b5e0ff), folders only.
"""The computer's own folder picker, for the launcher window.

The browser can't name a path on the computer: it can only ask UM-Codex to
show the native picker, and the person chooses. The picker reports its choice
as JSON: names may contain line breaks and other odd characters, so splitting
text output on lines could turn one crafted folder name into several paths.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

# JavaScript for Automation (osascript -l JavaScript).
_MAC = """
const app = Application.currentApplication();
app.includeStandardAdditions = true;
app.activate();
const chosen = [app.chooseFolder(START
  ? {withPrompt: "Choose a folder for UM-Codex", defaultLocation: Path(START)}
  : {withPrompt: "Choose a folder for UM-Codex"})];
JSON.stringify(chosen.map(String));
"""

# Windows PowerShell 5.1. Windows keeps a program in the background (here,
# UM-Codex's PowerShell) from taking the focus from the browser, so a dialog
# with no window of its own opens behind it and looks like nothing happened.
# The dialog gets an owner that is actually shown: an invisible, always-on-top
# window where the mouse is, brought to the front. Windows lets it come
# forward while its input is joined to the window in front (the browser) for a
# moment. If that isn't allowed here, the dialog still opens, maybe behind.
_WINDOWS = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.FormBorderStyle = 'None'
$owner.Opacity = 0
$owner.StartPosition = 'Manual'
$cursor = [System.Windows.Forms.Cursor]::Position
$area = [System.Windows.Forms.Screen]::FromPoint($cursor).WorkingArea
$x = $area.X + [int]($area.Width / 2)
$y = $area.Y + [int]($area.Height / 3)
$owner.Bounds = [System.Drawing.Rectangle]::new($x, $y, 1, 1)
$paths = @()
try {
    $owner.Show()
    try {
        Add-Type -Namespace UmCodexPicker -Name Front -MemberDefinition @'
[DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
[DllImport("user32.dll")]
public static extern uint GetWindowThreadProcessId(IntPtr window, IntPtr process);
[DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
[DllImport("user32.dll")]
public static extern bool AttachThreadInput(uint from, uint to, bool attach);
[DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr window);
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
'@
        $api = [UmCodexPicker.Front]
        $front = $api::GetWindowThreadProcessId($api::GetForegroundWindow(), [IntPtr]::Zero)
        $mine = $api::GetCurrentThreadId()
        $joined = $false
        if ($front -ne 0 -and $front -ne $mine) {
            $joined = $api::AttachThreadInput($mine, $front, $true)
        }
        $null = $api::BringWindowToTop($owner.Handle)
        $null = $api::SetForegroundWindow($owner.Handle)
        if ($joined) { $null = $api::AttachThreadInput($mine, $front, $false) }
    } catch { }
    $owner.Activate()
    $owner.BringToFront()
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = 'Choose a folder for UM-Codex'
    if ($env:UMCODEX_PICK_START) { $dialog.SelectedPath = $env:UMCODEX_PICK_START }
    if ($dialog.ShowDialog($owner) -eq 'OK') { $paths = @($dialog.SelectedPath) }
} finally {
    $owner.Close()
    $owner.Dispose()
}
ConvertTo-Json -InputObject @($paths) -Compress
"""


def windows_command() -> list[str]:
    """PowerShell running the picker script. Encoded, as the script has double
    quotes that Windows' command line would otherwise mangle."""
    encoded = base64.b64encode(_WINDOWS.encode("utf-16-le")).decode("ascii")
    return ["powershell", "-NoProfile", "-STA", "-NonInteractive", "-EncodedCommand", encoded]


def mac_command(start: str) -> list[str]:
    script = f"const START = {json.dumps(start)};\n" + _MAC
    return ["osascript", "-l", "JavaScript", "-e", script]


class PickerUnavailable(RuntimeError):
    pass


class PickerBusy(RuntimeError):
    pass


# One picker at a time.
_lock = asyncio.Lock()


async def pick_folder(*, start_in: Path | None = None) -> Path | None:
    """Show the folder picker; the folder chosen, or None if cancelled.
    `start_in` is where it opens; the person still chooses."""
    env = dict(os.environ)
    start = str(start_in) if start_in is not None else ""
    if sys.platform == "darwin":
        command = mac_command(start)
    elif sys.platform == "win32":
        # The start folder is passed in the environment, never spliced into the script.
        env["UMCODEX_PICK_START"] = start
        command = windows_command()
    else:
        raise PickerUnavailable("Choosing a folder needs UM-Codex on a Mac or Windows computer.")
    if _lock.locked():
        raise PickerBusy("A folder picker is already open.")
    async with _lock:
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
        )
        try:
            out, _ = await process.communicate()
        finally:
            # If the request is abandoned, close the picker too.
            if process.returncode is None:
                process.kill()
    if process.returncode != 0:
        return None  # cancelled
    chosen = parse(out.decode("utf-8-sig", "replace"))  # PowerShell may start with a BOM
    return chosen[0] if chosen else None


def parse(output: str) -> list[Path]:
    """The chosen paths, from the picker's JSON. Only full paths count."""
    try:
        chosen = json.loads(output.strip() or "[]")
    except json.JSONDecodeError:
        return []
    if isinstance(chosen, str):
        chosen = [chosen]
    if not isinstance(chosen, list):
        return []
    return [Path(p) for p in chosen if isinstance(p, str) and p and Path(p).is_absolute()]
