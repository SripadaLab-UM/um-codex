# TEST ONLY, not released: the agent image plus an SSH entry point, so the
# Codex desktop app can work inside a UM-Codex container through its SSH
# connections (docs/spikes/2026-10-01-codex-desktop-app.md).
#
# Nothing listens: `um-codex ssh-proxy` runs `sshd -i` (one sshd per
# connection, on the ssh client's stdin/stdout) through `docker exec`.
#
#   docker build -t um-codex-agent:app-test images/agent-app-test
#   (BASE defaults to the locally built um-codex-agent:dev)
ARG BASE=um-codex-agent:dev
FROM ${BASE}

USER root
# openssh-server brings sftp-server too (the app uses `sftp` for files). The
# package's host keys are removed: each container makes its own at start
# (`um-codex app-test`). `usermod -p '*'` leaves agent with no password but
# not "locked", which sshd (without PAM) would refuse even for a key.
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
    && chmod 0755 /usr/local/bin/umcodex-token \
    && ssh-keygen -q -t ed25519 -N '' -f /tmp/check_host_key \
    && /usr/sbin/sshd -t -f /etc/um-codex/sshd_config -h /tmp/check_host_key \
    && rm -f /tmp/check_host_key /tmp/check_host_key.pub

USER agent
# As agent: Codex makes $CODEX_HOME/tmp, which a new setup's volume copies.
RUN codex --version
