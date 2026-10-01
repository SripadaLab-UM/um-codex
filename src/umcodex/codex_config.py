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

# The browser tool (M2b): Playwright's MCP server, installed in the agent
# image (images/agent/Dockerfile), started by Codex over stdio inside the
# container. Headless Chromium (Playwright's own build, so amd64 and arm64
# both work), a profile kept in memory only (`--isolated`: no logins, nothing
# kept), and automatically named files (unnamed screenshots, logs) in the
# container's /tmp. A screenshot saved under a name Codex chooses goes in
# /work (the server's working folder), so only when the person asks for one.
# images/agent/smoke.sh starts it with the same arguments (a test checks).
BROWSER_SERVER = "browser"
BROWSER_COMMAND = "/usr/local/bin/playwright-mcp"
BROWSER_ARGS = (
    "--headless",
    "--browser", "chromium",
    "--isolated",
    "--output-dir", "/tmp/um-codex-browser",
)  # fmt: skip
# Codex starts MCP servers with only a few environment variables (HOME, PATH
# and the like), so where the image put Chromium is passed on here.
BROWSER_ENV = {"PLAYWRIGHT_BROWSERS_PATH": "/opt/ms-playwright"}

# Codex 0.157.1 auto-approves every MCP tool call when `approval_policy` is
# "never" with full access (codex-mcp's mcp_permission_prompt_is_auto_approved),
# and turns down MCP approval prompts under "never". So when the person wants
# to approve browser actions but lets Codex run commands without asking, the
# policy is "granular": the same as "never" for commands, patches, permissions
# and network, with MCP approval prompts shown. The other differences from
# "never" (checked in the rust-v0.157.1 source): installing a skill's MCP
# dependencies asks "Install MCP servers?" (mcp_skill_dependencies.rs); MCP
# elicitations with an empty form are shown instead of accepted (session/mcp.rs);
# the model's permissions instructions describe "granular"; Codex's status line
# shows it; and hooks see permission_mode "default".
GRANULAR_NEVER_BUT_MCP = (
    "{ granular = { sandbox_approval = false, rules = false, mcp_elicitations = true, "
    "request_permissions = false, skill_approval = false } }"
)


def render(
    *,
    model: str,
    approvals: Approvals,
    internet: bool,
    browser: bool = False,
    browser_asks: bool = True,
    token_command: str | None = None,
) -> str:
    """The config.toml text for one launch. The browser tool needs the
    internet: with the internet off it's never added.

    `token_command` (the Codex desktop app test only): Codex gets the launch
    token by running this command (a provider `auth.command`) instead of from
    the UMCODEX_TOKEN variable, which ssh sessions don't have. It also sets
    `forced_login_method = "api"`, so no ChatGPT sign-in is offered in the
    container. Both checked against the rust-v0.157.1 source: `auth` can't be
    combined with `env_key` (model-provider-info's validate), and
    ForcedLoginMethod is "chatgpt" or "api"."""
    if approvals not in ("never", "on-request"):
        raise ValueError(f"unknown approval policy {approvals!r}")
    browser = browser and internet
    if browser and browser_asks and approvals == "never":
        approval_policy = GRANULAR_NEVER_BUT_MCP
    else:
        approval_policy = f'"{approvals}"'
    lines = [
        "# Written by UM-Codex for one launch, and mounted read-only. Do not edit.",
        f"model = {json.dumps(model)}",  # a JSON string is a valid TOML string
        'model_provider = "toolkit"',
        # The container is the sandbox; Codex's own Linux sandbox needs
        # privileges the container doesn't have.
        'sandbox_mode = "danger-full-access"',
        f"approval_policy = {approval_policy}",
        f'web_search = "{"live" if internet else "disabled"}"',
        "check_for_update_on_startup = false",
        *(['forced_login_method = "api"'] if token_command else []),
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
        *([] if token_command else [f'env_key = "{TOKEN_ENV}"']),
        'wire_api = "responses"',
        # The relay retries failed requests itself, honouring the server's
        # wait (relay.py); one more round from here at most.
        "request_max_retries = 1",
        "stream_max_retries = 2",
        "stream_idle_timeout_ms = 300000",
    ]
    if token_command:
        lines += [
            "",
            "[model_providers.toolkit.auth]",
            f"command = {json.dumps(token_command)}",
        ]
    if browser:
        lines += [
            "",
            f"[mcp_servers.{BROWSER_SERVER}]",
            f"command = {json.dumps(BROWSER_COMMAND)}",
            f"args = {json.dumps(list(BROWSER_ARGS))}",
            'cwd = "/work"',
            "env = { " + ", ".join(f"{k} = {json.dumps(v)}" for k, v in BROWSER_ENV.items()) + " }",
            # The first start launches Chromium; a slow page can take a while.
            "startup_timeout_sec = 60",
            "tool_timeout_sec = 180",
            # "writes": the person approves each browser action (opening a
            # page, clicking, typing); tools the server marks read-only
            # (snapshot, screenshot, find, console and network lists, wait)
            # run unasked. "approve": none are asked about.
            f'default_tools_approval_mode = "{"writes" if browser_asks else "approve"}"',
        ]
    return "\n".join(lines) + "\n"
