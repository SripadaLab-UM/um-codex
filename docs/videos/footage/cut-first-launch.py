"""Cuts the raw footage of a first-launch filming into the takes of
04-first-launch (and the launcher shot of 02-installing-on-a-mac).

    python3 footage/cut-first-launch.py <scratch folder with film/ and film2/>

Inputs (kept out of the repo: the screen recording has the whole desktop in it):
  film/launcher.mp4, film/events.json   footage/film-first-launch.mjs
  film/raw.mp4                          a full-screen recording, 1920x1200 points
  film2/edit.mp4, film2/edit-rects.json footage/film-edit.mjs
Only crops of the raw recording are ever used: the folder picker's dialog and
UM-Codex's own Codex window. The picker's left column (the parent folder's
listing) is blurred. The cut points were read off contact sheets of this run
(PICKER, WINDOW, ...): look again after a new filming.

Writes build/<video>/takes/<shot>.mp4 and merges build/<video>/takes.json.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SCRATCH = Path(sys.argv[1])
FILM, FILM2 = SCRATCH / "film", SCRATCH / "film2"
EV = json.loads((FILM / "events.json").read_text())["rects"]
EDIT = json.loads((FILM2 / "edit-rects.json").read_text())["rects"]
PAPER = "0xf6f5f2"


def seconds(stamp):
    h, m, r = stamp.split(":")
    s, ms = r.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def spoken(video, shot, phrase):
    """Seconds after the shot's start that `phrase` is spoken (as the page works it out)."""
    build = HERE / "build" / video
    shots = {s["shot"]: s for s in json.loads((build / "timing.json").read_text())["shots"]}
    s = shots[shot]
    for block in (build / "captions.srt").read_text(encoding="utf-8").strip().split("\n\n"):
        lines = block.split("\n")
        a, b = map(seconds, lines[1].split(" --> "))
        text = " ".join(lines[2:])
        if a < s["start"] - 0.01 or b > s["end"] + 0.01:
            continue
        i = text.find(phrase)
        if i >= 0:
            return a + i / len(text) * (b - a) - s["start"]
    raise SystemExit(f'"{phrase}" not spoken in {shot}')


def run(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True)


ENC = ["-r", "30", "-c:v", "libx264", "-crf", "17", "-g", "10", "-pix_fmt", "yuv420p", "-an"]


def cut(src, parts, out, vf="null", slow=None):
    """Joins the parts [(from, to), ...] of src, filtered, into out.
    slow: {part index: factor}, a part played that many times slower."""
    graph, names = [], []
    for i, (a, b) in enumerate(parts):
        f = (slow or {}).get(i, 1)
        graph.append(f"[0:v]trim={a}:{b},setpts={f}*(PTS-STARTPTS),{vf},fps=30[p{i}]")
        names.append(f"[p{i}]")
    graph.append("".join(names) + f"concat=n={len(parts)}:v=1[v]")
    run("-i", src, "-filter_complex", ";".join(graph), "-map", "[v]", *ENC, out)


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True, check=True)
    return float(r.stdout)


def rects_for(source, ids, parts, slow=None):
    """The sampled rects of `ids` in a take made of `parts` of the source timeline."""
    out, offset = {}, 0.0
    for i, (a, b) in enumerate(parts):
        f = (slow or {}).get(i, 1)
        for rid in ids:
            samples = source.get(rid, [])
            before = [m for m in samples if m["at"] <= a]
            keep = ([before[-1]] if before else []) + [m for m in samples if a < m["at"] <= b]
            for m in keep:
                out.setdefault(rid, []).append({**{k: round(v, 1) for k, v in m.items() if k != "at"},
                                                "at": round(offset + max(0, m["at"] - a) * f, 3)})
        offset += (b - a) * f
    return out


def manifest(video):
    path = HERE / "build" / video / "takes.json"
    return path, json.loads(path.read_text()) if path.exists() else {}


def put(video, shot, parts, vf="null", src=None, ids=(), source=None, ff=None, slow=None, extra=None):
    d = HERE / "build" / video / "takes"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{shot}.mp4"
    cut(str(src or FILM / "launcher.mp4"), parts, out, vf, slow)
    path, takes = manifest(video)
    rects = rects_for(source if source is not None else EV, ids, parts, slow) if ids else {}
    rects.update(extra or {})
    takes[shot] = {"file": f"takes/{shot}.mp4", "seconds": round(duration(out), 3), "rects": rects, "ff": ff or []}
    path.write_text(json.dumps(takes, indent=1))
    print(video, shot, takes[shot]["seconds"], "s")


V4, V2 = "04-first-launch", "02-installing-on-a-mac"
RAW = FILM / "raw.mp4"

# ---- the launcher page (a continuous take; times are its own clock) ----
put(V4, "2.1", [(0.4, 25.9)], ids=("status", "start", "help"))
put(V2, "5.2", [(0.4, 10.4)], ids=("status",),
    extra={"window": [{"at": 0, "x": 330, "y": 30, "width": 1260, "height": 620}]})

# Starting is short in real time (about 1.5 s): slowed so it is on screen as the
# narration says it. The wait on "Opening Codex" is squeezed (the page's "Sped up").
slow = {0: 4.0}
a_len = (86.3 - 84.7) * 4.0
put(V4, "3.1", [(84.7, 86.3), (86.3, 104.4)], ids=("card", "line"), slow=slow,
    ff=[[round(a_len, 2), round(a_len + (100.0 - 86.3), 2), round(spoken(V4, "3.1", "Connected"), 2)]])
put(V4, "3.4", [(110.0, 120.0)], ids=("facts", "card"))
put(V4, "4.1", [(172.8, 188.0)], ids=("stop", "dialog"))
# Start button (4.2, a), then the Edit form filmed whole in a tall window (b).
a = (189.6, 194.6)
put(V4, "4.2a", [a], ids=("startlast",))
edit_src = FILM2 / "edit.mp4"
cut(str(edit_src), [(0.3, 10.3)], HERE / "build" / V4 / "takes" / "4.2b.mp4")
d = HERE / "build" / V4 / "takes"
(d / "list.txt").write_text(f"file '{d / '4.2a.mp4'}'\nfile '{d / '4.2b.mp4'}'\n")
run("-f", "concat", "-safe", "0", "-i", d / "list.txt", "-c", "copy", d / "4.2.mp4")
path, takes = manifest(V4)
shift = a[1] - a[0] - 0.3
rects = dict(takes["4.2a"]["rects"])
for sid in ("sec1", "sec2", "sec3"):
    rects[sid] = [{**{k: round(v, 1) for k, v in m.items() if k != "at"}, "at": round(max(m["at"], 0.3) + shift, 3)}
                  for m in EDIT[sid][:1]]
takes["4.2"] = {"file": "takes/4.2.mp4", "seconds": round(duration(d / "4.2.mp4"), 3), "rects": rects, "ff": []}
for junk in ("4.2a", "4.2b"):
    takes.pop(junk, None)
    (d / f"{junk}.mp4").unlink(missing_ok=True)
(d / "list.txt").unlink(missing_ok=True)
path.write_text(json.dumps(takes, indent=1))
print(V4, "4.2", takes["4.2"]["seconds"], "s")

# ---- the desktop: crops of the screen recording ----
# The folder picker: its dialog (x 484-1436, y 212-658). Its left column lists the
# parent folder, so it is blurred. Shown 1.6x, centred. It is fully on screen from 34 s of the
# recording and closed by Choose at 86.5 s; the wait between is cut out. Never cut
# nearer the ends: before 33.5 s and after 86.4 s the desktop under it shows.
PICK = "crop=952:446:484:212,split[a][b];[b]crop=243:293:276:88,boxblur=18[c];[a][c]overlay=276:88,scale=1523:714,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:" + PAPER
put(V4, "2.2", [(34.2, 39.7), (80.8, 86.2)], vf=PICK, src=RAW,
    extra={"picker": [{"at": 0, "x": 198, "y": 183, "width": 1523, "height": 714}]})
# UM-Codex's own Codex window (x 0-1280, y 30-850), fitted to the frame height.
WIN = "crop=1280:820:0:30,scale=-2:1080,pad=1920:1080:(ow-iw)/2:0:" + PAPER
K, PADX = 1080 / 820, (1920 - 1280 * 1080 / 820) / 2
chips = {"x": PADX + 455 * K, "y": (695 - 30) * K - 6, "width": (1163 - 455) * K, "height": 37 * K + 12}
put(V4, "3.2", [(97.4, 112.4)], vf=WIN, src=RAW, extra={"remote": [{"at": 0, **{k: round(v, 1) for k, v in chips.items()}}]})
put(V4, "3.3", [(124.5, 160.5)], vf=WIN, src=RAW, ff=[[3.0, 29.5, None]])
