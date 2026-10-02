# UM-Codex

Full-power OpenAI Codex on U-M GPT Toolkit, running in a Docker container on
your Mac or Windows computer. You choose which folders Codex can read, which
it can change, and whether it can use the internet; then Codex opens in a
terminal window.

Status: under construction (see [docs/DESIGN.md](docs/DESIGN.md)). The
install commands below work once the first release is published
([docs/RELEASING.md](docs/RELEASING.md)).

You need a U-M GPT Toolkit API key for Codex (see ITS's "Codex Setup"
articles for how to get one). The key is kept in your computer's keychain and
never goes into the container.

## Install on a Mac

In Terminal (Applications > Utilities > Terminal), paste:

```sh
curl -q -fsSL https://github.com/SripadaLab-UM/um-codex/releases/latest/download/install-macos.sh | sh
```

It sets up Docker Desktop (if it isn't there, it asks first), UM-Codex and
your key, then adds the UM-Codex app to Applications and a shortcut to the
Desktop. Details: [docs/INSTALLING.md](docs/INSTALLING.md).

## Install on Windows

In Windows PowerShell (Start menu > Windows PowerShell), paste:

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; irm https://github.com/SripadaLab-UM/um-codex/releases/latest/download/install-windows.ps1 | iex
```

It sets up Docker Desktop (with one administrator step and a restart, if
needed), UM-Codex and your key, then adds UM-Codex to the Start menu and the
Desktop. Details: [docs/INSTALLING.md](docs/INSTALLING.md).

## Opening UM-Codex

Open the **UM-Codex** app (Mac: the Desktop shortcut, Applications, or
Spotlight; Windows: the Desktop shortcut or the Start menu). It opens
UM-Codex's window in your web browser. The page runs on your own computer
(at `127.0.0.1`, signed in by the link the app opens) and isn't on the web.
There you:

- make a **setup**: a name, the working folder Codex starts in, any more
  folders (each read only, or read & write), the internet on or off (and,
  with it on, the browser tool), whether Codex asks before commands, and the
  model. "Choose folder…" opens your computer's own folder picker;
- press **Start** on a setup: the page shows what Codex will be able to see
  and do, then opens a terminal window with Codex in it (or the Codex app:
  see below);
- see what's **running** ("Running since 14:05") and **Stop** it;
- see whether Docker is running, whether your key is saved ("Replace key…"),
  and whether a new version is out.

The window closes by itself a while after you close its page; opening the
app again brings it back. In a terminal, `um-codex ui` opens it too, and
plain `um-codex` still asks the setup questions in the terminal instead.

### Opening a setup in the Codex app (Mac)

Instead of a terminal, a setup can open in **Codex's desktop app** (part of
OpenAI's ChatGPT desktop app; get it from https://chatgpt.com/download). In
the setup, choose **Open in: Codex app**. The work still happens in the
sandbox, with the same folders, internet setting and key protection; the app
is only the window you use. What to know:

- UM-Codex opens **its own copy** of the app, with its own settings, beside
  your normal one (a second ChatGPT icon in the Dock). Your own Codex/ChatGPT
  app and its settings aren't touched, and the copy needs no sign-in.
- The app reaches the sandbox through ssh. The first time, UM-Codex asks to
  add one line at the top of your `~/.ssh/config`
  (`Include ~/.ssh/um-codex/config`; your file is backed up first, and
  uninstalling takes it out). Choose **Allow**, or use Terminal instead.
  Settings in your own `Host *` entries (such as port forwards) still apply
  to these hosts, as ssh does for every host.
- **The first time for each setup**, in UM-Codex's Codex window: open
  Settings → Connections and turn on `umcodex-<setup>`; then start a chat in
  the project "work" (Remote · `umcodex-<setup>`), or add the folder `/work`.
  The launcher shows these steps and says "Connected ✓" once the app is in.
  After that, the app is meant to reconnect by itself when you start the
  setup again; if it doesn't, "show the steps" in the launcher brings them
  back.
- **Chats must show "Remote · umcodex-<setup>"** to run in the sandbox. Other
  (local) chats in that window would run on your computer, outside the
  sandbox, so UM-Codex blocks them: they only answer with a reminder to start
  a chat on Remote · `umcodex-<setup>`.
- Your own ChatGPT app reads the same `~/.ssh/config`, so it lists the
  `umcodex-*` hosts under Settings → Connections too (switched off). You can
  leave them off there; use UM-Codex's copy.
- The app's own browser runs on your computer, not in the sandbox. For
  browsing inside the sandbox, turn on the setup's Browser tool.
- The setup runs until you press **Stop** in the launcher; the app then says
  it can't reconnect, which is expected.
- Windows: not yet (Terminal only).

In a terminal: `um-codex launch --setup <name> --open app`.

## Updating

```sh
um-codex update
```

It installs the newest release beside the one you have (only a release
signed with UM-Codex's release key, and never while Codex is open), pulls
its containers, and switches to it; the version before is kept.
`um-codex update --rollback` switches back. Once a day, starting UM-Codex
says when a new version is out. Running the install command again also
installs the newest release.

To remove UM-Codex: `uninstall-macos.sh` or `uninstall-windows.ps1` from the
same release page (they ask before removing your saved setups and Codex
history).

## Run from source (M1, a Mac with Docker Desktop)

You need [uv](https://docs.astral.sh/uv/), Docker Desktop (running), and git.

1. Build the agent image locally (it isn't published yet). It's in
   `images/agent`, on the `m1-image` branch until that's merged:

   ```sh
   docker build -t um-codex-agent:dev path/to/a/checkout/of/m1-image/images/agent
   ```

2. In this repository:

   ```sh
   uv sync
   uv run um-codex pull      # the gateway image; the :dev agent image is skipped
   uv run um-codex key       # paste your Toolkit API key (saved in the Keychain)
   uv run um-codex doctor    # checks Docker, the images, the key and the Toolkit
   uv run um-codex ui        # the launcher window, in your browser
   uv run um-codex           # or: the setup questions in this terminal, then Codex opens
   ```

`um-codex` asks which folder Codex works in, which more folders it can
write, which it can only read, whether the internet is on (and, if it is,
whether the browser tool is on), the model and the approvals, then shows a
summary and asks "Start?". When you quit Codex, the container is removed;
the setup's Codex history is kept (`codex resume` works next time, or
`uv run um-codex launch -- resume`).

With the internet on, `um-codex` also asks about the **browser tool**
(default off): "Browser tool on? (Codex can open websites in a fresh browser
inside the sandbox; it has none of your logins.)". When it's on, Codex can
open pages, click, fill in forms, read pages and take screenshots, in a
headless Chromium inside the container. It's a fresh browser each time, not
yours: it has none of your logins or cookies, and it can't see or control
your own browser or desktop. By default you approve each browser action
("Approve each browser action (opening pages, clicking, typing)? [Y/n]");
reading the page that's open (a snapshot or screenshot) doesn't ask. Codex is
told to save a screenshot in your working folder only when you ask for one.

A word of care: Codex can change anything in the folders you let it write,
including files your own tools run later on your computer (git hooks, a
Makefile, `package.json` scripts, `.envrc`, `.vscode/tasks.json`). Look before
running those in a folder Codex has worked in.

Other commands: `uv run um-codex setups` (list, edit, delete setups) and
`uv run um-codex uninstall`.

For development only:
- `UMCODEX_DATA_DIR` puts UM-Codex's data folder somewhere else;
- `um-codex ui --no-browser` prints the launcher window's sign-in link
  instead of opening the browser (the link works once);
- `UMCODEX_AGENT_IMAGE` uses another agent image;
- `UMCODEX_UPSTREAM` sends model requests to a local stub instead of the
  Toolkit (UM-Codex says so when it's set);
- `UMCODEX_INSTALL_DIR` and `UMCODEX_RELEASES_API` (tests) point
  `um-codex update` at another program folder and at a stand-in for
  GitHub's API on this computer; `UMCODEX_NO_UPDATE_CHECK=1` turns off the
  daily check at launch.

Releases, signing and `um-codex update`: [docs/RELEASING.md](docs/RELEASING.md).

Checks: `uv run ruff check . && uv run pyright && uv run pytest -q`.
