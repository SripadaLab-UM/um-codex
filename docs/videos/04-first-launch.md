# Walkthrough: Your first launch

Status: **draft for review.**

| | |
|---|---|
| Subtitle | Choose a folder, and Codex opens on it |
| Length | About 3:30 |
| For | Anyone who has installed UM-Codex and is opening it for the first time |
| Closing line | More folders, and the internet switch: Edit, on each card |
| Sources | The launcher window, filmed live on a demo data folder (release v0.1.0-alpha.4); the Mac's folder picker and UM-Codex's own copy of the Codex app, screen-recorded, cropped to their own windows. A demo folder of made-up files ("UM-Codex demo": a CSV and a short README). |

## Rules for this video

- Only UM-Codex's own copy of the Codex app is filmed, never the maintainer's own
  ChatGPT or Codex app, or their chats.
- The demo folder holds made-up files only. No real data, names or emails.
- The Toolkit key is never shown: it is already saved, so the page never asks.
- The narration says "the University of Michigan's GPT Toolkit", never "U-M".
- Not shown: "On this computer" mode, the Codex app on Windows, the browser tool
  (video 5), and a later start reconnecting by itself (not checked yet).

## Script and storyboard

---

### Chapter 1: This video covers

**Shot 1.1**

- **Visual:** The title and agenda.
  - agenda · Open UM-Codex · "open its window"
  - agenda · Choose a folder · "choose a folder"
  - agenda · Ask Codex · "ask Codex to do"
  - agenda · Stop, and start again · "stop and start again"
- **Narration:**
  > This video is a first walk through UM-Codex. You'll open its window,
  > choose a folder, and watch Codex open on it. Then you'll ask Codex to do
  > something, and stop and start again.

---

### Chapter 2: Open UM-Codex and choose a folder

**Shot 2.1**

- **Visual (launcher, filmed):** The first screen.
  - `status` · "Docker is running" · Docker running, key saved
  - `start` · "Choose a folder and start" · One button
  - `help` · "your real files" · What Codex can do
- **Narration:**
  > Open UM-Codex from your Desktop, and its window opens in your browser.
  > Docker is running and your key is saved. The first time, there's one
  > button: Choose a folder and start. Under it is what Codex gets. It can
  > change and delete files in that folder: they're your real files, with
  > no undo. And the internet is on, so Codex could send what it reads
  > anywhere. You can change any of that later.

**Shot 2.2**

- **Visual (the Mac's folder picker, recorded):** The picker; the demo folder chosen.
  - `picker` · "your Mac's own folder picker" · The folder picker
- **Narration:**
  > Press it, and choose a folder in your Mac's own folder picker. For this
  > video, it's a demo folder of made-up files. For anything important,
  > work in a copy, or in a folder that's a git repository.

---

### Chapter 3: Codex opens

**Shot 3.1**

- **Visual (launcher, filmed):** The setup's card; its line goes Starting, Opening Codex, Connected.
  - `card` · "named after it" · Your folder, as a setup
  - `line` · "Connected" · Starting, Opening Codex, Connected
- **Narration:**
  > That's all you do. The folder is now a setup, a card named after it.
  > Its line goes from Starting, to Opening Codex, to Connected. UM-Codex
  > opens its own copy of the Codex app, with its own settings. Your own
  > ChatGPT app isn't touched.

**Shot 3.2**

- **Visual (UM-Codex's Codex app, recorded):** The window opening on the project.
  - `remote` · "it says Remote" · Remote · umcodex-…
- **Narration:**
  > Codex opens on a project named after your folder. At the bottom, it
  > says Remote, and the setup's name. That chat is running in the sealed
  > environment on your Mac. A chat that doesn't say Remote would run on
  > your Mac itself, so UM-Codex blocks it.

**Shot 3.3**

- **Visual (Codex app, recorded):** A request typed; Codex works; the answer. Sped up while it works.
- **Narration:**
  > Now ask Codex for something in the folder. Here, it summarizes the
  > spreadsheet and writes a short note about it. Codex works inside the
  > sealed environment, and the note lands in your real folder.

**Shot 3.4**

- **Visual (launcher, filmed):** The card's facts.
  - `facts` · "the card" · What this setup gives Codex
- **Narration:**
  > Back in the window, the card always says what Codex can do with this
  > setup: the folder, and that changes there are real; the internet; and
  > the model it's using.

---

### Chapter 4: Stop, and start again

**Shot 4.1**

- **Visual (launcher, filmed):** Stop; the question; Stop.
  - `stop` · "press Stop" · Stop
  - `dialog` · "It asks first" · What Stop does
  - `none` · "its history is kept"
- **Narration:**
  > When you're finished, press Stop. It asks first. Codex stops and its
  > sandbox is removed. Files it already changed in your folder stay as they
  > are, and its history is kept. The Codex app then says it can't
  > reconnect. That's expected.

**Shot 4.2**

- **Visual (launcher, filmed):** The Start button, named after the folder; then Edit's three sections.
  - `startlast` · "the button at the top" · Start "UM-Codex demo"
  - `sec1` · "Folder" · Folder
  - `sec2` · "Access" · Access
  - `sec3` · "Codex" · Codex
- **Narration:**
  > Next time, the button at the top is Start, with your folder's name. One
  > click. Edit shows three sections: Folder, Access and Codex. That's where
  > you add a folder Codex can only read, or turn the internet off.

**Shot 4.3**

- **Visual:** The end card.
- **Narration:**
  > That's your first launch.
