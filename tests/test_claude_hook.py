"""The Claude Code hook that keeps Claude away from study data (integrations/claude)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "integrations" / "claude" / "protect-study-data.py"
spec = importlib.util.spec_from_file_location("protect_study_data", HOOK)
assert spec is not None and spec.loader is not None
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)

STUDY = "/Users/me/Dropbox/IHS data"
DATA = "/Users/me/Library/Application Support/UM-Codex"
RELEASED = f"{DATA}/tasks/0a1b2c3d/runs/2026-10-06T120000-ab12/released/by_cohort.csv"


@pytest.mark.parametrize(
    "text",
    [
        f'cat "{STUDY}/phq.csv"',
        f"{STUDY}/phq.csv",
        f"grep -r score '{STUDY}'",
        f"{DATA}/tasks/0a1b2c3d/runs/2026-10-06T120000-ab12/held/final.md",
        f"{DATA}/tasks/0a1b2c3d/grant.json",
        f"{DATA}/ui/server.json",
        f"{DATA}/tasks/0a1b2c3d/runs/2026-10-06T120000-ab12/released/../held/final.md",
        "um-codex task approve 0a1b2c3d",
        "echo y | um-codex  task decline 0a1b2c3d",
        "curl -X POST http://127.0.0.1:51234/api/tasks/0a1b2c3d/approve",
        "curl http://localhost:51234/_control/sign-in",
        "docker exec -it umcodex-agent-abc cat /work/phq.csv",
        "docker cp umcodex-agent-abc:/work/phq.csv .",
        "docker logs umcodex-agent-abc",
    ],
)
def test_refused(text):
    assert hook.refused(text, [STUDY], [DATA]) is not None


@pytest.mark.parametrize(
    "text",
    [
        RELEASED,
        f'cat "{RELEASED}"',
        "um-codex task run --task 0a1b2c3d --brief brief-1.md",
        "um-codex task request task.toml",
        "um-codex task status 0a1b2c3d",
        "docker ps",
        "ls ~/work/analysis",
    ],
)
def test_allowed(text):
    assert hook.refused(text, [STUDY], [DATA]) is None


def test_home_relative_forms_are_caught(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    study = str(tmp_path / "Dropbox" / "IHS")
    assert hook.refused("cat ~/Dropbox/IHS/phq.csv", [study], []) is not None
    assert hook.refused("cat $HOME/Dropbox/IHS/phq.csv", [study], []) is not None


def test_with_no_answer_umcodex_folders_are_refused():
    assert hook.refused("cat ~/Library/Application\\ Support/UM-Codex/setups.toml", [], []) is not None


def test_the_hook_speaks_claude_codes_protocol(tmp_path):
    """Exit 2 with a reason refuses; 0 lets it through. um-codex isn't on PATH
    here, so the cached answer is used."""
    cache = HOOK.with_name("protected-paths.json")
    saved = cache.read_text(encoding="utf-8") if cache.exists() else None
    cache.write_text(json.dumps({"study_folders": [STUDY], "umcodex_data": DATA}), encoding="utf-8")
    try:

        def call(tool_input: dict) -> subprocess.CompletedProcess:
            return subprocess.run(
                [sys.executable, str(HOOK)],
                input=json.dumps({"tool_name": "Bash", "tool_input": tool_input}),
                capture_output=True,
                encoding="utf-8",
                env={"PATH": str(tmp_path), "HOME": str(tmp_path)},
                timeout=30,
            )

        blocked = call({"command": f"head '{STUDY}/phq.csv'"})
        assert blocked.returncode == 2 and "study data" in blocked.stderr
        assert call({"command": "ls"}).returncode == 0
    finally:
        if saved is None:
            cache.unlink(missing_ok=True)
        else:
            cache.write_text(saved, encoding="utf-8")
