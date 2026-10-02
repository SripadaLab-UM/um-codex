# Records the Start menu finding UM-Codex (03-installing-on-windows, shot 5.1):
# the Start menu opened, "UM-Codex" typed, the entry shown, then closed. The full
# screen goes to $Scratch\startmenu.mkv (stays out of the repository); cut-windows.py
# crops it to the search pane and blurs every result below the Best match.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File docs\videos\footage\record-windows-startmenu.ps1
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "winui.ps1")
$Scratch = "C:\umv-film"
$Tools = Get-ChildItem "C:\umv-tools" -Directory
$env:Path = (($Tools | ForEach-Object { if (Test-Path "$($_.FullName)\bin") { "$($_.FullName)\bin" } else { $_.FullName } }) -join ";") + ";" + $env:Path
New-Item -ItemType Directory -Force $Scratch | Out-Null
Remove-Item "$Scratch\startmenu.mkv" -ErrorAction SilentlyContinue
# Every window out of the way (Win+D).
[W]::keybd_event(0x5B, 0, 0, [UIntPtr]::Zero); [W]::keybd_event(0x44, 0, 0, [UIntPtr]::Zero); [W]::keybd_event(0x44, 0, 2, [UIntPtr]::Zero); [W]::keybd_event(0x5B, 0, 2, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 1000
[W]::SetCursorPos(1915, 540) | Out-Null
$info = New-Object Diagnostics.ProcessStartInfo (Get-Command ffmpeg).Source
$info.Arguments = "-v error -y -f gdigrab -framerate 30 -offset_x 0 -offset_y 0 -video_size 1920x1080 -i desktop -c:v libx264 -preset ultrafast -crf 14 -pix_fmt yuv420p `"$Scratch\startmenu.mkv`""
$info.UseShellExecute = $false; $info.RedirectStandardInput = $true; $info.CreateNoWindow = $true
$ff = [Diagnostics.Process]::Start($info)
try {
    Start-Sleep -Milliseconds 2500
    [W]::keybd_event(0x5B, 0, 0, [UIntPtr]::Zero); [W]::keybd_event(0x5B, 0, 2, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 1800
    Keys "UM-Codex" 140
    Start-Sleep -Milliseconds 4500
    Keys "{ESC}"
    Start-Sleep -Milliseconds 1200
} finally {
    $ff.StandardInput.Write("q"); $ff.StandardInput.Flush()
    if (-not $ff.WaitForExit(20000)) { $ff.Kill() }
}
Write-Host "Done: $Scratch\startmenu.mkv"
