# Installing UM-Codex

How the installers and uninstallers work, and why. For the person installing,
the README has the commands; docs/DESIGN.md has the overall plan.

## Windows

`installer/windows/install.ps1` and `uninstall.ps1`, adapted from IHS
DataLab's at `6b6fdca`. They run from a file or straight from the web:

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; irm <release>/install-windows.ps1 | iex
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; & ([scriptblock]::Create((irm <release>/install-windows.ps1))) -ReplaceKey   # with options
powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 [-Package <whl or https URL>] [-Requirements <file or URL>] [-ReplaceKey] [-AdminAccessUrl <https page>] [-Yes]
```

The first part turns on TLS 1.2 (3072) for that window: Windows PowerShell
5.1 may not offer it by itself, and GitHub refuses older versions, so a bare
`irm` can fail before the installer has even started (which turns it on for
its own downloads).

Steps: (1) WSL and Docker Desktop, behind one administrator step, then a
restart that resumes by itself; (2) start Docker Desktop, fixing the VM logon
right if a policy took it; (3) the pinned uv; (4) UM-Codex in
`%LOCALAPPDATA%\UM-Codex\app\versions\<version>`, with `current`/`previous`,
`bin\um-codex.exe` and `bin` on the user PATH; (5) `um-codex pull`; (6) the
Toolkit key, read masked and piped to `um-codex key --from-stdin` (0 saved,
1 invalid: asked again up to 3 times, 2 cancelled), kept if one is saved
unless `-ReplaceKey`, skipped under `-Yes`; (7) "UM-Codex" in the Start menu
and on the Desktop with `UM-Codex.ico`, opening Windows Terminal if it's
installed, else Windows PowerShell, running `um-codex launch --from-app`
(which asks for the working folder: the terminal starts in the home folder,
which Codex may not have). Then "All done!" with
a summary.

`uninstall.ps1 [-DeleteData | -KeepData] [-Yes]` (both data options at once:
refused, exit 2) runs `um-codex uninstall` (containers, networks, images, the
key, and the data if asked). Only once that has succeeded does it remove uv,
the installer's folders and the program files (`versions`, `bin`, `icons`, `downloads`, `current`,
`previous`), the shortcuts, the PATH entry and the installer's leftovers, and
lists anything it couldn't remove.

Left out from DataLab (DataLab only): lab settings files, profiles and
practice, the Oracle/practice database, GitHub sign-in and the lab repos (and
so Git), the knowledge base, the port 8765/8766 check, and the clean-up of
DataLab 0.1's `uv tool` copy.

### Findings carried over from DataLab

Each line: what the scripts do, then the DataLab commit or PR it came from.

Running it
- ASCII only, LF in git (`.gitattributes`): Windows PowerShell 5.1 reads a file without a BOM as the ANSI code page. (e8b1e45, DataLab `.gitattributes`)
- Windows PowerShell 5.1 syntax only (no `&&`, `||`, `??`, `?.`, ternary; `-UseBasicParsing`); CI parses both scripts with 5.1. (7d8ec23)
- File runs use `-NoProfile -ExecutionPolicy Bypass -File`, which works under the default policy. (b32dec6, c97c179)
- Stops at once in Constrained Language Mode (AppLocker, WDAC). (c97c179)
- Stops at once in 32-bit PowerShell on 64-bit Windows. (21da163)
- Per-user install: everything after step 1 runs as the person, without administrator rights. (386fc99)
- Don't test from an MSIX-packaged app (AppData writes are redirected); use a normal PowerShell window or Task Scheduler. (1f40c2f)

The administrator part (`-Prepare`) and the person's part
- Virtualization off in firmware is found before any administrator step, download or restart; a running hypervisor counts as on; unknown carries on. (43a40b9)
- One administrator step, up front and only if something's missing: WSL features, WSL and Docker Desktop, `docker-users`, the service, the VM right. (386fc99)
- The elevated window runs only a copy of the installer's text checked by SHA-256 against the running text, from memory, started with `-EncodedCommand` and Base64 values (no quoting). (1c6e382, c97c179)
- Elevated: `PSModulePath` pinned to Windows' folders, autoloading off, modules loaded from `$PSHOME`; `powershell.exe`, `msiexec.exe`, `wsl.exe`, `tasklist.exe`, `taskkill.exe` by full path from System32. (c97c179)
- Its work folder is a new `ProgramData\UM-Codex-setup-<32 hex>` only SYSTEM and Administrators can use, made with that ACL in one step and checked; ProgramData itself is checked (owner, no loose rules); TEMP points inside it. (1c6e382, c97c179, 21da163)
- That folder is removed only if recorded in `%LOCALAPPDATA%\UM-Codex\installer-admin-folder.txt` and its owner and ACL are exactly what the elevated part set; the shared block is byte-identical in both scripts. (21da163)
- WSL and Docker Desktop downloads pinned by SHA-256 and Authenticode signature with the exact organisation (`Microsoft Corporation`, `Docker Inc`); a certificate name must be one `KEY=value` per line with one `O=`, quoted values unquoted. (386fc99, c97c179, 0ed6270, 3430203)
- TLS 1.2 is turned on before downloading (5.1 may not offer it). (c97c179)
- Each checked download is logged as "Checked: SHA-256 and signature (<O=>)". (1f40c2f)
- Docker Desktop installed with `--always-run-service`; an existing one's `com.docker.service` is set to Automatic; a Disabled one is left to IT. (1c6e382)
- `docker-users` by SID, not name (no domain controller off the VPN); the group and members are checked quietly first. (386fc99, 1f40c2f)
- The administrator window turns QuickEdit off for itself (console API defined in memory, `PreserveSig`), so a click doesn't pause it. (1f40c2f, 0ed6270)
- No `Add-Type` anywhere: it compiles through files in TEMP. (7e7a41d, 0ed6270)
- The restart resumes from a per-SID logon task (Startup shortcut as fallback), not RunOnce, which managed machines skipped. (386fc99, 1c6e382)
- A restart counter: after a restart that didn't help, it stops and names the likely cause (a group policy) instead of restarting again; it never re-runs the administrator part under `-Yes`. (1c6e382, c97c179)
- One installer at a time (named mutex); every run removes the after-restart task first. (1c6e382)
- For IT (docs): endpoint protection may block an elevated `powershell -EncodedCommand`; `--always-run-service` leaves a SYSTEM service; `docker-users` is a privileged group. (1c6e382, 21da163)

Michigan Medicine elevation
- Temporary administrator access (JIT, the profile page) has to be turned on first: the installer says so before the box, asks for at least 30 minutes, and names the reason to give CyberArk EPM ("Installing UM-Codex"); `-AdminAccessUrl` prints the page (DataLab's `[windows] admin_access_url`). (386fc99, 9374f68)
- A cancelled UAC or CyberArk EPM box is "declined": `Start-Process -Verb RunAs` only raises a non-terminating error, so it runs with `-ErrorAction Stop` and no process counts as declined, never as done or "restart Windows"; the VM fix then offers to try again. (19bb64d, 9374f68)

Docker and the VM logon right
- `docker info` through `Invoke-Quiet` (5.1 turns a native program's error output into a terminating error), with a time limit. (386fc99)
- The Docker check gives up after 10 seconds: a stuck engine otherwise waits the whole time. (19bb64d)
- Waiting for Docker uses a real clock (10 minutes) and says how long it's been. (386fc99)
- Before starting Docker Desktop, stale socket folders are moved aside and a leftover `docker-desktop` VM is terminated. (386fc99)
- The VM logon right (`SeServiceLogonRight` for `S-1-5-83-0`, which the CoreOne-Security policy removes): detected by starting WSL's own system distribution (`wsl --system -e true`) and looking for `0x80070569`, never Docker's distribution. (7e7a41d)
- The fix is fixed text (`LsaAddAccountRights`, methods defined in memory) behind one administrator prompt, the same as `windows_vm.GRANT_SCRIPT` (a test checks); the administrator part runs it too. (7e7a41d)
- `Repair-VmLogon` says that Docker Desktop will close and reopen before asking. (e70ca01)
- After the fix, Docker Desktop is restarted afresh, not with `docker desktop restart` (which left the stuck backend): only its four images (`Docker Desktop.exe`, `com.docker.backend.exe`, `com.docker.build.exe`, `docker-sandbox.exe`), only this account's (tasklist's USERNAME filter, the account from the process token), never `com.docker.service`. (f0a5e90, e70ca01)
- `taskkill /F` by PID with the same IMAGENAME and USERNAME filters, so a reused PID isn't ended; it looks again once a second for 15 s. (e70ca01)
- `wsl --terminate docker-desktop`, never `wsl --shutdown`; a distribution that isn't there counts as stopped. (f0a5e90)
- `Invoke-Captured` runs each program with a time limit; `Get-OwnPids` returns an empty list (not `$null`) when nothing runs and `$null` when tasklist fails. (e70ca01, 960ed15)
- After the fix (`$State.VmLogonRepaired`, DataLab's `$script:VmLogonRepaired`), Docker not ready in 10 minutes says "Restart Windows"; so do a Docker Desktop that won't close and a VM that won't stop. (e70ca01)
- CI runs `Get-OwnPids`, `Stop-DockerDesktopProcesses` and `Stop-DockerVm` as they are over tasklist/taskkill/wsl output captured on the laptop, and `Invoke-Captured` for real on cmd.exe. (960ed15)

uv and the package
- uv is the pinned release zip (SHA-256) with `uv.exe` signed by "OpenAI OpCo, LLC", in UM-Codex's own folder, used by full path, reused only if it's still the same file; no script piped from the web for uv. To move uv: change `$UvVersion`, `$UvZipUrl` and `$UvZipSha256` together (from the release's `.sha256` file) and check the signer; CI checks all three. (0ed6270, 3430203)
- `UV_*`, `PIP_*`, `PYTHONPATH`, `PYTHONHOME`, `VIRTUAL_ENV` don't come from the environment. (1f40c2f)
- Only what `requirements.txt` pins: `--require-hashes --only-binary :all: --default-index https://pypi.org/simple --no-config`, and the package checked against its own line first. (1f40c2f)
- `--link-mode copy`: hardlinks into uv's cache fail in cloud-synced or redirected folders (os error 396). (b0bf0b0)
- uv gets the package and `requirements.txt` under plain names from a staging folder: it cuts paths at the first space ("OneDrive - Michigan Medicine"). (386fc99)
- A bare package file name is resolved first, so `requirements.txt` beside it is found. (7d8ec23)
- Without `-Package`, the one package beside the installer is used (none or two: refused, saying why). (1f40c2f)
- The version in the package name must end in a letter or digit. (0ed6270)
- Each version in its own folder, `current` and `previous`, a `.complete` marker with the wheel's SHA-256; launchers always go through `current`, never a version named in the launcher itself, so an update or rollback takes effect. (40a455f, 1f40c2f)
- `PYTHONUTF8=1` for UM-Codex's Python (cp1252 errors on Windows): set by the shortcut and the installer's and uninstaller's own calls; DataLab set it in its `.cmd` shim, which UM-Codex doesn't have (see below), so the typed `um-codex` relies on UM-Codex opening its files as UTF-8 and on Python's UTF-16 console (PEP 528). (0ed6270)
- A running UM-Codex is waited for, never stopped; `-Yes` stops instead. (1f40c2f)

The key, the launchers, the end
- The key prompt shows one `*` per character (at most 40, then `...`), with Backspace, Ctrl-U and Enter; Ctrl-C cancels; it says how many characters arrived, trims the ends, and refuses a paste of more than one line. (b603c25)
- A failed key or image step stops the installer instead of reaching "All done!". (7e7a41d, b32dec6)
- Start menu entry and Desktop shortcut, both with the `.ico` copied to `<app>\icons` (an update removes version folders); a Desktop shortcut of that name that isn't UM-Codex's is left alone, and it says so. (627383c, 86efba7)
- The program folder in the launcher is escaped with `EscapeSingleQuotedStringContent` (`C:\Users\o'brien`). (0ed6270)
- Nothing is asked after "All done!", and a Ctrl-C after it just ends; only an unfinished run says "Stopped before the end". (ba4bcf1; DISTRIBUTION.md "Windows asks nothing after All done")

Uninstalling
- After-restart task and Startup shortcut, progress files, TEMP copies and the recorded administrator folder go first. (1c6e382, 21da163)
- Only what the installer and the updater put in the app folder, including the updater's `downloads`; the folder itself only if empty. (0ed6270, 615cd0f)
- Read-only files (git makes its object files read-only) are made writable and tried once more. (#36: bbbb386)
- Folders are removed without following links: a link (a reparse point whose tag is a name surrogate: symlinks, junctions, WSL's Linux symlinks `0xA000001D`, or an unreadable tag) is removed as itself; other reparse points (OneDrive placeholders) are ordinary. (c97c179, 21da163; #36: 865b3e4, 87bf5f9)
- Leftovers are reported as they are: what couldn't be removed, what wasn't UM-Codex's, kept data. (#36: 01b8e0f)
- It says what stays installed (Docker Desktop, WSL and its features, uv's downloads, `docker-users`) and how to remove each. (1f40c2f)

### New here (not in DataLab)

- `irm | iex` and `& ([scriptblock]::Create((irm ...))) -Options`: the installer is one script block (`$UmCodexInstaller`), so the administrator part and the after-restart copy use its exact text however it was started; a stop ends only the installer (`Stop-Run` throws to the runner instead of `exit`, which would close the person's window); the environment and window title it changes are put back. CI checks both.
- The after-restart run uses a saved copy of the installer (`%LOCALAPPDATA%\UM-Codex\installer\install.ps1`).
- The `um-codex` command: `bin` is added to the user PATH as stored (REG_EXPAND_SZ entries kept unexpanded), announced with WM_SETTINGCHANGE, and removed on uninstall.
- No `.cmd` shim: cmd.exe asks "Terminate batch job (Y/N)?" after every Ctrl-C. The typed `um-codex` is `bin\um-codex.exe`, a copy of the current version's own uv launcher (which names that version's `python.exe` by full path), recopied on every switch; a running copy is renamed aside rather than overwritten, and old copies removed later. The shortcut runs the version `current` names directly. A `.cmd` beside the `.exe` would never run (PATHEXT prefers `.exe`), so an earlier one is removed.
- In Windows Terminal, `;` is escaped as `\;` and `--` ends wt's own options.
- `current` and `previous` are written to `<file>.tmp` and moved into place (`Move-Item -Force`), and read as `"$(Get-Content -TotalCount 1)".Trim()`, so an empty or half-written file never breaks a launch.
- The key is never on a command line, in the environment or in a file: the installer writes it to `um-codex key --from-stdin`'s standard input itself (`Process.StandardInput`, UTF-8 without a BOM), not through PowerShell's pipe (`$OutputEncoding`).
- A host other than the console (PowerShell ISE, an editor's) stops at once and says to open Windows PowerShell or Windows Terminal; if a key can't be read a key at a time, the prompt falls back to `Read-Host -AsSecureString`.
- `Set-StrictMode -Off` and an empty `$PSDefaultParameterValues` inside each script block, so an `iex` run isn't changed by the person's profile; afterwards the runner removes the variables an `iex` run left in the person's session (the param block's too).
- Shared state in a hashtable (`$State`), because `$script:` inside the script block means the file's scope, or the person's session.

### Not verified without Windows

The scripts were written on a Mac with no PowerShell. CI's `windows-installer`
job parses both under Windows PowerShell 5.1 and runs the parts that can run
there. Still unverified until a Windows acceptance run: the full install and
restart, the elevated part, the VM fix and Docker restart against a real
Docker Desktop, the masked prompt in conhost and Windows Terminal, the
Windows Terminal shortcut, the PATH change reaching new terminals, and the
uninstaller with UM-Codex installed.
