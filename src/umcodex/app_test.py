"""TEST ONLY (development, not released): the Codex desktop app working inside
a UM-Codex container, through the app's SSH connections.

Design: docs/spikes/2026-10-01-codex-desktop-app.md (the SSH path, with a
`docker exec` ProxyCommand and no listener).

`um-codex app-test start`:
1. launches a container for the fixed test setup `app-test` the way a launch
   does (relay, gateway, token; working folder ~/Documents/UM-Codex-app-test;
   internet on), from the image `um-codex-agent:app-test`
   (images/agent-app-test), with Codex's provider reading the launch token
   from a file (`umcodex-token`), since ssh sessions don't get `docker run -e`;
2. inside it: a host key, the setup's public key for `agent`, the token file;
3. on this computer: the key pair and `~/.ssh/um-codex/config` (one
   `Host umcodex-test`, ProxyCommand `um-codex ssh-proxy app-test`), and the
   one line `Include ~/.ssh/um-codex/config` at the top of `~/.ssh/config`
   (backed up first to ~/.ssh/config.um-codex-backup);
4. a second, separate copy of the Codex app with UM-Codex's own CODEX_HOME
   and Electron profile (as the app's own "Codex Demo" launcher does), opened
   on the link that adds the host, connects and opens /work;
5. waits (the relay runs) until Ctrl-C, then removes the containers.

`um-codex app-test stop` removes leftovers (by label) and the Host file and
key; the Include line stays until the person decides. `--purge` also removes
the test setup's Codex history volume and the app copy's data folder.

The Toolkit key stays in the relay, as in every launch. The app copy's own
(local) side uses the same relay on 127.0.0.1 with the launch token, read by
`cat` from a 0600 file in UM-Codex's data folder.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from umcodex import launch
from umcodex.containers import APP, APP_LABEL, INSTANCE_LABEL, Docker, DockerError, LaunchSpec, instance_of
from umcodex.folders import plan
from umcodex.paths import data_dir
from umcodex.setups import Setup
from umcodex.toolkit import DEFAULT_MODEL

Say = Callable[[str], None]

SETUP_ID = "app-test"
ALIAS = "umcodex-test"
IMAGE = "um-codex-agent:app-test"
SSH_LABEL = "umcodex.ssh"
TOKEN_FILE = "/run/um-codex/token"
TOKEN_COMMAND = "/usr/local/bin/umcodex-token"
SSHD = ("/usr/sbin/sshd", "-i", "-f", "/etc/um-codex/sshd_config")
INCLUDE_LINE = "Include ~/.ssh/um-codex/config"
APP_BUNDLE = Path("/Applications/ChatGPT.app")
APP_BUNDLE_ID = "com.openai.codex"


def deep_link(alias: str = ALIAS) -> str:
    return f"codex://settings/connections/ssh/add?name={alias}&projectPath=/work&enabled=true"


# --- Where things go ----------------------------------------------------------


def ssh_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".ssh"


def own_ssh_dir(home: Path | None = None) -> Path:
    return ssh_dir(home) / "um-codex"


def key_path(home: Path | None = None) -> Path:
    return own_ssh_dir(home) / f"{SETUP_ID}_ed25519"


def app_dir(data: Path | None = None) -> Path:
    return (data or data_dir()) / "codex-app"


def working_folder(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Documents" / "UM-Codex-app-test"


# --- ~/.ssh -----------------------------------------------------------------


def host_block(*, proxy: list[str], home: Path | None = None) -> str:
    """UM-Codex's own ssh config file: one Host for the test setup."""
    quoted = " ".join(f'"{part}"' if " " in part else part for part in proxy)
    key = "~/.ssh/um-codex/" + key_path(home).name
    return "\n".join(
        [
            "# Written by `um-codex app-test start` (a test); removed by `um-codex app-test stop`.",
            f"Host {ALIAS}",
            # Never used: the ProxyCommand reaches the container through Docker.
            f"  HostName {ALIAS}.invalid",
            "  User agent",
            f"  IdentityFile {key}",
            "  IdentitiesOnly yes",
            "  IdentityAgent none",
            "  ForwardAgent no",
            "  ForwardX11 no",
            # The transport is `docker exec` on this computer, and each
            # container makes a new host key.
            "  StrictHostKeyChecking no",
            "  UserKnownHostsFile /dev/null",
            "  LogLevel ERROR",
            f"  ProxyCommand {quoted}",
            "",
        ]
    )


def _private_write(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
        file.write(text)
    os.chmod(path, 0o600)


def add_include(home: Path | None = None) -> str:
    """The one line at the very top of ~/.ssh/config (the app follows only
    top-level Includes). Backs the file up first. Returns what was done."""
    config = ssh_dir(home) / "config"
    if not config.exists():
        ssh_dir(home).mkdir(mode=0o700, exist_ok=True)
        _private_write(config, INCLUDE_LINE + "\n")
        return "created"
    text = config.read_text(encoding="utf-8")
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first == INCLUDE_LINE:
        return "already there"
    backup = ssh_dir(home) / "config.um-codex-backup"
    if not backup.exists():
        shutil.copy2(config, backup)
    # In place, so the file keeps its own permissions.
    with config.open("r+", encoding="utf-8", newline="") as file:
        file.seek(0)
        file.write(INCLUDE_LINE + "\n" + text)
        file.truncate()
    return "added"


def write_ssh_files(proxy: list[str], home: Path | None = None) -> Path:
    """The key pair (kept between starts) and the Host file. Returns the public key's path."""
    folder = own_ssh_dir(home)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    key = key_path(home)
    if not key.exists():
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", f"um-codex {SETUP_ID}", "-f", str(key)],
            check=True,
        )
    os.chmod(key, 0o600)
    _private_write(folder / "config", host_block(proxy=proxy, home=home))
    return key.with_name(key.name + ".pub")


def remove_ssh_files(home: Path | None = None) -> list[Path]:
    removed = []
    for path in (
        own_ssh_dir(home) / "config",
        key_path(home),
        key_path(home).with_name(key_path(home).name + ".pub"),
    ):
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed


# --- The proxy ----------------------------------------------------------------


def find_agent(docker: Docker, setup_id: str, instance: str) -> str | None:
    """The running agent container of the setup's test launch, by label."""
    out = docker(
        "ps",
        "--filter", f"label={SSH_LABEL}={setup_id}",
        "--filter", f"label={INSTANCE_LABEL}={instance}",
        "--filter", f"label={APP_LABEL}={APP}",
        "--filter", "status=running",
        "--format", "{{.Names}}",
        check=False,
    )  # fmt: skip
    agents = [name for name in out.split() if name.endswith("-agent")]
    return agents[0] if len(agents) == 1 else None


def ssh_proxy(setup_id: str, docker_command: str = "docker") -> int:
    """`um-codex ssh-proxy <setup>`: ssh's ProxyCommand. Replaces itself with
    `docker exec -i -u root <agent> sshd -i`, so ssh talks to an sshd that
    runs for this one connection. Nothing but ssh's own bytes on stdout."""
    docker = Docker(lambda command, **options: subprocess.run([docker_command, *command[1:]], **options))
    try:
        agent = find_agent(docker, setup_id, instance_of(data_dir()))
    except DockerError as error:
        print(f"um-codex ssh-proxy: {error}", file=sys.stderr)
        return 1
    if agent is None:
        print(
            f"um-codex ssh-proxy: no running UM-Codex launch for {setup_id!r}. "
            "Start it with `um-codex app-test start`.",
            file=sys.stderr,
        )
        return 1
    os.execv(docker_command, [docker_command, "exec", "-i", "-u", "root", agent, *SSHD])
    return 1  # not reached


# --- Inside the container -----------------------------------------------------

# Run as root in the agent once it's up. The token comes from the
# container's own environment (docker exec inherits it), never a command line.
PREPARE = (
    "set -e; "
    "key=/etc/ssh/ssh_host_ed25519_key; "
    "[ -f $key ] || ssh-keygen -q -t ed25519 -N '' -f $key; "
    "install -d -m 0750 -o root -g agent /run/um-codex; "
    f"(umask 027; printf '%s' \"$UMCODEX_TOKEN\" > {TOKEN_FILE}); "
    f"chgrp agent {TOKEN_FILE}; "
    "install -d -m 0700 -o agent -g agent /home/agent/.ssh; "
    "cat > /home/agent/.ssh/authorized_keys; "
    "chown agent:agent /home/agent/.ssh/authorized_keys; chmod 0600 /home/agent/.ssh/authorized_keys"
)


def prepare_container(docker_command: str, agent: str, public_key: Path) -> None:
    subprocess.run(
        [docker_command, "exec", "-i", "-u", "root", agent, "sh", "-c", PREPARE],
        input=public_key.read_bytes(),
        check=True,
        timeout=60,
    )


# --- The app copy ---------------------------------------------------------------


def local_config(relay_port: int, token_file: Path, model: str = DEFAULT_MODEL) -> str:
    """config.toml for the app copy's own CODEX_HOME: the Toolkit through the
    relay on this computer, with the launch token read from a private file, so
    the app needs no ChatGPT or OpenAI sign-in (spike, section 2)."""
    return "\n".join(
        [
            "# Written by `um-codex app-test start` (a test). Rewritten at each start.",
            f'model = "{model}"',
            'model_provider = "toolkit"',
            'forced_login_method = "api"',
            "check_for_update_on_startup = false",
            "",
            "[analytics]",
            "enabled = false",
            "",
            "[feedback]",
            "enabled = false",
            "",
            "[model_providers.toolkit]",
            'name = "U-M GPT Toolkit (through UM-Codex)"',
            f'base_url = "http://127.0.0.1:{relay_port}/relay/v1"',
            'wire_api = "responses"',
            "request_max_retries = 1",
            "stream_max_retries = 2",
            "stream_idle_timeout_ms = 300000",
            "",
            "[model_providers.toolkit.auth]",
            'command = "/bin/cat"',
            f"args = [{_toml_string(str(token_file))}]",
            "",
        ]
    )


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def open_app_command(folder: Path, link: str | None) -> list[str]:
    """A second, separate app copy, as the app's "Codex Demo" launcher starts
    one (`open -n --env CODEX_HOME=… --env CODEX_ELECTRON_USER_DATA_PATH=…
    <app> --args --user-data-dir=…`). The link goes in its arguments: the app
    reads codex:// links from its command line at start, while `open <link>`
    would go to whichever copy macOS picks (perhaps the person's own)."""
    home = folder / "codex-home"
    user_data = folder / "user-data"
    args = ["--args", f"--user-data-dir={user_data}"]
    if link:
        args.append(link)
    return [
        "/usr/bin/open", "-n",
        "--env", f"CODEX_HOME={home}",
        "--env", f"CODEX_ELECTRON_USER_DATA_PATH={user_data}",
        str(APP_BUNDLE),
        *args,
    ]  # fmt: skip


# --- start / stop -----------------------------------------------------------------


def test_setup(home: Path | None = None) -> Setup:
    return Setup(
        id=SETUP_ID,
        name="app test",
        working=str(working_folder(home)),
        internet=True,
        model=DEFAULT_MODEL,
        approvals="never",
    )


def _umcodex_command() -> str:
    """The absolute path of this `um-codex` (for the ProxyCommand)."""
    here = Path(sys.argv[0])
    found = here if here.is_absolute() else shutil.which(sys.argv[0])
    found = found or shutil.which("um-codex")
    if not found:
        raise RuntimeError("couldn't find the um-codex command's own path")
    return str(Path(found).resolve())


def start(*, open_app: bool = True, say: Say = print, image: str = IMAGE) -> int:
    docker_command = shutil.which("docker")
    if not docker_command:
        say("Docker's `docker` command isn't on PATH.")
        return 1
    docker = Docker()
    if not docker.exists("image", image):
        say(f"The test image {image} isn't here. Build it: docker build -t {image} images/agent-app-test")
        return 1
    if open_app and not APP_BUNDLE.is_dir():
        say(f"The Codex app isn't at {APP_BUNDLE}.")
        return 1
    folder = working_folder()
    folder.mkdir(parents=True, exist_ok=True)
    setup = test_setup()
    layout = plan(folder.resolve(), [], [])
    proxy = [_umcodex_command(), "ssh-proxy", SETUP_ID, "--docker", docker_command]

    def hold(spec: LaunchSpec, relay_port: int, token: str) -> int:
        # Ctrl-C ends the test launch, even if this process was started with
        # SIGINT ignored (as background jobs are).
        signal.signal(signal.SIGINT, signal.default_int_handler)
        say("Preparing ssh inside the container...")
        public_key = write_ssh_files(proxy)
        prepare_container(docker_command, spec.agent, public_key)
        say(f"Wrote {own_ssh_dir() / 'config'} (Host {ALIAS}).")
        say(f"~/.ssh/config: Include line {add_include()}.")
        app = app_dir()
        (app / "codex-home").mkdir(parents=True, exist_ok=True, mode=0o700)
        (app / "user-data").mkdir(parents=True, exist_ok=True, mode=0o700)
        token_file = app / "launch-token"
        _private_write(token_file, token)
        _private_write(app / "codex-home" / "config.toml", local_config(relay_port, token_file))
        try:
            if open_app:
                command = open_app_command(app, deep_link())
                say("Opening a second, separate copy of the Codex app on the test container...")
                done = subprocess.run(command, check=False, timeout=60)
                if done.returncode != 0:
                    say("The app copy didn't open (see above).")
            else:
                say("Not opening the app (--no-app).")
            say("")
            say(f"Ready: `ssh {ALIAS}` reaches the container. Codex app link: {deep_link()}")
            say("The relay runs while this does. Press Ctrl-C to end the test launch.")
            sys.stdout.flush()
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            signal.signal(signal.SIGINT, signal.SIG_IGN)  # let the cleanup finish
            say("")
            say("Ending the test launch...")
            return 0
        finally:
            token_file.unlink(missing_ok=True)

    return launch.run(
        setup,
        layout,
        say=say,
        docker=docker,
        image=image,
        labels=((SSH_LABEL, SETUP_ID),),
        token_command=TOKEN_COMMAND,
        hold=hold,
    )


def stop(*, purge: bool = False, say: Say = print) -> int:
    docker = Docker()
    instance = instance_of(data_dir())
    owned = [f"label={SSH_LABEL}={SETUP_ID}", f"label={INSTANCE_LABEL}={instance}"]
    filters = [arg for label in owned for arg in ("--filter", label)]
    containers = docker("ps", "-a", *filters, "--format", "{{.ID}}", check=False).split()
    if containers:
        docker("rm", "-f", *containers, check=False)
    networks = docker("network", "ls", *filters, "--format", "{{.ID}}", check=False).split()
    if networks:
        docker("network", "rm", *networks, check=False)
    say(f"Removed {len(containers)} containers and {len(networks)} networks.")
    for path in remove_ssh_files():
        say(f"Removed {path}.")
    if purge:
        with contextlib.suppress(DockerError):
            docker("volume", "rm", f"umcodex-home-{SETUP_ID}", check=False)
        shutil.rmtree(app_dir(), ignore_errors=True)
        say(f"Removed the test's Codex history volume and {app_dir()}.")
    say(f"Left as they are: the line `{INCLUDE_LINE}` at the top of ~/.ssh/config")
    say("(backup: ~/.ssh/config.um-codex-backup), and the app copy if it's open (quit it with Cmd-Q).")
    return 0
