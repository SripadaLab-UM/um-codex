# Installing UM-Codex

How the installers and uninstallers work, and why. For the person installing,
the README has the commands; docs/DESIGN.md has the overall plan. Most of it
comes from IHS DataLab's installers at `6b6fdca`; each finding below names the
DataLab commit it came from, so a later change can keep it (or drop it on
purpose).

## Mac

`installer/macos/install.sh` (shipped as `install-macos.sh`), from a release's
files:

```sh
sh install-macos.sh --package umcodex-<version>-py3-none-any.whl
```

or straight from the web, with no arguments:

```sh
curl -q -fsSL https://github.com/SripadaLab-UM/um-codex/releases/latest/download/install-macos.sh | sh
```

A release's `install-macos.sh` has `RELEASE_BASE` (that release's download
address) and `RELEASE_WHEEL` (its package's name) filled in by
`scripts/build-release.sh`, so without `--package` it installs its own
release's package and `requirements.txt`. In the repository both are empty,
and `--package` is needed. (Options go after `sh -s --`.)

Options: `--requirements <file or URL>` (found automatically beside a local
package), `--install-docker` (answers yes to installing Docker Desktop),
`--replace-key` (asks for the key even if one is saved).

Steps:

1. **Docker Desktop:** found, started, or (asked first) downloaded, checked
   and installed. This is DataLab's step, unchanged but for names.
2. **uv:** installed if it's missing (pinned 0.12.19).
3. **UM-Codex:** the package, with its own Python, in
   `~/Library/Application Support/UM-Codex/app` (`UMCODEX_INSTALL_DIR` for
   tests):

   ```
   versions/<version>/   one Python environment per version; .complete when whole
   current               the version the launcher opens
   previous              the one it opened before
   bin/um-codex          the launcher's command: runs `current`
   ```

   `bin/um-codex` is written by the new version itself, `um-codex launchers
   --write-command` (`src/umcodex/launchers.py`, which `um-codex update` also
   uses to bring it up to date): a shell script with this folder written in,
   single-quoted, never worked out from `$0`. Then a link
   `~/.local/bin/um-codex` to `bin/um-codex`, and a check that the link
   works as people use it (`um-codex --version` through the link, run in
   another folder). The end of the install says how to run it: `um-codex` if
   `~/.local/bin` was on PATH and the link works, otherwise the full path.
4. **Images:** `um-codex pull`. If it fails, the install stops and says to
   run it again.
5. **Toolkit key:** if the Keychain has a key already (`security
   find-generic-password -s UM-Codex -a toolkit-api-key`, which doesn't read
   the key) it's kept, unless `--replace-key`. Otherwise, at a terminal, it
   runs `um-codex key < /dev/tty`: `um-codex`'s own masked prompt (below)
   reads the terminal, so the key never passes through the installer's
   shell (no variable, argument, environment or `set -x` trace; a test runs
   the step under `SHELLOPTS=xtrace:allexport`). Exit 0 saved, 1 refused or
   invalid (asked again, three tries), 2 cancelled. Skipping, cancelling or
   no terminal never stops the install: `um-codex` asks for the key at its
   first launch.
6. **Launcher:** `UM-Codex.app` (bundle id `edu.umich.umcodex`, icon from
   the package's `umcodex/branding/UM-Codex.icns`), whose script runs
   `bin/um-codex ui --detach`: UM-Codex's launcher window (DESIGN.md, M5)
   starts in the background and opens in the browser. No Terminal window
   opens until a setup is started there, and `LSUIElement` keeps the app
   out of the Dock. The installer chooses where it goes and makes the
   bundle folder; what's in it is written by the new version itself, `um-codex
   launchers --write <app>` (`src/umcodex/launchers.py`, the same code `um-codex
   update` uses to bring it up to date: see "Keeping the app and shortcuts up
   to date" below). And a Desktop shortcut `~/Desktop/UM-Codex`.
   Then, at a terminal (M7), the Codex app's one line: `um-codex
   ssh-include < /dev/tty` asks, only when the Codex app is installed
   (`codex_app.find_app`) and `~/.ssh/config` doesn't have the line yet,
   with the reason in three plain lines (the line, the backup, uninstall
   takes it out), then "Add that line now? [Y/n]": Return is yes, `n` adds
   nothing. The question is asked by `um-codex` itself (`codex_app.
   offer_include`), so the installer's shell never touches `~/.ssh/config`.
   An answer of no is remembered (`ssh-include-declined` in the data
   folder), so installing again doesn't ask again (`um-codex ssh-include
   --ask-again` asks). `um-codex ssh-include` itself refuses to ask without a
   terminal (exit 1, nothing added).
   **No terminal adds nothing:** consent must be the person's, so it says
   the line wasn't asked about, and the launcher window explains it on the
   setup's card ("Add the line and start") when a setup in the Codex app is
   first started. A failure never stops the install.
   Then "Done", where everything went, and the offer to show and open it.

`installer/macos/uninstall.sh` runs `um-codex uninstall` (which first asks
"Uninstall UM-Codex? [y/N]", then about the images and the data; its options
are passed on, `--yes` included), reading `/dev/tty` when it can be opened
(with no terminal a question reads end-of-input, which `um-codex` takes as
no). If that stops or fails, it says "Nothing else was removed." and exits
with its code. Only if it succeeds does it remove the program files, then the `~/.local/bin/um-codex` link
(only if it points at this install), the app (only one with UM-Codex's
bundle id), the Desktop shortcut (only a link to exactly one of the two app
paths), and `~/Library/Caches/UM-Codex` (a kept Docker download). It leaves
Docker Desktop and uv alone. When the program files aren't there, it says
what may be left (Docker's containers and images, the key, the saved
setups) and removes the app, shortcut and command link.

Tests: `tests/test_macos_installer.py` runs the real scripts against
stand-ins for `docker`, `uv`, `open`, `osascript`, `security`, `curl`,
`hdiutil`, `codesign`, `spctl`, `sw_vers`, `sysctl`, `uname`, `df`, `ps`,
`mdfind`, `ditto`, `id`, `sudo`, Docker's `install`, `date` and `sleep` (a
fake clock), with HOME a temporary folder and `UMCODEX_SYSTEM_APPLICATIONS`
in place of `/Applications`. PATH is only the fakes plus the system's
commands without any `docker`. Questions are answered through a real
terminal (pty). `UMCODEX_DOCKER_WAIT_SECONDS`, `UMCODEX_DOCKER_POLL_SECONDS`,
`UMCODEX_DOCKER_INFO_SECONDS`, `UMCODEX_DOCKER_RESTART_AFTER` and
`UMCODEX_TEST_WITHIN=sh` change the Docker waits;
`UMCODEX_INSTALL_STOP_AFTER_DOCKER=1` stops once Docker is ready.

### Findings carried over from DataLab (keep these)

Commits are in github.com/SripadaLab-UM/ihs-datalab.

**Running the script**

- Never runs as root: "Run this without sudo." (`1eb5673`)
- Every `UV_*` and `PIP_*` variable, and `PYTHONPATH`, `PYTHONHOME`, `PYTHONSTARTUP`, `VIRTUAL_ENV`, are unset first: the environment can't steer uv, pip or Python. (`1eb5673`)
- Questions are read from `/dev/tty`, so they work when the script arrives on a pipe. (`40a455f`)
- No terminal to answer means no: nothing is installed unasked. (`70852af`, kept in `3dc639d`)
- Ctrl-C, TERM or HUP during the install says "Stopped. Run this installer again…" and exits 130; the EXIT trap detaches Docker's disk image and removes a half-made copy and the staging folder. (`70852af`, `b45ca9c`)
- Every stop says what to do, and that running again carries on without doing anything twice. (`70852af`)
- No `$name` runs into a non-ASCII character (`${place}…`, not `$place…`): in a UTF-8 locale sh read the first byte of "…" as part of the name ("unbound variable"). A test checks both scripts, and a full install runs under `en_US.UTF-8`. (`2a2de83`)
- No `printf`/`echo` piped into `grep -q` (a "Broken pipe" write error); text is matched with `case`. (`e7fc74c`)

**Docker Desktop: finding it**

- Looked for in `/Applications` and `~/Applications`; its `docker` command on PATH, inside the app (`Contents/Resources/bin/docker`), or in `~/.docker/bin`. (`70852af`)
- The command found is used by full path, and its folder goes *last* on PATH, so it hides nothing (it also holds Docker's credential helpers). (`b45ca9c`)
- A `docker` on PATH that links to a Docker.app elsewhere (renamed, in a subfolder) is followed to that app; failing that, Spotlight (`mdfind` for `com.docker.docker`) is asked, so a second copy isn't installed. (`b45ca9c`)
- Only an app in an Applications folder counts: not Docker's own staging copy from a half-done install or uninstall (`~/Library/Application Support/com.docker.install/in_progress/`), the Trash, a disk image, `~/Library` or a cache. (`2a2de83`)
- After installing, the new app's own `docker` is used, not another Docker's (Colima, Homebrew) on PATH. (`b45ca9c`)
- A `docker` that isn't answering with no Docker Desktop installed: mentions Colima/OrbStack, then offers the install. (`70852af`)
- An incomplete leftover Docker.app (no program named by `CFBundleExecutable`) is reported: drag it to the Trash. (`b45ca9c`)
- An existing Docker Desktop is never reinstalled, upgraded, reset or reconfigured; no prune, `docker rm`, or `group.com.docker` (a test checks). (`70852af`)

**Docker Desktop: starting it and waiting**

- Readiness is `docker info` only. (`70852af`, `ff6d770`)
- Each `docker info` is given 20 s by a parent process (perl forks the command in its own process group, alarm in the parent, SIGTERM then SIGKILL 2 s later, exit 124; a background watcher without perl), because docker is a Go program and ignores SIGALRM: a hung `docker info` used to hang the installer for good. (`e7fc74c`)
- Waits are timed by the clock, not by counting sleeps; "Still waiting… (N seconds)" every 30 s; 5 minutes for an existing Docker, 15 for a first run. (`70852af`, `b45ca9c`)
- An existing Docker Desktop whose programs run but whose engine hasn't answered for 90 s gets one `docker desktop restart` (120 s limit); never on a first run, never without that command. (`e7fc74c`)
- A hung engine at the deadline gets its own message: Restart, then Troubleshoot; "Clean / Purge data" and "Reset to factory defaults" DELETE containers, images and volumes (for UM-Codex, the setups' Codex history). (`e7fc74c`)
- Docker quitting before it's ready (its programs gone for two checks after 30 s) is explained: usually its agreement was declined. Docker's programs are matched as plain text in `ps`. (`70852af`, `b45ca9c`)
- When Docker doesn't come up, the message also says to quit leftover Docker programs or restart the Mac. (`2a2de83`)

**Docker Desktop: installing it**

- The question is `Download and install Docker Desktop? [Y/n]`: Return is yes, n/no stops, no terminal is no, `--install-docker` answers yes beforehand. (`3dc639d`)
- Before asking: Apple silicon (`sysctl hw.optional.arm64`, right under Rosetta too) or Intel; macOS 14 or newer; about 6 GB free. (`70852af`)
- The prompt says Docker's license terms apply and an organisation may have its own guidance, without saying what anyone's license status is. (`70852af`)
- The download folder (`~/Library/Caches/UM-Codex/docker-desktop`) is made only after the person says yes. (`b45ca9c`)
- Download: https and TLS 1.2+ only, resumable (`-C -`), given up on under 10 kB/s for 2 minutes; curl exit 22 or 33 removes the part so the next try starts afresh. (`70852af`, `b45ca9c`)
- The disk image's own Docker Inc signature is checked before it's opened; it's attached read-only at a private mount point. (`b45ca9c`)
- The app must pass `codesign --verify --deep --strict` against "Apple anchor, leaf OU 9BNSXJN65R, identifier com.docker.docker", `codesign -dv` team and identifier, and `spctl` "Notarized Developer ID" from Docker Inc; a symlinked app is refused; Gatekeeper off gets its own message; the app's own `LSMinimumSystemVersion` is checked. Any failure deletes the download. (`70852af`, `b45ca9c`)
- On an administrator account: Docker's own installer from the checked image, `sudo <image>/Docker.app/Contents/MacOS/install --user <user>`, never `--accept-license`; it says first that macOS will ask for the password, sudo reads it from the terminal; the installed app is checked again; a cancelled password or failed installer stops with what to do, keeping the download. `sudo` appears nowhere else (a test checks). (`ff6d770`)
- Otherwise (not an administrator, or no install command in the image): `ditto` copy to `/Applications` if writable without sudo, else `~/Applications`, under the temporary name `.Docker.app.umcodex-partial` (removed however the installer ends, Ctrl-C included), checked again, then renamed; a Docker.app that appears meanwhile is left alone. (`70852af`, `b45ca9c`)
- A copy refused with "Operation not permitted" says to allow Terminal under Privacy & Security > App Management or use `~/Applications`; other failures say to use Self Service or ask IT. (`b45ca9c`)
- Docker's agreement is accepted by the person in Docker's own first-run window; the installer explains that window (Accept, recommended settings, password for the helper, Skip sign-in; "Use advanced settings" with tools set to "User" for `~/Applications`). (`70852af`, `ff6d770`)

**uv and the package**

- uv is pinned (`0.12.19`) and installed only if missing. (`0ed6270`; UM-Codex adds `--proto =https --tlsv1.2` to that download)
- Every `curl` starts with `-q`, so a `~/.curlrc` can't change it. (UM-Codex)
- The package name carries the version, which must start with a digit and end with a letter or digit. (`1eb5673`, `0ed6270`)
- `requirements.txt` pins every dependency by hash and names the package by its SHA-256; a package it doesn't name is refused. Found beside a local package, else `--requirements`. (`1eb5673`)
- Downloads are https only (`--proto =https --proto-redir =https`). (`6ef0309`)
- uv gets both files under plain names from a staging folder: it cuts a path at its first space ("Application Support"). (`40a455f`)
- `uv venv --no-config --python 3.13 --python-preference only-managed` (UM-Codex adds the last: always uv's own Python build, never Homebrew's or python.org's, which could change or go from under it), then `uv pip install --no-config --require-hashes --only-binary :all: --default-index https://pypi.org/simple --link-mode copy`: only hashed wheels from PyPI, copied rather than hardlinked (hardlinks fail in cloud-synced or redirected folders). (`1eb5673`, `b0bf0b0`)
- Per-version folders: a version is installed beside the one in use, checked (`--version` must say it), `sync`ed, then marked `.complete` with the package's checksum; the same version with another package is reinstalled. `current` and `previous` are switched by rename. (`40a455f`, `1eb5673`)
- The shim `bin/um-codex` runs `current`, falls back to `previous` and says so, and sets `PYTHONUTF8=1`. (`1eb5673`, `0ed6270`; its folder is now written in: see "The command link must work" below.)

**The key**

- The masked prompt is DataLab's `secret_prompt.py`, in `um-codex key`: one * per character, typed or pasted (at most 64, then "…"), Backspace, Ctrl-U, Enter, Ctrl-C cancels (ISIG off: exit 2, no traceback); it says how many characters arrived (never any of them), removes spaces and line breaks at the ends and says so, and refuses a paste of more than one line (asks again). UM-Codex turns echo off before writing the label, so a paste that arrives as the label shows is never echoed. (`b603c25`)

**The launcher**

- The app goes in `/Applications` if writable without sudo, else `~/Applications`. Only UM-Codex's own app (its bundle id) is replaced or removed: someone else's in `/Applications` is left and ours goes in `~/Applications`; someone else's in `~/Applications` stops the installer with what to do; ours that can't be replaced in `/Applications` falls back to `~/Applications`, in `~/Applications` it says to quit UM-Codex. (`627383c`, `86efba7`)
- An earlier installer's copy in the other Applications folder is removed. (`627383c`)
- The app runs `bin/um-codex`, never a version's folder, so it keeps working when `current` changes. (`627383c`)
- The program's path is single-quote escaped in the app's script, so a home folder like `/Users/o'brien` works. (`86efba7`; DataLab handed it to AppleScript as an argument, as UM-Codex did before M5.)
- The icon is copied out of the package into the bundle, so removing an old version doesn't take it; `touch` the app so Finder notices. (`627383c`; now done by `um-codex launchers --write`.)
- A Desktop shortcut: a link to the app, replacing only a link to exactly `~/Applications/UM-Codex.app` or `/Applications/UM-Codex.app`; anything else there is left alone. The uninstaller removes only such a link. (`627383c`, `86efba7`)
- "Done" says where the app, the shortcut, the command and the program files are, then, only with someone at a terminal, offers "Show in Finder" (`open -R`) and "Open now". (`627383c`)
- Ctrl-C at those two questions just ends ("OK.", exit 0): the install has finished by then. (`ba4bcf1`)

**Tests**

- Hermetic: PATH is the fakes plus a copy of the system's commands without any `docker`, so a real Docker is never found; the fakes need no macOS tools, so they run on Linux too; `/Applications` is a stand-in. (`ff6d770`, `627383c`)
- Questions are answered through a real terminal (pty), Ctrl-C typed as ETX. (`3dc639d`, `ba4bcf1`)

### What UM-Codex adds or changes

- The whole script is one `{ ... }` block, so sh reads all of it before
  running any: a cut-off download runs nothing, and with `curl … | sh` no
  command it runs can read the rest of the script as its input (a test
  checks with a `um-codex pull` that reads its input).
- The final offers need `/dev/tty` and a terminal on stdout, not a terminal
  on stdin, so they work under `curl … | sh`.
- The `~/.local/bin/um-codex` link, replaced only if it's a link to this
  install's command; the uninstaller removes only that link.
- **The command link must work.** alpha.1's and alpha.2's `bin/um-codex`
  worked out its folder from `$0` (`cd "$(dirname "$0")/.."`). Run through
  the link, `$0` is the link, so it looked in `~/.local` and said "UM-Codex
  (none) can't be opened": typing `um-codex` in Terminal never worked (the
  app ran the command by its full path, and so did the tests). Now
  `um-codex launchers --write-command` writes the folder in, single-quoted
  (`/Users/o'brien` works), and a link always stays a link to it. The
  installer runs `um-codex --version` through the link from `/` and, if that
  fails, says so and gives the full path instead. A test types `um-codex
  --version` through the link from another folder, with an apostrophe and a
  space in the home folder, after first showing alpha.2's command fails there.
  Installs from alpha.1 and alpha.2 get the command rewritten by the
  launchers' refresh (launcher format 3, below): by `um-codex update` (the
  new version's `launchers --refresh`), by the installer, or at the new
  version's first `um-codex ui` (opening the app, which runs the command by
  its full path). The typed `um-codex` can't do it: the old command fails
  before any Python runs. Windows has no such link: `bin` itself is on PATH,
  and `bin\um-codex.exe` is a copy of uv's launcher, which names the
  version's `python.exe` by its full path, not relative to itself.
- The key step runs `um-codex key < /dev/tty` (DataLab's `datalab setup`
  asked for keys itself), and `set +a` follows `set -eu`, so nothing the
  script sets is exported even if sh started with allexport.
- The app runs `um-codex ui --detach` (the launcher window, M5) with no
  Terminal window and no Dock icon (`LSUIElement`). A setup started there
  opens one Terminal window, through a `.command` file the launcher writes
  for that start (it removes itself), so no permission to control Terminal
  is needed. Before M5 the app ran `um-codex launch --from-app` in Terminal
  through AppleScript; that command still works.
- The uninstaller removes `~/Library/Caches/UM-Codex` and an empty data
  folder.

### Left out (DataLab only)

Profiles (real/practice) and the second app and icon, the lab settings file,
the database password, the GitHub sign-in and repos sync, the practice
(Oracle) database, Git, and the removal of an older `uv tool install` copy.
Pruning old versions belongs to `um-codex update`, as it did to DataLab's
updater (docs/RELEASING.md); the installer keeps `current` and `previous`
and doesn't remove others.

Not a DataLab installer finding: the quarantine flag. DataLab sets it on
exported files (`exports.py`), not in its installer. The app here is written
by the script, so it carries no quarantine flag and Gatekeeper doesn't
question it; Docker's download is checked with `codesign` and `spctl`
instead.

## Keeping the app and shortcuts up to date

What the launchers contain is said in one place, `src/umcodex/launchers.py`,
and both the installers and the updater use it, so they can't drift apart:

- The installers decide where the launchers go (as above) and then run the
  new version's `um-codex launchers --write <paths>`: on a Mac the app's
  `Info.plist`, its script and its icon, then `lsregister -f` so macOS reads
  it again (skipped if lsregister isn't there); on Windows the `.lnk` files
  (through WScript.Shell, in a Windows PowerShell it starts, with
  `PYTHONUTF8`) and the icon in `<app>\icons`. If the Mac app can't be
  written, the installer removes the half-made one it had just prepared, so
  the next run isn't blocked.
- `um-codex update` and `--rollback`, once `current` names the version
  switched to, run that version's `um-codex launchers --refresh`. It rewrites
  only this install's own launchers, only where they already are
  (`/Applications` or `~/Applications`; the Start menu, and the Desktop as
  Windows says where it is, OneDrive included), and only if they differ from
  what that version writes. Anything else of that name, or a launcher the
  person removed, is left alone.
  - Mac: the app's bundle id, *and* a script naming this install's command
    (`'<app folder>/bin/um-codex'`, single-quoted; alpha.1's names it too), so
    another account's UM-Codex in a shared `/Applications` is never taken for
    ours. The installer's `ours()` and the uninstaller check the same.
  - Windows: a shortcut whose command line names `'<app folder>\`,
    single-quoted.
  - Never through a link: the app, `Contents` and `Contents/MacOS` must be
    folders themselves, and each file is written under a name of its own
    (`mkstemp`, so `O_CREAT|O_EXCL`) and renamed into place (which replaces a
    link there rather than writing through it); the same for
    `<app>/launchers` and the Windows icon.
  - On a Mac the Desktop shortcut is a link to the app, so it never needs
    rewriting. An older copy that can't be changed while another copy is up
    to date is skipped, with a note that it can go to the Trash.
  - If one can't be rewritten, the update still stands, and it says to run
    the installer again (or `um-codex launchers --refresh` later, or
    `um-codex` in a terminal).
- Rolling back to a version from before this (0.1.0-alpha.1, which has no
  `launchers` command): the newer code doing the rollback writes alpha.1's
  launchers itself (format 1: the app runs `launch --from-app` in Terminal;
  the shortcut runs it in Windows Terminal or Windows PowerShell), so
  alpha.1 still opens. If even that fails, it says the app won't open it and
  gives the command to run in a terminal.
- `<app>/launchers` records the launcher format they were last written in
  (`launchers.FORMAT`; the Mac app's `Info.plist` has it too, as
  `UMCodexLauncherFormat`), whether that worked, and when. An update made by
  alpha.1's own updater doesn't refresh them, so the first `um-codex` or
  `um-codex ui` of a newer version whose format differs from the record (or
  finds none) refreshes them. That's how alpha.1's app becomes the launcher
  window's: opened once more, it runs the new version's `um-codex launch
  --from-app`, which rewrites it and carries on in Terminal; from then on it
  opens in the browser. If that refresh fails, it says so once; after that
  it tries again at most once a day, and says so only in the log.
- Both launchers run the command in `<app>/bin` (the Mac shim, the Windows
  `um-codex.exe` copy), never a version's folder, so an ordinary update
  changes nothing in them. A change to what they contain bumps `FORMAT`.
- On a Mac the refresh also rewrites that command, `<app>/bin/um-codex`
  (`mac_command_file`), in an install (`<app>/current` is there) where it
  differs: format 3 is format 2 plus a command with its folder written in
  (alpha.1's and alpha.2's didn't work through `~/.local/bin/um-codex`; see
  "The command link must work"). It's the same in every format, a rollback
  to alpha.1 included: any version runs from it.
- A shortcut pinned to the Windows taskbar is Windows' own copy (in
  `%APPDATA%\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar`),
  which UM-Codex doesn't touch: after an update that changes the launchers,
  an alpha.1 pin still opens a terminal. Unpin it and pin UM-Codex again from
  the Start menu. (The same for a Mac Dock item: it follows the app, so it
  needs nothing.)
- `um-codex launchers --refresh --dry-run` says what would change (for the
  Mac app, the lines of each file) and changes nothing.

Tests: `tests/test_launchers.py` (the Mac app in temporary folders, links
and another account's app included; the Windows shortcuts through a
stand-in for WScript.Shell, and, on CI's `windows-installer` job, real ones
in a temporary Start menu and Desktop, and a Desktop redirected as OneDrive
does it), `tests/test_update.py` (the update and rollback run it, carry on
when it fails, and a rollback to alpha.1 writes its launchers), and
`tests/test_macos_installer.py` (its fake `um-codex` runs the real
`launchers` command). The tests point `/Applications`, the Start menu, the
Desktop and the home folder at temporary folders
(`UMCODEX_SYSTEM_APPLICATIONS`, `UMCODEX_START_MENU`, `UMCODEX_DESKTOP`,
`HOME`), and turn lsregister off (`UMCODEX_LSREGISTER=`).

## Windows

`installer/windows/install.ps1` and `uninstall.ps1`, adapted from IHS
DataLab's at `6b6fdca`. They run from a file or straight from the web:

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; irm <release>/install-windows.ps1 | iex
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; & ([scriptblock]::Create((irm <release>/install-windows.ps1))) -ReplaceKey   # with options
powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 [-Package <whl or https URL>] [-Requirements <file or URL>] [-ReplaceKey] [-AdminAccessUrl <https page>] [-Yes]
```

A release's `install-windows.ps1` has `$ReleaseBase` and `$ReleaseWheel`
filled in by `scripts/build-release.sh`, so with no `-Package` it installs
its own release's package and `requirements.txt`: from beside it only if
that's exactly `$ReleaseWheel`, otherwise from the release. CI checks both. The first part turns on TLS 1.2
(3072) for that window: Windows PowerShell
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
and on the Desktop with `UM-Codex.ico`, written by `um-codex launchers --write
<.lnk files>` (`src/umcodex/launchers.py`, which `um-codex update` also uses;
the installer only decides which: the Start menu's, and the Desktop's unless
one of that name there isn't UM-Codex's), running Windows PowerShell with its
window hidden (and the shortcut minimized, so it at most flashes), which runs
`bin\um-codex.exe ui --detach`: the launcher window (DESIGN.md, M5) starts in the
background with a console that's never shown (the Docker commands it runs
share it) and opens in the browser. A setup started there opens Windows
Terminal if it's installed, else Windows PowerShell. Then, unless `-Yes`,
`um-codex ssh-include` (as on a Mac: it asks only where "Open in: Codex app"
works and the line is missing; on Windows the Codex app isn't offered yet,
so it says nothing). With `-Yes` it isn't run: the consent is the person's,
not the one running the installer for them. Then "All done!" with
a summary.

`uninstall.ps1 [-DeleteData | -KeepData] [-Yes]` (both data options at once:
refused, exit 2) runs `um-codex uninstall` (containers, networks, images, the
key, and the data if asked). Only once that has succeeded does it remove uv,
the installer's folders and the program files (`versions`, `bin`, `icons`, `downloads`, `current`,
`previous`, `launchers`), the shortcuts, the PATH entry and the installer's leftovers, and
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
- No `.cmd` shim: cmd.exe asks "Terminate batch job (Y/N)?" after every Ctrl-C. The typed `um-codex` is `bin\um-codex.exe`, a copy of the current version's own uv launcher (which names that version's `python.exe` by full path), recopied on every switch, before `current` is written: copied beside it as `.um-codex.exe.new`, then a running copy is renamed aside rather than overwritten and the new one moved into place; old copies are removed later. `um-codex update` does the same. The shortcut runs `bin\um-codex.exe` (before, it read `current` and ran that version's own `um-codex.exe`). A `.cmd` beside the `.exe` would never run (PATHEXT prefers `.exe`), so an earlier one is removed.
- In Windows Terminal, `--` ends wt's own options; the launcher window gives
  PowerShell its command as `-EncodedCommand`, so there's no `;` for wt to
  split at (before M5 the shortcut escaped it as `\;`, and the uninstaller
  still recognises such a shortcut).
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
shortcut's hidden PowerShell and the launcher window's terminal (Windows
Terminal or PowerShell) and folder picker, the PATH change reaching new terminals, the
uninstaller with UM-Codex installed, and `um-codex update` and `--rollback`
(the copy of the new launcher into `bin`, renaming the running one aside),
which are unit-tested only.
