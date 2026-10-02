# Notes for the video agent

For the agent that will make UM-Codex's companion videos, like DataLab's
(see DataLab's `docs/videos/` for the format, voice and tooling) but fewer
and shorter. Kept up to date as features land. **Check each claim against
the code and docs/DESIGN.md at the commit you record from**, and mark
anything still in "Not built yet" as left out.

Last updated: 2026-10-01 (M1 launcher, M2 installers, M2b browser tool, M3
releases and updates, M5 launcher window and M6 "Open in: Codex app" (Mac)
built; no release published yet, so record installs once one is).

## Who it's for

A research group that wants full-power Codex, not a locked-down tool. They
aren't developers of UM-Codex and may not know Docker. Tone: practical and
plain; no product pitch. These are separate from DataLab's users.

## Suggested set (short: 2–4 minutes each)

1. **What UM-Codex is** (about 2 min): Codex on the U-M GPT Toolkit, running
   in a sealed environment on your own computer; you choose what it can see
   and whether it can use the internet, in a small window in your browser;
   then Codex's own screen is where you work with it. One diagram: your computer, the sealed environment with Codex
   in it, your chosen folders going in, the key staying outside.
2. **Installing on a Mac** and 3. **Installing on Windows** (about 3 min
   each): the one install command, Docker Desktop (installed for you if
   missing; on Windows the one-time administrator step and the VM fix), the
   Toolkit key prompt, the UM-Codex app on the Desktop.
4. **Your first launch** (about 3 min), in the launcher window: open the
   UM-Codex app and its window opens in the browser (the status line at the
   top: Docker running, key saved). "New setup": choose the working folder
   with "Choose folder…" (the computer's own folder picker), the name fills
   in from it; add a read-only folder (a chip with "Read only / Read &
   write"); leave the internet off; Save. The setup appears as a card. Press
   Start: the page shows what Codex will be able to see and do (pause on
   it), then "Start in Terminal" opens a terminal window with Codex in it.
   Ask Codex to do something in the working folder. Back in the browser,
   "Running now: *setup* · Running since 14:05 · Stop". Quit Codex (or press
   Stop), and the card is still there for next time.
5. **Folders and internet, in practice** (about 2 min): read-only vs write
   folders, internet on vs off, what each means (see "What to say" below).
6. **The browser tool** (about 2 min): turning it on in a setup, the summary
   line, asking Codex to open a page and tell you what's on it, approving
   the browser action, and a screenshot saved in the working folder when
   asked.

7. **Opening a setup in the Codex app** (about 3 min, Mac only): for people
   who prefer Codex's desktop app to a terminal. Show, in order:
   - the ChatGPT desktop app installed (from chatgpt.com/download; Codex is
     part of it), and the launcher's form with "Open in: Codex app" chosen
     (before it's installed, the choice is greyed out with that link);
   - Start: the summary, with "In the Codex app:" and its two lines; the
     one-time question about the ssh line ("Let the Codex app find the
     sandbox?", with the reason) and Allow;
   - a second ChatGPT icon in the Dock: UM-Codex's own copy, which opens
     with no sign-in (say: your own ChatGPT app isn't touched);
   - the copy opening straight on a project named after the setup, with
     "Remote · umcodex-<setup>" and a green dot under the composer: nothing
     to set up (say: UM-Codex prepared it);
   - the launcher turning to "Connected ✓";
   - asking Codex to list the files and make one in the working folder, and
     the file appearing in Finder; the diff and "View changes" in the app;
   - optionally, a local (not Remote) chat answering with the reminder to
     use a Remote chat;
   - Stop in the launcher (its question says the app will show it can't
     reconnect), and the app showing that;
   - starting the setup again later: the app comes forward and reconnects by
     itself.

Later, when built: "On this computer" mode (M4).

## What to say (true now, in the code)

- **The key.** You enter your U-M GPT Toolkit API key once; it's kept in
  your computer's secure keychain (macOS Keychain, Windows Credential
  Manager). It never goes inside the sealed environment: a small relay on
  your computer adds it to Codex's requests on the way out. So even with
  the internet on, nothing Codex runs can read or send your key. (This is
  a difference from ITS's setup articles, which put the key in a file.)
- **The launcher window** (what the app opens): a page in your browser,
  served by UM-Codex on your own computer, not a website. A setup there has:
  the working folder (Codex starts there; it can read, change and delete in
  it); a name; more folders, each "Read only" or "Read & write"; Internet
  (off or on); with the internet on, the Browser tool and "Approve each
  browser action" (see below); "Ask me before commands" (off by default:
  Codex runs commands without asking); the model (default `gpt-5.6-terra`);
  and "Open in": Terminal or Codex app (Mac; see below). Folders are chosen with the computer's own folder picker;
  a folder UM-Codex won't share is refused right there in plain words.
  Before Start it shows a summary in plain words, then opens Codex in a
  terminal window. Setups are kept as cards, with Start, Edit, Duplicate and
  Delete; running ones show "Running since …" and Stop.
- **The terminal way** still works: typing `um-codex` in a terminal asks the
  same things as questions (working folder, name, more folders to write,
  folders to read only, internet, browser tool, model, approvals), then the
  summary and "Start? [Y/n]".
- **Write folders are real.** Changes and deletions in the working folder
  and write folders happen to your actual files, with no undo or trash (the
  summary says: "These are your real files: changes and deletions there
  happen straight away, with no undo.").
  Say this plainly; suggest a copy or a git repo for anything important.
- **Read-only folders** can't be changed, even by Codex using `sudo`.
- **Internet off:** Codex can reach the model and nothing else (no
  downloads, no installs, no websites).
- **Internet on:** the whole internet. Known limit, decided on purpose:
  with internet on, Codex can also reach services on your own computer and
  your local network or VPN. The summary before a start says so.
- **The browser tool** (only offered when the internet is on; off unless
  you turn it on). In the launcher window: the "Browser tool" switch (its
  line: "Codex can open websites in a fresh browser inside the sandbox; it
  has none of your logins.") and "Approve each browser action" (on by
  default). In the terminal, the questions are "Browser tool on? (…) [y/N]"
  and "Approve each browser action (opening pages, clicking, typing)?
  [Y/n]". The summary says "Browser tool: ON. Codex can
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
- **The model inside Codex.** Codex opens on the setup's model. `/model`
  lists the Toolkit's models that Codex knows; picking one changes it for
  that session (Codex says the saved choice is overridden: the next launch
  uses the setup's model again; edit the setup to change it for good).
  Codex never offers to switch to another model by itself. Codex's own
  preferences (reasoning level, its screen settings) are kept for the setup.
- **Two things UM-Codex refuses to share:** your whole home folder or a
  whole drive, and private places like your keychain, `.ssh` and cloud
  credentials. It explains why in plain words.
- **Checking things:** the launcher window's status line shows whether
  Docker is running (with "Open Docker Desktop", and on Windows the one-time
  fix when Windows blocks Docker's virtual machine) and whether the key is
  saved ("Replace key…"); `um-codex doctor` checks Docker, the key and the
  Toolkit and says what's wrong.
- **Installing:** one command pasted into Terminal (Mac) or Windows
  PowerShell, from the README; it needs no options. It sets up Docker
  Desktop if needed, UM-Codex, the key, and the app (Mac: Applications and a
  Desktop shortcut; Windows: Start menu and Desktop).
- **Updates:** `um-codex update` installs the newest version beside the one
  you have, only if it's signed by the UM-Codex release key, and never
  while Codex is open; the version before is kept, and
  `um-codex update --rollback` goes back to it. About once a day UM-Codex
  checks for a new version, and the launcher window (or a terminal launch)
  says when one is out. Updates don't touch
  your folders, setups or Codex history.

- **The Codex app** (Mac only, for now). A setup can open in Codex's
  desktop app instead of a terminal; the work still happens in the sealed
  environment with the same folders, internet setting and key protection.
  UM-Codex opens its own copy of the app, with its own settings, beside the
  person's normal one; it needs no sign-in, and the person's own app isn't
  changed. The app reaches the environment through ssh, so the first time
  UM-Codex asks to add one line to the person's ssh settings (with a backup;
  uninstalling takes it out). UM-Codex prepares its copy, so it opens on a
  project named after the setup, already connected; the launcher says
  "Connected" when the app is in. (Only if the copy was already open does the
  launcher show a few steps instead.) Chats run in the
  environment only when they show "Remote · umcodex-…". Other (local) chats
  in that window would run on the person's computer, so UM-Codex blocks
  them: they answer only "This UM-Codex window only works in Remote chats.
  Start a chat on Remote · umcodex-… (its project in the sidebar). Local
  chats would run on your Mac, outside the sandbox." The person's own ChatGPT app also lists
  the `umcodex-*` hosts in its Connections (it reads the same ssh settings);
  they can stay off there. The app's own browser is on the person's computer
  too; the Browser tool is the one inside the environment. The setup runs
  until Stop in the launcher.

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
- Footage of the launcher window and of Codex's own screen are the main
  visuals; the summary before Start is worth a pause. Use a demo folder
  with a short path (the page shows full paths).

## Not built yet (leave out until it is)

- "On this computer" mode, the person's own browser, computer control
  (M4; computer control depends on a spike).
- The Codex app on Windows.
- An install website; until then the README has the commands.
- In the Codex app: that a later launch reconnects with no steps isn't
  checked yet (DESIGN.md M6); say it only once it is.
