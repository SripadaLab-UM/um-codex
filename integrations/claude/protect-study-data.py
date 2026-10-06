#!/usr/bin/env python3
"""Claude Code PreToolUse hook: keep Claude away from study data.

UM-Codex is approved for sensitive study data; Claude isn't. With tasks
(UM-Codex's tasks.py), Claude hands data steps to UM-Codex and reads back
only the results that passed UM-Codex's disclosure check. This hook makes
that a rule Claude can't break by accident:

- any tool call that names a protected path is refused: every folder of a
  UM-Codex setup that allows tasks, and UM-Codex's whole data folder (its
  launcher's sign-in records, tasks' answers and outputs), apart from a task
  run's released/ folder;
- Claude can't answer a task request (`um-codex task approve|decline`,
  writing a grant, or the launcher's task or control addresses), nor reach
  into UM-Codex's containers (`docker exec`,
  `cp`, `logs`, `inspect` on them), where the data is mounted.

The protected paths come from `um-codex task protected-paths`, and the last
answer is kept (beside this file) for when it can't run. With neither, every
call that names a UM-Codex data folder is refused.

Exit code 2 with a reason on stderr refuses the call (Claude Code's hook
protocol); 0 lets it through. Python 3.9+, standard library only.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CACHE = Path(__file__).with_name("protected-paths.json")
RELEASED = re.compile(r"/tasks/[0-9a-f]{8}/runs/[^/]+/released(/|$)")
ANSWERING = re.compile(r"\bum-codex\b[^|;&\n]*\btask\s+(approve|decline)\b|grant\.json")
LAUNCHER = re.compile(r"(127\.0\.0\.1|localhost|\[::1\]):\d+/(_control|api/tasks)", re.IGNORECASE)
CONTAINERS = re.compile(
    r"\bdocker\b[^|;&\n]*\b(exec|cp|logs|inspect|attach|commit|export|diff)\b[^|;&\n]*umcodex"
)


def protected() -> tuple[list[str], list[str]]:
    """(study folders, UM-Codex data folders)."""
    command = shutil.which("um-codex") or str(Path.home() / ".local" / "bin" / "um-codex")
    answer = None
    try:
        done = subprocess.run(
            [command, "task", "protected-paths"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        if done.returncode == 0:
            answer = json.loads(done.stdout)
            with contextlib.suppress(OSError):
                CACHE.write_text(json.dumps(answer), encoding="utf-8")
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    if not isinstance(answer, dict):
        try:
            answer = json.loads(CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            answer = {}
    if not isinstance(answer, dict):
        answer = {}
    study = [p for p in answer.get("study_folders", []) if isinstance(p, str) and p]
    data = answer.get("umcodex_data")
    return study, [data] if isinstance(data, str) and data else []


def strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]
    return []


def forms(path: str) -> set[str]:
    """How a path may be written in a tool call: as is, real, with ~."""
    found = {path.rstrip("/")}
    with contextlib.suppress(OSError):
        found.add(os.path.realpath(path).rstrip("/"))
    home = str(Path.home())
    for p in list(found):
        if p.startswith(home + "/"):
            found.add("~" + p[len(home) :])
            found.add("$HOME" + p[len(home) :])
    return {p for p in found if p}


def mentions(text: str, path: str) -> list[str]:
    """Each path-like word in `text` that starts with one way of writing `path`."""
    found = []
    for form in forms(path):
        start = text.find(form)
        while start != -1:
            # The path itself may have spaces; what follows it ends at a space or quote.
            rest = text[start + len(form) :]
            end = re.search(r"[\s'\"`;|&<>()]", rest)
            found.append(form + (rest[: end.start()] if end else rest))
            start = text.find(form, start + 1)
    return found


def refused(text: str, study: list[str], data: list[str]) -> str | None:
    if ANSWERING.search(text):
        return "Only the person answers UM-Codex task requests (in the UM-Codex window)."
    if LAUNCHER.search(text):
        return "Only the person answers UM-Codex task requests (in the UM-Codex window)."
    if CONTAINERS.search(text):
        return "UM-Codex's containers hold study data: work through `um-codex task run` only."
    for path in study:
        if mentions(text, path):
            return f"{path} holds study data: only UM-Codex reads it (`um-codex task run`)."
    for path in data:
        for named in mentions(text, path):
            if not (RELEASED.search(named) and ".." not in named):
                return (
                    f"{path} is UM-Codex's own data folder: Claude may read only a task run's released/ "
                    "folder, as `um-codex task run` reports it."
                )
    if not data and re.search(r"UM-Codex[/\\]", text) and not RELEASED.search(text):
        return "That looks like UM-Codex's data folder: only a task run's released/ folder may be read."
    return None


def main() -> int:
    try:
        call = json.load(sys.stdin)
    except ValueError:
        return 0
    text = "\n".join(strings(call.get("tool_input", {})))
    if not text:
        return 0
    reason = refused(text, *protected())
    if reason is None:
        return 0
    print(f"Blocked by protect-study-data: {reason}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
