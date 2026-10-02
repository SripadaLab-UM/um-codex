# UM-Codex installer for Windows.
# Adapted from IHS DataLab's installer/windows/install.ps1 at 6b6fdca (every
# Windows finding kept; DataLab's lab settings, profiles, GitHub, practice
# database and knowledge-base steps left out). docs/INSTALLING.md, "Windows",
# lists each finding and where it came from.
#
# Two ways to run it, both fine with the default execution policy:
#
#   (Before `irm`, turn on TLS 1.2 for the window: Windows PowerShell 5.1 may not
#   offer it, and GitHub refuses older versions. docs/INSTALLING.md has the line.)
#   irm <release>/install-windows.ps1 | iex
#   & ([scriptblock]::Create((irm <release>/install-windows.ps1))) -ReplaceKey
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1
#       [-Package <umcodex .whl file or https URL>] [-Requirements <requirements.txt file or URL>]
#       [-ReplaceKey] [-AdminAccessUrl <https page for temporary admin access>] [-Yes]
#
# Without -Package it uses the one umcodex-<version>-py3-none-any.whl beside
# this script, or else the release this copy was published with. Its
# requirements.txt pins every dependency by version and hash, and the package
# by its checksum; nothing is installed that it doesn't name.
#
# The people running this aren't expected to know Windows administration, so
# every step says what is about to happen, why, and what to click.
#
# What it does:
#   1. Checks for WSL and Docker Desktop. If anything needs an administrator
#      (turning on WSL, installing WSL and Docker Desktop, letting you use
#      Docker), it asks Windows for permission once and does all of it
#      together. If Windows then needs a restart, it offers one and carries on
#      by itself after you sign in.
#   2. Starts Docker Desktop (and, if a Windows policy has taken away the right
#      Docker's virtual machine needs, offers to put it back).
#   3. Installs uv (a Python installer), a pinned version checked by SHA-256
#      and signature.
#   4. Installs UM-Codex, with its own Python, in your user account (no admin
#      rights), and adds the `um-codex` command to your PATH.
#   5. Downloads UM-Codex's containers (`um-codex pull`).
#   6. Asks for your U-M GPT Toolkit API key (each character shows as *) and
#      saves it in Windows Credential Manager (`um-codex key --from-stdin`).
#   7. Adds UM-Codex to the Start menu and the Desktop. Where the Codex app
#      works with UM-Codex (a Mac, for now: so not yet here), it would ask
#      once about its line in ~/.ssh/config (`um-codex ssh-include`).
#
# Everything after step 1 runs as you, without administrator rights.
#
# The installer is the script block below. Kept as one block, its exact text
# can be checked and run by the administrator part (Invoke-AdminPart) and
# saved for after a restart, however it was started (a file, or `irm | iex`).
# The two param blocks are the same (tests check).
param(
    [string]$Package = "",
    [string]$Requirements = "",
    # Ask for the Toolkit key even if one is saved already.
    [switch]$ReplaceKey,
    # The page where this computer's temporary administrator access is turned on.
    [string]$AdminAccessUrl = "",
    # Answer yes to every question, including the restart (for IT, or testing).
    [switch]$Yes,
    # Windows starts the installer with this after the restart.
    [switch]$Resume,
    # Internal: the one part that runs as administrator (step 1). It only ever
    # runs from a checked copy of the installer's text held in memory; see Invoke-AdminPart.
    [switch]$Prepare,
    [string]$ForUserSid = "",
    [string]$WorkDir = ""
)
$UmCodexInstaller = {
param(
    [string]$Package = "",
    [string]$Requirements = "",
    # Ask for the Toolkit key even if one is saved already.
    [switch]$ReplaceKey,
    # The page where this computer's temporary administrator access is turned on.
    [string]$AdminAccessUrl = "",
    # Answer yes to every question, including the restart (for IT, or testing).
    [switch]$Yes,
    # Windows starts the installer with this after the restart.
    [switch]$Resume,
    # Internal: the one part that runs as administrator (step 1). It only ever
    # runs from a checked copy of the installer's text held in memory; see Invoke-AdminPart.
    [switch]$Prepare,
    [string]$ForUserSid = "",
    [string]$WorkDir = ""
)
$ErrorActionPreference = "Stop"
# With `irm | iex` this runs under the person's own profile settings: no
# strict mode, and no default parameter values of theirs.
Set-StrictMode -Off
$PSDefaultParameterValues = @{}
# Ends the installer with an exit code. Run from a file (or as the
# administrator part, or after a restart), that's `exit`. Run with `irm | iex`,
# `exit` would close the person's own PowerShell window before they could read
# why, so it ends just the installer instead (the runner at the bottom of the
# file catches this).
$StopMarker = "UM-Codex installer stopped"
# What the installer's functions tell each other. A hashtable, as the
# installer runs in a script block's own scope, where `$script:` would mean
# the file's (or, with `irm | iex`, the person's session).
$State = @{ StoppedSaying = $false; Finished = $false; VmLogonRepaired = $false; RestartBoot = [int64]0 }
function Stop-Run([int]$code) {
    # Every planned stop has said why: not "Stopped before the end" as well.
    if ($State) { $State.StoppedSaying = $true }
    if ($UmCodexFromFile -or -not $UmCodexInstaller) { exit $code }
    $global:LASTEXITCODE = $code
    throw $StopMarker
}
# Constrained Language Mode (AppLocker, WDAC) blocks the .NET calls this relies
# on, partway through; better to say so now.
if ($ExecutionContext.SessionState.LanguageMode -ne "FullLanguage") {
    Write-Host ""
    Write-Host "   This computer runs PowerShell in a restricted mode ($($ExecutionContext.SessionState.LanguageMode))," -ForegroundColor Red
    Write-Host "   usually set by IT (AppLocker or Windows Defender Application Control), so the" -ForegroundColor Red
    Write-Host "   UM-Codex installer can't run. Ask IT to install UM-Codex, or to allow this script." -ForegroundColor Red
    Stop-Run 1
}
# 32-bit PowerShell ("Windows PowerShell (x86)") on 64-bit Windows sees other
# Program Files and system folders, and would install the wrong things.
if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
    Write-Host ""
    Write-Host "   This is the 32-bit PowerShell, 'Windows PowerShell (x86)'. Please open the" -ForegroundColor Red
    Write-Host "   normal one (Start menu > Windows PowerShell, without '(x86)'), then run the" -ForegroundColor Red
    Write-Host "   installer again from there." -ForegroundColor Red
    Stop-Run 1
}
# The text of this installer as it's running, for the administrator part (see
# Invoke-AdminPart) and the run after a restart: the script block's own text,
# or, when this text was started as a file of its own, that file's.
$ScriptText = if ($UmCodexInstaller) { $UmCodexInstaller.ToString() } else { $MyInvocation.MyCommand.ScriptContents }
# The installer's own folder, where the package is looked for without
# -Package. Empty when it wasn't started from a file (irm | iex).
$ScriptFolder = if ($UmCodexScriptFolder) { $UmCodexScriptFolder } else { $PSScriptRoot }
# The release this copy of the installer belongs to. The release workflow
# fills these in for the published install-windows.ps1; in the repository
# they're empty, and -Package (or a package beside the script) is needed.
$ReleaseBase = ""
$ReleaseWheel = ""
# uv, which installs UM-Codex: its release for 64-bit Windows, pinned by
# version and by the SHA-256 in that release's published .sha256 file, and
# its uv.exe checked for its publisher's signature. To move to a newer uv,
# change all three from the new release's page on GitHub
# (docs/INSTALLING.md, "Windows").
$UvVersion = "0.12.19"
$UvZipUrl = "https://github.com/astral-sh/uv/releases/download/0.12.19/uv-x86_64-pc-windows-msvc.zip"
$UvZipSha256 = "6dbb02d79e419522f1c500f0adb1cddcff0cda7d59b0d66ea7f5e3b4a1b2f5f0"
$UvPublisher = "OpenAI OpCo, LLC"
# Pinned downloads, checked (SHA-256 and publisher's signature) before they run.
$WslVersion = "2.7.14"
$WslMsiUrl = "https://github.com/microsoft/WSL/releases/download/2.7.14/wsl.2.7.14.0.x64.msi"
$WslMsiSha256 = "db084e536279a59e90a26ec598d8aa8a4dff8309f41d078fd06242953ac1ebcd"
# The exact organisation (O=) of the certificate each one must be signed with.
$WslPublisher = "Microsoft Corporation"
$DockerVersion = "4.77.0"
$DockerUrl = "https://desktop.docker.com/win/main/amd64/228796/Docker%20Desktop%20Installer.exe"
$DockerSha256 = "5b866599f0de9208f4594d64aa33658fa55cbdd64e0db13648cffe12c91795d2"
$DockerPublisher = "Docker Inc"
$DockerAgreement = "https://www.docker.com/legal/docker-subscription-service-agreement/"

# UM-Codex's own folder (its data folder too: um-codex keeps saved setups and
# logs here, beside the program files in app\).
$StateDir = Join-Path $Env:LOCALAPPDATA "UM-Codex"
$ResumeFile = Join-Path $StateDir "installer-resume.json"
# The copy of this installer that runs after a restart (it may have come from
# `irm | iex`, with no file of its own).
$ResumeScript = Join-Path $StateDir "installer\install.ps1"
# The pinned uv, in a folder of UM-Codex's own, used by full path (never a uv
# found on PATH).
$UvDir = Join-Path $StateDir "uv"
$Uv = Join-Path $UvDir "uv.exe"
# The administrator part's folders this account's installer made, one per line,
# so that exactly those (and nothing else in ProgramData) are removed later.
$AdminRecord = Join-Path $StateDir "installer-admin-folder.txt"
$ProgramFilesDir = [Environment]::GetFolderPath("ProgramFiles")
$ResumeShortcut = Join-Path ([Environment]::GetFolderPath("Startup")) "UM-Codex setup.lnk"
$DockerDesktop = Join-Path $ProgramFilesDir "Docker\Docker\Docker Desktop.exe"
# Docker's own command, where Docker Desktop installs it: a window opened
# before Docker Desktop was installed doesn't have it on its PATH yet.
$DockerCliDir = Join-Path $ProgramFilesDir "Docker\Docker\resources\bin"
# Docker Desktop's Windows service. Docker Desktop starts without an
# administrator only when this service starts by itself (--always-run-service).
$DockerService = "com.docker.service"
# Docker Desktop's own processes, which run as the person: the ones closing it
# ends (Repair-VmLogon). Never its service above, which runs as SYSTEM. The same
# list as DOCKER_DESKTOP_IMAGES in UM-Codex's windows_vm.py (tests check they match).
$DockerDesktopImages = @("Docker Desktop.exe", "com.docker.backend.exe", "com.docker.build.exe", "docker-sandbox.exe")
$WslExe = Join-Path $ProgramFilesDir "WSL\wsl.exe"
# The group Docker Desktop creates for the people allowed to use it; its SID
# differs per computer, so it's matched by name.
$DockerUsers = "docker-users"
# The administrator part's folder: "<ProgramData>\UM-Codex-setup-<32 hex digits>".
# ProgramData comes from Windows itself, not from $Env:ProgramData, which a
# person can change for their own account.
$AdminBase = [Environment]::GetFolderPath("CommonApplicationData")
$AdminFolderPrefix = "UM-Codex-setup-"
$AdminFolderPattern = "^" + [regex]::Escape((Join-Path $AdminBase $AdminFolderPrefix)) + "[0-9a-f]{32}$"
# Programs run by full path from Windows' own folder, never looked up by name
# (a person can add folders and App Paths entries for their own account).
$SystemDir = [Environment]::SystemDirectory
$WindowsPowerShell = Join-Path $SystemDir "WindowsPowerShell\v1.0\powershell.exe"
# Well-known SIDs.
$SystemSid = "S-1-5-18"
$AdminsSid = "S-1-5-32-544"
$OwnerRightsSid = "S-1-3-4"
$TrustedInstallerSid = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
# WSL's virtual machine (and so Docker's) signs in as NT VIRTUAL MACHINE\Virtual
# Machines, which needs the "Log on as a service" right. Hyper-V adds it when
# Windows starts; a domain policy that sets that right to its own list (on the
# Michigan Medicine network) takes it away again, and then no WSL virtual
# machine starts (HCS 0x80070569) and Docker Desktop waits for ever. This puts
# back that one right for that one account, and changes nothing else. It's the
# same text as GRANT_SCRIPT in UM-Codex's windows_vm.py (tests check they
# match), which offers the same fix whenever UM-Codex starts.
$VmLogonRefused = "0x80070569"
$VmLogonGrant = @'
$ErrorActionPreference = 'Stop'
$Sid = 'S-1-5-83-0'
$Right = 'SeServiceLogonRight'
$Marshal = [Runtime.InteropServices.Marshal]
$assembly = [AppDomain]::CurrentDomain.DefineDynamicAssembly(
    (New-Object Reflection.AssemblyName 'UMCodexVmLogonRight'),
    [Reflection.Emit.AssemblyBuilderAccess]::Run)
$type = $assembly.DefineDynamicModule('UMCodexVmLogonRight').DefineType('Lsa', 'Public, Class')
foreach ($method in @(
    @('LsaOpenPolicy', @([IntPtr], [byte[]], [UInt32], [IntPtr].MakeByRefType())),
    @('LsaAddAccountRights', @([IntPtr], [byte[]], [IntPtr], [UInt32])),
    @('LsaNtStatusToWinError', @([UInt32])),
    @('LsaClose', @([IntPtr])))) {
    $defined = $type.DefinePInvokeMethod($method[0], 'advapi32.dll',
        'Public, Static, PinvokeImpl', [Reflection.CallingConventions]::Standard,
        [UInt32], [Type[]]$method[1], [Runtime.InteropServices.CallingConvention]::Winapi,
        [Runtime.InteropServices.CharSet]::Unicode)
    # The NTSTATUS comes back as the value, not turned into an exception.
    $defined.SetImplementationFlags([Reflection.MethodImplAttributes]::PreserveSig)
}
$Lsa = $type.CreateType()
function Test-Status($status) {
    if ($status -ne 0) {
        throw (New-Object ComponentModel.Win32Exception([int]$Lsa::LsaNtStatusToWinError($status)))
    }
}
$sidObject = New-Object Security.Principal.SecurityIdentifier($Sid)
$sidBytes = New-Object byte[] $sidObject.BinaryLength
$sidObject.GetBinaryForm($sidBytes, 0)
# LSA_OBJECT_ATTRIBUTES, all zero (LsaOpenPolicy ignores its members).
$attributes = New-Object byte[] 64
$policy = [IntPtr]::Zero
# POLICY_CREATE_ACCOUNT | POLICY_LOOKUP_NAMES
Test-Status ($Lsa::LsaOpenPolicy([IntPtr]::Zero, $attributes, 0x810, [ref]$policy))
$name = $Marshal::StringToHGlobalUni($Right)
$unicode = $Marshal::AllocHGlobal(16)
try {
    # LSA_UNICODE_STRING: Length, MaximumLength (in bytes), then the text's address.
    $Marshal::WriteInt16($unicode, 0, [int16]($Right.Length * 2))
    $Marshal::WriteInt16($unicode, 2, [int16]($Right.Length * 2 + 2))
    $Marshal::WriteIntPtr($unicode, [IntPtr]::Size, $name)
    Test-Status ($Lsa::LsaAddAccountRights($policy, $sidBytes, $unicode, 1))
} finally {
    $Marshal::FreeHGlobal($unicode)
    $Marshal::FreeHGlobal($name)
    $null = $Lsa::LsaClose($policy)
}
'@

function Step($text) { Write-Host "`n== $text ==" -ForegroundColor Cyan }
function Say($text) { Write-Host "   $text" }
function Good($text) { Write-Host "   OK: $text" -ForegroundColor Green }
function Note($text) { Write-Host "   $text" -ForegroundColor Yellow }

# Whether hardware virtualization is on (Step 1). $true when Windows can't say.
function Test-VirtualizationOn {
    try {
        $system = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
        if ($system.HypervisorPresent) { return $true }
        $processor = Get-CimInstance Win32_Processor -ErrorAction Stop | Select-Object -First 1
        return [bool]$processor.VirtualizationFirmwareEnabled
    } catch {
        Say "(Couldn't check whether virtualization is on; carrying on.)"
        return $true
    }
}

function Stop-Install($text) {
    Write-Host ""
    Write-Host "   $text" -ForegroundColor Red
    Write-Host "   Nothing is lost: you can run the installer again at any time, and it picks"
    Write-Host "   up where it stopped. If it keeps happening, send a screenshot of this window"
    Write-Host "   to the UM-Codex maintainer."
    $State.StoppedSaying = $true
    Stop-Run 1
}

function Ask($question) {
    if ($Yes) { Write-Host "   $question [Y/n] y (-Yes)"; return $true }
    $answer = Read-Host "   $question [Y/n]"
    return ($answer -eq "" -or $answer -match '^(y|yes)$')
}

# Runs a program and returns its exit code, or $null if it didn't finish in
# time. Windows PowerShell 5.1 turns a program's error output into a
# terminating error under $ErrorActionPreference = "Stop", so a plain
# `docker info *> $null` would stop the installer instead of reporting that
# Docker isn't running; this also stops a stuck `docker` from hanging it.
function Invoke-Quiet($file, [string[]]$arguments, $seconds = 30) {
    $out = [System.IO.Path]::GetTempFileName()
    try {
        $process = Start-Process $file -ArgumentList $arguments -NoNewWindow -PassThru `
            -RedirectStandardOutput $out -RedirectStandardError "$out.err"
        $null = $process.Handle  # without this, Windows PowerShell loses the exit code
        if (-not $process.WaitForExit($seconds * 1000)) {
            try { $process.Kill() } catch {}
            return $null
        }
        return $process.ExitCode
    } finally {
        Remove-Item $out, "$out.err" -ErrorAction SilentlyContinue
    }
}

# Docker's own command: where Docker Desktop installs it, else one on PATH.
function Get-DockerCli {
    $installed = Join-Path $DockerCliDir "docker.exe"
    if (Test-Path -LiteralPath $installed -PathType Leaf) { return $installed }
    $found = Get-Command docker -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { return $found.Source }
    return $null
}

# Whether Docker's engine answers. A stuck engine can leave `docker info`
# waiting for ever, and a working one answers in a second or two, so this
# gives up after 10 seconds.
function Test-DockerRunning {
    $docker = Get-DockerCli
    if (-not $docker) { return $false }
    return (Invoke-Quiet $docker @("info") 10) -eq 0
}

# Whether this sign-in may use Docker. Windows applies a new group membership
# only at the next sign-in, so this reads the sign-in's own groups; it also
# needs no domain controller, so it works off the VPN.
function Test-CanUseDocker {
    return [bool](whoami /groups | Select-String -SimpleMatch "\$DockerUsers ")
}

# Whether this account is in docker-users already (Docker Desktop's own
# installer adds the account that runs it), even if it needs a new sign-in to
# take effect. Matched by SID, so no domain controller is needed. $null if the
# group can't be read (the administrator part then checks again).
# Checked quietly, first whether the group is there at all (before Docker
# Desktop is installed, it isn't), so expected cases never show up as errors.
function Test-InDockerUsers($sid) {
    if (-not (Get-LocalGroup -Name $DockerUsers -ErrorAction SilentlyContinue)) { return $null }
    $members = @(Get-LocalGroupMember -Group $DockerUsers -ErrorAction SilentlyContinue -ErrorVariable unreadable)
    if ($unreadable) { return $null }
    return [bool]($members | Where-Object { $_.SID.Value -eq $sid })
}

# Whether Docker Desktop is installed but its service starts only for an
# administrator (installed without --always-run-service). A service turned
# off altogether ("Disabled") is left alone: that's IT's choice.
function Test-DockerServiceManual {
    if (-not (Test-Path $DockerDesktop)) { return $false }
    $service = Get-Service $DockerService -ErrorAction SilentlyContinue
    return [bool]($service -and "$($service.StartType)" -eq "Manual")
}

# Whether Windows refuses to let WSL's virtual machine sign in (see
# $VmLogonGrant). Found out by starting WSL's own system distribution, never
# Docker's: a docker-desktop started outside Docker Desktop can leave it
# waiting for that to shut down. Asking Windows directly needs an administrator.
function Test-VmLogonRefused {
    $wsl = Join-Path $SystemDir "wsl.exe"
    if (-not (Test-Path $wsl)) { return $false }
    $out = [System.IO.Path]::GetTempFileName()
    $before = $Env:WSL_UTF8
    $Env:WSL_UTF8 = "1"  # wsl.exe's own messages in UTF-8, not UTF-16
    try {
        $process = Start-Process $wsl -ArgumentList "--system", "-e", "true" -NoNewWindow -PassThru `
            -RedirectStandardOutput $out -RedirectStandardError "$out.err"
        $null = $process.Handle  # without this, Windows PowerShell loses the exit code
        if (-not $process.WaitForExit(90 * 1000)) {
            try { $process.Kill() } catch {}
            return $false
        }
        if ($process.ExitCode -eq 0) { return $false }
        $said = (@(Get-Content -Raw -LiteralPath $out, "$out.err" -ErrorAction SilentlyContinue) -join "") -replace "`0", ""
        return $said.ToLower().Contains($VmLogonRefused)
    } finally {
        if ($null -eq $before) { Remove-Item Env:WSL_UTF8 -ErrorAction SilentlyContinue } else { $Env:WSL_UTF8 = $before }
        Remove-Item $out, "$out.err" -ErrorAction SilentlyContinue
    }
}

# Where to turn on temporary administrator access, in words (and the page,
# when -AdminAccessUrl names one).
function Say-AdminAccess {
    if ($AdminAccessUrl) {
        Say "Turn on your temporary administrator access first, on this page:"
        Say "  $AdminAccessUrl"
    } else {
        Say "If your computer gives you administrator access for a limited time (on a"
        Say "Michigan Medicine computer: your profile page, 'administrator access'),"
        Say "turn it on first."
    }
}

# Shows Windows' administrator box and runs the fixed $VmLogonGrant text
# behind it, from memory. "fixed", "declined" (the box was closed or refused,
# or the change didn't go through) or "still-refused".
function Invoke-VmLogonGrant {
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($VmLogonGrant))
    Say "Asking Windows for permission now (look for the box; it may be behind this window)..."
    $grant = $null
    try {
        # A refused or cancelled box (CyberArk EPM's request box included) is
        # only a non-terminating error to Start-Process: -ErrorAction Stop
        # makes it one, and no process at all counts as declined, never as done.
        $grant = Start-Process $WindowsPowerShell -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ErrorAction Stop `
            -ArgumentList "-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand $encoded"
    } catch {
        return "declined"
    }
    if (-not $grant -or $grant.ExitCode -ne 0) { return "declined" }
    if (Test-VmLogonRefused) { return "still-refused" }
    return "fixed"
}

# Puts the virtual machines' sign-in right back (Step 2), behind one
# administrator prompt, then closes Docker Desktop if it was open so that
# Step 2 opens it afresh.
function Repair-VmLogon {
    Write-Host ""
    Note "Docker can't start on this computer right now: Windows won't let its virtual"
    Note "machine sign in. A Windows policy took away a right it needs (this happens on"
    Note "the Michigan Medicine network)."
    Say "Two ways to fix it:"
    Say "  - Restart Windows (no administrator needed), then run the installer again, or"
    Say "  - Fix it now: Windows asks for administrator permission once, and the right is"
    Say "    given back."
    Say-AdminAccess
    Say "It can happen again later; UM-Codex then offers the same fix when it starts"
    Say "(or run: um-codex doctor --fix-docker)."
    Say "If Docker Desktop is open, fixing it closes and reopens Docker Desktop, so"
    Say "anything running in Docker stops."
    if (-not (Ask "Fix it now?")) {
        Stop-Install "Docker can't start until that's fixed. Restart Windows, then run the installer again."
    }
    while ($true) {
        $outcome = Invoke-VmLogonGrant
        if ($outcome -eq "fixed") { break }
        if ($outcome -eq "still-refused") {
            Stop-Install "That didn't fix it. Restart Windows, then run the installer again."
        }
        # Declined: most often the temporary administrator access wasn't on
        # yet. The way back is to turn it on and try again, here.
        Write-Host ""
        Note "Windows didn't give administrator permission (the box was closed, 'No' was"
        Note "clicked, or the administrator access isn't on yet), so nothing was changed."
        Say-AdminAccess
        if ($Yes -or -not (Ask "Try again?")) {
            Stop-Install ("Docker can't start until that's fixed. Restart Windows (or get " +
                "administrator access), then run the installer again.")
        }
    }
    Good "Docker's virtual machine may start again."
    $State.VmLogonRepaired = $true
    # A Docker Desktop that was already waiting for its engine never tries
    # again, and `docker desktop restart` left that stuck backend running (seen
    # with DataLab 0.3.0b3): so it's closed and its VM stopped, and Step 2
    # opens it afresh.
    $open = @($DockerDesktopImages | ForEach-Object { Get-OwnPids $_ } | Where-Object { $_ })
    if ($open) {
        Say "Closing Docker Desktop, so it starts again with its virtual machine..."
        if (-not (Stop-DockerDesktopProcesses)) {
            Stop-Install ("Windows lets Docker's virtual machine start again, but Docker Desktop " +
                "wouldn't close. Restart Windows, then run the installer again.")
        }
        if (-not (Stop-DockerVm)) {
            Stop-Install ("Windows lets Docker's virtual machine start again, but Docker's virtual " +
                "machine wouldn't stop. Restart Windows, then run the installer again.")
        }
    }
}

# Runs a program and returns its exit code and what it printed, or $null if it
# didn't finish in time. `$arguments` is the command line after the program.
function Invoke-Captured($file, [string]$arguments, $seconds = 30) {
    $info = New-Object System.Diagnostics.ProcessStartInfo $file, $arguments
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.EnvironmentVariables["WSL_UTF8"] = "1"  # wsl.exe's own messages in UTF-8
    $process = [System.Diagnostics.Process]::Start($info)
    $out = $process.StandardOutput.ReadToEndAsync()
    $err = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit($seconds * 1000)) {
        try { $process.Kill() } catch {}
        return $null
    }
    return @{ Code = $process.ExitCode; Out = $out.Result + $err.Result }
}

# The ids of one program's processes (by its exact file name) that run as this
# account: never another account's, nor SYSTEM's. $null when tasklist can't say.
# The account comes from this process's own token, not the environment.
function Get-OwnPids($image) {
    $me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $listed = Invoke-Captured (Join-Path $SystemDir "tasklist.exe") `
        "/FI `"IMAGENAME eq $image`" /FI `"USERNAME eq $me`" /FO CSV /NH" 15
    if (-not $listed -or $listed.Code -ne 0) { return $null }
    # No match is one line, "INFO: No tasks are running which match ...". A Docker
    # Desktop started elevated may list with no user name: it isn't found here.
    $rows = @($listed.Out -split "`r?`n" | Where-Object { $_.StartsWith('"') } |
        ConvertFrom-Csv -Header Image, Id, Session, Number, Memory)
    # The comma keeps an empty list a list: `return @()` would give the caller $null.
    return ,@($rows | Where-Object { $_.Image -eq $image -and $_.Id -match '^\d+$' } | ForEach-Object { [int]$_.Id })
}

# Ends Docker Desktop's own processes ($DockerDesktopImages), this account's
# only, by process id. $false if any is still there afterwards.
function Stop-DockerDesktopProcesses {
    $me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    foreach ($image in $DockerDesktopImages) {
        $ids = Get-OwnPids $image
        if ($null -eq $ids) { return $false }
        # The same filters as the listing, beside the id: an id Windows has
        # handed to another program since isn't ended, nor one that has ended
        # already ("INFO: No tasks running with the specified criteria.").
        foreach ($id in $ids) {
            $null = Invoke-Captured (Join-Path $SystemDir "taskkill.exe") `
                "/F /FI `"IMAGENAME eq $image`" /FI `"USERNAME eq $me`" /PID $id" 15
        }
    }
    # taskkill /F answers before a process has quite gone: look again, once a
    # second, for 15 seconds.
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 1
        $left = @($DockerDesktopImages | ForEach-Object { Get-OwnPids $_ })
        if (-not ($left | Where-Object { $null -eq $_ -or $_.Count -gt 0 })) { return $true }
    }
    return $false
}

# Stops Docker's own WSL distribution, and nothing else of WSL's (never
# `wsl --shutdown`). One that isn't there counts as stopped.
function Stop-DockerVm {
    $done = Invoke-Captured (Join-Path $SystemDir "wsl.exe") "--terminate docker-desktop" 60
    if (-not $done) { return $false }
    return ($done.Code -eq 0 -or $done.Out.Contains("WSL_E_DISTRO_NOT_FOUND"))
}

# --- Shared by install.ps1 and uninstall.ps1 (keep both copies the same) ----
# Removing folders without following links, reading and announcing the user
# PATH, and removing what an administrator part left for this account. ProgramData is shared by every account and anyone can
# create folders in it, so nothing there is removed by name or pattern: only
# the exact folders this account's own installer recorded in $AdminRecord
# (under %LOCALAPPDATA%, which other accounts can't write), and only after
# they check out.

# The reparse tag of a file or folder (0 for none), read without opening it,
# or $null when Windows can't say. FindFirstFile's WIN32_FIND_DATAW carries it
# (dwReserved0, at byte 36); defined in memory, not with Add-Type, which
# compiles through files in TEMP.
function Get-ReparseTag($path) {
    # Defined once per PowerShell process, and found again by its name (no
    # variable outside this function: with `irm | iex` that would be the
    # person's session).
    $assembly = [AppDomain]::CurrentDomain.GetAssemblies() | Where-Object { $_.GetName().Name -eq "UMCodexFind" } | Select-Object -First 1
    if ($assembly) {
        $api = $assembly.GetType("UMCodexFind.Native")
    } else {
        $name = New-Object System.Reflection.AssemblyName("UMCodexFind")
        $assembly = [System.Reflection.Emit.AssemblyBuilder]::DefineDynamicAssembly($name,
            [System.Reflection.Emit.AssemblyBuilderAccess]::Run)
        $type = $assembly.DefineDynamicModule("UMCodexFind").DefineType("UMCodexFind.Native", "Public, Class")
        $calls = @(
            @("FindFirstFileW", [IntPtr], [Type[]]@([string], [byte[]])),
            @("FindClose", [bool], [Type[]]@([IntPtr])))
        foreach ($call in $calls) {
            $method = $type.DefinePInvokeMethod($call[0], "kernel32.dll",
                [System.Reflection.MethodAttributes]"Public, Static, PinvokeImpl",
                [System.Reflection.CallingConventions]::Standard, $call[1], $call[2],
                [System.Runtime.InteropServices.CallingConvention]::Winapi,
                [System.Runtime.InteropServices.CharSet]::Unicode)
            $method.SetImplementationFlags([System.Reflection.MethodImplAttributes]::PreserveSig)
        }
        $api = $type.CreateType()
    }
    # WIN32_FIND_DATAW is 592 bytes; the array is pinned for the call, so
    # what Windows writes into it is there afterwards.
    $data = New-Object byte[] 600
    $handle = $api::FindFirstFileW($path, $data)
    if ($handle -eq [IntPtr]-1) { return $null }
    $null = $api::FindClose($handle)
    $attributes = [BitConverter]::ToUInt32($data, 0)
    if (-not ($attributes -band 0x400)) { return [uint32]0 }  # FILE_ATTRIBUTE_REPARSE_POINT
    return [BitConverter]::ToUInt32($data, 36)
}

# Whether $item is a link of some kind, to be removed as itself and never
# followed: a reparse point whose tag is a "name surrogate" (symlinks,
# junctions, WSL's Linux symlinks 0xA000001D), or one whose tag can't be
# read. Other reparse points (OneDrive's cloud placeholders) are ordinary
# files and folders with extra handling.
function Test-Link($item) {
    if (-not ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) { return $false }
    $tag = $null
    try { $tag = Get-ReparseTag $item.FullName } catch { Write-Verbose "No reparse tag for $($item.FullName): $_" }
    if ($null -eq $tag) { return $true }
    return [bool]($tag -band 0x20000000)
}

# Deletes one file, folder (already empty) or link. A read-only one (git
# makes its object files read-only, and Windows won't delete those as they
# are: "Access is denied") is made writable and tried once more; a link is
# never changed. Whatever still can't go stays (a file in use, say).
function Remove-Entry($item) {
    for ($try = 1; $try -le 2; $try++) {
        try {
            if ($item.PSIsContainer) { [System.IO.Directory]::Delete($item.FullName, $false) }
            else { [System.IO.File]::Delete($item.FullName) }
            return
        } catch {
            # (PowerShell wraps an exception from a .NET call in its own.)
            # Windows PowerShell's .NET reports a read-only folder as an
            # IOException ("Access to the path is denied") and a read-only file
            # as UnauthorizedAccessException: both get the retry.
            $inner = $_.Exception.InnerException
            $denied = ($_.Exception -is [System.UnauthorizedAccessException]) -or
                ($inner -is [System.UnauthorizedAccessException]) -or
                ($_.Exception -is [System.IO.IOException]) -or ($inner -is [System.IO.IOException])
            $readOnly = [bool]($item.Attributes -band [System.IO.FileAttributes]::ReadOnly)
            if ($try -eq 2 -or -not $denied -or -not $readOnly -or (Test-Link $item)) {
                Write-Verbose "Couldn't remove $($item.FullName): $_"
                return
            }
        }
        try { $item.Attributes = $item.Attributes -band (-bnot [System.IO.FileAttributes]::ReadOnly) }
        catch { Write-Verbose "Couldn't make $($item.FullName) writable: $_"; return }
    }
}

# Deletes a folder and what's in it without following links: a link inside is
# removed as a link, never what it points to, and a folder that is itself a
# link is left alone. Whatever can't be deleted stays (callers check).
function Remove-Tree($path) {
    $top = Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    if (-not $top -or -not $top.PSIsContainer -or (Test-Link $top)) { return }
    foreach ($child in @(Get-ChildItem -LiteralPath $path -Force -ErrorAction SilentlyContinue)) {
        if ($child.PSIsContainer -and -not (Test-Link $child)) { Remove-Tree $child.FullName }
        else { Remove-Entry $child }
    }
    Remove-Entry $top
}

# Whether $path is a real folder (read fresh, not a link) owned by SYSTEM or
# Administrators.
function Test-AdminOwned($path) {
    $item = Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    if (-not $item -or -not $item.PSIsContainer -or ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) { return $false }
    try { $owner = (Get-Acl -LiteralPath $path).GetOwner([System.Security.Principal.SecurityIdentifier]).Value } catch { return $false }
    return $owner -in @($SystemSid, $AdminsSid)
}

# Whether $path is exactly what an administrator part leaves for the account
# $sid: the installer's name for it, a real folder owned by SYSTEM or
# Administrators, inheritance off, and no permissions but the ones it sets
# (SYSTEM and Administrators: full control; OWNER RIGHTS: read permissions;
# $sid: list, read attributes, read permissions and delete, on the folder
# only). No Deny rules. A profile folder, say, fails this even if another
# account manages to put a link to it where the folder was.
function Test-AdminFolder($path, $sid) {
    if ($path -notmatch $AdminFolderPattern -or -not (Test-AdminOwned $path)) { return $false }
    try { $acl = Get-Acl -LiteralPath $path } catch { return $false }
    if (-not $acl.AreAccessRulesProtected) { return $false }
    $fsr = [System.Security.AccessControl.FileSystemRights]
    $sync = [int]$fsr::Synchronize  # Windows adds it to every Allow rule
    $expected = @{
        $SystemSid = [int]$fsr::FullControl
        $AdminsSid = [int]$fsr::FullControl
        $OwnerRightsSid = [int]$fsr::ReadPermissions
    }
    $personRights = [int]($fsr::ListDirectory -bor $fsr::ReadAttributes -bor $fsr::ReadPermissions -bor $fsr::Delete)
    $sawPerson = $false
    foreach ($rule in @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))) {
        if ($rule.IsInherited -or "$($rule.AccessControlType)" -ne "Allow") { return $false }
        $who = $rule.IdentityReference.Value
        $rights = [int]$rule.FileSystemRights -bor $sync
        if ($who -eq $sid) {
            if ($rights -ne ($personRights -bor $sync) -or "$($rule.InheritanceFlags)" -ne "None" -or
                "$($rule.PropagationFlags)" -ne "None") { return $false }
            $sawPerson = $true
        } elseif ($expected.ContainsKey($who)) {
            if ($rights -ne ($expected[$who] -bor $sync)) { return $false }
        } else { return $false }
    }
    return $sawPerson
}

# Removes the folders recorded in $AdminRecord that check out, and forgets
# them. One that doesn't check out is left alone (and forgotten); one that
# couldn't be removed is kept for the next run.
function Remove-RecordedAdminFolder($sid) {
    if (-not (Test-Path -LiteralPath $AdminRecord -PathType Leaf)) { return }
    $keep = @()
    foreach ($path in @(Get-Content -LiteralPath $AdminRecord -ErrorAction SilentlyContinue)) {
        $path = "$path".Trim()
        if (-not $path -or $path -notmatch $AdminFolderPattern -or -not (Test-Path -LiteralPath $path)) { continue }
        if (-not (Test-AdminFolder $path $sid)) {
            Write-Host "   (A folder an earlier administrator step left, $path, doesn't have the"
            Write-Host "   permissions it should, so it was left alone. IT can remove it.)"
            continue
        }
        # Checked again right before removing: still a real folder, not a link.
        if (Test-AdminOwned $path) { Remove-Tree $path }
        if (Test-Path -LiteralPath $path) { $keep += $path }
    }
    if ($keep) { Set-Content -LiteralPath $AdminRecord -Value $keep -Encoding UTF8 }
    else { Remove-Item -LiteralPath $AdminRecord -Force -ErrorAction SilentlyContinue }
}
# The user PATH as stored (REG_EXPAND_SZ entries like %USERPROFILE%\bin kept
# as written, not expanded), and its kind. [Environment]::GetEnvironmentVariable
# would expand them, and writing that back would freeze them.
function Get-UserPath {
    $key = Get-Item -LiteralPath "HKCU:\Environment"
    $value = $key.GetValue("Path", "", [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    $kind = "ExpandString"
    if ($key.GetValueNames() -contains "Path") { $kind = "$($key.GetValueKind('Path'))" }
    return @{ Value = "$value"; Kind = $kind }
}

# Whether one PATH entry is $folder (case, a trailing \ and variables aside).
function Test-SamePath($entry, $folder) {
    $a = [Environment]::ExpandEnvironmentVariables("$entry".Trim()).TrimEnd("\")
    return [string]::Equals($a, $folder.TrimEnd("\"), [StringComparison]::OrdinalIgnoreCase)
}

# Tells open programs (Explorer, and so new terminals) that the environment
# changed: setting a user variable through .NET sends WM_SETTINGCHANGE.
function Send-EnvironmentChanged {
    try {
        [Environment]::SetEnvironmentVariable("UMCODEX_PATH_CHANGED", "1", "User")
        [Environment]::SetEnvironmentVariable("UMCODEX_PATH_CHANGED", $null, "User")
    } catch { Write-Verbose "Couldn't announce the PATH change: $_" }
}

# --- End of the part shared by install.ps1 and uninstall.ps1 ---------------

# A Docker Desktop that was uninstalled (or crashed) can leave its socket files
# behind. Windows can't open or delete them ("The file cannot be accessed by the
# system"), and the next Docker Desktop then fails to start on them. They can
# still be moved, so each folder holding them is renamed aside and Docker makes
# a fresh one. Only while Docker Desktop isn't running at all.
function Clear-StaleDockerSockets {
    # Folders an earlier run moved aside: Docker doesn't use them any more, and
    # after a restart their files can usually be deleted.
    $moved = @(Get-Item (Join-Path $Env:LOCALAPPDATA "Docker\run.stale-*"),
        (Join-Path $Env:LOCALAPPDATA "docker-secrets-engine.stale-*") -Force -ErrorAction SilentlyContinue)
    foreach ($folder in $moved) { Remove-Tree $folder.FullName }
    if (Get-Process "com.docker.backend", "Docker Desktop" -ErrorAction SilentlyContinue) { return }
    # Docker's own Linux VM, left running by a Docker Desktop that crashed or was
    # killed: the next start waits for it to shut down, times out ("waiting for
    # shutdown: context deadline exceeded"), and never comes up. Only Docker's
    # own distribution: never `wsl --shutdown`.
    if (Test-Path $WslExe) { $null = Invoke-Quiet $WslExe @("--terminate", "docker-desktop") 60 }
    $stamp = Get-Date -Format yyyyMMdd-HHmmss
    foreach ($folder in "Docker\run", "docker-secrets-engine") {
        $path = Join-Path $Env:LOCALAPPDATA $folder
        if (-not (Test-Path $path)) { continue }
        $stale = Get-ChildItem $path -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Attributes -band [System.IO.FileAttributes]::ReparsePoint }
        if (-not $stale) { continue }
        try {
            Rename-Item -LiteralPath $path -NewName "$(Split-Path $path -Leaf).stale-$stamp" -ErrorAction Stop
            Say "(Moved aside some files an earlier Docker Desktop left behind in $folder.)"
        } catch { Write-Verbose "Couldn't move $path aside: $_" }
    }
}

# Downloads a pinned file and checks it before it's used: its SHA-256, and
# that it's signed by its publisher.
function Save-Download($url, $sha256, $publisher, $file) {
    Say "Downloading $([System.Uri]::UnescapeDataString(($url -split '/')[-1]))..."
    $ProgressPreference = "SilentlyContinue"  # the progress bar makes big downloads much slower
    # Windows PowerShell 5.1 may not offer TLS 1.2 by itself.
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $file
    $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $sha256) {
        Remove-Item -LiteralPath $file -ErrorAction SilentlyContinue
        throw "The download of $url didn't match its expected checksum, so it wasn't run."
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $file
    $signedBy = Get-Organisation $signature.SignerCertificate
    if ($signature.Status -ne "Valid" -or $signedBy -cne $publisher) {
        Remove-Item -LiteralPath $file -ErrorAction SilentlyContinue
        throw "The download of $url isn't signed by its publisher ($publisher), so it wasn't run."
    }
    # For the log (audits): what was checked, and whose signature it has,
    # as the certificate itself names it.
    Say "Checked: SHA-256 and signature ($signedBy)"
}

# The organisation (O=) a certificate was issued to, exactly as written in it,
# or "" (which never matches a publisher). A value with a comma in it
# ("OpenAI OpCo, LLC") may come back quoted, as O="OpenAI OpCo, LLC" (with any
# quote inside doubled): that's unquoted, so the comparison stays exact.
# Refused ("") unless every line is "KEY=value" and exactly one is O=: a value
# with a line break in it (say, a CN of "x<newline>O=Docker Inc") would
# otherwise read as a line of its own.
function Get-Organisation($certificate) {
    if (-not $certificate) { return "" }
    $name = $certificate.SubjectName.Format($true).TrimEnd("`r", "`n")  # one "KEY=value" per line
    $found = @()
    foreach ($line in $name -split "\r?\n") {
        if ($line -notmatch '^\s*[A-Za-z][A-Za-z0-9.]*=') { return "" }
        if ($line -match '^\s*O=(.*)$') { $found += $Matches[1].Trim() }
    }
    if ($found.Count -ne 1) { return "" }
    $value = $found[0]
    if ($value.Length -ge 2 -and $value.StartsWith('"') -and $value.EndsWith('"')) {
        $value = $value.Substring(1, $value.Length - 2).Replace('""', '"')
    }
    return $value
}

# The SHA-256 of some bytes, written the same way as in the command that starts
# the administrator part (Invoke-AdminPart).
function Get-BytesHash([byte[]]$bytes) {
    return [BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes))
}

# Turns off QuickEdit for this console window only: otherwise a click in it
# starts selecting text ("Select" in the title) and pauses the script until
# Esc. It changes this window's mode through the Windows API, nothing saved
# (not the person's console settings, nor the registry). The API call is
# defined in memory: Add-Type would compile code through files in TEMP.
function Disable-QuickEdit {
    try {
        $name = New-Object System.Reflection.AssemblyName("UMCodexConsole")
        $assembly = [System.Reflection.Emit.AssemblyBuilder]::DefineDynamicAssembly($name,
            [System.Reflection.Emit.AssemblyBuilderAccess]::Run)
        $type = $assembly.DefineDynamicModule("UMCodexConsole").DefineType("UMCodexConsole.Native", "Public, Class")
        $calls = @(
            @("GetStdHandle", [IntPtr], [Type[]]@([int])),
            @("GetConsoleMode", [bool], [Type[]]@([IntPtr], [uint32].MakeByRefType())),
            @("SetConsoleMode", [bool], [Type[]]@([IntPtr], [uint32])))
        foreach ($call in $calls) {
            $method = $type.DefinePInvokeMethod($call[0], "kernel32.dll",
                [System.Reflection.MethodAttributes]"Public, Static, PinvokeImpl",
                [System.Reflection.CallingConventions]::Standard, $call[1], $call[2],
                [System.Runtime.InteropServices.CallingConvention]::Winapi,
                [System.Runtime.InteropServices.CharSet]::Auto)
            # Without this, the call's result is dropped (every call returns 0).
            $method.SetImplementationFlags([System.Reflection.MethodImplAttributes]::PreserveSig)
        }
        $native = $type.CreateType()
        $console = $native::GetStdHandle(-10)  # the console's input
        if ($console -eq [IntPtr]::Zero -or $console -eq [IntPtr]-1) { throw "no console input handle" }
        $mode = [uint32]0
        if (-not $native::GetConsoleMode($console, [ref]$mode)) { throw "GetConsoleMode failed" }
        # ENABLE_QUICK_EDIT_MODE (0x40) off; ENABLE_EXTENDED_FLAGS (0x80) makes that apply.
        if (-not $native::SetConsoleMode($console, [uint32](($mode -band (-bnot 0x40)) -bor 0x80))) {
            throw "SetConsoleMode failed"
        }
    } catch {
        # Not a problem for the install, just a note in the log.
        Write-Host "   (QuickEdit stays on in this window ($_): if a click pauses it, press Esc.)"
    }
}

# ---------------------------------------------------------------------------
# The administrator part. Runs in its own window, started from step 1 below.
# ---------------------------------------------------------------------------

# Its working folder: new, in ProgramData, and usable only by SYSTEM and
# Administrators, so nothing running as the person can change a download
# between its check and its run, add files beside an installer, or redirect
# what's written there. It's made with those permissions in one step (never
# looser, even briefly), then checked; anything unexpected stops the
# administrator part before it does anything.
function New-ProtectedFolder($path) {
    $system = New-Object System.Security.Principal.SecurityIdentifier($SystemSid)
    $admins = New-Object System.Security.Principal.SecurityIdentifier($AdminsSid)
    # A file's owner may always change its permissions, and Windows can make
    # the person the owner of what an elevated window creates. With this rule
    # an owner gets only what it gives: reading the permissions.
    $ownerRights = New-Object System.Security.Principal.SecurityIdentifier($OwnerRightsSid)
    $inherit = [System.Security.AccessControl.InheritanceFlags]"ContainerInherit, ObjectInherit"
    $none = [System.Security.AccessControl.PropagationFlags]::None
    $allow = [System.Security.AccessControl.AccessControlType]::Allow
    $security = New-Object System.Security.AccessControl.DirectorySecurity
    $security.SetAccessRuleProtection($true, $false)  # nothing inherited from ProgramData
    $security.SetOwner($admins)
    foreach ($who in $system, $admins) {
        $security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $who, [System.Security.AccessControl.FileSystemRights]::FullControl, $inherit, $none, $allow)))
    }
    $security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
        $ownerRights, [System.Security.AccessControl.FileSystemRights]::ReadPermissions, $inherit, $none, $allow)))

    if (Test-Path -LiteralPath $path) { throw "The folder $path already exists, so it can't be trusted." }
    $null = [System.IO.Directory]::CreateDirectory($path, $security)

    $item = Get-Item -LiteralPath $path -Force
    if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { throw "$path is a link, not a folder." }
    $acl = Get-Acl -LiteralPath $path
    $owner = $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
    $allowed = @($system.Value, $admins.Value, $ownerRights.Value)
    $others = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]) |
        Where-Object { $_.IdentityReference.Value -notin $allowed })
    $wrongOwner = $owner -notin @($system.Value, $admins.Value)
    $notEmpty = @(Get-ChildItem -LiteralPath $path -Force).Count -ne 0
    if ($wrongOwner -or -not $acl.AreAccessRulesProtected -or $others.Count -ne 0 -or $notEmpty) {
        throw "The folder $path didn't get the expected permissions (owner $owner), so it wasn't used."
    }
}

# Once the administrator part is completely done, lets the person read its
# result and log, and check and remove the folder (Remove-RecordedAdminFolder).
# Nothing elevated uses the folder after this.
function Grant-ResultToPerson($folder, [string[]]$files) {
    $person = New-Object System.Security.Principal.SecurityIdentifier($ForUserSid)
    $noInherit = [System.Security.AccessControl.InheritanceFlags]::None
    $none = [System.Security.AccessControl.PropagationFlags]::None
    $allow = [System.Security.AccessControl.AccessControlType]::Allow
    $rights = [System.Security.AccessControl.FileSystemRights]
    $access = [System.Security.AccessControl.AccessControlSections]::Access
    foreach ($file in $files) {
        if (-not (Test-Path -LiteralPath $file)) { continue }
        $item = Get-Item -LiteralPath $file -Force
        $acl = $item.GetAccessControl($access)
        $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $person, ($rights::Read -bor $rights::Delete), $noInherit, $none, $allow)))
        $item.SetAccessControl($acl)
    }
    $item = Get-Item -LiteralPath $folder -Force
    $acl = $item.GetAccessControl($access)
    $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
        $person, ($rights::ListDirectory -bor $rights::ReadAttributes -bor $rights::ReadPermissions -bor
            $rights::Delete -bor $rights::Synchronize),
        $noInherit, $none, $allow)))
    $item.SetAccessControl($acl)
}

if ($Prepare) {
    $Host.UI.RawUI.WindowTitle = "UM-Codex setup (administrator part)"
    Disable-QuickEdit
    $result = @{ ok = $false; restart = $false; error = "" }
    $ready = $false
    $resultFile = Join-Path $WorkDir "result.json"
    $logFile = Join-Path $WorkDir "setup.log"
    try {
        if ($WorkDir -notmatch $AdminFolderPattern) { throw "Unexpected working folder: $WorkDir" }
        # ProgramData itself must be Windows' own: not a link, owned by SYSTEM,
        # TrustedInstaller or Administrators, and nobody else may delete,
        # replace or re-permission what's in it.
        $baseItem = Get-Item -LiteralPath $AdminBase -Force
        $baseAcl = Get-Acl -LiteralPath $AdminBase
        $baseOwner = $baseAcl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
        $trusted = @($SystemSid, $TrustedInstallerSid, $AdminsSid)
        if (($baseItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or $baseOwner -notin $trusted) {
            throw "$AdminBase isn't set up the way Windows sets it up (owner $baseOwner), so it wasn't used. Please ask IT to check it."
        }
        $fsr = [System.Security.AccessControl.FileSystemRights]
        $risky = [int]($fsr::DeleteSubdirectoriesAndFiles -bor $fsr::ChangePermissions -bor $fsr::TakeOwnership) -bor 0x10000000  # GENERIC_ALL
        $modify = [int]$fsr::Modify
        $loose = @($baseAcl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]) | Where-Object {
            $rights = [int]$_.FileSystemRights
            "$($_.AccessControlType)" -eq "Allow" -and $_.IdentityReference.Value -notin $trusted -and
                -not ($_.PropagationFlags -band [System.Security.AccessControl.PropagationFlags]::InheritOnly) -and
                (($rights -band $risky) -or (($rights -band $modify) -eq $modify))
        })
        if ($loose) {
            $who = ($loose | ForEach-Object { $_.IdentityReference.Value } | Sort-Object -Unique) -join ", "
            throw ("On this computer, other accounts ($who) may delete or change what's in $AdminBase, " +
                "so the administrator part can't keep its downloads safe there. Please ask IT to check the permissions on $AdminBase.")
        }
        New-ProtectedFolder $WorkDir
        $ready = $true
        Set-Location -LiteralPath $WorkDir
        Start-Transcript -Path $logFile | Out-Null
        # The installers unpack into TEMP: keep that inside the protected
        # folder too, not in the person's own temp folder.
        $temp = Join-Path $WorkDir "temp"
        New-Item -ItemType Directory $temp | Out-Null
        $Env:TEMP = $temp; $Env:TMP = $temp

        Write-Host "UM-Codex setup: the administrator part" -ForegroundColor Cyan
        Write-Host "Please leave this window open. It closes by itself when it's done."
        Write-Host "The downloads are large (about 900 MB), so this can take 10 minutes or more."

        Step "Turning on the Windows features WSL needs"
        foreach ($name in "Microsoft-Windows-Subsystem-Linux", "VirtualMachinePlatform") {
            $feature = Get-WindowsOptionalFeature -Online -FeatureName $name
            if ($feature.State -eq "Enabled") { Good "$name is on."; continue }
            if ($feature.State -eq "EnablePending") { Good "$name turns on at the next restart."; $result.restart = $true; continue }
            $change = Enable-WindowsOptionalFeature -Online -FeatureName $name -All -NoRestart -WarningAction SilentlyContinue
            Good "Turned on $name."
            if ($change.RestartNeeded) { $result.restart = $true }
        }

        Step "Installing WSL (Windows Subsystem for Linux)"
        if (Test-Path $WslExe) {
            Good "WSL is already installed."
        } else {
            $msi = Join-Path $WorkDir "wsl.$WslVersion.x64.msi"
            Save-Download $WslMsiUrl $WslMsiSha256 $WslPublisher $msi
            Say "Installing WSL $WslVersion..."
            $install = Start-Process (Join-Path $SystemDir "msiexec.exe") -ArgumentList "/i", "`"$msi`"", "/qn", "/norestart" `
                -WorkingDirectory $WorkDir -Wait -PassThru
            if ($install.ExitCode -eq 3010) { $result.restart = $true }
            elseif ($install.ExitCode -ne 0) { throw "Installing WSL failed (msiexec exit code $($install.ExitCode))." }
            Good "Installed WSL."
        }

        Step "Installing Docker Desktop"
        if (Test-Path $DockerDesktop) {
            Good "Docker Desktop is already installed."
        } else {
            $installer = Join-Path $WorkDir "Docker Desktop Installer.exe"
            Save-Download $DockerUrl $DockerSha256 $DockerPublisher $installer
            Say "Installing Docker Desktop $DockerVersion (this takes a few minutes, with no progress shown)..."
            # --always-run-service: Docker Desktop can then start without an administrator.
            $install = Start-Process $installer -ArgumentList "install", "--quiet", "--accept-license", `
                "--backend=wsl-2", "--always-run-service" -WorkingDirectory $WorkDir -Wait -PassThru
            if ($install.ExitCode -ne 0) { throw "Installing Docker Desktop failed (exit code $($install.ExitCode))." }
            Good "Installed Docker Desktop."
            $result.restart = $true
        }

        Step "Letting Docker Desktop start without an administrator"
        # A Docker Desktop installed earlier without --always-run-service has a
        # service that only an administrator can start.
        $service = Get-Service $DockerService -ErrorAction SilentlyContinue
        $startType = "$($service.StartType)"
        if (-not $service) {
            Note "Docker Desktop's service ($DockerService) wasn't found; Docker Desktop may ask for an administrator when it starts."
        } elseif ($startType -eq "Disabled") {
            Note "Docker Desktop's service is turned off on this computer (by IT, most likely), so it was left as it is."
        } elseif ($startType -ne "Automatic") {
            Set-Service -Name $DockerService -StartupType Automatic
            Good "Docker Desktop's service now starts by itself."
        } else {
            Good "Docker Desktop's service already starts by itself."
        }
        if ($service -and $startType -ne "Disabled" -and -not $result.restart) {
            Start-Service -Name $DockerService -ErrorAction SilentlyContinue
        }

        Step "Letting you use Docker"
        # By SID, not name: looking up a domain account's name needs the domain
        # controller, which isn't reachable off the VPN.
        # Add-LocalGroupMember takes a SID only as text ("S-1-5-..."), not as a SecurityIdentifier.
        $sid = (New-Object System.Security.Principal.SecurityIdentifier($ForUserSid)).Value
        # Checked first, quietly, so the expected cases don't show in the log as errors.
        if (-not (Get-LocalGroup -Name $DockerUsers -ErrorAction SilentlyContinue)) {
            throw "Docker Desktop's '$DockerUsers' group isn't on this computer, so your account can't be added to it. Reinstall Docker Desktop, or ask IT."
        }
        # Any trouble listing the members just means trying to add (below).
        $members = @()
        try { $members = @(Get-LocalGroupMember -Group $DockerUsers -ErrorAction SilentlyContinue) }
        catch { Write-Verbose "Couldn't list $DockerUsers members: $_" }
        if ($members | Where-Object { $_.SID.Value -eq $sid }) {
            Good "You're already in the $DockerUsers group."
        } else {
            try {
                Add-LocalGroupMember -Group $DockerUsers -Member $sid
                Good "Added you to the $DockerUsers group (it takes effect after the restart)."
                $result.restart = $true
            } catch [Microsoft.PowerShell.Commands.MemberExistsException] {
                # (The list above can come back short, e.g. with a member Windows can't name.)
                Good "You're already in the $DockerUsers group."
            }
        }

        Step "Letting Docker's virtual machine start"
        # A policy can take this away again later: Step 2 and UM-Codex itself
        # check for that and offer the same fix.
        try {
            & ([scriptblock]::Create($VmLogonGrant))
            Good "Its virtual machine has the right it needs to sign in."
        } catch {
            Note "Couldn't give Docker's virtual machine the right it needs to sign in: $_"
        }
        $result.ok = $true
        Write-Host "`nAll done here. This window closes in a moment." -ForegroundColor Green
        Start-Sleep -Seconds 3
    } catch {
        $result.error = "$_"
        Write-Host "`nSomething went wrong: $_" -ForegroundColor Red
        if ($Yes) { Start-Sleep -Seconds 10 }
        else { Read-Host "Press Enter to close this window (the main installer window explains what to do)" }
    } finally {
        # Only into the folder this part made itself; without it, nothing is written.
        if ($ready) {
            $result | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath $resultFile
            Stop-Transcript | Out-Null
            # The downloads and unpacked installers aren't needed any more.
            foreach ($child in @(Get-ChildItem -LiteralPath $WorkDir -Force)) {
                if ($child.FullName -notin @($resultFile, $logFile)) {
                    if ($child.PSIsContainer) { Remove-Tree $child.FullName }
                    else { Remove-Item -LiteralPath $child.FullName -Force -ErrorAction SilentlyContinue }
                }
            }
            Grant-ResultToPerson $WorkDir @($resultFile, $logFile)
        }
    }
    # Always its own PowerShell process (started by Invoke-AdminPart), so
    # `exit` ends only that window.
    if ($result.ok) { exit 0 } else { exit 1 }
}

# ---------------------------------------------------------------------------
# The installer, run as the person installing.
# ---------------------------------------------------------------------------
# The prompts (the masked key, the questions) need a real console: not the
# PowerShell ISE, VS Code's integrated host or another program's.
if ($Host.Name -ne "ConsoleHost") {
    Write-Host ""
    Write-Host "   This window ($($Host.Name)) can't show the installer's questions. Open Windows" -ForegroundColor Red
    Write-Host "   PowerShell or Windows Terminal (Start menu), then run the installer there." -ForegroundColor Red
    Stop-Run 1
}
$MySid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
# Per account, so two people installing on one computer don't share it.
$ResumeTask = "UM-Codex setup for $MySid (continue after restart)"

# One installer at a time: after a restart, the logon task, the Startup-folder
# shortcut and a run started by hand could otherwise overlap.
$createdNew = $false
$SetupLock = [System.Threading.Mutex]::new($false, "Local\UM-Codex-setup", [ref]$createdNew)
if (-not $createdNew) {
    $SetupLock.Dispose()
    Write-Host ""
    Write-Host "The UM-Codex installer is already open in another window. Carry on there," -ForegroundColor Yellow
    Write-Host "or close that window and run the installer again." -ForegroundColor Yellow
    Stop-Run 3
}
$OldTitle = $Host.UI.RawUI.WindowTitle
$Host.UI.RawUI.WindowTitle = "UM-Codex setup"

# Opens the installer again after the next sign-in, from a saved copy of its
# text (it may have come from `irm | iex`, with no file of its own). A logon
# task for this account, not a RunOnce entry: managed Windows machines were
# seen skipping RunOnce entirely. If the task can't be made, a Startup-folder
# shortcut does it. The account is given by its SID: its name would need the
# domain controller.
function Register-Resume {
    New-Item -ItemType Directory -Force (Split-Path $ResumeScript -Parent) | Out-Null
    [System.IO.File]::WriteAllBytes($ResumeScript, (New-Object System.Text.UTF8Encoding($false)).GetBytes($ScriptText))
    $arguments = "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$ResumeScript`" -Resume"
    try {
        $action = New-ScheduledTaskAction -Execute $WindowsPowerShell -Argument $arguments
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $MySid
        $trigger.Delay = "PT20S"  # let the desktop finish appearing first
        $principal = New-ScheduledTaskPrincipal -UserId $MySid -LogonType Interactive -RunLevel Limited
        # Laptops: by default a task doesn't start on battery.
        $options = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
        Register-ScheduledTask -TaskName $ResumeTask -Action $action -Trigger $trigger -Principal $principal `
            -Settings $options -Force -ErrorAction Stop | Out-Null
    } catch {
        $link = (New-Object -ComObject WScript.Shell).CreateShortcut($ResumeShortcut)
        $link.TargetPath = $WindowsPowerShell
        $link.Arguments = $arguments
        $link.Save()
    }
}

function Unregister-Resume {
    Unregister-ScheduledTask -TaskName $ResumeTask -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item $ResumeShortcut -ErrorAction SilentlyContinue
}

# Puts the pinned uv in $UvDir, as the person: the release zip is checked for
# its SHA-256 and uv.exe for its publisher's signature before it's used. A
# uv already there is used only if it's that version and still signed.
function Install-PinnedUv {
    # The version, the zip's SHA-256, and uv.exe's own SHA-256 when it was
    # unpacked: a copy is reused only if it's still exactly that file.
    $marker = Join-Path $UvDir "umcodex-pinned.txt"
    $want = "$UvVersion $UvZipSha256"
    $recorded = if (Test-Path -LiteralPath $marker) { "$(Get-Content -LiteralPath $marker -TotalCount 1)".Trim() } else { "" }
    if ((Test-Path -LiteralPath $Uv) -and $recorded -eq "$want $((Get-FileHash -LiteralPath $Uv -Algorithm SHA256).Hash.ToLower())") {
        $signature = Get-AuthenticodeSignature -LiteralPath $Uv
        if ($signature.Status -eq "Valid" -and (Get-Organisation $signature.SignerCertificate) -ceq $UvPublisher) {
            Good "uv $UvVersion is installed already."
            return
        }
    }
    if (Test-Path -LiteralPath $UvDir) { Remove-Tree $UvDir }
    if (Test-Path -LiteralPath $UvDir) { Stop-Install "The folder $UvDir couldn't be replaced. Close anything using it, then run the installer again." }
    $download = Join-Path $StateDir ("uv-download-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force $download | Out-Null
    try {
        $zip = Join-Path $download "uv.zip"
        Say "Downloading uv $UvVersion (from github.com/astral-sh/uv)..."
        $ProgressPreference = "SilentlyContinue"
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $UvZipUrl -OutFile $zip
        if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLower() -ne $UvZipSha256) {
            Stop-Install "The download of uv didn't match its expected checksum, so it wasn't used."
        }
        $unpacked = Join-Path $download "uv"
        Expand-Archive -LiteralPath $zip -DestinationPath $unpacked
        $signature = Get-AuthenticodeSignature -LiteralPath (Join-Path $unpacked "uv.exe")
        $signedBy = Get-Organisation $signature.SignerCertificate
        if ($signature.Status -ne "Valid" -or $signedBy -cne $UvPublisher) {
            Stop-Install "uv.exe isn't signed by its publisher ($UvPublisher), so it wasn't used."
        }
        Say "Checked: SHA-256 and signature ($signedBy)"
        $uvHash = (Get-FileHash -LiteralPath (Join-Path $unpacked "uv.exe") -Algorithm SHA256).Hash.ToLower()
        Move-Item -LiteralPath $unpacked -Destination $UvDir
        Set-Content -LiteralPath $marker -Value "$want $uvHash" -Encoding ASCII
    } finally {
        Remove-Tree $download
    }
    Good "uv $UvVersion is ready."
}

# What of UM-Codex is running, in words, or "" if nothing: a process started
# from one of the versions installed side by side under $root, or the command.
function Get-RunningUmCodex($root) {
    $found = @()
    $places = @((Join-Path $root "versions"), (Join-Path $root "bin"))
    foreach ($process in @(Get-Process -ErrorAction SilentlyContinue)) {
        $path = $null
        try { $path = $process.Path } catch { Write-Verbose "No path for process $($process.Id)" }
        if (-not $path) { continue }
        foreach ($place in $places) {
            if ($path.StartsWith($place + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
                $found += "process $($process.Id)"
            }
        }
    }
    return (@($found | Select-Object -Unique) -join ", ")
}

# When Windows last started (in ticks, 0 if unknown): to tell whether it has
# restarted since a restart was asked for.
function Get-BootTime {
    try { return [int64](Get-CimInstance Win32_OperatingSystem -ErrorAction Stop).LastBootUpTime.ToUniversalTime().Ticks }
    catch { return [int64]0 }
}

# Downloads an https file the person named (the package or requirements.txt),
# or copies a local one, to $file.
function Get-Input($source, $file) {
    if ($source -match '^[a-zA-Z][a-zA-Z0-9+.-]*://') {
        if ($source -notmatch '^https://') { Stop-Install "Only https downloads: $source" }
        $ProgressPreference = "SilentlyContinue"
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $source -OutFile $file
    } else {
        Copy-Item -LiteralPath $source $file -Force
    }
}

# Adds $folder to the end of the user PATH, once; nothing else in it changes.
function Add-UserPath($folder) {
    $path = Get-UserPath
    $entries = @($path.Value -split ";" | Where-Object { "$_".Trim() })
    if (-not ($entries | Where-Object { Test-SamePath $_ $folder })) {
        $new = (@($entries) + $folder) -join ";"
        New-ItemProperty -Path "HKCU:\Environment" -Name "Path" -Value $new -PropertyType $path.Kind -Force | Out-Null
        Send-EnvironmentChanged
        Good "Added $folder to your PATH (new terminal windows have the um-codex command)."
    }
    # This window too.
    if (-not (@($Env:Path -split ";") | Where-Object { Test-SamePath $_ $folder })) { $Env:Path = "$Env:Path;$folder" }
}

# Writes a one-line text file whole: into "<file>.tmp", then moved over the file.
function Write-Atomically($file, $value) {
    Set-Content -LiteralPath "$file.tmp" -Value $value -Encoding ASCII
    Move-Item -LiteralPath "$file.tmp" -Destination $file -Force
}

# Notes the uv this install used, by its full path, in "<root>\uv", for
# `um-codex update` (update.py's find_uv reads it first). UTF-8 without a BOM:
# the path may have letters ASCII doesn't (the account's folder name).
function Write-UvRecord($root, $uv) {
    $record = Join-Path $root "uv"
    [System.IO.File]::WriteAllBytes("$record.tmp", (New-Object System.Text.UTF8Encoding($false)).GetBytes("$uv`n"))
    Move-Item -LiteralPath "$record.tmp" -Destination $record -Force
}

# Puts a version's launcher at $destination. A running um-codex.exe can't be
# overwritten, but it can be renamed: the new copy is made beside it first
# (".um-codex.exe.new", so a copy that fails part way never leaves bin without
# a command), then the one there is moved aside and the new one moved into its
# place. Copies moved aside earlier are removed once nothing runs them.
# (um-codex update does the same: Layout.install_command in update.py.)
function Install-Launcher($source, $destination) {
    $folder = Split-Path $destination -Parent
    $name = Split-Path $destination -Leaf
    foreach ($old in @(Get-ChildItem -LiteralPath $folder -File -Filter "$name.old-*" -Force -ErrorAction SilentlyContinue)) {
        Remove-Item -LiteralPath $old.FullName -Force -ErrorAction SilentlyContinue
    }
    $fresh = Join-Path $folder ".$name.new"
    Copy-Item -LiteralPath $source -Destination $fresh -Force
    if (Test-Path -LiteralPath $destination) {
        Rename-Item -LiteralPath $destination -NewName ("$name.old-" + [guid]::NewGuid().ToString("N"))
    }
    Move-Item -LiteralPath $fresh -Destination $destination
}

# Runs um-codex with the key on its standard input, written as UTF-8 (no BOM)
# and then closed: never on a command line, in an environment variable or in a
# file. Its messages go to this window. Returns its exit code.
function Send-Key($program, $key) {
    $info = New-Object System.Diagnostics.ProcessStartInfo $program, "key --from-stdin"
    $info.UseShellExecute = $false
    $info.RedirectStandardInput = $true
    $info.EnvironmentVariables["PYTHONUTF8"] = "1"
    $process = [System.Diagnostics.Process]::Start($info)
    $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes("$key`n")
    $process.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
    $process.StandardInput.Close()
    $process.WaitForExit()
    return $process.ExitCode
}

# Reads the Toolkit key, showing one * per character typed or pasted (at most
# 40, then "..."), with Backspace, Ctrl-U (clear) and Enter; Ctrl-C cancels
# ($null). A paste of more than one line is refused and asked again. Only the
# number of characters is ever shown, never any of them. Where the console
# can't be read a key at a time, it falls back to Read-Host -AsSecureString.
function Read-HiddenKey($prompt) {
    $secure = Read-Host "   $prompt" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return ([Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)).Trim() }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}
function Read-MaskedKey($prompt) {
    $console = $true
    try { $console = -not [Console]::IsInputRedirected } catch { $console = $false }
    if (-not $console) { return (Read-HiddenKey $prompt) }
    while ($true) {
        Write-Host -NoNewline "   ${prompt}: "
        $typed = New-Object System.Text.StringBuilder
        $shown = 0
        $cancelled = $false
        $before = [Console]::TreatControlCAsInput
        [Console]::TreatControlCAsInput = $true
        try {
            while ($true) {
                try { $key = [Console]::ReadKey($true) }
                catch {
                    # No console to read a key at a time from, after all.
                    Write-Host ""
                    return (Read-HiddenKey $prompt)
                }
                $char = [int]$key.KeyChar
                if ($key.Key -eq [ConsoleKey]::Enter) { break }
                if ($char -eq 3) { $cancelled = $true; break }  # Ctrl-C
                if ($key.Key -eq [ConsoleKey]::Backspace) {
                    if ($typed.Length -gt 0) { $null = $typed.Remove($typed.Length - 1, 1) }
                } elseif ($char -eq 21) {  # Ctrl-U
                    $null = $typed.Clear()
                } elseif ($char -ge 32) {
                    $null = $typed.Append($key.KeyChar)
                } else { continue }
                $mask = ("*" * [Math]::Min($typed.Length, 40))
                if ($typed.Length -gt 40) { $mask += "..." }
                Write-Host -NoNewline (("`b `b" * $shown) + $mask)
                $shown = $mask.Length
            }
        } finally {
            [Console]::TreatControlCAsInput = $before
        }
        Write-Host ""
        if ($cancelled) { return $null }
        # More already waiting right after Enter: a paste of more than one line.
        # (A line break at the end of a paste can arrive as a second key: only
        # more text counts.)
        $extra = ""
        while ([Console]::KeyAvailable) {
            $more = [Console]::ReadKey($true)
            if ([int]$more.KeyChar -ge 32) { $extra += $more.KeyChar }
        }
        if ($extra.Trim()) {
            $extra = $null
            Note "That was more than one line. Paste just the key (one line), then press Enter."
            continue
        }
        $text = $typed.ToString()
        $trimmed = $text.Trim()
        if ($trimmed.Length -ne $text.Length) { Say "(Removed spaces or line breaks at the ends.)" }
        if ($trimmed) { Say "Got $($trimmed.Length) characters." }
        return $trimmed
    }
}

# The rest runs inside try/finally, so the one-at-a-time lock is freed however
# it ends, also when the window stays open afterwards (-NoExit) or after
# Ctrl-C. Settings this run changes in its own window (it may be the person's
# own window, with `irm | iex`) are put back too.
$SavedEnv = @{}
try {
# Whatever started this run, nothing should open the installer again unless
# this run asks for another restart (Request-Restart sets it up again).
Unregister-Resume
# What an earlier administrator part left for this account to remove.
Remove-RecordedAdminFolder $MySid

$saved = $null
if (Test-Path $ResumeFile) { $saved = Get-Content $ResumeFile -Raw | ConvertFrom-Json }
if ($Resume) {
    if (-not $saved) { Write-Host "There's no UM-Codex install waiting to continue."; Stop-Run 2 }
    $Package = $saved.Package; $Requirements = $saved.Requirements
    $ReplaceKey = [bool]$saved.ReplaceKey; $AdminAccessUrl = "$($saved.AdminAccessUrl)"
    Write-Host ""
    Write-Host "Welcome back! Let's finish setting up UM-Codex." -ForegroundColor Cyan
    Write-Host "This part shouldn't need administrator permission. If it does, it says why first."
} else {
    Write-Host ""
    Write-Host "Welcome! This sets up UM-Codex on this computer." -ForegroundColor Cyan
    Write-Host "It takes about 20-30 minutes, most of it downloading. It walks you through"
    Write-Host "each step and tells you whenever it needs you to do something."
}
if ($AdminAccessUrl -and $AdminAccessUrl -notmatch '^https://[^\s]+$') {
    Note "(-AdminAccessUrl isn't an https:// address, so it's ignored.)"
    $AdminAccessUrl = ""
}
if (-not $Package) {
    # The package beside this script (download the installer and the package,
    # and requirements.txt, from the same release into one folder), else the
    # release this installer was published with.
    $besideScript = @()
    if ($ScriptFolder) {
        $besideScript = @(Get-ChildItem -LiteralPath $ScriptFolder -File -Filter "umcodex-*-py3-none-any.whl" -ErrorAction SilentlyContinue)
    }
    # A release's installer takes only its own release's package from beside it.
    if ($ReleaseWheel) { $besideScript = @($besideScript | Where-Object { $_.Name -ceq $ReleaseWheel }) }
    if ($besideScript.Count -eq 1) { $Package = $besideScript[0].FullName }
    elseif ($besideScript.Count -gt 1) {
        Write-Host "There's more than one UM-Codex package in $ScriptFolder"
        Write-Host "($(($besideScript | ForEach-Object Name) -join ', ')). Pass the one to install: -Package <file>."
        Stop-Run 2
    } elseif ($ReleaseBase -and $ReleaseWheel) {
        $Package = "$ReleaseBase/$ReleaseWheel"
        if (-not $Requirements) { $Requirements = "$ReleaseBase/requirements.txt" }
    } else {
        Write-Host "The UM-Codex package (umcodex-<version>-py3-none-any.whl) wasn't found beside the installer."
        Write-Host "Download it from the same release into the installer's folder, or pass -Package <file or https URL>."
        Stop-Run 2
    }
}

# Check the package before anything else, so a wrong path is found before
# any administrator step or restart.
$IsUrl = $Package -match '^[a-zA-Z][a-zA-Z0-9+.-]*://'
if (-not $IsUrl) {
    # A bare file name ("umcodex-....whl") has no parent folder of its own, so
    # resolve it first: requirements.txt is looked for next to the real file.
    if (-not (Test-Path -LiteralPath $Package -PathType Leaf)) { Write-Host "Package file not found: $Package"; Stop-Run 2 }
    $Package = (Resolve-Path -LiteralPath $Package).ProviderPath
}
if (-not $Requirements -and -not $IsUrl) {
    $Beside = Join-Path ([System.IO.Path]::GetDirectoryName($Package)) "requirements.txt"
    if (Test-Path -LiteralPath $Beside) { $Requirements = $Beside }
}
if (-not $Requirements) { Write-Host "requirements.txt (every dependency, pinned by hash) wasn't found. Pass -Requirements."; Stop-Run 2 }
if ($Requirements -notmatch '^[a-zA-Z][a-zA-Z0-9+.-]*://') {
    if (-not (Test-Path -LiteralPath $Requirements -PathType Leaf)) { Write-Host "requirements.txt not found: $Requirements"; Stop-Run 2 }
    $Requirements = (Resolve-Path -LiteralPath $Requirements).ProviderPath
}
# The package's file name carries its version: umcodex-<version>-py3-none-any.whl
$FileName = [System.IO.Path]::GetFileName(($Package -split '\?')[0])
if ($FileName -notmatch '^umcodex-([0-9](?:[A-Za-z0-9.+!]*[A-Za-z0-9])?)-py3-none-any\.whl$') {
    Write-Host "The package must be a umcodex-<version>-py3-none-any.whl file."; Stop-Run 2
}
$Version = $Matches[1]

# How many restarts so far didn't make Docker usable, and when Windows had
# started at the time the last restart was asked for: 0 if no restart is
# waiting, -1 if one is but the start time couldn't be read.
$Restarts = 0
if ($saved) {
    if ($saved.Restarts) { $Restarts = [int]$saved.Restarts }
    if ($saved.RestartBoot) { $State.RestartBoot = [int64]$saved.RestartBoot }
}
if ($State.RestartBoot -ne 0) {
    $bootNow = Get-BootTime
    # Windows' start time can shift by a few seconds when its clock is set, so
    # only a clear change counts. With no start time to compare, a run from
    # the logon task counts as after a restart.
    $restarted = if ($State.RestartBoot -gt 0 -and $bootNow -gt 0) {
        [math]::Abs($bootNow - $State.RestartBoot) -gt [TimeSpan]::FromMinutes(2).Ticks
    } else { [bool]$Resume }
    if ($restarted) { $Restarts += 1; $State.RestartBoot = [int64]0 }
}

function Save-Progress($prepared) {
    New-Item -ItemType Directory -Force $StateDir | Out-Null
    @{ Package = $Package; Requirements = $Requirements; Prepared = $prepared
        ReplaceKey = [bool]$ReplaceKey; AdminAccessUrl = $AdminAccessUrl
        Restarts = $Restarts; RestartBoot = $State.RestartBoot } |
        ConvertTo-Json | Set-Content -Encoding UTF8 $ResumeFile
}

function Request-Restart {
    $State.RestartBoot = Get-BootTime
    if ($State.RestartBoot -eq 0) { $State.RestartBoot = [int64]-1 }
    Save-Progress $true
    Register-Resume
    Write-Host ""
    Note "Windows needs to restart to finish turning these on."
    Note "After the restart, sign in as usual. The UM-Codex installer opens by itself"
    Note "a few moments later and carries on from here. It shouldn't need"
    Note "administrator permission again."
    Note "Save anything you have open in other programs first."
    $State.Finished = $true  # a planned stop, not an interrupted one
    if (Ask "Restart now?") {
        Restart-Computer -Force
    } else {
        Say "OK. Restart whenever you're ready (Start menu > Power > Restart);"
        Say "the installer carries on after you sign in again."
    }
    Stop-Run 0
}

# Runs the administrator part and returns its result (ok, restart, error).
#
# It runs elevated, so it must not run anything that a program running as the
# person could have changed, and a script file (in Downloads or OneDrive, say)
# is one of those. So the elevated window gets a short, fixed command that
# reads a copy of this installer's text once, checks its SHA-256 against the
# text this window is running, and runs that checked text from memory; no file
# is run elevated. What it downloads and writes goes into a new folder only
# administrators can change (New-ProtectedFolder), which it lets the person
# read and remove once it's done.
#
# The command is passed with -EncodedCommand, and the values in it (the copy's
# path, the SID, the folder) as Base64 text, so no quoting is involved: a
# path with any kind of quote in it can't change the command. Before anything
# else, the command limits where PowerShell looks for modules to Windows' own
# folders and turns off loading them automatically, then loads the ones the
# administrator part uses from $PSHOME: the person's own module folders
# (Documents, or PSModulePath in their environment) are never used elevated.
function Invoke-AdminPart {
    if (-not $ScriptText) { Stop-Install "The installer couldn't read its own text, so it can't run the administrator part." }
    $work = Join-Path $AdminBase ($AdminFolderPrefix + [guid]::NewGuid().ToString("N"))
    $copy = Join-Path $Env:TEMP ($AdminFolderPrefix + [guid]::NewGuid().ToString("N") + ".ps1")
    $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($ScriptText)
    [System.IO.File]::WriteAllBytes($copy, $bytes)
    # Recorded first, so this exact folder (and only it) is removed later, even
    # if this window is closed before the administrator part finishes.
    New-Item -ItemType Directory -Force $StateDir | Out-Null
    Add-Content -LiteralPath $AdminRecord -Value $work -Encoding UTF8
    $data = { param($text) "(D '" + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($text)) + "')" }
    # The window stays open to show a problem: -Yes waits a while, otherwise it
    # waits for Enter. Only $Host is used for that, as other commands may not
    # have loaded yet.
    $pause = if ($Yes) { "[Threading.Thread]::Sleep(20000)" } else { "`$Host.UI.WriteLine('Press Enter to close this window.'); `$null = `$Host.UI.ReadLine()" }
    $command = @(
        "`$ErrorActionPreference = 'Stop'"
        "try {"
        "`$env:PSModulePath = `$PSHOME + '\Modules;' + [Environment]::GetFolderPath('ProgramFiles') + '\WindowsPowerShell\Modules'"
        "`$PSModuleAutoLoadingPreference = 'None'"
        "foreach (`$m in 'Microsoft.PowerShell.Management', 'Microsoft.PowerShell.Utility', 'Microsoft.PowerShell.Security', " +
            "'Microsoft.PowerShell.Host', 'Dism', 'Microsoft.PowerShell.LocalAccounts') { Import-Module (`$PSHOME + '\Modules\' + `$m) }"
        "function D(`$t) { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(`$t)) }"
        "`$b = [IO.File]::ReadAllBytes($(& $data $copy))"
        "`$h = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash(`$b))"
        "if (`$h -ne '$(Get-BytesHash $bytes)') { `$Host.UI.WriteErrorLine('The installer changed on disk after it started, so nothing was run.'); $pause; exit 1 }"
        "& ([scriptblock]::Create([Text.Encoding]::UTF8.GetString(`$b))) -Prepare -ForUserSid $(& $data $MySid) -WorkDir $(& $data $work)$(if ($Yes) { ' -Yes' })"
        "} catch {"
        "`$Host.UI.WriteErrorLine('The administrator part could not start: ' + `$_); $pause; exit 1"
        "}"
    ) -join "`n"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    Say "Asking Windows for permission now (look for the box; it may be behind this window)..."
    $started = $null
    try {
        # A cancelled box is only a non-terminating error to Start-Process
        # (CyberArk EPM's request box too): -ErrorAction Stop makes it one.
        $started = Start-Process $WindowsPowerShell -Verb RunAs -Wait -PassThru -ErrorAction Stop `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -EncodedCommand $encoded"
    } catch {
        $started = $null
        $why = $_.Exception.Message
    } finally {
        Remove-Item -LiteralPath $copy -ErrorAction SilentlyContinue
    }
    if (-not $started) {
        Stop-Install ("Windows didn't give administrator permission (declined: the box was closed or 'No' was " +
            "clicked, or your temporary administrator access isn't on, or has run out), so nothing was changed. " +
            "Turn on administrator access again (or ask IT for it), then run the installer again." +
            "`n   (Windows said: $why)")
    }
    $resultFile = Join-Path $work "result.json"
    if (-not (Test-AdminOwned $work) -or -not (Test-Path -LiteralPath $resultFile)) {
        Stop-Install "The administrator part closed before it finished."
    }
    $outcome = Get-Content -LiteralPath $resultFile -Raw | ConvertFrom-Json
    if (-not $outcome.ok) {
        Stop-Install ("The administrator part didn't finish: $($outcome.error)`n   " +
            "Details are saved in $(Join-Path $work 'setup.log')")
    }
    Remove-RecordedAdminFolder $MySid
    return $outcome
}

# Offers to run the administrator part again after a restart didn't fix
# something, then restarts. Never with -Yes: unattended, it would restart at
# every sign-in.
function Invoke-AdminPartAgain {
    if ($Yes) { return }
    Write-Host ""
    Say "You can also run the administrator part again now. If something on this"
    Say "computer undoes it, it won't last past the next restart either."
    if (Ask "Run the administrator part again?") {
        $null = Invoke-AdminPart
        Good "Windows is set up."
        Request-Restart
    }
}

# The administrator part ran and Windows restarted, but something it did is
# needed again. Running it (and restarting) again and again won't help, so
# this stops and says what's missing.
function Stop-StillMissing([string[]]$items) {
    Save-Progress $true  # keeps the count of restarts
    Write-Host ""
    Note "Windows has restarted after the administrator part, but this is still needed:"
    $items | ForEach-Object { Say "  - $_" }
    Say "On a managed computer, the likely cause is a policy that undoes it (for example,"
    Say "one that sets Docker Desktop's service back to starting by hand), or WSL or"
    Say "Docker Desktop being installed somewhere other than the usual place. Ask IT"
    Say "(the service desk), and show them this list."
    Invoke-AdminPartAgain
    Stop-Install "Windows isn't ready for Docker yet (see above)."
}

# Windows has restarted, but this sign-in still can't use Docker. Asking for
# another restart could repeat for ever (and with -Yes, restart at every
# sign-in), so this stops and says why.
function Stop-StillNoDocker {
    Save-Progress $true  # keeps the count of restarts
    Write-Host ""
    Note "Windows has restarted, but your account still can't use Docker."
    $member = Test-InDockerUsers $MySid
    if ($member -eq $true) {
        Say "Your account is in the '$DockerUsers' group, but Windows hasn't applied that to"
        Say "this sign-in. Sign out and in again, then run the installer again."
        $State.StoppedSaying = $true
        Stop-Run 1
    }
    if ($member -eq $false) {
        Say "Your account was added to the '$DockerUsers' group, but it isn't in it any more."
    } else {
        Say "Your account should be in the '$DockerUsers' group, but Windows doesn't show it there."
    }
    Say "On a managed computer, the likely cause is a group policy that resets who is in"
    Say "this computer's groups at each sign-in. Ask IT (the service desk) to let your"
    Say "account stay in the '$DockerUsers' group on this computer, and mention that a"
    Say "group policy seems to remove it."
    Invoke-AdminPartAgain
    Stop-Install "Your account can't use Docker yet (see above)."
}

Step "Step 1 of 7: Getting Windows ready (WSL and Docker Desktop)"
Say "UM-Codex runs Codex in Docker, a sealed-off space on your computer."
Say "Docker needs a Windows feature called WSL."
# WSL 2 needs hardware virtualization, which only the computer's firmware can
# turn on (administrator rights can't). Found out here, before any
# administrator step, download or restart, not after them. With a hypervisor
# already running (e.g. Credential Guard), the processor reports firmware
# virtualization as off, so a running hypervisor counts as on. If Windows
# can't say, carry on: an unknown isn't a refusal.
if (-not (Test-VirtualizationOn)) {
    Stop-Install ("This computer has virtualization turned off in its firmware (the settings " +
        "below Windows). UM-Codex needs it, and Windows settings or administrator rights can't " +
        "change it. Ask IT (the service desk) to turn on 'Intel Virtualization Technology " +
        "(VT-x)' or 'AMD-V / SVM' in this computer's firmware, then run the installer again. " +
        "Nothing was changed on this computer.")
}
$missing = @()
if (-not (Test-Path $WslExe)) { $missing += "Turn on WSL and install it (WSL $WslVersion, from Microsoft)" }
if (-not (Test-Path $DockerDesktop)) { $missing += "Install Docker Desktop $DockerVersion (from Docker)" }
if (Test-DockerServiceManual) { $missing += "Let Docker Desktop start without an administrator" }
$prepared = ($saved -and $saved.Prepared) -or (Test-InDockerUsers $MySid)
if (-not (Test-CanUseDocker) -and -not $prepared) { $missing += "Give your account permission to use Docker" }

# After the administrator part and a restart, the same things shouldn't be
# missing again; if they are, running it again every time won't help.
if ($missing -and $saved -and $saved.Prepared -and $Restarts -ge 1) { Stop-StillMissing $missing }
if ($missing) {
    Write-Host ""
    Say "To do that, Windows needs to:"
    $missing | ForEach-Object { Say "  - $_" }
    Write-Host ""
    Say "This needs administrator permission, just this once."
    Say "If your computer only gives you administrator access for a limited time"
    Say "(Michigan Medicine computers do), request it now, before you continue,"
    Say "and give it at least 30 minutes."
    if ($AdminAccessUrl) { Say "Turn it on here: $AdminAccessUrl" }
    Write-Host ""
    Say "When you continue:"
    Say "  1. Windows shows a box asking 'Do you want to allow this app to make"
    Say "     changes to your device?' Click Yes. (On a Michigan Medicine computer"
    Say "     you may be asked for your password or for a reason: 'Installing UM-Codex'.)"
    Say "  2. A second window opens and does the work. It can take 10 minutes or"
    Say "     more; leave it open until it closes by itself."
    Say "  3. Windows will then need a restart, and the installer carries on by"
    Say "     itself after you sign in again."
    if (-not (Test-Path $DockerDesktop)) {
        Say ""
        Say "Docker Desktop is used under Docker's Subscription Service Agreement:"
        Say "$DockerAgreement"
        Say "Continuing means you accept it."
    }
    Write-Host ""
    if (-not (Ask "Ready to continue?")) {
        Say "No problem. Nothing was changed; run the installer again when you're ready."
        $State.StoppedSaying = $true
        Stop-Run 1
    }

    $outcome = Invoke-AdminPart
    Good "Windows is set up."
    Save-Progress $true
    if ($outcome.restart -or -not (Test-CanUseDocker)) { Request-Restart }
} elseif (-not (Test-CanUseDocker)) {
    # The administrator part is done, but Windows only applies it at sign-in.
    # After one restart that didn't help, another won't either.
    if ($Restarts -ge 1) { Stop-StillNoDocker }
    Request-Restart
}
Good "WSL and Docker Desktop are ready."

Step "Step 2 of 7: Starting Docker Desktop"
# Docker's command for this window (and um-codex, started from it), if
# Docker Desktop was installed after the window opened.
if ((Test-Path -LiteralPath $DockerCliDir) -and -not (@($Env:Path -split ";") | Where-Object { Test-SamePath $_ $DockerCliDir })) {
    $Env:Path = "$Env:Path;$DockerCliDir"
}
if (-not (Test-DockerRunning)) {
    Say "Starting Docker Desktop. The first start can take a few minutes."
    Say "If Docker Desktop shows a welcome screen or asks you to sign in, you can"
    Say "skip it: UM-Codex doesn't need a Docker account. Leave Docker Desktop running."
    Clear-StaleDockerSockets
    if (Test-VmLogonRefused) { Repair-VmLogon }
    if (Test-Path $DockerDesktop) { Start-Process $DockerDesktop }
    # A real clock: each check can itself take up to 10 seconds.
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    $lastNote = 0
    do {
        Start-Sleep -Seconds 5
        $running = Test-DockerRunning
        $minutes = [int][math]::Floor($clock.Elapsed.TotalMinutes)
        if (-not $running -and $minutes -gt $lastNote) {
            $lastNote = $minutes
            Say "Still waiting for Docker Desktop ($minutes min)... this is normal the first time."
        }
    } until ($running -or $clock.Elapsed.TotalMinutes -ge 10)
    if (-not $running -and $State.VmLogonRepaired) {
        Stop-Install ("Windows lets Docker's virtual machine start again, but Docker Desktop didn't " +
            "get ready within 10 minutes. Restart Windows, then run the installer again.")
    }
    if (-not $running) {
        Stop-Install ("Docker Desktop didn't finish starting. Open it from the Start menu, wait until " +
            "it says 'Engine running' (bottom left), then run the installer again.")
    }
}
Good "Docker Desktop is running."

Step "Step 3 of 7: Installing uv (the tool that installs UM-Codex)"
# Nothing from the environment may steer uv or pip (another index, checks
# turned off) or Python. Put back afterwards: with `irm | iex` this is the
# person's own window.
@(Get-ChildItem Env: | Where-Object { $_.Name -match '^(UV|PIP)_' -or $_.Name -in 'PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV' }) |
    ForEach-Object { $SavedEnv[$_.Name] = $_.Value; Remove-Item -LiteralPath "Env:$($_.Name)" }
Install-PinnedUv
& $Uv --version

Step "Step 4 of 7: Installing UM-Codex"
# In UM-Codex's folder: app\versions\<version>\, current, previous, bin\um-codex.exe.
$Root = Join-Path $StateDir "app"
# A UM-Codex that's running holds its files open, and an update of the
# version it runs couldn't replace them. So it's closed first, never stopped
# by the installer.
while ($true) {
    $running = Get-RunningUmCodex $Root
    if (-not $running) { break }
    Write-Host ""
    Note "UM-Codex is running ($running). Quit Codex in its window first (or close"
    Note "that window)."
    if ($Yes) { Stop-Install "UM-Codex is running, so it wasn't changed. Quit it, then run the installer again." }
    $answer = Read-Host "   Press Enter once it's closed (or type q to stop here)"
    if ($answer -match '^q') {
        Say "OK. Nothing was changed; run the installer again when UM-Codex is closed."
        $State.StoppedSaying = $true
        Stop-Run 1
    }
}
# uv cuts a path at its first space ("failed to read from file
# C:\Users\me\OneDrive"), and on Michigan Medicine computers downloads usually
# sit under "OneDrive - Michigan Medicine". So uv gets the package and
# requirements.txt under plain names, from their own folder.
$Stage = Join-Path $StateDir "install"
if (Test-Path -LiteralPath $Stage) { Remove-Tree $Stage }
New-Item -ItemType Directory -Force $Stage | Out-Null
Get-Input $Package (Join-Path $Stage $FileName)
Get-Input $Requirements (Join-Path $Stage "requirements.txt")
# The package must be the one requirements.txt names, by its checksum.
$Sha256 = (Get-FileHash -LiteralPath (Join-Path $Stage $FileName) -Algorithm SHA256).Hash.ToLower()
$Pinned = Get-Content -LiteralPath (Join-Path $Stage "requirements.txt") | Where-Object { $_ -ceq "./$FileName --hash=sha256:$Sha256" }
if (-not $Pinned) {
    Stop-Install ("requirements.txt doesn't name this package with this checksum. Use the two " +
        "files from the same UM-Codex release.")
}
Say "Checked: SHA-256 of $FileName (as requirements.txt names it)"
$Target = Join-Path $Root "versions\$Version"
$Complete = Join-Path $Target ".complete"
if ((Test-Path -LiteralPath $Complete) -and ((Get-Content -LiteralPath $Complete -Raw) -match "`"wheel_sha256`": `"$Sha256`"")) {
    Good "UM-Codex $Version is installed already."
} else {
    # A folder without .complete (or with another package) is replaced.
    if (Test-Path -LiteralPath $Target) { Remove-Tree $Target }
    if (Test-Path -LiteralPath $Target) { Stop-Install "The folder $Target couldn't be replaced. Quit UM-Codex, then run the installer again." }
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "versions") | Out-Null
    & $Uv venv -q --no-config --python 3.13 $Target
    if ($LASTEXITCODE -ne 0) { Stop-Install "Making UM-Codex's Python environment didn't work (see the messages above)." }
    # Every file checked against requirements.txt's hashes, only wheels, and only from PyPI.
    Push-Location $Stage
    try {
        # Copies, not hardlinks into uv's cache: a hardlink fails in a
        # cloud-synced or redirected folder ("incompatible hardlinks").
        & $Uv pip install -q --no-config --require-hashes --only-binary :all: `
            --default-index https://pypi.org/simple --link-mode copy `
            --python (Join-Path $Target "Scripts\python.exe") -r requirements.txt
    } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) {
        Remove-Tree $Target
        Stop-Install "Installing UM-Codex didn't work (see the messages above)."
    }
    $Said = & (Join-Path $Target "Scripts\um-codex.exe") --version
    if ($Said -ne "UM-Codex $Version") {
        Remove-Tree $Target
        Stop-Install "The installed UM-Codex says '$Said', not $Version."
    }
    $Stamp = Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz"
    Set-Content -LiteralPath $Complete -Encoding ASCII `
        -Value "{`"version`": `"$Version`", `"wheel_sha256`": `"$Sha256`", `"installed_at`": `"$Stamp`"}"
}
Remove-Tree $Stage
# The `um-codex` command: bin\um-codex.exe, on the user PATH, a copy of this
# version's own launcher (uv's, which names this version's python.exe by its
# full path), so it runs the version `current` names. A real .exe, not a .cmd
# shim: cmd.exe asks "Terminate batch job (Y/N)?" after every Ctrl-C. (So no
# um-codex.cmd: PATHEXT prefers .exe, and one beside it would never run; an
# earlier one is removed.)
$Bin = Join-Path $Root "bin"
New-Item -ItemType Directory -Force -Path $Bin | Out-Null
$UmCodex = Join-Path $Bin "um-codex.exe"
Install-Launcher (Join-Path $Target "Scripts\um-codex.exe") $UmCodex
Remove-Item -LiteralPath (Join-Path $Bin "um-codex.cmd") -Force -ErrorAction SilentlyContinue
# (The command is copied first: `current` then names a version whose
# command is in place.)
# `current` names the version the launchers run (an update switches it, and
# keeps `previous`). Each is written whole, then moved into place, so a
# reader never sees half a file.
$CurrentFile = Join-Path $Root "current"
$Old = if (Test-Path -LiteralPath $CurrentFile) { "$(Get-Content -LiteralPath $CurrentFile -TotalCount 1)".Trim() } else { "" }
if ($Old -and $Old -ne $Version) { Write-Atomically (Join-Path $Root "previous") $Old }
Write-Atomically $CurrentFile $Version
Write-UvRecord $Root $Uv
& $UmCodex --version
Add-UserPath $Bin

Step "Step 5 of 7: Downloading UM-Codex's containers (about 2 GB; this takes a while)"
& $UmCodex pull
if ($LASTEXITCODE -ne 0) {
    Stop-Install ("Downloading the containers didn't work (the messages above say why). If you're " +
        "offline, reconnect, then run the installer again.")
}

Step "Step 6 of 7: Your U-M GPT Toolkit API key"
$KeyState = "not saved"
& (Join-Path $Target "Scripts\python.exe") -c "import sys; from umcodex import credentials; sys.exit(0 if credentials.has_api_key() else 1)"
$HasKey = ($LASTEXITCODE -eq 0)
if ($HasKey -and -not $ReplaceKey) {
    Good "A Toolkit key is saved already, so it was kept. (To replace it: um-codex key)"
    $KeyState = "saved (kept)"
} elseif ($Yes) {
    # (-Yes runs unattended, and the key has to come from the person.)
    Say "Skipped (-Yes). Add it later with: um-codex key"
} else {
    Say "Paste your Toolkit API key (see ITS's 'Codex Setup' articles for how to get one)."
    Say "Each character shows as *. Press Enter when done, or Ctrl-C to skip for now."
    Say "It's kept in Windows Credential Manager and never goes into the container."
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $Key = Read-MaskedKey "Toolkit API key"
        if (-not $Key) {
            Say "Skipped. Add it later with: um-codex key"
            break
        }
        $code = Send-Key $UmCodex $Key
        $Key = $null
        if ($code -eq 0) { $KeyState = "saved"; break }
        if ($code -eq 2) { Say "Skipped. Add it later with: um-codex key"; break }
        if ($attempt -lt 3) { Say "Let's try again." }
        else { Note "Not saved. Add it later with: um-codex key" }
    }
}

Step "Step 7 of 7: Adding UM-Codex to the Start menu and the Desktop"
# What the shortcuts contain comes from UM-Codex itself (umcodex/launchers.py),
# which `um-codex update` also uses to bring them up to date, so the two never
# differ: they open UM-Codex's launcher window (`um-codex ui --detach` starts
# it in the background, with no window of its own, and its page opens in the
# browser; starting a setup there opens Windows Terminal or Windows
# PowerShell with Codex in it). Windows PowerShell, hidden and minimized,
# runs bin\um-codex.exe (the version `current` names; an update replaces it),
# with PYTHONUTF8, and the icon is kept in icons\, beside bin\.
$StartMenu = Join-Path $Env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$LinkName = "UM-Codex"
# The program folder, quoted for a single-quoted PowerShell string (as in
# C:\Users\o'brien), then "\": every UM-Codex shortcut's command line has it,
# this one's and earlier installers' alike.
$QuotedRoot = [System.Management.Automation.Language.CodeGeneration]::EscapeSingleQuotedStringContent($Root)
$Marker = "'$QuotedRoot\"
$Desktop = [Environment]::GetFolderPath("Desktop")
$Links = @(Join-Path $StartMenu "$LinkName.lnk")
if ($Desktop) {
    # A Desktop shortcut of that name is replaced only if it's UM-Codex's (it
    # runs this program folder's UM-Codex); anything else there is the
    # person's own. (An earlier installer's, in Windows Terminal, has each
    # ";" written "\;".)
    $DesktopLink = Join-Path $Desktop "$LinkName.lnk"
    $Existing = if (Test-Path -LiteralPath $DesktopLink) { (New-Object -ComObject WScript.Shell).CreateShortcut($DesktopLink) } else { $null }
    if ($Existing -and "$($Existing.Arguments)".IndexOf($Marker, [StringComparison]::OrdinalIgnoreCase) -lt 0 -and
        "$($Existing.Arguments)".IndexOf($Marker.Replace(";", "\;"), [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        Note "Your Desktop already has a shortcut called $LinkName that isn't UM-Codex's; it was left alone."
        $Desktop = ""
    } else {
        $Links += $DesktopLink
    }
}
# With PYTHONUTF8, as the shortcuts run it (put back afterwards: with
# `irm | iex` this is the person's own window).
$SavedUtf8 = $Env:PYTHONUTF8
$Env:PYTHONUTF8 = "1"
try {
    & $UmCodex launchers --write @Links
    $Wrote = $LASTEXITCODE
} finally {
    if ($null -eq $SavedUtf8) { Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue } else { $Env:PYTHONUTF8 = $SavedUtf8 }
}
if ($Wrote -ne 0) {
    Stop-Install ("The Start menu shortcut couldn't be made (the messages above say why). Run the " +
        "installer again; UM-Codex itself is installed (type um-codex in a new terminal).")
}
Good "Added $LinkName to the Start menu$(if ($Desktop) { ' and the Desktop' }) (it opens UM-Codex's window in your browser)."
# The Codex app's one line in ~/.ssh/config, asked here once so that starting
# a setup in the Codex app needs no question later (`um-codex ssh-include`:
# the reason, then [Y/n], Return is yes). It asks only where "Open in: Codex
# app" works (on Windows too, experimental), with the Codex app installed and
# the line not there yet; with no terminal to answer in it adds nothing. With
# -Yes it isn't asked: the consent must be the person's, and the launcher
# window asks on the setup's card when it's needed.
if (-not $Yes) {
    $SavedUtf8 = $Env:PYTHONUTF8
    $Env:PYTHONUTF8 = "1"
    try {
        & $UmCodex ssh-include
    } finally {
        if ($null -eq $SavedUtf8) { Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue } else { $Env:PYTHONUTF8 = $SavedUtf8 }
    }
}
Remove-Item $ResumeFile -ErrorAction SilentlyContinue
Remove-Tree (Split-Path $ResumeScript -Parent)

# Done. Nothing is asked after this, so a Ctrl-C now can only end a finished
# install, never look like a failed one.
$State.Finished = $true
Write-Host ""
Write-Host "All done! UM-Codex $Version is installed." -ForegroundColor Green
Say "Start menu entry:  $(Join-Path $StartMenu "$LinkName.lnk")"
if ($Desktop) { Say "Desktop shortcut:  $(Join-Path $Desktop "$LinkName.lnk")" }
Say "Program files:     $Root"
Say "Command:           um-codex (in any new terminal window, and this one)"
Say "Toolkit key:       $KeyState"
Say "To open it: double-click $LinkName on your Desktop, or Start menu > type $LinkName"
Say "> press Enter. Its window opens in your browser: choose a folder to work in, and Codex"
Say "starts there in a terminal. Next time, one Start. Or type um-codex in a terminal."
Say "To remove it later: run uninstall.ps1 from the same release (it runs um-codex uninstall)."
} finally {
    if (-not $State.Finished -and -not $State.StoppedSaying) {
        # Ctrl-C, or something unexpected, part way through.
        Write-Host ""
        Write-Host "   Stopped before the end. Nothing is lost: run the installer again, and it" -ForegroundColor Yellow
        Write-Host "   picks up where it stopped." -ForegroundColor Yellow
    }
    foreach ($name in $SavedEnv.Keys) { Set-Item -LiteralPath "Env:$name" -Value $SavedEnv[$name] }
    $Host.UI.RawUI.WindowTitle = $OldTitle
    $SetupLock.Dispose()
}
}

# Runs the installer above. From a file, its folder is where a package beside
# it is looked for, and Stop-Run may `exit`. From `irm | iex`, a stop ends only
# the installer, and the person's window stays open with its messages.
$UmCodexFromFile = [bool]$PSCommandPath
$UmCodexScriptFolder = $PSScriptRoot
$UmCodexArguments = @{}
if ($PSBoundParameters) { $UmCodexArguments = $PSBoundParameters }
try {
    & $UmCodexInstaller @UmCodexArguments
} catch {
    if ("$($_.Exception.Message)" -ne "UM-Codex installer stopped") { throw }
} finally {
    if (-not $UmCodexFromFile) {
        # With `irm | iex` these (and the param block's) are now variables of
        # the person's session: take them out again.
        Remove-Variable -Scope Local -ErrorAction SilentlyContinue -Name UmCodexInstaller, UmCodexFromFile,
            UmCodexScriptFolder, UmCodexArguments, Package, Requirements, ReplaceKey, AdminAccessUrl, Yes,
            Resume, Prepare, ForUserSid, WorkDir
    }
}
