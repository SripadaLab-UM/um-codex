# Codex desktop app against a UM-Codex container: hands-on results

Run on 2026-10-01 by a computer-use agent following
`2026-10-01-codex-app-test-instructions.md`, with the test build on branch
`spike-codex-app` (21db539). Summary by the maintainer's session.

- **Sign-in:**
  - The test copy (its own CODEX_HOME and user-data, local provider = the
    Toolkit through the relay) opened with no sign-in at all. Its profile
    menu showed "U-M GPT Toolkit (through UM-...)".
  - No ChatGPT or OpenAI sign-in was offered for the remote.
- **Connections:**
  - Settings → Connections → SSH listed `umcodex-test`.
  - The one-step `codex://settings/connections/ssh/add?...&projectPath=/work&enabled=true`
    link, passed at the copy's start, did **not** connect by itself (an
    earlier run). After the host was switched on and `/work` added by hand,
    it showed "Connected".
  - Chats show a location strip: "work · Remote · umcodex-test" (green).
- **In the container:**
  - Commands ran in `/work` as `agent`. Python, R 4.6.1 and
    `curl https://example.com` (HTTP 200) worked, with the internet on.
  - The created file was verified inside the container. The host-side read
    was blocked by macOS for the test runner, but an earlier read showed the
    file on the host.
- **Edits:** a diff in chat, an "Edited hello.txt +1 -0" card, and "View
  changes" opened the Changes panel. Opening a file launched VS Code
  connected to `work [SSH: umcodex-test]`.
- **Models:**
  - The picker listed Default, 6 Astra, 6 Sol, 6 Luna, 5.6 Sol, 5.6 Terra,
    5.6 Luna and 5.5.
  - Switching to 6 Sol and sending a message worked, through the Toolkit.
- **Browser:**
  - The app's in-app browser opened Example Domain, but it runs on the Mac,
    not in the container.
  - The remote agent only got "queued" and couldn't control or verify it.
  - Computer Use and Chrome tools were unavailable in the remote chat.
- **Container ends:** the app showed "Couldn't reconnect to umcodex-test /
  Your connection keeps dropping", the location dot went red, and the
  composer didn't accept a message.
- **Friction for non-developers:**
  - Local and remote chats are easy to mix up.
  - Adding the remote folder the first time is a manual step.
  - The model names are OpenAI-style.
  - The in-app browser isn't the agent's.
  - Opening a file switches to the external editor.
