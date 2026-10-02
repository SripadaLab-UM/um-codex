#!/bin/sh
# Smoke test for the UM-Codex agent image. The Dockerfile's last RUN runs it
# at build time, and CI can run it in a built image:
#   docker run --rm um-codex-agent:dev um-codex-smoke
# Adapted from the smoke checks in IHS DataLab's images/agent/Dockerfile at
# 6b6fdca. Prints one line per check; exits non-zero on the first failure.
set -eu

check() {
    name=$1
    shift
    if "$@" > /dev/null 2>&1; then
        echo "ok    $name"
    else
        echo "FAIL  $name" >&2
        "$@" >&2 || true
        exit 1
    fi
}

check "user is agent" test "$(whoami)" = agent
check "uid is 10004" test "$(id -u)" = 10004
check "passwordless sudo" sudo -n true
check "CODEX_HOME is /codex-home" test "${CODEX_HOME:-}" = /codex-home
check "no Codex credentials in the image" test ! -e "$CODEX_HOME/auth.json"
check "/work writable" sh -c 'f=/work/.um-codex-smoke.$$ && touch "$f" && rm "$f"'
check "/codex-home writable" sh -c 'f=/codex-home/.um-codex-smoke.$$ && touch "$f" && rm "$f"'
check "mount points exist" test -d /mnt/write -a -d /mnt/read
check "base AGENTS.md" test -s /etc/um-codex/AGENTS.md

# Every Codex run here gets a throwaway CODEX_HOME: Codex writes an
# installation id, databases and its bundled skills into its home, and the
# image's /codex-home is copied into every new setup's volume (the
# Dockerfile's last stage checks it stayed empty).
check "codex" sh -c 'h=$(mktemp -d) && CODEX_HOME="$h" codex --version; s=$?; rm -rf "$h"; exit $s'
check "shipped skills found, Codex's bundled skills seen" timeout 60 um-codex-skills-check
check "shipped skills found, bundled skills off" timeout 60 um-codex-skills-check --no-bundled -c skills.bundled.enabled=false
check "node" node --version
check "npm" npm --version
for tool in git ssh curl wget jq rg fd tree less ps make gcc g++ vi nano unzip pandoc typst sqlite3; do
    check "$tool on PATH" command -v "$tool"
done

# The browser tool, started the way codex_config.py starts it (keep the two
# argument lists the same; a test checks), opening a page with no network.
check "playwright-mcp" playwright-mcp --version
check "Chromium in the shared folder" sh -c 'ls -d "$PLAYWRIGHT_BROWSERS_PATH"/chromium-*/chrome-linux*/chrome'
check "browser tool opens a page headless" um-codex-browser-check \
    'data:text/html,<title>smoke</title><h1>UM-Codex browser smoke</h1>' 'heading "UM-Codex browser smoke"' \
    -- /usr/local/bin/playwright-mcp --headless --browser chromium --isolated --output-dir /tmp/um-codex-browser
rm -rf /tmp/um-codex-browser

# "Open in: Codex app" (M6): sshd's config is valid (checked with a throwaway
# host key: each container makes its own), the app's login shell gets
# CODEX_HOME and codex, and the token helper is there.
check "sshd and sftp-server" test -x /usr/sbin/sshd -a -x /usr/lib/openssh/sftp-server
check "sshd config is valid" sh -c 'k=$(mktemp -u) && ssh-keygen -q -t ed25519 -N "" -f "$k" && sudo -n /usr/sbin/sshd -t -f /etc/um-codex/sshd_config -h "$k"; s=$?; rm -f "$k" "$k.pub"; exit $s'
check "no host keys in the image" sh -c '! ls /etc/ssh/ssh_host_* 2>/dev/null'
check "agent's login shell is bash" test "$(getent passwd agent | cut -d: -f7)" = /bin/bash
check "login shell has CODEX_HOME and codex" env -i HOME=/home/agent SHELL=/bin/bash /bin/bash -l -c 'test "$CODEX_HOME" = /codex-home && command -v codex'
check "token helper" test -x /usr/local/bin/umcodex-token

check "python is the venv" test "$(command -v python)" = /opt/venv/bin/python
check "pip in the venv" python -m pip --version
check "venv owned by agent" test -w /opt/venv/lib
check "python headers" sh -c 'test -f "$(python -c "import sysconfig; print(sysconfig.get_paths()[\"include\"])")/Python.h"'
check "pip dependency consistency" python -m pip check
check "uv" uv --version
check "Quarto" quarto --version
check "pandoc is Quarto's" test "$(readlink -f "$(command -v pandoc)")" = "/opt/quarto/bin/tools/$(uname -m)/pandoc"
check "typst is Quarto's" test "$(readlink -f "$(command -v typst)")" = "/opt/quarto/bin/tools/$(uname -m)/typst"
check "R finds pandoc" Rscript -e 'stopifnot(rmarkdown::pandoc_available("3.0"))'
check "TypeScript" tsc --version
check "esbuild" esbuild --version
check "research execution and dashboards" um-codex-capability-check

check "python packages" python -c "import yaml, duckdb, pandas, polars, numpy, scipy, statsmodels, sklearn, matplotlib, seaborn, altair, plotnine, pyarrow, pdfplumber, pypdf, docx, pptx, openpyxl, xlsxwriter, vl_convert, bs4, httpx, lxml, requests, pytest"
check "R packages" Rscript -e "suppressMessages({library(tidyverse); library(data.table); library(lubridate); library(ggplot2); library(lme4); library(lmerTest); library(survival); library(mgcv); library(arrow); library(rmarkdown); library(flextable); library(testthat)})"
check "R user library writable" test -w "$R_LIBS_USER"

echo "smoke test passed"
