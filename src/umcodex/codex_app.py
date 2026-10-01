"""M6, "Open in: Codex app": the Codex desktop app as the front end of a
launch, with every file, command and model call inside the container.

Design: docs/DESIGN.md (M6), from the spike of 2026-10-01
(docs/spikes/2026-10-01-codex-desktop-app.md and its hands-on results). The
app ("ChatGPT.app", bundle id com.openai.codex) reaches a container through
its SSH "Connections":

- **Per setup, a stable ssh host** `umcodex-<setup id>`, in UM-Codex's own
  ssh config file `~/.ssh/um-codex/config`, with a key pair per setup in the
  same folder (0700, keys 0600). Its `ProxyCommand` is `um-codex ssh-proxy
  <setup>` (absolute paths), which runs `docker exec -i -u root <agent>
  /usr/sbin/sshd -i` for that one connection: nothing listens, and it works
  with the internet off.
- **One line at the very top of `~/.ssh/config`**, `Include
  ~/.ssh/um-codex/config` (the app follows only top-level Includes), added
  only with the person's consent, after a backup. `um-codex uninstall`
  removes it.
- **The container:** a launch as any other (relay, gateway, token, folders,
  internet), with the label `umcodex.ssh=<setup>`; then (as root, through
  `docker exec`) a host key, the setup's public key for `agent`, and the
  launch token in `/run/um-codex/token`, which Codex's provider reads with a
  command (ssh sessions don't get `docker run -e`).
- **A separate copy of the app**, with UM-Codex's own CODEX_HOME and Electron
  profile under the data folder (`codex-app/`), as the app's own "Codex Demo"
  launcher opens one. The person's own copy and ~/.codex are never touched.
  Its own (local, "this computer") side uses the Toolkit through the current
  launch's relay; those chats run on the Mac, not in the sandbox, and only
  while a launch runs.
- **The first time** for a setup, the copy opens on the documented link that
  adds the host (switched off); the person switches it on and opens /work
  once (the launcher shows the steps). The launch watches for Codex's
  app-server inside the container and marks it "Connected". The app keeps
  the host switched on, so later launches of the setup need no steps.

Windows: the ssh side is written for Windows OpenSSH, but opening a second
copy of the Store app with its own settings isn't verified, so "Codex app"
is Mac only for now (`unavailable_reason`).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w

from umcodex.containers import APP, APP_LABEL, INSTANCE_LABEL, Docker, DockerError, instance_of
from umcodex.paths import data_dir
from umcodex.setups import Setup

log = logging.getLogger(__name__)

Say = Callable[[str], None]
Runner = Callable[..., subprocess.CompletedProcess]

SSH_LABEL = "umcodex.ssh"
ALIAS_PREFIX = "umcodex-"
TOKEN_FILE = "/run/um-codex/token"
SSHD = ("/usr/sbin/sshd", "-i", "-f", "/etc/um-codex/sshd_config")
INCLUDE_LINE = "Include ~/.ssh/um-codex/config"
BACKUP_NAME = "config.um-codex-backup"
APP_BUNDLE_ID = "com.openai.codex"
APP_FOLDER = "codex-app"  # in the data folder: the app copy's CODEX_HOME and profile
APP_DOWNLOAD = "https://chatgpt.com/download"

# What the launcher (and the terminal) says before adding the Include line.
INCLUDE_EXPLAINED = (
    "The Codex app finds the sandbox through your ssh settings. UM-Codex keeps its own in "
    "~/.ssh/um-codex (one entry and key per setup), and needs one line at the top of your "
    "~/.ssh/config to point there: Include ~/.ssh/um-codex/config. Your file is backed up first "
    "(~/.ssh/config.um-codex-backup), nothing else in it changes, and uninstalling UM-Codex "
    "takes the line out again. The entries reach only UM-Codex's own sandboxes, through Docker "
    "on this computer."
)

# The plain lines the launcher and the terminal show for a setup in the app.
APP_NOTES = (
    "Chats must show Remote · {alias} to run in the sandbox. Other chats in that Codex window "
    "run on this computer, not in the sandbox, and work only while a setup is running.",
    "The Codex app's own browser runs on this computer, not in the sandbox; use the Browser tool "
    "for browsing inside it.",
)


def alias(setup_id: str) -> str:
    """The ssh host name the app shows for a setup. Stable per setup: the app
    keeps its switch, projects and chats by this name."""
    return ALIAS_PREFIX + setup_id


def notes(setup_id: str) -> list[str]:
    return [note.format(alias=alias(setup_id)) for note in APP_NOTES]


def first_steps(setup_id: str) -> list[str]:
    """What the person does once per setup, in UM-Codex's Codex window (from
    the hands-on test: the one-step link didn't connect by itself)."""
    name = alias(setup_id)
    return [
        "Switch to UM-Codex's Codex window (a second ChatGPT icon in the Dock).",
        f"Open Settings → Connections, and turn on {name}.",
        f"Start a new chat: choose the project “work” (Remote · {name}), or add the folder /work on {name}.",
        f"Check that the chat shows Remote · {name}, then ask away.",
    ]


# --- Where things go -----------------------------------------------------------


def user_home() -> Path:
    """The person's home folder (tests point it elsewhere)."""
    return Path.home()


def ssh_dir(home: Path | None = None) -> Path:
    return (home or user_home()) / ".ssh"


def own_ssh_dir(home: Path | None = None) -> Path:
    return ssh_dir(home) / "um-codex"


def key_path(setup_id: str, home: Path | None = None) -> Path:
    return own_ssh_dir(home) / f"{setup_id}_ed25519"


def app_folder(data: Path | None = None) -> Path:
    return (data or data_dir()) / APP_FOLDER


def _private_write(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
        file.write(text)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)


# --- The Include line in ~/.ssh/config (only with consent) ------------------------


def _top_lines(text: str) -> list[str]:
    """The config's lines before its first Host or Match block, stripped."""
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if re.match(r"(?i)(host|match)\s", line):
            break
        lines.append(line)
    return lines


def include_present(home: Path | None = None) -> bool:
    """Whether ~/.ssh/config has UM-Codex's Include line where the app follows
    it (before any Host or Match block)."""
    config = ssh_dir(home) / "config"
    try:
        text = config.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return INCLUDE_LINE in _top_lines(text)


def add_include(home: Path | None = None) -> str:
    """Put the Include line at the very top of ~/.ssh/config, after backing
    the file up (once: an older backup is the person's original). Returns
    "created", "added" or "already there"."""
    folder = ssh_dir(home)
    config = folder / "config"
    if not config.exists():
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        _private_write(config, INCLUDE_LINE + "\n")
        return "created"
    if include_present(home):
        return "already there"
    text = config.read_text(encoding="utf-8")
    backup = folder / BACKUP_NAME
    if not backup.exists():
        shutil.copy2(config, backup)
    newline = "\r\n" if "\r\n" in text else "\n"
    # In place, so the file keeps its own permissions (and stays a link's target).
    with config.open("r+", encoding="utf-8", newline="") as file:
        file.seek(0)
        file.write(INCLUDE_LINE + newline + text)
        file.truncate()
    return "added"


def remove_include(home: Path | None = None) -> list[str]:
    """Take the Include line out of ~/.ssh/config (uninstall). The backup goes
    too when the file is now the same as it, or the file itself when
    UM-Codex made it and only the line was in it. Returns what was done, in
    plain words."""
    folder = ssh_dir(home)
    config = folder / "config"
    backup = folder / BACKUP_NAME
    done: list[str] = []
    try:
        text = config.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = None
    if text is not None and INCLUDE_LINE in text:
        kept = "".join(line for line in text.splitlines(keepends=True) if line.strip() != INCLUDE_LINE)
        if not kept.strip() and not backup.exists():
            config.unlink()
            done.append(f"Removed {config} (UM-Codex had made it for its one line).")
        else:
            with config.open("r+", encoding="utf-8", newline="") as file:
                file.write(kept)
                file.truncate()
            done.append(f"Took the line “{INCLUDE_LINE}” out of {config}.")
    if backup.exists():
        try:
            same = config.exists() and backup.read_bytes() == config.read_bytes()
        except OSError:
            same = False
        if same:
            backup.unlink()
            done.append(f"Removed its backup {backup} (the same as the file now).")
        else:
            done.append(f"Kept {backup}: your ssh config has changed since UM-Codex backed it up.")
    return done


def remove_ssh_files(home: Path | None = None) -> list[str]:
    """Remove ~/.ssh/um-codex (uninstall)."""
    folder = own_ssh_dir(home)
    if not folder.exists():
        return []
    shutil.rmtree(folder, ignore_errors=True)
    if folder.exists():
        return [f"Couldn't remove {folder}: delete it yourself."]
    return [f"Removed {folder}."]


# --- UM-Codex's own ssh config ------------------------------------------------------


def _ssh_arg(part: str) -> str:
    """One ProxyCommand word for ssh: `%` doubled (ssh's own tokens), and
    double quotes around a word with a space (the shell on a Mac, Windows'
    command line on Windows)."""
    if '"' in part or "\n" in part:
        raise ValueError("a ProxyCommand part can't hold a double quote or a line break")
    part = part.replace("%", "%%")
    return f'"{part}"' if re.search(r"\s", part) else part


def proxy_command(setup_id: str) -> list[str]:
    """The ProxyCommand: this UM-Codex's `ssh-proxy` with absolute paths (the
    app checks the command in its own PATH, which a Dock start keeps short).
    An installed UM-Codex uses its launcher command (`<app>/bin/um-codex`,
    which follows updates); a development copy, its own Python."""
    from umcodex.docker_path import ensure_docker_on_path
    from umcodex.update import Layout, install_root

    layout = Layout(install_root())
    if layout.running_version() is not None and layout.command.exists():
        program = [str(layout.command)]
    else:
        program = [sys.executable, "-m", "umcodex"]
    ensure_docker_on_path()
    docker = shutil.which("docker") or "docker"
    command = [*program, "ssh-proxy", setup_id, "--docker", str(Path(docker).absolute())]
    if os.environ.get("UMCODEX_DATA_DIR"):  # development and tests only
        command += ["--data-dir", str(data_dir())]
    return command


def host_block(setup_id: str, proxy: Sequence[str]) -> str:
    """One Host for a setup. Everything ssh needs is here: the app adds only
    BatchMode, timeouts and keep-alives to its ssh commands."""
    name = alias(setup_id)
    return "\n".join(
        [
            f"Host {name}",
            # Never used: the ProxyCommand reaches the container through Docker.
            f"  HostName {name}.invalid",
            "  User agent",
            f"  IdentityFile ~/.ssh/um-codex/{setup_id}_ed25519",
            "  IdentitiesOnly yes",
            "  IdentityAgent none",
            "  ForwardAgent no",
            "  ForwardX11 no",
            "  PasswordAuthentication no",
            "  KbdInteractiveAuthentication no",
            # The transport is `docker exec` on this computer, and each
            # container makes a new host key, so there's nothing to check.
            "  StrictHostKeyChecking no",
            "  UserKnownHostsFile /dev/null",
            "  LogLevel ERROR",
            f"  ProxyCommand {' '.join(_ssh_arg(part) for part in proxy)}",
            "",
        ]
    )


SETUP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


def known_setups(home: Path | None = None) -> list[str]:
    """The setups that have a key here (each was opened in the app once)."""
    folder = own_ssh_dir(home)
    if not folder.is_dir():
        return []
    found = [p.name.removesuffix("_ed25519") for p in folder.glob("*_ed25519") if p.is_file()]
    return sorted(s for s in found if SETUP_ID.fullmatch(s))


def write_config(proxy_for: Callable[[str], Sequence[str]] = proxy_command, home: Path | None = None) -> Path:
    """~/.ssh/um-codex/config: one Host per setup with a key, rewritten whole."""
    folder = own_ssh_dir(home)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(folder, 0o700)
    blocks = [host_block(setup_id, proxy_for(setup_id)) for setup_id in known_setups(home)]
    header = [
        "# Written by UM-Codex, rewritten at each launch in the Codex app; changes here are lost.",
        "# Each Host reaches one setup's sandbox while it runs (um-codex ssh-proxy, through Docker).",
        "",
    ]
    path = folder / "config"
    _private_write(path, "\n".join(header) + "\n".join(blocks))
    return path


def ensure_key(setup_id: str, home: Path | None = None, run: Runner = subprocess.run) -> Path:
    """The setup's key pair (kept between launches). Returns the public key's path."""
    if not SETUP_ID.fullmatch(setup_id):
        raise ValueError("unusual setup id")
    folder = own_ssh_dir(home)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(folder, 0o700)
    key = key_path(setup_id, home)
    public = key.with_name(key.name + ".pub")
    if not (key.exists() and public.exists()):
        key.unlink(missing_ok=True)
        public.unlink(missing_ok=True)
        run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", f"um-codex {setup_id}", "-f", str(key)],
            check=True,
            capture_output=True,
            timeout=60,
        )
    with contextlib.suppress(OSError):
        os.chmod(key, 0o600)
    return public


def forget_setup(setup_id: str, home: Path | None = None) -> None:
    """A deleted setup: its key goes, and its Host with it."""
    if not SETUP_ID.fullmatch(setup_id):
        return
    key = key_path(setup_id, home)
    if not key.exists() and not key.with_name(key.name + ".pub").exists():
        return
    key.unlink(missing_ok=True)
    key.with_name(key.name + ".pub").unlink(missing_ok=True)
    with contextlib.suppress(OSError, ValueError):
        write_config(home=home)


# --- ssh's ProxyCommand ---------------------------------------------------------------


def find_agent(docker: Docker, setup_id: str, instance: str) -> str | None:
    """The running agent container of the setup's launch in the app, by label."""
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


def ssh_proxy(setup_id: str, docker_command: str = "docker", data: Path | None = None) -> int:
    """`um-codex ssh-proxy <setup>`: ssh's ProxyCommand. Becomes `docker exec
    -i -u root <agent> sshd -i`, so ssh talks to an sshd that runs for this
    one connection. Nothing but ssh's own bytes on stdout."""

    def run(command: list[str], **options: object) -> subprocess.CompletedProcess:
        return subprocess.run([docker_command, *command[1:]], **options)  # type: ignore[call-overload]

    docker = Docker(run)
    try:
        agent = find_agent(docker, setup_id, instance_of(data or data_dir()))
    except DockerError as error:
        print(f"um-codex ssh-proxy: {error}", file=sys.stderr)
        return 1
    if agent is None:
        print(
            f"um-codex ssh-proxy: {alias(setup_id)} isn't running. Start it in UM-Codex "
            "(Open in: Codex app) first.",
            file=sys.stderr,
        )
        return 1
    command = [docker_command, "exec", "-i", "-u", "root", agent, *SSHD]
    if sys.platform == "win32":  # no exec there: run it with ssh's own stdin and stdout
        return subprocess.call(command)
    os.execv(docker_command, command)
    return 1  # not reached


# --- Inside the container -------------------------------------------------------------

# Run as root in the agent once it's up: a host key, the launch token for the
# provider's command (from the container's own environment, which docker exec
# inherits; never on a command line), the setup's public key (on stdin).
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

# The app starts Codex's app-server in the container with `nohup codex ...
# app-server --listen unix://` (the spike, and the test's monitor).
APP_SERVER_PATTERN = "app-server --listen"


def prepare_container(docker: Docker, agent: str, public_key: Path, run: Runner = subprocess.run) -> None:
    done = run(
        ["docker", "exec", "-i", "-u", "root", agent, "sh", "-c", PREPARE],
        input=public_key.read_bytes(),
        capture_output=True,
        timeout=60,
        check=False,
    )
    if done.returncode != 0:
        raise DockerError("the sandbox couldn't be prepared for the Codex app")


def app_server_running(docker: Docker, agent: str) -> bool:
    """Whether the Codex app has started Codex's app-server in the container."""
    try:
        code, _, _ = docker.status("exec", agent, "pgrep", "-f", APP_SERVER_PATTERN, timeout=15)
    except DockerError:
        return False
    return code == 0


# --- The UM-Codex copy of the app -------------------------------------------------------


def _bundle_id(app: Path) -> str | None:
    try:
        with (app / "Contents" / "Info.plist").open("rb") as file:
            info = plistlib.load(file)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    value = info.get("CFBundleIdentifier") if isinstance(info, dict) else None
    return value if isinstance(value, str) else None


def find_app(
    *, platform: str = sys.platform, home: Path | None = None, run: Runner = subprocess.run
) -> Path | None:
    """The Codex app (the ChatGPT desktop app, bundle id com.openai.codex):
    in /Applications or ~/Applications, else wherever Spotlight knows it."""
    if platform != "darwin":
        return None
    home = home or user_home()
    names = ("ChatGPT.app", "Codex.app")
    candidates = [Path("/Applications") / n for n in names] + [home / "Applications" / n for n in names]
    for candidate in candidates:
        if _bundle_id(candidate) == APP_BUNDLE_ID:
            return candidate
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        done = run(
            ["/usr/bin/mdfind", f'kMDItemCFBundleIdentifier == "{APP_BUNDLE_ID}"'],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in (done.stdout or "").splitlines():
            found = Path(line.strip())
            if line.strip().endswith(".app") and _bundle_id(found) == APP_BUNDLE_ID:
                return found
    return None


def unavailable_reason(platform: str = sys.platform, app: Path | None = None) -> str | None:
    """Why "Open in: Codex app" can't be used here, in plain words (None: it can)."""
    if platform == "win32":
        return "The Codex app works with UM-Codex on a Mac only, for now. Use Terminal."
    if platform != "darwin":
        return "The Codex app works with UM-Codex on a Mac only."
    if app is None:
        return (
            "The Codex app isn't installed. It's part of OpenAI's ChatGPT desktop app: get it from "
            f"{APP_DOWNLOAD}, then come back. Terminal works in the meantime."
        )
    return None


def deep_link(setup_id: str) -> str:
    """The documented link that adds the host (switched off) in Settings → Connections."""
    return f"codex://settings/connections/ssh/add?name={alias(setup_id)}"


def copy_paths(data: Path | None = None) -> tuple[Path, Path]:
    """The copy's CODEX_HOME and Electron profile."""
    folder = app_folder(data)
    return folder / "codex-home", folder / "user-data"


def open_command(app: Path, data: Path | None = None, link: str | None = None) -> list[str]:
    """A second, separate copy of the app, as its "Codex Demo" launcher starts
    one. The link goes in its arguments: the app reads codex:// links from
    its command line at start, while `open <link>` could reach the person's
    own copy."""
    home, user_data = copy_paths(data)
    return [
        "/usr/bin/open", "-n",
        "--env", f"CODEX_HOME={home}",
        "--env", f"CODEX_ELECTRON_USER_DATA_PATH={user_data}",
        str(app),
        "--args", f"--user-data-dir={user_data}",
        *([link] if link else []),
    ]  # fmt: skip


def running_copy(data: Path | None = None, run: Runner = subprocess.run) -> int | None:
    """The PID of UM-Codex's copy of the app, if it's running: the main
    process whose arguments carry the copy's profile folder."""
    _, user_data = copy_paths(data)
    marker = f"--user-data-dir={user_data}"
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        done = run(["/bin/ps", "-axww", "-o", "pid=,args="], capture_output=True, text=True, timeout=10)
        for line in (done.stdout or "").splitlines():
            pid, _, args = line.strip().partition(" ")
            program = args.split(" --", 1)[0]
            helper = "/Contents/Frameworks/" in program or " --type=" in args
            if marker in args and "/Contents/MacOS/" in program and not helper and pid.isdigit():
                return int(pid)
    return None


# JavaScript for Automation, through AppKit (no permission to control other apps needed).
_ACTIVATE = (
    'ObjC.import("AppKit"); function run(argv) { '
    "var app = $.NSRunningApplication.runningApplicationWithProcessIdentifier(parseInt(argv[0])); "
    'if (!app || app.isNil()) return "gone"; '
    'return app.activateWithOptions($.NSApplicationActivateAllWindows) ? "ok" : "refused"; }'
)


def bring_forward(pid: int, run: Runner = subprocess.run) -> bool:
    """Ask macOS to bring that copy to the front. macOS may decline (an app
    in the background can't always take focus); the launcher then says where it is."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        done = run(
            ["/usr/bin/osascript", "-l", "JavaScript", "-e", _ACTIVATE, str(pid)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return done.returncode == 0 and done.stdout.strip() == "ok"
    return False


def local_config(existing: str, relay_port: int, token_file: Path, model: str) -> str:
    """The copy's own config.toml: its local side ("this computer") uses the
    Toolkit through this launch's relay, with the launch token read from a
    private file, so the copy needs no ChatGPT or OpenAI sign-in. The other
    settings the app saved there are kept."""
    try:
        config = tomllib.loads(existing) if existing.strip() else {}
    except tomllib.TOMLDecodeError:
        config = {}
    providers = config.get("model_providers")
    providers = providers if isinstance(providers, dict) else {}
    providers["toolkit"] = {
        "name": "U-M GPT Toolkit (through UM-Codex)",
        "base_url": f"http://127.0.0.1:{relay_port}/relay/v1",
        "wire_api": "responses",
        "request_max_retries": 1,
        "stream_max_retries": 2,
        "stream_idle_timeout_ms": 300000,
        "auth": {"command": "/bin/cat", "args": [str(token_file)]},
    }
    config.update(
        {
            "model_provider": "toolkit",
            "forced_login_method": "api",
            "check_for_update_on_startup": False,
            "analytics": {"enabled": False},
            "feedback": {"enabled": False},
            "model_providers": providers,
        }
    )
    config.setdefault("model", model)
    head = "# UM-Codex sets the provider here at each launch in the Codex app; the rest is the app's.\n"
    return head + tomli_w.dumps(config)


# --- Which setups have connected once ---------------------------------------------


def _hosts_file(data: Path | None = None) -> Path:
    return app_folder(data) / "hosts.json"


def connected_before(setup_id: str, data: Path | None = None) -> bool:
    try:
        hosts = json.loads(_hosts_file(data).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(hosts, dict) and alias(setup_id) in hosts


def mark_connected(setup_id: str, data: Path | None = None) -> None:
    path = _hosts_file(data)
    try:
        hosts = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        hosts = {}
    if not isinstance(hosts, dict):
        hosts = {}
    hosts[alias(setup_id)] = {"connected_at": time.time()}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".hosts.{os.getpid()}.json")
    temporary.write_text(json.dumps(hosts) + "\n", encoding="utf-8")
    os.replace(temporary, path)


# --- The launch, held while the app uses it ------------------------------------------


@dataclass
class AppHold:
    """launch.run's `hold` for a setup opened in the Codex app: prepares the
    container and this computer's ssh files, opens (or finds) UM-Codex's copy
    of the app, then waits until the launch is stopped (its containers are
    removed: Stop in the launcher), or Ctrl-C in a terminal, watching for the
    app's connection."""

    setup_id: str
    say: Say = print
    data: Path = field(default_factory=data_dir)
    app: Path | None = None  # None: don't open the app (development checks)
    docker: Docker = field(default_factory=Docker)
    run: Runner = subprocess.run
    poll_seconds: float = 2.0
    sleep: Callable[[float], None] = time.sleep
    proxy_for: Callable[[str], Sequence[str]] = proxy_command
    labels: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        self.labels = ((SSH_LABEL, self.setup_id),)

    def __call__(self, running) -> int:  # running: launch.Running
        from umcodex.launch import update_launch_app

        spec, setup = running.spec, running.setup
        name = alias(setup.id)
        self.say("Preparing the sandbox for the Codex app...")
        public = ensure_key(setup.id, run=self.run)
        write_config(self.proxy_for)
        prepare_container(self.docker, spec.agent, public, run=self.run)
        token_file = self._write_copy_files(running.relay_port, running.token, setup)
        first = not connected_before(setup.id, self.data)
        state = {
            "alias": name,
            "connected": False,
            "first_time": first,
            "steps": first_steps(setup.id),
            "notes": notes(setup.id),
            "copy": "not-opened",
        }
        try:
            state["copy"] = self._open_copy(setup.id, first)
            update_launch_app(running.folder, state)
            self._say_ready(name, state)
            return self._wait(running, state)
        except KeyboardInterrupt:
            self.say("")
            self.say("Ending the launch...")
            return 0
        finally:
            # Only this launch's token (another launch may have written its own since).
            with contextlib.suppress(OSError):
                if token_file.read_text(encoding="utf-8") == running.token:
                    token_file.unlink()

    def _write_copy_files(self, relay_port: int, token: str, setup: Setup) -> Path:
        home, user_data = copy_paths(self.data)
        for folder in (app_folder(self.data), home, user_data):
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        token_file = app_folder(self.data) / "launch-token"
        _private_write(token_file, token)
        config = home / "config.toml"
        existing = config.read_text(encoding="utf-8") if config.exists() else ""
        _private_write(config, local_config(existing, relay_port, token_file, setup.model))
        return token_file

    def _open_copy(self, setup_id: str, first: bool) -> str:
        if self.app is None:
            return "not-opened"
        pid = running_copy(self.data, self.run)
        if pid is not None:
            return "brought-forward" if bring_forward(pid, self.run) else "already-open"
        # The add link only the first time: it adds the host switched off, so
        # later it would switch off a host the person turned on.
        link = deep_link(setup_id) if first else None
        done = self.run(open_command(self.app, self.data, link), capture_output=True, timeout=60, check=False)
        if done.returncode != 0:
            log.warning("the Codex app copy didn't open (exit code %s)", done.returncode)
            return "failed"
        return "opened"

    def _say_ready(self, name: str, state: dict) -> None:
        copy = state["copy"]
        if copy == "failed":
            self.say("UM-Codex's Codex window couldn't be opened. Open the launcher and try again.")
        elif copy == "already-open":
            self.say(
                "UM-Codex's Codex window is already open: switch to it (the second ChatGPT icon in the Dock)."
            )
        if state["first_time"]:
            self.say("")
            self.say("The first time for this setup, in UM-Codex's Codex window:")
            for number, step in enumerate(state["steps"], 1):
                self.say(f"  {number}. {step}")
        else:
            self.say(f"The Codex app reconnects to {name} by itself.")
        self.say("")
        for line in state["notes"]:
            self.say(line)
        self.say("")
        self.say("The sandbox runs until you stop it (Stop in UM-Codex, or Ctrl-C here).")
        with contextlib.suppress(OSError, ValueError):
            sys.stdout.flush()

    def _wait(self, running, state: dict) -> int:
        from umcodex.launch import update_launch_app

        agent = running.spec.agent
        missing = 0
        while True:
            # Twice in a row: a Docker that's slow to answer once isn't a stop.
            missing = 0 if self.docker.running(agent) else missing + 1
            if missing >= 2:
                self.say("The sandbox was stopped.")
                return 0
            if not state["connected"] and app_server_running(self.docker, agent):
                state = {**state, "connected": True, "first_time": False}
                mark_connected(running.setup.id, self.data)
                update_launch_app(running.folder, state)
                log.info("launch %s: the Codex app connected", running.spec.launch_id)
                self.say(f"Connected: the Codex app is working in the sandbox ({state['alias']}).")
            self.sleep(self.poll_seconds)


def ask_for_include(ask: Callable[[str], str], say: Say, home: Path | None = None) -> bool:
    """The terminal's way to the Include line: the explanation, then a yes/no."""
    if include_present(home):
        return True
    say(INCLUDE_EXPLAINED)
    answer = ask("Add that line to ~/.ssh/config now? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        say("Nothing was changed. The Codex app can't reach the sandbox without it; use Terminal instead.")
        return False
    say(f"~/.ssh/config: {add_include(home)} (backup: ~/.ssh/{BACKUP_NAME}).")
    return True


def app_launch_running(docker: Docker, setup_id: str, data: Path | None = None) -> bool:
    """Whether this setup already runs in the Codex app (one at a time: the
    proxy must find exactly one sandbox for the host)."""
    try:
        out = docker(
            "ps", "-q",
            "--filter", f"label={SSH_LABEL}={setup_id}",
            "--filter", f"label={INSTANCE_LABEL}={instance_of(data or data_dir())}",
            "--filter", f"label={APP_LABEL}={APP}",
            check=False,
        )  # fmt: skip
    except DockerError:
        return False
    return bool(out.split())
