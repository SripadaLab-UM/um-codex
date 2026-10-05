# Where the app differed from NOTES.md

From recording "Installing on a Mac" and "Your first launch" on 2026-10-02, from
the released v0.1.0-alpha.4 (the installer's own download), on macOS with
Docker Desktop and the ChatGPT desktop app installed. Each item says what the
screen showed; fix NOTES.md (or the app) as you judge.

## The installer

1. **Six steps, not seven.** `1/6 Docker Desktop`, `2/6 uv`, `3/6 UM-Codex`,
   `4/6 Container images`, `5/6 Toolkit key`, `6/6 Launcher`, then `Done`.
   (DataLab's installer has seven; NOTES.md's install section doesn't count
   them, but the DataLab script it points to does.)
2. **After an uninstall the install downloads the images again** (about 35 s
   here) and **asks for the key**: the Keychain item was gone, and
   `um-codex uninstall --help` says it removes "containers, key, images and
   data". NOTES.md's recording note ("keeps saved setups unless
   `--delete-data`") is true of the setups, but a "clean install" also means a
   key prompt and a long image download. The Mac install video keeps the
   key off camera by skipping it with Enter and drawing the typing as a labelled
   illustration.
3. **The key prompt says "container"** ("never goes into the container"), and
   "U-M GPT Toolkit". The narration says "sealed environment" and "the
   University of Michigan's GPT Toolkit", as NOTES.md asks; the screen can't
   be changed by narration, so the words differ.
4. **The installer ends with two questions** ("Show UM-Codex in Finder?
   [Y/n]", "Open UM-Codex now? [Y/n]"); NOTES.md doesn't mention them. They
   were answered `n` for the recording. With the Codex app's ssh line already
   present, step 6 prints "The Codex app's line in ~/.ssh/config is there
   already." and asks nothing, so the "Add that line now? [Y/n]" question was
   not recorded (it belongs to the Codex-app video).

## The launcher window

5. **The card's line, once connected,** reads "Connected ✓ The Codex app is
   working in the sandbox (umcodex-um-codex-demo-acecf5_327ae834)." (the
   host name is on it), and the big line at the top repeats it as
   `"UM-Codex demo": Connected ✓ …`. While opening it says "Opening Codex…
   waiting for the Codex app to connect." with an "It doesn't connect: show
   the steps" link. NOTES.md says only "Starting… → Opening Codex… →
   Connected ✓". The first start took about 16 s from the card appearing to
   Connected.
6. **The first-run screen** has a second link, "Choose options first…", under
   the explanation. The explanation reads "Codex starts in the Codex app,
   working in the folder you choose. Codex can change and delete files there:
   your real files, no undo." then "Internet on: …". Matches NOTES.md; the link
   isn't mentioned.
7. **The folder picker opens where it was last used,** not at a fixed place:
   on this Mac, inside Documents, showing the folder names there. The
   recording points the picker at the demo folder through the page (a one-line
   patch in `footage/film-first-launch.mjs`); the app itself doesn't do that.
   People will see their own folders in the picker.
8. **Stop's question** matches NOTES.md: "Stop “UM-Codex demo”? Codex stops and
   its sandbox is removed. Files it already changed in your folders stay as they
   are; its history is kept. The Codex app then says it can't reconnect to
   umcodex-…; that's expected. Start the setup again to go on." After Stop the
   card's button returns to "Start" and the hero becomes `Start "UM-Codex demo"`.
9. **Edit** has three sections as written (Folder, Access, Codex), plus a
   "What Codex gets" summary box and three buttons at the bottom: "Save and
   start", "Save", "Cancel". "Open in" offers Terminal and Codex app. The
   Browser tool switch sits under Internet (off by default).

## UM-Codex's own copy of the Codex app

10. **The copy's menu bar says "ChatGPT"**, not UM-Codex (it is the ChatGPT app
    with its own data folder). NOTES.md says "a second ChatGPT icon in the Dock":
    consistent, but worth saying on camera.
11. **"Remote · umcodex-…" is not one label.** The composer shows chips:
    the project ("UM-Codex demo"), "Remote", and, at the right with a green dot,
    "umcodex-um-codex-de…" (cut off). The launcher's own wording
    ("Use chats that show Remote · umcodex-…") reads as one label. The
    narration says "it says Remote, and the setup's name".
12. **The copy shows the ChatGPT app's own banner** "Full access is on:
    ChatGPT can edit any file and run commands with internet access without
    your approval…". Inside UM-Codex that is true only within the sandbox and
    the chosen folders; the banner doesn't say so, and a viewer may read it as
    "Codex can edit any file on my Mac". Not mentioned in NOTES.md; consider
    either a line in the narration of a later video or hiding the banner in the
    copy.
13. **Stop → "Couldn't reconnect to umcodex-um-codex-demo-…" with a Reconnect
    button** and a red dot on the project: as NOTES.md says.
14. **Codex's work:** it read `/work/plant-growth.csv` (the demo folder is
    `/work` inside the sandbox), ran Python, and wrote `summary.md` in the real
    folder in about 25 s ("Edited summary.md +5 −0", "View changes").
    The model shown is "5.6 Terra Medium".

## Not checked

- A later start reconnecting by itself (NOTES.md: not yet checked).
- The browser tool, the update strip, a second ChatGPT icon in the Dock.

## Recording notes

- The footage of the launcher is a headless Chrome capture of a demo data
  folder (`UMCODEX_DATA_DIR=~/Library/Application Support/UM-Codex-demo`), so the
  real setups were never on screen. The desktop parts are crops of a
  full-screen recording (the picker dialog, with its left column blurred, and
  UM-Codex's own Codex window). The full-screen recording, which also holds
  other windows, is not in the repository.
- The demo folder is `~/Demo/UM-Codex demo`, not `~/Documents/UM-Codex demo`:
  the picker shows the parent folder's listing, and Documents holds other
  things.

## Re-recorded on v0.1.0-alpha.7 (2026-10-05)

The launcher screens were re-filmed on alpha.7 (the installer steps and the
Codex window are unchanged, so those takes were kept). What the screen showed:

15. **First run:** a "Get started" list: the lead "UM-Codex runs Codex on the U-M
    GPT Toolkit in a sandbox: Codex sees only the folders you give it.", then
    "Toolkit key saved ✓", "Docker is running ✓", and "3 Make your first setup"
    with the explanation and a **New setup…** button. The strip under the title
    ("Docker running", "Toolkit key saved", the version) is still there.
16. **New setup form:** titled "New setup", with a primary **Choose folder…**
    button under Folder, the defaults already set (Internet on, Browser tool off,
    the newest model, Open in: Codex app), "What Codex gets" at the bottom
    ("FOLDER No folder yet" until one is chosen), and **Save and start**, **Save**,
    **Cancel**. The picker opens where it was last used unless told otherwise
    (the recording starts it inside the demo folder).
17. **The card:** one **Start**/**Stop** at its top right; one summary line
    (`~/Demo/UM-Codex demo · Codex app · Internet on · gpt-5.6-terra`); the status
    line ("Starting…", "Opening Codex… waiting for the Codex app to connect.",
    "Connected ✓ The Codex app is working in the sandbox (umcodex-…)"); a
    collapsed **What Codex can do here** (Folder, Access, Codex, as before); and
    **Edit**, **Rename**, **Duplicate**, **Delete** as small links at the bottom.
    The "Last used" tag only shows when there is more than one setup. After the
    first start in a fresh data folder, Connected came about 26 s after the card
    appeared (16 s on alpha.4 in the earlier recording).
18. **"Your setups"** has **New setup…** beside the heading, and one line:
    "Each setup is a folder for Codex to work in. Start one to open Codex there."
19. **More options** in the Edit form has a new field, **Where Codex runs**:
    "In the sandbox (recommended)" or "On this computer (experimental)". The
    settings video names it in one sentence, says there is no sandbox around the
    experimental option and that it asks first, and does not demonstrate it.
20. **Stop's question** is unchanged. The Stop button is the card's own, at its
    top right.
