# Videos

Companion videos for people installing and using UM-Codex, made the way
DataLab's are (its `docs/videos/` has the long version of this page): a
script, Amazon Polly narration, an animation page, and Chrome plus `ffmpeg`.
[NOTES.md](NOTES.md) says what to say and what to leave out;
[RECORDING-FINDINGS.md](RECORDING-FINDINGS.md) lists where the app differed
from it when these were recorded.

| Video | Script |
|---|---|
| Installing on a Mac | [02-installing-on-a-mac.md](02-installing-on-a-mac.md) |
| Your first launch | [04-first-launch.md](04-first-launch.md) |
| What each setting means | [05-launcher-settings.md](05-launcher-settings.md) |

The narration is sent to Amazon Polly and the videos are public: the screen
shows only a demo folder of made-up files, and the Toolkit key is never shown
or typed on camera.

## How a video is made

1. **Script** (`NN-name.md`): the narration is the `> ` lines under each
   `**Shot X.Y**`; the cues under it (`agenda`, `card`, `term`, `typed`, and
   `` `id` · "phrase" · label `` for a spotlight) say what to show when each
   phrase is spoken. The phrase must be spoken in that shot, word for word.
2. **Narration:** `python3 scripts/narrate-video.py docs/videos/NN-name.md --voice Ruth`
   writes `build/NN-name/` (MP3 per shot, `narration.wav`, `timing.json`,
   `captions.srt`). Uses the AWS CLI's configured profile.
3. **Takes** (in `build/NN-name/takes/`, listed in `takes.json` with the
   spotlight rectangles): see below.
4. **Render:** `npm install` once in this folder, then
   `node render.mjs NN-name` (`--stills 10,60` for single frames). It drives
   the installed Google Chrome frame by frame and encodes with `ffmpeg`.
5. **Publish:** `build/` is not in git; everything in it can be made again.

## Filming

**The installer's terminal** is drawn from a recording of the real installer:
run it under `script -r` on a pty (answering its questions), then
`python3 terminal-rec.py NN-name rec` writes `build/NN-name/terminal.json`
(docker's in-place progress bars are dropped, the timing kept). The key step
runs for real and is skipped with Enter; typing it is a labelled illustration.

**The launcher window** is filmed headless, on a demo data folder, so real
setups are never on screen:

```bash
UMCODEX_DATA_DIR="$HOME/Library/Application Support/UM-Codex-demo" um-codex ui --no-browser
FILM_SIGN_IN=<the link it prints> FILM_START="$HOME/Demo/UM-Codex demo" \
  FILM_DIR=<scratch> node footage/film-first-launch.mjs
```

It films the page in one continuous take (the "Choose a folder and start…"
click opens the Mac's real folder picker; the script waits for the card to
connect, then for a file named `stop-now` in `FILM_DIR`, and goes on with
Stop, Start and Edit). Meanwhile a full-screen recording
(`ffmpeg -f avfoundation -i "1:none"`) catches the picker and UM-Codex's own
Codex window; the picker is answered with an Accessibility press on its Choose
button (it belongs to a background process that ignores synthetic clicks).
`footage/film-edit.mjs` films the Edit form whole, in a tall window.
`python3 footage/cut-first-launch.py <scratch>` then cuts all of it into the
takes, blurring the picker's left column. Its cut points were read off
contact sheets of one run: check them again after a new filming.

Keep the demo folder's parent free of anything else (the picker shows it), and
keep the full-screen recording out of the repository: it holds the whole desktop.
