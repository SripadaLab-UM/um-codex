"""M6, "Open in: Codex app": the ssh side, the container side, the app copy,
and the launch held while the app uses it."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import pytest

from umcodex import codex_app, codex_config, launch
from umcodex import codex_app_windows as win
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


def test_a_terminal_launch_keeps_the_token_variable_and_full_access_only():
    requirements = tomllib.loads(codex_config.render_requirements(internet=False))
    provider = requirements["model_providers"]["toolkit"]
    assert provider["env_key"] == "UMCODEX_TOKEN" and "auth" not in provider
    # The TUI's /permissions too: only full access (Codex's own sandbox can't run in the container).
    assert requirements["default_permissions"] == ":danger-full-access"
    assert [k for k, v in requirements["allowed_permission_profiles"].items() if v] == [":danger-full-access"]
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


# Where "Codex app" works, with the app installed: a Mac, and Windows (the Store package's exe).
WITH_THE_APP = [
    ("darwin", "/Applications/ChatGPT.app"),
    ("win32", r"C:\Program Files\WindowsApps\OpenAI.Codex_26.928.4866.0_x64__2p2nqsd0c76g0\app\ChatGPT.exe"),
]


@pytest.mark.parametrize(("platform", "app"), WITH_THE_APP)
def test_the_installers_question_defaults_to_yes(ssh_home, platform, app):
    """`um-codex ssh-include`: Return adds the line; n, or no answer at all
    (no terminal), adds nothing. The same on a Mac and on Windows."""
    mac = {"find": lambda: Path(app), "platform": platform, "data": ssh_home}  # the Codex app is there
    said: list[str] = []
    assert codex_app.offer_include(lambda _: "n", said.append, **mac) == 1
    assert not (ssh_home / ".ssh" / "config").exists()
    assert any("Include ~/.ssh/um-codex/config" in line for line in said)

    def no_terminal(_):
        raise EOFError

    assert codex_app.offer_include(no_terminal, said.append, **mac) == 1
    assert not (ssh_home / ".ssh" / "config").exists()
    asked: list[str] = []
    # (a no is remembered: asked again only on request; see the test below)
    assert codex_app.offer_include(lambda q: asked.append(q) or "", said.append, ask_again=True, **mac) == 0
    assert asked == ["Add that line now? [Y/n] "]
    assert codex_app.include_present()
    # Asked once: there now, so not asked again.
    assert codex_app.offer_include(lambda _: pytest.fail("asked again"), said.append, **mac) == 0


def test_the_installers_question_isnt_asked_without_the_app_or_where_it_isnt_offered(ssh_home, monkeypatch):
    said: list[str] = []
    never = lambda _: pytest.fail("asked")  # noqa: E731
    for platform in ("darwin", "win32"):
        assert codex_app.offer_include(never, said.append, find=lambda: None, platform=platform) == 0
        assert "isn't installed" in said[-1]
    assert codex_app.offer_include(never, said.append, platform="linux", find=lambda: Path("x")) == 0
    monkeypatch.setattr(codex_app, "WINDOWS_COPY", False)  # Windows switched off again: not asked there
    monkeypatch.delenv("UMCODEX_WINDOWS_CODEX_APP", raising=False)
    assert codex_app.offer_include(never, said.append, platform="win32", find=lambda: Path("x")) == 0
    assert not (ssh_home / ".ssh" / "config").exists()


def test_the_cli_runs_the_installers_question_only_at_a_terminal(monkeypatch, capsys):
    from umcodex import cli

    calls = []
    monkeypatch.setattr(
        codex_app, "offer_include", lambda ask, say, ask_again: calls.append((ask, say, ask_again)) or 1
    )
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert cli.main(["ssh-include"]) == 1
    assert calls == [] and "no terminal" in capsys.readouterr().out
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    assert cli.main(["ssh-include"]) == 1
    assert cli.main(["ssh-include", "--ask-again"]) == 1
    assert calls == [(input, print, False), (input, print, True)]


@pytest.mark.parametrize(("platform", "app"), WITH_THE_APP)
def test_a_no_is_remembered_until_asked_again(ssh_home, tmp_path, platform, app):
    mac = {"find": lambda: Path(app), "platform": platform, "data": tmp_path}
    said: list[str] = []
    assert codex_app.offer_include(lambda _: "no", said.append, **mac) == 1
    assert (tmp_path / codex_app.INCLUDE_DECLINED).exists()
    assert codex_app.offer_include(lambda _: pytest.fail("asked"), said.append, **mac) == 1
    assert "you said no before" in said[-1]
    assert codex_app.offer_include(lambda _: "", said.append, ask_again=True, **mac) == 0
    assert codex_app.include_present() and not (tmp_path / codex_app.INCLUDE_DECLINED).exists()


# --- UM-Codex's own ssh files ------------------------------------------------------------


PROXY = ["/Users/x/Library/Application Support/UM-Codex/app/bin/um-codex", "ssh-proxy", "thesis-a1b2c3"]


def test_the_host_block():
    block = codex_app.host_block("thesis-a1b2c3", [*PROXY, "--docker", "/usr/local/bin/docker"])
    lines = [line.strip() for line in block.splitlines()]
    assert "Host umcodex-thesis-a1b2c3" in lines
    for wanted in (
        "User agent",
        f"IdentityFile ~/.ssh/um-codex/installs/{codex_app.install_id()}/thesis-a1b2c3_ed25519",
        "IdentitiesOnly yes",
        "IdentityAgent none",
        "ForwardAgent no",
        "ForwardX11 no",
        "ForwardX11Trusted no",
        "Tunnel no",
        "ControlMaster no",
        "ControlPath none",
        "GSSAPIAuthentication no",
        "UpdateHostKeys no",
        "StrictHostKeyChecking no",
        "UserKnownHostsFile /dev/null",
    ):
        assert wanted in lines, wanted
    proxy = next(line for line in lines if line.startswith("ProxyCommand "))
    if sys.platform == "win32":
        assert proxy.startswith('ProxyCommand "/Users/x/Library/Application Support/')
    else:
        assert proxy == (
            "ProxyCommand '/Users/x/Library/Application Support/UM-Codex/app/bin/um-codex' ssh-proxy "
            "thesis-a1b2c3 --docker /usr/local/bin/docker"
        )


def test_proxy_command_words_are_safe_for_ssh():
    windows = "C:\\Program Files\\UM-Codex\\um-codex.exe"
    assert codex_app._ssh_arg(windows, "win32") == f'"{windows}"'
    assert codex_app._ssh_arg("/a/100%/b", "win32") == "/a/100%%/b"  # ssh's own % tokens
    with pytest.raises(ValueError):
        codex_app._ssh_arg('/a"b', "win32")
    assert codex_app._ssh_arg("/a/100%/b", "darwin") == "/a/100%%/b"
    assert codex_app._ssh_arg("/a b/$x`y`'z;&w", "darwin") == "'/a b/$x`y`'\"'\"'z;&w'"
    with pytest.raises(ValueError):
        codex_app._ssh_arg("/a\nb", "darwin")


NASTY_PARTS = ["/tmp/a b/$HOME/`id`/it's;x&y|z", "100% sure", 'say "hi"', "*?[a]~"]


@pytest.mark.skipif(sys.platform == "win32", reason="the Mac's quoting, through a POSIX shell")
@pytest.mark.parametrize("shell", ["/bin/sh", "/bin/zsh", "/bin/bash"])
def test_ssh_runs_the_proxy_command_with_every_word_unchanged(tmp_path, shell):
    """The real ssh client runs the ProxyCommand (with the person's shell):
    a stand-in records the words it gets, which must be exactly ours."""
    if not (ssh := _which("ssh")) or not Path(shell).exists():
        pytest.skip("no ssh client or no such shell here")
    folder = tmp_path / "it's $a `b` ;&"
    folder.mkdir()
    record = tmp_path / "words.txt"
    program = folder / "proxy"
    program.write_text(
        f'#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done > {shlex_quote(str(record))}\n'
    )
    program.chmod(0o755)
    config = tmp_path / "config"
    config.write_text(codex_app.host_block("thesis-a1", [str(program), *NASTY_PARTS]))
    subprocess.run(
        [
            ssh,
            "-F",
            str(config),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            "umcodex-thesis-a1",
            "true",
        ],
        capture_output=True,
        timeout=30,
        env={**os.environ, "SHELL": shell},
    )
    assert record.read_text().splitlines() == NASTY_PARTS


def shlex_quote(text: str) -> str:
    import shlex

    return shlex.quote(text)


@pytest.mark.skipif(sys.platform == "win32", reason="the Mac's quoting, through a POSIX shell")
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
    assert seen["proxycommand"] == f"'{PROXY[0]}' ssh-proxy thesis-a1b2c3"


def _which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


def test_keys_and_config_are_private_and_a_deleted_setup_goes(ssh_home):
    if not _which("ssh-keygen"):
        pytest.skip("no ssh-keygen here")
    for setup_id in ("thesis-a1b2c3", "data-d4e5f6"):
        public = codex_app.ensure_key(setup_id)
        assert public.read_text().startswith("ssh-ed25519 ")
    proxy = lambda setup_id: ["/x/um-codex", "ssh-proxy", setup_id]  # noqa: E731
    path = codex_app.write_config(proxy, setup_ids=["thesis-a1b2c3", "data-d4e5f6"])
    folder = ssh_home / ".ssh" / "um-codex"
    mine = codex_app.install_ssh_dir()
    assert mine.parent == folder / "installs"
    if sys.platform != "win32":
        for private in (folder, folder / "installs", mine):
            assert stat.S_IMODE(private.stat().st_mode) == 0o700
        assert stat.S_IMODE((folder / "config").stat().st_mode) == 0o600
        for name in ("hosts", "owner", "thesis-a1b2c3_ed25519", "data-d4e5f6_ed25519"):
            assert stat.S_IMODE((mine / name).stat().st_mode) == 0o600
    assert (mine / "owner").read_text().strip() == os.path.realpath(codex_app.data_dir())
    text = path.read_text()
    assert "Host umcodex-thesis-a1b2c3" in text and "Host umcodex-data-d4e5f6" in text
    key = (mine / "thesis-a1b2c3_ed25519").read_bytes()
    codex_app.ensure_key("thesis-a1b2c3")
    assert (mine / "thesis-a1b2c3_ed25519").read_bytes() == key  # kept between launches

    codex_app.forget_setup("data-d4e5f6")
    assert not (mine / "data-d4e5f6_ed25519").exists()
    assert "data-d4e5f6" not in path.read_text()
    assert codex_app.known_setups() == ["thesis-a1b2c3"]
    done, others = codex_app.remove_ssh_files()
    assert done and not others and not folder.exists()


def _fake_key(folder: Path, setup_id: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{setup_id}_ed25519").write_text(f"private {setup_id}")
    (folder / f"{setup_id}_ed25519.pub").write_text("ssh-ed25519 AAAA\n")


def _legacy_block(setup_id: str, data: Path | None = None) -> str:
    """A Host as UM-Codex 0.1.0a3 wrote it: `--data-dir` only for a data
    folder other than the installed copy's (the test's own data folder)."""
    extra = f" --data-dir {shlex_quote(str(data))}" if data is not None else ""
    return (
        f"Host umcodex-{setup_id}\n  User agent\n"
        f"  IdentityFile ~/.ssh/um-codex/{setup_id}_ed25519\n"
        f"  ProxyCommand /old/um-codex ssh-proxy {setup_id} --docker /usr/local/bin/docker{extra}\n"
    )


PROXY_FOR = lambda s: ["/x/um-codex", "ssh-proxy", s]  # noqa: E731


def test_the_flat_layout_moves_in_and_another_data_folders_flat_keys_stay(ssh_home, data_folder, tmp_path):
    """Up to 0.1.0a3 each launch removed the keys and Hosts of every setup it
    didn't know: another data folder's. Now this data folder's keys move into
    its own folder; the others' keys and Hosts stay as they are."""
    from umcodex.setups import SetupStore

    other, gone = tmp_path / "other-a3", tmp_path / "scratch-a3"
    other.mkdir()
    folder = ssh_home / ".ssh" / "um-codex"
    # A spike's key (no Host), ours, ours of a deleted setup, another data
    # folder's, and one of a data folder that's gone.
    for name in ("app-test", "thesis-a1", "deleted-b2", "first-project-c3", "orphan-d4"):
        _fake_key(folder, name)
    (folder / "config").write_text(
        "# Written by UM-Codex 0.1.0a3\n\n"
        + _legacy_block("thesis-a1")
        + _legacy_block("deleted-b2")
        + _legacy_block("first-project-c3", other)
        + _legacy_block("orphan-d4", gone)
    )
    SetupStore().save(Setup(id="thesis-a1", name="Thesis", working="/tmp"))
    text = codex_app.write_config(PROXY_FOR).read_text()
    mine = codex_app.install_ssh_dir()
    assert (mine / "thesis-a1_ed25519").read_text() == "private thesis-a1"  # moved, not made anew
    assert (mine / "thesis-a1_ed25519.pub").exists() and not (folder / "thesis-a1_ed25519").exists()
    assert not (folder / "deleted-b2_ed25519").exists()  # ours (its Host says so), no saved setup
    for name in ("app-test", "first-project-c3", "orphan-d4"):  # left alone
        assert (folder / f"{name}_ed25519").read_text() == f"private {name}"
    assert text.count("Host umcodex-thesis-a1\n") == 1
    assert f"installs/{codex_app.install_id()}/thesis-a1_ed25519" in text
    assert _legacy_block("first-project-c3", other) in text  # the older UM-Codex's Host, as it was
    assert "umcodex-app-test" not in text and "deleted-b2" not in text
    assert "orphan-d4" not in text  # its data folder is gone: no Host, the key stays
    again = codex_app.write_config(PROXY_FOR).read_text()
    assert again == text  # stable


def test_a_key_made_before_the_move_doesnt_shadow_the_new_host(ssh_home, data_folder):
    folder = ssh_home / ".ssh" / "um-codex"
    _fake_key(folder, "thesis-a1")
    (folder / "config").write_text(_legacy_block("thesis-a1"))
    _fake_key(codex_app.install_ssh_dir(), "thesis-a1")  # already in its own folder too
    text = codex_app.write_config(PROXY_FOR, setup_ids=["thesis-a1"]).read_text()
    assert text.count("Host umcodex-thesis-a1\n") == 1
    assert "IdentityFile ~/.ssh/um-codex/thesis-a1_ed25519" not in text


def test_two_data_folders_never_lose_each_others_hosts_or_keys(ssh_home, data_folder, tmp_path):
    other = tmp_path / "dev-data"
    other.mkdir()
    folder = ssh_home / ".ssh" / "um-codex"
    a, b = codex_app.install_ssh_dir(), codex_app.install_ssh_dir(data=other)
    assert a != b

    def config() -> str:
        return (folder / "config").read_text()

    _fake_key(a, "thesis-a1")
    codex_app.write_config(PROXY_FOR, setup_ids=["thesis-a1"])
    _fake_key(b, "dev-b2")
    codex_app.write_config(PROXY_FOR, setup_ids=["dev-b2"], data=other)
    dev = codex_app.alias("dev-b2", other)
    assert "Host umcodex-thesis-a1\n" in config() and f"Host {dev}\n" in config()
    codex_app.write_config(PROXY_FOR, setup_ids=["thesis-a1"])  # A launches again
    assert f"Host {dev}\n" in config() and (b / "dev-b2_ed25519").exists()
    codex_app.forget_setup("thesis-a1")  # A deletes its setup
    assert "umcodex-thesis-a1" not in config() and f"Host {dev}\n" in config()
    _fake_key(a, "next-c3")
    codex_app.write_config(PROXY_FOR, setup_ids=["next-c3"])
    codex_app.forget_setup("dev-b2", data=other)  # B deletes its setup
    assert "Host umcodex-next-c3\n" in config() and dev not in config()
    _fake_key(b, "dev-d4")
    codex_app.write_config(PROXY_FOR, setup_ids=["dev-d4"], data=other)
    done, others = codex_app.remove_ssh_files(setup_ids=[])  # A uninstalls
    assert others and not a.exists() and (b / "dev-d4_ed25519").exists()
    assert "umcodex-next-c3" not in config() and f"Host {codex_app.alias('dev-d4', other)}\n" in config()
    done, others = codex_app.remove_ssh_files(data=other, setup_ids=[])  # then B
    assert not others and not folder.exists()


def test_aliases_are_unique_across_data_folders_and_ssh_resolves_each(ssh_home, data_folder, tmp_path):
    other = tmp_path / "dev-data"
    other.mkdir()
    plain, suffixed = codex_app.alias("same-a1"), codex_app.alias("same-a1", other)
    assert plain == "umcodex-same-a1"
    assert suffixed == f"umcodex-same-a1_{codex_app.install_id(other)[:8]}"
    from umcodex import relay

    assert relay._LOCAL_PATH.fullmatch(f"/um-codex-local/{suffixed}/v1/responses")
    for data in (data_folder, other):
        _fake_key(codex_app.install_ssh_dir(data=data), "same-a1")
        codex_app.write_config(PROXY_FOR, setup_ids=["same-a1"], data=data)
    config = ssh_home / ".ssh" / "um-codex" / "config"
    text = config.read_text()
    assert text.count("\nHost ") == 2 and f"Host {plain}\n" in text and f"Host {suffixed}\n" in text
    if not (ssh := _which("ssh")):
        return
    for name, data in ((plain, data_folder), (suffixed, other)):
        done = subprocess.run(
            [ssh, "-G", "-F", str(config), name], capture_output=True, text=True,
            env={**os.environ, "HOME": str(ssh_home)},
        )  # fmt: skip
        assert done.returncode == 0, done.stderr
        seen = dict(line.split(" ", 1) for line in done.stdout.splitlines() if " " in line)
        assert seen["identityfile"].endswith(f"/installs/{codex_app.install_id(data)}/same-a1_ed25519")


def _install_for(owner: Path, setup_id: str) -> Path:
    """An install's ssh folder as its UM-Codex left it, for a data folder
    that may not be reachable now."""
    folder = codex_app.installs_dir() / codex_app.instance_of(owner)
    _fake_key(folder, setup_id)
    (folder / "owner").write_text(f"{owner}\n")
    (folder / "hosts").write_text(codex_app.host_block(setup_id, PROXY_FOR(setup_id), owner))
    return folder


def _launch_mine(setup_id: str = "thesis-a1") -> str:
    _fake_key(codex_app.install_ssh_dir(), setup_id)
    return codex_app.write_config(PROXY_FOR, setup_ids=[setup_id]).read_text()


def test_a_data_folder_thats_gone_loses_its_hosts_at_once_and_its_folder_after_30_days(
    ssh_home, data_folder, tmp_path, monkeypatch, caplog
):
    other = tmp_path / "scratch-data"
    other.mkdir()
    folder = _install_for(other, "scratch-b2")
    name = codex_app.alias("scratch-b2", other)
    clock = [1_000_000.0]
    monkeypatch.setattr(codex_app, "_now", lambda: clock[0])
    assert f"Host {name}\n" in _launch_mine()
    other.rmdir()
    with caplog.at_level("INFO", logger="umcodex.codex_app"):
        text = _launch_mine()
    assert f"Host {name}" not in text and "Host umcodex-thesis-a1\n" in text
    assert (folder / "scratch-b2_ed25519").exists()  # kept for now
    assert any("data folder is gone" in r.getMessage() for r in caplog.records)
    missing = json.loads((ssh_home / ".ssh" / "um-codex" / "missing.json").read_text())
    assert missing == {folder.name: 1_000_000.0}
    # Back within the grace period: its Hosts are back, nothing was lost.
    clock[0] += 29 * 86400
    other.mkdir()
    assert f"Host {name}\n" in _launch_mine()
    assert not (ssh_home / ".ssh" / "um-codex" / "missing.json").exists()
    # Gone again, and for 30 days: then its folder goes.
    other.rmdir()
    _launch_mine()
    clock[0] += 29 * 86400
    _launch_mine()
    assert folder.exists()
    clock[0] += 86400
    _launch_mine()
    assert not folder.exists()
    assert not (ssh_home / ".ssh" / "um-codex" / "missing.json").exists()


def test_a_data_folder_on_an_unmounted_volume_keeps_its_hosts_and_keys(ssh_home, data_folder, tmp_path):
    volumes = tmp_path / "Volumes"
    volumes.mkdir()
    away = volumes / "Thesis-Drive" / "UM-Codex"  # the volume isn't mounted: its folder isn't there
    folder = _install_for(away, "drive-e5")
    text = _launch_mine()
    assert f"Host {codex_app.alias('drive-e5', away)}\n" in text
    assert (folder / "drive-e5_ed25519").exists()
    assert not (ssh_home / ".ssh" / "um-codex" / "missing.json").exists()
    # And nothing is ever made there, for this data folder either.
    with pytest.raises(FileNotFoundError):
        codex_app.write_config(PROXY_FOR, setup_ids=[], data=away)
    assert not (volumes / "Thesis-Drive").exists()


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX permissions, not root")
def test_a_data_folder_that_cant_be_read_keeps_its_hosts_and_keys(ssh_home, data_folder, tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    behind = _install_for(locked / "UM-Codex", "behind-f6")  # its parent can't be read
    other = tmp_path / "other"
    other.mkdir()
    unreadable = _install_for(other, "unread-a7")
    unknown = codex_app.installs_dir() / ("f" * 16)  # no owner file: not one UM-Codex can tell about
    _fake_key(unknown, "x-1")
    os.chmod(locked, 0)
    os.chmod(unreadable / "owner", 0)
    other.rmdir()  # gone, but its owner file can't be read to say so
    try:
        text = _launch_mine()
    finally:
        os.chmod(locked, 0o700)
        os.chmod(unreadable / "owner", 0o600)
    assert f"Host {codex_app.alias('behind-f6', locked / 'UM-Codex')}\n" in text
    assert (behind / "behind-f6_ed25519").exists() and (unreadable / "unread-a7_ed25519").exists()
    assert unknown.exists()


def _write_from_another_process(home: str, data: str, setup_id: str, rounds: int) -> None:
    from umcodex import codex_app

    folder = codex_app.installs_dir(Path(home)) / codex_app.install_id(Path(data))
    for _ in range(rounds):
        _fake_key(folder, setup_id)
        codex_app.write_config(PROXY_FOR, home=Path(home), setup_ids=[setup_id], data=Path(data))


def test_data_folders_writing_at_once_all_end_up_in_the_config(ssh_home, tmp_path):
    import multiprocessing

    datas = []
    for n in range(6):
        datas.append(tmp_path / f"data-{n}")
        datas[-1].mkdir()
    context = multiprocessing.get_context("spawn")
    workers = [
        context.Process(target=_write_from_another_process, args=(str(ssh_home), str(d), f"s{n}-a1", 15))
        for n, d in enumerate(datas)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(120)
        assert worker.exitcode == 0
    text = (ssh_home / ".ssh" / "um-codex" / "config").read_text()
    for n, data in enumerate(datas):
        assert text.count(f"Host {codex_app.alias(f's{n}-a1', data)}\n") == 1
    assert text.count("\nHost ") == len(datas)
    if ssh := _which("ssh"):
        config = ssh_home / ".ssh" / "um-codex" / "config"
        done = subprocess.run([ssh, "-G", "-F", str(config), "anything"], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr  # ssh reads the whole file
    assert not [p for p in (ssh_home / ".ssh" / "um-codex").iterdir() if ".um-codex-" in p.name]


def test_the_proxy_command_names_the_data_folder_it_was_made_for(monkeypatch, tmp_path):
    monkeypatch.delenv("UMCODEX_DATA_DIR")
    monkeypatch.setattr(codex_app, "default_data_dir", lambda: tmp_path / "installed")
    other = tmp_path / "dev"
    command = codex_app.proxy_command("thesis-a1", other)
    assert command[command.index("--data-dir") + 1] == str(other)
    assert "--data-dir" not in codex_app.proxy_command("thesis-a1", tmp_path / "installed")


def test_the_proxy_for_a_data_folders_hosts_is_its_own(ssh_home, data_folder, tmp_path):
    other = tmp_path / "dev"
    other.mkdir()
    _fake_key(codex_app.install_ssh_dir(data=other), "dev-b2")
    text = codex_app.write_config(setup_ids=["dev-b2"], data=other).read_text()
    assert f"--data-dir {other}" in text and str(data_folder) not in text


def test_ssh_is_made_private_when_it_isnt_there_and_left_as_it_is_otherwise(ssh_home, data_folder):
    ssh = ssh_home / ".ssh"
    assert not ssh.exists()
    codex_app.write_config(PROXY_FOR, setup_ids=[])
    if sys.platform != "win32":
        assert stat.S_IMODE(ssh.stat().st_mode) == 0o700
        os.chmod(ssh, 0o750)
        _launch_mine()
        assert stat.S_IMODE(ssh.stat().st_mode) == 0o750


def test_a_copy_set_up_under_the_plain_alias_loses_that_host_and_project(tmp_path, monkeypatch):
    """A development copy's state from before its hosts had the install id."""
    monkeypatch.setattr(codex_app, "plain_alias_folder", lambda: tmp_path / "installed")
    setup = Setup(id="other-c3", name="Other", working="/tmp")
    state = codex_app.seeded_state(GUI_TEST_STATE, setup, data=tmp_path / "dev")
    old = "remote-ssh-discovered:umcodex-other-c3"
    assert not any(c["hostId"] == old for c in state["codex-managed-remote-connections"])
    assert old not in state["remote-connection-auto-connect-by-host-id"]
    assert not any(p["hostId"] == old for p in state["remote-projects"])
    assert "3df46154" not in state["project-order"]
    new = codex_app.host_id("other-c3", tmp_path / "dev")
    assert state["remote-connection-auto-connect-by-host-id"] == {new: True}
    # The installed copy's own state keeps its plain-alias host.
    kept = codex_app.seeded_state(GUI_TEST_STATE, setup, data=tmp_path / "installed")
    assert any(c["hostId"] == old for c in kept["codex-managed-remote-connections"])


def test_the_tests_never_reach_this_computers_ssh_folder(ssh_home, data_folder):
    assert codex_app.own_ssh_dir().is_relative_to(ssh_home)
    if sys.platform != "win32":
        import pwd

        real = Path(pwd.getpwuid(os.getuid()).pw_dir)  # not $HOME, which the tests change
        assert not codex_app.own_ssh_dir().is_relative_to(real / ".ssh")
    assert codex_app.plain_alias_folder() == data_folder


def test_an_app_launch_from_another_data_folder_uses_its_alias_throughout(
    tmp_path, data_folder, ssh_home, monkeypatch
):
    """A development copy's data folder: the ssh Host, the copy's seeded
    state, its local-chats provider and the launch's state all use the one
    alias with its install id."""
    monkeypatch.setattr(codex_app, "plain_alias_folder", lambda: tmp_path / "installed")
    name = codex_app.alias("thesis-a1", data_folder)
    assert name.startswith("umcodex-thesis-a1_")
    running = _running(tmp_path, data_folder)
    hold = codex_app.AppHold(
        "thesis-a1", say=lambda _: None, data=data_folder, app=Path("/Applications/ChatGPT.app"),
        docker=FakeDocker(running_for=6, connects_after=2), run=_ran([]), sleep=lambda _: None,
        proxy_for=lambda s: ["/x/um-codex", "ssh-proxy", s],
    )  # fmt: skip
    assert hold(running) == 0
    info = json.loads((running.folder / "launch.json").read_text())
    assert info["app"]["alias"] == name
    home, _ = codex_app.copy_paths(data_folder)
    state = json.loads((home / ".codex-global-state.json").read_text())
    assert state["remote-connection-auto-connect-by-host-id"] == {f"remote-ssh-discovered:{name}": True}
    assert f"/um-codex-local/{name}/v1" in (home / "config.toml").read_text()
    assert (ssh_home / ".ssh" / "um-codex" / "config").read_text().count(f"Host {name}\n") == 1


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

    codex_app.prepare_container(Docker(run), "umcodex-ab12cd34-agent", public)
    command, options = calls[0]
    assert command[:6] == ["docker", "exec", "-i", "-u", "root", "umcodex-ab12cd34-agent"]
    assert options["input"] == public.read_text()
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


def test_where_the_codex_app_can_be_used(monkeypatch):
    monkeypatch.setattr(win, "openssh_installed", lambda: True)
    assert codex_app.unavailable_reason("win32", Path("C:/x/ChatGPT.exe")) is None  # on: experimental
    monkeypatch.setattr(win, "openssh_installed", lambda: False)  # no OpenSSH Client feature
    assert codex_app.unavailable_reason("win32", Path("C:/x/ChatGPT.exe")) == win.OPENSSH_MISSING
    assert "OpenSSH Client" in win.OPENSSH_MISSING
    monkeypatch.setattr(win, "openssh_installed", lambda: True)
    monkeypatch.setattr(codex_app, "WINDOWS_COPY", False)  # switched off again
    monkeypatch.delenv("UMCODEX_WINDOWS_CODEX_APP", raising=False)
    assert codex_app.unavailable_reason("darwin", Path("/Applications/ChatGPT.app")) is None
    assert "chatgpt.com/download" in (codex_app.unavailable_reason("darwin", None) or "")
    assert "Mac only" in (codex_app.unavailable_reason("win32", None) or "")
    assert "Mac only" in (codex_app.unavailable_reason("win32", Path("C:/x/ChatGPT.exe")) or "")
    monkeypatch.setenv("UMCODEX_WINDOWS_CODEX_APP", "1")  # the hands-on test's switch
    assert codex_app.unavailable_reason("win32", Path("C:/x/ChatGPT.exe")) is None
    assert "Microsoft Store" in (codex_app.unavailable_reason("win32", None) or "")


# The Store package as this Windows laptop has it (2026-10-02).
WINDOWS_PACKAGE = r"C:\Program Files\WindowsApps\OpenAI.Codex_26.928.4866.0_x64__2p2nqsd0c76g0"


def _appx(folder: Path, family: str = win.FAMILY, publisher: str = win.PUBLISHER) -> str:
    """Get-AppxPackage's answer, as ConvertTo-Json -Compress gave it on this laptop (2026-10-02)."""
    return json.dumps(
        {"InstallLocation": str(folder), "PackageFamilyName": family, "Publisher": publisher},
        separators=(",", ":"),
    )


def test_the_windows_app_is_found_by_its_store_package(tmp_path):
    package = tmp_path / "OpenAI.Codex_26.928.4866.0_x64__2p2nqsd0c76g0"
    (package / "app").mkdir(parents=True)
    (package / "app" / "ChatGPT.exe").write_bytes(b"")
    asked = []

    def answer(text):
        def powershell(command, **options):
            asked.append(command)
            return subprocess.CompletedProcess(command, 0, text + "\r\n", "")

        return powershell

    found = codex_app.find_app(platform="win32", run=answer(_appx(package)))
    assert found == package / "app" / "ChatGPT.exe"
    assert asked[0][0].lower().endswith(r"\system32\windowspowershell\v1.0\powershell.exe")
    assert "Get-AppxPackage -Name OpenAI.Codex" in asked[0][-1]
    assert codex_app.app_version(found) == "26.928.4866.0"
    assert codex_app.app_version(Path(WINDOWS_PACKAGE) / "app" / "ChatGPT.exe") == "26.928.4866.0"
    assert codex_app.find_app(platform="win32", run=answer("")) is None  # not installed
    assert codex_app.find_app(platform="win32", run=answer(_appx(tmp_path / "gone"))) is None
    # Someone else's package with that name isn't run.
    assert codex_app.find_app(platform="win32", run=answer(_appx(package, publisher="CN=Other"))) is None
    other_family = _appx(package, family="OpenAI.Codex_0000000000000")
    assert codex_app.find_app(platform="win32", run=answer(other_family)) is None
    assert codex_app.find_app(platform="win32", run=answer("not json")) is None


def test_the_windows_copy_never_uses_the_persons_own_folders(tmp_path):
    data, person, app_data = tmp_path / "data" / "codex-app", tmp_path / "me", tmp_path / "me" / "Roaming"
    win.check_paths(data / "codex-home", data / "user-data", data, person, app_data)  # fine
    for home, user_data in (
        (person / ".codex", data / "user-data"),  # the person's own Codex home
        (data / "codex-home", app_data / "Codex"),  # the app's own profile
        (tmp_path / "elsewhere", data / "user-data"),  # outside UM-Codex's folder
        (data, data / "user-data"),
    ):
        with pytest.raises(win.UnsafePaths):
            win.check_paths(home, user_data, data, person, app_data)
    with pytest.raises(win.UnsafePaths):  # a data folder that holds the person's ~/.codex
        win.check_paths(person / ".codex" / "x", data / "user-data", person, person, app_data)


def test_the_windows_copy_is_the_exe_itself_with_its_own_home(data_folder):
    app = Path(WINDOWS_PACKAGE) / "app" / "ChatGPT.exe"
    person = {
        "Path": r"C:\Git\usr\bin;C:\Windows", "CODEX_HOME": r"C:\Users\x\.codex",
        "CODEX_APP_SERVER_WS_URL": "ws://x", "OPENAI_API_KEY": "sk-x", "OPENAI_BASE_URL": "https://x",
        "HTTPS_PROXY": "http://p:1", "no_proxy": "*", "SHELL": "/usr/bin/bash",
    }  # fmt: skip
    command, env = codex_app.windows_open(app, link=codex_app.deep_link("thesis-a1"), environ=person)
    home, user_data = codex_app.copy_paths()
    assert command == [
        str(app),
        f"--user-data-dir={user_data}",
        "codex://settings/connections/ssh/add?name=umcodex-thesis-a1",
    ]
    assert env["CODEX_HOME"] == str(home) and str(data_folder) in env["CODEX_HOME"]  # never ~/.codex
    assert env["CODEX_ELECTRON_USER_DATA_PATH"] == str(user_data)
    assert set(env) == {"PATH", "CODEX_HOME", "CODEX_ELECTRON_USER_DATA_PATH"}  # nothing leads it elsewhere
    # Windows' own ssh first (Git's ssh runs a ProxyCommand through /bin/sh); the rest is kept.
    assert env["PATH"].split(";")[0].lower().endswith(r"\system32\openssh")
    assert env["PATH"].split(";")[1:] == [r"C:\Git\usr\bin", r"C:\Windows"]
    assert codex_app.windows_open(app, environ={})[0] == [str(app), f"--user-data-dir={user_data}"]


def test_the_running_windows_copy_is_found_by_its_profile_folder(data_folder):
    _, user_data = codex_app.copy_paths()
    exe = f'"{WINDOWS_PACKAGE}\\app\\ChatGPT.exe"'
    # Win32_Process command lines, as this laptop showed them (2026-10-02).
    listing = "\r\n".join(
        [
            f"7180 {exe} ",  # the person's own copy
            f'4040 {exe} --type=renderer --user-data-dir="{user_data}" --app-user-model-id=x',
            f'5050 {exe} --user-data-dir="{user_data}-2"',  # not ours: another folder beside it
            f'19952 {exe} "--user-data-dir={str(user_data).upper()}"',
        ]
    )

    def listed(text):
        return lambda c, **o: subprocess.CompletedProcess(c, 0, text, "")

    assert codex_app.running_copy(run=listed(listing), platform="win32") == 19952
    assert codex_app.running_copy(run=listed(listing.split("\r\n")[0]), platform="win32") is None
    other_spellings = [
        f'31 {exe} --user-data-dir="{user_data}"',  # the value quoted
        f'33 {exe} "--user-data-dir={user_data.parent}\\x\\..\\{user_data.name}" codex://x',
    ]
    if " " not in str(user_data):  # a bare value can't hold a space
        other_spellings.append(f"32 {exe} --user-data-dir={str(user_data).replace(chr(92), '/')}")
    for line in other_spellings:
        assert codex_app.running_copy(run=listed(line), platform="win32") == int(line.split()[0]), line
    assert win.profile_of(f"{exe} ") is None  # the person's own copy has none
    assert win.profile_of(f"{exe} --type=gpu-process --user-data-dir=C:\\x") is None

    def activate(command, **options):
        assert command[-1].endswith("AppActivate(19952)")
        return subprocess.CompletedProcess(command, 0, "True\r\n", "")

    assert codex_app.bring_forward(19952, run=activate, platform="win32") is True
    refused = lambda c, **o: subprocess.CompletedProcess(c, 0, "False\r\n", "")  # noqa: E731
    assert codex_app.bring_forward(19952, run=refused, platform="win32") is False


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


EXISTING = 'model = "gpt-5.5"\npersonality = "friendly"\n[projects."/x"]\ntrust_level = "trusted"\n'


def test_the_copys_local_chats_are_blocked_and_its_own_settings_kept():
    assert codex_app.LOCAL_CHATS is False  # the maintainer's decision (2026-10-01)
    config = tomllib.loads(
        codex_app.local_config(EXISTING, 41234, "gpt-5.6-terra", setup_alias="umcodex-thesis-a1")
    )
    provider = config["model_providers"]["toolkit"]
    assert config["model_provider"] == "toolkit" and config["forced_login_method"] == "api"
    # The relay's own answer, never the Toolkit; no credential at all.
    assert provider["base_url"] == "http://127.0.0.1:41234/um-codex-local/umcodex-thesis-a1/v1"
    assert "auth" not in provider and "env_key" not in provider
    assert "requires_openai_auth" not in provider  # so the copy opens with no sign-in
    assert config["personality"] == "friendly" and config["projects"]["/x"]["trust_level"] == "trusted"
    assert config["model"] == "gpt-5.5"  # the person's choice in the app
    assert (
        tomllib.loads(codex_app.local_config("", 1, "gpt-5.6-terra", setup_alias="umcodex-a"))["model"]
        == "gpt-5.6-terra"
    )


def test_local_chats_can_be_switched_back_on(tmp_path):
    config = tomllib.loads(
        codex_app.local_config(
            EXISTING, 41234, "m", setup_alias="umcodex-a", token_file=tmp_path / "t", local_chats=True
        )
    )
    provider = config["model_providers"]["toolkit"]
    assert provider["base_url"] == "http://127.0.0.1:41234/relay/v1"
    assert provider["auth"] == {"command": "/bin/cat", "args": [str(tmp_path / "t")]}
    assert any("work only while a setup is running" in n for n in codex_app.notes("a", local_chats=True))
    assert any("blocked" in n for n in codex_app.notes("a"))


def test_connected_setups_are_remembered(data_folder):
    assert not codex_app.connected_before("thesis-a1")
    codex_app.mark_connected("thesis-a1")
    assert codex_app.connected_before("thesis-a1") and not codex_app.connected_before("other")


# --- The launch, held while the app uses it ---------------------------------------------------


class FakeDocker(Docker):
    """The agent runs for `running_for` checks; the app-server shows up after `connects_after`."""

    def __init__(self, running_for: int, connects_after: int | None) -> None:
        self.commands: list[list[str]] = []
        self.running_for = running_for
        self.connects_after = connects_after
        self.checks = 0
        self.execs = 0
        super().__init__(self._run)

    def _run(self, command, **options):
        self.commands.append(command)
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


def test_the_first_launch_sets_the_copy_up_opens_it_and_notices_the_connection(
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
    assert not any(part.startswith("codex://") for part in opened)  # set up already: no add link
    assert any(c[:2] == ["docker", "exec"] and "root" in c for c in docker.commands)  # prepared
    info = json.loads((running.folder / "launch.json").read_text())
    assert info["app"]["connected"] is True and info["app"]["alias"] == "umcodex-thesis-a1"
    assert info["app"]["seeded"] is True
    assert info["setup_id"] == "thesis-a1" and info["started_at"] == 100.0
    assert codex_app.connected_before("thesis-a1", data_folder)
    assert any("opens on this setup's project" in line for line in said)
    assert any(line.startswith("Connected") for line in said)
    home, _ = codex_app.copy_paths(data_folder)
    state = json.loads((home / ".codex-global-state.json").read_text())
    assert state["remote-connection-auto-connect-by-host-id"] == {
        "remote-ssh-discovered:umcodex-thesis-a1": True
    }
    port = codex_app.local_chats_port(data_folder)
    assert f"127.0.0.1:{port}/um-codex-local/umcodex-thesis-a1/v1" in (home / "config.toml").read_text()
    assert not (codex_app.app_folder(data_folder) / "launch-token").exists()  # never written
    assert "tok-123" not in (home / "config.toml").read_text()
    assert (ssh_home / ".ssh" / "um-codex" / "config").read_text().count("Host umcodex-thesis-a1") == 1


def test_a_copy_state_of_an_unknown_shape_gets_the_steps_and_the_add_link(tmp_path, data_folder):
    home, _ = codex_app.copy_paths(data_folder)
    home.mkdir(parents=True)
    (home / ".codex-global-state.json").write_text(json.dumps({"remote-projects": {"not": "a list"}}))
    running = _running(tmp_path, data_folder)
    calls: list[list[str]] = []
    hold = codex_app.AppHold(
        "thesis-a1", say=lambda _: None, data=data_folder, app=Path("/Applications/ChatGPT.app"),
        docker=FakeDocker(running_for=1, connects_after=None), run=_ran(calls), sleep=lambda _: None,
        proxy_for=lambda s: ["/x/um-codex", "ssh-proxy", s],
    )  # fmt: skip
    hold(running)
    opened = next(c for c in calls if c[0] == "/usr/bin/open")
    assert opened[-1] == "codex://settings/connections/ssh/add?name=umcodex-thesis-a1"
    info = json.loads((running.folder / "launch.json").read_text())
    assert info["app"]["seeded"] is False and info["app"]["first_time"] is True
    assert json.loads((home / ".codex-global-state.json").read_text()) == {
        "remote-projects": {"not": "a list"}
    }


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


def _windows_hold(tmp_path, data_folder, docker, *, clock=lambda: 0.0, starts=True, busy=lambda: False):
    """An AppHold on Windows whose copy shows up in Win32_Process once started."""
    calls: list[list[str]] = []
    started: list[tuple[list[str], dict]] = []
    said: list[str] = []
    _, user_data = codex_app.copy_paths(data_folder)
    plain = _ran(calls)

    def run(command, **options):
        if command[0].lower().endswith("powershell.exe") and "Win32_Process" in command[-1]:
            calls.append(command)
            killed = any(c[0].lower().endswith("taskkill.exe") for c in calls)
            line = f'4242 "{WINDOWS_PACKAGE}\\app\\ChatGPT.exe" --user-data-dir={user_data}'
            shown = started and starts and not killed
            return subprocess.CompletedProcess(command, 0, line if shown else "", "")
        return plain(command, **options)

    hold = codex_app.AppHold(
        "thesis-a1", say=said.append, data=data_folder, app=Path(WINDOWS_PACKAGE) / "app" / "ChatGPT.exe",
        docker=docker, run=run, sleep=lambda _: None, clock=clock, runtime_busy=busy,
        proxy_for=lambda s: ["C:/x/um-codex.exe", "ssh-proxy", s], platform="win32",
        popen=lambda command, **options: started.append((command, options)),
    )  # fmt: skip
    return hold, calls, started, said


def test_on_windows_the_copy_is_started_with_its_own_home(tmp_path, data_folder):
    running = _running(tmp_path, data_folder)
    docker = FakeDocker(running_for=3, connects_after=0)
    hold, calls, started, said = _windows_hold(tmp_path, data_folder, docker)
    assert hold(running) == 0  # connected, then the sandbox was stopped
    assert not any(c[0] == "/usr/bin/open" for c in calls)
    ((command, options),) = started
    home, user_data = codex_app.copy_paths(data_folder)
    assert command[0] == str(hold.app) and command[1] == f"--user-data-dir={user_data}"
    assert options["env"]["CODEX_HOME"] == str(home)  # never the person's ~/.codex
    assert options["env"]["CODEX_ELECTRON_USER_DATA_PATH"] == str(user_data)
    assert options["stdin"] == subprocess.DEVNULL and options["creationflags"]
    assert (home / ".codex-global-state.json").exists()  # seeded, as on a Mac
    assert not any("Dock" in line for line in said)
    assert all(note in said for note in codex_app.WINDOWS_NOTES)
    assert any(line.startswith("Connected:") for line in said)
    assert not any("taskkill" in c[0] for c in calls)


def test_on_windows_a_copy_that_doesnt_connect_is_stopped(tmp_path, data_folder):
    running = _running(tmp_path, data_folder)
    times = iter([0.0, 10.0, codex_app.WINDOWS_CONNECT_SECONDS + 1])
    docker = FakeDocker(running_for=99, connects_after=None)
    hold, calls, _, said = _windows_hold(tmp_path, data_folder, docker, clock=lambda: next(times))
    assert hold(running) == 1
    assert [c[1:] for c in calls if c[0].lower().endswith("taskkill.exe")] == [["/PID", "4242", "/T", "/F"]]
    assert said[-1] == codex_app.WINDOWS_FALLBACK
    info = json.loads((running.folder / "launch.json").read_text())
    assert info["app"]["fallback"] == "terminal" and info["app"]["connected"] is False


def test_on_windows_a_runtime_download_puts_the_fallback_off(tmp_path, data_folder):
    running = _running(tmp_path, data_folder)
    late = codex_app.WINDOWS_CONNECT_SECONDS + 1
    times = iter([0.0, late, late + 10, late + 20])
    busy = iter([True, True, False])
    docker = FakeDocker(running_for=99, connects_after=None)
    hold, calls, _, said = _windows_hold(
        tmp_path, data_folder, docker, clock=lambda: next(times), busy=lambda: next(busy)
    )
    assert hold(running) == 1  # stopped only once the download had ended
    assert said[-1] == codex_app.WINDOWS_FALLBACK
    assert next(busy, "all asked") == "all asked"
    times = iter([0.0, late + codex_app.WINDOWS_UPDATE_GRACE_SECONDS + 1])  # not for ever
    hold, _, _, _ = _windows_hold(
        tmp_path, data_folder / "b", docker, clock=lambda: next(times), busy=lambda: True
    )
    assert hold(_running(tmp_path / "b", data_folder / "b")) == 1


def test_a_runtime_download_is_seen_by_its_staging_folder(tmp_path):
    staging = tmp_path / ".cache" / "codex-runtimes" / "codex-runtime-install-SsKNSv"
    (staging / "payload").mkdir(parents=True)
    part = staging / "payload" / "node"
    part.write_bytes(b"x")
    os.utime(part, (1000.0, 1000.0))  # extracted files keep the archive's old times
    made = time.time()
    assert win.runtime_update_running(tmp_path, now=made + 60) is True
    assert win.runtime_update_running(tmp_path, now=made + 3600) is False  # left over long ago
    assert win.runtime_update_running(tmp_path / "nobody", now=made + 60) is False


def test_on_windows_only_our_copy_is_ever_stopped(data_folder):
    _, user_data = codex_app.copy_paths(data_folder)
    exe = f'"{WINDOWS_PACKAGE}\\app\\ChatGPT.exe"'
    ours = f'4242 {exe} --user-data-dir="{user_data}"'
    calls: list[list[str]] = []

    def now_running(listing, *, after="", taskkill_code=0):
        """Win32_Process shows `listing`, and `after` once taskkill has run."""

        def run(command, **options):
            calls.append(command)
            if command[0].lower().endswith("taskkill.exe"):
                return subprocess.CompletedProcess(command, taskkill_code, "", "")
            killed = any(c[0].lower().endswith("taskkill.exe") for c in calls)
            return subprocess.CompletedProcess(command, 0, after if killed else listing, "")

        return run

    # The number now belongs to another process (the person's own copy): nothing is stopped.
    assert win.stop(4242, user_data, now_running(f"4242 {exe} ")) is False
    assert win.stop(4242, user_data, now_running(f"999 {exe} --user-data-dir={user_data}")) is False
    assert not any(c[0].lower().endswith("taskkill.exe") for c in calls)
    assert win.stop(4242, user_data, now_running(ours)) is True
    assert [c for c in calls if c[0].lower().endswith("taskkill.exe")][-1][1:] == ["/PID", "4242", "/T", "/F"]
    # taskkill /T says 128 when a helper was already ending, but the copy is gone: stopped.
    calls.clear()
    assert win.stop(4242, user_data, now_running(ours, taskkill_code=128)) is True
    calls.clear()
    assert win.stop(4242, user_data, now_running(ours, after=ours, taskkill_code=1)) is False  # still there


def test_on_windows_a_copy_that_doesnt_start_ends_the_launch(tmp_path, data_folder):
    running = _running(tmp_path, data_folder)
    docker = FakeDocker(running_for=99, connects_after=None)
    hold, calls, started, said = _windows_hold(tmp_path, data_folder, docker, starts=False)
    assert hold(running) == 1 and len(started) == 1
    assert not any(c[0].lower().endswith("taskkill.exe") for c in calls)  # nothing of ours to stop
    assert said[-1] == codex_app.WINDOWS_FALLBACKS["not-started"]
    info = json.loads((running.folder / "launch.json").read_text())
    assert info["app"]["fallback"] == "terminal"
    assert info["app"]["fallback_message"] == codex_app.WINDOWS_FALLBACKS["not-started"]


class _Held:
    """A process this launch started (subprocess.Popen's pid, poll, wait)."""

    def __init__(self, pid: int) -> None:
        self.pid, self.ended = pid, False

    def poll(self):
        return 0 if self.ended else None

    def wait(self, timeout=None):  # after taskkill: it has ended
        self.ended = True
        return 0


def test_on_windows_the_started_process_is_the_copy_when_the_lookup_cant_tell(tmp_path, data_folder):
    """A profile path Win32_Process doesn't give back as written (an
    encoding, a short name): the process this launch started and still holds
    is the copy, and it's what the fallback stops."""
    running = _running(tmp_path, data_folder)
    times = iter([0.0, codex_app.WINDOWS_CONNECT_SECONDS + 1])
    docker = FakeDocker(running_for=99, connects_after=None)
    hold, calls, started, said = _windows_hold(
        tmp_path, data_folder, docker, starts=False, clock=lambda: next(times)
    )
    held = _Held(5150)

    def kill(command, **options):
        if command[0].lower().endswith("taskkill.exe"):
            held.ended = True
        return calls.append(command) or subprocess.CompletedProcess(command, 0, "", "")

    hold.popen = lambda command, **options: started.append((command, options)) or held
    plain_run = hold.run
    hold.run = lambda command, **options: (
        kill(command) if command[0].lower().endswith("taskkill.exe") else plain_run(command, **options)
    )
    assert hold(running) == 1
    assert [c[1:3] for c in calls if c[0].lower().endswith("taskkill.exe")] == [["/PID", "5150"]]
    assert said[-1] == codex_app.WINDOWS_FALLBACKS["stopped"]


def test_on_windows_a_copy_another_setup_uses_isnt_stopped(tmp_path, data_folder, monkeypatch):
    running = _running(tmp_path, data_folder)
    times = iter([0.0, codex_app.WINDOWS_CONNECT_SECONDS + 1])
    docker = FakeDocker(running_for=99, connects_after=None)
    hold, calls, _, said = _windows_hold(tmp_path, data_folder, docker, clock=lambda: next(times))
    this = launch.RunningLaunch("ab12cd34", "thesis-a1", "Thesis", 100.0, app={"alias": "umcodex-thesis-a1"})
    other = launch.RunningLaunch("ffff0000", "other-b2", "Other", 90.0, app={"alias": "umcodex-other-b2"})
    in_terminal = launch.RunningLaunch("eeee0000", "t-c3", "T", 95.0, app=None)
    monkeypatch.setattr(launch, "running_launches", lambda data: [other, in_terminal, this])
    assert hold(running) == 1
    assert not any(c[0].lower().endswith("taskkill.exe") for c in calls)
    assert said[-1] == codex_app.WINDOWS_FALLBACKS["shared"]
    # Only this launch, or another one in a terminal: the copy is ours to stop.
    monkeypatch.setattr(launch, "running_launches", lambda data: [in_terminal, this])
    assert not hold._copy_shared(running)


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


def test_a_broken_copy_config_is_moved_aside(tmp_path, data_folder, caplog):
    home, _ = codex_app.copy_paths(data_folder)
    home.mkdir(parents=True)
    (home / "config.toml").write_text("this isn't [ toml")
    running = _running(tmp_path, data_folder)
    hold = codex_app.AppHold(
        "thesis-a1", say=lambda _: None, data=data_folder, app=None,
        docker=FakeDocker(running_for=1, connects_after=None), run=_ran([]), sleep=lambda _: None,
        proxy_for=lambda s: ["/x/um-codex", "ssh-proxy", s],
    )  # fmt: skip
    with caplog.at_level("WARNING"):
        hold(running)
    (aside,) = home.glob("config.toml.bad-*")
    assert aside.read_text() == "this isn't [ toml"
    assert tomllib.loads((home / "config.toml").read_text())["model_provider"] == "toolkit"
    assert "didn't parse" in caplog.text


def test_the_include_keeps_crlf_links_and_mode_and_refreshes_a_stale_backup(ssh_home):
    ssh = ssh_home / ".ssh"
    ssh.mkdir()
    real = ssh / "real-config"
    real.write_bytes(b"Host a\r\n  User me\r\n")
    os.chmod(real, 0o640)
    (ssh / "config").symlink_to(real)
    (ssh / "config.um-codex-backup").write_bytes(b"an old backup\n")
    assert codex_app.add_include() == "added"
    assert (ssh / "config").is_symlink()  # the link still works
    assert real.read_bytes() == b"Include ~/.ssh/um-codex/config\r\nHost a\r\n  User me\r\n"
    assert stat.S_IMODE(real.stat().st_mode) == 0o640
    assert (ssh / "config.um-codex-backup").read_bytes() == b"Host a\r\n  User me\r\n"  # refreshed
    assert not [p for p in ssh.iterdir() if p.name.startswith(".")]  # no temporary files left
    codex_app.remove_include()
    assert real.read_bytes() == b"Host a\r\n  User me\r\n"
    assert not (ssh / "config.um-codex-backup").exists()


@pytest.mark.parametrize("first", ["Host=a", "Host = a", "Match all", "host\ta"])
def test_an_include_after_any_host_form_doesnt_count(ssh_home, first):
    ssh = ssh_home / ".ssh"
    ssh.mkdir()
    (ssh / "config").write_text(f"{first}\nInclude ~/.ssh/um-codex/config\n")
    assert not codex_app.include_present()


def test_a_config_that_isnt_text_is_left_alone(ssh_home):
    ssh = ssh_home / ".ssh"
    ssh.mkdir()
    (ssh / "config").write_bytes(b"\xff\xfe binary")
    with pytest.raises(UnicodeDecodeError):
        codex_app.add_include()
    assert (ssh / "config").read_bytes() == b"\xff\xfe binary"


# --- The copy's state file (shapes the app 26.928 wrote in the GUI test) -------------

GUI_TEST_STATE = {
    "local-projects": {},
    "codex-managed-remote-connections": [
        {
            "hostId": "remote-ssh-discovered:umcodex-other-c3",
            "displayName": "umcodex-other-c3",
            "source": "discovered",
            "alias": "umcodex-other-c3",
            "hostname": None,
            "sshPort": None,
            "identity": None,
            "connectionAnalyticsId": "c55f5ada-089f-49d5-90d1-cc733963b884",
        }
    ],
    "remote-connection-auto-connect-by-host-id": {"remote-ssh-discovered:umcodex-other-c3": True},
    "remote-projects": [
        {
            "id": "3df46154",
            "hostId": "remote-ssh-discovered:umcodex-other-c3",
            "remotePath": "/work",
            "label": "work",
        }
    ],
    "project-order": ["3df46154"],
    "selected-project": {"type": "remote", "projectId": "3df46154"},
    "electron-persisted-atom-state": {
        "seen-model-upgrade-list": ["gpt-6.1-sol"],
        "home-composer-mode-v1": "work",
    },
}


def test_the_copy_state_gets_the_host_on_its_project_selected_and_pop_ups_seen():
    setup = Setup(id="thesis-a1", name="Thesis", working="/tmp")
    state = codex_app.seeded_state(GUI_TEST_STATE, setup, seen_models=["gpt-6.1-sol", "gpt-7"])
    host = "remote-ssh-discovered:umcodex-thesis-a1"
    mine = next(c for c in state["codex-managed-remote-connections"] if c["hostId"] == host)
    assert mine["alias"] == "umcodex-thesis-a1" and mine["source"] == "discovered"
    assert mine["connectionAnalyticsId"] == state["remote-connection-analytics-id-by-host-id"][host]
    assert state["remote-connection-auto-connect-by-host-id"][host] is True
    project = next(p for p in state["remote-projects"] if p["hostId"] == host)
    assert project == {
        "id": codex_app.project_id("thesis-a1"),
        "hostId": host,
        "remotePath": "/work",
        "label": "Thesis",
    }
    assert state["project-order"][0] == project["id"] and "3df46154" in state["project-order"]
    assert state["selected-project"] == {"type": "remote", "projectId": project["id"]}
    atoms = state["electron-persisted-atom-state"]
    assert atoms["electron:onboarding-projectless-completed"] is True
    assert atoms["seen-model-upgrade-list"] == ["gpt-6.1-sol", "gpt-7"]
    assert "electron:onboarding-welcome-v2-role-state" not in atoms  # no role chosen for the person
    assert atoms["home-composer-mode-v1"] == "work"  # the app's own state kept
    # The other setup's host and project are kept, and a second pass changes nothing.
    assert len(state["codex-managed-remote-connections"]) == 2 and len(state["remote-projects"]) == 2
    assert codex_app.seeded_state(state, setup, seen_models=["gpt-7"]) == state
    assert GUI_TEST_STATE["project-order"] == ["3df46154"]  # the input isn't changed


@pytest.mark.parametrize(
    "broken",
    [
        {"remote-projects": {}},
        {"codex-managed-remote-connections": "x"},
        {"electron-persisted-atom-state": []},
        {"electron-persisted-atom-state": {"seen-model-upgrade-list": "gpt"}},
    ],
)
def test_an_unknown_state_shape_isnt_touched(broken):
    with pytest.raises(codex_app.StateUnknown):
        codex_app.seeded_state(broken, Setup(id="a1", name="A", working="/tmp"))


def test_the_state_file_and_its_backup_are_written_the_way_the_app_reads_them(tmp_path):
    (tmp_path / ".codex-global-state.json").write_text("{ not json")
    (tmp_path / ".codex-global-state.json.bak").write_text(json.dumps({"project-order": ["x"]}))
    codex_app.seed_copy(tmp_path, Setup(id="a1", name="A", working="/tmp"))
    main = json.loads((tmp_path / ".codex-global-state.json").read_text())
    assert main == json.loads((tmp_path / ".codex-global-state.json.bak").read_text())
    assert main["project-order"][-1] == "x"  # read from the backup, as the app does


def test_the_copys_catalog_has_no_announcements(tmp_path):
    bundled = Path(__file__).parent / "data" / "codex-0.157.1-bundled-models.json"
    entries = json.loads(bundled.read_text())["models"]
    entries[0]["availability_nux"] = {"title": "Introducing"}
    text = json.dumps({"models": entries})
    calls = []

    def run(command, **options):
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 0, text, "")

    catalog, announced = codex_app.bundled_catalog(Path("/A.app"), tmp_path, "gpt-5.6-terra", run=run)
    assert announced == [entries[0]["slug"]]
    assert calls[0][0][-3:] == ["debug", "models", "--bundled"]
    assert calls[0][1]["env"]["CODEX_HOME"] == str(tmp_path)  # never the person's ~/.codex
    assert catalog is not None
    assert all(m["availability_nux"] is None and m["upgrade"] is None for m in json.loads(catalog)["models"])
    failed = lambda c, **o: subprocess.CompletedProcess(c, 1, "", "")  # noqa: E731
    assert codex_app.bundled_catalog(Path("/A.app"), tmp_path, "m", run=failed) == (None, [])
    calls.clear()
    windows = Path(WINDOWS_PACKAGE) / "app" / "ChatGPT.exe"
    assert codex_app.bundled_catalog(windows, tmp_path, "gpt-5.6-terra", run=run)[1] == announced
    assert calls[0][0][0] == str(Path(WINDOWS_PACKAGE) / "app" / "resources" / "codex.exe")
    assert calls[0][1]["env"]["CODEX_HOME"] == str(tmp_path) == calls[0][1]["env"]["USERPROFILE"]


# --- The local-chats responder ------------------------------------------------------


def test_the_responder_port_is_kept_and_taken_over_when_free(data_folder):
    import httpx

    first = codex_app.LocalChatsServer(data_folder)
    port = first.ensure()
    assert port == codex_app.local_chats_port(data_folder)  # kept in the data folder
    second = codex_app.LocalChatsServer(data_folder)
    try:
        assert second.ensure() == port and not second.serving  # the first one serves it
        answer = httpx.post(f"http://127.0.0.1:{port}/um-codex-local/umcodex-a1/v1/responses", content=b"{}")
        assert "no UM-Codex setup is running" in answer.text
        first.stop()
        assert second.ensure() == port and second.serving  # taken over
    finally:
        first.stop()
        second.stop()


def test_a_port_held_by_another_program_is_replaced(data_folder):
    import socket

    taken = socket.socket()
    taken.bind(("127.0.0.1", 0))
    taken.listen()
    try:
        path = codex_app.app_folder(data_folder) / "local-chats-port"
        path.parent.mkdir(parents=True)
        path.write_text(f"{taken.getsockname()[1]}\n")
        server = codex_app.LocalChatsServer(data_folder)
        try:
            port = server.ensure()
            assert port != taken.getsockname()[1] and server.serving
            assert codex_app.local_chats_port(data_folder) == port
        finally:
            server.stop()
    finally:
        taken.close()


def test_ssh_folders_and_files_get_only_the_persons_permissions_on_windows(tmp_path, monkeypatch):
    """Windows: no mkdir mode (Python 3.13's 0o700 means OWNER RIGHTS there,
    which OpenSSH refuses), and UM-Codex's own ssh folders and files set to
    the person, SYSTEM and Administrators with icacls; elsewhere, 0o700."""
    modes, locked = [], []
    real = Path.mkdir

    def mkdir(self, *args, **options):
        modes.append(options.get("mode"))
        return real(self, *args, **options)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(
        codex_app, "_windows_owner_only", lambda path, folder: locked.append((path, folder)) or True
    )
    codex_app._ssh_mkdir(tmp_path / "w", platform="win32")
    codex_app._ssh_mkdir(tmp_path / "theirs", platform="win32", own=False)  # a ~/.ssh that was there
    codex_app._ssh_write(tmp_path / "w" / "config", "Host x\n", platform="win32")
    codex_app._ssh_mkdir(tmp_path / "m" / "n", parents=True, platform="darwin")
    codex_app._ssh_write(tmp_path / "m" / "n" / "config", "Host x\n", platform="darwin")
    assert modes[:2] == [None, None] and 0o700 in modes[2:]
    assert locked == [(tmp_path / "w", True), (tmp_path / "w" / "config", False)]
    assert (tmp_path / "m" / "n" / "config").read_text() == "Host x\n"


def test_windows_permissions_are_set_with_icacls(tmp_path):
    calls = []

    def run(command, **options):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    assert codex_app._windows_owner_only(tmp_path, folder=True, run=run, sid="S-1-5-21-1-2-3-1001")
    assert calls[-1][0].lower().endswith(r"\system32\icacls.exe")
    assert calls[-1][1:] == [
        str(tmp_path), "/inheritance:r",
        "/grant:r", "*S-1-5-21-1-2-3-1001:(OI)(CI)F",
        "/grant:r", "*S-1-5-18:(OI)(CI)F",
        "/grant:r", "*S-1-5-32-544:(OI)(CI)F",
        "/Q",
    ]  # fmt: skip
    assert codex_app._windows_owner_only(tmp_path / "f", folder=False, run=run, sid="S-1-5-21-9")
    assert calls[-1][3:5] == ["/grant:r", "*S-1-5-21-9:F"]
    failed = lambda c, **o: subprocess.CompletedProcess(c, 5, "Access is denied.", "")  # noqa: E731
    assert not codex_app._windows_owner_only(tmp_path, folder=True, run=failed, sid="S-1-5-21-9")


WINDOWS_SSH = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "OpenSSH" / "ssh.exe"


def _acls(*paths: Path) -> str:
    return "\n".join(subprocess.run(["icacls", str(p)], capture_output=True, text=True).stdout for p in paths)


@pytest.mark.skipif(sys.platform != "win32" or not WINDOWS_SSH.is_file(), reason="needs Windows OpenSSH")
def test_windows_openssh_accepts_umcodex_ssh_folders(tmp_path):
    """The real check, with Windows' own ssh.exe: a config UM-Codex writes in
    folders it made is accepted when reached through an Include (ssh checks
    included files' permissions; a file given with -F it doesn't), whatever
    the folder above hands down (pytest's tmp_path, made with 0o700, hands
    down OWNER RIGHTS) and whatever the account. The same file written in a
    folder made with mkdir(mode=0o700) is refused, so the check runs."""
    host = "Host umcodex-x\n  HostName umcodex-x.invalid\n"

    def resolves(config: Path) -> subprocess.CompletedProcess:
        top = tmp_path / f"top-{config.parent.name}"
        top.write_text(f"Include {config.as_posix()}\n", encoding="utf-8")
        return subprocess.run(
            [str(WINDOWS_SSH), "-G", "-F", str(top), "umcodex-x"],
            capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL,
        )  # fmt: skip

    ours = tmp_path / ".ssh"
    codex_app._private_dir(ours)
    codex_app._private_dir(ours / "um-codex")
    config = ours / "um-codex" / "config"
    codex_app._ssh_write(config, host)
    done = resolves(config)
    assert done.returncode == 0 and "Bad permissions" not in done.stderr, done.stderr + _acls(ours, config)
    assert "hostname umcodex-x.invalid" in done.stdout.splitlines()
    refused = tmp_path / "with-mode"
    os.mkdir(refused, 0o700)
    codex_app._private_write(refused / "config", host)
    done = resolves(refused / "config")
    assert done.returncode != 0 and "Bad permissions" in done.stderr, done.stderr + _acls(refused)


def test_windows_lookups_read_powershell_as_utf8_and_find_a_non_ascii_profile(tmp_path):
    """Windows PowerShell 5.1 writes redirected output in the OEM code page,
    so a profile under C:/Users/José came back as "Jos?" and never matched."""
    user_data = tmp_path / "Jos\u00e9 N\u00fa\u00f1ez" / "UM-Codex" / "codex-app" / "user-data"
    asked = []

    def run(command, **options):
        asked.append((command, options))
        line = f'7311 "{WINDOWS_PACKAGE}\\app\\ChatGPT.exe" "--user-data-dir={user_data}"'
        return subprocess.CompletedProcess(command, 0, line + "\r\n", "")

    assert win.find_copy(user_data, run) == 7311
    command, options = asked[0]
    assert command[-1].startswith("[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); ")
    assert options["encoding"] == "utf-8" and options["errors"] == "replace"


def test_windows_stop_uses_the_held_process_when_the_lookup_cant_find_it(tmp_path):
    calls = []

    def nothing_found(command, **options):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    held = _Held(5150)
    assert win.stop(5150, tmp_path, nothing_found, held) is True  # the process it holds: ours
    assert [c[1:3] for c in calls if c[0].lower().endswith("taskkill.exe")] == [["/PID", "5150"]]
    calls.clear()
    ended = _Held(5150)
    ended.ended = True  # it ended: the number may be someone else's now
    assert win.stop(5150, tmp_path, nothing_found, ended) is False
    assert win.stop(5150, tmp_path, nothing_found, _Held(9999)) is False  # not that process
    assert not any(c[0].lower().endswith("taskkill.exe") for c in calls)


def test_windows_ssh_files_that_cant_be_trusted_arent_left(tmp_path, monkeypatch):
    """icacls failing: the file ssh would refuse (and with it every host) is
    taken away, and the launch stops with a plain message."""
    monkeypatch.setattr(codex_app, "_windows_owner_only", lambda path, folder: False)
    with pytest.raises(codex_app.SshPermissionsError) as raised:
        codex_app._ssh_write(tmp_path / "config", "Host x\n", platform="win32")
    assert not (tmp_path / "config").exists()
    assert "Terminal" in str(raised.value) and "weren't changed" in str(raised.value)
    with pytest.raises(codex_app.SshPermissionsError):
        codex_app._ssh_mkdir(tmp_path / "um-codex", platform="win32")
    codex_app._ssh_mkdir(tmp_path / "theirs", platform="win32", own=False)  # theirs: not changed, no error


def test_the_sid_lookup_isnt_kept_when_it_fails(monkeypatch):
    monkeypatch.setattr(codex_app, "_sid", None)
    answers = iter([subprocess.CompletedProcess([], 1, "", "no"), subprocess.CompletedProcess(
        [], 0, '"umhs\\someone","S-1-5-21-1-2-3-1001"\r\n', ""
    )])  # fmt: skip
    asked = []

    def run(command, **options):
        asked.append(command)
        return next(answers)

    assert codex_app._windows_user_sid(run) is None
    assert codex_app._windows_user_sid(run) == "S-1-5-21-1-2-3-1001"  # asked again
    kept = codex_app._windows_user_sid(lambda *a, **o: pytest.fail("asked a third time"))
    assert kept == "S-1-5-21-1-2-3-1001"
    assert asked[0][0].lower().endswith(r"\system32\whoami.exe")


def test_on_windows_the_include_keeps_the_files_access_rules(ssh_home, monkeypatch):
    """The new ~/.ssh/config (a new file) and its backup get the original's
    access rules; if Windows' ssh then refuses the file, it's put back."""
    config = ssh_home / ".ssh" / "config"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("Host mine\n  HostName example.invalid\n")
    rules = "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;S-1-5-21-1-2-3-1001)"
    given = []
    monkeypatch.setattr(win, "access_rules", lambda path, run=None: rules)
    monkeypatch.setattr(
        win, "set_access_rules", lambda path, sddl, run=None: given.append((path.name, sddl)) or True
    )
    monkeypatch.setattr(codex_app, "repair_ssh_dir", lambda *a, **o: False)
    monkeypatch.setattr(codex_app, "_is_the_persons_ssh", lambda home: True)
    monkeypatch.setattr(win, "ssh_refuses_config", lambda run=None: None)
    assert codex_app.add_include(platform="win32") == "added"
    assert config.read_text().startswith(codex_app.INCLUDE_LINE)
    assert given == [(codex_app.BACKUP_NAME, rules), ("config", rules)]
    # ssh refuses it after all: the file is put back as it was, rules too.
    config.write_text("Host mine\n  HostName example.invalid\n")
    given.clear()
    monkeypatch.setattr(win, "ssh_refuses_config", lambda run=None: "Bad permissions. Try removing ...")
    with pytest.raises(codex_app.SshPermissionsError):
        codex_app.add_include(platform="win32")
    assert config.read_text() == "Host mine\n  HostName example.invalid\n"
    assert given[-1] == ("config", rules)


def test_an_ssh_folder_an_earlier_umcodex_made_is_repaired_folder_by_folder_on_windows(ssh_home, monkeypatch):
    """Only folders with exactly Python 3.13's 0o700 rules: ~/.ssh only with
    UM-Codex's note, its own folders under ~/.ssh/um-codex wherever they
    have them. One at a time, never /T, and the person is given full rights
    before OWNER RIGHTS goes, so no folder is ever left without them."""
    own = ssh_home / ".ssh" / "um-codex"
    nested = own / "installs" / "1483d901e834a396"
    nested.mkdir(parents=True, exist_ok=True)
    (own / codex_app.SSH_DIR_MADE).write_text("yes\n")
    monkeypatch.setattr(codex_app, "_sid", "S-1-5-21-1-2-3-1001")
    python_0700 = {ssh_home / ".ssh", own, own / "installs", nested}
    monkeypatch.setattr(win, "owner_rights_only", lambda folder, run=None: folder in python_0700)
    ran = []

    def run(command, **options):
        ran.append([Path(command[1]).relative_to(ssh_home).as_posix(), *command[2:]])
        return subprocess.CompletedProcess(command, 0, "", "")

    assert codex_app.repair_ssh_dir(run=run, platform="win32")
    grant = [
        "/inheritance:r", "/grant:r", "*S-1-5-21-1-2-3-1001:(OI)(CI)F", "/grant:r", "*S-1-5-18:(OI)(CI)F",
        "/grant:r", "*S-1-5-32-544:(OI)(CI)F", "/Q",
    ]  # fmt: skip
    expected = []
    folders = (".ssh", ".ssh/um-codex", ".ssh/um-codex/installs", ".ssh/um-codex/installs/1483d901e834a396")
    for folder in folders:
        expected += [[folder, *grant], [folder, "/remove:g", "*S-1-3-4", "/Q"]]
    assert ran == expected
    assert not any("/T" in command for command in ran)
    # Without UM-Codex's note, the person's own ~/.ssh isn't touched (only UM-Codex's folders).
    (own / codex_app.SSH_DIR_MADE).unlink()
    ran.clear()
    assert codex_app.repair_ssh_dir(run=run, platform="win32")
    assert ".ssh" not in [command[0] for command in ran]
    # A grant that fails: OWNER RIGHTS stays (the person keeps their access through it).
    ran.clear()

    def refused(command, **options):
        ran.append(command[2:4])
        return subprocess.CompletedProcess(command, 5, "Access is denied.", "")

    assert not codex_app.repair_ssh_dir(run=refused, platform="win32")
    assert ["/remove:g", "*S-1-3-4"] not in ran
    monkeypatch.setattr(win, "owner_rights_only", lambda folder, run=None: False)  # the person's own rules
    assert not codex_app.repair_ssh_dir(run=run, platform="win32")
    assert not codex_app.repair_ssh_dir(run=run, platform="darwin")


def test_python_313s_windows_0o700_rules_are_recognised_exactly(monkeypatch):
    for sddl, expected in (
        ("D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)", True),  # mkdir(mode=0o700), live 2026-10-02
        ("D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;OW)", True),  # the same, in another order
        ("D:(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)(A;OICIID;FA;;;OW)", False),  # inherited, not made so
        ("D:PAI(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)", False),  # other flags
        ("D:P(A;OICI;0x1200a9;;;OW)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)", False),  # other rights
        ("D:P(D;OICI;FA;;;OW)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)", False),  # a deny
        ("D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;WD)", False),  # one more
        ("D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;S-1-5-21-1-2-3-1001)", False),  # the person's
    ):
        monkeypatch.setattr(win, "saved_rules", lambda folder, run=None, s=sddl: s)
        assert win.owner_rights_only(Path("x")) is expected, sddl


def test_folder_rules_come_from_icacls_save(tmp_path):
    """icacls /save, as it wrote on a Windows 11 laptop (UTF-16, the name then the SDDL)."""
    asked = []

    def run(command, **options):
        asked.append(command)
        Path(command[3]).write_bytes(
            "with-mode\r\nD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;OW)\r\n".encode("utf-16-le")
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    assert win.saved_rules(tmp_path, run) == "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;OW)"
    assert asked[0][0].lower().endswith(r"\system32\icacls.exe") and asked[0][1:3] == [str(tmp_path), "/save"]
    assert not Path(asked[0][3]).exists()  # its own file goes again
    failed = lambda c, **o: subprocess.CompletedProcess(c, 5, "", "denied")  # noqa: E731
    assert win.saved_rules(tmp_path, failed) is None


def test_powershell_gets_paths_through_the_environment():
    """A path is never written into the command: PowerShell takes U+2018 to
    U+201B for a single quote too, so O\u2019Brien would end the string."""
    path = Path("C:/Users/O\u2019Brien's") / "it\u2018s \u201b" / "config"
    asked = []

    def run(command, **options):
        asked.append((command, options))
        return subprocess.CompletedProcess(command, 0, "D:(A;ID;FA;;;SY)\r\n", "")

    assert win.access_rules(path, run) == "D:(A;ID;FA;;;SY)"
    assert win.set_access_rules(path, "D:P(A;;FA;;;SY)", run)
    for command, options in asked:
        assert str(path) not in command[-1] and "O\u2019Brien" not in command[-1]
        assert options["env"]["UMCODEX_PS_PATH"] == str(path)
    assert asked[1][1]["env"]["UMCODEX_PS_SDDL"] == "D:P(A;;FA;;;SY)"
    assert "$env:UMCODEX_PS_SDDL" in asked[1][0][-1]
    assert not win.set_access_rules(path, "not sddl", run)


def test_on_a_mac_the_include_leaves_no_windows_note(ssh_home):
    assert codex_app.add_include(platform="darwin") == "created"
    assert not (ssh_home / ".ssh" / "um-codex").exists()


def test_a_rollback_whose_permissions_cant_be_put_back_says_so(ssh_home, monkeypatch):
    config = ssh_home / ".ssh" / "config"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("Host mine\n")
    monkeypatch.setattr(win, "access_rules", lambda path, run=None: "D:P(A;;FA;;;SY)")
    calls = []
    monkeypatch.setattr(
        win, "set_access_rules", lambda path, sddl, run=None: calls.append(path.name) or len(calls) < 3
    )
    monkeypatch.setattr(codex_app, "repair_ssh_dir", lambda *a, **o: False)
    monkeypatch.setattr(codex_app, "_is_the_persons_ssh", lambda home: True)
    monkeypatch.setattr(win, "ssh_refuses_config", lambda run=None: "Bad permissions")
    with pytest.raises(codex_app.SshPermissionsError) as raised:
        codex_app.add_include(platform="win32")
    assert config.read_text() == "Host mine\n"
    assert calls == [codex_app.BACKUP_NAME, "config", "config"]  # the third, the rollback's, failed
    assert "not its permissions" in str(raised.value) and "Bad permissions" in str(raised.value)


# --- Every Codex-app setup is known to the copy; a copy that isn't is reopened (GUI round) ---


def _save_app_setups(tmp_path: Path) -> None:
    from umcodex.setups import SetupStore

    store = SetupStore()
    for setup in (
        Setup(id="thesis-a1", name="Thesis", working=str(tmp_path), open_in="codex-app"),
        Setup(id="other-b2", name="Other", working=str(tmp_path), open_in="codex-app"),
        Setup(id="here-c3", name="Here", working=str(tmp_path), open_in="codex-app", runs_on="this-computer"),
        Setup(id="term-d4", name="Term", working=str(tmp_path), open_in="terminal"),
    ):
        store.save(setup)


def test_the_copy_is_set_up_with_every_codex_app_setup(tmp_path, data_folder, ssh_home):
    _save_app_setups(tmp_path)
    running = _running(tmp_path, data_folder)
    hold = codex_app.AppHold(
        "thesis-a1", say=lambda _: None, data=data_folder, app=Path("/Applications/ChatGPT.app"),
        docker=FakeDocker(running_for=3, connects_after=1), run=_ran([]), sleep=lambda _: None,
        proxy_for=lambda s: ["/x/um-codex", "ssh-proxy", s],
    )  # fmt: skip
    assert hold(running) == 0
    home, _ = codex_app.copy_paths(data_folder)
    state = json.loads((home / ".codex-global-state.json").read_text())
    hosts = set(state["remote-connection-auto-connect-by-host-id"])
    assert hosts == {"remote-ssh-discovered:umcodex-thesis-a1", "remote-ssh-discovered:umcodex-other-b2"}
    assert state["selected-project"]["projectId"] == codex_app.project_id("thesis-a1", data_folder)
    assert state["project-order"][0] == codex_app.project_id("thesis-a1", data_folder)
    assert codex_app.copy_knows("other-b2", data_folder) and not codex_app.copy_knows("here-c3", data_folder)
    config = (ssh_home / ".ssh" / "um-codex" / "config").read_text()
    assert "Host umcodex-other-b2" in config and "Host umcodex-here-c3" not in config


class OpenCopy:
    """`ps` lists UM-Codex's copy until it's asked to quit; everything else answers ok."""

    def __init__(self, data: Path) -> None:
        self.data = data
        self.open = True
        self.calls: list[list[str]] = []

    def __call__(self, command, **options):
        self.calls.append(list(command))
        if command[0] == "ssh-keygen":
            key = Path(command[command.index("-f") + 1])
            key.write_text("private")
            key.with_name(key.name + ".pub").write_text("ssh-ed25519 AAAA test\n")
        if command[0] == "/bin/ps":
            _, user_data = codex_app.copy_paths(self.data)
            line = f"4242 /Applications/ChatGPT.app/Contents/MacOS/ChatGPT --user-data-dir={user_data}\n"
            return subprocess.CompletedProcess(command, 0, line if self.open else "", "")
        if command[0] == "/usr/bin/osascript" and "terminate()" in " ".join(command):
            self.open = False
            return subprocess.CompletedProcess(command, 0, "ok\n", "")
        if command[0] == "/usr/bin/open":
            self.open = True
        return subprocess.CompletedProcess(command, 0, "ok", "")


def _open_copy_knowing_only_other(tmp_path: Path, data: Path) -> None:
    _save_app_setups(tmp_path)
    home, _ = codex_app.copy_paths(data)
    home.mkdir(parents=True)
    other = Setup(id="other-b2", name="Other", working=str(tmp_path), open_in="codex-app")
    codex_app.seed_copy(home, other, data=data)


def test_a_copy_that_doesnt_know_the_setup_is_reopened_set_up(tmp_path, data_folder, monkeypatch):
    _open_copy_knowing_only_other(tmp_path, data_folder)
    monkeypatch.setattr(launch, "running_launches", lambda data: [])
    running = _running(tmp_path, data_folder)
    run = OpenCopy(data_folder)
    said: list[str] = []
    hold = codex_app.AppHold(
        "thesis-a1", say=said.append, data=data_folder, app=Path("/Applications/ChatGPT.app"),
        docker=FakeDocker(running_for=3, connects_after=1), run=run, sleep=lambda _: None,
        proxy_for=lambda s: ["/x/um-codex", "ssh-proxy", s], platform="darwin",
    )  # fmt: skip
    assert hold(running) == 0
    quit_at = next(i for i, c in enumerate(run.calls) if "terminate()" in " ".join(c))
    open_at = next(i for i, c in enumerate(run.calls) if c[0] == "/usr/bin/open")
    assert quit_at < open_at  # quit, set up, opened again
    assert codex_app.copy_knows("thesis-a1", data_folder) and codex_app.copy_knows("other-b2", data_folder)
    info = json.loads((running.folder / "launch.json").read_text())["app"]
    assert info["reopened"] is True and info["seeded"] is True and info["copy"] == "opened"
    assert any("Reopening" in line for line in said)


def test_a_copy_another_launch_uses_isnt_reopened(tmp_path, data_folder, monkeypatch):
    _open_copy_knowing_only_other(tmp_path, data_folder)
    other = launch.RunningLaunch("ffff0000", "other-b2", "Other", 90.0, app={"alias": "umcodex-other-b2"})
    monkeypatch.setattr(launch, "running_launches", lambda data: [other])
    running = _running(tmp_path, data_folder)
    run = OpenCopy(data_folder)
    hold = codex_app.AppHold(
        "thesis-a1", say=lambda _: None, data=data_folder, app=Path("/Applications/ChatGPT.app"),
        docker=FakeDocker(running_for=3, connects_after=None), run=run, sleep=lambda _: None,
        proxy_for=lambda s: ["/x/um-codex", "ssh-proxy", s], platform="darwin",
    )  # fmt: skip
    hold(running)
    assert not any("terminate()" in " ".join(c) for c in run.calls)
    assert not any(c[0] == "/usr/bin/open" for c in run.calls)
    info = json.loads((running.folder / "launch.json").read_text())["app"]
    assert info["reopened"] is False and info["first_time"] is True  # the guided steps


def test_a_copy_that_wont_quit_isnt_killed_and_gets_the_steps(tmp_path, data_folder, monkeypatch):
    from umcodex import this_computer

    _open_copy_knowing_only_other(tmp_path, data_folder)
    monkeypatch.setattr(launch, "running_launches", lambda data: [])
    signals: list[int] = []
    monkeypatch.setattr(
        this_computer.os, "kill", lambda pid, sig: signals.append(sig)
    )  # never a real process

    class Stubborn(OpenCopy):
        def __call__(self, command, **options):
            done = super().__call__(command, **options)
            self.open = True  # it doesn't quit when asked
            return done

    run = Stubborn(data_folder)
    running = _running(tmp_path, data_folder)
    hold = codex_app.AppHold(
        "thesis-a1", say=lambda _: None, data=data_folder, app=Path("/Applications/ChatGPT.app"),
        docker=FakeDocker(running_for=3, connects_after=None), run=run, sleep=lambda _: None,
        proxy_for=lambda s: ["/x/um-codex", "ssh-proxy", s], platform="darwin",
    )  # fmt: skip
    hold(running)
    import signal

    assert signals == [signal.SIGTERM]  # asked, then SIGTERM; no SIGKILL
    info = json.loads((running.folder / "launch.json").read_text())["app"]
    assert info["reopened"] is False and info["first_time"] is True


def test_an_unreadable_copy_state_isnt_reopened(tmp_path, data_folder, monkeypatch):
    _save_app_setups(tmp_path)
    home, _ = codex_app.copy_paths(data_folder)
    home.mkdir(parents=True)
    (home / ".codex-global-state.json").write_text("[1, 2]")  # another shape
    assert codex_app.copy_knows("thesis-a1", data_folder) is None
    monkeypatch.setattr(launch, "running_launches", lambda data: [])
    run = OpenCopy(data_folder)
    hold = codex_app.AppHold(
        "thesis-a1", say=lambda _: None, data=data_folder, app=Path("/Applications/ChatGPT.app"),
        docker=FakeDocker(running_for=3, connects_after=None), run=run, sleep=lambda _: None,
        proxy_for=lambda s: ["/x/um-codex", "ssh-proxy", s], platform="darwin",
    )  # fmt: skip
    hold(_running(tmp_path, data_folder))
    assert not any("terminate()" in " ".join(c) for c in run.calls)
