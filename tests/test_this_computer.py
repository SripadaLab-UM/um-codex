from __future__ import annotations

import stat
import tomllib
from pathlib import Path

import httpx
import pytest

from umcodex import this_computer as tc
from umcodex.codex_app import ATOMS, StateUnknown

from .conftest import FAKE_KEY


def test_copy_is_separate_from_the_sandbox_copy(tmp_path: Path) -> None:
    home, user_data = tc.copy_paths(tmp_path)
    assert home == tmp_path / "codex-app-local" / "codex-home"
    assert user_data == tmp_path / "codex-app-local" / "user-data"
    command = tc.open_command(Path("/Applications/ChatGPT.app"), tmp_path)
    assert command[:2] == ["/usr/bin/open", "-n"]
    assert f"CODEX_HOME={home}" in command
    assert f"--user-data-dir={user_data}" in command
    assert "codex-app/" not in " ".join(command)


def test_local_config_provider_through_the_relay(tmp_path: Path) -> None:
    token_file = tmp_path / "relay-token"
    existing = '[tui]\ntheme = "dark"\n[model_providers.other]\nbase_url = "http://example.invalid"\n'
    text = tc.local_config(
        existing, port=43210, token_file=token_file, model="gpt-5.6-terra", folders=[tmp_path / "work"]
    )
    config = tomllib.loads(text)
    provider = config["model_providers"]["toolkit"]
    assert config["model_provider"] == "toolkit"
    assert provider["base_url"] == "http://127.0.0.1:43210/relay/v1"
    assert provider["auth"]["command"] == "/bin/cat"
    assert provider["auth"]["args"] == [str(token_file)]
    assert "requires_openai_auth" not in provider and "env_key" not in provider
    assert config["forced_login_method"] == "api"
    assert config["sandbox_mode"] == "danger-full-access"
    assert config["approval_policy"] == "never"
    assert config["projects"][str(tmp_path / "work")] == {"trust_level": "trusted"}
    # The app's own settings are kept.
    assert config["tui"] == {"theme": "dark"}
    assert config["model_providers"]["other"]["base_url"] == "http://example.invalid"
    assert FAKE_KEY not in text


def test_local_config_this_folder_only(tmp_path: Path) -> None:
    text = tc.local_config(
        "",
        port=43210,
        token_file=tmp_path / "t",
        model="m",
        folders=[],
        access="folder",
        approval_policy="on-request",
        internet=False,
    )
    config = tomllib.loads(text)
    assert config["sandbox_mode"] == "workspace-write"
    assert config["approval_policy"] == "on-request"
    assert config["sandbox_workspace_write"] == {"network_access": False}
    with pytest.raises(ValueError):
        tc.local_config("", port=1, token_file=tmp_path / "t", model="m", folders=[], access="anything")


def test_seeded_state_makes_and_selects_the_local_project(tmp_path: Path) -> None:
    folder = tmp_path / "work"
    state = tc.seeded_state({"other": 1}, name="Thesis", folder=folder, seen_models=["gpt-6-sol"], now=1000)
    project = state["local-projects"][state["selected-project"]["projectId"]]
    assert state["selected-project"]["type"] == "local"
    assert project["name"] == "Thesis" and project["rootPaths"] == [str(folder)]
    assert project["createdAt"] == project["updatedAt"] == 1_000_000
    assert state["project-order"][0] == project["id"]
    assert state[ATOMS]["electron:onboarding-projectless-completed"] is True
    assert state[ATOMS]["seen-model-upgrade-list"] == ["gpt-6-sol"]
    assert state["other"] == 1
    # Seeding again doesn't duplicate.
    again = tc.seeded_state(state, name="Thesis", folder=folder, seen_models=["gpt-6-sol"], now=2000)
    assert len(again["local-projects"]) == 1 and again["project-order"].count(project["id"]) == 1
    with pytest.raises(StateUnknown):
        tc.seeded_state({"local-projects": []}, name="x", folder=folder)


def test_relay_port_is_kept(tmp_path: Path) -> None:
    port = tc.relay_port(tmp_path)
    assert tc.relay_port(tmp_path) == port
    assert stat.S_IMODE((tmp_path / "codex-app-local" / "relay-port").stat().st_mode) == 0o600


def test_local_relay_token_file_and_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["authorization"])
        return httpx.Response(200, json={"object": "list", "data": []})

    relay = tc.LocalRelay(lambda: FAKE_KEY, "http://upstream.invalid/v1", tmp_path)
    port = relay.start()
    try:
        relay._server.relay._client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
        assert port == tc.relay_port(tmp_path)
        token = relay.token_file.read_text(encoding="utf-8")
        assert stat.S_IMODE(relay.token_file.stat().st_mode) == 0o600
        assert FAKE_KEY not in token
        base = f"http://127.0.0.1:{port}/relay/v1"
        assert httpx.get(f"{base}/models", timeout=10).status_code == 401
        answer = httpx.get(f"{base}/models", headers={"authorization": f"Bearer {token}"}, timeout=10)
        assert answer.status_code == 200
        assert seen == [f"Bearer {FAKE_KEY}"]
    finally:
        relay.stop()
    assert not relay.token_file.exists()


def test_local_relay_keeps_the_open_copys_token(tmp_path: Path) -> None:
    first = tc.LocalRelay(lambda: FAKE_KEY, "http://upstream.invalid/v1", tmp_path)
    first.start()
    first.stop(forget=False)  # the relay ended; the copy is still open
    again = tc.LocalRelay(lambda: FAKE_KEY, "http://upstream.invalid/v1", tmp_path, keep_token=True)
    assert again.token == first.token
    again.start()
    again.stop()
    assert not again.token_file.exists()
    fresh = tc.LocalRelay(lambda: FAKE_KEY, "http://upstream.invalid/v1", tmp_path, keep_token=True)
    assert fresh.token != first.token
