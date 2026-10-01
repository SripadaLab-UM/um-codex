# Adapted from IHS DataLab's backend/tests/test_windows_installer.py at 6b6fdca.
"""installer/windows: what can be checked without Windows.

CI's windows-installer job parses both scripts with Windows PowerShell 5.1,
runs their package-finding lines, and runs the Docker Desktop restart
functions over captured tasklist/taskkill/wsl output; these check the rest of
what the scripts promise each other, UM-Codex and the release.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WINDOWS = REPO / "installer" / "windows"
INSTALL = (WINDOWS / "install.ps1").read_text(encoding="utf-8")
UNINSTALL = (WINDOWS / "uninstall.ps1").read_text(encoding="utf-8")
SCRIPTS = {"install.ps1": INSTALL, "uninstall.ps1": UNINSTALL}
SHARED_START = "# --- Shared by install.ps1 and uninstall.ps1"
SHARED_END = "# --- End of the part shared by install.ps1 and uninstall.ps1"


def code(text: str) -> str:
    """Without whole-line comments."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def bare(text: str) -> str:
    """Code without comments, here-strings or quoted strings: what's left is
    PowerShell syntax, for the checks on syntax Windows PowerShell 5.1 lacks."""
    text = re.sub(r"(?ms)^\$\w+ = @'\n.*?\n'@$", "", text)
    lines = []
    for line in code(text).splitlines():
        line = re.sub(r"'[^']*'", "''", line)
        line = re.sub(r'"(?:`.|[^"`])*"', '""', line)
        lines.append(line.split(" # ")[0])
    return "\n".join(lines)


def function(text: str, name: str) -> str:
    start = text.index(f"\nfunction {name}")
    return text[start : text.index("\n}\n", start) + 3]


def shared(text: str) -> str:
    assert text.count(SHARED_START) == 1 and text.count(SHARED_END) == 1
    return text[text.index(SHARED_START) : text.index(SHARED_END)]


def person_part(text: str) -> str:
    return text[text.index("# The installer, run as the person installing.") :]


def admin_part(text: str) -> str:
    start = text.index("if ($Prepare) {")
    return text[start : text.index("# The installer, run as the person installing.")]


def step(number: int) -> str:
    start = INSTALL.index(f'Step "Step {number} of 7')
    after = INSTALL.find(f'Step "Step {number + 1} of 7', start)
    return INSTALL[start : after if after != -1 else INSTALL.index("$State.Finished = $true\nWrite-Host")]


# --- Windows PowerShell 5.1, as people run it ---------------------------------


@pytest.mark.parametrize("name", SCRIPTS)
def test_the_scripts_are_ascii_with_lf_line_endings(name):
    """Windows PowerShell 5.1 reads a script without a BOM as the ANSI code
    page, so the scripts stay ASCII; .gitattributes keeps them LF."""
    raw = (WINDOWS / name).read_bytes()
    assert raw.isascii(), name
    assert b"\r" not in raw, name
    attributes = (REPO / ".gitattributes").read_text(encoding="utf-8")
    assert "*.ps1 text eol=lf" in attributes
    assert "*.cmd text eol=crlf" in attributes


@pytest.mark.parametrize("name", SCRIPTS)
def test_no_syntax_windows_powershell_51_lacks(name):
    body = bare(SCRIPTS[name])
    # Pipeline chains, null-coalescing, null-conditional and the ternary are PowerShell 7.
    for token in ("&&", "||", "??", "?.", "?["):
        assert token not in body, token
    assert not re.search(r"\s\?\s", body), "ternary"
    # PowerShell 6+ parameters and variables.
    for later in (
        "-Parallel",
        "-AsHashtable",
        "-AsByteStream",
        "utf8NoBOM",
        "-SkipCertificateCheck",
        "$IsWindows",
        "$IsLinux",
        "$IsMacOS",
        "Test-Json",
        "-AdditionalChildPath",
        "clean {",
    ):
        assert later not in body, later
    # Without -UseBasicParsing, 5.1's Invoke-WebRequest needs Internet Explorer's engine.
    for line in body.splitlines():
        if "Invoke-WebRequest" in line:
            assert "-UseBasicParsing" in line, line


@pytest.mark.parametrize("name", SCRIPTS)
def test_braces_and_parentheses_balance(name):
    body = bare(SCRIPTS[name])
    assert body.count("{") == body.count("}")
    assert body.count("(") == body.count(")")


@pytest.mark.parametrize("name", SCRIPTS)
def test_read_only_automatic_variables_are_never_assigned(name):
    """$HOME and friends are read-only: assigning one stops the script."""
    for variable in ("Home", "Host", "Input", "Args", "PSItem", "Error", "Profile", "PID", "PSHOME"):
        assert not re.search(rf"(?im)^\s*\${variable}\s*=[^=]", code(SCRIPTS[name])), variable


# --- irm | iex and file runs ---------------------------------------------------


BLOCKS = [("install.ps1", "UmCodexInstaller"), ("uninstall.ps1", "UmCodexUninstaller")]


@pytest.mark.parametrize(("name", "block"), BLOCKS)
def test_one_script_block_with_the_same_params_runs_from_a_file_or_from_iex(name, block):
    text = SCRIPTS[name]
    params = re.findall(r"(?ms)^param\(.*?^\)$|^param\(\[[^\n]*\)$", text)
    assert len(params) == 2 and params[0] == params[1], name
    assert text.count(f"${block} = {{\nparam(") == 1
    # The runner: a hashtable splat (never $args), and a stop that ends only
    # the script when it was piped to iex (exit would close the person's window).
    runner = text[text.rindex("$UmCodexFromFile = [bool]$PSCommandPath") :]
    assert f"& ${block} @UmCodexArguments" in runner
    assert '-ne "UM-Codex ' in runner and "{ throw }" in runner
    stop = function(text, "Stop-Run")
    assert f"if ($UmCodexFromFile -or -not ${block}) {{ exit $code }}" in stop
    assert "throw $StopMarker" in stop
    marker = re.search(r'\$StopMarker = "([^"]+)"', text).group(1)
    assert f'-ne "{marker}"' in runner


@pytest.mark.parametrize("name", SCRIPTS)
def test_exit_is_used_only_where_it_ends_just_this_script(name):
    """With `irm | iex`, `exit` closes the person's own PowerShell window: the
    person's part stops through Stop-Run. Only Stop-Run and the administrator
    part (always its own process) exit."""
    text = SCRIPTS[name]
    allowed = function(text, "Stop-Run")
    if name == "install.ps1":
        allowed += admin_part(text) + function(text, "Invoke-AdminPart")
    for match in re.finditer(r"(?m)\bexit\b(?! /b)", bare(text)):
        line = bare(text)[: match.end()].splitlines()[-1]
        assert line.strip() and line.strip() in bare(allowed), line


def test_script_scope_isnt_used_inside_the_script_block():
    """In the script block, $script: is the file's scope (or, with iex, the
    person's session), not the installer's: shared state is a hashtable."""
    for text in SCRIPTS.values():
        assert "$script:" not in code(text)
    assert "$State = @{ StoppedSaying = $false; Finished = $false; VmLogonRepaired = $false" in INSTALL


def test_the_installer_text_for_the_admin_part_and_the_resume_is_the_blocks_own():
    assert "$ScriptText = if ($UmCodexInstaller) { $UmCodexInstaller.ToString() }" in INSTALL
    resume = function(INSTALL, "Register-Resume")
    assert "WriteAllBytes($ResumeScript" in resume and '-File `"$ResumeScript`" -Resume' in resume
    assert "-ExecutionPolicy Bypass" in resume


def test_the_release_fills_in_its_own_package():
    for name in ("ReleaseBase", "ReleaseWheel"):
        assert len(re.findall(rf'(?m)^\${name} = ""$', INSTALL)) == 1
    assert '$Package = "$ReleaseBase/$ReleaseWheel"' in INSTALL
    assert '$Requirements = "$ReleaseBase/requirements.txt"' in INSTALL


# --- The shared block, and what CI runs on its own -----------------------------


def test_the_shared_block_is_byte_identical_in_both_scripts():
    assert shared(INSTALL) == shared(UNINSTALL)
    functions = (
        "Get-ReparseTag",
        "Test-Link",
        "Remove-Entry",
        "Remove-Tree",
        "Test-AdminOwned",
        "Test-AdminFolder",
        "Remove-RecordedAdminFolder",
        "Get-UserPath",
        "Test-SamePath",
        "Send-EnvironmentChanged",
    )
    for name in functions:
        assert f"\nfunction {name}" in shared(INSTALL), name


@pytest.mark.parametrize(
    "marker",
    [
        "if (-not $Package) {",
        "$IsUrl =",
        "if (-not $Requirements) { Write-Host",
        "$Version = $Matches[1]",
        "\n$DockerDesktopImages = ",
        "\nfunction Invoke-Captured(",
        "\nfunction Get-OwnPids(",
        "\nfunction Stop-DockerDesktopProcesses {",
        "\nfunction Stop-DockerVm {",
        "\n$UvVersion = ",
        "\nfunction Install-PinnedUv {",
    ],
)
def test_the_lines_ci_runs_on_their_own_are_still_there(marker):
    """ci.yml's windows-installer job slices the script at these, or runs
    these functions on their own."""
    assert INSTALL.count(marker) == 1


def test_ci_runs_the_restart_functions_over_captured_output():
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "runs-on: windows-latest" in ci and "shell: powershell" in ci
    assert "[System.Management.Automation.Language.Parser]::ParseFile" in ci
    for name in ("Invoke-Captured", "Get-OwnPids", "Stop-DockerDesktopProcesses", "Stop-DockerVm"):
        assert f'"{name}"' in ci
    # tasklist, taskkill and wsl.exe as they answered on the Michigan Medicine laptop.
    assert "INFO: No tasks are running which match the specified criteria." in ci
    assert "INFO: No tasks running with the specified criteria." in ci
    assert "WSL_E_DISTRO_NOT_FOUND" in ci
    assert "OTHER\\someone" in ci  # another account's Docker Desktop is never ended


# --- Docker, WSL and the VM logon right ---------------------------------------


def test_taskkill_only_closes_this_accounts_docker_desktop_by_id_with_its_filters():
    """taskkill only closes Docker Desktop (Repair-VmLogon), by its own
    programs' names and this account's user name: never UM-Codex, never
    another account's processes, never Docker's SYSTEM service."""
    assert "Stop-Process" not in code(INSTALL)
    stop = code(function(INSTALL, "Stop-DockerDesktopProcesses"))
    assert code(INSTALL).lower().count("taskkill") == stop.lower().count("taskkill") == 1
    assert "foreach ($image in $DockerDesktopImages)" in stop
    assert '/F /FI `"IMAGENAME eq $image`" /FI `"USERNAME eq $me`" /PID $id' in stop
    assert "[System.Security.Principal.WindowsIdentity]::GetCurrent().Name" in stop
    assert "com.docker.service" not in re.search(r"(?m)^\$DockerDesktopImages = .*$", INSTALL).group(0)
    listing = function(INSTALL, "Get-OwnPids")
    assert '/FI `"IMAGENAME eq $image`" /FI `"USERNAME eq $me`" /FO CSV /NH' in listing
    assert "return ,@(" in listing  # an empty list stays a list, not $null


def test_wsl_is_only_ever_asked_to_stop_dockers_own_distribution():
    body = code(INSTALL)
    assert "--shutdown" not in body
    assert '"--terminate docker-desktop"' in function(INSTALL, "Stop-DockerVm")
    assert '@("--terminate", "docker-desktop")' in function(INSTALL, "Clear-StaleDockerSockets")
    # The VM check starts WSL's own system distribution, never Docker's.
    assert '"--system", "-e", "true"' in function(INSTALL, "Test-VmLogonRefused")
    # Every run of wsl.exe, and what it's asked.
    runs = re.findall(r'(?:"wsl\.exe"\)|Invoke-Quiet \$WslExe|Start-Process \$wsl) (.*)', body)
    assert len(runs) == 3
    for arguments in runs:
        assert "docker-desktop" in arguments or '"--system", "-e", "true"' in arguments, arguments


def test_every_capture_has_a_time_limit():
    assert "WaitForExit($seconds * 1000)" in function(INSTALL, "Invoke-Captured")
    for call in re.findall(r"Invoke-Captured \([^)]*\) `?\s*\"[^\n]*", INSTALL):
        assert re.search(r"\" \d+$", call), call
    # docker info gives up after 10 seconds: a stuck engine makes it wait for ever.
    assert '(Invoke-Quiet $docker @("info") 10) -eq 0' in function(INSTALL, "Test-DockerRunning")


def test_the_vm_logon_fix_matches_umcodex_and_runs_from_memory():
    grant = re.search(r"(?ms)^\$VmLogonGrant = @'\n(.*?)\n'@$", INSTALL).group(1)
    assert "'S-1-5-83-0'" in grant and "'SeServiceLogonRight'" in grant
    assert "LsaAddAccountRights" in grant and "Add-Type" not in grant
    module = REPO / "src" / "umcodex" / "windows_vm.py"
    if not module.exists():
        pytest.skip("windows_vm.py isn't on this branch yet")
    source = module.read_text(encoding="utf-8")
    python = re.search(r'GRANT_SCRIPT = r"""\n(.*?)\n"""', source, re.S).group(1)
    assert grant == python
    images = re.search(r"DOCKER_DESKTOP_IMAGES = \((.*?)\)", source, re.S).group(1)
    assert re.findall(r'"([^"]+)"', images) == re.findall(
        r'"([^"]+)"', re.search(r"(?m)^\$DockerDesktopImages = .*$", INSTALL).group(0)
    )


def test_a_cancelled_admin_box_is_declined_and_can_be_tried_again():
    """Cancelling CyberArk EPM's request box is only a non-terminating error
    to Start-Process: it must read as "declined" (turn on the administrator
    access, try again), never as done or as "restart Windows"."""
    grant = function(INSTALL, "Invoke-VmLogonGrant")
    assert "-Verb RunAs -Wait -PassThru -WindowStyle Hidden -ErrorAction Stop" in grant
    assert 'if (-not $grant -or $grant.ExitCode -ne 0) { return "declined" }' in grant
    assert 'return "still-refused"' in grant
    repair = function(INSTALL, "Repair-VmLogon")
    assert 'Ask "Try again?"' in repair and "Say-AdminAccess" in repair
    assert "$Yes -or -not (Ask" in repair  # unattended, it never loops
    admin = function(INSTALL, "Invoke-AdminPart")
    assert "-Verb RunAs -Wait -PassThru -ErrorAction Stop" in admin
    assert "if (-not $started) {" in admin and "declined" in admin


def test_after_the_fix_docker_desktop_is_restarted_afresh_or_windows_restarted():
    repair = function(INSTALL, "Repair-VmLogon")
    assert "$State.VmLogonRepaired = $true" in repair
    assert repair.index("Stop-DockerDesktopProcesses") < repair.index("Stop-DockerVm")
    assert "docker desktop restart" not in code(repair)
    two = step(2)
    assert two.index("Test-VmLogonRefused") < two.index("Start-Process $DockerDesktop")
    assert "if (-not $running -and $State.VmLogonRepaired)" in two
    assert "Restart Windows" in two


def test_the_jit_admin_access_is_explained_before_any_admin_prompt():
    one = step(1)
    assert one.index("request it now, before you continue") < one.index("Invoke-AdminPart")
    assert "'Installing UM-Codex'" in one  # CyberArk EPM asks for a reason
    assert "$AdminAccessUrl" in function(INSTALL, "Say-AdminAccess")
    assert "-AdminAccessUrl isn't an https:// address, so it's ignored." in INSTALL


def test_virtualization_is_checked_before_any_administrator_step():
    check = INSTALL.index("if (-not (Test-VirtualizationOn))")
    assert check < INSTALL.index('Say "This needs administrator permission, just this once."')
    assert check < INSTALL.index('Step "Step 2 of 7')
    body = function(INSTALL, "Test-VirtualizationOn")
    assert "HypervisorPresent" in body and "VirtualizationFirmwareEnabled" in body
    assert "return $true" in body.split("catch")[1]


def test_quickedit_is_turned_off_in_memory_for_the_admin_window_only():
    assert "Add-Type" not in code(INSTALL)  # it compiles through files in TEMP
    assert "Disable-QuickEdit" in admin_part(INSTALL)
    # The registry is only touched for the user PATH.
    for text in SCRIPTS.values():
        assert set(re.findall(r"HKCU:[^\"']*", code(text))) <= {"HKCU:\\Environment"}
        assert "Set-ItemProperty" not in code(text)


def test_the_admin_part_installs_windows_pieces_and_nothing_of_umcodex():
    admin = admin_part(INSTALL)
    for command in ("um-codex", "$Uv", "pull", "--from-stdin"):
        assert command not in code(admin), command
    for command in ("& $UmCodex pull", "Send-Key $UmCodex $Key", "Install-PinnedUv"):
        assert command in person_part(INSTALL), command


def test_each_checked_download_is_logged_with_its_publisher():
    assert 'Say "Checked: SHA-256 and signature ($signedBy)"' in INSTALL


# --- uv and the package --------------------------------------------------------


def test_it_installs_only_what_requirements_txt_pins():
    assert "uv tool install" not in code(INSTALL)
    assert "--require-hashes --only-binary :all:" in INSTALL
    assert "--default-index https://pypi.org/simple --link-mode copy" in INSTALL
    assert "--no-config" in INSTALL and "-r requirements.txt" in INSTALL
    assert "'^(UV|PIP)_'" in INSTALL  # uv's and pip's settings don't come from the environment
    # ... and put back afterwards (with irm | iex it's the person's window).
    assert 'Set-Item -LiteralPath "Env:$name" -Value $SavedEnv[$name]' in INSTALL
    assert '$_ -ceq "./$FileName --hash=sha256:$Sha256"' in INSTALL


def test_uv_is_the_pinned_release_checked_and_used_by_full_path():
    pins = dict(re.findall(r'(?m)^\$(Uv\w+) = "([^"]*)"$', INSTALL))
    assert re.fullmatch(r"\d+\.\d+\.\d+", pins["UvVersion"])
    assert pins["UvZipUrl"] == (
        f"https://github.com/astral-sh/uv/releases/download/{pins['UvVersion']}/uv-x86_64-pc-windows-msvc.zip"
    )
    assert re.fullmatch(r"[0-9a-f]{64}", pins["UvZipSha256"])
    assert pins["UvPublisher"]
    body = code(INSTALL)
    assert "irm " not in body and "| iex" not in body and "Invoke-Expression" not in body
    assert "& $Uv venv" in body and "& $Uv pip install" in body
    assert not re.search(r"(?m)^\s*uv\s", body) and "Get-Command uv" not in body


def test_uv_gets_the_files_under_plain_names_from_their_own_folder():
    """uv cuts a path at its first space ("OneDrive - Michigan Medicine")."""
    four = step(4)
    assert "Get-Input $Package (Join-Path $Stage $FileName)" in four
    assert 'Get-Input $Requirements (Join-Path $Stage "requirements.txt")' in four
    assert "Push-Location $Stage" in four


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        ("umcodex-0.1.0a1-py3-none-any.whl", True),
        ("umcodex-7-py3-none-any.whl", True),
        ("umcodex-1.-py3-none-any.whl", False),
        ("umcodex-.1-py3-none-any.whl", False),
        ("umcodex-latest-py3-none-any.whl", False),
        ("datalab-0.1.0-py3-none-any.whl", False),
    ],
)
def test_the_package_name_must_carry_a_version(name, ok):
    pattern = re.search(r"-notmatch '(\^umcodex-[^']+)'", INSTALL)
    assert pattern is not None
    assert bool(re.match(pattern.group(1), name)) is ok


def test_versions_side_by_side_and_a_stable_command_on_the_user_path():
    four = step(4)
    assert '$Root = Join-Path $StateDir "app"' in four
    assert '$StateDir = Join-Path $Env:LOCALAPPDATA "UM-Codex"' in INSTALL
    assert '$Target = Join-Path $Root "versions\\$Version"' in four
    assert '"UM-Codex $Version"' in four  # um-codex --version says so
    # `current` and `previous` written whole, then moved into place; read
    # without failing on an empty file.
    assert "Write-Atomically $CurrentFile $Version" in four
    assert 'Write-Atomically (Join-Path $Root "previous") $Old' in four
    atomic = function(INSTALL, "Write-Atomically")
    assert 'Set-Content -LiteralPath "$file.tmp"' in atomic
    assert 'Move-Item -LiteralPath "$file.tmp" -Destination $file -Force' in atomic
    assert '"$(Get-Content -LiteralPath $CurrentFile -TotalCount 1)".Trim()' in four
    unsafe = r"Set-Content -LiteralPath \$CurrentFile|\(Get-Content [^)]*\)\.Trim\(\)"
    assert not re.search(unsafe, code(INSTALL))
    # The command is a copy of the version's own launcher (no .cmd shim, whose
    # cmd.exe asks "Terminate batch job (Y/N)?"): copied beside it first, then
    # the one there renamed aside and the copy moved into place; and before
    # `current` names the new version.
    assert '$UmCodex = Join-Path $Bin "um-codex.exe"' in four
    assert 'Install-Launcher (Join-Path $Target "Scripts\\um-codex.exe") $UmCodex' in four
    assert four.index("Install-Launcher (Join-Path $Target") < four.index(
        "Write-Atomically $CurrentFile $Version"
    )
    launcher = function(INSTALL, "Install-Launcher")
    assert '$fresh = Join-Path $folder ".$name.new"' in launcher
    assert launcher.index("Copy-Item -LiteralPath $source -Destination $fresh") < launcher.index(
        "Rename-Item"
    )
    assert launcher.index("Rename-Item") < launcher.index(
        "Move-Item -LiteralPath $fresh -Destination $destination"
    )
    assert "um-codex.cmd" not in code(INSTALL).replace('(Join-Path $Bin "um-codex.cmd") -Force', "")
    assert "Add-UserPath $Bin" in four
    add = function(INSTALL, "Add-UserPath")
    assert "-PropertyType $path.Kind" in add and "Send-EnvironmentChanged" in add
    # Stored entries as written (%USERPROFILE%...), not expanded.
    assert "DoNotExpandEnvironmentNames" in function(INSTALL, "Get-UserPath")
    assert "GetEnvironmentVariable(" not in code(INSTALL)


def test_a_running_umcodex_is_waited_for_never_stopped():
    four = step(4)
    assert "Get-RunningUmCodex $Root" in four
    assert 'if ($Yes) { Stop-Install "UM-Codex is running' in four


# --- The key ---------------------------------------------------------------------


def test_the_key_goes_from_the_masked_prompt_to_um_codex_key_on_stdin():
    six = step(6)
    assert 'Read-MaskedKey "Toolkit API key"' in six
    assert "$code = Send-Key $UmCodex $Key" in six
    # Written to its standard input as UTF-8 without a BOM, then closed.
    send = function(INSTALL, "Send-Key")
    assert '"key --from-stdin"' in send and "RedirectStandardInput = $true" in send
    assert "UTF8Encoding($false)" in send and "StandardInput.BaseStream.Write" in send
    assert "StandardInput.Close()" in send
    # um-codex key: 0 saved, 1 invalid (ask again), 2 cancelled.
    assert "if ($code -eq 0) {" in six and "if ($code -eq 2) {" in six and "$attempt -le 3" in six
    assert "$Key = $null" in six
    # Kept if one is saved already, unless -ReplaceKey; never asked under -Yes.
    assert "credentials.has_api_key()" in six
    assert "if ($HasKey -and -not $ReplaceKey) {" in six and "elseif ($Yes) {" in six
    # Never on a command line, in the environment or in a file.
    for line in code(INSTALL).splitlines():
        if re.search(r"\$Key\b", line):
            assert "Env:" not in line and "Set-Content" not in line and "Write-" not in line, line
            allowed = r"Read-MaskedKey|\$Key = \$null|if \(-not \$Key\)|Send-Key \$UmCodex \$Key"
            assert re.search(allowed, line), line


def test_the_masked_prompt_shows_stars_and_handles_ctrl_c_and_pastes():
    prompt = function(INSTALL, "Read-MaskedKey")
    assert "try { $key = [Console]::ReadKey($true) }" in prompt
    assert "return (Read-HiddenKey $prompt)" in prompt  # no console after all
    assert "[Console]::TreatControlCAsInput = $true" in prompt
    assert "[Console]::TreatControlCAsInput = $before" in prompt.split("} finally {")[-1]
    assert "if ($char -eq 3) { $cancelled = $true; break }" in prompt
    assert '"*" * [Math]::Min($typed.Length, 40)' in prompt
    assert "That was more than one line." in prompt
    assert "Got $($trimmed.Length) characters." in prompt
    assert 'Read-Host "   $prompt" -AsSecureString' in function(INSTALL, "Read-HiddenKey")


def test_the_installer_needs_a_console_host():
    person = person_part(INSTALL)
    check = person.index('if ($Host.Name -ne "ConsoleHost") {')
    assert check < person.index("$SetupLock = ")
    assert "Open Windows" in person[check : check + 400] and "Stop-Run 1" in person[check : check + 400]


# --- Launchers -------------------------------------------------------------------


def test_the_start_menu_and_desktop_shortcuts_open_a_terminal_running_um_codex():
    seven = step(7)
    assert '$Links = @(Join-Path $StartMenu "$LinkName.lnk")' in seven
    assert '$LinkName = "UM-Codex"' in seven
    assert '[Environment]::GetFolderPath("Desktop")' in seven
    assert "$Links += $DesktopLink" in seven
    # Windows Terminal if it's there, else Windows PowerShell; ";" escaped for wt.
    assert 'Join-Path $Env:LOCALAPPDATA "Microsoft\\WindowsApps\\wt.exe"' in seven
    assert '.Replace(";", "\\;")' in seven
    assert "$LinkTarget = $WindowsPowerShell" in seven
    # The version `current` names, run directly (no cmd.exe "Terminate batch job?").
    assert "EscapeSingleQuotedStringContent($Root)" in seven
    assert "$Marker = \"'$QuotedRoot\\current'\"" in seven
    assert "\\Scripts\\um-codex.exe')" in seven and "um-codex.cmd" not in code(seven)
    assert '$PowerShellArguments = "-NoProfile -NoExit -Command `"$Launch`""' in seven
    # From the app, um-codex asks for the working folder (home is refused).
    assert "\\Scripts\\um-codex.exe') launch --from-app\"" in seven
    launch = re.search(r"(?s)\$Launch = (.*?)\n\$PowerShellArguments", seven).group(1)
    assert '`"' not in launch  # no double quotes inside -Command "..."
    assert "([string](Get-Content -LiteralPath $Marker -TotalCount 1)).Trim()" in launch
    assert '-d `"$UserHome`" -- `"$WindowsPowerShell`"' in seven  # "--" ends wt's options
    # Someone else's Desktop shortcut of that name is left alone, and it says so.
    assert ".IndexOf($Marker, [StringComparison]::OrdinalIgnoreCase) -lt 0" in seven
    assert "that isn't UM-Codex's; it was left alone." in seven
    # The icon comes from the package, kept beside bin\ (an update removes version folders).
    assert '$Icons = Join-Path $Root "icons"' in seven
    assert 'Join-Path $Target "Lib\\site-packages\\umcodex\\branding\\UM-Codex.ico"' in seven
    assert '$Shortcut.IconLocation = "$Icon,0"' in seven


def test_the_icon_the_launchers_name_comes_with_the_package():
    icon = REPO / "src" / "umcodex" / "branding" / "UM-Codex.ico"
    assert icon.stat().st_size > 1000
    assert icon.read_bytes()[:4] == b"\x00\x00\x01\x00"


def test_failed_steps_stop_the_installer_instead_of_saying_all_done():
    five = step(5)
    assert five.index("& $UmCodex pull") < five.index("if ($LASTEXITCODE -ne 0) {")
    assert "Stop-Install" in five


def test_nothing_is_asked_after_done_so_ctrl_c_just_ends():
    end = "} finally {\n    if (-not $State.Finished"
    done = INSTALL[INSTALL.index("$State.Finished = $true\nWrite-Host") : INSTALL.index(end)]
    assert "Read-Host" not in done and "Ask " not in done and "ReadKey" not in done
    tail = INSTALL[INSTALL.index(end) : INSTALL.index("\n}\n", INSTALL.index(end))]
    assert "if (-not $State.Finished -and -not $State.StoppedSaying)" in tail
    assert "$SetupLock.Dispose()" in tail


# --- Uninstall -------------------------------------------------------------------


def test_the_uninstaller_runs_um_codex_uninstall_first_and_stops_if_it_refuses():
    body = code(UNINSTALL)
    run = body.index("& $Program uninstall @choice")
    # Nothing of UM-Codex's own files goes before it has succeeded (uv and the
    # installer's folders included).
    assert run < body.index('foreach ($name in "installer", "install", "uv")')
    assert run < body.index('foreach ($name in "versions", "bin", "icons", "downloads")')
    assert "if ($code -ne 0) {" in body[run : run + 400]
    assert '$choice += "--delete-data"' in body and '$choice += "--keep-data"' in body
    assert '$choice += "--yes"' in body
    both = body.index("if ($DeleteData -and $KeepData) {")
    assert "Stop-Run 2" in body[both : both + 200] and both < body.index("Unregister-ScheduledTask")


@pytest.mark.parametrize("name", SCRIPTS)
def test_iex_runs_ignore_the_persons_session_settings_and_leave_no_variables(name):
    text = SCRIPTS[name]
    block = text[text.index("= {\nparam(") :]
    top = block[: block.index("function Stop-Run")]
    assert "Set-StrictMode -Off" in top and "$PSDefaultParameterValues = @{}" in top
    params = re.findall(r"\[(?:string|switch)\]\$(\w+)", text[: text.index("= {\nparam(")])
    runner = text[text.rindex("} finally {") :]
    assert "Remove-Variable -Scope Local" in runner
    for param in params:
        assert re.search(rf"\b{param}\b", runner), param


def test_the_uninstaller_removes_only_what_the_installer_put_in_the_app_folder():
    body = code(UNINSTALL)
    # downloads: the updater's (DataLab 615cd0f).
    assert 'foreach ($name in "versions", "bin", "icons", "downloads")' in body
    assert "if ($inRoot.Count -eq 0) { Remove-Tree $Root }" in body
    installer = 'foreach ($name in "installer", "install", "uv") { Remove-Tree (Join-Path $StateDir $name) }'
    assert installer in body


def test_the_uninstaller_removes_shortcuts_and_the_path_entry_and_reports_leftovers():
    body = code(UNINSTALL)
    assert '$Link = Join-Path $StartMenu "UM-Codex.lnk"' in body
    assert "$Marker = \"'$QuotedRoot\\current'\"" in body  # the Desktop one only if it's ours
    assert "it isn't UM-Codex's." in body
    assert "-not (Test-SamePath $_ $Bin)" in body and "Send-EnvironmentChanged" in body
    assert "couldn't be removed: a file still in use?" in body
    assert "not UM-Codex's, so it was left" in body
    assert "Not removed, as um-codex couldn't run:" in body


def test_the_uninstaller_says_what_stays_and_how_to_remove_it():
    end = UNINSTALL[UNINSTALL.index('Write-Host "UM-Codex has been removed."') :]
    for thing in ("Docker Desktop", "Subsystem for Linux", "uv", "docker-users", "Your own folders"):
        assert thing in end, thing


def test_removing_never_follows_links_and_retries_read_only_files():
    tree = function(INSTALL, "Remove-Tree")
    assert "(Test-Link $top)" in tree and "-not (Test-Link $child)" in tree
    link = function(INSTALL, "Test-Link")
    # Name surrogates (symlinks, junctions, WSL's Linux symlinks) are links;
    # an unreadable tag counts as one; OneDrive placeholders aren't.
    assert "0x20000000" in link and "if ($null -eq $tag) { return $true }" in link
    assert "FindFirstFileW" in function(INSTALL, "Get-ReparseTag")
    assert "BitConverter]::ToUInt32($data, 36)" in function(INSTALL, "Get-ReparseTag")
    entry = function(INSTALL, "Remove-Entry")
    assert "UnauthorizedAccessException" in entry and "ReadOnly" in entry
    assert "(Test-Link $item)" in entry  # a link's attributes are never changed
