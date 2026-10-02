"""Records the Windows installer's own output for 03-installing-on-windows.

    python footage/record-windows-install.py [--release v0.1.0-alpha.4]

Runs the real install-windows.ps1 of that release in Windows PowerShell 5.1
(the same text `irm ... | iex` runs, started as a script block so that
-ReplaceKey can be passed), with Enter pressed only at the key prompt (any other question stops it), and writes
build/03-installing-on-windows/terminal.json: {"events": [[seconds, text], ...]}.

- Nothing is typed into the key prompt: Enter skips it, and a key that is saved
  already is left as it is (the installer only replaces a key it was given).
  Typing a key is a labelled illustration in the video.
- The user's name is shown as "you" in everything recorded.
- It stops at once if UM-Codex is running (the installer asks for it to be
  closed before it changes anything) or if no key is saved already (the
  installer would then wait at the key prompt, with nothing to keep).
- Run on a computer that has Docker Desktop running and UM-Codex installed;
  the administrator part of step 1 is then not needed (and is drawn in the
  video instead, in the installer's own words).
"""

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--release", default="v0.1.0-alpha.4")
parser.add_argument("--name", default="03-installing-on-windows")
args = parser.parse_args()

BASE = f"https://github.com/SripadaLab-UM/um-codex/releases/download/{args.release}"
ROOT = Path(os.environ["LOCALAPPDATA"]) / "UM-Codex" / "app"
user = os.environ["USERNAME"]
home = re.compile(re.escape("\\Users\\" + user), re.I)
bare = re.compile(r"\b" + re.escape(user) + r"\b", re.I)
redact = lambda s: bare.sub("you", home.sub(r"\\Users\\you", s))


def running() -> list[str]:
    """Processes started from UM-Codex's program folders (what the installer checks)."""
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          f"Get-Process | Where-Object {{ $_.Path -and ($_.Path.StartsWith('{ROOT}\\versions\\', 'OrdinalIgnoreCase') -or $_.Path.StartsWith('{ROOT}\\bin\\', 'OrdinalIgnoreCase')) }} | ForEach-Object {{ $_.Id }}"],
                         capture_output=True, text=True).stdout.split()
    return out


def key_saved() -> bool:
    py = ROOT / "versions" / (ROOT / "current").read_text().strip() / "Scripts" / "python.exe"
    return subprocess.run([str(py), "-c", "import sys; from umcodex import credentials; sys.exit(0 if credentials.has_api_key() else 1)"]).returncode == 0


if running():
    sys.exit(f"UM-Codex is running (process {', '.join(running())}): close it first.")
if not key_saved():
    sys.exit("No Toolkit key is saved, so the installer would wait at its key prompt. Save one first (off camera).")

def clean_env():
    """The environment as Windows gives it: a shell such as Git Bash puts its own whoami.exe and other
    tools first on PATH, and the installer runs `whoami /groups`."""
    env = dict(os.environ)
    root = os.environ["SystemRoot"]
    system32 = os.path.join(root, "System32")
    env["PATH"] = ";".join([system32, root, os.path.join(system32, "Wbem"),
                            os.path.join(system32, "WindowsPowerShell", "v1.0"),
                            os.path.join(os.environ["ProgramFiles"], "Docker", "Docker", "resources", "bin")])
    return env


command = (
    "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
    "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; "
    f"irm {BASE}/install-windows.ps1 | iex"
)
process = subprocess.Popen(
    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=clean_env())
q: queue.Queue = queue.Queue()


def pump() -> None:
    while True:
        data = process.stdout.read1(4096)
        q.put(data)
        if not data:
            return


threading.Thread(target=pump, daemon=True).start()

events, t0, buf = [], time.monotonic(), ""


def emit(text: str) -> None:
    events.append([round(time.monotonic() - t0, 3), redact(text)])
    with open(Path(os.environ.get("TEMP", ".")) / "install-live.log", "a", encoding="utf-8") as live:
        live.write(redact(text))


import codecs
decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
while True:
    try:
        chunk = q.get(timeout=0.2)
    except queue.Empty:
        if buf:  # a prompt, waiting for an answer
            emit(buf)
            if "Toolkit API key" in buf:  # the only question answered: Enter skips it
                process.stdin.write(b"\r\n"); process.stdin.flush()
            elif re.search(r"\[Y/n\]|Press Enter|\? *$", buf):
                # Any other question would be answered "yes" by Enter (administrator part, restart).
                process.kill()
                sys.exit(f"Stopped at a question the recording must not answer: {buf.strip()!r}")
            buf = ""
        if process.poll() is not None and q.empty():
            break
        continue
    if not chunk:
        break
    buf += decoder.decode(chunk).replace("\r\n", "\n").replace("\r", "")
    while "\n" in buf:
        line, buf = buf.split("\n", 1)
        emit(line + "\n")
if buf:
    emit(buf)
process.wait()
out = Path(__file__).resolve().parent.parent / "build" / args.name
out.mkdir(parents=True, exist_ok=True)
(out / "terminal.json").write_text(json.dumps({"events": events}, indent=1), encoding="utf-8")
print(f"exit {process.returncode}; {len(events)} events, {events[-1][0] if events else 0} s -> {out / 'terminal.json'}")
print("key still saved:", key_saved())
