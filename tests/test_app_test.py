"""The Codex desktop app test (development only): its files and commands."""

from __future__ import annotations

import os
import stat
import subprocess
import tomllib
from pathlib import Path

from umcodex import app_test, codex_config
from umcodex.containers import Docker, LaunchSpec


def test_the_container_config_reads_the_token_with_a_command():
    text = codex_config.render(
        model="gpt-5.6-terra", approvals="never", internet=True, token_command=app_test.TOKEN_COMMAND
    )
    config = tomllib.loads(text)
    provider = config["model_providers"]["toolkit"]
    # Codex 0.157.1 refuses `auth` together with `env_key`.
    assert "env_key" not in provider
    assert provider["auth"] == {"command": "/usr/local/bin/umcodex-token"}
    assert provider["base_url"] == "http://gateway/v1"
    assert config["forced_login_method"] == "api"
    plain = tomllib.loads(codex_config.render(model="m", approvals="never", internet=False))
    assert plain["model_providers"]["toolkit"]["env_key"] == "UMCODEX_TOKEN"
    assert "auth" not in plain["model_providers"]["toolkit"] and "forced_login_method" not in plain


def test_the_app_copys_config_uses_the_relay_and_a_token_file(tmp_path):
    config = tomllib.loads(app_test.local_config(41234, tmp_path / "launch token"))
    provider = config["model_providers"]["toolkit"]
    assert config["model_provider"] == "toolkit" and config["forced_login_method"] == "api"
    assert provider["base_url"] == "http://127.0.0.1:41234/relay/v1"
    assert provider["auth"] == {"command": "/bin/cat", "args": [str(tmp_path / "launch token")]}
    assert "env_key" not in provider and "requires_openai_auth" not in provider


def test_the_host_block(tmp_path):
    block = app_test.host_block(proxy=["/a b/um-codex", "ssh-proxy", "app-test"], home=tmp_path)
    lines = [line.strip() for line in block.splitlines()]
    assert "Host umcodex-test" in lines
    for wanted in (
        "User agent",
        "IdentityFile ~/.ssh/um-codex/app-test_ed25519",
        "IdentitiesOnly yes",
        "ForwardAgent no",
        "StrictHostKeyChecking no",
        "UserKnownHostsFile /dev/null",
        "LogLevel ERROR",
        'ProxyCommand "/a b/um-codex" ssh-proxy app-test',
    ):
        assert wanted in lines


def test_the_include_line_goes_at_the_top_once_with_a_backup(tmp_path):
    ssh = tmp_path / ".ssh"
    assert app_test.add_include(tmp_path) == "created"
    assert (ssh / "config").read_text() == "Include ~/.ssh/um-codex/config\n"
    assert stat.S_IMODE((ssh / "config").stat().st_mode) == 0o600
    (ssh / "config").write_text("Host example\n  User me\n")
    os.chmod(ssh / "config", 0o644)
    assert app_test.add_include(tmp_path) == "added"
    assert (ssh / "config").read_text() == "Include ~/.ssh/um-codex/config\nHost example\n  User me\n"
    assert (ssh / "config.um-codex-backup").read_text() == "Host example\n  User me\n"
    assert stat.S_IMODE((ssh / "config").stat().st_mode) == 0o644  # its own permissions kept
    assert app_test.add_include(tmp_path) == "already there"
    assert (ssh / "config").read_text().count("Include ~/.ssh/um-codex/config") == 1


def test_the_ssh_files_are_private_and_removed_by_stop(tmp_path):
    app_test.write_ssh_files(["/x/um-codex", "ssh-proxy", "app-test"], home=tmp_path)
    folder = tmp_path / ".ssh" / "um-codex"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    for name in ("config", "app-test_ed25519"):
        assert stat.S_IMODE((folder / name).stat().st_mode) == 0o600
    assert (folder / "app-test_ed25519.pub").read_text().startswith("ssh-ed25519 ")
    assert len(app_test.remove_ssh_files(tmp_path)) == 3
    assert list(folder.iterdir()) == []


def test_the_app_copy_is_opened_like_codex_demo_with_the_link_in_its_arguments(tmp_path):
    command = app_test.open_app_command(tmp_path, app_test.deep_link())
    assert command[:2] == ["/usr/bin/open", "-n"]
    assert f"CODEX_HOME={tmp_path / 'codex-home'}" in command
    assert f"CODEX_ELECTRON_USER_DATA_PATH={tmp_path / 'user-data'}" in command
    after = command[command.index("--args") + 1 :]
    assert after == [
        f"--user-data-dir={tmp_path / 'user-data'}",
        "codex://settings/connections/ssh/add?name=umcodex-test&projectPath=/work&enabled=true",
    ]


def test_the_proxy_finds_the_agent_by_label():
    calls = []

    def run(command, **options):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "umcodex-ab12cd34-agent\n", "")

    assert app_test.find_agent(Docker(run), "app-test", "inst") == "umcodex-ab12cd34-agent"
    assert "label=umcodex.ssh=app-test" in calls[0] and "label=umcodex.instance=inst" in calls[0]
    assert "status=running" in calls[0]


def test_extra_labels_go_on_every_container_and_network(tmp_path: Path):
    spec = LaunchSpec(
        launch_id="ab12cd34", instance="inst", setup_id="app-test", agent_image="a", gateway_image="g",
        internet=True, folders=(), config_file=tmp_path / "c", launch_note=tmp_path / "n",
        gateway_conf=tmp_path / "g", env_file=tmp_path / "e", extra_labels=(("umcodex.ssh", "app-test"),),
    )  # fmt: skip
    for command in [*spec.network_commands(), spec.gateway_commands()[0], spec.agent_commands()[0]]:
        assert "umcodex.ssh=app-test" in command, command
