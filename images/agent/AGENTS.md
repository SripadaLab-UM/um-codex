# UM-Codex

You're running inside a Docker container that UM-Codex started for one
person on their computer. They talk to you through this Codex terminal.

**Read `/etc/um-codex/launch.md` first.** It describes this launch: which
host folders are mounted where, and whether the internet is on.

## Folders

| Path | What | Access |
|---|---|---|
| `/work` | The working folder, where you start | read, write, delete |
| `/mnt/write/<name>` | More folders the person chose to share | read, write, delete |
| `/mnt/read/<name>` | Folders shared for reading | read only |

These are the person's real folders on their computer. Changes and
deletions there are real and immediate: there's no undo and no trash. Be
careful with `rm`, `mv` and overwrites, and ask before deleting or
rewriting anything you didn't create.

Everything else in the container is temporary.

## Internet

It may be on or off; `launch.md` says which. When it's off, you can reach
only the model, so installs and downloads will fail: say so instead of
retrying.

## Installing things

You have passwordless `sudo` inside the container. With internet on you can
`sudo apt-get install`, `pip install` (Python is a venv at `/opt/venv`),
`npm install` and `install.packages()` in R. Nothing you install survives
the end of this session, except files in the mounted folders and in
`$CODEX_HOME`. If the person needs a tool every time, tell them.

Already installed: Python 3 with common data science packages, R with the
tidyverse and common statistics packages, Node, git, build tools, pandoc,
ripgrep (`rg`), `fd`, `jq`.

## Credentials

The container holds no API keys or passwords, and the model connection is
handled outside it. Don't look for credentials, and don't ask the person to
paste secrets into files here.
