# Records the whole screen (1920x1080, 30 fps) in segments, restarting at once if the capture
# fails, until $Dir\stop exists. On a managed Windows PC, a permission box (the secure desktop)
# makes the capture fail with "error 5" for as long as it is up; one long recording would end
# there for good. Each segment is $Dir\seg-NNN.mkv, and $Dir\segments.txt lists when each one
# began ("<n> <ISO time>"), so a moment in the filming can be found in the right segment.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File footage\record-segments.ps1 [-Dir C:\umv-film\seg]
param([string]$Dir = "C:\umv-film\seg")
$ErrorActionPreference = "Continue"
$Ffmpeg = (Get-Command ffmpeg).Source
New-Item -ItemType Directory -Force $Dir | Out-Null
Get-ChildItem $Dir -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
$n = 0
while (-not (Test-Path (Join-Path $Dir "stop"))) {
    $n++
    $file = Join-Path $Dir ("seg-{0:D3}.mkv" -f $n)
    $info = New-Object Diagnostics.ProcessStartInfo $Ffmpeg
    $info.Arguments = "-v error -y -f gdigrab -framerate 30 -offset_x 0 -offset_y 0 -video_size 1920x1080 -i desktop -c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p `"$file`""
    $info.UseShellExecute = $false; $info.RedirectStandardInput = $true; $info.CreateNoWindow = $true
    $p = [Diagnostics.Process]::Start($info)
    # The first frame comes about a second after the start.
    Add-Content (Join-Path $Dir "segments.txt") ("{0} {1}" -f $n, (Get-Date).AddSeconds(1.2).ToString("o"))
    while (-not $p.HasExited -and -not (Test-Path (Join-Path $Dir "stop"))) { Start-Sleep -Milliseconds 300 }
    if (-not $p.HasExited) {
        $p.StandardInput.Write("q"); $p.StandardInput.Flush()
        if (-not $p.WaitForExit(30000)) { $p.Kill() }
    } else {
        Start-Sleep -Milliseconds 700   # the capture failed: try again
    }
}
"done" | Set-Content (Join-Path $Dir "done")
