# Walkthrough: Installing on a Mac

Status: **draft for review.**

| | |
|---|---|
| Subtitle | One command, then the app on your Desktop |
| Length | About 3:00 |
| For | Anyone installing UM-Codex on a Mac for the first time |
| Closing line | Next: Your first launch |
| Command | `curl -q -fsSL https://github.com/SripadaLab-UM/um-codex/releases/latest/download/install-macos.sh \| sh` |
| Sources | The Desktop on a Mac, recorded (a crop with only the shortcut in it); Terminal is drawn from a recording of the real installer (release v0.1.0-alpha.4, the user's name in paths shown as "you"); the launcher window, filmed live. One moment is a labelled illustration: typing the key at its prompt (keys are never typed on camera). |

## Rules for this video

- The installer's words are its own: the terminal view replays a real run.
- The Toolkit key never appears. The narration says where it goes, not what it is.
- "Docker" is named only where it is on screen (Docker Desktop, step one).
- The narration says "the University of Michigan's GPT Toolkit", never "U-M".
- Not shown: the Codex app's ssh question (it is for the "Opening a setup in the
  Codex app" video), and Windows.

## Script and storyboard

---

### Chapter 1: This video covers

**Shot 1.1**

- **Visual:** The title and agenda.
  - agenda · Before you start · "what to have ready"
  - agenda · Run the install command · "the one command"
  - agenda · Docker and your key · "Docker Desktop and your key"
  - agenda · Open UM-Codex · "how to open UM-Codex"
- **Narration:**
  > This video shows how to install UM-Codex on a Mac. First, what to have
  > ready. Then, the one command that installs it. Then, Docker Desktop and
  > your key. And last, how to open UM-Codex.

---

### Chapter 2: Before you start

**Shot 2.1**

- **Visual (drawn card):** Three things to have ready.
  - cardtitle · "Have ready"
  - card · A Mac · "You need a Mac"
  - card · Your Toolkit API key, in Aman's email · "your key for the University of Michigan's GPT Toolkit"
  - card · Docker Desktop · "Docker Desktop"
- **Narration:**
  > UM-Codex runs Codex in a sealed environment on your own computer. You
  > need a Mac, your key for the University of Michigan's GPT Toolkit, which
  > is in Aman's email, shared on Dropbox, and Docker Desktop, which runs the
  > sealed environment. If Docker Desktop isn't installed, setup offers to
  > install it.

---

### Chapter 3: Run the install command

**Shot 3.1**

- **Visual (drawn card):** Two ways to open Terminal.
  - cardtitle · "Open Terminal"
  - card · Command and Space, then type Terminal · "Press Command and Space"
  - card · Or: Applications, then Utilities · "under Utilities"
- **Narration:**
  > Open Terminal. Press Command and Space, type Terminal, and press
  > Return. It's also in Applications, under Utilities.

---

**Shot 3.2**

- **Visual (Terminal, drawn from the real run):** The command pasted and run; the first lines.
  - term · "" · "1/6 Docker Desktop"
- **Narration:**
  > Paste the install command from UM-Codex's page on GitHub, and press
  > Return. It works through six steps, and each one says what it's doing.

---

### Chapter 4: Docker and your key

**Shot 4.1**

- **Visual (Terminal):** Step 1.
  - term · "" · "Docker Desktop is running."
- **Narration:**
  > Step one is Docker Desktop. On this Mac it's already installed and
  > running. On a Mac without Docker, the installer asks first, then
  > downloads and installs it.

**Shot 4.2**

- **Visual (Terminal):** Steps 2 to 4.
  - term · "" · "5/6 Toolkit key"
- **Narration:**
  > Steps two to four install UM-Codex itself, with its own copy of Python,
  > and download the sealed environment's image. The download is the long
  > part, the first time.

**Shot 4.3**

- **Visual (Terminal, then a labelled illustration of typing):** Step 5's prompt; stars appear as a key is pasted.
  - term · "" · "Toolkit API key:"
  - typed · "****************************************"
  - typed · "The Toolkit accepted the key."
  - typed · "Saved in the keychain."
- **Narration:**
  > Step five asks for your key. Copy it from Aman's email, paste it, and press Return. Each character
  > shows as a star, and the key is saved in your Mac's Keychain. It never
  > goes into the sealed environment, and it isn't kept in any file.

**Shot 4.4**

- **Visual (Terminal):** Step 6 and Done.
  - term · "6/6 Launcher" · "Or, in any Terminal window"
- **Narration:**
  > Step six adds the UM-Codex app to Applications, and a shortcut to your
  > Desktop. If you have the Codex app, setup may also ask one question
  > about it. It gives the reason, and Return means yes. Then it's done.

---

### Chapter 5: Open UM-Codex

**Shot 5.1**

- **Visual (the Desktop, real):** The UM-Codex shortcut setup added.
  - `icon` · "the UM-Codex icon" · Double-click to open
  - `none` · "Spotlight finds it"
- **Narration:**
  > To open UM-Codex, double-click the UM-Codex icon on your Desktop. It's
  > also in Applications, and Spotlight finds it.

**Shot 5.2**

- **Visual (the launcher window):** The first screen, then the status line.
  - `window` · "UM-Codex's window" · UM-Codex
  - `status` · "The line at the top" · Docker running, key saved
- **Narration:**
  > It opens UM-Codex's window in your browser. That's a page running on
  > your own Mac, not a website. The line at the top says Docker is running
  > and your key is saved.

**Shot 5.3**

- **Visual:** The end card.
- **Narration:**
  > That's UM-Codex installed. In the next video, Your first launch, you
  > start Codex in a folder.
