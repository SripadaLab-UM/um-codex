# Walkthrough: Your first launch on Windows

Status: **draft for review** (rewritten for the alpha.7 launcher).

| | |
|---|---|
| Subtitle | A setup, where Codex runs, and your first request |
| Length | About 6:30 |
| For | Anyone who has installed UM-Codex on Windows and is opening it for the first time |
| Closing line | Next: the same window on a Mac, and what each setting means |
| Sources | The launcher window, filmed live on a demo data folder (release v0.1.0-alpha.7); Windows' folder dialog and UM-Codex's own copy of the Codex app, screen-recorded and cropped to their own windows. A demo folder of made-up files ("UM-Codex demo": a CSV and a short README). |

## Rules for this video

- Only UM-Codex's own copy of the Codex app is filmed, never anyone's own ChatGPT or
  Codex app, or their chats.
- The demo folder holds made-up files only. No real data, names or emails.
- The Toolkit key is never shown: it is already saved, so the page never asks.
- The narration says "the University of Michigan's GPT Toolkit", never "U-M". It says
  "sealed environment" for the container, and says that the screen calls it "the sandbox".
- "On this computer" is explained but not filmed running: on Windows its option is greyed
  out ("works with the Codex app on a Mac only, for now"). Its description is the
  launcher's own caution (this_computer.WARNING), in words that fit Windows.

## Script and storyboard

---

### Chapter 1: This video covers

**Shot 1.1**

- **Visual:** The title and agenda.
  - agenda · Open UM-Codex · "open its window"
  - agenda · Make a setup · "make a setup"
  - agenda · Where Codex runs · "where Codex runs"
  - agenda · Start, and ask Codex · "ask Codex to do something"
  - agenda · Stop, and start again · "stop and start again"
- **Narration:**
  > This video is a first walk through UM-Codex on Windows. You'll open its
  > window, make a setup, and see every choice in it, including where Codex
  > runs. Then you'll start Codex, ask Codex to do something, and stop and
  > start again.

---

### Chapter 2: Open UM-Codex

**Shot 2.1**

- **Visual (launcher, filmed):** The first screen.
  - `status` · "Docker is running" · Docker running, key saved
  - `steps` · "Get started" · A short list
  - `newsetup` · "Make your first setup" · One button
- **Narration:**
  > Open UM-Codex from your Desktop, and its window opens in your browser.
  > It's a page running on your own computer, not a website. The line at the
  > top says Docker is running and your key is saved. Under it is Get started,
  > a short list: your key is saved, Docker is running, and the last step is
  > Make your first setup. A setup is a folder, plus what Codex may reach and
  > where it runs.

---

### Chapter 3: Make a setup

**Shot 3.1**

- **Visual (launcher, filmed):** The New setup form, Folder.
  - `folderfield` · "working folder" · Where Codex starts
- **Narration:**
  > Press New setup. The first part is Folder. The working folder is where
  > Codex starts. It can read, change and delete files there. They're your
  > real files, with no undo. Under it, you can add more folders, and say for
  > each one whether Codex can only read it, or read and write.

**Shot 3.2**

- **Visual (launcher, filmed):** Access.
  - `internet` · "the internet switch" · Internet
- **Narration:**
  > Access has the internet switch. With it on, Codex can reach the whole
  > internet, so it could send what it can read anywhere, including programs
  > on your computer and your local network. With it off, Codex can reach only
  > the model. Under it is the browser tool, which gives Codex a fresh browser
  > inside the sealed environment, with none of your logins.

**Shot 3.3**

- **Visual (launcher, filmed):** The Codex section.
  - `model` · "the model" · Model
  - `openin` · "where Codex opens" · Terminal, or the Codex app
- **Narration:**
  > Then Codex. Pick the model, newest first. And pick where Codex opens: in
  > a Terminal window, or in the Codex app, which is the default. The Codex app
  > here is UM-Codex's own copy of it, with its own settings. Your own ChatGPT
  > app isn't touched.

**Shot 3.4**

- **Visual (launcher, filmed):** More options.
  - `more` · "More options" · More options
  - `askcmd` · "Ask before commands" · Off, by default
- **Narration:**
  > Under More options, Ask before commands is off by default. Codex then runs
  > commands without asking, and the sealed environment is what keeps it in.
  > Turn it on if you want to approve each command yourself.

**Shot 3.5**

- **Visual (launcher, filmed):** Where Codex runs.
  - `runson` · "Where Codex runs" · Two choices
  - `sandboxopt` · "In the sandbox" · Recommended
- **Narration:**
  > The most important choice is Where Codex runs. The first choice is In the
  > sandbox, which is what the screen calls the sealed environment, and it's
  > the recommended one. Codex works in a sealed environment on your computer.
  > It sees only the folders you gave it. Your Toolkit key stays outside it:
  > a small relay on your computer adds the key to Codex's requests, so
  > nothing Codex runs can read it.

**Shot 3.6**

- **Visual (launcher, filmed):** The second choice.
  - `localopt` · "On this computer" · Experimental
- **Narration:**
  > The second choice is On this computer, and it's experimental. Codex then
  > runs on the computer itself, not in the sealed environment. It can do
  > anything you can do. It can read, change and delete any of your files, use
  > your apps and your browser, and act with your accounts. It might even be
  > able to reach UM-Codex's own key, because it runs as you. Use it only when
  > you need Codex to control the computer or the browser.

**Shot 3.7**

- **Visual (launcher, filmed):** The greyed-out option and its line.
  - `localopt` · "greyed out" · Not available on Windows yet
- **Narration:**
  > On Windows, that choice is greyed out for now. The line under it says it
  > works with the Codex app on a Mac only, for now. So everything in this
  > video runs in the sealed environment.

**Shot 3.8**

- **Visual (launcher, filmed):** What Codex gets, and the buttons.
  - `gets` · "What Codex gets" · The whole setup, in plain words
- **Narration:**
  > At the bottom, What Codex gets says it all in plain words: the folder, the
  > access, and the Codex settings. It ends the same way every time: your
  > Toolkit key stays on this computer, and the sandbox never sees it. Save and
  > start saves the setup and opens Codex. Save only saves it. And Cancel
  > throws it away.

---

### Chapter 4: Start, and ask Codex

**Shot 4.1**

- **Visual (Windows' folder dialog, recorded):** The dialog; the demo folder chosen.
  - `picker` · "Windows' own folder dialog" · Choose folder
- **Narration:**
  > Press Choose folder, and pick a folder in Windows' own folder dialog. For
  > this video, it's a demo folder of made-up files. For anything important,
  > work in a copy, or in a folder that's a git repository. Then press Save
  > and start.

**Shot 4.2**

- **Visual (launcher, filmed):** The setup's card; its line goes Starting, Opening Codex, Connected.
  - `card` · "named after it" · Your folder, as a setup
  - `line` · "Connected" · Starting, Opening Codex, Connected
- **Narration:**
  > That's all you do. The folder is now a setup, a card named after it. Its
  > line goes from Starting, to Opening Codex, to Connected.

**Shot 4.3**

- **Visual (UM-Codex's Codex app, recorded):** The window opening on the project.
  - `remote` · "it says Remote" · Remote, and the sandbox's name
- **Narration:**
  > UM-Codex opens its own copy of the Codex app, in a window of its own, with
  > its own settings. It opens on a project named after your folder. At the
  > bottom, it says Remote, and the sandbox's name, with a green dot. A chat
  > that says Remote runs in the sealed environment. A chat that doesn't would
  > run on your computer itself, so UM-Codex blocks it.

**Shot 4.4**

- **Visual (Codex app, recorded):** The banner "Full access is on".
  - `banner` · "Full access is on" · The app's own banner
- **Narration:**
  > You may see the app's own banner, Full access is on. That's the app's
  > wording. Inside UM-Codex it applies only within the sealed environment and
  > the folders you chose.

**Shot 4.5**

- **Visual (Codex app, recorded):** A request typed; Codex works; the answer. Sped up while it works.
- **Narration:**
  > Now ask Codex for something in the folder. Here, it summarizes the
  > spreadsheet and writes a short note about it. Codex works inside the
  > sealed environment, and the note lands in your real folder. View changes
  > shows exactly what it changed.

**Shot 4.6**

- **Visual (launcher, filmed):** The card's summary line and what Codex can do here.
  - `summary` · "one line" · Where it opens, internet, model
  - `facts` · "What Codex can do here" · The full wording
- **Narration:**
  > Back in the window, the card sums the setup up in one line: where Codex
  > opens, the internet, and the model. Open What Codex can do here for the
  > full wording, the same as in the form.

---

### Chapter 5: Stop, and start again

**Shot 5.1**

- **Visual (launcher, filmed):** Stop; the question; Stop.
  - `startbtn` · "press Stop" · Stop
  - `dialog` · "It asks first" · What Stop does
  - `none` · "its history is kept"
- **Narration:**
  > When you're finished, press Stop. It asks first. Codex stops and its
  > sandbox is removed. Files it already changed in your folder stay as they
  > are, and its history is kept. The Codex app then says it can't reconnect.
  > That's expected.

**Shot 5.2**

- **Visual (launcher, filmed):** The card, stopped; its Start button and its links.
  - `startbtn` · "Start is at the top of the card" · Start
- **Narration:**
  > Next time, Start is at the top of the card. One click. Under the card are
  > four links: Edit, to change the setup, Rename, Duplicate, and Delete,
  > which asks first. At the top of the window, Check for updates and Replace
  > your key are always there.

**Shot 5.3**

- **Visual:** The end card.
- **Narration:**
  > That's your first launch. Next, what each setting means, and the same
  > window on a Mac.
