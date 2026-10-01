# Notes for the video agent

For the agent that will make UM-Codex's companion videos, like DataLab's
(see DataLab's `docs/videos/` for the format, voice and tooling) but fewer
and shorter. Kept up to date as features land. **Check each claim against
the code and docs/DESIGN.md at the commit you record from**, and mark
anything still in "Not built yet" as left out.

Last updated: 2026-10-01 (M1 launcher, M2 installers, M2b browser tool and
M3 releases and updates built; no release published yet, so record installs
once one is).

## Who it's for

A research group that wants full-power Codex, not a locked-down tool. They
aren't developers of UM-Codex and may not know Docker. Tone: practical and
plain; no product pitch. These are separate from DataLab's users.

## Suggested set (short: 2–4 minutes each)

1. **What UM-Codex is** (about 2 min): Codex on the U-M GPT Toolkit, running
   in a sealed environment on your own computer; you choose what it can see
   and whether it can use the internet; Codex's own screen is the
   interface. One diagram: your computer, the sealed environment with Codex
   in it, your chosen folders going in, the key staying outside.
2. **Installing on a Mac** and 3. **Installing on Windows** (about 3 min
   each): the one install command, Docker Desktop (installed for you if
   missing; on Windows the one-time administrator step and the VM fix), the
   Toolkit key prompt, the UM-Codex app on the Desktop.
4. **Your first launch** (about 3 min): the setup questions, the summary
   screen, Codex opening, asking it to do something in the working folder,
   quitting, launching again with "use last setup".
5. **Folders and internet, in practice** (about 2 min): read-only vs write
   folders, internet on vs off, what each means (see "What to say" below).
6. **The browser tool** (about 2 min): turning it on in a setup, the summary
   line, asking Codex to open a page and tell you what's on it, approving
   the browser action, and a screenshot saved in the working folder when
   asked.

Later, when built: "On this computer" mode (M4).

## What to say (true now, in the code)

- **The key.** You enter your U-M GPT Toolkit API key once; it's kept in
  your computer's secure keychain (macOS Keychain, Windows Credential
  Manager). It never goes inside the sealed environment: a small relay on
  your computer adds it to Codex's requests on the way out. So even with
  the internet on, nothing Codex runs can read or send your key. (This is
  a difference from ITS's setup articles, which put the key in a file.)
- **The setup questions, in order:** a name; the working folder (Codex
  starts there; it can read, change and delete in it); more folders Codex
  can change; folders it can only read; internet on or off; with the
  internet on, the browser tool (see below); the model
  (default `gpt-5.6-terra`); approvals ("runs commands without asking", the
  default, or "ask me before commands"). Then a summary in plain words and
  "Start? [Y/n]". Setups are saved; next time it offers the last one.
- **Write folders are real.** Changes and deletions in the working folder
  and write folders happen to your actual files, with no undo or trash.
  Say this plainly; suggest a copy or a git repo for anything important.
- **Read-only folders** can't be changed, even by Codex using `sudo`.
- **Internet off:** Codex can reach the model and nothing else (no
  downloads, no installs, no websites).
- **Internet on:** the whole internet. Known limit, decided on purpose:
  with internet on, Codex can also reach services on your own computer and
  your local network or VPN. The launch screen says so.
- **The browser tool** (only offered when the internet is on; off unless
  you turn it on). The questions, exactly: "Browser tool on? (Codex can
  open websites in a fresh browser inside the sandbox; it has none of your
  logins.) [y/N]", then "Approve each browser action (opening pages,
  clicking, typing)? [Y/n]". The summary says "Browser tool: ON. Codex can
  open websites in a fresh browser inside the sandbox; it has none of your
  logins." and "It asks you before each browser action (opening pages,
  clicking, typing); reading a page doesn't ask." With it on, Codex can
  open pages, click, fill in forms, read pages and take screenshots, in a
  browser with no window that runs inside the sealed environment. It's a
  fresh browser every time: none of your logins, cookies or bookmarks, and
  it can't see or control your own browser or desktop. By default Codex
  stops and asks before each action that opens a page, clicks or types; you
  approve ("Allow") or decline ("Cancel") it in Codex's screen. Reading the
  page that's open (its text, a screenshot) doesn't ask. Codex is told to
  save a screenshot in your working folder only when you ask for one. With
  the internet off there's no browser tool (the question isn't asked).
- **Inside the environment** Codex has Python, R, Node, git and build tools,
  and can install more with `sudo` when the internet is on. Installed
  things last only for that session; files in your folders stay.
- **History:** quitting removes the environment but keeps Codex's history
  for that setup, so `codex resume` picks up where you left off.
- **Two things UM-Codex refuses to share:** your whole home folder or a
  whole drive, and private places like your keychain, `.ssh` and cloud
  credentials. It explains why in plain words.
- **Checking things:** `um-codex doctor` checks Docker, the key and the
  Toolkit and says what's wrong.
- **Installing:** one command pasted into Terminal (Mac) or Windows
  PowerShell, from the README; it needs no options. It sets up Docker
  Desktop if needed, UM-Codex, the key, and the app (Mac: Applications and a
  Desktop shortcut; Windows: Start menu and Desktop).
- **Updates:** `um-codex update` installs the newest version beside the one
  you have, only if it's signed by the UM-Codex release key, and never
  while Codex is open; the version before is kept, and
  `um-codex update --rollback` goes back to it. About once a day, starting
  UM-Codex prints one line when a new version is out. Updates don't touch
  your folders, setups or Codex history.

## Careful wording

- "Sealed environment" for the container, as in DataLab's videos; say
  "Docker" only where the person sees it (installing Docker Desktop).
- "The University of Michigan's GPT Toolkit": narration never says "U-M"
  (the voice reads it as letters); the screen can show "U-M GPT Toolkit".
- Don't call it "safe" or "secure" without saying what from: the key is
  protected; your chosen folders are exactly what Codex can touch.
- The browser tool is a separate browser inside the sealed environment,
  not the person's own: don't say Codex "uses your browser". Don't promise
  control of the person's own browser or computer yet (see below).

## Recording

- Use a demo folder of made-up files; no real research data, names or
  emails on screen.
- Never show the key: the prompt is masked; don't record a screen where
  it's typed into anything else.
- Footage of Codex's own screen is the main visual; the summary screen is
  worth a pause.

## Not built yet (leave out until it is)

- "On this computer" mode, the person's own browser, computer control
  (M4; computer control depends on a spike).
- An install website; until then the README has the commands.
