# Adapted from DataLab's backend/src/datalab/sessions/containers.py at 6b6fdca.
"""Docker for one launch: networks, the gateway, the agent, and cleanup.

- The agent joins the launch's internal network, which has no route out. Its
  way to the model is the gateway, a stock nginx that forwards to the relay
  in `um-codex` on the host.
- Internet off: the agent is on the internal network only, and can resolve
  only names Docker knows (DataLab's no-DNS setting).
- Internet on: it also joins a plain bridge network of its own, with the
  whole internet.

Everything UM-Codex creates carries its labels, and cleanup finds things by
label only, so nothing else in Docker is ever touched. The commands are built
by plain functions (tested without Docker) and run by `Docker`.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from umcodex.codex_config import CODEX_ETC

APP_LABEL = "umcodex.app"
APP = "um-codex"
LAUNCH_LABEL = "umcodex.launch"
# Which UM-Codex data folder owns it, so tests (or a second data folder)
# never remove another's launches.
INSTANCE_LABEL = "umcodex.instance"
# The data folder itself (resolved), beside its instance: the instance is a
# hash, so this lets a later version tell the objects of a data folder that's
# gone from those of one still in use.
DATA_LABEL = "umcodex.data"
SETUP_LABEL = "umcodex.setup"
# An unroutable address (TEST-NET-1): with the internet off, containers can
# resolve only names Docker knows (the gateway), and nothing else.
NO_DNS = "192.0.2.1"
# Docker Desktop names the host `host.docker.internal`. The agent gets it
# pointed at nowhere, so with the internet on that easy way to services on
# the host's localhost is closed (the gateway has the real one).
HOST_ALIAS = "host.docker.internal"
CODEX_HOME = "/codex-home"
LAUNCH_NOTE = "/etc/um-codex/launch.md"
# The agent's main process when the image's command is known: the image's
# command runs in the background, and this loop asks the relay (through the
# gateway, with the launch token) every 15 s whether the launch is still on.
# After 4 failed asks in a row (about a minute: the relay or gateway is gone,
# because `um-codex` was killed or its terminal closed) the loop ends, so the
# container stops and, started with --rm, removes itself. The leftovers'
# networks and gateway go at the next launch (by label). No curl: never stop.
WATCHDOG = (
    '"$@" & '
    "command -v curl >/dev/null 2>&1 || { wait; exit 0; }; "
    "fails=0; "
    "while sleep 15; do "
    'if curl -fsS -m 5 -o /dev/null -H "Authorization: Bearer $UMCODEX_TOKEN" '
    "http://gateway/v1/_umcodex/alive; then fails=0; else fails=$((fails+1)); fi; "
    '[ "$fails" -ge 4 ] && { echo "watchdog: launch gone, ending"; exit 0; }; '
    "done"
)


class DockerError(RuntimeError):
    pass


def instance_of(data_dir: Path) -> str:
    """A short, stable name for the UM-Codex data folder that owns a launch."""
    return hashlib.sha256(str(Path(data_dir).resolve()).encode()).hexdigest()[:16]


def images() -> dict[str, str]:
    """The pinned images (images.json)."""
    text = resources.files(__package__).joinpath("images.json").read_text(encoding="utf-8")
    return {k: v for k, v in json.loads(text).items() if not k.startswith("_")}


def agent_image() -> str:
    """The agent image: images.json's, or `UMCODEX_AGENT_IMAGE` (development only)."""
    return os.environ.get("UMCODEX_AGENT_IMAGE") or images()["agent"]


def volume_name(setup_id: str) -> str:
    return f"umcodex-home-{setup_id}"


@dataclass(frozen=True)
class BindMount:
    """A host file or folder in the agent's container."""

    source: Path
    target: str
    readonly: bool

    def args(self) -> list[str]:
        # --mount (not -v) so a missing source is an error, never an empty
        # folder, and colons in Windows paths aren't misread. Values are
        # CSV-quoted, so commas and quotes in names are safe.
        fields = ["type=bind", f"source={self.source}", f"target={self.target}"]
        if self.readonly:
            fields.append("readonly")
        return ["--mount", ",".join(_csv_field(f) for f in fields)]


def _csv_field(value: str) -> str:
    if any(c in value for c in ',"\n\r'):
        return '"' + value.replace('"', '""') + '"'
    return value


@dataclass(frozen=True)
class LaunchSpec:
    launch_id: str
    instance: str
    setup_id: str
    agent_image: str
    gateway_image: str
    internet: bool
    folders: tuple[BindMount, ...]  # /work, /mnt/write/*, /mnt/read/*
    codex_etc: Path  # Codex's enforced settings (codex_config.py), mounted read-only at /etc/codex
    launch_note: Path  # launch.md, mounted read-only
    gateway_conf: Path
    env_file: Path
    # The agent image's own command (`Config.Cmd`), run under the watchdog
    # (see WATCHDOG). Empty: the image's command runs as it is, unwatched.
    image_cmd: tuple[str, ...] = ()
    # More labels on the containers and networks: a launch opened in the
    # Codex app has `umcodex.ssh=<setup>`, which `um-codex ssh-proxy` finds
    # its agent by (codex_app.py).
    extra_labels: tuple[tuple[str, str], ...] = ()
    # The data folder that owns the launch (DATA_LABEL); empty: no label.
    data_folder: str = ""

    @property
    def prefix(self) -> str:
        return f"umcodex-{self.launch_id}"

    @property
    def internal_network(self) -> str:
        return f"{self.prefix}-int"

    @property
    def internet_network(self) -> str:
        return f"{self.prefix}-net"

    @property
    def gateway_network(self) -> str:
        return f"{self.prefix}-gw"

    @property
    def gateway(self) -> str:
        return f"{self.prefix}-gateway"

    @property
    def agent(self) -> str:
        return f"{self.prefix}-agent"

    @property
    def models_container(self) -> str:
        """The throwaway container that prints Codex's model list."""
        return f"{self.agent}-models"

    @property
    def volume(self) -> str:
        return volume_name(self.setup_id)

    def labels(self) -> list[str]:
        return [
            "--label", f"{APP_LABEL}={APP}",
            "--label", f"{INSTANCE_LABEL}={self.instance}",
            *self._data_label(),
            "--label", f"{LAUNCH_LABEL}={self.launch_id}",
            *(arg for name, value in self.extra_labels for arg in ("--label", f"{name}={value}")),
        ]  # fmt: skip

    def _data_label(self) -> list[str]:
        return ["--label", f"{DATA_LABEL}={self.data_folder}"] if self.data_folder else []

    def network_commands(self) -> list[list[str]]:
        commands = [
            ["network", "create", "--internal", *self.labels(), self.internal_network],
            # The gateway's own way to the host's relay: a bridge of its own,
            # not Docker's shared default one.
            ["network", "create", *self.labels(), self.gateway_network],
        ]
        if self.internet:
            commands.append(["network", "create", *self.labels(), self.internet_network])
        return commands

    def volume_command(self) -> list[str]:
        return [
            "volume", "create",
            "--label", f"{APP_LABEL}={APP}",
            "--label", f"{INSTANCE_LABEL}={self.instance}",
            *self._data_label(),
            "--label", f"{SETUP_LABEL}={self.setup_id}",
            self.volume,
        ]  # fmt: skip

    def gateway_commands(self) -> list[list[str]]:
        run = [
            "run", "-d", "--name", self.gateway,
            *self.labels(),
            "--network", self.gateway_network,
            "--add-host", f"{HOST_ALIAS}:host-gateway",
            "--read-only", "--tmpfs", "/var/cache/nginx", "--tmpfs", "/var/run",
            "--cap-drop", "ALL", "--cap-add", "CHOWN", "--cap-add", "SETUID",
            "--cap-add", "SETGID", "--cap-add", "NET_BIND_SERVICE",
            "--security-opt", "no-new-privileges",
            "--memory", "128m", "--pids-limit", "128",
            *BindMount(self.gateway_conf, "/etc/nginx/conf.d/default.conf", readonly=True).args(),
            self.gateway_image,
        ]  # fmt: skip
        connect = ["network", "connect", "--alias", "gateway", self.internal_network, self.gateway]
        return [_guarded(run), connect]

    def agent_commands(self) -> list[list[str]]:
        """`docker run` for the agent, then (internet on) joining the internet network.

        No --privileged, no Docker socket, no added capabilities. Docker's
        default capabilities stay, so `sudo` works inside the container.
        """
        mounts: list[str] = []
        for mount in self.folders:
            mounts += mount.args()
        mounts += [
            "--mount", f"type=volume,source={self.volume},target={CODEX_HOME}",
            # Not over $CODEX_HOME/config.toml: that's the person's own,
            # where Codex saves its preferences (codex_config.py).
            *BindMount(self.codex_etc, CODEX_ETC, readonly=True).args(),
            *BindMount(self.launch_note, LAUNCH_NOTE, readonly=True).args(),
        ]  # fmt: skip
        dns = [] if self.internet else ["--dns", NO_DNS]
        run = [
            "run", "-d", "--rm", "--name", self.agent,
            *self.labels(),
            "--network", self.internal_network,
            *dns,
            "--add-host", f"{HOST_ALIAS}:{NO_DNS}",
            "--hostname", "um-codex",
            "--init",
            "--pids-limit", "4096",
            # The token goes in a private env file, not on a command line
            # where other programs on this computer could see it.
            "--env-file", str(self.env_file),
            *mounts,
            self.agent_image,
            *(["sh", "-c", WATCHDOG, "sh", *self.image_cmd] if self.image_cmd else []),
        ]  # fmt: skip
        commands = [_guarded(run)]
        if self.internet:
            commands.append(["network", "connect", self.internet_network, self.agent])
        return commands

    def bundled_models_command(self) -> list[str]:
        """`docker run` printing the agent image's Codex model list (the
        catalog's source, codex_config.model_catalog). No network, removed
        when done."""
        return _guarded([
            "run", "--rm", "--name", self.models_container, *self.labels(), "--network", "none",
            self.agent_image, "codex", "debug", "models", "--bundled",
        ])  # fmt: skip

    def remove_commands(self) -> list[list[str]]:
        networks = [self.internal_network, self.gateway_network]
        networks += [self.internet_network] if self.internet else []
        return [["rm", "-f", self.agent, self.gateway, self.models_container], ["network", "rm", *networks]]


def exec_command(agent: str, *, tty: bool, term: str, args: Sequence[str] = ()) -> list[str]:
    """`docker exec` for Codex's terminal interface, in the person's terminal."""
    flags = ["-it"] if tty else ["-i"]
    return ["docker", "exec", *flags, "-w", "/work", "-e", f"TERM={term}", agent, "codex", *args]


def _guarded(args: list[str]) -> list[str]:
    """A last check on a `docker run` command line."""
    allowed = {"CHOWN", "SETUID", "SETGID", "NET_BIND_SERVICE"}
    added: set[str] = set()
    for index, arg in enumerate(args):
        lowered = arg.lower()
        if lowered.startswith("--privileged") or "docker.sock" in lowered:
            raise DockerError("UM-Codex refused to start a container with access to Docker or the host.")
        if lowered in ("--network=host", "--pid=host", "--ipc=host", "--userns=host", "--uts=host"):
            raise DockerError("UM-Codex refused to start a container with access to Docker or the host.")
        if arg in ("--network", "--pid", "--ipc", "--userns", "--uts") and args[index + 1 : index + 2] == [
            "host"
        ]:
            raise DockerError("UM-Codex refused to start a container with access to Docker or the host.")
        if arg == "--cap-add" and index + 1 < len(args):
            added.add(args[index + 1].upper())
        elif lowered.startswith("--cap-add="):
            added.add(arg.split("=", 1)[1].upper())
    if added - allowed:
        raise DockerError("UM-Codex refused to add a capability to a container.")
    return args


def render_gateway_conf(relay_port: int) -> str:
    template = resources.files(__package__).joinpath("gateway.conf").read_text(encoding="utf-8")
    return template.replace("{port}", str(relay_port))


Runner = Callable[..., subprocess.CompletedProcess]


class Docker:
    """Runs `docker` commands. Arguments are never put in an error or a log."""

    def __init__(self, run: Runner = subprocess.run) -> None:
        self._run = run

    def status(self, *args: str, timeout: float = 120, input: str | None = None) -> tuple[int, str, str]:
        """`input`: text for the command's stdin (none: no stdin is passed)."""
        extra = {} if input is None else {"input": input}
        try:
            done = self._run(
                ["docker", *args], capture_output=True, text=True, timeout=timeout,
                encoding="utf-8", errors="replace", **extra,
            )  # fmt: skip
        except FileNotFoundError as error:
            raise DockerError("Docker's `docker` command isn't installed or isn't on PATH.") from error
        except subprocess.TimeoutExpired as error:
            raise DockerError(f"docker {args[0]} took too long.") from error
        return done.returncode, done.stdout or "", done.stderr or ""

    def __call__(self, *args: str, check: bool = True, timeout: float = 120) -> str:
        code, out, err = self.status(*args, timeout=timeout)
        if check and code != 0:
            raise DockerError(f"docker {args[0]} failed: {err.strip()[:500]}")
        return out

    def exists(self, kind: str, name: str) -> bool:
        code, _, _ = self.status(kind, "inspect", name)
        return code == 0

    def running(self, name: str) -> bool:
        code, out, _ = self.status("inspect", "-f", "{{.State.Running}}", name)
        return code == 0 and out.strip() == "true"

    def wait_running(self, name: str, seconds: float = 30, sleep: Callable = time.sleep) -> bool:
        for _ in range(int(seconds * 4)):
            if self.running(name):
                return True
            sleep(0.25)
        return False


def owned_leftovers(
    docker: Docker, instance: str, live: Callable[[str], bool]
) -> tuple[list[str], list[str]]:
    """Containers and networks this UM-Codex data folder made for launches that
    are no longer running (`live` says whether a launch is). By label only."""
    owned = f"label={INSTANCE_LABEL}={instance}"
    fields = f'{{{{.ID}}}}|{{{{.Label "{LAUNCH_LABEL}"}}}}|{{{{.Label "{APP_LABEL}"}}}}'
    found: list[list[str]] = []
    for kind in (["ps", "-a"], ["network", "ls"]):
        listing = docker(*kind, "--filter", owned, "--format", fields, check=False)
        ids = []
        for line in listing.splitlines():
            object_id, launch, app = ([*line.split("|"), "", ""])[:3]
            if object_id.strip() and app.strip() == APP and launch.strip() and not live(launch.strip()):
                ids.append(object_id.strip())
        found.append(ids)
    return found[0], found[1]


def remove_leftovers(docker: Docker, instance: str, live: Callable[[str], bool]) -> int:
    """Remove what a killed `um-codex` left behind. Returns how many things went."""
    containers, networks = owned_leftovers(docker, instance, live)
    if containers:
        docker("rm", "-f", *containers, check=False)
    if networks:
        docker("network", "rm", *networks, check=False)
    return len(containers) + len(networks)


def say_now(line: str) -> None:
    """Print a line and flush it at once, so it comes before what a child
    process (`docker pull`) writes after it, even when stdout is a file or a
    pipe (the launcher's Update, Windows)."""
    print(line, flush=True)


# A failed `docker pull` is tried again after these waits (seconds): a
# registry can answer "not found" or time out for a moment.
PULL_RETRY_WAITS = (3.0, 10.0)


def pull_images(
    say: Callable[[str], None] = say_now,
    docker: Docker | None = None,
    run: Runner = subprocess.run,
    *,
    sleep: Callable[[float], None] = time.sleep,
    quiet: bool | None = None,
) -> bool:
    """`um-codex pull` (the installers' and `um-codex update`'s too): every
    image in images.json (the agent, the gateway).

    An image pinned by digest that's already here isn't pulled again (it
    can't have changed). A failed pull is tried again twice, and if the
    image turns out to be here after all, that's fine. In a terminal,
    Docker's own progress is shown; otherwise (`quiet`, by default when
    stdout isn't a terminal) one line per image. A local `:dev` image that's
    already here is skipped; one that isn't can only be built, not pulled.
    False on any failure, saying which kind: Docker not running, the
    registry or the network, or the disk, with Docker's own words."""
    docker = docker or Docker(run)
    if quiet is None:
        quiet = not _is_terminal()
    try:
        code, out, err = docker.status("info", "--format", "{{.ServerVersion}}", timeout=30)
    except DockerError as error:
        say(str(error))
        return False
    if code != 0:
        said = _docker_said(err or out)
        say(
            "Docker isn't running. Open Docker Desktop, wait until it says it's running, then try again."
            + (f" (Docker said: {said})" if said else "")
        )
        return False
    ok = True
    for role, image in images().items():
        image = agent_image() if role == "agent" else image
        if image.endswith(":dev") and "@" not in image:
            if docker.exists("image", image):
                say(f"The {role} image {image} is a local development image and is already here: not pulled.")
            else:
                say(
                    f"The {role} image {image} is a local development image, so it can't be pulled: "
                    "build it (see README)."
                )
                ok = False
            continue
        ok = pull_image(role, image, say=say, docker=docker, run=run, sleep=sleep, quiet=quiet) and ok
    return ok


def pull_image(
    role: str,
    image: str,
    *,
    say: Callable[[str], None],
    docker: Docker,
    run: Runner,
    sleep: Callable[[float], None] = time.sleep,
    quiet: bool = False,
) -> bool:
    """Pull one image (see pull_images). True when it's here afterwards."""
    pinned = "@sha256:" in image
    if pinned and _image_here(docker, image):
        say(f"The {role} image is already here ({image}).")
        return True
    say(f"Downloading the {role} image ({image})...")
    said = ""
    for attempt in range(len(PULL_RETRY_WAITS) + 1):
        if attempt:
            wait = PULL_RETRY_WAITS[attempt - 1]
            say(f"  That didn't work (Docker said: {said}). Trying again in {wait:.0f} seconds...")
            sleep(wait)
        # Ours first, then Docker's: its progress goes straight to the terminal.
        sys.stdout.flush()
        sys.stderr.flush()
        command = ["docker", "pull", *(["--quiet"] if quiet else []), image]
        timed_out = False
        try:
            done = run(
                command,
                stdout=subprocess.DEVNULL if quiet else None,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
                timeout=3600,
            )
        except FileNotFoundError:
            say("Docker's `docker` command isn't installed or isn't on PATH.")
            return False
        except subprocess.TimeoutExpired:
            said, timed_out = "it took more than an hour", True
        except OSError as error:
            said = f"{type(error).__name__}: {error}"
        else:
            if done.returncode == 0:
                if quiet:
                    say(f"  Downloaded the {role} image.")
                return True
            said = _docker_said(done.stderr) or f"docker pull ended with code {done.returncode}"
        if pinned and _image_here(docker, image):
            say(f"  The {role} image is here (that exact version), so the error doesn't matter.")
            return True
        if timed_out or not _docker_running(docker) or "no space left" in said.lower():
            break  # trying again won't help (an hour gone, Docker stopped, the disk full)
    say(_pull_failed(role, said, running=_docker_running(docker)))
    return False


def _pull_failed(role: str, said: str, *, running: bool) -> str:
    """Why a pull failed, in plain words, with Docker's own line."""
    quoted = f" Docker said: {said}" if said else ""
    if not running:
        return (
            f"Couldn't download the {role} image: Docker stopped running.{quoted} Open Docker Desktop, "
            "wait until it says it's running, then try again."
        )
    if "no space left" in said.lower():
        return (
            f"Couldn't download the {role} image: Docker is out of disk space.{quoted} Free some space "
            "(Docker Desktop's settings show how much it uses), then try again."
        )
    return (
        f"Couldn't download the {role} image from its registry (Docker is running; this is the "
        f"network or the registry).{quoted} Check this computer is online, then try again in a few minutes."
    )


def _image_here(docker: Docker, image: str) -> bool:
    try:
        return docker.exists("image", image)
    except DockerError:
        return False


def _docker_running(docker: Docker) -> bool:
    try:
        code, _, _ = docker.status("info", "--format", "{{.ServerVersion}}", timeout=30)
    except DockerError:
        return False
    return code == 0


def _docker_said(text: str | None) -> str:
    """Docker's error, on one line: its last 3 non-empty lines, shortened."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    said = " / ".join(lines[-3:])
    return said if len(said) <= 500 else said[:497] + "..."


def _is_terminal() -> bool:
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False
