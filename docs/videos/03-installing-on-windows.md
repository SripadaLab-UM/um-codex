# Walkthrough: Installing on Windows

Status: **draft for review.**

| | |
|---|---|
| Subtitle | One command, then the app on your Desktop |
| Length | About 3:30 |
| For | Anyone installing UM-Codex on a Windows computer for the first time |
| Closing line | Next: Your first launch on Windows |
| Command | `[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; irm https://github.com/SripadaLab-UM/um-codex/releases/latest/download/install-windows.ps1 \| iex` |
| Sources | Windows PowerShell is drawn from a recording of the real installer (release v0.1.0-alpha.4, the user's name in paths shown as "you"; this computer already had a key saved, so the run shows "kept" and step 6's prompt is drawn); the Desktop and the Start menu on a Windows computer, recorded (cropped to the shortcut, other results blurred); the launcher window, filmed live. Three things are labelled illustrations, drawn in the installer's own words: the administrator step and restart (this computer already has Docker Desktop), the fix for Docker's virtual machine, and typing the key at its prompt (keys are never typed on camera). |

## Rules for this video

- The installer's words are its own: the terminal view replays a real run.
- The Toolkit key never appears. The narration says where it goes, not what it is.
- "Docker" is named only where it is on screen (Docker Desktop, step one).
- The narration says "the University of Michigan's GPT Toolkit", never "U-M".
- Not shown: the Codex app (not built for Windows yet), and Mac.

## Script and storyboard

---

### Chapter 1: This video covers

**Shot 1.1**

- **Visual:** The title and agenda.
  - agenda · Before you start · "what to have ready"
  - agenda · Run the install command · "the one command"
  - agenda · Docker, the administrator step, and your key · "Docker Desktop, the administrator step, and your key"
  - agenda · Open UM-Codex · "how to open UM-Codex"
- **Narration:**
  > This video shows how to install UM-Codex on a Windows computer. First,
  > what to have ready. Then, the one command that installs it. Then, Docker
  > Desktop, the administrator step, and your key. And last, how to open
  > UM-Codex.

---

### Chapter 2: Before you start

**Shot 2.1**

- **Visual (drawn card):** Three things to have ready.
  - cardtitle · "Have ready"
  - card · A Windows computer · "a Windows computer"
  - card · Your Toolkit API key, in Aman's email · "your key for the University of Michigan's GPT Toolkit"
  - card · Docker Desktop · "Docker Desktop"
- **Narration:**
  > UM-Codex runs Codex in a sealed environment on your own computer. You
  > need a Windows computer, your key for the University of Michigan's GPT
  > Toolkit, which is in Aman's email, shared on Dropbox, and Docker Desktop,
  > which runs the sealed environment. If Docker Desktop isn't installed,
  > setup installs it for you.

**Shot 2.2**

- **Visual (drawn card):** Temporary administrator access, in the installer's words.
  - cardtitle · "Michigan Medicine computers"
  - card · Request temporary administrator access first · "request temporary administrator access"
  - card · It is turned on from your profile page · "your profile page"
  - card · Give it at least 30 minutes · "at least thirty minutes"
- **Narration:**
  > Installing Docker Desktop needs administrator permission, just once. On a
  > Michigan Medicine computer, you request temporary administrator access
  > first. It's turned on from your profile page, under administrator access.
  > Give it at least thirty minutes.

---

### Chapter 3: Run the install command

**Shot 3.1**

- **Visual (drawn card):** How to open Windows PowerShell.
  - cardtitle · "Open Windows PowerShell"
  - card · Start menu, type PowerShell · "type PowerShell"
  - card · Press Enter · "press Enter"
  - card · The ordinary way, not as administrator · "not as administrator"
- **Narration:**
  > Open the Start menu, type PowerShell, and press Enter. Open it the
  > ordinary way, not as administrator. The installer asks for administrator
  > permission itself, only if it needs it.

---

**Shot 3.2**

- **Visual (Windows PowerShell, drawn from the real run):** The command pasted and run; the first lines.
  - term · "" · "Step 1 of 7"
- **Narration:**
  > Paste the install command from UM-Codex's page on GitHub, and press
  > Enter. It's one command. It works through seven steps, and each one says
  > what it's doing.

---

### Chapter 4: Docker, the administrator step, and your key

**Shot 4.1**

- **Visual (PowerShell):** Step 1.
  - term · "" · "WSL and Docker Desktop are ready."
- **Narration:**
  > Step one gets Windows ready. Docker Desktop needs a Windows feature
  > called WSL. On this computer, WSL and Docker Desktop are already there,
  > so it moves on.

**Shot 4.2**

- **Visual (drawn card):** What step one does on a computer without them.
  - cardtitle · "If something is missing"
  - card · It lists what it will change, and asks · "lists what it needs to change"
  - card · Windows asks to allow changes: click Yes · "Click Yes"
  - card · A second window does the work: 10 minutes or more · "ten minutes or more"
  - card · Windows restarts; the installer carries on · "carries on by itself after you sign in"
- **Narration:**
  > On a computer without them, step one lists what it needs to change, and
  > asks if you're ready. Windows then shows a box asking to allow changes to
  > your device. Click Yes. A second window does the work, which can take ten
  > minutes or more. Leave it open. Windows then restarts, and the installer
  > carries on by itself after you sign in.

**Shot 4.3**

- **Visual (drawn card):** The fix for Docker's virtual machine, in the installer's words.
  - cardtitle · "If Docker can't start"
  - card · A Windows policy took away a right it needs · "a Windows policy"
  - card · The installer offers: Fix it now? · "fix it now"
  - card · Windows asks for administrator permission once · "administrator permission once"
  - card · Or restart Windows, and run it again · "restart Windows"
- **Narration:**
  > On the Michigan Medicine network, a Windows policy can stop Docker's
  > virtual machine from starting. If that happens, the installer says so, and
  > offers to fix it now. Windows asks for administrator permission once, and
  > the right is given back. Or you can restart Windows, and run the installer
  > again.

**Shot 4.4**

- **Visual (PowerShell):** Steps 2 to 5.
  - term · "" · "Step 6 of 7"
- **Narration:**
  > Step two starts Docker Desktop. Steps three to five install UM-Codex
  > itself, with its own copy of Python, and download the sealed
  > environment's image. The download is the long part, the first time.

**Shot 4.5**

- **Visual (PowerShell, then a labelled illustration of typing):** Step 6's prompt; stars appear as a key is pasted.
  - term · "-" · "-"
  - typed · "   Paste your Toolkit API key (see ITS's 'Codex Setup' articles for how to get one)."
  - typed · "   It's kept in Windows Credential Manager and never goes into the container."
  - typed · "   Toolkit API key: ****************************************"
  - typed · "The Toolkit accepted the key."
  - typed · "Saved in the keychain."
- **Narration:**
  > Step six asks for your key. Copy it from Aman's email, paste it, and
  > press Enter. Each character shows as a star, and the key is saved in
  > Windows Credential Manager. It never goes into the sealed environment,
  > and it isn't kept in any file.

**Shot 4.6**

- **Visual (PowerShell):** Step 7 and the end.
  - term · "Step 7 of 7" · "To remove it later"
- **Narration:**
  > Step seven adds UM-Codex to your Start menu, and a shortcut to your
  > Desktop. Then it's done, and it tells you how to open it.

---

### Chapter 5: Open UM-Codex

**Shot 5.1**

- **Visual (the Desktop and the Start menu, real):** The UM-Codex shortcut setup added.
  - `icon` · "the UM-Codex icon" · Double-click to open
  - `none` · "the Start menu"
- **Narration:**
  > To open UM-Codex, double-click the UM-Codex icon on your Desktop. You
  > can also open the Start menu, and type UM-Codex.

**Shot 5.2**

- **Visual (the launcher window):** The first screen, then the status line.
  - `window` · "UM-Codex's window" · UM-Codex
  - `status` · "The line at the top" · Docker running, key saved
- **Narration:**
  > It opens UM-Codex's window in your browser. That's a page running on
  > your own computer, not a website. The line at the top says Docker is
  > running and your key is saved.

**Shot 5.3**

- **Visual:** The end card.
- **Narration:**
  > That's UM-Codex installed. In the next video, Your first launch on
  > Windows, you start Codex in a folder.
