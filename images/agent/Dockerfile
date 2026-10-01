# UM-Codex agent image: the Codex CLI, Node, Python and R, plus general
# developer tools, for a research group's full-power Codex.
#
# Adapted from IHS DataLab's images/agent/Dockerfile at 6b6fdca
# (github.com/SripadaLab-UM/ihs-datalab). Changes: the DataLab skills,
# helper commands (profile-data, render-report), /inputs and /data/oracle
# are gone; build and developer tools, sudo and the /mnt/write and
# /mnt/read mount points are added.
#
# It holds no credentials. At launch, UM-Codex mounts:
#   /work                  the working folder (read/write), Codex's cwd
#   /mnt/write/<name>      more read/write folders
#   /mnt/read/<name>       read-only folders
#   /codex-home            the setup's Codex home volume (CODEX_HOME); its
#                          config.toml is the person's own, Codex writes it
#   /etc/codex             Codex's enforced settings and model catalog
#                          (read-only; src/umcodex/codex_config.py)
#   /etc/um-codex/launch.md  this launch's folders and internet (read-only)
# and runs Codex with `docker exec -it <agent> codex`.
#
# The `agent` user has passwordless sudo, on purpose: the container is the
# sandbox, and with internet on people must be able to apt/pip install.
# Nothing installed persists after the launch except in mounted folders and
# the Codex home volume.
#
# Build context: images/agent
#   docker build -t um-codex-agent:dev images/agent
#
# Everything is pinned so every person runs the same tools:
# - R: the Rocker r-ver image (exact R version), with CRAN packages from a
#   dated Posit Package Manager snapshot;
# - Codex CLI, Node and the Playwright MCP server (with the Chromium build
#   its Playwright pins): exact versions;
# - Python packages: requirements.txt (see requirements.in).

FROM node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c AS node
ARG CODEX_VERSION=0.157.1
# The browser tool (M2b): Playwright's MCP server, which brings its own
# Playwright. Its Chromium is installed in the final stage.
ARG PLAYWRIGHT_MCP_VERSION=0.0.83
RUN npm install -g "@openai/codex@${CODEX_VERSION}" "@playwright/mcp@${PLAYWRIGHT_MCP_VERSION}" \
    && npm cache clean --force

FROM rocker/r-ver:4.6.1@sha256:4e6e6696ff54a86625c7f80046478e67014a2184e942b85eeff43db7b992d93e

# Freeze CRAN at a date, so rebuilding the image gives the same R packages.
ARG CRAN_SNAPSHOT=https://p3m.dev/cran/__linux__/noble/2026-09-25
ENV CRAN=${CRAN_SNAPSHOT} \
    DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl wget file findutils git openssh-client jq less procps \
        ripgrep fd-find tree unzip zip sqlite3 sudo vim-tiny nano \
        build-essential pkg-config \
        pandoc poppler-utils qpdf tesseract-ocr ghostscript \
        fonts-dejavu-core fonts-liberation \
        python3 python3-venv python3-dev \
        libxml2 libfontconfig1 libfreetype6 libharfbuzz0b libfribidi0 libpng16-16 libtiff6 libjpeg-turbo8 \
    && ln -s /usr/bin/fdfind /usr/local/bin/fd \
    && rm -rf /var/lib/apt/lists/*

# R packages: binaries from the snapshot above.
RUN echo "options(repos = c(CRAN = '${CRAN}'))" >> "${R_HOME}/etc/Rprofile.site" \
    && install2.r --error --skipinstalled --ncpus -1 \
        tidyverse data.table lubridate readxl openxlsx vroom jsonlite yaml glue withr \
        DBI RSQLite arrow \
        broom lme4 lmerTest survival mgcv \
        ggplot2 patchwork cowplot ggrepel viridis plotly svglite ragg \
        rmarkdown knitr flextable officer skimr \
        testthat lintr \
    && rm -rf /tmp/downloaded_packages

# Node, npm and the Codex CLI, from the first stage.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex \
    && ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && ln -s ../lib/node_modules/@playwright/mcp/cli.js /usr/local/bin/playwright-mcp \
    && codex --version

# The browser tool: the Chromium build that the MCP server's Playwright pins
# (Chrome for Testing, for amd64 and arm64), with the system libraries it
# needs, in a shared folder the agent user can read. Codex starts the server
# only when a setup turns the browser tool on (codex_config.py); it runs
# headless, as agent, with a fresh in-memory profile each time. The headless
# shell isn't installed: `--browser chromium` uses the full build.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN playwright-mcp install-browser --with-deps --no-shell chromium \
    && chmod -R a+rX /opt/ms-playwright \
    && rm -rf /var/lib/apt/lists/* /tmp/*

# Non-root user with passwordless sudo (see the note at the top).
RUN useradd --create-home --uid 10004 --shell /bin/bash agent \
    && echo 'agent ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/agent \
    && chmod 0440 /etc/sudoers.d/agent \
    && visudo -cf /etc/sudoers.d/agent

# Python: a venv the agent owns, so `pip install` works without sudo.
COPY requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-deps -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt \
    && chown -R agent:agent /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Base instructions Codex reads (copied into CODEX_HOME at start) and the
# smoke test, which CI can also run: `docker run --rm <image> um-codex-smoke`.
COPY AGENTS.md /etc/um-codex/AGENTS.md
COPY smoke.sh /usr/local/bin/um-codex-smoke
COPY browser-check.js /usr/local/bin/um-codex-browser-check
RUN chmod 0644 /etc/um-codex/AGENTS.md \
    && chmod 0755 /usr/local/bin/um-codex-smoke /usr/local/bin/um-codex-browser-check \
    && mkdir -p /work /mnt/write /mnt/read /codex-home /home/agent/R/library \
    && chown agent:agent /work /codex-home /home/agent/R /home/agent/R/library

USER agent
WORKDIR /work
ENV HOME=/home/agent \
    CODEX_HOME=/codex-home \
    MPLCONFIGDIR=/tmp/matplotlib \
    R_LIBS_USER=/home/agent/R/library

RUN um-codex-smoke

ENTRYPOINT []
# Put the base instructions where Codex reads them (they're the app's file,
# so they're overwritten each start), then wait: UM-Codex runs Codex with
# `docker exec -it`.
CMD ["sh", "-c", "cp /etc/um-codex/AGENTS.md \"$CODEX_HOME/AGENTS.md\" && exec sleep infinity"]
