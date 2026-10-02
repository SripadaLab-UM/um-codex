# Helpers for driving a Windows desktop while it is filmed (dot-source this).
# Adapted from DataLab's docs/videos/footage/record-windows-setup.ps1: a real,
# eased mouse; key presses; windows found and placed by UI Automation.
Add-Type -AssemblyName System.Windows.Forms, UIAutomationClient, UIAutomationTypes
Add-Type @"
using System; using System.Runtime.InteropServices;
public static class W {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint f, UIntPtr e);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint f);
  [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
}
"@
$Desktop = [Windows.Automation.AutomationElement]::RootElement
$CT = [Windows.Automation.ControlType]

function Move-Mouse($x, $y, $seconds = 0.6) {
    $p = New-Object W+POINT; [W]::GetCursorPos([ref]$p) | Out-Null
    $steps = [int]($seconds * 60)
    for ($i = 1; $i -le $steps; $i++) {
        $t = $i / $steps; $e = $t * $t * (3 - 2 * $t)
        [W]::SetCursorPos([int]($p.X + ($x - $p.X) * $e), [int]($p.Y + ($y - $p.Y) * $e)) | Out-Null
        Start-Sleep -Milliseconds 16
    }
}
function Click {
    [W]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero); Start-Sleep -Milliseconds 70
    [W]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
}
function Front($hwnd) {
    # A key press nothing uses (F24), so Windows lets this script bring a window forward.
    [W]::keybd_event(0x87, 0, 0, [UIntPtr]::Zero); [W]::keybd_event(0x87, 0, 2, [UIntPtr]::Zero)
    [W]::SetForegroundWindow([IntPtr]$hwnd) | Out-Null
}
function Keys($text, $gap = 0) {
    if (-not $gap) { [Windows.Forms.SendKeys]::SendWait($text); return }
    foreach ($c in $text.ToCharArray()) { [Windows.Forms.SendKeys]::SendWait("$c"); Start-Sleep -Milliseconds $gap }
}
function Find-Top($pattern, $seconds = 10) {
    $until = (Get-Date).AddSeconds($seconds)
    do {
        $hit = $Desktop.FindAll([Windows.Automation.TreeScope]::Children, [Windows.Automation.Condition]::TrueCondition) |
            Where-Object { $_.Current.Name -match $pattern -or $_.Current.ClassName -match $pattern } | Select-Object -First 1
        if ($hit) { return $hit }
        Start-Sleep -Milliseconds 150
    } while ((Get-Date) -lt $until)
    return $null
}
function Find-In($root, $type, $pattern, $seconds = 10) {
    $condition = New-Object Windows.Automation.PropertyCondition ([Windows.Automation.AutomationElement]::ControlTypeProperty), $type
    $until = (Get-Date).AddSeconds($seconds)
    do {
        $hit = $root.FindAll([Windows.Automation.TreeScope]::Descendants, $condition) | Where-Object { $_.Current.Name -match $pattern } | Select-Object -First 1
        if ($hit) { return $hit }
        Start-Sleep -Milliseconds 150
    } while ((Get-Date) -lt $until)
    return $null
}
function Rect-Of($element) { $r = $element.Current.BoundingRectangle; @{ x = [int]$r.X; y = [int]$r.Y; w = [int]$r.Width; h = [int]$r.Height } }
