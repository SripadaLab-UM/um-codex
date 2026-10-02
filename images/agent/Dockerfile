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
# and runs Codex with `docker exec -it <agent> codex`, or, for the Codex
# desktop app (M6), lets the app in over ssh through `docker exec ... sshd -i`
# (see the openssh-server step below; nothing listens on a port).
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
# - Python packages: requirements.txt (see requirements.in), with hashes.

FROM node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c AS node
ARG CODEX_VERSION=0.157.1
# The browser tool (M2b): Playwright's MCP server, which brings its own
# Playwright. Its Chromium is installed in the final stage.
ARG PLAYWRIGHT_MCP_VERSION=0.0.83
RUN npm install -g "@openai/codex@${CODEX_VERSION}" "@playwright/mcp@${PLAYWRIGHT_MCP_VERSION}" \
    && npm cache clean --force

FROM rocker/r-ver:4.6.1@sha256:4e6e6696ff54a86625c7f80046478e67014a2184e942b85eeff43db7b992d93e AS runtime

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
        poppler-utils qpdf tesseract-ocr ghostscript \
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
COPY requirements.txt /opt/um-codex/python-requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-deps --require-hashes -r /opt/um-codex/python-requirements.txt \
    && /opt/venv/bin/pip check \
    && chown -R agent:agent /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Research authoring and dashboard tools. Versions are fixed; Quarto's
# release assets are verified on both supported architectures. Quarto brings
# its own Pandoc and Typst, which are the image's `pandoc` (for R Markdown
# too) and `typst`: HTML, DOCX and PDF (through Typst, fonts included) work
# offline. No TeX or GPU stack: those need a project-specific installation.
ARG QUARTO_VERSION=1.10.18
RUN arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
        amd64) checksum=4bdf5a17df300003beb2f8f0e4dfe568e2ca0ff91318220c8537d2655015c430 ;; \
        arm64) checksum=ed3f70f63ee12b290ea1e38da08aa7c74c6843f6bed6df828e1e1652ef6d7d98 ;; \
        *) echo "Unsupported architecture: $arch" >&2; exit 1 ;; \
       esac \
    && curl -fsSL "https://github.com/quarto-dev/quarto-cli/releases/download/v${QUARTO_VERSION}/quarto-${QUARTO_VERSION}-linux-${arch}.deb" -o /tmp/quarto.deb \
    && echo "$checksum  /tmp/quarto.deb" | sha256sum -c - \
    && dpkg -i /tmp/quarto.deb \
    && rm /tmp/quarto.deb \
    && ln -s "/opt/quarto/bin/tools/$(uname -m)/pandoc" /usr/local/bin/pandoc \
    && ln -s "/opt/quarto/bin/tools/$(uname -m)/typst" /usr/local/bin/typst \
    && pandoc --version && typst --version
# CRAN's fs binary (used by renv/Shiny) links against Ubuntu's libuv.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libuv1t64 \
    && rm -rf /var/lib/apt/lists/*
RUN install2.r --error --skipinstalled --ncpus -1 renv shiny \
    && Rscript -e 'stopifnot(as.character(packageVersion("renv")) == "1.2.4", as.character(packageVersion("shiny")) == "1.14.0")' \
    && rm -rf /tmp/downloaded_packages
RUN npm install -g typescript@7.0.2 esbuild@0.28.2 \
    && npm cache clean --force

# Base instructions Codex reads (copied into CODEX_HOME at start) and the
# smoke test, which CI can also run: `docker run --rm <image> um-codex-smoke`.
COPY AGENTS.md /etc/um-codex/AGENTS.md
COPY smoke.sh /usr/local/bin/um-codex-smoke
COPY browser-check.js /usr/local/bin/um-codex-browser-check
RUN chmod 0644 /etc/um-codex/AGENTS.md \
    && chmod 0755 /usr/local/bin/um-codex-smoke /usr/local/bin/um-codex-browser-check \
    && mkdir -p /work /mnt/write /mnt/read /codex-home /home/agent/R/library \
    && chown agent:agent /work /codex-home /home/agent/R /home/agent/R/library

# "Open in: Codex app" (M6): the Codex desktop app reaches this container over
# ssh, through `docker exec` (the host's `um-codex ssh-proxy`, ssh's
# ProxyCommand), so nothing listens on a port. openssh-server brings
# sftp-server too (the app uses sftp for files). The package's host keys are
# removed: each container makes its own at start. `usermod -p '*'` leaves
# agent with no password but not "locked", which sshd (without PAM) would
# refuse even for a key. The app runs agent's login shell, which must be bash.
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-server openssh-sftp-server \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/ssh/ssh_host_* \
    && mkdir -p /run/sshd && chmod 0755 /run/sshd \
    && usermod -p '*' agent \
    && test "$(getent passwd agent | cut -d: -f7)" = /bin/bash
COPY sshd_config /etc/um-codex/sshd_config
COPY profile.sh /etc/profile.d/um-codex.sh
COPY umcodex-token /usr/local/bin/umcodex-token
RUN chmod 0644 /etc/um-codex/sshd_config /etc/profile.d/um-codex.sh \
    && chmod 0755 /usr/local/bin/umcodex-token

# UM-Codex's skills: user skills, which Codex 0.157.1 finds in
# $HOME/.agents/skills (HOME=/home/agent; ext/skills host_roots.rs) and are
# on by default, in the terminal and over ssh alike. Not /etc/codex/skills:
# the launch mounts /etc/codex, hiding the image's. Codex's own bundled
# skills are turned off in managed_config.toml (codex_config.py). ~/.agents
# belongs to agent, so a session can add skills there too (for that launch:
# home isn't kept; a project's .agents/skills under /work is).
COPY --chown=agent:agent skills/ /home/agent/.agents/skills/
COPY project-env.py /usr/local/bin/um-codex-env
COPY dashboard.py /usr/local/bin/um-codex-dashboard
COPY capability-check.py /usr/local/bin/um-codex-capability-check
COPY dashboard-check.js /usr/local/bin/um-codex-dashboard-check
COPY skills-check.py /usr/local/bin/um-codex-skills-check
RUN chown agent:agent /home/agent/.agents \
    && chmod -R a+rX /home/agent/.agents \
    && chmod 0755 /usr/local/bin/um-codex-env /usr/local/bin/um-codex-dashboard /usr/local/bin/um-codex-capability-check \
        /usr/local/bin/um-codex-dashboard-check /usr/local/bin/um-codex-skills-check

USER agent
WORKDIR /work
ENV HOME=/home/agent \
    CODEX_HOME=/codex-home \
    MPLCONFIGDIR=/tmp/matplotlib \
    R_LIBS_USER=/home/agent/R/library

# Runtime is also a diagnostic target; the shipped default stage always
# executes the smoke test. Do not publish the unvalidated runtime target.
# The smoke test's leftovers (caches, Quarto/Jupyter state, R and browser
# temp folders) are removed. Then /codex-home must hold nothing but what
# alpha.3's did (Codex's tmp/arg0 helper links, if anything): Docker copies
# it into every new setup's volume, so an installation id, databases or
# skills left there would be shared by every person's setup.
FROM runtime AS validated
RUN --network=none um-codex-smoke \
    && sudo -n rm -rf /home/agent/.cache /home/agent/.ipython /home/agent/.jupyter /home/agent/.local \
        /tmp/node-compile-cache /tmp/pw-* /tmp/Rtmp* \
    && leftovers="$(find /codex-home -mindepth 1 ! -path /codex-home/tmp ! -path '/codex-home/tmp/arg0' ! -path '/codex-home/tmp/arg0/*')" \
    && if [ -n "$leftovers" ]; then echo "/codex-home must be empty in the image; found:" >&2; echo "$leftovers" >&2; exit 1; fi

ENTRYPOINT []
# Put the base instructions where Codex reads them (they're the app's file,
# so they're overwritten each start), then wait: UM-Codex runs Codex with
# `docker exec -it`.
CMD ["sh", "-c", "cp /etc/um-codex/AGENTS.md \"$CODEX_HOME/AGENTS.md\" && exec sleep infinity"]
