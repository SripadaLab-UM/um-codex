# Records the desktop footage for 04-first-launch-windows on a Windows PC, in
# phases (so each can be checked on screen before the next):
#
#   -Phase start   Starts a full-screen recording and the launcher on a demo data
#                  folder, films its page headless (film-first-launch.mjs), presses
#                  "Choose a folder and start...", answers Windows' folder picker
#                  with the demo folder, and waits for Codex's Terminal window.
#   -Phase picker  Answers Windows' folder picker with the demo folder and waits for\n#                  Codex's Terminal window.\n#   -Phase type    Types a request into Codex, slowly.
#   -Phase finish  Lets the page go on to Stop, Start and Edit, then stops everything
#                  and removes the demo setup.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File docs\videos\footage\record-windows-launch.ps1 -Phase start
#
# Needs: node and ffmpeg on PATH (set below), Google Chrome, Docker Desktop running
# with UM-Codex installed and a key saved; a 1920x1080 main screen at 100% scaling;
# no notifications. The full-screen recording ($Scratch\raw.mkv) holds the whole
# desktop and stays out of the repository; only crops of it are used. Don't touch
# the PC while a phase runs: it moves the mouse and types.
param([Parameter(Mandatory)][ValidateSet("start", "picker", "codex", "type", "finish")][string]$Phase)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "winui.ps1")
$Scratch = "C:\umv-film"
$Demo = "C:\Demo\UM-Codex demo"          # a short path; its parent holds nothing else
$Data = "$Scratch\data"                  # the demo launcher's own data folder
$Videos = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$Tools = Get-ChildItem "C:\umv-tools" -Directory
$env:Path = (($Tools | ForEach-Object { if (Test-Path "$($_.FullName)\bin") { "$($_.FullName)\bin" } else { $_.FullName } }) -join ";") + ";" + $env:Path
New-Item -ItemType Directory -Force "$Scratch\film" | Out-Null
$Marks = "$Scratch\marks.json"
function Mark($name) {
    $m = if (Test-Path $Marks) { Get-Content $Marks -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }
    $began = [datetime](Get-Content "$Scratch\ffmpeg-started.txt")
    $m | Add-Member -NotePropertyName $name -NotePropertyValue ([math]::Round(((Get-Date) - $began).TotalSeconds, 2)) -Force
    $m | ConvertTo-Json | Set-Content $Marks
}

if ($Phase -eq "start") {
    Remove-Item -Recurse -Force $Data, "$Scratch\film", "$Scratch\marks.json", "$Scratch\raw.mkv" -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force "$Scratch\film" | Out-Null
    # Win+D: every window out of the way, so only what is opened next is on the desktop.
    [W]::keybd_event(0x5B, 0, 0, [UIntPtr]::Zero); [W]::keybd_event(0x44, 0, 0, [UIntPtr]::Zero); [W]::keybd_event(0x44, 0, 2, [UIntPtr]::Zero); [W]::keybd_event(0x5B, 0, 2, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 800
    [W]::SetCursorPos(1915, 1075) | Out-Null
    # The full screen, 1920x1080, 30 fps.
    $ff = Start-Process ffmpeg -PassThru -WindowStyle Hidden -ArgumentList "-v error -y -f gdigrab -framerate 30 -offset_x 0 -offset_y 0 -video_size 1920x1080 -i desktop -c:v libx264 -preset ultrafast -crf 14 -pix_fmt yuv420p `"$Scratch\raw.mkv`""
    (Get-Date).AddSeconds(1.2).ToString("o") | Set-Content "$Scratch\ffmpeg-started.txt"
    $ff.Id | Set-Content "$Scratch\ffmpeg.pid"
    # The demo launcher.
    $env:UMCODEX_DATA_DIR = $Data
    $ui = Start-Process um-codex -ArgumentList "ui", "--no-browser" -PassThru -WindowStyle Hidden -RedirectStandardOutput "$Scratch\ui.out" -RedirectStandardError "$Scratch\ui.err"
    $ui.Id | Set-Content "$Scratch\ui.pid"
    $link = $null
    for ($i = 0; $i -lt 60 -and -not $link; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-Path "$Scratch\ui.out") { $link = [regex]::Match(("" + (Get-Content "$Scratch\ui.out" -Raw)), 'http://127\.0\.0\.1:\d+/\S*sign-in\S*').Value }
    }
    if (-not $link) { throw "The launcher printed no sign-in link: see $Scratch\ui.out" }
    # The page, filmed headless. Its click on "Choose a folder and start..." opens the real picker.
    $env:FILM_SIGN_IN = $link; $env:FILM_START = $Demo; $env:FILM_DIR = "$Scratch\film"
    $film = Start-Process node -ArgumentList "footage\film-first-launch-windows.mjs" -WorkingDirectory $Videos -PassThru -WindowStyle Hidden -RedirectStandardOutput "$Scratch\film.out" -RedirectStandardError "$Scratch\film.err"
    $film.Id | Set-Content "$Scratch\film.pid"
    Mark "page-film-started"
    Write-Host "The page is being filmed. Run -Phase picker once it has pressed the button."
}

if ($Phase -eq "picker") {
    # Windows' folder dialog (IFileOpenDialog, "Select Folder"): a window owned by an invisible
    # WinForms window, so it is looked for among the top-level windows and that owner's descendants.
    $picker = $null
    for ($i = 0; $i -lt 480 -and -not $picker; $i++) {
        $picker = Find-Top "^Choose a folder for UM-Codex$" 0
        if (-not $picker) {
            $owner = $Desktop.FindAll([Windows.Automation.TreeScope]::Children, [Windows.Automation.Condition]::TrueCondition) | Where-Object { $_.Current.ClassName -like "WindowsForms10*" } | Select-Object -First 1
            if ($owner) { $picker = $Desktop.FindAll([Windows.Automation.TreeScope]::Descendants, [Windows.Automation.Condition]::TrueCondition) | Where-Object { $_.Current.Name -eq "Choose a folder for UM-Codex" -and $_.Current.ClassName -eq "#32770" } | Select-Object -First 1 }
        }
        if (-not $picker) { Start-Sleep -Milliseconds 250 }
    }
    if (-not $picker) { throw "The folder dialog didn't open." }
    Start-Sleep -Milliseconds 1800
    Front $picker.Current.NativeWindowHandle
    Mark "picker"
    (Rect-Of $picker) | ConvertTo-Json | Set-Content "$Scratch\picker-rect.json"
    Start-Sleep -Milliseconds 4500
    $ok = Find-In $picker $CT::Button "^Select Folder$" 5
    if (-not $ok) { $ok = $picker.FindAll([Windows.Automation.TreeScope]::Descendants, [Windows.Automation.Condition]::TrueCondition) | Where-Object { $_.Current.Name -eq "Select Folder" } | Select-Object -First 1 }
    $c = $ok.Current.BoundingRectangle
    Move-Mouse ([int]($c.X + $c.Width / 2)) ([int]($c.Y + $c.Height / 2)) 0.8
    Start-Sleep -Milliseconds 400
    Mark "picker-ok"
    Click
    [W]::SetCursorPos(1915, 1075) | Out-Null
    Write-Host "Folder chosen. Run -Phase codex once the Codex app's window is up."
}

if ($Phase -eq "codex") {
    # UM-Codex's own copy of the Codex app: ChatGPT.exe started with its own data folder.
    $win = $null
    for ($i = 0; $i -lt 720 -and -not $win; $i++) {
        $win = Get-CimInstance Win32_Process -Filter "Name='ChatGPT.exe'" | Where-Object { $_.CommandLine -match "UM-Codex" } | ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue } | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
        if (-not $win) { Start-Sleep -Milliseconds 250 }
    }
    if (-not $win) { throw "UM-Codex's Codex window didn't open." }
    Start-Sleep -Seconds 2
    $h = $win.MainWindowHandle
    [W]::SetWindowPos($h, [IntPtr]::Zero, 160, 60, 1600, 940, 0x0040) | Out-Null
    Front $h
    [W]::SetCursorPos(1915, 1075) | Out-Null
    $r = New-Object W+RECT; [W]::GetWindowRect($h, [ref]$r) | Out-Null
    @{ x = $r.Left; y = $r.Top; w = $r.Right - $r.Left; h = $r.Bottom - $r.Top } | ConvertTo-Json | Set-Content "$Scratch\terminal-rect.json"
    $h.ToInt64() | Set-Content "$Scratch\terminal.hwnd"
    Mark "terminal"
    Write-Host "The Codex window is up ($($win.Id)). Check it on screen."
}
if ($Phase -eq "type") {
    $h = [IntPtr][int64](Get-Content "$Scratch\terminal.hwnd")
    Front $h
    Start-Sleep -Milliseconds 800
    Mark "typing"
    Keys "Summarize plant-growth.csv and write a short note about it in summary.md" 45
    Start-Sleep -Milliseconds 700
    Keys "{ENTER}"
    Mark "sent"
    Write-Host "Sent. Wait for Codex to finish (summary.md appears in the demo folder), then run -Phase finish."
}

if ($Phase -eq "finish") {
    Mark "codex-done"
    New-Item -ItemType File "$Scratch\film\stop-now" -Force | Out-Null
    $film = Get-Process -Id ([int](Get-Content "$Scratch\film.pid")) -ErrorAction SilentlyContinue
    if ($film) { $film.WaitForExit(180000) | Out-Null }
    Mark "page-film-done"
    Start-Sleep -Seconds 1
    Stop-Process -Id ([int](Get-Content "$Scratch\ffmpeg.pid")) -ErrorAction SilentlyContinue
    # Only the demo launcher this script started (never a real one), and what it started.
    $uiPid = [int](Get-Content "$Scratch\ui.pid")
    Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $uiPid } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Stop-Process -Id $uiPid -Force -ErrorAction SilentlyContinue
    Write-Host "Done. Raw footage: $Scratch\raw.mkv, page film: $Scratch\film, marks: $Marks"
}
