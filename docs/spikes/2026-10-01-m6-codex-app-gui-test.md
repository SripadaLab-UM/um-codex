# Instructions: test "Open in: Codex app" (M6) in the app itself

For an agent with computer use on the maintainer's Mac. Written 2026-10-01
for branch `m6-codex-app`. Everything up to the app's own window was checked
without a GUI (docs/DESIGN.md, M6 "Live check"); these steps cover what
needs clicks. Report back with the answers in "What to report".

## Background, briefly

UM-Codex runs OpenAI Codex inside a Docker container (the "sandbox"). With
M6 a setup can open in **Codex's desktop app** (the ChatGPT app) instead of
a terminal: the app connects to the sandbox over ssh, as the host
**`umcodex-<setup id>`**, and every command and file change happens in the
sandbox. UM-Codex opens **its own copy** of the app, with its own settings.

The model is the U-M GPT Toolkit. Its key stays in the Mac's Keychain and a
relay on the Mac adds it to requests. **You never need the key, and must
never type, paste or look for it.**

There will be **two copies of the ChatGPT app** running. Use only
UM-Codex's:

- **UM-Codex's copy:** started with the settings folder
  `~/Library/Application Support/UM-Codex-m6-test/codex-app/`. Find it with
  `ps -axww -o pid=,args= | grep "UM-Codex-m6-test/codex-app/user-data" | grep -v Helper | grep -v grep`.
- **The maintainer's normal copy:** don't use it, don't change its
  settings, don't quit it.

## Rules

- Work only in UM-Codex's copy of the app, the launcher page in the
  browser, and Terminal for the read-only checks below.
- Never type or paste an API key, password or token. If anything asks to
  sign in (ChatGPT, OpenAI, an API key), don't. Note exactly what it asked,
  with a screenshot, and cancel.
- Don't change macOS settings or permissions; answer "Don't allow" to any
  permission prompt and note it.
- Don't edit `~/.ssh/config` or anything in `~/.codex`. (UM-Codex itself
  rewrites `~/.ssh/um-codex/config` when a setup starts; that's expected.)
- Delete nothing except files you create in the test chats.
- Take a screenshot at each numbered step.

## Before you start (Terminal)

1. Check that Docker Desktop is running: `docker info --format ok` prints
   `ok`. The image must be there:
   `docker image inspect um-codex-agent:m6 --format ok` prints `ok` (if not:
   `docker build -t um-codex-agent:m6 ~/work/um-codex-appopen/images/agent`,
   about 2 minutes with the cache).
2. Check that `~/.ssh/config` starts with `Include ~/.ssh/um-codex/config`
   (`head -1 ~/.ssh/config`). It should already. If it doesn't, the
   launcher will ask; choose Allow and note the dialog's text.
3. Make the test folder and start the launcher with a data folder of its
   own (leave this Terminal tab open; it's the launcher's server):

   ```sh
   mkdir -p ~/Documents/UM-Codex-m6-test
   cd ~/work/um-codex-appopen
   UMCODEX_DATA_DIR="$HOME/Library/Application Support/UM-Codex-m6-test" \
   UMCODEX_AGENT_IMAGE=um-codex-agent:m6 uv run um-codex ui
   ```

   The launcher page opens in the browser.

## Steps

1. **New setup** in the launcher page:
   - "Choose working folder…": `~/Documents/UM-Codex-m6-test`.
   - Name: `m6 test`. Internet: on. Browser tool: on, "Approve each browser
     action" on. "Ask me before commands": off.
   - Open in: **Codex app** (record whether it's enabled, and the help line
     under it). Save.
2. **Start** on the card. Record the summary page's "In the Codex app:"
   lines, then press "Start in Codex app".
   - Expected: a notice "Starting in the Codex app…", then in about 20 s a
     **second ChatGPT window** opens (UM-Codex's copy), and the launcher's
     "Running now" shows "m6 test · Running in the Codex app since …" with
     "The first time for this setup…" and four steps.
   - Record: did the copy show any sign-in screen? Did it open on Settings →
     Connections, or on its home screen?
3. **Settings → Connections** in UM-Codex's copy. Record what's listed under
   SSH (expect `umcodex-m6-test-…`; `umcodex-app-test`, a leftover of the
   spike, may be listed too: ignore it). Turn on `umcodex-m6-test-…`.
   Record what it shows (connecting, connected, an error).
4. **Open a chat in the sandbox.** Start a new chat on that host with the
   folder `/work` (the project "work", Remote · `umcodex-m6-test-…`, or
   "add folder" `/work` on that host). Record the exact clicks: they become
   the launcher's steps.
   - The chat's location strip must read "work · Remote · umcodex-m6-test-…".
   - Within a few seconds the launcher page should show **"✓ Connected: the
     Codex app is working in the sandbox (umcodex-m6-test-…)"**, and the
     steps go away. Record how long it took.
5. **Permissions.** In the chat's composer, find the permission control
   (it may read "Full access", "Default permissions" or similar). Record
   what it shows, then open it and record every option offered. Don't
   change it. (UM-Codex allows only full access in the sandbox; anything
   else falls back to it.)
6. **Basic test.** Send:
   `run pwd, whoami and ls -la, then create hello.txt containing "hello from the container"`.
   - Expect `/work`, `agent`, and no approval questions for commands.
   - In Terminal: `cat ~/Documents/UM-Codex-m6-test/hello.txt` shows the text.
7. **Model and internet.** Open the model picker; record the list and the
   selected model. Send:
   `run curl -sI https://example.com | head -1 and python3 -c "import pandas; print('ok')"`.
   Expect an HTTP 200 line and `ok`.
8. **The browser tool (in the sandbox).** Send:
   `use the browser tool to open https://example.com and tell me the page title`.
   Expect an approval question for opening the page (approve it) and the
   title "Example Domain". Record how the approval looked in the app.
9. **A local chat (on the Mac).** In UM-Codex's copy, start a new chat that
   is **not** on the remote host (the local "this computer" kind). Send:
   `reply with the single word hi; don't run any commands`.
   Record whether it answers (it goes through the Toolkit by way of the
   running launch), and how the app shows that it's local. Don't ask it to
   run anything.
10. **Stop.** In the launcher, press Stop on the running setup. Record the
    question's text; press Stop. In the app, record what the sandbox chat
    shows (expected: it can't reconnect to `umcodex-m6-test-…`).
11. **Start again (the reconnect test).** In the launcher, Start `m6 test`
    again. Expected: no new ChatGPT window; UM-Codex's copy comes to the
    front (record whether it did), and the launcher says "Waiting for the
    Codex app to reconnect to umcodex-m6-test-…" without the steps.
    - Record whether the app reconnects **by itself** (the location dot
      goes green, and the launcher shows "Connected ✓"), and how long it
      took. If it doesn't within a minute, record what you had to do.
    - In the old sandbox chat, send `run pwd` and record the result.
12. **The local chat after a restart.** In the local chat from step 9, send
    `reply with the single word again`. Record whether it answers (the
    launch's relay has a new port now).
13. **End.** Stop the setup in the launcher. Quit **UM-Codex's copy only**
    (Cmd-Q while it's in front; check the maintainer's normal copy is still
    running). In the launcher's Terminal tab press Ctrl-C.

## What to report

1. Step 1: was "Codex app" enabled; its help line.
2. Step 2: the summary lines; any sign-in screen; where the copy opened.
3. Step 3: what Connections → SSH listed; what turning the host on showed.
4. Step 4: the exact clicks; the location strip; when "Connected ✓" showed.
5. Step 5: the permission control's label and every option it offered.
6. Steps 6–8: the outputs; whether hello.txt appeared on the Mac; the model
   list; the browser approval and the title.
7. Step 9: whether the local chat answered, and how the app marks it local.
8. Step 10: the Stop question's text and what the app showed.
9. Step 11: whether the copy came forward, whether the app reconnected by
   itself (and how long), and `pwd` in the old chat.
10. Step 12: whether the local chat still worked.
11. Anything confusing for a non-developer, and anything that looked wrong.

## Undo (only if the maintainer asks)

- `rm -rf "$HOME/Library/Application Support/UM-Codex-m6-test"` (the test's
  setups and the copy's settings and chats), after the copy has been quit.
- The setup's Codex history volume: `docker volume ls --filter label=umcodex.app=um-codex`
  and `docker volume rm` the `umcodex-home-m6-test-…` one.
- `~/.ssh/um-codex/m6-test-…_ed25519*` and its Host in
  `~/.ssh/um-codex/config` (deleting the setup in the launcher removes both).
