"""M6, "Open in: Codex app": the ssh side, the container side, the app copy,
and the launch held while the app uses it."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from umcodex import codex_app, codex_config, launch
from umcodex.containers import Docker, LaunchSpec
from umcodex.setups import Setup

# --- Codex's settings in the container ------------------------------------------


def test_an_app_launch_reads_the_token_with_a_command():
    requirements = tomllib.loads(codex_config.render_requirements(internet=True, app=True))
    provider = requirements["model_providers"]["toolkit"]
    # Codex 0.157.1 refuses `auth` together with `env_key`.
    assert "env_key" not in provider
    assert provider["auth"] == {"command": "/usr/local/bin/umcodex-token"}
    assert provider["base_url"] == "http://gateway/v1"
    assert requirements["model_provider"] == "toolkit"
    managed = tomllib.loads(codex_config.render(model="m", approvals="never", internet=True, app=True))
    assert managed["forced_login_method"] == "api"
    # Only full access: the app's own choice of permissions (":workspace" by
    # default) falls back to it instead of a sandbox the container can't make.
    assert requirements["default_permissions"] == ":danger-full-access"
    assert requirements["allowed_permission_profiles"] == {
        ":danger-full-access": True,
        ":read-only": False,
        ":workspace": False,
    }


def test_a_terminal_launch_keeps_the_token_variable():
    requirements = tomllib.loads(codex_config.render_requirements(internet=False))
    provider = requirements["model_providers"]["toolkit"]
    assert provider["env_key"] == "UMCODEX_TOKEN" and "auth" not in provider
    assert "allowed_permission_profiles" not in requirements and "default_permissions" not in requirements
    managed = tomllib.loads(codex_config.render(model="m", approvals="never", internet=False))
    assert "forced_login_method" not in managed


def test_the_image_files_agree_with_the_code():
    image = Path(__file__).parent.parent / "images" / "agent"
    helper = (image / "umcodex-token").read_text()
    assert f"exec cat {codex_app.TOKEN_FILE}" in helper
    dockerfile = (image / "Dockerfile").read_text()
    assert f"COPY umcodex-token {codex_config.TOKEN_COMMAND}" in dockerfile
    assert "COPY sshd_config /etc/um-codex/sshd_config" in dockerfile
    assert codex_app.SSHD[-1] == "/etc/um-codex/sshd_config"
    sshd = {
        line.split()[0]: line.split(None, 1)[1]
        for line in (image / "sshd_config").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    for key, value in {
        "AllowUsers": "agent",
        "PermitRootLogin": "no",
        "AuthenticationMethods": "publickey",
        "PasswordAuthentication": "no",
        "KbdInteractiveAuthentication": "no",
        "AllowAgentForwarding": "no",
        "AllowTcpForwarding": "local",
        "X11Forwarding": "no",
        "PermitTunnel": "no",
        "GatewayPorts": "no",
    }.items():
        assert sshd[key] == value, key
    assert "ListenAddress" not in sshd and "Port" not in sshd
    assert "CODEX_HOME=/codex-home" in (image / "profile.sh").read_text()


# --- The Include line ----------------------------------------------------------------


def test_the_include_line_goes_at_the_top_once_with_a_backup(ssh_home):
    ssh = ssh_home / ".ssh"
    assert not codex_app.include_present()
    assert codex_app.add_include() == "created"
    assert (ssh / "config").read_text() == "Include ~/.ssh/um-codex/config\n"
    assert stat.S_IMODE((ssh / "config").stat().st_mode) == 0o600
    assert codex_app.include_present()

    (ssh / "config").write_text("Host example\n  User me\n")
    os.chmod(ssh / "config", 0o644)
    assert not codex_app.include_present()
    assert codex_app.add_include() == "added"
    assert (ssh / "config").read_text() == "Include ~/.ssh/um-codex/config\nHost example\n  User me\n"
    assert (ssh / "config.um-codex-backup").read_text() == "Host example\n  User me\n"
    if sys.platform != "win32":
        assert stat.S_IMODE((ssh / "config").stat().st_mode) == 0o644  # its own permissions kept
    assert codex_app.add_include() == "already there"
    assert (ssh / "config").read_text().count("Include ~/.ssh/um-codex/config") == 1


def test_an_include_inside_a_host_block_doesnt_count(ssh_home):
    ssh = ssh_home / ".ssh"
    ssh.mkdir()
    (ssh / "config").write_text("Host a\n  User me\nInclude ~/.ssh/um-codex/config\n")
    assert not codex_app.include_present()  # the app (and ssh) take it as part of Host a
    codex_app.add_include()
    assert (ssh / "config").read_text().startswith("Include ~/.ssh/um-codex/config\nHost a\n")


def test_uninstall_takes_the_line_out_and_the_backup_if_nothing_else_changed(ssh_home):
    ssh = ssh_home / ".ssh"
    ssh.mkdir()
    (ssh / "config").write_text("Host example\n  User me\n")
    codex_app.add_include()
    done = codex_app.remove_include()
    assert (ssh / "config").read_text() == "Host example\n  User me\n"
    assert not (ssh / "config.um-codex-backup").exists()
    assert len(done) == 2


def test_uninstall_keeps_the_backup_when_the_person_changed_the_file(ssh_home):
    ssh = ssh_home / ".ssh"
    ssh.mkdir()
    (ssh / "config").write_text("Host example\n")
    codex_app.add_include()
    with (ssh / "config").open("a") as file:
        file.write("Host another\n")
    codex_app.remove_include()
    assert (ssh / "config").read_text() == "Host example\nHost another\n"
    assert (ssh / "config.um-codex-backup").read_text() == "Host example\n"


def test_uninstall_removes_a_config_it_made_for_its_one_line(ssh_home):
    codex_app.add_include()
    codex_app.remove_include()
    assert not (ssh_home / ".ssh" / "config").exists()
    assert codex_app.remove_include() == []


def test_the_terminal_asks_before_adding_the_line(ssh_home):
    said: list[str] = []
    assert not codex_app.ask_for_include(lambda _: "n", said.append)
    assert not (ssh_home / ".ssh" / "config").exists()
    assert codex_app.INCLUDE_EXPLAINED in said
    assert codex_app.ask_for_include(lambda _: "y", said.append)
    assert codex_app.include_present()


# --- UM-Codex's own ssh files ------------------------------------------------------------


PROXY = ["/Users/x/Library/Application Support/UM-Codex/app/bin/um-codex", "ssh-proxy", "thesis-a1b2c3"]


def test_the_host_block():
    block = codex_app.host_block("thesis-a1b2c3", [*PROXY, "--docker", "/usr/local/bin/docker"])
    lines = [line.strip() for line in block.splitlines()]
    assert "Host umcodex-thesis-a1b2c3" in lines
    for wanted in (
        "User agent",
        "IdentityFile ~/.ssh/um-codex/thesis-a1b2c3_ed25519",
        "IdentitiesOnly yes",
        "IdentityAgent none",
        "ForwardAgent no",
        "ForwardX11 no",
        "StrictHostKeyChecking no",
        "UserKnownHostsFile /dev/null",
        'ProxyCommand "/Users/x/Library/Application Support/UM-Codex/app/bin/um-codex" ssh-proxy '
        "thesis-a1b2c3 --docker /usr/local/bin/docker",
    ):
        assert wanted in lines, wanted


def test_proxy_command_words_are_safe_for_ssh():
    assert codex_app._ssh_arg("C:\\Program Files\\UM-Codex\\um-codex.exe") == (
        '"C:\\Program Files\\UM-Codex\\um-codex.exe"'
    )
    assert codex_app._ssh_arg("/a/100%/b") == "/a/100%%/b"  # ssh's own % tokens
    with pytest.raises(ValueError):
        codex_app._ssh_arg('/a"b')


@pytest.mark.skipif(sys.platform == "win32", reason="the Codex app is Mac only for now")
def test_ssh_reads_the_host_as_written(ssh_home, tmp_path):
    """The real ssh client's view of the block (`ssh -G`), when it's here."""
    if not (ssh := _which("ssh")):
        pytest.skip("no ssh client here")
    config = tmp_path / "config"
    config.write_text(codex_app.host_block("thesis-a1b2c3", PROXY))
    done = subprocess.run(
        [ssh, "-G", "-F", str(config), "umcodex-thesis-a1b2c3"], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    seen = dict(line.split(" ", 1) for line in done.stdout.splitlines() if " " in line)
    assert seen["user"] == "agent"
    assert seen["forwardagent"] == "no"
    assert seen["identitiesonly"] == "yes"
    assert seen["proxycommand"] == f'"{PROXY[0]}" ssh-proxy thesis-a1b2c3'


def _which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


def test_keys_and_config_are_private_and_a_deleted_setup_goes(ssh_home):
    if not _which("ssh-keygen"):
        pytest.skip("no ssh-keygen here")
    for setup_id in ("thesis-a1b2c3", "data-d4e5f6"):
        public = codex_app.ensure_key(setup_id)
        assert public.read_text().startswith("ssh-ed25519 ")
    path = codex_app.write_config(lambda setup_id: ["/x/um-codex", "ssh-proxy", setup_id])
    folder = ssh_home / ".ssh" / "um-codex"
    if sys.platform != "win32":
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700
        for name in ("config", "thesis-a1b2c3_ed25519", "data-d4e5f6_ed25519"):
            assert stat.S_IMODE((folder / name).stat().st_mode) == 0o600
    text = path.read_text()
    assert "Host umcodex-thesis-a1b2c3" in text and "Host umcodex-data-d4e5f6" in text
    key = (folder / "thesis-a1b2c3_ed25519").read_bytes()
    codex_app.ensure_key("thesis-a1b2c3")
    assert (folder / "thesis-a1b2c3_ed25519").read_bytes() == key  # kept between launches

    codex_app.forget_setup(
        "data-d4e5f6",
    )
    assert not (folder / "data-d4e5f6_ed25519").exists()
    assert codex_app.known_setups() == ["thesis-a1b2c3"]
    assert codex_app.remove_ssh_files() and not folder.exists()


def test_an_odd_setup_id_gets_no_key(ssh_home):
    with pytest.raises(ValueError):
        codex_app.ensure_key("../x")


# --- The proxy and the container ------------------------------------------------------------


def test_the_proxy_finds_the_agent_by_label():
    calls = []

    def run(command, **options):
        calls.append(command)
        return subprocess.CompletedProcess(
            command, 0, "umcodex-ab12cd34-agent\numcodex-ab12cd34-gateway\n", ""
        )

    assert codex_app.find_agent(Docker(run), "thesis-a1b2c3", "inst") == "umcodex-ab12cd34-agent"
    assert "label=umcodex.ssh=thesis-a1b2c3" in calls[0] and "label=umcodex.instance=inst" in calls[0]
    assert "status=running" in calls[0]


def test_the_proxy_says_so_when_nothing_runs(tmp_path, capsys):
    docker = tmp_path / "docker"
    docker.write_text("#!/bin/sh\nexit 0\n")
    docker.chmod(0o755)
    if sys.platform == "win32":
        pytest.skip("a shell script stands in for docker")
    assert codex_app.ssh_proxy("thesis-a1b2c3", str(docker)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # stdout is ssh's connection
    assert "umcodex-thesis-a1b2c3 isn't running" in captured.err


def test_extra_labels_go_on_every_container_and_network(tmp_path: Path):
    spec = LaunchSpec(
        launch_id="ab12cd34", instance="inst", setup_id="thesis", agent_image="a", gateway_image="g",
        internet=True, folders=(), codex_etc=tmp_path / "codex", launch_note=tmp_path / "n",
        gateway_conf=tmp_path / "g", env_file=tmp_path / "e", extra_labels=(("umcodex.ssh", "thesis"),),
    )  # fmt: skip
    for command in [*spec.network_commands(), spec.gateway_commands()[0], spec.agent_commands()[0]]:
        assert "umcodex.ssh=thesis" in command, command


def test_the_container_is_prepared_as_root_with_the_key_on_stdin(tmp_path):
    public = tmp_path / "k.pub"
    public.write_text("ssh-ed25519 AAAA um-codex thesis\n")
    calls = []

    def run(command, **options):
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 0, "", "")

    codex_app.prepare_container(Docker(run), "umcodex-ab12cd34-agent", public, run=run)
    command, options = calls[0]
    assert command[:6] == ["docker", "exec", "-i", "-u", "root", "umcodex-ab12cd34-agent"]
    assert options["input"] == public.read_bytes()
    script = command[-1]
    assert '"$UMCODEX_TOKEN"' in script and "/run/um-codex/token" in script  # never the token itself
    assert "authorized_keys" in script and "ssh_host_ed25519_key" in script


# --- The app copy -------------------------------------------------------------------------------


def _fake_app(folder: Path, bundle_id: str = codex_app.APP_BUNDLE_ID) -> Path:
    import plistlib

    app = folder / "ChatGPT.app"
    (app / "Contents").mkdir(parents=True)
    with (app / "Contents" / "Info.plist").open("wb") as file:
        plistlib.dump({"CFBundleIdentifier": bundle_id, "CFBundleExecutable": "ChatGPT"}, file)
    return app


def test_the_app_is_found_by_its_bundle_id(tmp_path):
    home = tmp_path / "home"
    nothing = lambda command, **options: subprocess.CompletedProcess(command, 0, "", "")  # noqa: E731
    _fake_app(home / "Applications", bundle_id="com.example.other")
    if codex_app.find_app(home=home, run=nothing, platform="darwin") is not None:
        pytest.skip("this computer has the Codex app in /Applications")
    elsewhere = _fake_app(tmp_path / "elsewhere")

    def spotlight(command, **options):
        assert command[0] == "/usr/bin/mdfind" and "com.openai.codex" in command[1]
        return subprocess.CompletedProcess(command, 0, f"{elsewhere}\n", "")

    assert codex_app.find_app(home=home, run=spotlight, platform="darwin") == elsewhere
    assert codex_app.find_app(home=home, run=nothing, platform="win32") is None


def test_where_the_codex_app_can_be_used():
    assert codex_app.unavailable_reason("darwin", Path("/Applications/ChatGPT.app")) is None
    assert "chatgpt.com/download" in (codex_app.unavailable_reason("darwin", None) or "")
    assert "Mac only" in (codex_app.unavailable_reason("win32", None) or "")


def test_the_copy_is_opened_separately_with_the_link_in_its_arguments(data_folder):
    command = codex_app.open_command(Path("/Applications/ChatGPT.app"), link=codex_app.deep_link("thesis-a1"))
    home, user_data = codex_app.copy_paths()
    assert command[:2] == ["/usr/bin/open", "-n"]
    assert f"CODEX_HOME={home}" in command
    assert f"CODEX_ELECTRON_USER_DATA_PATH={user_data}" in command
    assert str(data_folder) in str(home)  # never ~/.codex
    after = command[command.index("--args") + 1 :]
    assert after == [
        f"--user-data-dir={user_data}",
        "codex://settings/connections/ssh/add?name=umcodex-thesis-a1",
    ]
    assert "--args" in codex_app.open_command(Path("/A.app")) and codex_app.open_command(Path("/A.app"))[
        -1
    ].startswith("--user-data-dir=")


def test_the_running_copy_is_found_by_its_profile_folder(data_folder):
    _, user_data = codex_app.copy_paths()
    listing = "\n".join(
        [
            "  101 /Applications/ChatGPT.app/Contents/MacOS/ChatGPT",  # the person's own copy
            "  202 /Applications/ChatGPT.app/Contents/Frameworks/ChatGPT Helper.app/Contents/MacOS/"
            f"ChatGPT Helper --type=renderer --user-data-dir={user_data}",
            f"  303 /Applications/ChatGPT.app/Contents/MacOS/ChatGPT --user-data-dir={user_data}",
        ]
    )

    def ps(command, **options):
        return subprocess.CompletedProcess(command, 0, listing, "")

    assert codex_app.running_copy(run=ps) == 303
    assert (
        codex_app.running_copy(run=lambda c, **o: subprocess.CompletedProcess(c, 0, listing[:60], "")) is None
    )


def test_the_copys_config_uses_the_relay_and_keeps_the_apps_own_settings(tmp_path):
    existing = 'model = "gpt-5.5"\npersonality = "friendly"\n[projects."/x"]\ntrust_level = "trusted"\n'
    config = tomllib.loads(
        codex_app.local_config(existing, 41234, tmp_path / "launch token", "gpt-5.6-terra")
    )
    provider = config["model_providers"]["toolkit"]
    assert config["model_provider"] == "toolkit" and config["forced_login_method"] == "api"
    assert provider["base_url"] == "http://127.0.0.1:41234/relay/v1"
    assert provider["auth"] == {"command": "/bin/cat", "args": [str(tmp_path / "launch token")]}
    assert "env_key" not in provider and "requires_openai_auth" not in provider
    assert config["personality"] == "friendly" and config["projects"]["/x"]["trust_level"] == "trusted"
    assert config["model"] == "gpt-5.5"  # the person's choice in the app
    fresh = tomllib.loads(codex_app.local_config("not toml [", 1, tmp_path / "t", "gpt-5.6-terra"))
    assert fresh["model"] == "gpt-5.6-terra"


def test_connected_setups_are_remembered(data_folder):
    assert not codex_app.connected_before("thesis-a1")
    codex_app.mark_connected("thesis-a1")
    assert codex_app.connected_before("thesis-a1") and not codex_app.connected_before("other")


# --- The launch, held while the app uses it ---------------------------------------------------


class FakeDocker(Docker):
    """The agent runs for `running_for` checks; the app-server shows up after `connects_after`."""

    def __init__(self, running_for: int, connects_after: int | None) -> None:
        self.running_for = running_for
        self.connects_after = connects_after
        self.checks = 0
        self.execs = 0
        super().__init__(self._run)

    def _run(self, command, **options):
        if command[1:3] == ["inspect", "-f"]:
            self.checks += 1
            alive = self.checks <= self.running_for
            return subprocess.CompletedProcess(command, 0, "true" if alive else "false", "")
        if command[1] == "exec" and "pgrep" in command:
            self.execs += 1
            found = self.connects_after is not None and self.execs > self.connects_after
            return subprocess.CompletedProcess(command, 0 if found else 1, "", "")
        return subprocess.CompletedProcess(command, 0, "", "")


def _running(tmp_path: Path, data: Path) -> launch.Running:
    folder = data / "launches" / "ab12cd34"
    folder.mkdir(parents=True)
    setup = Setup(id="thesis-a1", name="Thesis", working=str(tmp_path))
    launch.write_launch_info(folder, setup, 100.0)
    spec = LaunchSpec(
        launch_id="ab12cd34", instance="inst", setup_id=setup.id, agent_image="a", gateway_image="g",
        internet=False, folders=(), codex_etc=folder / "codex", launch_note=folder / "n",
        gateway_conf=folder / "g", env_file=folder / "e",
    )  # fmt: skip
    return launch.Running(spec=spec, relay_port=41234, token="tok-123", folder=folder, setup=setup)


def _ran(calls):
    def run(command, **options):
        calls.append(command)
        if command[0] == "ssh-keygen":
            key = Path(command[command.index("-f") + 1])
            key.write_text("private")
            key.with_name(key.name + ".pub").write_text("ssh-ed25519 AAAA test\n")
        if command[0] == "/bin/ps":
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, "ok", "")

    return run


def test_the_first_launch_opens_the_copy_on_the_add_link_and_notices_the_connection(
    tmp_path, data_folder, ssh_home
):
    running = _running(tmp_path, data_folder)
    calls: list[list[str]] = []
    said: list[str] = []
    docker = FakeDocker(running_for=6, connects_after=2)
    hold = codex_app.AppHold(
        "thesis-a1", say=said.append, data=data_folder, app=Path("/Applications/ChatGPT.app"), docker=docker,
        run=_ran(calls), sleep=lambda _: None, proxy_for=lambda s: ["/x/um-codex", "ssh-proxy", s],
    )  # fmt: skip
    assert hold.labels == (("umcodex.ssh", "thesis-a1"),)
    assert hold(running) == 0
    opened = next(c for c in calls if c[0] == "/usr/bin/open")
    assert opened[-1] == "codex://settings/connections/ssh/add?name=umcodex-thesis-a1"
    assert any(c[:2] == ["docker", "exec"] and "root" in c for c in calls)  # prepared
    info = json.loads((running.folder / "launch.json").read_text())
    assert info["app"]["connected"] is True and info["app"]["alias"] == "umcodex-thesis-a1"
    assert info["setup_id"] == "thesis-a1" and info["started_at"] == 100.0
    assert codex_app.connected_before("thesis-a1", data_folder)
    assert any("Settings → Connections" in line for line in said)
    assert any(line.startswith("Connected") for line in said)
    # The copy's config and its token file; the token file goes at the end.
    home, _ = codex_app.copy_paths(data_folder)
    assert "127.0.0.1:41234" in (home / "config.toml").read_text()
    assert not (codex_app.app_folder(data_folder) / "launch-token").exists()
    assert "tok-123" not in (home / "config.toml").read_text()
    assert (ssh_home / ".ssh" / "um-codex" / "config").read_text().count("Host umcodex-thesis-a1") == 1


def test_a_later_launch_doesnt_pass_the_link_and_a_running_copy_isnt_doubled(tmp_path, data_folder):
    codex_app.mark_connected("thesis-a1", data_folder)
    running = _running(tmp_path, data_folder)
    calls: list[list[str]] = []
    hold = codex_app.AppHold(
        "thesis-a1", say=lambda _: None, data=data_folder, app=Path("/Applications/ChatGPT.app"),
        docker=FakeDocker(running_for=1, connects_after=None), run=_ran(calls), sleep=lambda _: None,
        proxy_for=lambda s: ["/x/um-codex", "ssh-proxy", s],
    )  # fmt: skip
    assert hold(running) == 0
    opened = next(c for c in calls if c[0] == "/usr/bin/open")
    assert not any(part.startswith("codex://") for part in opened)
    info = json.loads((running.folder / "launch.json").read_text())
    assert info["app"]["first_time"] is False and info["app"]["connected"] is False

    _, user_data = codex_app.copy_paths(data_folder)
    calls.clear()

    def with_copy(command, **options):
        calls.append(command)
        if command[0] == "/bin/ps":
            line = f"77 /Applications/ChatGPT.app/Contents/MacOS/ChatGPT --user-data-dir={user_data}"
            return subprocess.CompletedProcess(command, 0, line, "")
        return subprocess.CompletedProcess(command, 0, "ok", "")

    running = _running(tmp_path / "again", data_folder / "again")
    hold.run = with_copy
    hold.docker = FakeDocker(running_for=1, connects_after=None)
    hold(running)
    assert not any(c[0] == "/usr/bin/open" for c in calls)
    assert any(c[0] == "/usr/bin/osascript" and c[-1] == "77" for c in calls)


def test_a_launch_without_the_app_still_prepares_everything(tmp_path, data_folder):
    running = _running(tmp_path, data_folder)
    calls: list[list[str]] = []
    hold = codex_app.AppHold(
        "thesis-a1", say=lambda _: None, data=data_folder, app=None,
        docker=FakeDocker(running_for=1, connects_after=None), run=_ran(calls), sleep=lambda _: None,
        proxy_for=lambda s: ["/x/um-codex", "ssh-proxy", s],
    )  # fmt: skip
    assert hold(running) == 0
    assert not any(c[0] in ("/usr/bin/open", "/bin/ps") for c in calls)
    assert json.loads((running.folder / "launch.json").read_text())["app"]["copy"] == "not-opened"


def test_running_launches_carry_the_app_state(tmp_path, data_folder):
    running = _running(tmp_path, data_folder)
    launch.update_launch_app(running.folder, {"alias": "umcodex-thesis-a1", "connected": True})
    lock = launch.LaunchLock(running.folder / "lock")
    assert lock.acquire()
    try:
        (found,) = launch.running_launches(data_folder)
    finally:
        lock.release()
    assert found.app == {"alias": "umcodex-thesis-a1", "connected": True}
    assert found.started_at == 100.0
