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

check "codex" codex --version
check "node" node --version
check "npm" npm --version
for tool in git ssh curl wget jq rg fd tree less ps make gcc g++ vi nano unzip pandoc sqlite3; do
    check "$tool on PATH" command -v "$tool"
done

# The browser tool, started the way codex_config.py starts it (keep the two
# argument lists the same; a test checks), opening a page with no network.
check "playwright-mcp" playwright-mcp --version
check "Chromium in the shared folder" sh -c 'ls -d "$PLAYWRIGHT_BROWSERS_PATH"/chromium-*/chrome-linux*/chrome'
check "browser tool opens a page headless" um-codex-browser-check \
    'data:text/html,<title>smoke</title><h1>UM-Codex browser smoke</h1>' 'heading "UM-Codex browser smoke"' \
    -- /usr/local/bin/playwright-mcp --headless --browser chromium --isolated --output-dir /tmp/um-codex-browser

check "python is the venv" test "$(command -v python)" = /opt/venv/bin/python
check "pip in the venv" python -m pip --version
check "venv owned by agent" test -w /opt/venv/lib
check "python headers" sh -c 'test -f "$(python -c "import sysconfig; print(sysconfig.get_paths()[\"include\"])")/Python.h"'
check "python packages" python -c "import duckdb, pandas, polars, numpy, scipy, statsmodels, sklearn, matplotlib, seaborn, altair, plotnine, pyarrow, pdfplumber, pypdf, docx, pptx, openpyxl, xlsxwriter, vl_convert, bs4, httpx, lxml, requests, pytest"
check "R packages" Rscript -e "suppressMessages({library(tidyverse); library(data.table); library(lubridate); library(ggplot2); library(lme4); library(lmerTest); library(survival); library(mgcv); library(arrow); library(rmarkdown); library(flextable); library(testthat)})"
check "R user library writable" test -w "$R_LIBS_USER"

echo "smoke test passed"
