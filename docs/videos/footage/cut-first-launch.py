"""Cuts the raw footage of a first-launch filming (alpha.7 flow) into the takes
of 04-first-launch and the launcher shot of 02-installing-on-a-mac.

    python3 footage/cut-first-launch.py <scratch folder with filmA7/ and film2A7/>

Inputs (kept out of the repo: the screen recording has the whole desktop in it):
  filmA7/launcher.mp4, filmA7/events.json   footage/film-first-launch.mjs
  filmA7/raw.mp4                            a full-screen recording, 1920x1200 points
  film2A7/edit.mp4, film2A7/edit-rects.json footage/film-edit.mjs
Only a crop of the raw recording is ever used: the folder picker's dialog, with
its left column (the parent folder's listing) blurred. UM-Codex's own Codex
window (shots 3.2 and 3.3) is not re-cut: those takes come from the first
recording (the window didn't change) and are left as they are.
The cut points were read off contact sheets of one run (PICKER below): look
again after a new filming.

Writes build/<video>/takes/<shot>.mp4 and merges build/<video>/takes.json.
"""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SCRATCH = Path(sys.argv[1])
FILM, FILM2 = SCRATCH / "filmA7", SCRATCH / "film2A7"
DATA = json.loads((FILM / "events.json").read_text())
EV, EVENTS = DATA["rects"], {e["name"]: e["t"] for e in DATA["events"]}
EDIT = json.loads((FILM2 / "edit-rects.json").read_text())["rects"]
PAPER = "0xf6f5f2"
V4, V2 = "04-first-launch", "02-installing-on-a-mac"


def seconds(stamp):
    h, m, r = stamp.split(":")
    s, ms = r.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def timing(video):
    return {s["shot"]: s for s in json.loads((HERE / "build" / video / "timing.json").read_text())["shots"]}


def room(video, shot):
    t = timing(video)
    shots = list(t)
    s = t[shot]
    end = t[shots[shots.index(shot) + 1]]["start"] if shots.index(shot) + 1 < len(shots) else s["end"] + 1
    return end - s["start"]


def spoken(video, shot, phrase):
    """Seconds after the shot's start that `phrase` is spoken (as the page works it out)."""
    build = HERE / "build" / video
    s = timing(video)[shot]
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


def rects_for(source, ids, parts, slow=None, alias=None):
    """The sampled rects of `ids` in a take made of `parts` of the source timeline.
    alias: {cue id: sampled id} for a cue that points at another element's samples."""
    out, offset = {}, 0.0
    for i, (a, b) in enumerate(parts):
        f = (slow or {}).get(i, 1)
        for rid in ids:
            samples = source.get((alias or {}).get(rid, rid), [])
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


def put(video, shot, parts, vf="null", src=None, ids=(), source=None, ff=None, slow=None, extra=None, alias=None):
    d = HERE / "build" / video / "takes"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{shot}.mp4"
    cut(str(src or FILM / "launcher.mp4"), parts, out, vf, slow)
    path, takes = manifest(video)
    rects = rects_for(source if source is not None else EV, ids, parts, slow, alias) if ids else {}
    rects.update(extra or {})
    takes[shot] = {"file": f"takes/{shot}.mp4", "seconds": round(duration(out), 3), "rects": rects, "ff": ff or []}
    path.write_text(json.dumps(takes, indent=1))
    print(video, shot, takes[shot]["seconds"], "s", sorted(rects))


def window(video, shot, start, **kw):
    """A take from the launcher page starting at `start`, as long as the shot (plus a little)."""
    put(video, shot, [(start, round(start + room(video, shot) + 0.4, 2))], **kw)


# ---- the launcher page (a continuous take; times are its own clock) ----
STATUS = {"status": [{"at": 0, "x": 375, "y": 158, "width": 1170, "height": 72}]}  # the strip under the title
window(V4, "2.1", 0.4, ids=("step1", "step2", "step3", "newsetup"))
window(V4, "2.2", EVENTS["form"] + 0.2, ids=("pickbtn", "summary"))
window(V4, "2.4", EVENTS["picked"] + 0.5, ids=("defaults", "summary", "save"))
window(V2, "5.2", 0.5, ids=("getstarted",),
       extra={**STATUS, "window": [{"at": 0, "x": 330, "y": 30, "width": 1260, "height": 620}]})

# Starting is short in real time (about 1.6 s): slowed so it is on screen as the
# narration says it. The wait on "Opening Codex" is squeezed (the page's "Sped up").
card, opening, connected = EVENTS["card"] + 0.1, EVENTS["card"] + 1.7, EVENTS["connected"]
a_len = (opening - card) * 4.0
put(V4, "3.1", [(card, opening), (opening, connected + 5.0)], ids=("card", "line"), slow={0: 4.0},
    ff=[[round(a_len, 2), round(a_len + (connected - opening), 2), round(spoken(V4, "3.1", "Connected"), 2)]])
put(V4, "3.4", [(connected - 0.6, round(connected - 0.6 + room(V4, "3.4") + 0.4, 2))], ids=("sum", "facts"))
window(V4, "4.1", EVENTS["stop"] - 0.4, ids=("stop", "dialog"))

# Start button and the small links (4.2, a), then the Edit form filmed whole in a tall window (b).
a_end = max(2.5, spoken(V4, "4.2", "Edit shows three sections") - 0.3)
a = (EVENTS["stopped"] + 0.2, round(EVENTS["stopped"] + 0.2 + a_end, 2))
put(V4, "4.2a", [a], ids=("startbtn", "links"), alias={"startbtn": "stop"})
d = HERE / "build" / V4 / "takes"
b_len = room(V4, "4.2") - a_end + 0.4
cut(str(FILM2 / "edit.mp4"), [(0.3, round(0.3 + b_len, 2))], d / "4.2b.mp4")
(d / "list.txt").write_text(f"file '{d / '4.2a.mp4'}'\nfile '{d / '4.2b.mp4'}'\n")
run("-f", "concat", "-safe", "0", "-i", d / "list.txt", "-c", "copy", d / "4.2.mp4")
path, takes = manifest(V4)
shift = (a[1] - a[0]) - 0.3
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
print(V4, "4.2", takes["4.2"]["seconds"], "s", sorted(rects))

# ---- the desktop: a crop of the screen recording ----
# The folder picker: its dialog (x 484-1436, y 212-658). Its left column lists the
# parent folder, so it is blurred. Shown 1.6x, centred. It is fully drawn from 34.2 s
# of the recording and closed by Choose at 53.0 s; the wait between is cut out. Never
# cut nearer the ends: before 34 s and after 52.8 s the desktop under it shows.
PICK = ("crop=952:446:484:212,split[a][b];[b]crop=243:293:276:88,boxblur=18[c];[a][c]overlay=276:88,"
        "scale=1523:714,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:" + PAPER)
put(V4, "2.3", [(34.4, 39.4), (47.6, 52.6)], vf=PICK, src=FILM / "raw.mp4",
    extra={"picker": [{"at": 0, "x": 198, "y": 183, "width": 1523, "height": 714}]})
