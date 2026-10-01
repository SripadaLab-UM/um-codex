# Installing UM-Codex

How the installers work, and why. Most of it comes from IHS DataLab's
installers at `6b6fdca`; each finding below names the DataLab commit it came
from, so a later change can keep it (or drop it on purpose).

## Mac

`installer/macos/install.sh` (shipped as `install-macos.sh`), from a release's
files:

```sh
sh install-macos.sh --package umcodex-<version>-py3-none-any.whl
```

or straight from the web (the release's URLs):

```sh
curl -fsSL <url>/install-macos.sh | sh -s -- --package <url>/umcodex-<version>-py3-none-any.whl --requirements <url>/requirements.txt
```

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

   and a link `~/.local/bin/um-codex` to `bin/um-codex`. The end of the
   install says how to run it: `um-codex` if `~/.local/bin` was on PATH,
   otherwise the full path.
4. **Images:** `um-codex pull`. If it fails, the install stops and says to
   run it again.
5. **Toolkit key:** if the Keychain has a key already (`security
   find-generic-password -s UM-Codex -a toolkit-api-key`, which doesn't read
   the key) it's kept, unless `--replace-key`. Otherwise, at a terminal, a
   masked prompt (below) asks for it and pipes it to `um-codex key
   --from-stdin`: exit 0 saved, 1 refused by the Toolkit (asked again, three
   tries), 2 cancelled. Skipping, cancelling or no terminal never stops the
   install: `um-codex` asks for the key at its first launch.
6. **Launcher:** `UM-Codex.app` (bundle id `edu.umich.umcodex`, icon from
   the package's `umcodex/branding/UM-Codex.icns`), which opens Terminal
   running `bin/um-codex`; and a Desktop shortcut `~/Desktop/UM-Codex`.
   Then "Done", where everything went, and the offer to show and open it.

`installer/macos/uninstall.sh` runs `um-codex uninstall` (which asks about
the data and the images; its options are passed on), and only if that
succeeds removes the program files, then the `~/.local/bin/um-codex` link
(only if it points at this install), the app (only one with UM-Codex's
bundle id), the Desktop shortcut (only a link to exactly one of the two app
paths), and `~/Library/Caches/UM-Codex` (a kept Docker download). It leaves
Docker Desktop and uv alone.

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
- The package name carries the version, which must start with a digit and end with a letter or digit. (`1eb5673`, `0ed6270`)
- `requirements.txt` pins every dependency by hash and names the package by its SHA-256; a package it doesn't name is refused. Found beside a local package, else `--requirements`. (`1eb5673`)
- Downloads are https only (`--proto =https --proto-redir =https`). (`6ef0309`)
- uv gets both files under plain names from a staging folder: it cuts a path at its first space ("Application Support"). (`40a455f`)
- `uv venv --no-config --python 3.13`, then `uv pip install --no-config --require-hashes --only-binary :all: --default-index https://pypi.org/simple --link-mode copy`: only hashed wheels from PyPI, copied rather than hardlinked (hardlinks fail in cloud-synced or redirected folders). (`1eb5673`, `b0bf0b0`)
- Per-version folders: a version is installed beside the one in use, checked (`--version` must say it), `sync`ed, then marked `.complete` with the package's checksum; the same version with another package is reinstalled. `current` and `previous` are switched by rename. (`40a455f`, `1eb5673`)
- The shim `bin/um-codex` runs `current`, falls back to `previous` and says so, and sets `PYTHONUTF8=1`. (`1eb5673`, `0ed6270`)

**The key**

- The masked prompt is DataLab's `secret_prompt.py`: one * per character, typed or pasted (at most 64, then "…"), Backspace, Ctrl-U, Enter, Ctrl-C cancels; it says how many characters arrived (never any of them), removes spaces and line breaks at the ends and says so, and refuses a paste of more than one line (asks again). In UM-Codex it runs in the installed Python, isolated (`-I`), reads and writes `/dev/tty` itself, and turns echo off before the prompt shows. (`b603c25`)

**The launcher**

- The app goes in `/Applications` if writable without sudo, else `~/Applications`. Only UM-Codex's own app (its bundle id) is replaced or removed: someone else's in `/Applications` is left and ours goes in `~/Applications`; someone else's in `~/Applications` stops the installer with what to do; ours that can't be replaced in `/Applications` falls back to `~/Applications`, in `~/Applications` it says to quit UM-Codex. (`627383c`, `86efba7`)
- An earlier installer's copy in the other Applications folder is removed. (`627383c`)
- The app runs `bin/um-codex`, never a version's folder, so it keeps working when `current` changes. (`627383c`)
- The program's path goes to AppleScript as an argument (`osascript - '<path>'`, single-quote escaped; `quoted form of` for Terminal), so a home folder like `/Users/o'brien` works. (`86efba7`)
- The icon is copied out of the package into the bundle, so removing an old version doesn't take it; `touch` the app so Finder notices. (`627383c`)
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
- The key step (DataLab's `datalab setup` asked for keys itself).
- The uninstaller removes `~/Library/Caches/UM-Codex` and an empty data
  folder.

### Left out (DataLab only)

Profiles (real/practice) and the second app and icon, the lab settings file,
the database password, the GitHub sign-in and repos sync, the practice
(Oracle) database, Git, and the removal of an older `uv tool install` copy.
Pruning old versions belongs to `um-codex update` (M3), as it did to
DataLab's updater; the installer keeps `current` and `previous` and doesn't
remove others.

Not a DataLab installer finding: the quarantine flag. DataLab sets it on
exported files (`exports.py`), not in its installer. The app here is written
by the script, so it carries no quarantine flag and Gatekeeper doesn't
question it; Docker's download is checked with `codesign` and `spctl`
instead.
