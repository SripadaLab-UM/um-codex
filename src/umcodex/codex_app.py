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
  Its own (local, "this computer") chats would run on the Mac, outside the
  sandbox, so they're blocked: its provider is the launch's relay, which
  answers them with a reminder to use a Remote chat and never calls the
  model (LOCAL_CHATS).
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
import shlex
import shutil
import stat
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable, Iterable, Sequence
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
    "Chats must show Remote · {alias} (and a globe) to run in the sandbox. {other}",
    "The app may show the chat's permissions as Custom (greyed): UM-Codex fixes them to full access "
    "inside the sandbox, so there's nothing to choose there.",
    "The Codex app's own browser runs on this computer, not in the sandbox; use the Browser tool "
    "for browsing inside it.",
)
# Pop-ups the app may still show (UM-Codex marks them as seen beforehand; an
# app update can bring new ones).
POPUP_NOTE = (
    "If the app asks what you'll use it for, choose Skip. If it announces a new model, choose "
    "Continue with current model: the setup decides the model."
)


def alias(setup_id: str) -> str:
    """The ssh host name the app shows for a setup. Stable per setup: the app
    keeps its switch, projects and chats by this name."""
    return ALIAS_PREFIX + setup_id


OTHER_CHATS = {
    True: "Other chats in that Codex window run on this computer, not in the sandbox, and work only "
    "while a setup is running.",
    False: "Other (local) chats in that Codex window would run on this computer, outside the sandbox, "
    "so they're blocked: they only answer with that reminder.",
}


def notes(setup_id: str, *, local_chats: bool | None = None) -> list[str]:
    other = OTHER_CHATS[LOCAL_CHATS if local_chats is None else local_chats]
    return [note.format(alias=alias(setup_id), other=other) for note in APP_NOTES]


def first_steps(setup_id: str, project: str) -> list[str]:
    """What the person does once per setup when UM-Codex couldn't set the
    copy up itself (it was already open, or the app's format changed), in
    UM-Codex's Codex window: the flow the GUI test found (app 26.928)."""
    name = alias(setup_id)
    return [
        "Switch to UM-Codex's Codex window (a second ChatGPT icon in the Dock).",
        f"Open Settings → Connections and press Add; choose {name} from the list, then Add. "
        "It's switched on and connects.",
        f"Go Home → Choose project → Create project. Name it “{project}”; under the source folders, "
        f"open “Add a folder on this computer”, choose {name}, then Add; type /work and press Return; "
        "then Create project.",
        f"Start a chat in that project, and check that it shows Remote · {name}.",
        POPUP_NOTE,
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
    """Write a file only the person can read (0600), whole: through a
    temporary file beside it and a rename, so a reader never sees half of it."""
    _replace(path, text.encode("utf-8"), mode=0o600)


def _replace(path: Path, data: bytes, *, mode: int) -> None:
    """Replace `path` (or, if it's a link, the file it leads to, so the link
    keeps working) with `data` atomically, with the given permissions."""
    target = Path(os.path.realpath(path))
    temporary = target.with_name(f".{target.name}.um-codex-{os.getpid()}-{time.monotonic_ns()}")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
        with contextlib.suppress(OSError):
            os.chmod(temporary, mode)
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


# --- The Include line in ~/.ssh/config (only with consent) ------------------------

# A Host or Match line, in any of ssh's forms: "Host a", "Host=a", "Host = a".
_BLOCK_START = re.compile(r"(?i)(host|match)(\s*=|\s)")


def _top_lines(text: str) -> list[str]:
    """The config's lines before its first Host or Match block, stripped."""
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if _BLOCK_START.match(line):
            break
        lines.append(line)
    return lines


def _read(path: Path) -> bytes:
    return path.read_bytes()


def include_present(home: Path | None = None) -> bool:
    """Whether ~/.ssh/config has UM-Codex's Include line where the app follows
    it (before any Host or Match block)."""
    config = ssh_dir(home) / "config"
    try:
        text = _read(config).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return INCLUDE_LINE in _top_lines(text)


def _mode(path: Path) -> int:
    try:
        return stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        return 0o600


def add_include(home: Path | None = None) -> str:
    """Put the Include line at the very top of ~/.ssh/config, after backing
    the file up (the backup is refreshed whenever it no longer matches the
    file as it is before the line goes in). The file keeps its own
    permissions and line endings, is replaced atomically, and a link to it
    keeps working. Returns "created", "added" or "already there". Raises
    OSError or UnicodeDecodeError (a file that isn't text) and changes nothing."""
    folder = ssh_dir(home)
    config = folder / "config"
    if not config.exists():
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        _private_write(config, INCLUDE_LINE + "\n")
        return "created"
    data = _read(config)
    text = data.decode("utf-8")
    if INCLUDE_LINE in _top_lines(text):
        return "already there"
    backup = folder / BACKUP_NAME
    if not backup.exists() or _read(backup) != data:
        _replace(backup, data, mode=_mode(config))
    newline = "\r\n" if "\r\n" in text else "\n"
    _replace(config, (INCLUDE_LINE + newline + text).encode("utf-8"), mode=_mode(config))
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
        text = _read(config).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        text = None
    if text is not None and INCLUDE_LINE in text:
        kept = "".join(line for line in text.splitlines(keepends=True) if line.strip() != INCLUDE_LINE)
        if not kept.strip() and not backup.exists():
            config.unlink()
            done.append(f"Removed {config} (UM-Codex had made it for its one line).")
        else:
            _replace(config, kept.encode("utf-8"), mode=_mode(config))
            done.append(f"Took the line “{INCLUDE_LINE}” out of {config}.")
    if backup.exists():
        try:
            same = config.exists() and _read(backup) == _read(config)
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


def _ssh_arg(part: str, platform: str = sys.platform) -> str:
    """One ProxyCommand word for ssh, with `%` doubled (ssh's own tokens).
    On a Mac ssh runs the command with the person's shell (`$SHELL -c "exec
    ..."`), so each word is shell-quoted (`shlex.quote`: `$`, backticks,
    quotes, `;` and `&` stay plain characters). Windows OpenSSH runs it
    itself, splitting it as a Windows command line: double quotes around a
    word with a space, and a double quote inside one is refused (no Windows
    path has one)."""
    if "\n" in part or "\r" in part or "\0" in part:
        raise ValueError("a ProxyCommand part can't hold a line break")
    part = part.replace("%", "%%")
    if platform == "win32":
        if '"' in part:
            raise ValueError("a ProxyCommand part can't hold a double quote on Windows")
        return f'"{part}"' if re.search(r"\s", part) else part
    return shlex.quote(part)


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
    BatchMode, timeouts and keep-alives to its ssh commands. The Include is
    the first line of ~/.ssh/config, so these values win (ssh keeps the first
    value it reads for each option); options set only in the person's own
    `Host *` (LocalForward, DynamicForward and the like) still apply, though
    the container's sshd allows only local forwards to its own localhost."""
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
            "  ForwardX11Trusted no",
            "  Tunnel no",
            "  ControlMaster no",
            "  ControlPath none",
            "  GSSAPIAuthentication no",
            "  UpdateHostKeys no",
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


def _saved_setup_ids() -> set[str]:
    from umcodex.setups import SetupStore

    return {setup.id for setup in SetupStore().all()}


def write_config(
    proxy_for: Callable[[str], Sequence[str]] = proxy_command,
    home: Path | None = None,
    setup_ids: Iterable[str] | None = None,
) -> Path:
    """~/.ssh/um-codex/config, rewritten whole: one Host per saved setup that
    has a key here (`setup_ids`: the saved setups; default, the setup store).
    Keys that belong to no saved setup (a deleted setup's, a test's) are
    removed."""
    folder = own_ssh_dir(home)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(folder, 0o700)
    saved = set(_saved_setup_ids() if setup_ids is None else setup_ids)
    hosts = []
    for setup_id in known_setups(home):
        if setup_id in saved:
            hosts.append(setup_id)
            continue
        key = key_path(setup_id, home)
        key.unlink(missing_ok=True)
        key.with_name(key.name + ".pub").unlink(missing_ok=True)
        log.info("removed the ssh key of %s, which is no saved setup", setup_id)
    blocks = [host_block(setup_id, proxy_for(setup_id)) for setup_id in hosts]
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
    remaining = [other for other in known_setups(home) if other != setup_id]
    with contextlib.suppress(OSError, ValueError):
        write_config(home=home, setup_ids=remaining)


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


def prepare_container(docker: Docker, agent: str, public_key: Path) -> None:
    code, _, _ = docker.status(
        "exec", "-i", "-u", "root", agent, "sh", "-c", PREPARE,
        input=public_key.read_text(encoding="utf-8"), timeout=60,
    )  # fmt: skip
    if code != 0:
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


# Chats on the copy's own side ("this computer": local, not Remote ·
# umcodex-...) would run on the Mac, outside the sandbox. The maintainer
# decided (2026-10-01) to block them: the copy's provider leads to the
# launch's relay at `/um-codex-local/<alias>/v1` (relay.LOCAL_PREFIX), which
# answers every request itself with a message saying to use a Remote chat,
# and never calls the model. True switches back to what the hands-on test
# did: local chats through the relay to the Toolkit, with the launch token.
LOCAL_CHATS = False


def local_config(
    existing: str,
    port: int,
    model: str,
    *,
    setup_alias: str,
    token_file: Path | None = None,
    local_chats: bool = LOCAL_CHATS,
    catalog: Path | None = None,
) -> str:
    """The copy's own config.toml. Its provider is a custom one without
    `requires_openai_auth`, so the copy opens with no ChatGPT or OpenAI
    sign-in. With local chats blocked (the default), `port` is the
    local-chats responder's (LocalChatsServer: no credential, no model
    call); with them on, it's the launch's relay, to the Toolkit with the
    launch token read from `token_file`.
    The other settings the app saved there are kept. `existing` must parse
    (AppHold moves a broken file aside first)."""
    config = tomllib.loads(existing) if existing.strip() else {}
    providers = config.get("model_providers")
    providers = providers if isinstance(providers, dict) else {}
    if local_chats:
        if token_file is None:
            raise ValueError("local chats need the launch token's file")
        providers["toolkit"] = {
            "name": "U-M GPT Toolkit (through UM-Codex)",
            "base_url": f"http://127.0.0.1:{port}/relay/v1",
            "wire_api": "responses",
            "request_max_retries": 1,
            "stream_max_retries": 2,
            "stream_idle_timeout_ms": 300000,
            "auth": {"command": "/bin/cat", "args": [str(token_file)]},
        }
    else:
        providers["toolkit"] = {
            "name": "UM-Codex: use a Remote chat",
            "base_url": f"http://127.0.0.1:{port}/um-codex-local/{setup_alias}/v1",
            "wire_api": "responses",
            "request_max_retries": 0,
            "stream_max_retries": 0,
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
    if catalog is not None:
        # No upgrade offers or new-model announcements on the copy's own side.
        config["model_catalog_json"] = str(catalog)
    else:
        config.pop("model_catalog_json", None)
    head = "# UM-Codex sets the provider here at each launch in the Codex app; the rest is the app's.\n"
    return head + tomli_w.dumps(config)


# --- The local-chats responder ----------------------------------------------------
#
# The copy keeps the config it started with while it runs, so its local
# provider can't follow a launch's relay port (the GUI test: after Stop and
# Start, an old local chat waited for a relay that was gone, showing
# "Reconnecting... waiting for network"). It points at a port fixed per data
# folder instead (`codex-app/local-chats-port`), where every app launch and
# the launcher window serve the responder (relay.local_chats_app): whichever
# binds it first, the others see it's there (`_whoami`). A failing
# `auth.command` was tried first: Codex 0.159.2 then retries for ever with
# "Reconnecting... waiting for network", never showing its message.

PORT_FILE = "local-chats-port"


def _port_file(data: Path | None = None) -> Path:
    return app_folder(data) / PORT_FILE


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def local_chats_port(data: Path | None = None) -> int:
    """This data folder's port for the responder, chosen once and kept."""
    path = _port_file(data)
    try:
        port = int(path.read_text(encoding="ascii").strip())
        if 1024 < port < 65536:
            return port
    except (OSError, ValueError):
        pass
    port = _free_port()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _private_write(path, f"{port}\n")
    return port


def _serves_us(port: int, instance: str) -> bool:
    import httpx

    from umcodex.relay import LOCAL_WHOAMI

    try:
        answer = httpx.get(f"http://127.0.0.1:{port}{LOCAL_WHOAMI}", timeout=2)
        return answer.json().get("instance") == instance
    except (httpx.HTTPError, ValueError, AttributeError):
        return False


class LocalChatsServer:
    """Serves the local-chats responder on this data folder's port, in a
    background thread, while it holds the port. `ensure()` (call it again
    from time to time) takes the port over when the process that had it has
    ended. If another program holds the port, a new one is chosen and kept;
    the copy follows it after a restart (its config is rewritten at each
    launch)."""

    def __init__(self, data: Path | None = None) -> None:
        self.data = data or data_dir()
        self._loop = None
        self._thread = None
        self._runner = None
        self.port: int | None = None

    @property
    def serving(self) -> bool:
        return self._runner is not None

    def ensure(self) -> int:
        """The port local chats reach now (served here or by another UM-Codex)."""
        port = local_chats_port(self.data)
        if self.serving and self.port == port:
            return port
        instance = instance_of(self.data)
        if self._bind(port, instance):
            return port
        if _serves_us(port, instance):
            return port
        log.warning("the local-chats port %d is used by another program; choosing another", port)
        _port_file(self.data).unlink(missing_ok=True)
        port = local_chats_port(self.data)
        self._bind(port, instance)
        return port

    def _bind(self, port: int, instance: str) -> bool:
        import asyncio
        import socket
        import threading

        from aiohttp import web

        from umcodex.relay import local_chats_app

        self.stop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            sock.close()
            return False
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, name="umcodex-local-chats", daemon=True)
        thread.start()

        data = self.data

        def running() -> list[str]:
            from umcodex.launch import running_launches

            return [
                launch.app["alias"]
                for launch in running_launches(data)
                if launch.app and "alias" in launch.app
            ]

        async def start() -> web.AppRunner:
            runner = web.AppRunner(local_chats_app(instance, running), access_log=None)
            await runner.setup()
            await web.SockSite(runner, sock).start()
            return runner

        self._runner = asyncio.run_coroutine_threadsafe(start(), loop).result(timeout=20)
        self._loop, self._thread, self.port = loop, thread, port
        return True

    def stop(self) -> None:
        import asyncio

        if self._loop is None or self._runner is None:
            return
        loop, runner, thread = self._loop, self._runner, self._thread
        self._loop = self._runner = self._thread = None
        self.port = None
        with contextlib.suppress(Exception):
            asyncio.run_coroutine_threadsafe(runner.cleanup(), loop).result(timeout=10)
        loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=10)
        loop.close()


# --- The copy's own state: the host, its project, pop-ups seen ----------------
#
# The app (26.928) keeps its connections, projects and what it has shown in
# `$CODEX_HOME/.codex-global-state.json` (and `.bak`, read when the first
# doesn't parse): a plain JSON object, loaded once when the app starts and
# rewritten by it as things change, each key checked against a schema (a
# value that fails is dropped). So UM-Codex merges its entries in only while
# the copy isn't running; with the copy open, the launcher shows the steps.
# The shapes are the ones the app itself wrote in the GUI test, after the
# host was added and a project made by hand. If the file holds anything
# UM-Codex doesn't recognise for these keys (an app update changed them), it
# changes nothing and the launcher shows the steps.

GLOBAL_STATE = ".codex-global-state.json"
ATOMS = "electron-persisted-atom-state"
TESTED_APP_VERSIONS = ("26.928.",)  # the app versions this was checked with


def host_id(setup_id: str) -> str:
    return f"remote-ssh-discovered:{alias(setup_id)}"


def project_id(setup_id: str) -> str:
    """The setup's project id in the app: stable (a UUID from the alias)."""
    import uuid

    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"um-codex:{alias(setup_id)}:/work"))


def app_version(app: Path | None) -> str | None:
    if app is None:
        return None
    try:
        with (app / "Contents" / "Info.plist").open("rb") as file:
            value = plistlib.load(file).get("CFBundleShortVersionString")
    except (OSError, plistlib.InvalidFileException, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) else None


class StateUnknown(ValueError):
    """The app's state file has a shape UM-Codex doesn't know."""


def _expect(value: object, kind: type, key: str) -> None:
    if value is not None and not isinstance(value, kind):
        raise StateUnknown(key)


def seeded_state(
    state: dict, setup: Setup, *, seen_models: Iterable[str] = (), now: float | None = None
) -> dict:
    """`state` with the setup's host added and switched on, its project
    (/work, named after the setup) made and selected, and the first-run
    onboarding and the given models' announcements marked as seen. Raises
    StateUnknown for a shape it doesn't know."""
    import uuid

    now = time.time() if now is None else now
    state = json.loads(json.dumps(state))  # a copy
    host, project, name = host_id(setup.id), project_id(setup.id), alias(setup.id)
    for key, kind in (
        ("codex-managed-remote-connections", list),
        ("remote-connection-auto-connect-by-host-id", dict),
        ("remote-connection-analytics-id-by-host-id", dict),
        ("remote-projects", list),
        ("project-order", list),
        ("selected-project", dict),
        (ATOMS, dict),
    ):
        _expect(state.get(key), kind, key)
    analytics = state.setdefault("remote-connection-analytics-id-by-host-id", {})
    analytics_id = analytics.setdefault(host, str(uuid.uuid4()))
    connections = state.setdefault("codex-managed-remote-connections", [])
    if not any(isinstance(c, dict) and c.get("hostId") == host for c in connections):
        connections.append(
            {
                "hostId": host,
                "displayName": name,
                "source": "discovered",
                "alias": name,
                "hostname": None,
                "sshPort": None,
                "identity": None,
                "connectionAnalyticsId": analytics_id,
            }
        )
    state.setdefault("remote-connection-auto-connect-by-host-id", {})[host] = True
    projects = state.setdefault("remote-projects", [])
    mine = next(
        (
            p
            for p in projects
            if isinstance(p, dict) and p.get("hostId") == host and p.get("remotePath") == "/work"
        ),
        None,
    )
    if mine is None:
        mine = {"id": project, "hostId": host, "remotePath": "/work", "label": setup.name}
        projects.append(mine)
    order = state.setdefault("project-order", [])
    if mine["id"] not in order:
        order.insert(0, mine["id"])
    state["selected-project"] = {"type": "remote", "projectId": mine["id"]}
    state.setdefault("desktop-first-seen-at-ms", int(now * 1000))
    atoms = state.setdefault(ATOMS, {})
    # The welcome flow is skipped once this is true (app-initial's route);
    # the person's role isn't answered for them.
    atoms["electron:onboarding-projectless-completed"] = True
    atoms.setdefault("electron:onboarding-hide-first-new-thread-promos", True)
    atoms.setdefault("chatgpt-migration-announcement-completed-v1", True)
    seen = atoms.setdefault("seen-model-upgrade-list", [])
    if not isinstance(seen, list):
        raise StateUnknown("seen-model-upgrade-list")
    seen.extend(m for m in seen_models if m not in seen)
    sidebar = atoms.setdefault("unified-sidebar-project-order-v1", [])
    if isinstance(sidebar, list) and f"codex:project:{mine['id']}" not in sidebar:
        sidebar.insert(0, f"codex:project:{mine['id']}")
    return state


def read_state(home: Path) -> dict:
    """The copy's state file (its backup if the file itself doesn't parse,
    as the app does); {} when there's none yet."""
    for path in (home / GLOBAL_STATE, home / f"{GLOBAL_STATE}.bak"):
        if not path.exists():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
        raise StateUnknown("the state file isn't a JSON object")
    return {}


def seed_copy(home: Path, setup: Setup, *, seen_models: Iterable[str] = ()) -> None:
    """Write the seeded state (the file and its backup, as the app does).
    Only while the copy isn't running. Raises StateUnknown or OSError."""
    text = json.dumps(seeded_state(read_state(home), setup, seen_models=seen_models))
    for path in (home / GLOBAL_STATE, home / f"{GLOBAL_STATE}.bak"):
        _replace(path, text.encode("utf-8"), mode=0o644)


def bundled_catalog(
    app: Path, home: Path, model: str, run: Runner = subprocess.run
) -> tuple[str | None, list[str]]:
    """The copy's own model catalog (the app's bundled Codex's list, with no
    upgrade offers or announcements: codex_config.model_catalog), and the
    models it would announce, to mark as seen. (None, []) if it can't be read."""
    from umcodex.codex_config import model_catalog

    codex = app / "Contents" / "Resources" / "codex-cli" / "bin" / "codex"
    try:
        done = run(
            [str(codex), "debug", "models", "--bundled"],
            capture_output=True, text=True, timeout=60, check=False,
            env={"CODEX_HOME": str(home), "HOME": str(home), "PATH": "/usr/bin:/bin"},
            stdin=subprocess.DEVNULL,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None, []
    if done.returncode != 0:
        return None, []
    try:
        entries = json.loads(done.stdout)["models"]
        announced = [e["slug"] for e in entries if isinstance(e, dict) and e.get("availability_nux")]
    except (ValueError, KeyError, TypeError):
        return None, []
    return model_catalog(done.stdout, [], model), announced


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
    local_chats: bool = LOCAL_CHATS
    labels: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        self.labels = ((SSH_LABEL, self.setup_id),)

    def __call__(self, running) -> int:  # running: launch.Running
        from umcodex.launch import update_launch_app

        spec, setup = running.spec, running.setup
        name = alias(setup.id)
        self.say("Preparing the sandbox for the Codex app...")
        public = ensure_key(setup.id, run=self.run)
        write_config(self.proxy_for, setup_ids={*_saved_setup_ids(), setup.id})
        prepare_container(self.docker, spec.agent, public)
        responder = LocalChatsServer(self.data)
        if not self.local_chats:
            responder.ensure()
        copy_open = self.app is not None and running_copy(self.data, self.run) is not None
        seen = self._write_copy_files(running.relay_port, running.token, setup, responder)
        seeded = False
        if self.app is not None and not copy_open:
            seeded = self._seed(setup, seen)
        connected_once = connected_before(setup.id, self.data)
        state = {
            "alias": name,
            "connected": False,
            # The steps show at once only when UM-Codex couldn't set the copy
            # up itself and the host hasn't connected before.
            "first_time": not connected_once and not seeded,
            "seeded": seeded,
            "steps": first_steps(setup.id, setup.name),
            "notes": notes(setup.id, local_chats=self.local_chats),
            "copy": "not-opened",
        }
        token_file = app_folder(self.data) / "launch-token"
        try:
            state["copy"] = self._open_copy(setup.id, link=not seeded and not connected_once)
            update_launch_app(running.folder, state)
            self._say_ready(name, state)
            return self._wait(running, state, responder)
        except KeyboardInterrupt:
            self.say("")
            self.say("Ending the launch...")
            return 0
        finally:
            responder.stop()
            # Only this launch's token (another launch may have written its own since).
            with contextlib.suppress(OSError):
                if token_file.read_text(encoding="utf-8") == running.token:
                    token_file.unlink()

    def _seed(self, setup: Setup, seen: list[str]) -> bool:
        """The host, its project and the pop-ups seen, in the copy's state
        file (the copy isn't running). False, and nothing changed, if the
        file's shape isn't one UM-Codex knows."""
        home, _ = copy_paths(self.data)
        version = app_version(self.app)
        if version is not None and not version.startswith(TESTED_APP_VERSIONS):
            log.info("Codex app %s: not a version the copy's set-up was checked with; trying it", version)
        try:
            seed_copy(home, setup, seen_models=seen)
        except (StateUnknown, OSError) as error:
            log.warning("the Codex app copy's state couldn't be set up (%s); showing the steps", error)
            return False
        log.info("the Codex app copy is set up for %s (app %s)", alias(setup.id), version)
        return True

    def _write_copy_files(
        self, relay_port: int, token: str, setup: Setup, responder: LocalChatsServer
    ) -> list[str]:
        """The copy's config.toml (and its model catalog). Returns the models
        the app would announce, to mark as seen."""
        home, user_data = copy_paths(self.data)
        for folder in (app_folder(self.data), home, user_data):
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        token_file = app_folder(self.data) / "launch-token"
        if self.local_chats:
            _private_write(token_file, token)
        else:
            token_file.unlink(missing_ok=True)  # from a copy that allowed local chats
        catalog_path, announced = None, []
        if self.app is not None:
            catalog, announced = bundled_catalog(self.app, home, setup.model, run=self.run)
            if catalog is not None:
                catalog_path = app_folder(self.data) / "models.json"
                _private_write(catalog_path, catalog)
        config = home / "config.toml"
        existing = ""
        if config.exists():
            try:
                existing = config.read_text(encoding="utf-8")
                tomllib.loads(existing)
            except (UnicodeDecodeError, tomllib.TOMLDecodeError):
                aside = config.with_name(f"config.toml.bad-{time.strftime('%Y%m%d-%H%M%S')}")
                os.replace(config, aside)
                log.warning("the Codex app copy's config.toml didn't parse; moved it to %s", aside)
                existing = ""
        text = local_config(
            existing,
            relay_port if self.local_chats else local_chats_port(self.data),
            setup.model,
            setup_alias=alias(setup.id),
            token_file=token_file if self.local_chats else None,
            local_chats=self.local_chats,
            catalog=catalog_path,
        )
        _private_write(config, text)
        return announced

    def _open_copy(self, setup_id: str, *, link: bool) -> str:
        if self.app is None:
            return "not-opened"
        pid = running_copy(self.data, self.run)
        if pid is not None:
            return "brought-forward" if bring_forward(pid, self.run) else "already-open"
        # The add link only when UM-Codex couldn't set the copy up and the
        # host never connected: it adds the host switched off, so later it
        # would switch off a host that's on.
        done = self.run(
            open_command(self.app, self.data, deep_link(setup_id) if link else None),
            capture_output=True,
            timeout=60,
            check=False,
        )
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
        elif state.get("seeded"):
            self.say(f"UM-Codex's Codex window opens on this setup's project, connected to {name}.")
            self.say(POPUP_NOTE)
        else:
            self.say(f"The Codex app reconnects to {name} by itself.")
        self.say("")
        for line in state["notes"]:
            self.say(line)
        self.say("")
        self.say("The sandbox runs until you stop it (Stop in UM-Codex, or Ctrl-C here).")
        with contextlib.suppress(OSError, ValueError):
            sys.stdout.flush()

    def _wait(self, running, state: dict, responder: LocalChatsServer | None = None) -> int:
        from umcodex.launch import update_launch_app

        agent = running.spec.agent
        missing = 0
        while True:
            # Twice in a row: a Docker that's slow to answer once isn't a stop.
            missing = 0 if self.docker.running(agent) else missing + 1
            if responder is not None and not self.local_chats:
                with contextlib.suppress(OSError, RuntimeError):
                    responder.ensure()  # takes the port over if the process that had it ended
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


# The installers' question (`um-codex ssh-include`), short: the reason in plain words.
INCLUDE_QUESTION_LINES = (
    "The Codex app (in ChatGPT's desktop app) reaches UM-Codex's sandbox through your ssh",
    "settings. That needs one line at the top of ~/.ssh/config: Include ~/.ssh/um-codex/config",
    "(your file is backed up first, nothing else in it changes, and uninstalling takes it out).",
)
INCLUDE_LATER = "UM-Codex asks again the first time you open a setup in the Codex app."
# A "no" at the installers' question, kept so another install doesn't ask
# again (`um-codex ssh-include --ask-again` does).
INCLUDE_DECLINED = "ssh-include-declined"


def offer_include(
    ask: Callable[[str], str],
    say: Say,
    *,
    home: Path | None = None,
    platform: str = sys.platform,
    find: Callable[[], Path | None] | None = None,
    data: Path | None = None,
    ask_again: bool = False,
) -> int:
    """The installers' one question about the Include line, so the launcher
    needn't ask it: asked only on a Mac with the Codex app installed and the
    line not there yet, default yes. No answer (no terminal) adds nothing:
    the consent must be the person's. A "no" is kept (in the data folder),
    so it isn't asked at the next install unless `ask_again`. 0: the line is
    there (or isn't needed here), 1: not added."""
    if platform != "darwin":
        return 0  # "Codex app" isn't offered here (unavailable_reason)
    if include_present(home):
        say("The Codex app's line in ~/.ssh/config is there already.")
        return 0
    found = (find or (lambda: find_app(platform=platform, home=home)))()
    if found is None:
        say(f"The Codex app isn't installed, so nothing was changed for it. {INCLUDE_LATER}")
        return 0
    declined = (data or data_dir()) / INCLUDE_DECLINED
    if declined.exists() and not ask_again:
        say(
            "The Codex app's line in ~/.ssh/config: you said no before, so it wasn't asked again "
            f"(um-codex ssh-include --ask-again asks). {INCLUDE_LATER}"
        )
        return 1
    for line in INCLUDE_QUESTION_LINES:
        say(line)
    try:
        answer = ask("Add that line now? [Y/n] ").strip().lower()
    except EOFError:
        say(f"No answer, so nothing was changed. {INCLUDE_LATER}")
        return 1
    if answer not in ("", "y", "yes"):
        with contextlib.suppress(OSError):
            declined.parent.mkdir(parents=True, exist_ok=True)
            declined.write_text("no\n", encoding="utf-8")
        say(f"Nothing was changed. {INCLUDE_LATER}")
        return 1
    declined.unlink(missing_ok=True)
    try:
        result = add_include(home)
    except (OSError, UnicodeDecodeError):
        say(
            f"~/.ssh/config couldn't be changed (it may not be plain text), so it was left alone. "
            f"{INCLUDE_LATER}"
        )
        return 1
    done = {"created": "made, with that one line", "added": "the line was added"}
    done = done.get(result, "the line is there")
    say(f"~/.ssh/config: {done} (a backup, if it had anything in it: ~/.ssh/{BACKUP_NAME}).")
    return 0


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
