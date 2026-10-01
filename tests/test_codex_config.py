"""The Codex settings each launch runs with: requirements.toml,
managed_config.toml and the model catalog."""

from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from umcodex import toolkit
from umcodex.codex_config import (
    BROWSER_ARGS,
    BROWSER_COMMAND,
    BROWSER_ENV,
    TOKEN_ENV,
    browser_tools,
    model_catalog,
    render,
    render_requirements,
)

DATA = Path(__file__).parent / "data"
# `codex debug models --bundled` in the agent image (Codex 0.157.1), four of
# its eleven entries, with the instruction texts shortened.
BUNDLED = (DATA / "codex-0.157.1-bundled-models.json").read_text()
# The Toolkit's GET /v1/models answer (the fields and ids; taken 2026-10-01).
TOOLKIT_MODELS = json.loads((DATA / "toolkit-models.json").read_text())


def parsed(**options) -> dict:
    defaults = {"model": "gpt-5.6-terra", "approvals": "never", "internet": False}
    return tomllib.loads(render(**{**defaults, **options}))


def requirements(**options) -> dict:
    return tomllib.loads(render_requirements(**{"internet": False, **options}))


def test_the_model_provider_is_required_and_is_the_gateway_with_the_launch_token():
    required = requirements()
    assert required["model_provider"] == "toolkit"
    provider = required["model_providers"]["toolkit"]
    assert provider["base_url"] == "http://gateway/v1"
    assert provider["env_key"] == TOKEN_ENV == "UMCODEX_TOKEN"
    assert provider["wire_api"] == "responses"
    assert provider["request_max_retries"] == 1
    # The provider is in requirements.toml only, where nothing can override it.
    config = parsed()
    assert "model_provider" not in config and "model_providers" not in config


def test_the_model_is_the_setups_in_the_top_layer():
    assert parsed()["model"] == "gpt-5.6-terra"
    assert parsed(model="gpt-6-sol")["model"] == "gpt-6-sol"


def test_requirements_hold_the_catalog_and_what_codex_enforces_exactly():
    required = requirements()
    assert required["model_catalog_json"] == "/etc/codex/models.json"
    assert required["check_for_update_on_startup"] is False
    assert required["feedback"] == {"enabled": False}
    # Codex refuses an allow-list without read-only (config_requirements.rs).
    assert required["allowed_sandbox_modes"] == ["read-only", "danger-full-access"]
    assert "model_catalog_json" not in requirements(catalog=False)


def test_no_web_search_without_the_internet():
    assert requirements(internet=False)["allowed_web_search_modes"] == ["disabled"]
    assert "allowed_web_search_modes" not in requirements(internet=True)


def test_requirements_use_only_keys_codex_0_157_1_knows():
    # ConfigRequirementsToml's fields (rust-v0.157.1 config_requirements.rs)
    # that UM-Codex uses; anything else would be ignored, with a warning.
    known = {
        "model_provider", "model_providers", "model_catalog_json", "check_for_update_on_startup",
        "feedback", "allowed_sandbox_modes", "allowed_web_search_modes",
    }  # fmt: skip
    assert set(requirements()) <= known and set(requirements(internet=True)) <= known


def test_the_container_is_the_sandbox():
    config = parsed()
    assert config["sandbox_mode"] == "danger-full-access"
    assert config["projects"]["/work"]["trust_level"] == "trusted"


@pytest.mark.parametrize("approvals", ["never", "on-request"])
def test_approvals(approvals):
    assert parsed(approvals=approvals)["approval_policy"] == approvals


def test_unknown_approvals_are_refused():
    with pytest.raises(ValueError):
        render(model="gpt-5.6-terra", approvals="sometimes", internet=False)  # type: ignore[arg-type]


def test_web_search_follows_the_internet_switch():
    assert parsed(internet=True)["web_search"] == "live"
    assert parsed(internet=False)["web_search"] == "disabled"


def test_analytics_is_off_and_the_built_in_model_switch_is_marked_seen():
    config = parsed()
    assert config["analytics"]["enabled"] is False
    # Codex 0.157.1's one built-in migration (tui/src/app/startup_prompts.rs).
    assert config["notice"]["model_migrations"] == {"gpt-5.4-mini": "gpt-6-luna"}


def test_no_key_or_auth_file_settings():
    for text in (
        render(model="gpt-5.6-terra", approvals="never", internet=True),
        render_requirements(internet=True),
    ):
        assert "api.toolkit" not in text and "auth" not in text.lower() and "sk-" not in text


def test_a_strange_model_name_stays_one_toml_string():
    config = parsed(model='gpt"x\nmodel_provider = "openai')
    assert config["model"] == 'gpt"x\nmodel_provider = "openai' and "model_provider" not in config


# --- The model catalog --------------------------------------------------------


def served() -> list[str]:
    """What the launch passes: the Toolkit's list as toolkit.list_models reads it."""
    return sorted({m["id"] for m in TOOLKIT_MODELS["data"] if toolkit.text_model(m["id"])})


def catalog(served_models, model="gpt-5.6-terra", bundled=BUNDLED) -> list[dict]:
    text = model_catalog(bundled, served_models, model)
    assert text is not None
    return json.loads(text)["models"]


def test_the_catalog_is_the_toolkits_models_that_codex_knows():
    models = catalog(served())
    # codex-auto-review isn't served by the Toolkit; gpt-5.4 is, though Codex hides it.
    assert [m["slug"] for m in models] == ["gpt-6-sol", "gpt-5.6-terra", "gpt-5.4"]
    assert all(m["visibility"] == "list" for m in models)
    # Codex's own settings for each model are kept as they are.
    terra = json.loads(BUNDLED)["models"][1]
    assert models[1] == {**terra, "upgrade": None, "visibility": "list"}


def test_the_catalog_offers_no_upgrades():
    # Codex 0.157.1's own list offers gpt-6-sol in place of gpt-5.6-terra: the
    # prompt that switched a real launch's model.
    assert json.loads(BUNDLED)["models"][1]["upgrade"]["model"] == "gpt-6-sol"
    assert all(m["upgrade"] is None and m["availability_nux"] is None for m in catalog(served()))


def test_the_setups_model_is_in_the_catalog_even_when_the_toolkit_cant_say():
    assert [m["slug"] for m in catalog([], model="gpt-5.4")] == ["gpt-5.4"]


def test_a_catalog_with_no_known_model_falls_back_to_codexs_own_list():
    models = catalog(["gpt-4o"], model="gpt-4o")
    assert [m["slug"] for m in models] == [m["slug"] for m in json.loads(BUNDLED)["models"]]
    assert all(m["upgrade"] is None for m in models)


@pytest.mark.parametrize("bundled", ["", "not json", "[]", '{"models": {}}', '{"models": []}'])
def test_no_catalog_when_codexs_list_cant_be_read(bundled):
    assert model_catalog(bundled, served(), "gpt-5.6-terra") is None


def test_the_toolkits_own_answer_is_not_what_codex_reads():
    # Codex decodes {"models": [...]}; the Toolkit sends {"object", "total", "data"}.
    assert "models" not in TOOLKIT_MODELS and set(TOOLKIT_MODELS["data"][0]) == {
        "id", "slug", "canonical_slug", "object"
    }  # fmt: skip


# --- The browser tool (M2b) -----------------------------------------------------


def test_no_browser_tool_unless_asked():
    assert "mcp_servers" not in parsed(internet=True)
    assert "mcp_servers" not in parsed(internet=True, browser=False)


def test_no_browser_tool_without_the_internet():
    config = parsed(internet=False, browser=True)
    assert "mcp_servers" not in config
    assert config["approval_policy"] == "never"


def test_the_browser_tool_runs_in_the_container_over_stdio():
    server = parsed(internet=True, browser=True)["mcp_servers"]["browser"]
    assert server["command"] == "/usr/local/bin/playwright-mcp"
    assert server["args"] == [
        "--headless", "--browser", "chromium", "--isolated", "--output-dir", "/tmp/um-codex-browser"
    ]  # fmt: skip
    assert server["cwd"] == "/work"
    # Codex passes MCP servers only a few environment variables.
    assert server["env"] == {"PLAYWRIGHT_BROWSERS_PATH": "/opt/ms-playwright"}
    assert server["startup_timeout_sec"] >= 30 and server["tool_timeout_sec"] >= 60
    assert "url" not in server  # stdio, not HTTP


@pytest.mark.parametrize(
    ("approvals", "asks", "mode", "policy"),
    [
        # Codex 0.157.1 auto-approves MCP calls under "never" with full access,
        # so asking needs the granular policy (commands still never asked).
        (
            "never",
            True,
            "writes",
            {
                "granular": {
                    "sandbox_approval": False,
                    "rules": False,
                    "mcp_elicitations": True,
                    "request_permissions": False,
                    "skill_approval": False,
                }
            },
        ),
        ("never", False, "approve", "never"),
        ("on-request", True, "writes", "on-request"),
        ("on-request", False, "approve", "on-request"),
    ],
)
def test_browser_approvals(approvals, asks, mode, policy):
    config = parsed(internet=True, browser=True, browser_asks=asks, approvals=approvals)
    assert config["mcp_servers"]["browser"]["default_tools_approval_mode"] == mode
    assert config["approval_policy"] == policy


def test_the_browser_tools_stay_direct_for_code_mode_models():
    config = parsed(internet=True, browser=True)
    assert config["features"]["code_mode"]["direct_only_tool_namespaces"] == ["mcp__browser"]
    assert "features" not in parsed(internet=True)


@pytest.mark.parametrize("asks", [True, False])
def test_every_browser_tools_approval_is_pinned(asks):
    tools = parsed(internet=True, browser=True, browser_asks=asks)["mcp_servers"]["browser"]["tools"]
    assert set(tools) == set(browser_tools()) and len(tools) == 25
    for name, read_only in browser_tools().items():
        expected = "prompt" if asks and not read_only else "approve"
        assert tools[name] == {"approval_mode": expected}, name
    if asks:
        assert tools["browser_navigate"]["approval_mode"] == "prompt"
        assert tools["browser_snapshot"]["approval_mode"] == "approve"


def image_tools_list(image: str) -> dict[str, bool] | None:
    """The browser server's tools/list in the agent image, or None without Docker or the image."""
    if not shutil.which("docker"):
        return None
    try:
        if subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=30).returncode:
            return None
    except (OSError, subprocess.TimeoutExpired):
        return None
    client = (
        "import json,subprocess,sys\n"
        "p=subprocess.Popen(sys.argv[1:],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)\n"
        "def send(m): p.stdin.write(json.dumps(m)+'\\n'); p.stdin.flush()\n"
        "def recv(i):\n"
        "    while True:\n"
        "        m=json.loads(p.stdout.readline())\n"
        "        if m.get('id')==i: return m\n"
        "send({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18',"
        "'capabilities':{},'clientInfo':{'name':'t','version':'0'}}})\n"
        "recv(1); send({'jsonrpc':'2.0','method':'notifications/initialized'})\n"
        "send({'jsonrpc':'2.0','id':2,'method':'tools/list'})\n"
        "print(json.dumps({t['name']:bool((t.get('annotations') or {}).get('readOnlyHint'))"
        " for t in recv(2)['result']['tools']})); p.kill()\n"
    )
    done = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--label", "umcodex.app=um-codex-test", image,
         "python3", "-c", client, BROWSER_COMMAND, *BROWSER_ARGS],
        capture_output=True, text=True, timeout=180,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_browser_tool_list_matches_the_agent_images():
    from umcodex.containers import agent_image

    found = image_tools_list(agent_image())
    if found is None:
        pytest.skip("needs Docker and the agent image")
    assert found == browser_tools()


def test_the_smoke_test_starts_the_browser_the_same_way():
    smoke = (Path(__file__).parents[1] / "images" / "agent" / "smoke.sh").read_text()
    assert " ".join(["--", BROWSER_COMMAND, *BROWSER_ARGS]) in smoke
    dockerfile = (Path(__file__).parents[1] / "images" / "agent" / "Dockerfile").read_text()
    for name, value in BROWSER_ENV.items():
        assert f"ENV {name}={value}" in dockerfile
