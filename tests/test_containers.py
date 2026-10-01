"""Docker command lines for a launch, and cleanup by label (no Docker needed)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from umcodex.containers import (
    NO_DNS,
    WATCHDOG,
    BindMount,
    Docker,
    DockerError,
    LaunchSpec,
    _guarded,
    exec_command,
    images,
    remove_leftovers,
    render_gateway_conf,
)


def spec(tmp_path: Path, *, internet: bool) -> LaunchSpec:
    folder = tmp_path / "launch"
    return LaunchSpec(
        launch_id="1a2b3c4d",
        instance="0123456789abcdef",
        setup_id="thesis-a1b2c3",
        agent_image="um-codex-agent:dev",
        gateway_image=images()["gateway"],
        internet=internet,
        folders=(
            BindMount(tmp_path / "thesis", "/work", readonly=False),
            BindMount(tmp_path / "out, final", "/mnt/write/out, final", readonly=False),
            BindMount(tmp_path / "raw", "/mnt/read/raw", readonly=True),
        ),
        codex_etc=folder / "codex",
        launch_note=folder / "launch.md",
        gateway_conf=folder / "gateway.conf",
        env_file=folder / "agent.env",
    )


def labels_of(command: list[str]) -> dict[str, str]:
    return dict(command[i + 1].split("=", 1) for i, a in enumerate(command) if a == "--label")


def mounts_of(command: list[str]) -> list[str]:
    return [command[i + 1] for i, a in enumerate(command) if a == "--mount"]


EXPECTED_LABELS = {
    "umcodex.app": "um-codex",
    "umcodex.instance": "0123456789abcdef",
    "umcodex.launch": "1a2b3c4d",
}


@pytest.mark.parametrize("internet", [False, True])
def test_everything_created_is_labelled(tmp_path, internet):
    s = spec(tmp_path, internet=internet)
    created = [*s.network_commands(), s.gateway_commands()[0], s.agent_commands()[0]]
    for command in created:
        assert labels_of(command) == EXPECTED_LABELS, command
    assert labels_of(s.volume_command())["umcodex.setup"] == "thesis-a1b2c3"


def test_internet_off_internal_network_only_and_no_dns(tmp_path):
    s = spec(tmp_path, internet=False)
    create, gateway_bridge = s.network_commands()
    assert create[:3] == ["network", "create", "--internal"] and create[-1] == "umcodex-1a2b3c4d-int"
    assert "--internal" not in gateway_bridge and gateway_bridge[-1] == "umcodex-1a2b3c4d-gw"
    [run] = s.agent_commands()
    assert run[run.index("--network") + 1] == "umcodex-1a2b3c4d-int"
    assert run[run.index("--dns") + 1] == NO_DNS
    assert "umcodex-1a2b3c4d-net" not in " ".join(run)


def test_internet_on_adds_a_bridge_network_of_its_own(tmp_path):
    s = spec(tmp_path, internet=True)
    internal, _, bridge = s.network_commands()
    assert "--internal" in internal
    assert "--internal" not in bridge and bridge[-1] == "umcodex-1a2b3c4d-net"
    run, connect = s.agent_commands()
    assert "--dns" not in run
    assert run[run.index("--network") + 1] == "umcodex-1a2b3c4d-int"
    assert connect == ["network", "connect", "umcodex-1a2b3c4d-net", "umcodex-1a2b3c4d-agent"]


def test_the_gateway_joins_the_internal_network_as_gateway(tmp_path):
    run, connect = spec(tmp_path, internet=False).gateway_commands()
    assert connect == [
        "network",
        "connect",
        "--alias",
        "gateway",
        "umcodex-1a2b3c4d-int",
        "umcodex-1a2b3c4d-gateway",
    ]
    assert "host.docker.internal:host-gateway" in run
    assert run[-1].startswith("nginx@sha256:")
    assert "type=bind,source=" in " ".join(mounts_of(run)) and mounts_of(run)[0].endswith(",readonly")


def test_agent_mounts(tmp_path):
    s = spec(tmp_path, internet=False)
    [run] = s.agent_commands()
    mounts = mounts_of(run)
    assert f"type=bind,source={tmp_path / 'thesis'},target=/work" in mounts
    assert f'type=bind,"source={tmp_path / "out, final"}","target=/mnt/write/out, final"' in mounts
    assert f"type=bind,source={tmp_path / 'raw'},target=/mnt/read/raw,readonly" in mounts
    assert "type=volume,source=umcodex-home-thesis-a1b2c3,target=/codex-home" in mounts
    # Codex's enforced settings: a read-only folder at /etc/codex. Nothing is
    # mounted over the person's own config.toml, where Codex saves preferences.
    assert f"type=bind,source={s.codex_etc},target=/etc/codex,readonly" in mounts
    assert not any("config.toml" in m for m in mounts)
    assert f"type=bind,source={s.launch_note},target=/etc/um-codex/launch.md,readonly" in mounts
    # Read-write folders are never marked read-only, and nothing else is mounted.
    assert not any(m.endswith("readonly") for m in mounts if "/work" in m or "/mnt/write" in m)
    assert len(mounts) == 6
    assert run[-1] == "um-codex-agent:dev"


@pytest.mark.parametrize("internet", [False, True])
def test_the_agent_gets_no_docker_socket_no_privileges_and_no_key(tmp_path, internet):
    [run, *_] = spec(tmp_path, internet=internet).agent_commands()
    text = " ".join(run)
    assert "docker.sock" not in text
    assert "--privileged" not in run and "--cap-add" not in run and "--pid" not in run
    assert "--network=host" not in text and run[run.index("--network") + 1] != "host"
    assert "-e" not in run and "--env" not in run  # the token is only in the env file
    assert run[run.index("--env-file") + 1].endswith("agent.env")
    assert run[run.index("--add-host") + 1] == f"host.docker.internal:{NO_DNS}"


def test_a_privileged_or_socket_mount_is_refused(tmp_path):
    s = spec(tmp_path, internet=False)
    bad = LaunchSpec(**{**s.__dict__, "folders": (BindMount(Path("/var/run/docker.sock"), "/work", False),)})
    with pytest.raises(DockerError):
        bad.agent_commands()


def test_removal(tmp_path):
    assert spec(tmp_path, internet=True).remove_commands() == [
        ["rm", "-f", "umcodex-1a2b3c4d-agent", "umcodex-1a2b3c4d-gateway"],
        ["network", "rm", "umcodex-1a2b3c4d-int", "umcodex-1a2b3c4d-gw", "umcodex-1a2b3c4d-net"],
    ]


def test_exec_command():
    assert exec_command("a", tty=True, term="xterm-256color") == [
        "docker", "exec", "-it", "-w", "/work", "-e", "TERM=xterm-256color", "a", "codex",
    ]  # fmt: skip
    assert exec_command("a", tty=False, term="dumb", args=["exec", "hi"])[2] == "-i"
    assert exec_command("a", tty=False, term="dumb", args=["exec", "hi"])[-3:] == ["codex", "exec", "hi"]


def test_gateway_conf_has_the_port_and_no_mcp():
    conf = render_gateway_conf(54321)
    assert "proxy_pass http://host.docker.internal:54321/relay/v1/;" in conf
    assert "Host 127.0.0.1:54321" in conf
    assert "location /mcp" not in conf and "{port}" not in conf


# --- cleanup ------------------------------------------------------------------


class FakeDocker:
    """subprocess.run for `docker`, answering ps/network ls with listings in
    the shape `--format '{{.ID}}|{{.Label ...}}|{{.Label ...}}'` prints."""

    def __init__(self, containers: str, networks: str) -> None:
        self.listings = {"ps": containers, "network": networks}
        self.calls: list[list[str]] = []

    def __call__(self, command, **options):
        self.calls.append(command)
        args = command[1:]
        out = ""
        if args[:2] == ["ps", "-a"]:
            out = self.listings["ps"]
        elif args[:2] == ["network", "ls"]:
            out = self.listings["network"]
        return subprocess.CompletedProcess(command, 0, out, "")


def test_cleanup_removes_only_leftovers_of_dead_launches_found_by_label():
    fake = FakeDocker(
        containers=(
            "3f9c2a1b7d4e|deadbeef|um-codex\n"
            "8e7d6c5b4a39|deadbeef|um-codex\n"
            "1234567890ab|a1a1a1a1|um-codex\n"  # a live launch
            "abcdefabcdef||um-codex\n"  # no launch label: not ours to judge
            "fedcbafedcba|deadbeef|\n"  # not UM-Codex's
        ),
        networks="0a1b2c3d4e5f|deadbeef|um-codex\n9f8e7d6c5b4a|a1a1a1a1|um-codex\n",
    )
    removed = remove_leftovers(Docker(fake), "0123456789abcdef", live=lambda launch: launch == "a1a1a1a1")
    assert removed == 3
    listings = [c for c in fake.calls if c[1] in ("ps", "network") and "--filter" in c]
    assert all(c[c.index("--filter") + 1] == "label=umcodex.instance=0123456789abcdef" for c in listings)
    assert ["docker", "rm", "-f", "3f9c2a1b7d4e", "8e7d6c5b4a39"] in fake.calls
    assert ["docker", "network", "rm", "0a1b2c3d4e5f"] in fake.calls
    assert not any("volume" in c for c in fake.calls)


def test_cleanup_with_nothing_left_removes_nothing():
    fake = FakeDocker("", "")
    assert remove_leftovers(Docker(fake), "0123456789abcdef", live=lambda _: False) == 0
    assert all(c[1] in ("ps", "network") and c[2] in ("-a", "ls") for c in fake.calls)


def test_docker_errors_never_include_the_arguments():
    def failing(command, **options):
        return subprocess.CompletedProcess(command, 1, "", "Error response from daemon: boom")

    with pytest.raises(DockerError) as raised:
        Docker(failing)("run", "--env-file", "/secret/place", "image")
    assert "/secret/place" not in str(raised.value) and "boom" in str(raised.value)


def test_the_gateway_has_a_bridge_of_its_own(tmp_path):
    run, _ = spec(tmp_path, internet=False).gateway_commands()
    assert run[run.index("--network") + 1] == "umcodex-1a2b3c4d-gw"


def test_the_agent_has_a_pids_limit_and_removes_itself(tmp_path):
    [run] = spec(tmp_path, internet=False).agent_commands()
    assert run[run.index("--pids-limit") + 1] == "4096"
    assert "--rm" in run and "--memory" not in run


def test_the_watchdog_wraps_the_images_own_command(tmp_path):
    image_cmd = ("sh", "-c", 'cp /etc/um-codex/AGENTS.md "$CODEX_HOME/AGENTS.md" && exec sleep infinity')
    s = LaunchSpec(**{**spec(tmp_path, internet=False).__dict__, "image_cmd": image_cmd})
    [run] = s.agent_commands()
    image_at = run.index("um-codex-agent:dev")
    assert run[image_at + 1 : image_at + 3] == ["sh", "-c"]
    assert run[image_at + 3] == WATCHDOG and run[image_at + 4] == "sh"
    assert tuple(run[image_at + 5 :]) == image_cmd
    assert "http://gateway/v1/_umcodex/alive" in WATCHDOG and "$UMCODEX_TOKEN" in WATCHDOG
    # Without a known command, the image runs as it is.
    [plain] = spec(tmp_path, internet=False).agent_commands()
    assert plain[-1] == "um-codex-agent:dev"


@pytest.mark.parametrize(
    "extra",
    [
        ["--cap-add=SYS_ADMIN"],
        ["--cap-add", "NET_ADMIN"],
        ["--cap-add=all"],
        ["--privileged=true"],
        ["--network=host"],
        ["--pid", "host"],
        ["-v", "/var/run/docker.sock:/var/run/docker.sock"],
    ],
)
def test_the_guard_refuses_host_access_in_any_spelling(extra):
    with pytest.raises(DockerError):
        _guarded(["run", "-d", *extra, "image"])


def test_the_watchdog_ends_when_the_relay_is_gone(tmp_path):
    """The loop itself, run by a local shell with a curl that always fails."""
    import shutil

    if shutil.which("sh") is None:
        pytest.skip("no sh")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "curl").write_text("#!/bin/sh\nexit 7\n")
    (fake_bin / "curl").chmod(0o755)
    (fake_bin / "sleep").write_text("#!/bin/sh\nexit 0\n")  # no waiting in a test
    (fake_bin / "sleep").chmod(0o755)
    done = subprocess.run(
        ["sh", "-c", WATCHDOG, "sh", "true"],
        env={"PATH": f"{fake_bin}:/usr/bin:/bin", "UMCODEX_TOKEN": "umc_x"},
        timeout=20,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0
    assert done.stdout.strip() == "watchdog: launch gone, ending"  # in `docker logs`, for the launch's log


def test_the_bundled_model_list_comes_from_a_throwaway_container(tmp_path):
    run = spec(tmp_path, internet=True).bundled_models_command()
    assert run[:2] == ["run", "--rm"]
    assert labels_of(run) == EXPECTED_LABELS
    assert run[run.index("--network") + 1] == "none"
    assert "--mount" not in run and "--env-file" not in run
    assert run[-5:] == ["um-codex-agent:dev", "codex", "debug", "models", "--bundled"]
