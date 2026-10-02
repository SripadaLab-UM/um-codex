"""Cuts the one take of film-settings.mjs into the takes of 05-launcher-settings.

    python3 footage/cut-settings.py <scratch folder holding film3/settings.mp4 and settings.json>

The take's clock is the narration's, so shot S is simply [S.start, S.end + 0.4]
of it. The spotlight rectangles are shifted to each take's own clock.
Writes build/05-launcher-settings/takes/<shot>.mp4 and takes.json.
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
NAME = "05-launcher-settings"
build = HERE / "build" / NAME
film = Path(sys.argv[1]) / "film3"
data = json.loads((film / "settings.json").read_text())
timing = json.loads((build / "timing.json").read_text())
SKIP = {"1.1", "6.2"}  # the agenda and the end card have no footage
(build / "takes").mkdir(parents=True, exist_ok=True)
takes = {}
for s in timing["shots"]:
    if s["shot"] in SKIP:
        continue
    a, b = s["start"], s["end"] + 0.4
    out = build / "takes" / f"{s['shot']}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(a), "-t", str(b - a), "-i", str(film / "settings.mp4"),
                    "-r", "30", "-c:v", "libx264", "-crf", "17", "-g", "10", "-pix_fmt", "yuv420p", "-an", str(out)], check=True)
    rects = {}
    for rid, samples in data["rects"].items():
        before = [m for m in samples if m["at"] <= a]
        keep = ([before[-1]] if before else []) + [m for m in samples if a < m["at"] <= b]
        if keep:
            rects[rid] = [{**{k: v for k, v in m.items() if k != "at"}, "at": round(max(0.0, m["at"] - a), 2)} for m in keep]
    takes[s["shot"]] = {"file": f"takes/{s['shot']}.mp4", "seconds": round(b - a, 2), "rects": rects, "ff": []}
    print(s["shot"], round(b - a, 1), "s", sorted(rects))
(build / "takes.json").write_text(json.dumps(takes, indent=1))
