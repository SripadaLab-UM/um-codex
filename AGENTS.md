# For coding agents working on UM-Codex

This file is for AI coding agents changing this repository. The agent that
runs *inside* UM-Codex reads `images/agent/AGENTS.md` instead.

## What UM-Codex is

A launcher that runs OpenAI Codex (on U-M GPT Toolkit) in a Docker container
on Mac and Windows. The person picks folders (read / write) and internet
on/off at launch; Codex's own terminal UI is the front end. The Toolkit key
stays on the host, in a relay; the container gets a per-launch token. Much of
the machinery is copied from IHS DataLab (github.com/SripadaLab-UM/ihs-datalab
at 6b6fdca); each copied file says so at the top.

## Authoritative documents

- [docs/DESIGN.md](docs/DESIGN.md): what it is, how a launch runs, the key, folder rules, layout, milestones.
- [README.md](README.md): install and use, for people.

If code and a document disagree, fix the document in the same change. Don't
start new plan documents; update DESIGN.md.

## Rules

- One git worktree per branch; never share a checkout with another session.
- The Toolkit key never goes into a container, env var, file, log or
  diagnostics. A change near the relay or containers keeps the test for it.
- Tests at a boundary (Docker CLI output, Codex config, Toolkit responses)
  use real shapes taken from a live run.
- Public repo: no hostnames beyond the documented Toolkit URL, no IPs,
  emails, credentials or machine-specific paths.
- Code style: ruff; plain-language user messages (the people using this aren't
  developers of it). No prettier.
- Line endings: LF everywhere (.gitattributes), PowerShell files ASCII-only.

## Checks

```sh
uv run ruff check . && uv run pyright && uv run pytest -q
```
