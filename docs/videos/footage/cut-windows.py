"""Cuts the raw footage of the Windows filmings into the takes of
03-installing-on-windows and 04-first-launch-windows (alpha.7 launcher).

    python footage/cut-windows.py <scratch folder>      # e.g. C:\\umv-film

Inputs (kept out of the repo: the screen recordings have the whole desktop in them):
  film/launcher.mp4, film/events.json         footage/film-first-launch-windows.mjs
  film-form/form.mp4, film-form/form-events.json   footage/film-form-windows.mjs
  seg/seg-NNN.mkv, seg/segments.txt, marks.json    footage/record-windows-launch.ps1
                                              (segments: the capture restarts if Windows
                                              denies it for a moment)
  startmenu.mkv, raw-fixed.mkv                footage/record-windows-startmenu.ps1 and the
                                              first desktop filming (the Start menu, the icon)
Only crops of the screen recordings are used: Windows' folder dialog (the OneDrive folder names
in its left pane pixelated), UM-Codex's own copy of the Codex app, the UM-Codex shortcut on the
Desktop (on a black ground), and the Start menu's search pane (every result below the Best match
pixelated). The cut points were read off contact sheets of one run (marks.json): check them
again after a new filming.

Writes build/<video>/takes/<shot>.mp4 and merges build/<video>/takes.json. Where the narration's
timing exists, a wait in a take is squeezed so that it ends as the phrase naming it is spoken.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SCRATCH = Path(sys.argv[1])
FILM, FORM = SCRATCH / "film", SCRATCH / "film-form"
EV = json.loads((FILM / "events.json").read_text())["rects"]
FORMEV = json.loads((FORM / "form-events.json").read_text())["rects"]
SEG = SCRATCH / "seg"
PAPER = "0xf6f5f2"
V3, V4 = "03-installing-on-windows", "04-first-launch-windows"

# Segment starts, as seconds after the first segment began (the clock marks.json uses).
segs = []
for line in (SEG / "segments.txt").read_text().splitlines():
    n, stamp = line.split(" ", 1)
    segs.append((int(n), stamp))
from datetime import datetime
T0 = datetime.fromisoformat(segs[0][1])
SEGSTART = {n: (datetime.fromisoformat(s) - T0).total_seconds() for n, s in segs}
GOOD = [n for n in SEGSTART if (SEG / f"seg-{n:03d}.mkv").exists() and (SEG / f"seg-{n:03d}.mkv").stat().st_size > 100_000]


def seg_at(t):
    """(file, seconds into it) of the raw filming at t seconds after it began."""
    ok = [n for n in GOOD if SEGSTART[n] <= t + 0.01]
    n = max(ok)
    return SEG / f"seg-{n:03d}.mkv", t - SEGSTART[n]


def run(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True)


ENC = ["-r", "30", "-c:v", "libx264", "-crf", "17", "-g", "10", "-pix_fmt", "yuv420p", "-an"]


def cut(src, parts, out, vf="null"):
    graph, names = [], []
    for i, (a, b) in enumerate(parts):
        graph.append(f"[0:v]trim={a}:{b},setpts=PTS-STARTPTS,{vf},fps=30[p{i}]")
        names.append(f"[p{i}]")
    graph.append("".join(names) + f"concat=n={len(parts)}:v=1[v]")
    run("-i", src, "-filter_complex", ";".join(graph), "-map", "[v]", *ENC, out)


def join(files, out):
    d = Path(out).parent
    lst = d / "list.txt"
    lst.write_text("".join(f"file '{f}'\n" for f in files))
    run("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out)
    lst.unlink()


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True, check=True)
    return float(r.stdout)


def rects_for(source, ids, parts):
    out, offset = {}, 0.0
    for a, b in parts:
        for rid in ids:
            samples = source.get(rid, [])
            before = [m for m in samples if m["at"] <= a]
            keep = ([before[-1]] if before else []) + [m for m in samples if a < m["at"] <= b]
            for m in keep:
                out.setdefault(rid, []).append({**{k: round(v, 1) for k, v in m.items() if k != "at"},
                                                "at": round(offset + max(0, m["at"] - a), 3)})
        offset += b - a
    return out


def manifest(video):
    path = HERE / "build" / video / "takes.json"
    return path, json.loads(path.read_text()) if path.exists() else {}


def spoken(video, shot, phrase):
    """Seconds after the shot's start that `phrase` is spoken, or None before the narration exists."""
    build = HERE / "build" / video
    try:
        shots = {s["shot"]: s for s in json.loads((build / "timing.json").read_text())["shots"]}
        s = shots[shot]
        for block in (build / "captions.srt").read_text(encoding="utf-8").strip().split("\n\n"):
            lines = block.split("\n")
            a, b = [sum(float(x) * k for x, k in zip(re.split("[:,]", t), (3600, 60, 1, 0.001))) for t in lines[1].split(" --> ")]
            text = " ".join(lines[2:])
            i = text.find(phrase)
            if s["start"] - 0.01 <= a and b <= s["end"] + 0.01 and i >= 0:
                return a + i / len(text) * (b - a) - s["start"]
    except FileNotFoundError:
        return None
    return None


def put(video, shot, parts, vf="null", src=None, ids=(), source=None, ff=None, extra=None):
    """A take of `parts` of src (default the page film); several (src, parts) pairs may be joined
    by passing parts as [(src, [(a, b)...]), ...] with src None."""
    d = HERE / "build" / video / "takes"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{shot}.mp4"
    cut(str(src or FILM / "launcher.mp4"), parts, out, vf)
    path, takes = manifest(video)
    rects = rects_for(source if source is not None else EV, ids, parts) if ids else {}
    rects.update(extra or {})
    takes[shot] = {"file": f"takes/{shot}.mp4", "seconds": round(duration(out), 3), "rects": rects, "ff": ff or []}
    path.write_text(json.dumps(takes, indent=1))
    print(video, shot, takes[shot]["seconds"], "s")
    return out


def raw_part(video, shot, rel_a, rel_b, vf):
    """A piece of the screen recording, rel_a..rel_b seconds after it began (one segment)."""
    f, a = seg_at(rel_a)
    d = HERE / "build" / video / "takes"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{shot}-{rel_a:.0f}.mp4"
    cut(str(f), [(round(a, 3), round(a + (rel_b - rel_a), 3))], out, vf)
    return out


def merge_take(video, shot, files, rects, ff=None):
    d = HERE / "build" / video / "takes"
    out = d / f"{shot}.mp4"
    join(files, out)
    for f in files:
        Path(f).unlink(missing_ok=True)
    path, takes = manifest(video)
    takes[shot] = {"file": f"takes/{shot}.mp4", "seconds": round(duration(out), 3), "rects": rects, "ff": ff or []}
    path.write_text(json.dumps(takes, indent=1))
    print(video, shot, takes[shot]["seconds"], "s")


# ================= 04-first-launch-windows =================
# ---- the home screen, the form (page films; times are their own clocks) ----
put(V4, "2.1", [(0.8, 16.5)], ids=("status", "steps", "newsetup"))
FORMSRC = FORM / "form.mp4"
for shot, (a, b), ids in [
    ("3.1", (3.9, 19.9), ("folderfield", "moreFolders")),
    ("3.2", (19.9, 34.9), ("internet", "browser", "accessbox")),
    ("3.3", (34.9, 50.1), ("model", "openin")),
    ("3.4", (50.1, 64.1), ("more", "askcmd")),
    ("3.5", (64.1, 82.2), ("runson", "sandboxopt")),
    ("3.6", (82.2, 106.2), ("localopt", "localhelp", "runson")),
    ("3.7", (106.2, 118.2), ("localopt", "localhelp")),
    ("3.8", (118.2, 138.0), ("gets", "buttons")),
]:
    put(V4, shot, [(a, b)], src=FORMSRC, ids=ids, source=FORMEV)

# ---- Windows' folder dialog (dark theme here): the OneDrive folder names in its left pane pixelated ----
PICK = ("crop=956:536:962:346,split=2[a][b];[b]crop=160:275:18:153,scale=iw/8:ih/8,scale=160:275:flags=neighbor[bl];"
        "[a][bl]overlay=18:153,scale=1816:1018:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:" + PAPER)
f, a = seg_at(74.0)
put(V4, "4.1", [(round(a, 3), round(a + 11.3, 3))], vf=PICK, src=f,
    extra={"picker": [{"at": 0, "x": 52, "y": 31, "width": 1816, "height": 1018}]})

# ---- the card, while Codex opens ----
connected = spoken(V4, "4.2", "Connected")
ff42 = []
put(V4, "4.2", [(89.8, 121.5)], ids=("card", "line"), ff=ff42)
if connected is not None:   # the wait on "Opening Codex" is squeezed so it ends as "Connected" is said
    path, takes = manifest(V4)
    takes["4.2"]["ff"] = [[3.0, 28.0, round(connected, 2)]]
    path.write_text(json.dumps(takes, indent=1))

# ---- UM-Codex's own copy of the Codex app (x 160-1760, y 60-1000): fitted to the frame height ----
WIN = "crop=1596:936:162:62,scale=-2:1080,pad=1920:1080:(ow-iw)/2:0:0x0c0c0c"
K = 1080 / 936
PADX = (1920 - 1596 * K) / 2
remote = {"remote": [{"at": 0, "x": round(PADX + (777 - 162) * K, 1), "y": round((850 - 62) * K, 1), "width": round(708 * K, 1), "height": round(36 * K, 1)}]}
banner = {"banner": [{"at": 0, "x": round(PADX + (606 - 162) * K, 1), "y": round((762 - 62) * K, 1), "width": round(737 * K, 1), "height": round(111 * K, 1)}]}
R5 = SEGSTART[max(GOOD)]   # the segment that carries the rest of the filming after the capture gap
files = [raw_part(V4, "4.3b", R5 + 0.3, R5 + 3.3, WIN)]
merge_take(V4, "4.3", files, remote)
f, a = seg_at(R5 + 14.0)
put(V4, "4.4", [(round(a, 3), round(a + 10.0, 3))], vf=WIN, src=f, extra=banner)
f, a = seg_at(R5 + 2.0)
put(V4, "4.5", [(round(a, 3), round(a + 43.0, 3))], vf=WIN, src=f, ff=[[8.0, 36.0, None]])
put(V4, "4.6", [(165.0, 176.5)], ids=("summary", "facts", "card"))
# Stop: the page, then the Codex app saying it can't reconnect.
d = HERE / "build" / V4 / "takes"
cut(str(FILM / "launcher.mp4"), [(176.4, 193.3)], d / "5.1a.mp4")
rect51 = rects_for(EV, ("startbtn", "dialog"), [(176.4, 193.3)])
b = raw_part(V4, "5.1b", R5 + 67.0, R5 + 73.0, WIN)
merge_take(V4, "5.1", [d / "5.1a.mp4", b], rect51)
put(V4, "5.2", [(193.3, 200.0)], ids=("startbtn", "card"))

# ================= 03-installing-on-windows =================
put(V3, "5.2", [(0.8, 10.4)], ids=("status", "steps"),
    extra={"window": [{"at": 0, "x": 330, "y": 30, "width": 1260, "height": 620}]})
# The UM-Codex shortcut on the Desktop on its own on a black ground, then the Start menu finding it
# (from the first desktop filming: raw-fixed.mkv and startmenu.mkv).
RAWOLD, MENU = SCRATCH / "raw-fixed.mkv", SCRATCH / "startmenu.mkv"
if RAWOLD.exists() and MENU.exists():
    ICON = "crop=100:96:216:200,scale=500:480:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black"
    MENU_VF = ("crop=816:870:10:156,split=2[a][b];[b]crop=410:510:14:210,scale=iw/8:ih/8,scale=410:510:flags=neighbor[l];"
               "[a][l]overlay=14:210,pad=1920:1080:(ow-iw)/2:100:0x202020")
    d3 = HERE / "build" / V3 / "takes"
    d3.mkdir(parents=True, exist_ok=True)
    cut(str(RAWOLD), [(2.0, 5.5)], d3 / "5.1a.mp4", ICON)
    cut(str(MENU), [(6.3, 9.3)], d3 / "5.1b.mp4", MENU_VF)
    merge_take(V3, "5.1", [d3 / "5.1a.mp4", d3 / "5.1b.mp4"],
               {"icon": [{"at": 0, "x": 710, "y": 300, "width": 500, "height": 480}]})
