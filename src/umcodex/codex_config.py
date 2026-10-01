# Adapted from DataLab's backend/src/datalab/sessions/codex_config.py at 6b6fdca.
"""The Codex `config.toml` each launch runs with.

Written by the host and mounted read-only over the setup's Codex home, so
Codex can't change its own provider. It follows ITS's "Codex Setup" articles
for the model settings (a `toolkit` provider on the Toolkit's API), except
that the base URL is the launch's gateway and the credential is the launch's
token, never the Toolkit key.

Unlike DataLab, Codex's features stay at Codex's defaults (full power): only
analytics, feedback and update checks are off.
"""

from __future__ import annotations

import json
from typing import Literal

TOKEN_ENV = "UMCODEX_TOKEN"
GATEWAY_BASE_URL = "http://gateway/v1"

Approvals = Literal["never", "on-request"]


def render(*, model: str, approvals: Approvals, internet: bool) -> str:
    """The config.toml text for one launch."""
    if approvals not in ("never", "on-request"):
        raise ValueError(f"unknown approval policy {approvals!r}")
    lines = [
        "# Written by UM-Codex for one launch, and mounted read-only. Do not edit.",
        f"model = {json.dumps(model)}",  # a JSON string is a valid TOML string
        'model_provider = "toolkit"',
        # The container is the sandbox; Codex's own Linux sandbox needs
        # privileges the container doesn't have.
        'sandbox_mode = "danger-full-access"',
        f'approval_policy = "{approvals}"',
        f'web_search = "{"live" if internet else "disabled"}"',
        "check_for_update_on_startup = false",
        "",
        "[analytics]",
        "enabled = false",
        "",
        "[feedback]",
        "enabled = false",
        "",
        '[projects."/work"]',
        'trust_level = "trusted"',
        "",
        "[model_providers.toolkit]",
        'name = "U-M GPT Toolkit (through UM-Codex)"',
        f'base_url = "{GATEWAY_BASE_URL}"',
        f'env_key = "{TOKEN_ENV}"',
        'wire_api = "responses"',
        # The relay retries failed requests itself, honouring the server's
        # wait (relay.py); one more round from here at most.
        "request_max_retries = 1",
        "stream_max_retries = 2",
        "stream_idle_timeout_ms = 300000",
    ]
    return "\n".join(lines) + "\n"
