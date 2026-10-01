"""The config.toml each launch's Codex runs with."""

from __future__ import annotations

import tomllib

import pytest

from umcodex.codex_config import TOKEN_ENV, render


def parsed(**options) -> dict:
    defaults = {"model": "gpt-5.6-terra", "approvals": "never", "internet": False}
    return tomllib.loads(render(**{**defaults, **options}))


def test_the_model_provider_is_the_gateway_with_the_launch_token():
    config = parsed()
    assert config["model"] == "gpt-5.6-terra"
    assert config["model_provider"] == "toolkit"
    provider = config["model_providers"]["toolkit"]
    assert provider["base_url"] == "http://gateway/v1"
    assert provider["env_key"] == TOKEN_ENV == "UMCODEX_TOKEN"
    assert provider["wire_api"] == "responses"
    assert provider["request_max_retries"] == 1


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


def test_analytics_feedback_and_update_checks_are_off():
    config = parsed()
    assert config["analytics"]["enabled"] is False
    assert config["feedback"]["enabled"] is False
    assert config["check_for_update_on_startup"] is False


def test_no_key_or_auth_file_settings():
    text = render(model="gpt-5.6-terra", approvals="never", internet=True)
    assert "api.toolkit" not in text and "auth" not in text.lower() and "sk-" not in text


def test_a_strange_model_name_stays_one_toml_string():
    assert parsed(model='gpt"x\nmodel_provider = "openai')["model_provider"] == "toolkit"
