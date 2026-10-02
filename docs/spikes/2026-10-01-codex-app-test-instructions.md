# Instructions: test the Codex desktop app against a UM-Codex container

For an agent with computer use on the maintainer's Mac. Written 2026-10-01.
Report back to the maintainer with the answers in "What to report".

## Background, briefly

UM-Codex runs OpenAI Codex inside a Docker container. We're testing whether
the **Codex desktop app** can be UM-Codex's front end: the app on the Mac,
but every file, command and model call inside the container. The app does
this through its SSH "Connections" feature. The container is reached as the
SSH host **`umcodex-test`**, through a `docker exec` command, not a network
port.

The model is the U-M GPT Toolkit. Its key stays in the Mac's Keychain, and a
relay on the Mac adds it to requests. **You never need the key, and must never
type, paste or look for it.**

There are **two copies of the Codex app** on this Mac. Only use the test copy:

- **The test copy:** started with UM-Codex's own settings folder,
  `~/Library/Application Support/UM-Codex/codex-app/`. It's the one to use.
- **The maintainer's normal copy:** their own Codex/ChatGPT app. Don't use
  it, don't change its settings, and don't quit it.

Both show as "ChatGPT" or "Codex" with the same icon. To tell them apart:

- The test copy has no chat history except a few test chats ("test,
  working?", "run pwd and ls…").
- Its Settings → Connections → SSH lists `umcodex-test`, which you or the
  maintainer switched on.
- If unsure, use `ps -o pid,args -ax | grep "user-data-dir=.*UM-Codex"` in
  Terminal to find the test copy's process.

## Current state (already set up; check, don't redo)

- **A test launch is running** in a Terminal tab. It printed
  "Ready: `ssh umcodex-test` reaches the container… Press Ctrl-C to end the
  test launch." Leave it running until the end; the relay lives there.
- **Check from Terminal:** `ssh -o BatchMode=yes umcodex-test 'echo ok $(whoami) $CODEX_HOME; codex --version'`
  should print `ok agent /codex-home` and `codex-cli 0.157.1`. If it
  doesn't, stop and report.
- **The test copy of the app is open.** It has already connected to
  `umcodex-test`: Codex's app-server is running inside the container.
- **The container's working folder `/work`** is the Mac folder
  `~/Documents/UM-Codex-app-test`.
- **Known from earlier:**
  - The test copy opened with **no sign-in**.
  - The one-step `codex://…ssh/add` link did **not** connect by itself.
  - The first two chats ran **on the Mac**, not in the container. One left
    an empty `~/work/hello.txt`, which you can ignore.

## Rules

- Work only in the **test copy** of the app, plus Terminal for the read-only
  checks below. Don't open other apps' settings or sign in to anything.
- Never type or paste an API key, password or token. If anything asks to
  sign in (ChatGPT, OpenAI, an API key), don't sign in. Note exactly what it
  asked, with a screenshot, and continue or cancel.
- Don't change macOS settings or permissions. If the app asks for Screen
  Recording, Accessibility or similar, choose "Don't allow" or cancel, and
  note it.
- Don't delete anything except the files you create in the test chats.
- Don't edit `~/.ssh/config`, anything in `~/.codex`, or the app's files.
- Don't press Ctrl-C in the test launch's Terminal tab until step 9.
- Take a screenshot at each numbered step and keep them for the report.

## Steps

1. **Find the test copy** and bring it to the front (see Background).

2. **Look at Settings → Connections → SSH** in the test copy.
   - Record whether `umcodex-test` is listed and switched on, and anything
     else listed.
   - If it's off, switch it on.

3. **Open a chat on the container.** Start a new chat, or new project, on
   the `umcodex-test` host with the folder **`/work`**. The app may offer a
   folder picker for the remote: choose `/work`.
   - Record the exact clicks needed. This is the flow we'll document for
     people.
   - Make sure the chat's location shows `umcodex-test` and `/work`, not a
     folder on the Mac. If you can't tell, step 4's `pwd` will.

4. **Basic test.** Send: `run pwd, whoami and ls -la, then create hello.txt containing "hello from the container"`.
   - Expect `pwd` = `/work` and `whoami` = `agent`.
   - Check from Terminal: `cat ~/Documents/UM-Codex-app-test/hello.txt`
     should show the text.
   - If commands need approval, approve them and note that they asked.

5. **The model goes through the Toolkit, not OpenAI.** Send:
   `which model are you, and what is your CODEX_HOME?`
   - Note the answer.
   - Open the model picker and record which models are listed and which is
     selected. We expect the Toolkit's `gpt-5.6-terra` or OpenAI's default
     names; the Toolkit's model list is known not to load.
   - Try switching to another listed model, send one short message, and
     note whether it works or errors.

6. **Container tools and internet** (internet is on for this test). Send:
   `run python3 -c "import pandas, numpy; print('ok')" and R --version | head -1, then curl -sI https://example.com | head -1`.
   - Expect `ok`, an R version line, and an HTTP 200 line.

7. **Edits, diffs and files in the app UI.**
   - Ask: `edit hello.txt to add a second line "edited", and show me the diff`.
   - Note whether the app's diff or review panel shows the change.
   - Note whether you can open or preview the file from the app (it uses SFTP).
   - Check from Terminal: `cat ~/Documents/UM-Codex-app-test/hello.txt` has
     both lines.

8. **What the app offers for the remote.**
   - Is a ChatGPT/OpenAI sign-in offered anywhere for this host?
   - Is the in-app browser, Computer Use or "Chrome" offered in this chat,
     and does it work? Try `open example.com in the browser` once, and
     cancel any permission prompt.
   - Note any errors, banners or warnings, with screenshots.

9. **What happens when the container goes away.**
   - In the test launch's Terminal tab, press **Ctrl-C** once and wait for
     it to finish ("Ending the test launch…").
   - In the app, send one more message in the container chat and note what
     the app shows: an error, reconnecting, or a hang.
   - Don't restart the test launch.

10. **Close the test copy only:** Cmd-Q while the test copy is in front.
    Confirm the maintainer's normal app is still running.

## What to report

Answer each item with yes/no or the observed text, plus the screenshots.

1. Did the test copy reach chats with **no sign-in**? Did anything ask to
   sign in, and where?
2. **Settings → Connections → SSH:** was `umcodex-test` listed? Was it on
   already, or did you switch it on? What else was listed?
3. **Opening a chat on `umcodex-test` in `/work`:** the exact clicks, and any
   friction.
4. **Step 4:** the `pwd` / `whoami` output, and whether `hello.txt` appeared in
   `~/Documents/UM-Codex-app-test` with the right text.
5. **Step 5:** the model's answer, the model picker's list, and whether
   switching models worked.
6. **Step 6:** pandas/numpy, R and curl results.
7. **Step 7:** whether the diff showed in the app, and whether the files
   opened or previewed.
8. **Step 8:** any sign-in offered for the remote; browser and Computer Use
   availability; errors or warnings.
9. **Step 9:** what the app showed after the container ended.
10. Anything confusing a non-developer would trip on, and anything that
    looked wrong.

## Undo (only if the maintainer asks; not part of the test)

In Terminal:

- `cd ~/work/um-codex-appspike && .venv/bin/um-codex app-test stop --purge`
  removes the test containers, the SSH host file and key, the test history
  volume and the test copy's data.
- `cp ~/.ssh/config.um-codex-backup ~/.ssh/config && rm ~/.ssh/config.um-codex-backup && rmdir ~/.ssh/um-codex`
  restores `~/.ssh/config`.
