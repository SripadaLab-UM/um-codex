# UM-Codex uninstaller for Windows.
# Adapted from IHS DataLab's installer/windows/uninstall.ps1 at 6b6fdca (with
# PR #36's read-only and Linux-symlink findings, and 615cd0f's downloads folder).
#
#   irm <release>/uninstall-windows.ps1 | iex
#   powershell -NoProfile -ExecutionPolicy Bypass -File uninstall.ps1 [-DeleteData | -KeepData] [-Yes]
#
# First `um-codex uninstall` removes UM-Codex's containers, networks, images
# and the Toolkit key in Credential Manager, and asks before deleting
# UM-Codex's data (saved setups, logs, each setup's Codex history; -DeleteData
# and -KeepData answer for it). Then this removes the program files (every
# version, the command, the icons, the updater's downloads), the Start menu
# and Desktop shortcuts, the `um-codex` entry in your PATH, and what the
# installer left behind (its after-restart task or shortcut, its progress
# files, the administrator part's folder). Your own folders are never
# touched. It leaves Docker Desktop, WSL and uv's downloads installed, and at
# the end says how to remove each of them, and anything it couldn't remove.
param([switch]$DeleteData, [switch]$KeepData, [switch]$Yes)
$UmCodexUninstaller = {
param([switch]$DeleteData, [switch]$KeepData, [switch]$Yes)
$ErrorActionPreference = "Stop"
# With `irm | iex` this runs under the person's own profile settings: no
# strict mode, and no default parameter values of theirs.
Set-StrictMode -Off
$PSDefaultParameterValues = @{}
# Ends the uninstaller with an exit code: `exit` from a file, but with
# `irm | iex` only the uninstaller (see install.ps1's Stop-Run).
$StopMarker = "UM-Codex uninstaller stopped"
function Stop-Run([int]$code) {
    if ($UmCodexFromFile -or -not $UmCodexUninstaller) { exit $code }
    $global:LASTEXITCODE = $code
    throw $StopMarker
}
$StateDir = Join-Path $Env:LOCALAPPDATA "UM-Codex"
$Root = Join-Path $StateDir "app"
$Bin = Join-Path $Root "bin"
if ($DeleteData -and $KeepData) {
    Write-Host "Choose one: -DeleteData or -KeepData (or neither, to be asked)."
    Stop-Run 2
}

# The installer's leftovers, first, so an install waiting for a restart can't
# start again after this. The names and checks match install.ps1.
$MySid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
Unregister-ScheduledTask -TaskName "UM-Codex setup for $MySid (continue after restart)" -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath("Startup")) "UM-Codex setup.lnk") -ErrorAction SilentlyContinue
Remove-Item (Join-Path $StateDir "installer-resume.json") -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $Env:TEMP -File -Filter "UM-Codex-setup-*.ps1" -Force -ErrorAction SilentlyContinue |
    Where-Object { -not ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue }

# The administrator part's result and log, which it left for this account to
# remove: only the exact folders the installer recorded, never a pattern
# (anyone can create folders in ProgramData). Names and checks match install.ps1.
$AdminBase = [Environment]::GetFolderPath("CommonApplicationData")
$AdminFolderPrefix = "UM-Codex-setup-"
$AdminFolderPattern = "^" + [regex]::Escape((Join-Path $AdminBase $AdminFolderPrefix)) + "[0-9a-f]{32}$"
$AdminRecord = Join-Path $StateDir "installer-admin-folder.txt"
$SystemSid = "S-1-5-18"
$AdminsSid = "S-1-5-32-544"
$OwnerRightsSid = "S-1-3-4"

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

Remove-RecordedAdminFolder $MySid

# UM-Codex's own uninstall: containers, networks, images, the key, and (if
# asked) the data. It refuses while UM-Codex is running, and then none of
# UM-Codex's files are removed either. It's run as the version `current`
# names, from that version's own folder.
$choice = @()
if ($DeleteData) { $choice += "--delete-data" } elseif ($KeepData) { $choice += "--keep-data" }
if ($Yes) { $choice += "--yes" }
$Version = ""
$CurrentFile = Join-Path $Root "current"
if (Test-Path -LiteralPath $CurrentFile -PathType Leaf) { $Version = "$(Get-Content -LiteralPath $CurrentFile -TotalCount 1)".Trim() }
$NotDone = @()
$Program = Join-Path $Root "versions\$Version\Scripts\um-codex.exe"
if ($Version -and (Test-Path -LiteralPath $Program -PathType Leaf)) {
    $before = $Env:PYTHONUTF8
    $Env:PYTHONUTF8 = "1"
    try { & $Program uninstall @choice; $code = $LASTEXITCODE }
    finally { if ($null -eq $before) { Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue } else { $Env:PYTHONUTF8 = $before } }
    if ($code -ne 0) {
        Write-Host ""
        Write-Host "UM-Codex's program files were left as they were. Once that's sorted out, run the" -ForegroundColor Yellow
        Write-Host "uninstaller again." -ForegroundColor Yellow
        Stop-Run $code
    }
} else {
    Write-Host "UM-Codex's program wasn't found (or is incomplete), so `"um-codex uninstall`" couldn't run."
    $NotDone += "UM-Codex's containers, networks and images in Docker (labelled um-codex), if any:"
    $NotDone += "  remove them in Docker Desktop (Containers, Images, Volumes)."
    $NotDone += "The Toolkit key, if one was saved: Control Panel > Credential Manager >"
    $NotDone += "  Windows Credentials > UM-Codex > Remove."
}

# The installer's own folders: its saved copy, its staging folder and uv.
foreach ($name in "installer", "install", "uv") { Remove-Tree (Join-Path $StateDir $name) }
foreach ($folder in @(Get-ChildItem -LiteralPath $StateDir -Directory -Filter "uv-download-*" -Force -ErrorAction SilentlyContinue)) {
    Remove-Tree $folder.FullName
}

# The program files: only what install.ps1 and the updater put there
# (downloads: a release while it installs); anything else in the folder stays.
foreach ($name in "versions", "bin", "icons", "downloads") { Remove-Tree (Join-Path $Root $name) }
foreach ($name in "current", "previous", "launchers") {
    $file = Join-Path $Root $name
    $item = Get-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue
    if ($item -and -not $item.PSIsContainer) { Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue }
}
$Left = @()
if (Test-Path -LiteralPath $Root) {
    $inRoot = @(Get-ChildItem -LiteralPath $Root -Force -ErrorAction SilentlyContinue)
    if ($inRoot.Count -eq 0) { Remove-Tree $Root }
    foreach ($entry in $inRoot) {
        if ($entry.Name -in "versions", "bin", "icons", "downloads", "current", "previous", "launchers") {
            $Left += "$($entry.FullName) (couldn't be removed: a file still in use? Delete it yourself)"
        } else {
            $Left += "$($entry.FullName) (not UM-Codex's, so it was left)"
        }
    }
}

# The Start menu entry, and the Desktop shortcut only if it's UM-Codex's: its
# command line names this program folder (single-quoted, then "\"), as every
# installer and `um-codex launchers` (umcodex/launchers.py) write it.
$StartMenu = Join-Path $Env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$Link = Join-Path $StartMenu "UM-Codex.lnk"
if (Test-Path -LiteralPath $Link -PathType Leaf) { Remove-Item -LiteralPath $Link -Force }
$QuotedRoot = [System.Management.Automation.Language.CodeGeneration]::EscapeSingleQuotedStringContent($Root)
$Marker = "'$QuotedRoot\"
$Desktop = [Environment]::GetFolderPath("Desktop")
if ($Desktop) {
    $Link = Join-Path $Desktop "UM-Codex.lnk"
    if (Test-Path -LiteralPath $Link -PathType Leaf) {
        $Shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($Link)
        $arguments = "$($Shortcut.Arguments)"
        if ($arguments.IndexOf($Marker, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
            $arguments.IndexOf($Marker.Replace(";", "\;"), [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            Remove-Item -LiteralPath $Link -Force
        } else {
            Write-Host "   (Left $Link on your Desktop: it isn't UM-Codex's.)"
        }
    }
}

# The `um-codex` command's folder in the user PATH: that one entry only.
$UserPath = Get-UserPath
$entries = @($UserPath.Value -split ";" | Where-Object { "$_".Trim() })
$kept = @($entries | Where-Object { -not (Test-SamePath $_ $Bin) })
if ($kept.Count -ne $entries.Count) {
    New-ItemProperty -Path "HKCU:\Environment" -Name "Path" -Value ($kept -join ";") -PropertyType $UserPath.Kind -Force | Out-Null
    Send-EnvironmentChanged
}
$Env:Path = (@($Env:Path -split ";" | Where-Object { $_ -and -not (Test-SamePath $_ $Bin) })) -join ";"

# UM-Codex's own folder goes too once it's empty: kept data (saved setups,
# logs) keeps it, and says so.
if (Test-Path -LiteralPath $StateDir) {
    $inState = @(Get-ChildItem -LiteralPath $StateDir -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne "app" })
    if ($inState.Count -eq 0 -and -not (Test-Path -LiteralPath $Root)) { Remove-Tree $StateDir }
    elseif ($inState.Count -gt 0) {
        $Left += "$StateDir (UM-Codex's data: $(($inState | ForEach-Object Name) -join ', '))"
    }
}

Write-Host ""
Write-Host "UM-Codex has been removed." -ForegroundColor Green
if ($Left) {
    Write-Host ""
    Write-Host "Still on this computer:"
    $Left | ForEach-Object { Write-Host "  - $_" }
}
if ($NotDone) {
    Write-Host ""
    Write-Host "Not removed, as um-codex couldn't run:"
    $NotDone | ForEach-Object { Write-Host "  - $_" }
}
Write-Host ""
Write-Host "Still installed, because other programs may use them (remove them only if nothing"
Write-Host "else on this computer needs them):"
Write-Host "  - Docker Desktop: Start menu > Settings > Apps > Installed apps > Docker Desktop >"
Write-Host "    Uninstall. It needs an administrator (on a managed computer, ask IT)."
Write-Host "  - WSL (Windows Subsystem for Linux): Settings > Apps > Installed apps > Windows"
Write-Host "    Subsystem for Linux > Uninstall. The Windows features it turned on stay on until an"
Write-Host "    administrator turns them off in 'Turn Windows features on or off' (Virtual Machine"
Write-Host "    Platform, Windows Subsystem for Linux)."
Write-Host "  - uv's downloads (its cache and the Python it installed), in PowerShell:"
Write-Host "      Remove-Item -Recurse `"$(Join-Path $Env:LOCALAPPDATA 'uv')`", `"$(Join-Path $Env:APPDATA 'uv')`""
Write-Host "    (UM-Codex's own copy of uv was removed.)"
Write-Host "  - Your account's membership of the docker-users group, which an administrator can"
Write-Host "    remove in Computer Management > Local Users and Groups (IT, on a managed computer)."
Write-Host "Your own folders were not touched."
}

# Runs the uninstaller above (see install.ps1's runner).
$UmCodexFromFile = [bool]$PSCommandPath
$UmCodexArguments = @{}
if ($PSBoundParameters) { $UmCodexArguments = $PSBoundParameters }
try {
    & $UmCodexUninstaller @UmCodexArguments
} catch {
    if ("$($_.Exception.Message)" -ne "UM-Codex uninstaller stopped") { throw }
} finally {
    if (-not $UmCodexFromFile) {
        # With `irm | iex` these (and the param block's) are now variables of
        # the person's session: take them out again.
        Remove-Variable -Scope Local -ErrorAction SilentlyContinue -Name UmCodexUninstaller, UmCodexFromFile,
            UmCodexArguments, DeleteData, KeepData, Yes
    }
}
