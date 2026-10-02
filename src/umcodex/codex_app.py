"""M6, "Open in: Codex app": the Codex desktop app as the front end of a
launch, with every file, command and model call inside the container.

Design: docs/DESIGN.md (M6), from the spike of 2026-10-01
(docs/spikes/2026-10-01-codex-desktop-app.md and its hands-on results). The
app ("ChatGPT.app", bundle id com.openai.codex) reaches a container through
its SSH "Connections":

- **Per setup, a stable ssh host** `umcodex-<setup id>` (another data
  folder's, such as a development copy's, adds its install id), in
  UM-Codex's own ssh config file `~/.ssh/um-codex/config`, which is every
  data folder's `installs/<id>/hosts` together; each data folder keeps a key
  pair per setup in its own `installs/<id>` (0700, keys 0600). Its `ProxyCommand` is `um-codex ssh-proxy
  <setup>` (absolute paths), which runs `docker exec -i -u root <agent>
  /usr/sbin/sshd -i` for that one connection: nothing listens, and it works
  with the internet off.
- **One line at the very top of `~/.ssh/config`**, `Include
  ~/.ssh/um-codex/config` (the app follows only top-level Includes), added
  only with the person's consent, after a backup. `um-codex uninstall`
  removes it once no other data folder has hosts there.
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

Windows (experimental, codex_app_windows): the ssh side uses Windows
OpenSSH, and the copy is the Store package's ChatGPT.exe started with its
own CODEX_HOME and profile (`windows_open`). Checked hands-on on 2026-10-02;
`WINDOWS_COPY` switches it.
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

from umcodex import chrome_link, locks
from umcodex import codex_app_windows as win
from umcodex.containers import APP, APP_LABEL, INSTANCE_LABEL, Docker, DockerError, instance_of
from umcodex.paths import data_dir, default_data_dir
from umcodex.setups import SETUP_ID, Setup

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

# Windows (codex_app_windows): the copy is the package's ChatGPT.exe run
# directly, with its own CODEX_HOME and profile; experimental. The maintainer
# agreed to that way of starting it, and the hands-on test on a Windows 11
# laptop passed (2026-10-02, app 26.928.4866.0), so it's on. False turns it
# off again ("Mac only, for now"); UMCODEX_WINDOWS_CODEX_APP=1 then turns it
# on for a test.
WINDOWS_COPY = True
# How long the launch waits for the Windows copy to connect to the sandbox
# before it stops the copy and says to use Terminal: when the copy was set up
# (seeded) or has connected before, and when the person has the first steps
# to do by hand.
WINDOWS_CONNECT_SECONDS = 180.0
WINDOWS_STEPS_SECONDS = 900.0
WINDOWS_START_CHECKS = 15  # looks for the started copy, poll_seconds apart
# What the launch (and the setup's card) says when the Windows copy didn't
# connect or start, by what became of the copy.
_USE_TERMINAL = "The Codex app on Windows is experimental: use Open in: Terminal for this setup."
WINDOWS_FALLBACKS = {
    "stopped": "The Codex app didn't connect to the sandbox, so UM-Codex closed its Codex window and "
    "stopped the sandbox. " + _USE_TERMINAL,
    "shared": "The Codex app didn't connect to this setup's sandbox, so UM-Codex stopped it. Its Codex "
    "window stays open for your other setup running there. " + _USE_TERMINAL,
    "still-open": "The Codex app didn't connect to the sandbox, so UM-Codex stopped the sandbox, but "
    "couldn't close its Codex window: close it yourself (the second ChatGPT icon in the taskbar). "
    + _USE_TERMINAL,
    "not-started": "UM-Codex's Codex window didn't open, so UM-Codex stopped the sandbox. " + _USE_TERMINAL,
    "already-open": "The Codex app didn't connect to the sandbox, so UM-Codex stopped this setup's sandbox. "
    "Its Codex window was already open, and stays open (another setup may be using it). " + _USE_TERMINAL,
}
WINDOWS_FALLBACK = WINDOWS_FALLBACKS["stopped"]
WINDOWS_NOTES = (
    "On Windows the Codex app is experimental. UM-Codex's Codex window runs without the app's "
    "Windows sandbox and Computer Use; work in Remote chats runs in UM-Codex's sandbox instead.",
    "UM-Codex's Codex window may download an app component update in the background (about 1 GB) "
    "the first time.",
)
# A runtime download under way (codex_app_windows.runtime_update_running) puts
# the fallback off, by up to this much, so it isn't left half done.
WINDOWS_UPDATE_GRACE_SECONDS = 1200.0


def windows_enabled() -> bool:
    return WINDOWS_COPY or os.environ.get("UMCODEX_WINDOWS_CODEX_APP") == "1"


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


def plain_alias_folder() -> Path:
    """The data folder whose hosts keep the plain alias `umcodex-<setup>`:
    the installed copy's (tests point it at their own)."""
    return default_data_dir()


def _same_folder(a: Path, b: Path) -> bool:
    return os.path.realpath(a) == os.path.realpath(b)


def alias(setup_id: str, data: Path | None = None) -> str:
    """The ssh host name the app shows for a setup. Stable per setup: the app
    keeps its switch, projects and chats by this name. Unique on this
    computer: every UM-Codex data folder's hosts are in the one ssh config,
    so another data folder's (a development copy's) carry its install id,
    `umcodex-<setup>_<id>` (a setup id never has `_`); the installed copy's
    keep the plain `umcodex-<setup>` they've always had."""
    data = data or data_dir()
    if _same_folder(data, plain_alias_folder()):
        return ALIAS_PREFIX + setup_id
    return f"{ALIAS_PREFIX}{setup_id}_{install_id(data)[:8]}"


OTHER_CHATS = {
    True: "Other chats in that Codex window run on this computer, not in the sandbox, and work only "
    "while a setup is running.",
    False: "Other (local) chats in that Codex window would run on this computer, outside the sandbox, "
    "so they're blocked: they only answer with that reminder.",
}


def notes(
    setup_id: str, *, local_chats: bool | None = None, data: Path | None = None, platform: str = sys.platform
) -> list[str]:
    other = OTHER_CHATS[LOCAL_CHATS if local_chats is None else local_chats]
    lines = [note.format(alias=alias(setup_id, data), other=other) for note in APP_NOTES]
    return [*lines, *WINDOWS_NOTES] if platform == "win32" else lines


def second_icon(platform: str = sys.platform) -> str:
    """Where the person finds UM-Codex's copy of the app."""
    place = "taskbar" if platform == "win32" else "Dock"
    return f"a second ChatGPT icon in the {place}"


def first_steps(
    setup_id: str, project: str, data: Path | None = None, platform: str = sys.platform
) -> list[str]:
    """What the person does once per setup when UM-Codex couldn't set the
    copy up itself (it was already open, or the app's format changed), in
    UM-Codex's Codex window: the flow the GUI test found (app 26.928)."""
    name = alias(setup_id, data)
    return [
        f"Switch to UM-Codex's Codex window ({second_icon(platform)}).",
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
    """~/.ssh/um-codex: shared by every UM-Codex data folder on this computer
    (the installed copy's, a development copy's): `config` is all of their
    hosts together; each one's own files are in `installs/<install id>`."""
    return ssh_dir(home) / "um-codex"


def install_id(data: Path | None = None) -> str:
    """A data folder's id on this computer (the launches' instance label)."""
    return instance_of(data or data_dir())


def installs_dir(home: Path | None = None) -> Path:
    return own_ssh_dir(home) / "installs"


def install_ssh_dir(home: Path | None = None, data: Path | None = None) -> Path:
    """This data folder's own ssh files: its keys, `hosts` (its Host blocks)
    and `owner` (the data folder's path, so another one can tell when it's
    gone)."""
    return installs_dir(home) / install_id(data)


def key_path(setup_id: str, home: Path | None = None, data: Path | None = None) -> Path:
    return install_ssh_dir(home, data) / f"{setup_id}_ed25519"


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


def _is_the_persons_ssh(home: Path | None) -> bool:
    """Whether ssh_dir(home) is the ~/.ssh Windows' ssh itself reads."""
    profile = os.environ.get("USERPROFILE")
    if not profile:
        return False
    with contextlib.suppress(OSError):
        return os.path.samefile(ssh_dir(home), Path(profile) / ".ssh")
    return False


SSH_DIR_MADE = "made-ssh-folder"  # in ~/.ssh/um-codex: UM-Codex made ~/.ssh itself


def _made_ssh_dir(home: Path | None) -> None:
    with contextlib.suppress(OSError):
        own_ssh_dir(home).mkdir(parents=True, exist_ok=True)
        (own_ssh_dir(home) / SSH_DIR_MADE).write_text("yes\n", encoding="utf-8")


def _remove_owner_rights(folder: Path, run: Runner, sid: str) -> bool:
    """One folder with PYTHON_0700's rules: the person, SYSTEM and
    Administrators given full rights first (nothing inherited, as before),
    then OWNER RIGHTS taken out; never the other way round, so the person
    always keeps their access. True if both went through."""
    if not _windows_owner_only(folder, folder=True, run=run, sid=sid):
        return False
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        done = run(
            [str(win.system_dir() / "icacls.exe"), str(folder), "/remove:g", "*S-1-3-4", "/Q"],
            capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL, creationflags=win.hidden(),
        )  # fmt: skip
        return done.returncode == 0
    return False


_repair_checked = False  # repair_ssh_dir runs once per process from _locked (it's only for old folders)


def _check_repair(home: Path | None) -> None:
    global _repair_checked
    _repair_checked = True
    repair_ssh_dir(home)


def repair_ssh_dir(
    home: Path | None = None, run: Runner = subprocess.run, platform: str = sys.platform
) -> bool:
    """Windows: folders an earlier UM-Codex made with Python 3.13's
    mkdir(mode=0o700) (win.PYTHON_0700: SYSTEM, Administrators and OWNER
    RIGHTS only, protected) make ssh refuse what's in them. Repaired, one
    folder at a time (never /T: a protected folder below would be left
    without the person): ~/.ssh only if UM-Codex's note says it made it
    (SSH_DIR_MADE), and UM-Codex's own folders under ~/.ssh/um-codex
    (it, installs, each install's) wherever they have exactly those rules.
    Each gets the person, SYSTEM and Administrators first, then loses OWNER
    RIGHTS. True if anything was repaired."""
    if platform != "win32" or not ssh_dir(home).is_dir():
        return False
    own = own_ssh_dir(home)
    folders = [ssh_dir(home)] if (own / SSH_DIR_MADE).is_file() else []
    if own.is_dir():
        folders.append(own)
        with contextlib.suppress(OSError):
            folders.extend(sorted(p for p in own.rglob("*") if p.is_dir() and not p.is_symlink()))
    folders = [folder for folder in folders if win.owner_rights_only(folder, run)]
    if not folders:
        return False
    sid = _windows_user_sid()
    if sid is None:
        log.warning("couldn't find this account's SID, so %s wasn't repaired", folders[0])
        return False
    repaired = False
    for folder in folders:  # the top first: the person can then reach what's below
        if _remove_owner_rights(folder, run, sid):
            log.info("repaired %s's permissions (OWNER RIGHTS taken out)", folder)
            repaired = True
        else:
            log.warning("couldn't repair %s's permissions", folder)
    return repaired


def add_include(
    home: Path | None = None, *, platform: str = sys.platform, run: Runner = subprocess.run
) -> str:
    """Put the Include line at the very top of ~/.ssh/config, after backing
    the file up (the backup is refreshed whenever it no longer matches the
    file as it is before the line goes in). The file keeps its line endings,
    is replaced atomically, and a link to it keeps working. It keeps its
    permissions: on a Mac its mode; on Windows its access rules (which the
    replacement, a new file, wouldn't otherwise have), given to the backup
    too, and then Windows' ssh is asked whether it still reads the file: if
    not, the file is put back as it was and SshPermissionsError raised.
    Returns "created", "added" or "already there". Raises OSError (also
    SshPermissionsError) or UnicodeDecodeError (a file that isn't text) and
    changes nothing."""
    folder = ssh_dir(home)
    config = folder / "config"
    if platform == "win32":
        repair_ssh_dir(home, run, platform)
    if not config.exists():
        # ~/.ssh keeps the permissions it has if it's there; made here, it's set as ssh wants.
        made = not folder.is_dir()
        _ssh_mkdir(folder, parents=True, platform=platform, own=made)
        if made and platform == "win32":  # what repair_ssh_dir may change; not needed on a Mac
            _made_ssh_dir(home)
        _ssh_write(config, INCLUDE_LINE + "\n", platform=platform)
        return "created"
    data = _read(config)
    text = data.decode("utf-8")
    if INCLUDE_LINE in _top_lines(text):
        return "already there"
    rules = win.access_rules(config, run) if platform == "win32" else None
    backup = folder / BACKUP_NAME
    if not backup.exists() or _read(backup) != data:
        _replace(backup, data, mode=_mode(config))
        if rules:
            win.set_access_rules(backup, rules, run)
    newline = "\r\n" if "\r\n" in text else "\n"
    _replace(config, (INCLUDE_LINE + newline + text).encode("utf-8"), mode=_mode(config))
    if rules:
        win.set_access_rules(config, rules, run)
    if platform == "win32" and _is_the_persons_ssh(home) and (said := win.ssh_refuses_config(run)):
        _replace(config, data, mode=_mode(config))
        restored = not rules or win.set_access_rules(config, rules, run)
        log.warning("ssh refused ~/.ssh/config after the Include line went in (%s); put back as it was", said)
        if not restored:
            log.error("~/.ssh/config was put back, but its permissions couldn't be")
        raise SshPermissionsError(config, restored=restored)
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


def proxy_command(setup_id: str, data: Path | None = None) -> list[str]:
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
    # Development and tests only: the installed copy's data folder is the default.
    if os.environ.get("UMCODEX_DATA_DIR") or (
        data is not None and not _same_folder(data, default_data_dir())
    ):
        command += ["--data-dir", str(data or data_dir())]
    return command


def host_block(setup_id: str, proxy: Sequence[str], data: Path | None = None) -> str:
    """One Host for a setup. Everything ssh needs is here: the app adds only
    BatchMode, timeouts and keep-alives to its ssh commands. The Include is
    the first line of ~/.ssh/config, so these values win (ssh keeps the first
    value it reads for each option); options set only in the person's own
    `Host *` (LocalForward, DynamicForward and the like) still apply, though
    the container's sshd allows only local forwards to its own localhost."""
    name = alias(setup_id, data)
    return "\n".join(
        [
            f"Host {name}",
            # Never used: the ProxyCommand reaches the container through Docker.
            f"  HostName {name}.invalid",
            "  User agent",
            f"  IdentityFile ~/.ssh/um-codex/installs/{install_id(data)}/{setup_id}_ed25519",
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


INSTALL_ID = re.compile(r"[0-9a-f]{16}")
OWNER = "owner"  # in an install's folder: its data folder's path
HOSTS = "hosts"  # in an install's folder: its Host blocks
LOCK = ".lock"  # in ~/.ssh/um-codex: held around every change there
MISSING = "missing.json"  # in ~/.ssh/um-codex: since when each gone data folder has been gone
# How long a data folder that's definitively gone keeps its ssh folder (its
# Hosts leave the config at once). Its keys open only its own sandboxes and
# are made anew at its next launch, so nothing is lost by removing them; the
# wait is for a folder put back (restored from a backup, moved back), and
# keeps ~/.ssh from collecting private keys of throwaway development folders.
GRACE_SECONDS = 30 * 24 * 3600

# Up to 0.1.0a3 every data folder kept its keys straight in ~/.ssh/um-codex
# ("flat"), and each launch rewrote `config` with only its own hosts and
# removed the keys it didn't know: another data folder's.
_BLOCK_LINE = re.compile(r"(?i)\s*(host|match)(\s*=|\s)")
_FLAT_KEY = re.compile(
    r"(?im)^\s*IdentityFile[\s=]+~/\.ssh/um-codex/([A-Za-z0-9][A-Za-z0-9_.-]{0,127})_ed25519\s*$"
)
_PROXY_LINE = re.compile(r"(?im)^\s*ProxyCommand[\s=]+(.*)$")
_HOST_NAMES = re.compile(r"(?i)\s*host(?:\s*=\s*|\s+)(.*)")


def _now() -> float:
    return time.time()


def _keys_in(folder: Path) -> list[str]:
    if not folder.is_dir():
        return []
    found = [p.name.removesuffix("_ed25519") for p in folder.glob("*_ed25519") if p.is_file()]
    return sorted(s for s in found if SETUP_ID.fullmatch(s))


def known_setups(home: Path | None = None, data: Path | None = None) -> list[str]:
    """This data folder's setups that have a key (each was opened in the app once)."""
    return _keys_in(install_ssh_dir(home, data))


def app_setups(data: Path | None = None) -> list[Setup]:
    """The data folder's saved setups that open in the Codex app (in the
    sandbox; not those that run on this computer)."""
    from umcodex.setups import SetupStore

    store = SetupStore() if data is None else SetupStore(path=data / "setups.toml")
    return [s for s in store.all() if s.open_in == "codex-app" and not s.on_this_computer]


def copy_knows(setup_id: str, data: Path | None = None) -> bool | None:
    """Whether UM-Codex's copy has the setup's host and project in its state;
    None when that can't be told (the file can't be read or has another shape)."""
    home, _ = copy_paths(data)
    if not any((home / name).exists() for name in (GLOBAL_STATE, f"{GLOBAL_STATE}.bak")):
        return False
    try:
        state = read_state(home)
    except (StateUnknown, OSError):
        return None
    if not state:
        return None  # there, but neither the file nor its backup could be read
    host = host_id(setup_id, data)
    connections = state.get("codex-managed-remote-connections")
    projects = state.get("remote-projects")
    return (
        isinstance(connections, list)
        and any(isinstance(c, dict) and c.get("hostId") == host for c in connections)
        and isinstance(projects, list)
        and any(isinstance(p, dict) and p.get("hostId") == host for p in projects)
    )


def _saved_setup_ids(data: Path | None = None) -> set[str]:
    from umcodex.setups import SetupStore

    store = SetupStore() if data is None else SetupStore(path=data / "setups.toml")
    return {setup.id for setup in store.all()}


# Windows: what OpenSSH accepts for its files is the person, SYSTEM and
# Administrators. Python 3.13's mkdir(mode=0o700) gives a folder SYSTEM,
# Administrators and OWNER RIGHTS instead, and ssh.exe refuses a config file
# with OWNER RIGHTS ("Bad permissions"): through the Include line, every host
# in ~/.ssh/config then fails (found on a Windows laptop, 2026-10-02). What a
# new file inherits also depends on the account (an administrator's, on CI,
# still got OWNER RIGHTS), so UM-Codex's own ssh folders and files are given
# exactly those three, not inherited, with icacls.
_SYSTEM_SID = "S-1-5-18"
_ADMINISTRATORS_SID = "S-1-5-32-544"


class SshPermissionsError(OSError):
    """Windows: a file or folder ssh reads couldn't be given the permissions
    OpenSSH accepts. Nothing is left that would break the person's ssh."""

    def __init__(self, path: Path, *, restored: bool = True) -> None:
        if restored:
            said = (
                f"UM-Codex couldn't set the permissions Windows' ssh needs on {path}, so it stopped there "
                "(your own ssh settings weren't changed). Use Open in: Terminal for now."
            )
        else:
            said = (
                f"UM-Codex couldn't set the permissions Windows' ssh needs on {path}. It put the file's "
                'contents back as they were, but not its permissions: if ssh now says "Bad permissions", '
                f"restore them from {path.name}.um-codex-backup's or ask for help. "
                "Use Open in: Terminal for now."
            )
        super().__init__(said)
        self.path = path


_sid: str | None = None  # the person's SID, once found (a failure isn't kept)


def _windows_user_sid(run: Runner = subprocess.run) -> str | None:
    """The person's SID (whoami /user), or None if Windows can't say now."""
    global _sid
    if _sid is not None:
        return _sid
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        done = run(
            [str(win.system_dir() / "whoami.exe"), "/user", "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL, creationflags=win.hidden(),
        )  # fmt: skip
        sid = done.stdout.strip().split(",")[-1].strip().strip('"')
        if done.returncode == 0 and sid.startswith("S-1-"):
            _sid = sid
            return sid
    return None


def _windows_owner_only(
    path: Path, *, folder: bool, run: Runner = subprocess.run, sid: str | None = None
) -> bool:
    """Windows: `path` readable by the person, SYSTEM and Administrators only,
    and not inheriting anything else (a folder hands the same down). False
    if that couldn't be done."""
    sid = sid or _windows_user_sid()
    if sid is None:
        log.warning("couldn't find this account's SID, so %s's permissions weren't set", path)
        return False
    flags = "(OI)(CI)F" if folder else "F"
    who = (sid, _SYSTEM_SID, _ADMINISTRATORS_SID)
    grants = [part for one in who for part in ("/grant:r", f"*{one}:{flags}")]
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        done = run(
            [str(win.system_dir() / "icacls.exe"), str(path), "/inheritance:r", *grants, "/Q"],
            capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL, creationflags=win.hidden(),
        )  # fmt: skip
        if done.returncode == 0:
            return True
        log.warning("icacls couldn't set %s's permissions: %s", path, (done.stdout or done.stderr).strip())
    return False


def _ssh_mkdir(
    folder: Path, *, parents: bool = False, platform: str = sys.platform, own: bool = True
) -> None:
    """Make a folder for ssh's files. On Windows without a mode (see above),
    and, if it's UM-Codex's own (`own`), with only the person, SYSTEM and
    Administrators; raises SshPermissionsError if that can't be done."""
    if platform == "win32":
        folder.mkdir(parents=parents, exist_ok=True)
        if own and not _windows_owner_only(folder, folder=True):
            raise SshPermissionsError(folder)
    else:
        folder.mkdir(mode=0o700, parents=parents, exist_ok=True)


def _ssh_write(path: Path, text: str, *, platform: str = sys.platform) -> None:
    """_private_write for a file ssh reads, with Windows' permissions set too.
    If they can't be, the file is taken away again (ssh skips an Include
    that matches nothing, but refuses one it can't trust, and with it every
    host) and SshPermissionsError is raised."""
    _private_write(path, text)
    if platform == "win32" and not _windows_owner_only(path, folder=False):
        path.unlink(missing_ok=True)
        raise SshPermissionsError(path)


def _private_dir(folder: Path) -> None:
    """A folder only the person can open (its parent must be there)."""
    _ssh_mkdir(folder)
    with contextlib.suppress(OSError):
        os.chmod(folder, 0o700)


@contextlib.contextmanager
def _locked(home: Path | None = None):
    """~/.ssh/um-codex's lock: every process of every data folder takes it
    before changing anything there. ~/.ssh is made (0700) if it isn't there;
    one that is keeps its own permissions."""
    ssh = ssh_dir(home)
    if not ssh.is_dir():
        _private_dir(ssh)
        if sys.platform == "win32":
            _made_ssh_dir(home)
    elif sys.platform == "win32" and not _repair_checked:
        _check_repair(home)
    _private_dir(own_ssh_dir(home))
    with locks.held(own_ssh_dir(home) / LOCK, timeout=30):
        yield


def _own_folder(home: Path | None, data: Path | None) -> Path:
    """This data folder's ssh folder, made (0700) with its `owner` file."""
    data = data or data_dir()
    # It's there, so no other data folder takes it for gone. Its parent must
    # be: nothing is made under an unmounted volume's path on the boot disk.
    data.mkdir(exist_ok=True)
    folder = install_ssh_dir(home, data)
    _private_dir(installs_dir(home))
    _private_dir(folder)
    owner = folder / OWNER
    text = str(Path(os.path.realpath(data))) + "\n"
    try:
        current = owner.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        current = None
    if current != text:
        _ssh_write(owner, text)
    return folder


def _owner_state(owner: Path) -> str:
    """ "present"; "gone", only when that's certain: the folder it was in is
    there and readable, and it isn't; else "unknown" (an unmounted volume, a
    folder that can't be read)."""
    try:
        os.lstat(owner)
        return "present"
    except FileNotFoundError:
        pass
    except OSError:
        return "unknown"
    parent = owner.parent
    if parent == owner or (sys.platform == "darwin" and parent == Path("/Volumes")):
        return "unknown"  # a volume's own mount point
    try:
        if not stat.S_ISDIR(os.stat(parent).st_mode) or not os.access(parent, os.R_OK | os.X_OK):
            return "unknown"
    except OSError:
        return "unknown"
    return "gone"


def _install_state(folder: Path) -> str:
    """The state of the data folder an install's ssh folder belongs to."""
    try:
        owner = Path((folder / OWNER).read_text(encoding="utf-8").strip())
        if not owner.is_absolute() or instance_of(owner) != folder.name:
            return "unknown"
        return _owner_state(owner)
    except (OSError, UnicodeDecodeError, RuntimeError):
        return "unknown"


def _blocks(text: str) -> list[str]:
    """A config's Host and Match blocks, each as written (comments in it too)."""
    blocks: list[list[str]] = []
    for line in text.splitlines():
        if _BLOCK_LINE.match(line):
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)
    return ["\n".join(block).rstrip() + "\n" for block in blocks]


def _host_names(block: str) -> set[str]:
    found = _HOST_NAMES.match(block.splitlines()[0])
    return set(found.group(1).split()) if found else set()


def _flat_owner(block: str) -> Path | None:
    """The data folder an older UM-Codex's Host belongs to, from its
    ProxyCommand: its `--data-dir`, else the installed copy's. None when the
    block doesn't say (it isn't UM-Codex's ssh-proxy)."""
    found = _PROXY_LINE.search(block)
    if not found:
        return None
    try:
        words = [word.replace("%%", "%") for word in shlex.split(found.group(1))]
    except ValueError:
        return None
    if "ssh-proxy" not in words:
        return None
    if "--data-dir" in words[:-1]:
        given = Path(words[words.index("--data-dir") + 1])
        return given if given.is_absolute() else None
    return plain_alias_folder()


def _flat_hosts(home: Path | None) -> list[tuple[str, str, Path | None]]:
    """The Hosts in today's `config` that use a flat key still there, as
    (setup id, block, its data folder or None)."""
    try:
        text = (own_ssh_dir(home) / "config").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    found = []
    for block in _blocks(text):
        key = _FLAT_KEY.search(block)
        if key and (own_ssh_dir(home) / f"{key.group(1)}_ed25519").is_file():
            found.append((key.group(1), block, _flat_owner(block)))
    return found


def _remove_flat_key(home: Path | None, setup_id: str) -> None:
    if SETUP_ID.fullmatch(setup_id):
        flat = own_ssh_dir(home) / f"{setup_id}_ed25519"
        flat.unlink(missing_ok=True)
        flat.with_name(flat.name + ".pub").unlink(missing_ok=True)


def _move_flat_keys(setup_ids: Iterable[str], home: Path | None, data: Path | None) -> None:
    """The flat layout's keys of these (this data folder's saved) setups go
    into its own folder. A flat key of any other setup is left alone: it may
    be another data folder's, run by an older UM-Codex."""
    folder = install_ssh_dir(home, data)
    for setup_id in setup_ids:
        flat = own_ssh_dir(home) / f"{setup_id}_ed25519"
        if not SETUP_ID.fullmatch(setup_id) or not flat.is_file():
            continue
        moved = folder / flat.name
        if moved.exists():
            continue
        public = flat.with_name(flat.name + ".pub")
        os.replace(flat, moved)
        if public.exists():
            os.replace(public, moved.with_name(moved.name + ".pub"))
        log.info("moved the ssh key of %s into %s", setup_id, folder)


def _read_missing(home: Path | None) -> dict[str, float]:
    try:
        value = json.loads((own_ssh_dir(home) / MISSING).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {k: float(v) for k, v in value.items() if isinstance(v, int | float) and INSTALL_ID.fullmatch(k)}


def _install_folders(home: Path | None) -> list[Path]:
    try:
        return sorted(p for p in installs_dir(home).glob("*") if INSTALL_ID.fullmatch(p.name) and p.is_dir())
    except OSError:
        return []


def _write_combined(home: Path | None, keep: str | None = None) -> Path:
    """~/.ssh/um-codex/config: every data folder's `hosts` together (and an
    older UM-Codex's flat ones), written whole. Only with the lock held.
    A data folder that's definitively gone (`_owner_state`) loses its Hosts
    here at once, and its ssh folder after GRACE_SECONDS; one that can't be
    told about (an unmounted volume) keeps both. The app follows Includes
    inside included files too (its bundle, 26.928), but one plain file
    doesn't depend on that, and `ssh -G` reads the same."""
    missing = _read_missing(home)
    still_missing: dict[str, float] = {}
    seen: set[str] = set()
    parts: list[str] = []
    for folder in _install_folders(home):
        try:
            state = "present" if folder.name == keep else _install_state(folder)
            if state == "gone":
                since = missing.get(folder.name, _now())
                if _now() - since >= GRACE_SECONDS:
                    shutil.rmtree(folder, ignore_errors=True)
                    log.info("removed %s: its UM-Codex data folder has been gone for 30 days", folder)
                else:
                    still_missing[folder.name] = since
                    log.info("left out the ssh Hosts of %s: its UM-Codex data folder is gone", folder)
                continue
            text = (folder / HOSTS).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        blocks = []
        for block in _blocks(text):
            names = _host_names(block)
            if names & seen:
                log.warning("left out a second ssh Host %s (from %s)", " ".join(sorted(names)), folder)
                continue
            seen |= names
            blocks.append(block)
        if blocks:
            parts.append(f"# installs/{folder.name}\n" + "\n".join(blocks))
    flat = [
        block
        for _, block, owner in _flat_hosts(home)
        if not (_host_names(block) & seen) and (owner is None or _owner_state(owner) != "gone")
    ]
    if flat:
        parts.append("# From an older UM-Codex (its keys straight in ~/.ssh/um-codex)\n" + "\n".join(flat))
    header = [
        "# Written by UM-Codex; changes here are lost. Every UM-Codex data folder on this computer",
        "# keeps its own Hosts and keys in ~/.ssh/um-codex/installs/<id>/; this file is all of them",
        "# together, rewritten whenever one of them changes. Each Host reaches one setup's sandbox",
        "# while it runs (um-codex ssh-proxy, through Docker).",
        "",
        "",
    ]
    if still_missing != missing:
        if still_missing:
            _ssh_write(own_ssh_dir(home) / MISSING, json.dumps(still_missing) + "\n")
        else:
            (own_ssh_dir(home) / MISSING).unlink(missing_ok=True)
    path = own_ssh_dir(home) / "config"
    _ssh_write(path, "\n".join(header) + "\n".join(parts))
    return path


def write_config(
    proxy_for: Callable[[str], Sequence[str]] | None = None,
    home: Path | None = None,
    setup_ids: Iterable[str] | None = None,
    data: Path | None = None,
) -> Path:
    """This data folder's Hosts (one per saved setup that has a key: in
    `setup_ids`, default the setup store) in its own `hosts`, then
    ~/.ssh/um-codex/config, all data folders' together. Its own keys that
    belong to no saved setup are removed (its flat ones too, known by the
    older UM-Codex's Host for them); another data folder's files are never
    touched, except, after GRACE_SECONDS, all of one whose data folder is gone."""
    data = data or data_dir()
    proxy = proxy_for or (lambda setup_id: proxy_command(setup_id, data))
    saved = set(_saved_setup_ids(data) if setup_ids is None else setup_ids)
    with _locked(home):
        folder = _own_folder(home, data)
        for setup_id, _, owner in _flat_hosts(home):
            if owner is not None and setup_id not in saved and _same_folder(owner, data):
                _remove_flat_key(home, setup_id)
                log.info("removed the flat ssh key of %s, which is no saved setup", setup_id)
        _move_flat_keys(saved, home, data)
        hosts = []
        for setup_id in known_setups(home, data):
            if setup_id in saved:
                hosts.append(setup_id)
                continue
            key = key_path(setup_id, home, data)
            key.unlink(missing_ok=True)
            key.with_name(key.name + ".pub").unlink(missing_ok=True)
            log.info("removed the ssh key of %s, which is no saved setup", setup_id)
        blocks = [host_block(setup_id, proxy(setup_id), data) for setup_id in hosts]
        _ssh_write(folder / HOSTS, "\n".join(blocks))
        return _write_combined(home, keep=folder.name)


def ensure_key(
    setup_id: str, home: Path | None = None, run: Runner = subprocess.run, data: Path | None = None
) -> Path:
    """The setup's key pair (kept between launches; one from the flat layout
    is moved in). Returns the public key's path."""
    if not SETUP_ID.fullmatch(setup_id):
        raise ValueError("unusual setup id")
    with _locked(home):
        _own_folder(home, data)
        _move_flat_keys([setup_id], home, data)
    key = key_path(setup_id, home, data)
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
    # ssh-keygen's own permissions can vary by account: set ours, or stop (ssh would refuse the key).
    if sys.platform == "win32" and not _windows_owner_only(key, folder=False):
        raise SshPermissionsError(key)
    return public


def forget_setup(setup_id: str, home: Path | None = None, data: Path | None = None) -> None:
    """A deleted setup: its key goes (this data folder's, or its flat one), and its Host with it."""
    if not SETUP_ID.fullmatch(setup_id):
        return
    key = key_path(setup_id, home, data)
    flat = own_ssh_dir(home) / key.name
    if not any(p.exists() for p in (key, flat)):
        return
    with _locked(home):
        for path in (key, flat):
            path.unlink(missing_ok=True)
            path.with_name(path.name + ".pub").unlink(missing_ok=True)
    remaining = [other for other in known_setups(home, data) if other != setup_id]
    with contextlib.suppress(OSError, ValueError, TimeoutError):
        write_config(home=home, setup_ids=remaining, data=data)


def remove_ssh_files(
    home: Path | None = None, data: Path | None = None, setup_ids: Iterable[str] | None = None
) -> tuple[list[str], bool]:
    """Uninstall: this data folder's ssh files (its folder, and its flat
    keys: its saved setups', and those whose older Host names this data
    folder). ~/.ssh/um-codex goes too, with any leftover, unless another
    data folder that isn't definitively gone still has a folder there, or
    an older UM-Codex's flat key with its Host; then its config is
    rewritten without this one's Hosts. Returns what was done, in plain
    words, and whether others still use it (then the Include line must stay)."""
    data = data or data_dir()
    folder = own_ssh_dir(home)
    if not folder.exists():
        return [], False
    done: list[str] = []
    try:
        saved = set(_saved_setup_ids(data) if setup_ids is None else setup_ids)
    except (OSError, ValueError):
        saved = set()  # the flat keys' Hosts still tell which are this data folder's
    with _locked(home):
        mine = install_ssh_dir(home, data)
        if mine.exists():
            shutil.rmtree(mine, ignore_errors=True)
            gone = not mine.exists()
            done.append(f"Removed {mine}." if gone else f"Couldn't remove {mine}: delete it yourself.")
        for setup_id in saved:
            _remove_flat_key(home, setup_id)
        others = False
        for setup_id, _, owner in _flat_hosts(home):
            if owner is not None and _same_folder(owner, data):
                _remove_flat_key(home, setup_id)
            elif owner is not None and _owner_state(owner) != "gone":
                others = True  # an older UM-Codex's, still in use
        others = others or any(f != mine and _install_state(f) != "gone" for f in _install_folders(home))
        if others:
            _write_combined(home)
            done.append(f"Kept {folder}: another UM-Codex data folder on this computer still uses it.")
            return done, True
    # After the lock is let go: its file is in the folder, and Windows can't
    # delete a file that's open (found on a Windows laptop, 2026-10-02).
    shutil.rmtree(folder, ignore_errors=True)
    if folder.exists():
        return [f"Couldn't remove {folder}: delete it yourself."], False
    return [f"Removed {folder}."], False


def uninstall_ssh(home: Path | None = None, data: Path | None = None) -> list[str]:
    """`um-codex uninstall`'s ssh part: this data folder's files, and the
    Include line in ~/.ssh/config only when no other data folder needs it."""
    done, others = remove_ssh_files(home, data)
    if others:
        return done + ["Kept the line in ~/.ssh/config, which the other data folder's hosts need."]
    return remove_include(home) + done


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
            f"um-codex ssh-proxy: {alias(setup_id, data)} isn't running. Start it in UM-Codex "
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
    in /Applications or ~/Applications, else wherever Spotlight knows it. On
    Windows, the Store package's ChatGPT.exe."""
    if platform == "win32":
        return win.find_app(run)
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
    if platform == "win32" and not windows_enabled():
        return "The Codex app works with UM-Codex on a Mac only, for now. Use Terminal."
    if platform == "win32":
        if app is None:
            return (
                "The Codex app isn't installed. It's part of OpenAI's ChatGPT desktop app: get it from "
                f"the Microsoft Store ({APP_DOWNLOAD}), then come back. Terminal works in the meantime."
            )
        if not win.openssh_installed():
            return win.OPENSSH_MISSING
        return None
    if platform != "darwin":
        return "The Codex app works with UM-Codex on a Mac only."
    if app is None:
        return (
            "The Codex app isn't installed. It's part of OpenAI's ChatGPT desktop app: get it from "
            f"{APP_DOWNLOAD}, then come back. Terminal works in the meantime."
        )
    return None


def deep_link(setup_id: str, data: Path | None = None) -> str:
    """The documented link that adds the host (switched off) in Settings → Connections."""
    return f"codex://settings/connections/ssh/add?name={alias(setup_id, data)}"


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


def windows_open(
    app: Path, data: Path | None = None, link: str | None = None, environ: dict[str, str] | None = None
) -> tuple[list[str], dict[str, str]]:
    """Windows: the copy's command and environment (codex_app_windows), its
    folders checked first: never the person's own. Raises win.UnsafePaths."""
    home, user_data = copy_paths(data)
    environ = dict(os.environ if environ is None else environ)
    theirs = next((value for key, value in environ.items() if key.upper() == "CODEX_HOME"), None)
    win.check_paths(home, user_data, app_folder(data), user_home(), _app_data(), theirs)
    return win.open_command(app, home, user_data, link, environ)


def _app_data() -> Path | None:
    value = os.environ.get("APPDATA")
    return Path(value) if value else None


def running_copy(
    data: Path | None = None, run: Runner = subprocess.run, platform: str = sys.platform
) -> int | None:
    """The PID of UM-Codex's copy of the app, if it's running: the main
    process whose arguments carry the copy's profile folder."""
    _, user_data = copy_paths(data)
    if platform == "win32":
        return win.find_copy(user_data, run)
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


def bring_forward(pid: int, run: Runner = subprocess.run, platform: str = sys.platform) -> bool:
    """Ask macOS (or Windows) to bring that copy to the front. It may
    decline (an app in the background can't always take focus); the
    launcher then says where it is."""
    if platform == "win32":
        return win.bring_forward(pid, run)
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
    # Chrome control off in this copy: its plugin would take the person's Chrome
    # connection over (chrome_link.py; the launch also keeps their manifest).
    plugins = config.get("plugins")
    plugins = plugins if isinstance(plugins, dict) else {}
    entry = plugins.get("chrome@openai-bundled")
    plugins["chrome@openai-bundled"] = {**(entry if isinstance(entry, dict) else {}), "enabled": False}
    config["plugins"] = plugins
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


def host_id(setup_id: str, data: Path | None = None) -> str:
    return f"remote-ssh-discovered:{alias(setup_id, data)}"


def project_id(setup_id: str, data: Path | None = None) -> str:
    """The setup's project id in the app: stable (a UUID from the alias)."""
    import uuid

    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"um-codex:{alias(setup_id, data)}:/work"))


def app_version(app: Path | None) -> str | None:
    if app is None:
        return None
    if win.is_windows_app(app):  # the package's folder name has it
        return win.version(app)
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
    state: dict,
    setup: Setup,
    *,
    seen_models: Iterable[str] = (),
    now: float | None = None,
    data: Path | None = None,
) -> dict:
    """`state` with the setup's host added and switched on, its project
    (/work, named after the setup) made and selected, and the first-run
    onboarding and the given models' announcements marked as seen. Raises
    StateUnknown for a shape it doesn't know."""
    import uuid

    now = time.time() if now is None else now
    state = json.loads(json.dumps(state))  # a copy
    host, project, name = host_id(setup.id, data), project_id(setup.id, data), alias(setup.id, data)
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
    _forget_old_alias(state, setup, host)
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


def _forget_old_alias(state: dict, setup: Setup, host: str) -> None:
    """This copy's host and project under the setup's plain alias, when its
    alias now has the install id (a development copy's, set up before
    0.1.0a4): that host no longer exists in the ssh config."""
    old = f"remote-ssh-discovered:{ALIAS_PREFIX}{setup.id}"
    if old == host:
        return
    if isinstance(state.get("codex-managed-remote-connections"), list):
        state["codex-managed-remote-connections"] = [
            c
            for c in state["codex-managed-remote-connections"]
            if not (isinstance(c, dict) and c.get("hostId") == old)
        ]
    for key in ("remote-connection-auto-connect-by-host-id", "remote-connection-analytics-id-by-host-id"):
        if isinstance(state.get(key), dict):
            state[key].pop(old, None)
    gone = set()
    if isinstance(state.get("remote-projects"), list):
        gone = {
            p.get("id") for p in state["remote-projects"] if isinstance(p, dict) and p.get("hostId") == old
        }
        state["remote-projects"] = [
            p for p in state["remote-projects"] if not (isinstance(p, dict) and p.get("hostId") == old)
        ]
    if not gone:
        return
    if isinstance(state.get("project-order"), list):
        state["project-order"] = [p for p in state["project-order"] if p not in gone]
    atoms = state.get(ATOMS)
    sidebar = atoms.get("unified-sidebar-project-order-v1") if isinstance(atoms, dict) else None
    if isinstance(atoms, dict) and isinstance(sidebar, list):
        atoms["unified-sidebar-project-order-v1"] = [
            p for p in sidebar if p not in {f"codex:project:{g}" for g in gone}
        ]


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


def seed_copy(
    home: Path,
    setup: Setup,
    *,
    seen_models: Iterable[str] = (),
    data: Path | None = None,
    others: Iterable[Setup] = (),
) -> None:
    """Write the seeded state (the file and its backup, as the app does):
    every setup in `others` (the data folder's other Codex-app setups, so
    the copy knows them before they're started) and then `setup`, which is
    selected. Only while the copy isn't running. Raises StateUnknown or OSError."""
    state = read_state(home)
    for other in others:
        if other.id != setup.id:
            state = seeded_state(state, other, seen_models=seen_models, data=data)
    text = json.dumps(seeded_state(state, setup, seen_models=seen_models, data=data))
    for path in (home / GLOBAL_STATE, home / f"{GLOBAL_STATE}.bak"):
        _replace(path, text.encode("utf-8"), mode=0o644)


def bundled_catalog(
    app: Path, home: Path, model: str, run: Runner = subprocess.run
) -> tuple[str | None, list[str]]:
    """The copy's own model catalog (the app's bundled Codex's list, with no
    upgrade offers or announcements: codex_config.model_catalog), and the
    models it would announce, to mark as seen. (None, []) if it can't be read."""
    from umcodex.codex_config import model_catalog

    if win.is_windows_app(app):  # the package's app\resources\codex.exe
        codex, env = win.bundled_codex(app, home)
    else:
        codex = app / "Contents" / "Resources" / "codex-cli" / "bin" / "codex"
        env = {"CODEX_HOME": str(home), "HOME": str(home), "PATH": "/usr/bin:/bin"}
    try:
        done = run(
            [str(codex), "debug", "models", "--bundled"],
            capture_output=True, text=True, timeout=60, check=False,
            env=env, stdin=subprocess.DEVNULL, creationflags=win.hidden(),
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
    return isinstance(hosts, dict) and alias(setup_id, data) in hosts


# Windows: why a setup's last launch in the Codex app fell back to Terminal,
# for the setup's card (the launch's own folder is gone by then). Kept until
# the setup is started again or the app connects.
FALLBACKS = "fallbacks.json"


def _fallbacks(data: Path | None) -> dict:
    try:
        found = json.loads((app_folder(data) / FALLBACKS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def record_fallback(setup_id: str, message: str | None, data: Path | None = None) -> None:
    """Keep (or, with None, forget) why the setup fell back to Terminal."""
    found = _fallbacks(data)
    if message is None and setup_id not in found:
        return
    if message is None:
        found.pop(setup_id, None)
    else:
        found[setup_id] = {"message": message, "at": time.time()}
    with contextlib.suppress(OSError):
        app_folder(data).mkdir(parents=True, exist_ok=True)
        _private_write(app_folder(data) / FALLBACKS, json.dumps(found) + "\n")


def last_fallback(setup_id: str, data: Path | None = None) -> str | None:
    entry = _fallbacks(data).get(setup_id)
    message = entry.get("message") if isinstance(entry, dict) else None
    return message if isinstance(message, str) else None


def mark_connected(setup_id: str, data: Path | None = None) -> None:
    path = _hosts_file(data)
    try:
        hosts = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        hosts = {}
    if not isinstance(hosts, dict):
        hosts = {}
    hosts[alias(setup_id, data)] = {"connected_at": time.time()}
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
    proxy_for: Callable[[str], Sequence[str]] | None = None  # None: proxy_command, for `data`
    local_chats: bool = LOCAL_CHATS
    platform: str = sys.platform
    popen: Callable[..., object] = subprocess.Popen  # Windows: the copy is started, not waited for
    clock: Callable[[], float] = time.monotonic
    labels: tuple[tuple[str, str], ...] = ()
    runtime_busy: Callable[[], bool] = lambda: win.runtime_update_running(user_home(), time.time())
    _started_pid: int | None = field(default=None, init=False)  # Windows: the copy this launch started
    _started: object = field(default=None, init=False)  # Windows: its process, while held

    def __post_init__(self) -> None:
        self.labels = ((SSH_LABEL, self.setup_id),)

    def __call__(self, running) -> int:  # running: launch.Running
        from umcodex.launch import update_launch_app

        spec, setup = running.spec, running.setup
        name = alias(setup.id, self.data)
        self.say("Preparing the sandbox for the Codex app...")
        others = [s for s in app_setups(self.data) if s.id != setup.id]
        try:
            public = ensure_key(setup.id, run=self.run, data=self.data)
            # Every Codex-app setup gets its key and Host now, so the copy can be
            # set up with all of them (one started later is known already).
            for other in others:
                with contextlib.suppress(OSError, subprocess.SubprocessError, ValueError):
                    ensure_key(other.id, run=self.run, data=self.data)
            write_config(self.proxy_for, setup_ids={*_saved_setup_ids(self.data), setup.id}, data=self.data)
        except SshPermissionsError as error:  # Windows: nothing left that would break ssh
            from umcodex.launch import update_launch_app

            log.error("launch %s: %s", spec.launch_id, error)
            state = {"alias": alias(setup.id, self.data), "connected": False, "copy": "not-opened"}
            state.update(fallback="terminal", fallback_message=str(error))
            update_launch_app(running.folder, state)
            record_fallback(setup.id, str(error), self.data)
            self.say(str(error))
            return 1
        prepare_container(self.docker, spec.agent, public)
        responder = LocalChatsServer(self.data)
        if not self.local_chats:
            responder.ensure()
        copy_open = self.app is not None and running_copy(self.data, self.run, self.platform) is not None
        seen = self._write_copy_files(running.relay_port, running.token, setup, responder)
        reopened = False
        if copy_open and self._reopen_for(running, setup):
            copy_open, reopened = False, True
        seeded = False
        if self.app is not None and not copy_open:
            seeded = self._seed(setup, seen, others)
        connected_once = connected_before(setup.id, self.data)
        state = {
            "alias": name,
            "connected": False,
            # The steps show at once only when UM-Codex couldn't set the copy
            # up itself and the host hasn't connected before.
            "first_time": not connected_once and not seeded,
            "seeded": seeded,
            "steps": first_steps(setup.id, setup.name, self.data, self.platform),
            "notes": notes(setup.id, local_chats=self.local_chats, data=self.data, platform=self.platform),
            "copy": "not-opened",
            "icon": second_icon(self.platform),  # where the launcher says the copy is
            "reopened": reopened,
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
            # The copy may stay open after the launch: the backup then stays for its next write.
            self._keep_chrome(
                final=self.app is None or running_copy(self.data, self.run, self.platform) is None
            )
            responder.stop()
            # Only this launch's token (another launch may have written its own since).
            with contextlib.suppress(OSError):
                if token_file.read_text(encoding="utf-8") == running.token:
                    token_file.unlink()

    def _keep_chrome(self, *, final: bool) -> None:
        """Put the person's Chrome manifest back if the copy took it
        (chrome_link.py): at each poll, and when the launch ends."""
        with contextlib.suppress(OSError):
            chrome_link.restore(app_folder(self.data), self.data, final=final, platform=self.platform)

    def _reopen_for(self, running, setup: Setup) -> bool:
        """The copy is open but doesn't know this setup (made after it opened):
        when no other setup's launch uses it, quit it so it can be set up and
        opened again (the card says "Reopening the Codex window…"). False when
        it's left as it is (it knows the setup, another launch uses it, or it
        didn't quit): the guided steps then show as before. Mac only."""
        from umcodex.launch import update_launch_app
        from umcodex.this_computer import quit_found

        known = copy_knows(setup.id, self.data)
        if self.platform != "darwin" or known is not False or self._copy_shared(running):
            return False  # it knows the setup, or that can't be told, or another launch uses it
        update_launch_app(
            running.folder, {"alias": alias(setup.id, self.data), "connected": False, "copy": "reopening"}
        )
        self.say("Reopening UM-Codex's Codex window, set up for this setup...")
        log.info("launch %s: reopening the Codex app copy to set it up", running.spec.launch_id)
        # Asked to quit, then SIGTERM; never SIGKILL here (the person may have a
        # chat open): if it hasn't quit in about 10 s, it's left and the steps show.
        ended = quit_found(
            lambda: running_copy(self.data, self.run, self.platform),
            run=self.run,
            sleep=self.sleep,
            patience=5.0,
            force=False,
        )
        if not ended:
            log.warning("the Codex app copy didn't quit; showing the steps")
        return ended

    def _seed(self, setup: Setup, seen: list[str], others: Iterable[Setup] = ()) -> bool:
        """The host, its project and the pop-ups seen, in the copy's state
        file (the copy isn't running). False, and nothing changed, if the
        file's shape isn't one UM-Codex knows."""
        home, _ = copy_paths(self.data)
        version = app_version(self.app)
        if version is not None and not version.startswith(TESTED_APP_VERSIONS):
            log.info("Codex app %s: not a version the copy's set-up was checked with; trying it", version)
        try:
            seed_copy(home, setup, seen_models=seen, data=self.data, others=others)
        except (StateUnknown, OSError) as error:
            log.warning("the Codex app copy's state couldn't be set up (%s); showing the steps", error)
            return False
        log.info("the Codex app copy is set up for %s (app %s)", alias(setup.id, self.data), version)
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
            setup_alias=alias(setup.id, self.data),
            token_file=token_file if self.local_chats else None,
            local_chats=self.local_chats,
            catalog=catalog_path,
        )
        _private_write(config, text)
        return announced

    def _open_copy(self, setup_id: str, *, link: bool) -> str:
        if self.app is None:
            return "not-opened"
        pid = running_copy(self.data, self.run, self.platform)
        if pid is not None:
            return "brought-forward" if bring_forward(pid, self.run, self.platform) else "already-open"
        # The add link only when UM-Codex couldn't set the copy up and the
        # host never connected: it adds the host switched off, so later it
        # would switch off a host that's on.
        link_arg = deep_link(setup_id, self.data) if link else None
        chrome_link.remember(
            app_folder(self.data), self.data, platform=self.platform
        )  # restored by _keep_chrome
        if self.platform == "win32":
            return self._open_windows(link_arg)
        done = self.run(
            open_command(self.app, self.data, link_arg),
            capture_output=True,
            timeout=60,
            check=False,
        )
        if done.returncode != 0:
            log.warning("the Codex app copy didn't open (exit code %s)", done.returncode)
            return "failed"
        return "opened"

    def _open_windows(self, link: str | None) -> str:
        """Windows: ChatGPT.exe itself, started and left running (never by
        its package, which would drop CODEX_HOME: codex_app_windows), then
        found again by its profile folder, so it's known to be ours. If the
        lookup can't find it while the process we started still runs, that
        process is the copy (a second copy on the same profile would hand
        over to the first and end)."""
        assert self.app is not None
        try:
            command, env = windows_open(self.app, self.data, link)
        except win.UnsafePaths as error:
            log.error("the Codex app copy wasn't started: %s", error)
            return "refused"
        try:
            self._started = win.start(command, env, self.popen)
        except OSError as error:
            log.warning("the Codex app copy didn't open (%s)", error)
            return "failed"
        for _ in range(WINDOWS_START_CHECKS):
            pid = running_copy(self.data, self.run, self.platform)
            if pid is not None:
                self._started_pid = pid
                return "opened"
            self.sleep(self.poll_seconds)
        if win.still_running(self._started) and isinstance(getattr(self._started, "pid", None), int):
            log.warning("the Codex app copy runs but wasn't found by its profile; keeping its process")
            self._started_pid = self._started.pid  # type: ignore[attr-defined]
            return "opened"
        log.warning("the Codex app copy was started but isn't running with UM-Codex's profile")
        return "failed"

    def _copy_shared(self, running) -> bool:
        """Whether another setup's launch in the Codex app (this data folder's)
        is running now: they share UM-Codex's one copy of the app."""
        from umcodex.launch import running_launches

        mine = running.spec.launch_id
        with contextlib.suppress(OSError):
            return any(
                launch.app and not launch.app.get("local") and launch.launch_id != mine
                for launch in running_launches(self.data)
            )
        return False

    def _fall_back(self, running, state: dict, why: str) -> int:
        """Windows: the copy didn't connect in time (or didn't start). Stop
        the copy this launch started (by its PID), unless another setup's
        launch uses it, end the launch, and say what happened and to use
        Terminal (the launcher shows it on the setup's card)."""
        from umcodex.launch import update_launch_app

        _, user_data = copy_paths(self.data)
        if self._started_pid is None:
            # Open from before (this launch brought it forward): not this launch's to close.
            opened_before = state.get("copy") in ("brought-forward", "already-open")
            outcome = "already-open" if opened_before else "not-started"
        elif self._copy_shared(running):
            outcome = "shared"
        elif win.stop(self._started_pid, user_data, self.run, self._started):
            outcome = "stopped"
            log.info("stopped the Codex app copy (pid %d)", self._started_pid)
        else:
            outcome = "still-open"
        message = WINDOWS_FALLBACKS[outcome]
        update_launch_app(running.folder, {**state, "fallback": "terminal", "fallback_message": message})
        record_fallback(running.setup.id, message, self.data)  # for the card, once the launch is gone
        log.warning("launch %s: %s; ending it (the copy: %s)", running.spec.launch_id, why, outcome)
        self.say(message)
        return 1

    def _say_ready(self, name: str, state: dict) -> None:
        copy = state["copy"]
        if copy == "failed":
            self.say("UM-Codex's Codex window couldn't be opened. Open the launcher and try again.")
        elif copy == "refused":
            self.say("UM-Codex didn't open its Codex window: its folders would have been your own app's.")
        elif copy == "already-open":
            self.say(f"UM-Codex's Codex window is already open: switch to it ({second_icon(self.platform)}).")
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
        windows = self.platform == "win32" and self.app is not None
        if windows and state["copy"] in ("failed", "refused"):
            return self._fall_back(running, state, "the Codex app copy didn't start")
        limit = WINDOWS_STEPS_SECONDS if state["first_time"] else WINDOWS_CONNECT_SECONDS
        deadline = self.clock() + limit
        waited = False
        while True:
            # Twice in a row: a Docker that's slow to answer once isn't a stop.
            missing = 0 if self.docker.running(agent) else missing + 1
            if responder is not None and not self.local_chats:
                with contextlib.suppress(OSError, RuntimeError):
                    responder.ensure()  # takes the port over if the process that had it ended
            self._keep_chrome(final=False)
            if missing >= 2:
                self.say("The sandbox was stopped.")
                return 0
            if not state["connected"] and app_server_running(self.docker, agent):
                state = {**state, "connected": True, "first_time": False}
                mark_connected(running.setup.id, self.data)
                record_fallback(running.setup.id, None, self.data)
                update_launch_app(running.folder, state)
                log.info("launch %s: the Codex app connected", running.spec.launch_id)
                self.say(f"Connected: the Codex app is working in the sandbox ({state['alias']}).")
            if windows and not state["connected"] and (now := self.clock()) > deadline:
                # A runtime download under way is left to finish first (up to the grace).
                if now < deadline + WINDOWS_UPDATE_GRACE_SECONDS and self.runtime_busy():
                    if not waited:
                        log.info("the Codex app is downloading its runtime; waiting before stopping it")
                    waited = True
                else:
                    why = f"the Codex app didn't connect within {limit:.0f}s"
                    return self._fall_back(running, state, why)
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
    needn't ask it: asked only where "Codex app" works (a Mac, or Windows
    with `windows_enabled`) with the Codex app installed and the line not
    there yet, default yes. No answer (no terminal) adds nothing: the
    consent must be the person's. A "no" is kept (in the data folder), so it
    isn't asked at the next install unless `ask_again`. 0: the line is there
    (or isn't needed here), 1: not added."""
    if platform != "darwin" and not (platform == "win32" and windows_enabled()):
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
