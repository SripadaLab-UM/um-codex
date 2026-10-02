# Walkthrough: What each setting means

Status: **draft for review.**

| | |
|---|---|
| Subtitle | The Edit page, setting by setting |
| Length | About 3:00 |
| For | Anyone who has started Codex once and wants to change what it can see and do |
| Closing line | Change any of it later, with Edit |
| Sources | The launcher window, filmed live on a demo data folder (release v0.1.0-alpha.4), nothing saved. The folder shown under More folders is a second demo folder of made-up files, chosen without opening the Mac's picker (it was shown in "Your first launch"). |

## Rules for this video

- Launcher only: no Codex window, no desktop.
- The words on screen are the app's own; the narration explains them and
  doesn't contradict them (checked against `ui/static/app.js` at alpha.4).
- Nothing is saved: every change is made in the form and thrown away with Cancel.
- The narration says "the University of Michigan's GPT Toolkit", never "U-M",
  and "sealed environment" or "sandbox" as the screen does, never "safe".
- Not shown: "On this computer" mode (not built), Windows.

## Script and storyboard

---

### Chapter 1: This video covers

**Shot 1.1**

- **Visual:** The title and agenda.
  - agenda · Folder · "First, Folder"
  - agenda · Access · "Then, Access"
  - agenda · Codex · "Then, Codex"
  - agenda · What Codex gets · "the box that sums it all up"
- **Narration:**
  > This video goes through the settings of a UM-Codex setup, one at a time,
  > and what each one means. First, Folder. Then, Access. Then, Codex. And
  > last, the box that sums it all up.

---

### Chapter 2: Opening the settings

**Shot 2.1**

- **Visual (launcher):** The setup's card; Edit pressed; the whole page.
  - `editbtn` · "Press Edit" · Edit
  - `sections` · "three sections" · Folder, Access, Codex
- **Narration:**
  > Press Edit on a setup's card to see them. For a new setup, press New
  > setup with options instead. It's all on one page, in three sections, and
  > nothing changes until you press Save.

---

### Chapter 3: Folder

**Shot 3.1**

- **Visual (launcher):** The working folder.
  - `working` · "the working folder" · Working folder
- **Narration:**
  > Under Folder, the working folder is where Codex starts. It can read,
  > change and delete files there. They're your real files, with no undo, so
  > use a copy, or a folder that's a git repository, for anything important.
  > Change opens your Mac's folder picker.

**Shot 3.2**

- **Visual (launcher):** Add a folder; the chip appears Read only; switched to Read & write and back.
  - `more` · "More folders" · More folders
  - `chip` · "Read only means" · Read only
  - `chip` · "Read and write means" · Read & write
- **Narration:**
  > More folders lets you add others. Each one is either Read only or Read
  > and write. Read only means Codex can look but not change, even with
  > administrator rights inside the sandbox. Read and write means it can
  > change and delete there too.

---

### Chapter 4: Access

**Shot 4.1**

- **Visual (launcher):** Internet switched off, then on; the summary changes.
  - `internet` · "Internet decides" · Internet
  - `summary` · "Off means" · What Codex gets
- **Narration:**
  > Under Access, Internet decides what Codex can reach. On means the whole
  > internet, and also programs on this computer and your local network or
  > VPN. Off means Codex can reach only the model: no downloads, no
  > installs, no websites.

**Shot 4.2**

- **Visual (launcher):** Browser tool switched on; Approve each browser action appears; internet off hides both.
  - `browser` · "Browser tool" · Browser tool
  - `asks` · "Approve each browser action is on" · Approve each browser action
- **Narration:**
  > With the internet on, there's a Browser tool. It's off until you turn it
  > on. It gives Codex a fresh browser inside the sandbox, with none of your
  > logins. When it's on, Approve each browser action is on too: Codex stops
  > and asks before it opens a page, clicks, or types. Reading a page doesn't
  > ask. Turn the internet off, and the Browser tool goes away, because it
  > needs the internet.

---

### Chapter 5: Codex

**Shot 5.1**

- **Visual (launcher):** Model; Open in.
  - `model` · "Model is" · Model
  - `openin` · "Open in is" · Open in
- **Narration:**
  > Under Codex, Model is the model Codex uses, newest first, with the
  > setup's own selected. A new setup starts on gpt-5.6-terra. Open in is
  > where Codex opens: in the Codex app, on a Mac that has it, or in a
  > Terminal window.

**Shot 5.2**

- **Visual (launcher):** More options opened; Ask before commands on, then off; the Name field.
  - `ask` · "Ask before commands is off" · Ask before commands
  - `name` · "Name is" · Name
- **Narration:**
  > Under More options, Ask before commands is off by default: Codex runs
  > commands without asking, and the sandbox is what keeps it in. Turn it
  > on, and Codex asks first. Name is what the card, and the project in the
  > Codex app, are called.

---

### Chapter 6: What Codex gets

**Shot 6.1**

- **Visual (launcher):** The summary box; Save and start; Cancel.
  - `summary` · "What Codex gets sums up" · What Codex gets
  - `save` · "Save and start" · Save and start
- **Narration:**
  > At the bottom, What Codex gets sums up your choices in plain words, and
  > changes as you do. Your Toolkit key stays on this computer: the sandbox
  > never sees it. Then press Save and start, or just Save. If the setup is
  > already running, changes apply the next time it starts.

**Shot 6.2**

- **Visual:** The end card.
- **Narration:**
  > That's every setting. You can change any of them later, with Edit.
