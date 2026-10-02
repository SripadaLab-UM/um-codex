---
name: project-environments
description: Create, restore or troubleshoot persistent Python and R project environments in UM-Codex, including offline use of bundled packages.
---

# Persistent project environments

Read `/etc/um-codex/launch.md` and inspect existing manifests first. Work in
`/work` or an explicitly selected writable mount. Never replace an existing
`.venv`, `renv.lock`, `.Rprofile`, or lockfile to force setup through.

## Python

For an existing uv project, use its Python constraint and `uv.lock`. With
internet on: `uv sync --locked`, then `uv run --no-sync ...`. For a new
isolated project: `uv venv --python /usr/bin/python3 .venv`, declare dependencies
in `pyproject.toml`, and lock them. Do not quietly upgrade an existing lock.

With internet off, a fresh isolated venv has no scientific packages. Use
`um-codex-env .venv --image-packages` for a new environment: it writes a `.pth`
fallback to the bundled `/opt/venv` and records its exact package inventory.
Project-installed packages take precedence. This is an **image-backed**
environment, not an independently restorable lock. Run `.venv/bin/python`
directly; `uv run` can try to resolve/sync and remove or bypass this fallback.
For strict isolation offline, use a previously prepared project wheelhouse
and `uv pip install --python .venv/bin/python --no-index --find-links wheels -r requirements.txt`.
An offline lock cannot magically supply missing distributions.

Keep caches/wheelhouses in the project only when persistence is needed. Do
not use `uvx`, `npx`, or an installer that downloads missing tools offline.
Never assume a Linux venv runs on the person's Mac/Windows host; rebuild it
from the manifest there. Record Python version and image-package fallback.

## R

For existing renv projects, inspect `renv.lock`, activation, and the actual
library before restoring; offline restores need available packages.
For a new project using bundled packages offline:

```r
image_libraries <- .libPaths()
renv::init(bare = TRUE, settings = list(use.cache = FALSE))
renv::hydrate(packages = c("dplyr", "ggplot2"), sources = image_libraries)
renv::snapshot(prompt = FALSE)
```

Capture `.libPaths()` **before** init: renv changes `.Library` to its base-only
sandbox; using it afterward can trigger downloads even for bundled packages.
Choose packages used by the project, not the whole image. Verify in a new
R process that `find.package()` points into the project and the script runs.
`use.cache = FALSE` copies packages into `renv/library`, avoiding symlinks to
an ephemeral cache. For an existing cached library, `renv::isolate()` copies
cache contents into the project. Keep `renv.lock`, `renv/activate.R`, and the
library under `/work`; tell the person libraries are OS/R-version specific.
Install new packages only with internet on and update the lock intentionally.

Reference: [uv Docker environments](https://docs.astral.sh/uv/guides/integration/docker/),
[renv isolation](https://rstudio.github.io/renv/reference/isolate.html).
