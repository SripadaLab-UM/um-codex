"""Cuts the raw footage of the Windows filmings into the takes of
03-installing-on-windows and 04-first-launch-windows.

    python footage/cut-windows.py <scratch folder>      # e.g. C:\\umv-film

Inputs (kept out of the repo: the screen recordings have the whole desktop in them):
  film/launcher.mp4, film/events.json    footage/film-first-launch.mjs
  film2/edit.mp4, film2/edit-rects.json  footage/film-edit.mjs
  raw-fixed.mkv                          footage/record-windows-launch.ps1 (remuxed:
                                         ffmpeg -i raw.mkv -c copy raw-fixed.mkv)
  startmenu.mkv                          footage/record-windows-startmenu.ps1
Only crops of the screen recordings are used: Windows' folder picker (the user's
own folders in its tree are pixelated), Codex's Terminal window, the UM-Codex
shortcut on the Desktop (on a black ground), and the Start menu's search pane
(every result below the Best match pixelated). The cut points were read off
contact sheets of one run (marks.json): check them again after a new filming.

Writes build/<video>/takes/<shot>.mp4 and merges build/<video>/takes.json.
"""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SCRATCH = Path(sys.argv[1])
FILM, FILM2 = SCRATCH / "film", SCRATCH / "film2"
EV = json.loads((FILM / "events.json").read_text())["rects"]
EDIT = json.loads((FILM2 / "edit-rects.json").read_text())["rects"]
RAW = SCRATCH / "raw-fixed.mkv"
MENU = SCRATCH / "startmenu.mkv"
PAPER = "0xf6f5f2"
V3, V4 = "03-installing-on-windows", "04-first-launch-windows"


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


def put(video, shot, parts, vf="null", src=None, ids=(), source=None, ff=None, extra=None):
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


# ---- the launcher page (a continuous take; times are its own clock) ----
put(V4, "2.1", [(1.0, 27.5)], ids=("status", "start", "help"))
put(V3, "5.2", [(1.0, 10.4)], ids=("status",),
    extra={"window": [{"at": 0, "x": 330, "y": 30, "width": 1260, "height": 620}]})
put(V4, "3.1", [(36.9, 52.0)], ids=("card", "line"))
put(V4, "3.4", [(100.0, 110.0)], ids=("facts", "card"))
put(V4, "4.1", [(111.5, 126.5)], ids=("stop", "dialog"))
a = (126.5, 131.0)
put(V4, "4.2a", [a], ids=("startlast",))
d = HERE / "build" / V4 / "takes"
cut(str(FILM2 / "edit.mp4"), [(0.3, 10.3)], d / "4.2b.mp4")
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

# ---- the desktop: crops of the screen recordings ----
# Windows' folder picker: its dialog (x 801-1119, y 354-728 on the 1920x1080 screen).
# The tree lists the user's own folders: pixelated, leaving the demo folder's rows.
# Shown 2.4x, centred, from when it is fully open to just before OK is pressed.
PICK = ("crop=318:374:801:354,split=3[a][b][c];[b]crop=290:180:15:87,scale=iw/6:ih/6,scale=290:180:flags=neighbor[bl];"
        "[c]crop=290:19:15:317,scale=iw/6:ih/6,scale=290:19:flags=neighbor[cl];[a][bl]overlay=15:87[d];[d][cl]overlay=15:317,"
        "scale=763:898:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:" + PAPER)
put(V4, "2.2", [(33.8, 38.7)], vf=PICK, src=RAW,
    extra={"picker": [{"at": 0, "x": 578, "y": 91, "width": 763, "height": 898}]})
# Codex's own Terminal window (x 165-1755, y 102-914), fitted to the frame's width.
WIN = "crop=1576:804:172:106,scale=1920:-2:flags=lanczos,pad=1920:1080:0:(oh-ih)/2:0x0c0c0c"
K = 1920 / 1576
put(V4, "3.2", [(46.5, 60.0)], vf=WIN, src=RAW,
    extra={"codex": [{"at": 0, "x": 0, "y": round((1080 - 804 * K) / 2, 1), "width": 1920, "height": round(804 * K, 1)}]})
put(V4, "3.3", [(75.8, 112.0)], vf=WIN, src=RAW, ff=[[7.0, 33.0, None]])

# The UM-Codex shortcut on the Desktop, on its own on a black ground (the Desktop's
# other icons and names are not used), then the Start menu finding it.
ICON = "crop=100:96:216:200,scale=500:480:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black"
MENU_VF = ("crop=816:870:10:156,split=2[a][b];[b]crop=410:510:14:210,scale=iw/8:ih/8,scale=410:510:flags=neighbor[l];"
           "[a][l]overlay=14:210,pad=1920:1080:(ow-iw)/2:100:0x202020")
d3 = HERE / "build" / V3 / "takes"
d3.mkdir(parents=True, exist_ok=True)
cut(str(RAW), [(2.0, 5.5)], d3 / "5.1a.mp4", ICON)
cut(str(MENU), [(6.3, 9.3)], d3 / "5.1b.mp4", MENU_VF)
(d3 / "list.txt").write_text(f"file '{d3 / '5.1a.mp4'}'\nfile '{d3 / '5.1b.mp4'}'\n")
run("-f", "concat", "-safe", "0", "-i", d3 / "list.txt", "-c", "copy", d3 / "5.1.mp4")
path, takes = manifest(V3)
takes["5.1"] = {"file": "takes/5.1.mp4", "seconds": round(duration(d3 / "5.1.mp4"), 3), "ff": [],
                "rects": {"icon": [{"at": 0, "x": 710, "y": 300, "width": 500, "height": 480}]}}
for junk in ("5.1a", "5.1b"):
    (d3 / f"{junk}.mp4").unlink(missing_ok=True)
(d3 / "list.txt").unlink(missing_ok=True)
path.write_text(json.dumps(takes, indent=1))
print(V3, "5.1", takes["5.1"]["seconds"], "s")
