# Adapted from DataLab's backend/src/datalab/sessions/codex_config.py at 6b6fdca.
"""The Codex settings each launch runs with.

The host writes three files into the launch's folder, and that folder is
mounted read-only at /etc/codex in the container (containers.py). Codex reads
them there on Linux; checked in the rust-v0.157.1 source
(codex-rs/config/src/loader, config_requirements.rs):

- `requirements.toml`: what Codex enforces over every other setting. The
  model provider is chosen here (`model_provider`: "exact provider selection,
  overriding local and session configuration") and defined here
  (`model_providers`: each entry replaces any provider of the same name,
  whole), so the base URL is the launch's gateway and the credential is the
  launch's token, never the Toolkit key. Also the model catalog, update
  checks and feedback (exact values), the allowed sandbox modes and, with the
  internet off, web search. Codex refuses to save these keys elsewhere.
- `managed_config.toml`: the top config *layer*, above the person's
  `config.toml`, profiles and `-c` flags (on Unix, Codex's "legacy managed
  config"). The model, approvals, sandbox mode, web search, analytics,
  /work's trust and the browser tool. It isn't above everything: options
  passed as overrides rather than config (`codex -m/-s/-a`, the app server's
  thread/start parameters, the TUI's `/model` for a session) still win for
  the model, which is harmless (every model goes through the gateway). The
  TUI saves a `/model` choice in the person's config.toml, where this layer
  overrides it at the next launch: the setup decides the model. Codex also
  turns this file's `approval_policy` and `sandbox_mode` into requirements
  (the only values allowed, besides read-only), so an override asking for
  another sandbox mode (`-s workspace-write`, say) is refused and Codex falls
  back to read-only, where every command fails (Codex's own sandbox can't run
  in the container): a broken session, not a way out.
- `models.json`: the model catalog (`model_catalog_json`): see model_catalog.

`$CODEX_HOME/config.toml`, in the setup's volume, is the person's own
writable file: Codex saves its preferences there. A config.toml written by
the person can still change their own Codex inside their own container
(tools, MCP servers, hooks, instructions, reasoning, history), but not the
model's way out (the provider and the gateway, enforced above), and no Codex
setting can change what the container reaches: the container and the relay
decide that.

Unlike DataLab, Codex's features stay at Codex's defaults (full power): only
analytics, feedback and update checks are off.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from importlib import resources
from typing import Literal

TOKEN_ENV = "UMCODEX_TOKEN"
GATEWAY_BASE_URL = "http://gateway/v1"

# Where the files go in the container: Codex's own fixed paths on Linux.
CODEX_ETC = "/etc/codex"
REQUIREMENTS_FILE = "requirements.toml"
MANAGED_CONFIG_FILE = "managed_config.toml"
CATALOG_FILE = "models.json"

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


def browser_tools() -> dict[str, bool]:
    """The browser server's tools and whether each is read-only
    (browser_tools.json: the pinned @playwright/mcp's tools/list)."""
    text = resources.files(__package__).joinpath("browser_tools.json").read_text(encoding="utf-8")
    return {name: bool(tool["read_only"]) for name, tool in json.loads(text)["tools"].items()}


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
) -> str:
    """managed_config.toml for one launch: the settings that win over the
    person's own config.toml. The browser tool needs the internet: with the
    internet off it's never added."""
    if approvals not in ("never", "on-request"):
        raise ValueError(f"unknown approval policy {approvals!r}")
    browser = browser and internet
    if browser and browser_asks and approvals == "never":
        approval_policy = GRANULAR_NEVER_BUT_MCP
    else:
        approval_policy = f'"{approvals}"'
    lines = [
        "# Written by UM-Codex for one launch, and mounted read-only. Do not edit.",
        "# Your own Codex settings go in $CODEX_HOME/config.toml; these win over them.",
        f"model = {json.dumps(model)}",  # a JSON string is a valid TOML string
        # The container is the sandbox; Codex's own Linux sandbox needs
        # privileges the container doesn't have.
        'sandbox_mode = "danger-full-access"',
        f"approval_policy = {approval_policy}",
        f'web_search = "{"live" if internet else "disabled"}"',
        "",
        "[analytics]",
        "enabled = false",
        "",
        # "Switch to a newer model" prompts come from a catalog's upgrade
        # offers (UM-Codex's catalog has none: model_catalog), except one that
        # Codex 0.157.1 has built in (tui/src/app/startup_prompts.rs): marked
        # as already seen, so a setup on gpt-5.4-mini isn't offered gpt-6-luna.
        "[notice.model_migrations]",
        '"gpt-5.4-mini" = "gpt-6-luna"',
        "",
        '[projects."/work"]',
        'trust_level = "trusted"',
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
        # Each tool's approval, pinned here too: a per-tool `approval_mode` in
        # config.toml (which the agent can write) would beat the default
        # above (core/src/mcp_tool_call.rs), and this layer beats config.toml.
        # A soft control only: with full access in the container the agent
        # could drive Chromium itself with shell commands.
        for name, read_only in browser_tools().items():
            mode = "approve" if read_only or not browser_asks else "prompt"
            lines += ["", f"[mcp_servers.{BROWSER_SERVER}.tools.{name}]", f'approval_mode = "{mode}"']
        # Code-mode-only models (gpt-5.6-*, gpt-6-*) otherwise get MCP tools
        # nested in their `exec` tool, deferred and unlisted; this keeps the
        # browser's tools direct, top-level model tools
        # (features/src/feature_configs.rs: direct_only_tool_namespaces).
        lines += ["", "[features.code_mode]", f'direct_only_tool_namespaces = ["mcp__{BROWSER_SERVER}"]']
    return "\n".join(lines) + "\n"


def render_requirements(*, internet: bool, catalog: bool = True) -> str:
    """requirements.toml for one launch: what Codex enforces, whatever the
    person's config.toml, profiles or `-c` flags say. `catalog`: models.json
    was written (see model_catalog)."""
    lines = [
        "# Written by UM-Codex for one launch, and mounted read-only. Do not edit.",
        "# Codex enforces these over every other setting.",
        'model_provider = "toolkit"',
        *([f'model_catalog_json = "{CODEX_ETC}/{CATALOG_FILE}"'] if catalog else []),
        "check_for_update_on_startup = false",
        # Defence in depth: managed_config.toml's sandbox_mode already limits
        # the modes the same way (Codex turns it into a requirement); this
        # keeps the limit if that legacy file is ever dropped. Codex requires
        # read-only among the allowed modes.
        'allowed_sandbox_modes = ["read-only", "danger-full-access"]',
        # With the internet off, no web search either (the Toolkit would search
        # for Codex); with it on, the person's choice.
        *([] if internet else ['allowed_web_search_modes = ["disabled"]']),
        "",
        "[feedback]",
        "enabled = false",
        "",
        # Replaces any `toolkit` provider in other settings, whole.
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


def model_catalog(bundled: str, served: Iterable[str], model: str) -> str | None:
    """models.json: Codex's own entries (`bundled`: what `codex debug models
    --bundled` prints in the agent image) for the models the Toolkit serves
    (`served`) and the setup's model, all shown in `/model`, with no upgrade
    offers.

    Codex asks a provider without a catalog for `/models` and can't read the
    Toolkit's answer (`{"object", "total", "data": [{"id", "slug",
    "canonical_slug", "object"}]}`: Codex expects `{"models": [...]}` with
    instructions, tools, reasoning levels and context window per model). It
    then falls back to its own list of OpenAI's models, upgrade offers
    included. With a catalog it never asks, and lists only the catalog's
    models (rust-v0.157.1: models-manager's StaticModelsManager).

    Only models this Codex knows can be listed (the Toolkit's list has no
    settings for the others); the setup's model works even if it isn't one.
    An empty `served` (the Toolkit couldn't be reached) gives the setup's
    model alone; if Codex knows none of them, all of Codex's own models. None
    if `bundled` can't be read: the launch then runs without a catalog."""
    try:
        entries = json.loads(bundled)["models"]
    except (ValueError, TypeError, KeyError):
        return None
    if not isinstance(entries, list):
        return None
    known = [e for e in entries if isinstance(e, dict) and isinstance(e.get("slug"), str)]
    wanted = {*served, model}
    chosen = [{**e, "visibility": "list"} for e in known if e["slug"] in wanted] or known
    if not chosen:
        return None
    return json.dumps({"models": [{**e, "upgrade": None, "availability_nux": None} for e in chosen]})
