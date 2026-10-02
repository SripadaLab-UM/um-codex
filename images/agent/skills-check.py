#!/opt/venv/bin/python
"""Check that Codex's app-server finds the shipped skills, enabled.

Usage: um-codex-skills-check [--no-bundled] [-c key=value ...]

Codex runs with a throwaway CODEX_HOME, removed afterwards: app-server writes
an installation id, its databases and (with bundled skills on) the bundled
skills into CODEX_HOME, and none of that may end up in the image's
/codex-home, which Docker copies into every new setup's volume.

--no-bundled: also check that Codex's bundled skills (scope "system") are
neither listed nor installed, as with a launch's managed_config.toml
(`[skills.bundled] enabled = false`). Without it, check they are listed, so
the check is known to see them. `-c` options are passed to codex.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SHIPPED = Path("/home/agent/.agents/skills")


def skills_list(codex_home: str, overrides: list[str]) -> dict:
    log = Path(codex_home) / "app-server.log"
    with log.open("w") as stderr:
        return _skills_list(codex_home, overrides, log, stderr)


def _skills_list(codex_home, overrides, log, stderr) -> dict:
    process = subprocess.Popen(
        ["codex", *overrides, "app-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=stderr,
        text=True,
        env={**os.environ, "CODEX_HOME": codex_home},
    )
    assert process.stdin and process.stdout

    def call(number, method, params):
        process.stdin.write(json.dumps({"id": number, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        while line := process.stdout.readline():
            response = json.loads(line)
            if response.get("id") == number:
                if "error" in response:
                    raise RuntimeError(response["error"])
                return response["result"]
        process.wait(timeout=10)
        raise RuntimeError(
            f"Codex app-server stopped ({process.returncode}) before its response:\n{log.read_text()}"
        )

    try:
        call(1, "initialize", {"clientInfo": {"name": "um-codex-skill-check", "version": "1"}})
        process.stdin.write('{"method":"initialized"}\n')
        process.stdin.flush()
        return call(2, "skills/list", {"cwds": ["/work"], "forceReload": True})["data"][0]
    finally:
        process.terminate()
        process.wait(timeout=10)


def main():
    args = sys.argv[1:]
    no_bundled = "--no-bundled" in args
    overrides = [arg for arg in args if arg != "--no-bundled"]
    with tempfile.TemporaryDirectory(prefix="um-codex-skills-check-") as codex_home:
        data = skills_list(codex_home, overrides)
        bundled_installed = (Path(codex_home) / "skills/.system").exists()
    assert not data.get("errors"), data["errors"]
    expected = {str(path) for path in SHIPPED.glob("*/SKILL.md")}
    found = {skill["path"] for skill in data["skills"] if skill["enabled"]}
    assert len(expected) == 8 and expected <= found, expected - found
    system = sorted(skill["name"] for skill in data["skills"] if skill["scope"] == "system")
    if no_bundled:
        assert not system, f"Codex's bundled skills are listed: {system}"
        assert not bundled_installed, "Codex installed its bundled skills"
        print("Codex found the eight shipped skills, enabled, and none of its bundled ones")
    else:
        assert system, "Codex listed none of its bundled skills: the check can't see them"
        print(f"Codex found the eight shipped skills, enabled (bundled: {', '.join(system)})")


if __name__ == "__main__":
    main()
