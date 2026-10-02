#!/opt/venv/bin/python
"""Check the actual Codex app-server discovers and enables the shipped skills."""

import json
import subprocess
from pathlib import Path


def main():
    process = subprocess.Popen(
        ["codex", "app-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
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
        raise RuntimeError("Codex app-server stopped before its response")

    try:
        call(1, "initialize", {"clientInfo": {"name": "um-codex-skill-check", "version": "1"}})
        process.stdin.write('{"method":"initialized"}\n')
        process.stdin.flush()
        data = call(2, "skills/list", {"cwds": ["/work"], "forceReload": True})["data"][0]
        expected = {str(path) for path in Path("/home/agent/.agents/skills").glob("*/SKILL.md")}
        found = {skill["path"] for skill in data["skills"] if skill["enabled"]}
        assert len(expected) == 8 and expected <= found, expected - found
        assert not data.get("errors"), data["errors"]
        print("Codex discovered all eight shipped skills")
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == "__main__":
    main()
