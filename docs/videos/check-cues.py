"""Checks, before any narration is made, that every cue phrase in a script is
spoken word for word inside one caption of its shot (the page finds a cue by
looking for its phrase in a caption, as scripts/narrate-video.py splits them).

    python docs/videos/check-cues.py docs/videos/03-installing-on-windows.md
"""

import importlib.util
import re
import sys
from pathlib import Path

script = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("narrate", Path(__file__).resolve().parents[2] / "scripts" / "narrate-video.py")
narrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(narrate)

spoken = {s["shot"]: narrate.captions(s["text"]) for s in narrate.read_shots(script)}
problems, shot = [], None
for line in script.read_text(encoding="utf-8").splitlines():
    if m := re.match(r"\*\*Shot (\d+\.\d+)\*\*", line):
        shot = m[1]
        continue
    cue = (re.match(r"\s+- agenda · .+? · \"(.+)\"$", line) or re.match(r"\s+- `[\w-]+` · \"(.+?)\"(?: · .+)?$", line)
           or re.match(r"\s+- card · .+? · \"(.+)\"$", line))
    if cue and shot:
        if shot not in spoken:
            problems.append(f"{shot}: cue \"{cue[1]}\" but the shot has no narration")
        elif not any(cue[1] in c for c in spoken[shot]):
            problems.append(f"{shot}: \"{cue[1]}\" is not inside one caption: {spoken[shot]}")
print("\n".join(problems) if problems else f"{script.name}: every cue phrase is spoken inside one caption.")
sys.exit(1 if problems else 0)
