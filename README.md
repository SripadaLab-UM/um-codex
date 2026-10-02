# UM-Codex

Full-power OpenAI Codex on U-M GPT Toolkit, running in a Docker container on
your Mac or Windows computer. You choose which folders Codex can read, which
it can change, and whether it can use the internet; then Codex opens in the
Codex desktop app (Mac) or a terminal window. Usually that's one click.

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
Desktop. If you have the Codex app (ChatGPT's desktop app), it also asks
once whether to add the one line the Codex app needs in your `~/.ssh/config`
(Return is yes; see below). If you say no, installing again doesn't ask
again (`um-codex ssh-include --ask-again` does). Details: [docs/INSTALLING.md](docs/INSTALLING.md).

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

- **The first time:** press **Choose a folder and start…**, pick the folder
  in your computer's own folder picker, and Codex starts there: in the Codex
  app if you have it (Mac), otherwise in a terminal window. It starts with
  the internet on, running commands without asking, on `gpt-5.6-terra`. (If
  no key is saved yet, the page asks for it right there first.)
- **Next time:** press **Start "<your folder>"** at the top. That's it.
- Each folder you've used is a **setup**, shown as a card named after its
  folder (**Rename** changes that). The card always says what Codex can do
  with it: the folders (and that changes there are real, with no undo), the
  internet on or off, the browser tool, where it opens, the model. A line on
  the card follows a start: Starting… → Opening Codex… → Connected ✓.
- **Edit** a setup for more: more folders (each read only, or read &
  write), the internet and the browser tool, the model (newest first), where
  it opens, and, under More options, "Ask before commands", its name and
  where Codex runs (below: On this computer).
  **New setup with options…** starts from that form.
- **Stop** ends a running setup (it asks first, as **Delete** does).
- The strip at the top says whether Docker is running and your key is saved
  (**Replace**), and offers an **Update** when a new version is out. If
  Docker Desktop is closed when you press Start, UM-Codex opens it and
  starts once it's running.

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
- The app reaches the sandbox through ssh, which needs one line at the top
  of your `~/.ssh/config` (`Include ~/.ssh/um-codex/config`; your file is
  backed up first, and uninstalling takes it out). The installer asks about
  it once. If it isn't there (you said no, or installed the Codex app
  later), the setup's card explains it and its button says **Add the line
  and start**; or choose **Open in Terminal instead**.
  Settings in your own `Host *` entries (such as port forwards) still apply
  to these hosts, as ssh does for every host.
- **No set-up in the app:** UM-Codex prepares its copy before opening it,
  so it opens on a project named after your setup, already connected to the
  sandbox (Remote · `umcodex-<setup>`). Just start a chat there. The launcher
  says "Connected ✓" once the app is in, and starting the setup again later
  reconnects by itself.
- If UM-Codex's copy was already open (or an app update changed how it keeps
  its settings), the launcher shows the steps instead: in UM-Codex's Codex
  window, Settings → Connections → **Add**, choose `umcodex-<setup>`, **Add**;
  then Home → Choose project → **Create project**, named after the setup,
  "Add a folder on this computer" → `umcodex-<setup>` → **Add**, type
  `/work`, press Return, **Create project**. If the app asks what you'll use
  it for, choose **Skip**; if it announces a new model, choose **Continue
  with current model** (your setup decides the model).
- **Chats must show "Remote · umcodex-<setup>"** to run in the sandbox. Other
  (local) chats in that window would run on your computer, outside the
  sandbox, so UM-Codex blocks them: they only answer with a reminder to start
  a chat on Remote · `umcodex-<setup>` (while a setup runs or this launcher
  window is open; otherwise they just wait for the network).
- The app may show a chat's permissions as "Custom", greyed out: UM-Codex
  fixes them to full access inside the sandbox.
- Your own ChatGPT app reads the same `~/.ssh/config`, so it lists the
  `umcodex-*` hosts under Settings → Connections too (switched off). You can
  leave them off there; use UM-Codex's copy.
- The app's own browser runs on your computer, not in the sandbox. For
  browsing inside the sandbox, turn on the setup's Browser tool.
- The setup runs until you press **Stop** in the launcher; the app then says
  it can't reconnect, which is expected.
- Windows: not yet (Terminal only).

In a terminal: `um-codex launch --setup <name> --open app`.

### On this computer (Mac): computer and browser control

The sandbox is the safe default. A setup can instead run Codex **directly
on your Mac**, when you need it to use your apps (Computer Use), the Codex
app's own browser, or your own Chrome. Use it only for that.

- In the setup's form, open **More options** → **Where Codex runs** → **On
  this computer**. UM-Codex asks once, then: *Codex will run on your Mac, not
  in the sandbox. It can read, change and delete any of your files, use your
  apps and browser, and act with your accounts. While it runs, it may also be
  able to reach UM-Codex's own Toolkit key.* **Cancel** keeps the sandbox;
  **Run on this computer** switches. Its card then says **On this computer**,
  and Start doesn't ask again.
- It opens in **UM-Codex's local Codex window**: another copy of the Codex
  app, apart from your own and from the sandbox's copy (its chats never mix
  with either). No sign-in, no Docker. It opens on a project with the setup's
  folders.
- **What Codex can change:** "Anything I can (full access)" (the default), or
  "Only this setup's folders" (Codex's own macOS sandbox, for its commands
  and file edits), with its own **Internet for Codex's commands** switch.
  That second choice doesn't limit computer and browser control: those act
  through your apps, which can change anything you can.
- **Ask before commands** is on by default here, and needed with full
  access. There's no "Approve for me" (the Toolkit has no reviewer model
  for it).
- **Computer and browser control** (on by default) turns on the app's
  Computer Use, Browser and Chrome plugins. The first time, macOS asks for
  **Screen Recording** and **Accessibility** for "Codex Computer Use";
  Chrome needs the ChatGPT extension (Settings → Computer Use in that
  window). Whether OpenAI offers these without a ChatGPT account is still
  being checked.
- Read-only folders aren't offered (Codex can read all your files here).
- Your Toolkit key stays in the keychain, read only by UM-Codex's relay,
  which runs while that window is open. Quit the window, or press **Stop**,
  to end it; if UM-Codex's side ends first, it closes the window too.
- Uninstalling removes the programs in that window's folder (its Computer
  Use and plugins); its settings and chats go only if you delete UM-Codex's
  data. If you granted Screen Recording or Accessibility to "Codex Computer
  Use" and no longer need it, remove it in System Settings → Privacy &
  Security yourself (your own ChatGPT app may use the same entry).
- Not on Windows yet, and not in a terminal yet.

## Updating

When a new version is out, UM-Codex's window says so at the top: press
**Update**. It shows its progress (Downloading… Installing… Getting the new
image…), then "Updated to …": press **Reopen** to use it. It doesn't start
while a setup is running (stop them first), and if anything fails nothing
changes (the reason is in `um-codex.log`, in UM-Codex's data folder).
**Check for updates** at the top asks right away; otherwise UM-Codex checks
once a day.

In a terminal it's:

```sh
um-codex update
```

It installs the newest release beside the one you have (only a release
signed with UM-Codex's release key, and never while Codex is open), pulls
its containers, and switches to it; the version before is kept.
`um-codex update --rollback` switches back. Once a day, starting UM-Codex
says when a new version is out. Running the install command again also
installs the newest release.

On a Mac with 0.1.0-alpha.1 or alpha.2, typing `um-codex` in Terminal
doesn't work (it says "UM-Codex (none) can't be opened"). Update with the
install command above, or run the command by its full path:

```sh
"$HOME/Library/Application Support/UM-Codex/app/bin/um-codex" update
```

After that, plain `um-codex` works. (If it still doesn't, open the UM-Codex
app once: that puts it right.)

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
