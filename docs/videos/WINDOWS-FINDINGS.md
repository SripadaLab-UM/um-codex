# Where the app differed from NOTES.md (Windows)

From recording "Installing on Windows" and "Your first launch on Windows" on
2026-10-02, from the released v0.1.0-alpha.4 (the release's own installer,
re-run over an existing alpha.4 install), on Windows 11 with Docker Desktop
and WSL already installed. Read with [RECORDING-FINDINGS.md](RECORDING-FINDINGS.md)
(the Mac findings). Each item says what the screen showed.

## The installer

1. **Seven steps** (`Step 1 of 7: Getting Windows ready` to `Step 7 of 7: Adding
   UM-Codex to the Start menu and the Desktop`), then `All done!`. The Mac has
   six; Windows adds WSL/administrator preparation as its own step 1.
2. **A re-run over an existing install is quick and changes little** (16 s here):
   `WSL and Docker Desktop are ready.`, `Docker Desktop is running.`, `uv 0.12.19
   is installed already.`, `UM-Codex 0.1.0a4 is installed already.`, the images
   "up to date", `A Toolkit key is saved already, so it was kept.`, and the two
   shortcuts "Brought ... up to date". The administrator part, the restart and the
   key prompt were therefore not on screen; the video draws them as labelled
   illustrations in the installer's own wording (from `installer/windows/install.ps1`).
3. **The key prompt says "container"** ("never goes into the container") and
   "U-M GPT Toolkit" on screen; the narration says "sealed environment" and "the
   University of Michigan's GPT Toolkit".
4. **The installer asks no closing questions** (the Mac asks about Finder and
   opening). On Windows with no terminal to answer in, step 7 prints `There's no
   terminal to answer in, so ~/.ssh/config wasn't changed.` after the shortcuts.
   (This is only because the recording was not run at a console; at a console,
   on alpha.4, `um-codex ssh-include` says nothing on Windows.)
5. **`Desktop shortcut:` shows `...\OneDrive - Michigan Medicine\Desktop\UM-Codex.lnk`**
   on a Michigan Medicine computer (the Desktop is redirected into OneDrive).
   The terminal view shows it as is; only the user name is shown as "you".
6. **Step 1's "restart" path is easy to trigger by accident.** When the
   installer is started from a shell that puts another `whoami.exe` first on PATH
   (Git Bash), `whoami /groups` fails, `Test-CanUseDocker` says no, and the
   installer offers to restart Windows although nothing is missing. The recording
   script runs the installer with Windows' own PATH. (Worth a test in
   `tests/test_windows_installer.py`: `Test-CanUseDocker` could call
   `$SystemDir\whoami.exe` by full path, as the installer does for other programs.)

## The launcher window (alpha.4, Windows)

7. **No "Connected ✓" line.** With "Open in" on Terminal (the only choice on
   Windows at alpha.4) the card's line goes `Starting…` then `Running in Terminal
   since <time>. Quit Codex there, or Stop here.` NOTES.md's `Starting… → Opening
   Codex… → Connected ✓` is the Codex app's sequence (Mac only at alpha.4).
8. **The first-run text says "Codex starts in a Terminal window"** (not the Codex
   app). It matches NOTES.md otherwise.
9. **Windows' folder picker is the classic "Browse For Folder" box** with the
   description `Choose a folder for UM-Codex`, a tree (Desktop, the user's
   folders, This PC, drives) and OK, Cancel, Make New Folder. Its tree lists the
   user's own folders and the Desktop's items, so the video shows the dialog
   cropped to the demo folder's row only, with the rest blurred. It opens with the
   demo folder selected because the recording passes the start folder through the
   page (as on the Mac); in normal use it opens where Windows last had it.
10. **The picker is owned by an invisible WinForms window**, so it does not appear
    among a UI Automation tree's top-level windows by name; the recording script
    looks inside the owner window.

## Codex's Terminal window

11. **It opens in Windows Terminal** (a tab titled `UM-Codex`, then the folder's
    name once Codex starts) when Windows Terminal is installed.
12. **Before Codex starts the Terminal shows:** `UM-Codex 0.1.0a4`, then (once a
    newer release is out) `UM-Codex 0.1.0a5 is available: run um-codex update`,
    then `Setup: <name>` and `Starting the container...`.
13. **Codex's banner:** `OpenAI Codex (v0.157.1)`, `model: GPT-5.6-Terra`,
    `directory: /work`, `permissions: YOLO mode`. The demo folder is `/work`
    inside the sealed environment; "YOLO mode" is Codex's own name for running
    commands without asking, which is the setup's default.

## Not checked

- The administrator part, the restart and the Docker virtual-machine fix, run for
  real (drawn from the installer's text instead).
- Windows without Windows Terminal (the setup opens in Windows PowerShell).
- A later start reconnecting by itself (not applicable: Terminal).

## Recording notes

- The installer's output was recorded by running the release's `install-windows.ps1`
  from a script (`footage/record-windows-install.py`) with Windows' own PATH, with
  its output passed through a filter that shows the user's name as "you". It
  answers nothing: a question stops it, so it can never say yes to the
  administrator part or a restart.
- The launcher page was filmed headless on a demo data folder (`footage/film-first-launch.mjs`);
  the picker and the Terminal window are crops of a full-screen recording
  (`footage/record-windows-launch.ps1`, after every window was minimized). The
  full-screen recording holds the whole desktop and is not in the repository.
- The demo folder is `C:\Demo\UM-Codex demo`, whose parent holds nothing else.

## Clean-install test (2026-10-04, v0.1.0-alpha.6, Windows 11, Michigan Medicine computer)

Done after removing UM-Codex (its own uninstaller, `-KeepData`), then Docker Desktop and WSL
(`footage/remove-docker-wsl.ps1`, elevated), then running the published install command in a
window whose PATH had no git.

14. **The installer never calls git** (nothing in `install.ps1` or `uninstall.ps1` runs it), so a
    machine without git is not a risk for UM-Codex. The install ran start to finish: the
    administrator part (WSL and Docker Desktop installed), a restart, the automatic resume after
    sign-in, the key prompt, the shortcuts. `um-codex doctor` then said "Everything needed for a
    launch is there" (Docker, both images, the key saved, the Toolkit accepting it).
15. **The window shows nothing after the restart question** if the person looks at the log: with
    `irm | iex` the planned stop throws `UM-Codex installer stopped` (visible in a transcript as
    `TerminatingError`). On screen the installer has already said why (the restart message), so
    it is not a silent failure, but a transcript or a pasted log reads like an error.
16. **The resumed half ran after sign-in with the person's normal PATH**, not the git-free one, so
    steps 2 to 7 were re-checked separately without git (see the note below if that was done).
17. **The uninstaller leaves things behind** that the person can't easily see: `~/.ssh/um-codex/.lock`
    ("delete it yourself", though it is UM-Codex's own), `UM-Codex\app\update.lock`, saved setups'
    Docker volumes (`umcodex-home-*`, with `-KeepData`), and containers/volumes from a demo data
    folder ("from other data folders"). The Docker/WSL removal is manual by design.

## Alpha.7 launcher, the Codex app on Windows, and the filming (2026-10-05)

From recording "Your first launch on Windows" again on v0.1.0-alpha.7 (the launcher redesign,
PR #32), on the same Michigan Medicine Windows 11 PC.

18. **The first-run screen is "Get started"**: `✓ Toolkit key saved`, `✓ Docker is running`, then
    `3 Make your first setup` with a **New setup…** button. The old "Choose a folder and start…"
    is gone. The form is Folder (Choose folder…, More folders), Access (Internet, Browser tool),
    Codex (Model, Open in: Terminal or Codex app, Codex app selected), More options (Ask before
    commands, Name, Where Codex runs), then "What Codex gets", Save and start, Save, Cancel.
19. **"On this computer (experimental)" is shown but greyed out on Windows**, with the line "On this
    computer works with the Codex app on a Mac only, for now." Its help text, and the caution text
    behind it (`this_computer.WARNING`), say "your Mac" even where the option can't be used.
20. **The Codex app is the default on Windows when the Store package `OpenAI.Codex` is found**
    (`WINDOWS_COPY = True`). The card's line goes `Starting…`, `Opening Codex… preparing the
    sandbox for the Codex app.`, `Opening Codex… waiting for the Codex app to connect.`, `Connected ✓
    The Codex app is working in the sandbox (umcodex-<setup>_<id>).` (about 30 s). The copy opens
    on a project named after the folder with the chips "<folder>", "Remote" and, with a green dot,
    "umcodex-um-codex-dem…". After Stop it says "Couldn't reconnect to umcodex-…" with a Reconnect
    button, and a red dot on the project.
21. **The app shows its own banner "Full access is on"** (edit any file, run commands with internet
    access, no approval). Inside UM-Codex that is true only within the sandbox and the chosen
    folders; the video says so. (Same as Mac finding 12.)
22. **The Codex app made local Windows accounts and firewall rules on this PC**: users
    `CodexSandboxOffline` and `CodexSandboxOnline`, and two firewall rules named "Codex". They are
    the app's own Windows sandbox for local chats, set up with an administrator approval; they are
    not used by UM-Codex's remote chats. It also left a folder under its data folder
    (`codex-app\codex-home\sandbox…`) that the person's own account can't delete (access denied),
    so a demo data folder holding one can't be removed; each filming uses a new data folder.
    The uninstaller doesn't mention any of this.
23. **The installer's last lines are out of date for alpha.7**: "Its window opens in your browser:
    choose a folder to work in, and Codex starts there in a terminal." The launcher now says "New
    setup…" and opens the Codex app by default.
24. **A leftover Codex app copy keeps running after Stop** (its processes have no window), and a setup
    that is still running (its container, `launch` and `ssh-proxy` processes) stops `um-codex update`
    with "Quit Codex there first" even when the Codex window has been closed. The only way out was
    to press Stop in the launcher.

### Filming on this PC (not UM-Codex findings)

- **Chrome and Edge both refuse to start a second instance** (exit code 21) while either is open,
  because a managed policy forces their profile folder (`UserDataDir`). The page filming and the
  render drive the installed Chrome headless, so Chrome and Edge must be closed first.
- **The screen capture can fail for a few seconds** ("Failed to capture image (error 5)"), and key
  presses can be refused ("Access is denied"), when Windows puts a permission box on its secure desktop.
  `record-segments.ps1` records in segments and restarts at once; `Keys` retries.
- **A bugcheck (0x50, a driver) happened once while a full-screen recording was being stopped**;
  the cause is unknown.
