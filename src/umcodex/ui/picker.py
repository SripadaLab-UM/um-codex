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
#
# The picker is Windows' own folder dialog (IFileOpenDialog), with its address
# bar and a box to type or paste a path: the old Browse For Folder tree hid
# the local Documents on a managed laptop whose My Documents was an unreachable
# network share (found 2026-10-02). If it can't be made, the old one opens.
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
    $modern = $false
    try {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace UmCodexPicker {
    [ComImport, Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")] class FileOpenDialogClass { }
    [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IShellItem {
        void BindToHandler(IntPtr bindContext, ref Guid handler, ref Guid riid, out IntPtr result);
        void GetParent(out IShellItem parent);
        void GetDisplayName(uint form, [MarshalAs(UnmanagedType.LPWStr)] out string name);
        void GetAttributes(uint mask, out uint attributes);
        void Compare(IShellItem other, uint hint, out int order);
    }
    [ComImport, Guid("d57c7288-d4ad-4768-be02-9d969532d960")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IFileOpenDialog {
        [PreserveSig] int Show(IntPtr owner);
        void SetFileTypes(uint count, IntPtr specs);
        void SetFileTypeIndex(uint index);
        void GetFileTypeIndex(out uint index);
        void Advise(IntPtr events, out uint cookie);
        void Unadvise(uint cookie);
        void SetOptions(uint options);
        void GetOptions(out uint options);
        void SetDefaultFolder(IShellItem folder);
        void SetFolder(IShellItem folder);
        void GetFolder(out IShellItem folder);
        void GetCurrentSelection(out IShellItem item);
        void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string name);
        void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string name);
        void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
        void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
        void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
        void GetResult(out IShellItem item);
        void AddPlace(IShellItem item, int where);
        void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string extension);
        void Close(int result);
        void SetClientGuid(ref Guid guid);
        void ClearClientData();
        void SetFilter(IntPtr filter);
        void GetResults(out IntPtr items);
        void GetSelectedItems(out IntPtr items);
    }
    public static class Folder {
        [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
        static extern void SHCreateItemFromParsingName(
            string path, IntPtr bindContext, ref Guid riid, out IShellItem item);
        static IFileOpenDialog Make(string title, string start) {
            IFileOpenDialog dialog = (IFileOpenDialog)new FileOpenDialogClass();
            uint options;
            dialog.GetOptions(out options);
            dialog.SetOptions(options | 0x20 | 0x40 | 0x800);  // pick folders, file system only, must exist
            dialog.SetTitle(title);
            if (!String.IsNullOrEmpty(start)) {
                try {
                    Guid shellItem = typeof(IShellItem).GUID;
                    IShellItem folder;
                    SHCreateItemFromParsingName(start, IntPtr.Zero, ref shellItem, out folder);
                    dialog.SetFolder(folder);
                } catch (Exception) { }
            }
            return dialog;
        }
        // The dialog's options, made but not shown (Windows CI checks this).
        public static uint Check(string start) {
            uint options;
            Make("Check", start).GetOptions(out options);
            return options;
        }
        // The folder chosen, or null if the person cancelled.
        public static string Pick(IntPtr owner, string title, string start) {
            IFileOpenDialog dialog = Make(title, start);
            int shown = dialog.Show(owner);
            if (shown == unchecked((int)0x800704C7)) return null;  // cancelled
            Marshal.ThrowExceptionForHR(shown);
            IShellItem chosen;
            dialog.GetResult(out chosen);
            string path;
            chosen.GetDisplayName(0x80058000, out path);  // its file system path
            return path;
        }
    }
}
'@
        $modern = $true
    } catch { }
    if ($modern) {
        try {
            $title = 'Choose a folder for UM-Codex'
            $chosen = [UmCodexPicker.Folder]::Pick($owner.Handle, $title, $env:UMCODEX_PICK_START)
            if ($chosen) { $paths = @($chosen) }
        } catch { $modern = $false }
    }
    if (-not $modern) {
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = 'Choose a folder for UM-Codex'
        if ($env:UMCODEX_PICK_START) { $dialog.SelectedPath = $env:UMCODEX_PICK_START }
        if ($dialog.ShowDialog($owner) -eq 'OK') { $paths = @($dialog.SelectedPath) }
    }
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


class PickerFailed(RuntimeError):
    """The picker couldn't be shown (not the person cancelling it)."""


# osascript's "User canceled." (the person pressed Cancel).
MAC_CANCELLED = "(-128)"


def outcome(returncode: int, err: str, platform: str = sys.platform) -> None:
    """Raise PickerFailed if a picker that ended with `returncode` failed;
    return if it was cancelled or succeeded. On a Mac a cancel is an error
    -128; on Windows the script reports a cancel as an empty choice."""
    if returncode == 0 or (platform == "darwin" and MAC_CANCELLED in err):
        return
    detail = " ".join(err.strip().splitlines()[-1:])[:200]
    raise PickerFailed(
        "The folder picker couldn't be shown" + (f" ({detail})." if detail else ".") + " Try again."
    )


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
            out, err = await process.communicate()
        finally:
            # If the request is abandoned, close the picker too.
            if process.returncode is None:
                process.kill()
    returncode = process.returncode if process.returncode is not None else 1
    outcome(returncode, err.decode("utf-8", "replace"))
    if returncode != 0:
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
