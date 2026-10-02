"""M4, "On this computer" (spike: docs/spikes/2026-10-02-this-computer.md).

Codex's desktop app working directly on the Mac, not in the sandbox: a
second UM-Codex copy of the app, separate from the sandbox copy (M6,
codex_app.py), with its own CODEX_HOME and Electron profile in
`<data>/codex-app-local/`, so local chats and sandbox chats are never in
the same window. Its provider is the Toolkit through a relay on this
computer, on a port fixed per data folder (the copy keeps the config it
started with while it runs), with a token the relay writes at each start
into a file only the person can read; Codex reads it with `auth.command`
and re-reads it every few minutes. The key stays in the keychain, read only
by the relay.

A launch of such a setup (`run_local`, `um-codex launch --setup <id>
--open local`, which the launcher window starts in the background) holds
the relay while the copy is open: it writes the copy's settings, seeds its
state (the project, the welcome flow, the model announcements) while it
isn't running, opens it, and ends when the copy quits. Stop in the launcher
quits the copy (`stop_local`). No Docker.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import socket
import subprocess
import time
import tomllib
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path

import tomli_w

from umcodex.codex_app import ATOMS, GLOBAL_STATE, StateUnknown, _private_write, _replace, read_state
from umcodex.paths import data_dir
from umcodex.relay import Relay, RelayServer, new_token

log = logging.getLogger(__name__)

LOCAL_FOLDER = "codex-app-local"  # in the data folder: this copy's CODEX_HOME, profile, relay files
PORT_FILE = "relay-port"
TOKEN_FILE = "relay-token"
RELAY_PID_FILE = "relay-pid"  # the process holding the relay (checked by `um-codex local-token`)
HOLD_LOCK = "launch.lock"  # one launch on this computer at a time, per data folder
PROVIDER = "toolkit"

# "Full access" (the default) or "this folder only": Codex's own sandbox on
# macOS (Seatbelt), writes limited to the project's folders.
ACCESS = {
    "full": {"sandbox_mode": "danger-full-access"},
    "folder": {"sandbox_mode": "workspace-write"},
}

# The caution dialog's text (the launcher window shows it when the choice is made).
WARNING = (
    "Codex will run on your Mac, not in the sandbox. It can read, change and delete any of "
    "your files, use your apps and browser, and act with your accounts. While it runs, it may "
    "also be able to reach UM-Codex's own Toolkit key (it runs as you). Use it only when you "
    "need computer or browser control."
)

# The bundled plugins behind "computer and browser control" (the app's
# `openai-bundled` marketplace): Computer Use, the in-app browser, Chrome.
# The bundled plugins behind "computer and browser control" (26.928's marketplace):
# Computer Use and its unified backend, the in-app browser, and the two that
# watch or act through the screen and apps (Record & Replay, Computer History).
CONTROL_PLUGINS = ("computer-use", "unified-computer-use", "browser", "record-and-replay", "computer-history")
# Chrome control: always off in the local copy for now. Its install writes the
# ChatGPT extension's native host manifest for the whole macOS user (the
# person's own app shares it), and the GUI round found it unusable here anyway.
OFF_PLUGINS = ("chrome",)
MARKETPLACE = "openai-bundled"

NOTES = (
    "This window runs Codex on your Mac, not in the sandbox: it can do anything you can do here.",
    'Computer Use asks macOS once for Screen Recording and Accessibility, for "Codex Computer Use". '
    "Grant them in System Settings only if you want Codex to see and use your apps.",
    "Control of your own Chrome isn't supported yet: it's off in this window.",
    "Quit this window (or Stop in UM-Codex) when you're done: the relay to the Toolkit ends with it.",
)


def local_folder(data: Path | None = None) -> Path:
    return (data or data_dir()) / LOCAL_FOLDER


def copy_paths(data: Path | None = None) -> tuple[Path, Path]:
    """This copy's CODEX_HOME and Electron profile (never the sandbox copy's)."""
    folder = local_folder(data)
    return folder / "codex-home", folder / "user-data"


def open_command(app: Path, data: Path | None = None, link: str | None = None) -> list[str]:
    """A separate copy of the app, as codex_app.open_command, in this folder."""
    home, user_data = copy_paths(data)
    return [
        "/usr/bin/open", "-n",
        "--env", f"CODEX_HOME={home}",
        "--env", f"CODEX_ELECTRON_USER_DATA_PATH={user_data}",
        str(app),
        "--args", f"--user-data-dir={user_data}",
        *([link] if link else []),
    ]  # fmt: skip


def running_copy(data: Path | None = None, run: Callable[..., subprocess.CompletedProcess] = subprocess.run):
    """The PID of this copy's main process, if it's running."""
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


# --- The copy's config.toml ----------------------------------------------------------


def local_config(
    existing: str,
    *,
    port: int,
    token_command: list[str],
    model: str,
    folders: Iterable[Path],
    access: str = "full",
    approval_policy: str = "on-request",
    internet: bool = True,
    catalog: Path | None = None,
    computer_use: bool | None = None,
) -> str:
    """The local copy's config.toml: the Toolkit through this computer's relay
    (no `requires_openai_auth`, so no sign-in), the default access and
    approvals, the working folders trusted. The app's other settings are kept.
    These are defaults: the person can change them in the app (nothing on a
    Mac enforces settings for one copy only)."""
    if access not in ACCESS:
        raise ValueError(f"unknown access {access!r}")
    folders = list(folders)
    config = tomllib.loads(existing) if existing.strip() else {}
    providers = config.get("model_providers")
    providers = providers if isinstance(providers, dict) else {}
    providers[PROVIDER] = {
        "name": "U-M GPT Toolkit (through UM-Codex)",
        "base_url": f"http://127.0.0.1:{port}/relay/v1",
        "wire_api": "responses",
        "request_max_retries": 1,
        "stream_max_retries": 2,
        "stream_idle_timeout_ms": 300000,
        # Re-read every 5 minutes: the relay writes a new token when it restarts.
        # `um-codex local-token`: the token, only after checking that what listens on the port is
        # this computer's relay, held by this person (local_token).
        "auth": {"command": token_command[0], "args": token_command[1:], "refresh_interval_ms": 300000},
    }
    # "Ask before commands" (on-request from the setup): Codex's "untrusted"
    # behaviour, which asks before every command it doesn't know to be
    # read-only and before file edits (core/src/exec_policy.rs and
    # tools/sandboxing.rs, rust-v0.157.1). With full access, on-request never
    # asks (nothing needs escalating). `approval_policy = "untrusted"` itself
    # is refused in config since 0.157.1 ("no longer supported"), so it comes
    # from the projects' trust level, with no approval_policy set.
    asks = approval_policy != "never"
    projects = config.get("projects")
    projects = projects if isinstance(projects, dict) else {}
    for folder in folders:
        projects[str(folder)] = {"trust_level": "untrusted" if asks else "trusted"}
    config.update(
        {
            "model_provider": PROVIDER,
            "forced_login_method": "api",
            "check_for_update_on_startup": False,
            "analytics": {"enabled": False},
            "feedback": {"enabled": False},
            "model_providers": providers,
            "projects": projects,
            # The person reviews; "Approve for me" would need a reviewer model the Toolkit doesn't have.
            "approvals_reviewer": "user",
            **ACCESS[access],
        }
    )
    if asks:
        config.pop("approval_policy", None)
    else:
        config["approval_policy"] = "never"
    if access == "folder":
        # Codex 0.157.1 and 0.159.2: `SandboxWorkspaceWrite { writable_roots, network_access, ... }`.
        # Every project folder is writable, not only the chat's working folder.
        config["sandbox_workspace_write"] = {
            "network_access": internet,
            "writable_roots": [str(f) for f in folders],
        }
    else:
        config.pop("sandbox_workspace_write", None)
    plugins = config.get("plugins")
    plugins = plugins if isinstance(plugins, dict) else {}
    for name in OFF_PLUGINS:
        key = f"{name}@{MARKETPLACE}"
        entry = plugins.get(key)
        plugins[key] = {**(entry if isinstance(entry, dict) else {}), "enabled": False}
    config["plugins"] = plugins
    if computer_use is not None:
        for name in CONTROL_PLUGINS:
            key = f"{name}@{MARKETPLACE}"
            entry = plugins.get(key)
            if not computer_use:
                plugins[key] = {**(entry if isinstance(entry, dict) else {}), "enabled": False}
            elif isinstance(entry, dict) and entry.get("enabled") is False:
                plugins[key] = {**entry, "enabled": True}  # switched back on: the app's choice again
    config["model"] = model
    if catalog is not None:
        config["model_catalog_json"] = str(catalog)
    head = "# UM-Codex sets the provider and defaults here (On this computer); the rest is the app's.\n"
    return head + tomli_w.dumps(config)


# --- The copy's state: the local project, pop-ups seen ---------------------------------


def project_id(folder: Path) -> str:
    """Stable per working folder."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"um-codex-local:{folder}"))


def seeded_state(
    state: dict,
    *,
    name: str,
    folders: Iterable[Path],
    seen_models: Iterable[str] = (),
    now: float | None = None,
) -> dict:
    """`state` with a local project for `folders` (the first is the working
    folder; named `name`) made, or brought up to date, and
    selected, and the welcome flow and the given models' announcements
    marked as seen. Shapes from the app's own schema (26.928: `local-projects`
    entries are {id, name, rootPaths, createdAt, updatedAt}). Raises
    StateUnknown for a shape it doesn't know."""
    now = time.time() if now is None else now
    state = json.loads(json.dumps(state))
    for key, kind in (
        ("local-projects", dict),
        ("project-order", list),
        ("selected-project", dict),
        (ATOMS, dict),
    ):
        value = state.get(key)
        if value is not None and not isinstance(value, kind):
            raise StateUnknown(key)
    roots = [str(f) for f in folders]
    if not roots:
        raise ValueError("a project needs a folder")
    projects = state.setdefault("local-projects", {})
    ms = int(now * 1000)
    pid = project_id(Path(roots[0]))
    mine = projects.get(pid)
    if not isinstance(mine, dict):
        mine = next(
            (
                p
                for p in projects.values()
                if isinstance(p, dict) and (p.get("rootPaths") or [None])[0] == roots[0]
            ),
            None,
        )
    if mine is None:
        mine = {"id": pid, "name": name, "rootPaths": roots, "createdAt": ms, "updatedAt": ms}
        projects[pid] = mine
    elif mine.get("rootPaths") != roots or mine.get("name") != name:
        mine.update({"name": name, "rootPaths": roots, "updatedAt": ms})
    order = state.setdefault("project-order", [])
    if mine["id"] not in order:
        order.insert(0, mine["id"])
    state["selected-project"] = {"type": "local", "projectId": mine["id"]}
    state.setdefault("desktop-first-seen-at-ms", int(now * 1000))
    atoms = state.setdefault(ATOMS, {})
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


def seed_copy(home: Path, *, name: str, folders: Iterable[Path], seen_models: Iterable[str] = ()) -> None:
    """Only while the copy isn't running (the app reads the file once at start)."""
    text = json.dumps(seeded_state(read_state(home), name=name, folders=folders, seen_models=seen_models))
    for path in (home / GLOBAL_STATE, home / f"{GLOBAL_STATE}.bak"):
        _replace(path, text.encode("utf-8"), mode=0o644)


# --- The relay for this copy -------------------------------------------------------------


def relay_port(data: Path | None = None) -> int:
    """This data folder's port for the local copy's relay, chosen once and kept."""
    path = local_folder(data) / PORT_FILE
    with contextlib.suppress(OSError, ValueError):
        port = int(path.read_text(encoding="ascii").strip())
        if 1024 < port < 65536:
            return port
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    _private_folder(path.parent)
    _private_write(path, f"{port}\n")
    return port


def _private_folder(folder: Path) -> None:
    """The local copy's folder: the person's only (0700), even if it was there before."""
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(folder, 0o700)


class FixedPortRelayServer(RelayServer):
    """RelayServer on a given port (the copy's config points at it)."""

    def __init__(self, relay: Relay, port: int) -> None:
        super().__init__(relay)
        self._fixed = port

    async def _start(self) -> int:
        import httpx
        from aiohttp import web

        self.relay._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=20, read=900, write=120, pool=20), follow_redirects=False
        )
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # A relay that just ended leaves its port in TIME_WAIT: rebinding it must work at once.
        # (On macOS this doesn't let two programs listen on the port together.)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", self._fixed))
        self._runner = web.AppRunner(self.relay.app(), access_log=None)
        await self._runner.setup()
        await web.SockSite(self._runner, sock).start()
        return self._fixed


class LocalRelay:
    """The local copy's relay, held while the copy runs. Its token is written
    to `relay-token` (0600) for Codex's `auth.command`. `keep_token` (the copy
    is still open, the relay restarted): the token already there is kept, so
    the open copy's chats don't need a new one. The holder removes the file
    (`stop(forget=True)`) when the copy quits."""

    def __init__(
        self, api_key: Callable[[], str], base_url: str, data: Path | None = None, *, keep_token: bool = False
    ) -> None:
        self.data = data or data_dir()
        self.port = relay_port(self.data)
        self.token_file = local_folder(self.data) / TOKEN_FILE
        self.pid_file = local_folder(self.data) / RELAY_PID_FILE
        kept = None
        if keep_token:
            with contextlib.suppress(OSError, UnicodeDecodeError):
                kept = self.token_file.read_text(encoding="utf-8").strip() or None
        self.token = kept or new_token()
        self._server = FixedPortRelayServer(Relay(self.token, api_key, base_url), self.port)

    def start(self) -> int:
        _private_folder(local_folder(self.data))
        self._server.start()  # OSError if the port is taken (another UM-Codex holds it)
        _private_write(self.token_file, self.token)
        _private_write(self.pid_file, f"{os.getpid()}\n")
        log.info("local copy's relay on 127.0.0.1:%d", self.port)
        return self.port

    def stop(self, *, forget: bool = True) -> None:
        with contextlib.suppress(OSError, ValueError):
            if int(self.pid_file.read_text(encoding="ascii")) == os.getpid():
                self.pid_file.unlink()
        if forget:
            with contextlib.suppress(OSError):
                if self.token_file.read_text(encoding="utf-8") == self.token:
                    self.token_file.unlink()
        self._server.stop()


# --- `um-codex local-token`: Codex's auth.command ---------------------------------------


class TokenRefused(RuntimeError):
    """The token isn't given out; the message says why (for the log, not a secret)."""


def token_command(data: Path | None = None) -> list[str]:
    """Codex's `auth.command` for the local copy: this UM-Codex's `local-token`,
    with absolute paths (an installed copy's launcher, which follows updates;
    a development copy, its own Python), and the data folder when it isn't
    the default."""
    import sys

    from umcodex.paths import default_data_dir
    from umcodex.update import Layout, install_root

    layout = Layout(install_root())
    if layout.running_version() is not None and layout.command.exists():
        program = [str(layout.command)]
    else:
        program = [sys.executable, "-m", "umcodex"]
    command = [*program, "local-token"]
    data = data or data_dir()
    if os.environ.get("UMCODEX_DATA_DIR") or os.path.realpath(data) != os.path.realpath(default_data_dir()):
        command += ["--data-dir", str(data)]
    return command


def listeners(port: int, run: Runner = subprocess.run) -> list[dict[str, str]]:
    """What listens on 127.0.0.1:<port> (TCP), from lsof's field output:
    one {"pid", "uid", "name"} per listening socket."""
    done = run(
        ["/usr/sbin/lsof", "-nP", "-a", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpun"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    found: list[dict[str, str]] = []
    pid = uid = ""
    for line in (done.stdout or "").splitlines():
        kind, value = line[:1], line[1:]
        if kind == "p":
            pid, uid = value, ""
        elif kind == "u":
            uid = value
        elif kind == "n":
            found.append({"pid": pid, "uid": uid, "name": value})
    return found


def local_token(data: Path | None = None, *, run: Runner = subprocess.run, uid: int | None = None) -> str:
    """The relay's token, for Codex in the local copy, only when the program
    listening on the relay's port is UM-Codex's relay for this data folder,
    run by this person: otherwise a program that took the port (another
    person on a shared Mac, say) would get the token, and with it the
    copy's prompts. Raises TokenRefused."""
    data = data or data_dir()
    folder = local_folder(data)
    uid = os.getuid() if uid is None else uid
    try:
        port = int((folder / PORT_FILE).read_text(encoding="ascii").strip())
        relay_pid = int((folder / RELAY_PID_FILE).read_text(encoding="ascii").strip())
        token_path = folder / TOKEN_FILE
        info = token_path.stat()
        token = token_path.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        raise TokenRefused("the relay isn't running (start the setup in UM-Codex)") from None
    if info.st_uid != uid or info.st_mode & 0o077:
        raise TokenRefused("the token file isn't private to this person")
    try:
        found = listeners(port, run)
    except (OSError, subprocess.SubprocessError):
        raise TokenRefused("what listens on the relay's port couldn't be checked") from None
    if not found:
        raise TokenRefused("nothing listens on the relay's port (start the setup in UM-Codex)")
    for entry in found:
        if entry["pid"] != str(relay_pid) or entry["uid"] != str(uid) or entry["name"] != f"127.0.0.1:{port}":
            raise TokenRefused("another program listens on the relay's port")
    if not token:
        raise TokenRefused("the token file is empty")
    return token


def wait_while_running(pid: int, poll: float = 2.0, sleep: Callable[[float], None] = time.sleep) -> None:
    """Return when the copy's main process has ended."""
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            pass
        sleep(poll)


# --- The launch: held while the copy is open ------------------------------------------

Say = Callable[[str], None]
Runner = Callable[..., subprocess.CompletedProcess]

UNAVAILABLE_WINDOWS = "On this computer works with the Codex app on a Mac only, for now."


def unavailable_reason(platform: str | None = None, app: Path | None = None) -> str | None:
    """Why "On this computer" can't be used here (None: it can)."""
    import sys

    from umcodex import codex_app

    platform = platform or sys.platform
    if platform != "darwin":
        return UNAVAILABLE_WINDOWS
    return codex_app.unavailable_reason(platform, app)


def project_folders(setup, layout) -> list[Path]:
    """The copy's project: the working folder and the other write folders."""
    return [Path(layout.working), *(Path(host) for host, _ in layout.writes)]


def _open_wait(data: Path, run: Runner, sleep: Callable[[float], None], seconds: float = 30) -> int | None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pid = running_copy(data, run)
        if pid is not None:
            return pid
        sleep(1)
    return None


def write_copy_files(
    setup, layout, *, data: Path, app: Path | None, port: int, token: list[str], run: Runner, seed: bool
) -> bool:
    """The copy's config.toml (and model catalog), and, when `seed` (the
    copy isn't running), its state. Returns whether the state was seeded."""
    from umcodex.codex_app import bundled_catalog

    home, user_data = copy_paths(data)
    for folder in (local_folder(data), home, user_data):
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    catalog_path, announced = None, []
    if app is not None:
        catalog, announced = bundled_catalog(app, home, setup.model, run=run)
        if catalog is not None:
            catalog_path = local_folder(data) / "models.json"
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
            log.warning("the local Codex app copy's config.toml didn't parse; moved it to %s", aside)
            existing = ""
    folders = project_folders(setup, layout)
    _private_write(
        config,
        local_config(
            existing,
            port=port,
            token_command=token,
            model=setup.model,
            folders=folders,
            access=setup.local_access,
            approval_policy=setup.approvals,
            internet=setup.internet,
            catalog=catalog_path,
            computer_use=setup.computer_use,
        ),
    )
    if not seed:
        return False
    try:
        seed_copy(home, name=setup.name, folders=folders, seen_models=announced)
    except (StateUnknown, OSError) as error:
        log.warning("the local Codex app copy's state couldn't be set up (%s)", error)
        return False
    return True


def run_local(
    setup,
    layout,
    *,
    say: Say = print,
    app: Path | None,
    data: Path | None = None,
    api_key: Callable[[], str] | None = None,
    base_url: str | None = None,
    run: Runner = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
    poll: float = 2.0,
    token: list[str] | None = None,
) -> int:
    """One launch "On this computer": relay, the copy's files, the copy
    opened (or brought forward), held until the copy quits. 0 when it ended
    normally, 1 when it couldn't start.

    The copy never outlives its relay: however the hold ends (the copy quit,
    Ctrl-C, SIGTERM or SIGHUP, an error, a refusal), a copy still open is
    quit first (`quit_copy`), so nothing else that later listens on the
    fixed port gets its requests."""
    import secrets
    import shutil

    from umcodex import codex_app, credentials, toolkit
    from umcodex.launch import LaunchLock, launches_dir, write_launch_info
    from umcodex.relay import upstream_base_url

    data = data or data_dir()
    refusal = local_refusal(setup)
    if refusal is not None:
        say(refusal)
        return 1
    _private_folder(local_folder(data))
    # One launch on this computer at a time (one copy, one relay): two Starts can't race.
    hold = LaunchLock(local_folder(data) / HOLD_LOCK)
    if not hold.acquire():
        say("Another setup is running on this computer now. Stop it first.")
        return 1
    launch_id = secrets.token_hex(4)
    folder = launches_dir(data) / launch_id
    folder.mkdir(parents=True)
    lock = LaunchLock(folder / "lock")
    if not lock.acquire(tries=40):
        hold.release()
        raise RuntimeError("couldn't lock the launch folder")
    state: dict = {"local": True, "copy": "not-opened", "pid": None, "seeded": False, "notes": list(NOTES)}
    write_launch_info(folder, setup, app=state)
    relay = None
    restore = _end_on_signals()
    try:
        pid = running_copy(data, run)
        key = api_key or credentials.api_key
        upstream = base_url or upstream_base_url(toolkit.BASE_URL)
        relay = LocalRelay(key, upstream, data, keep_token=pid is not None)
        try:
            port = relay.start()
        except OSError:
            relay.stop(forget=False)  # its thread
            relay = None
            if pid is not None:
                say(
                    "The relay's port is taken by another program, so UM-Codex's local Codex window "
                    "was closed. Start again in UM-Codex."
                )
                return 1
            (local_folder(data) / PORT_FILE).unlink(missing_ok=True)  # another program has it: a new one
            relay = LocalRelay(key, upstream, data)
            port = relay.start()
        log.info("launch %s: on this computer, relay on 127.0.0.1:%d", launch_id, port)
        seeded = write_copy_files(
            setup,
            layout,
            data=data,
            app=app,
            port=port,
            token=token or token_command(data),
            run=run,
            seed=pid is None,
        )
        if pid is not None:
            state["copy"] = "brought-forward" if codex_app.bring_forward(pid, run) else "already-open"
            say(
                "UM-Codex's local Codex window was already open: it keeps the project and settings "
                "it opened with."
            )
        elif app is None:
            state["copy"] = "not-opened"
        else:
            remember_chrome_manifests(data)
            done = run(open_command(app, data), capture_output=True, timeout=60, check=False)
            pid = _open_wait(data, run, sleep) if done.returncode == 0 else None
            state["copy"] = "opened" if pid is not None else "failed"
        state.update({"pid": pid, "seeded": seeded})
        write_launch_info(folder, setup, app=state)
        if pid is None:
            if state["copy"] == "failed":
                say("UM-Codex's local Codex window couldn't be opened.")
                return 1
            return 0
        say(f"Running on this computer, in UM-Codex's local Codex window ({setup.name}).")
        for line in NOTES:
            say(line)
        wait_while_running(pid, poll, sleep)
        say("UM-Codex's local Codex window was closed.")
        return 0
    except KeyboardInterrupt:
        say("")
        say("Ending the launch: UM-Codex's local Codex window is closed with it.")
        return 0
    finally:
        restore()
        quiet = _no_interrupts()  # a second Ctrl-C (or a signal) mustn't stop the copy being quit
        try:
            if running_copy(data, run) is not None:
                quit_copy(data, run=run, sleep=sleep)
            if running_copy(data, run) is None:
                for line in restore_chrome_manifests(data):
                    log.info("%s", line)
        finally:
            quiet()
            if relay is not None:
                relay.stop(forget=running_copy(data, run) is None)
            lock.release()
            hold.release()
            shutil.rmtree(folder, ignore_errors=True)


def local_refusal(setup) -> str | None:
    """Why a setup can't run on this computer as it is (None: it can)."""
    if setup.reads:
        return "Read-only folders aren't available on this computer: edit the setup and remove them."
    if setup.approvals == "never" and (setup.local_access == "full" or setup.computer_use):
        return FULL_AND_NEVER
    return None


FULL_AND_NEVER = (
    "On this computer, Codex must ask before commands with full access or with computer and browser "
    "control on (without asking, the apps' own permission questions are turned down): turn on Ask before "
    "commands, or choose Only this setup's folders with computer and browser control off."
)


class _Ended(KeyboardInterrupt):
    """SIGTERM or SIGHUP: end the hold as Ctrl-C does (the copy is quit first)."""


def _end_on_signals() -> Callable[[], None]:
    """SIGTERM and SIGHUP end the hold through its `finally` (in the main
    thread only, where Python delivers signals). Returns the restorer."""
    import signal
    import threading

    if threading.current_thread() is not threading.main_thread():
        return lambda: None

    def end(signum, frame):
        raise _Ended()

    previous = {}
    for name in ("SIGTERM", "SIGHUP"):
        number = getattr(signal, name, None)
        if number is not None:
            previous[number] = signal.signal(number, end)

    def restore() -> None:
        for number, handler in previous.items():
            with contextlib.suppress(ValueError, TypeError):
                signal.signal(number, handler)

    return restore


def _no_interrupts() -> Callable[[], None]:
    """Ignore SIGINT, SIGTERM and SIGHUP while the hold cleans up (main
    thread only). Returns the restorer."""
    import signal
    import threading

    if threading.current_thread() is not threading.main_thread():
        return lambda: None
    previous = {}
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        number = getattr(signal, name, None)
        if number is not None:
            previous[number] = signal.signal(number, signal.SIG_IGN)

    def restore() -> None:
        for number, handler in previous.items():
            with contextlib.suppress(ValueError, TypeError):
                signal.signal(number, handler)

    return restore


# JavaScript for Automation, through AppKit: ask the copy to quit, as its Quit
# menu does (it may ask the person first). No permission to control other apps.
_TERMINATE = (
    'ObjC.import("AppKit"); function run(argv) { '
    "var app = $.NSRunningApplication.runningApplicationWithProcessIdentifier(parseInt(argv[0])); "
    'if (!app || app.isNil()) return "gone"; '
    'return app.terminate() ? "ok" : "refused"; }'
)


def ask_to_quit(pid: int, run: Runner = subprocess.run) -> None:
    """Ask the copy to quit as its Quit menu does; SIGTERM if that can't be asked."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        done = run(
            ["/usr/bin/osascript", "-l", "JavaScript", "-e", _TERMINATE, str(pid)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if done.returncode == 0 and done.stdout.strip() in ("ok", "gone"):
            return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(pid, 15)


def quit_copy(
    data: Path,
    *,
    run: Runner = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
    patience: float = 10.0,
) -> bool:
    """Make sure UM-Codex's local copy has ended: asked to quit, then SIGTERM,
    then SIGKILL, each after a short wait. Only the process carrying the
    copy's profile folder. True when no copy is left."""
    ended = quit_found(lambda: running_copy(data, run), run=run, sleep=sleep, patience=patience)
    if not ended:
        log.warning("UM-Codex's local Codex window didn't quit")
    return ended


def quit_found(
    find: Callable[[], int | None],
    *,
    run: Runner = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
    patience: float = 10.0,
) -> bool:
    """End the app process `find` finds (it's looked for again before each
    step, by its profile folder): asked to quit, then SIGTERM, then SIGKILL,
    each after `patience` seconds. True when it's gone. Also used for the
    sandbox copy (codex_app.AppHold, to reopen it set up for a new setup)."""
    import signal

    pid = find()
    if pid is None:
        return True
    steps = [
        lambda p: ask_to_quit(p, run),
        lambda p: os.kill(p, signal.SIGTERM),
        lambda p: os.kill(p, signal.SIGKILL),
    ]
    for step in steps:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            step(pid)
        waited = 0.0
        while waited < patience:
            if find() is None:
                return True
            sleep(0.5)
            waited += 0.5
        pid = find()
        if pid is None:
            return True
    return False


def stop_local(data: Path, launch, run: Runner = subprocess.run) -> bool:
    """Stop a launch on this computer: ask UM-Codex's local copy to quit
    (the one carrying its profile folder, whatever PID the launch noted);
    its launch then ends, and makes sure the copy has. False when there's
    nothing to stop."""
    if not (launch.app and launch.app.get("local")):
        return False
    current = running_copy(data, run)
    if current is None:
        return False
    ask_to_quit(current, run)
    return True


def chrome_manifests(home: Path | None = None) -> list[Path]:
    """The Chrome extension's native messaging manifests (the app's Chrome
    plugin writes them for the whole macOS user)."""
    home = home or Path.home()
    support = home / "Library" / "Application Support"
    folders = ("Google/Chrome", "Chromium", "Google/ChromeForTesting", "Google/Chrome for Testing")
    return [support / f / "NativeMessagingHosts" / "com.openai.codexextension.json" for f in folders]


def _inside(path: Path, folder: Path) -> bool:
    """Whether `path` is `folder` or in it, letter case aside (a Mac's disk usually ignores it)."""
    a, b = str(path).casefold().rstrip("/"), str(folder).casefold().rstrip("/")
    return a == b or a.startswith(b + "/")


def forget_chrome_manifests(data: Path, home: Path | None = None) -> list[str]:
    """Remove the manifests that lead into the local copy's folder (which
    uninstall removes): left, they'd point Chrome at a program that's gone.
    A manifest of the person's own ChatGPT app is left alone."""
    ours = local_folder(data).resolve()
    removed = []
    for path in chrome_manifests(home):
        try:
            target = Path(json.loads(path.read_text(encoding="utf-8"))["path"]).resolve()
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if _inside(target, ours):
            with contextlib.suppress(OSError):
                path.unlink()
                removed.append(
                    f"Removed Chrome's link to UM-Codex's local Codex window ({path.parent.parent.name})."
                )
    return removed


# The person's Chrome connection. The app's Chrome plugin writes the ChatGPT
# extension's native host manifest (`com.openai.codexextension.json`, for the
# whole macOS user) and an entry in a shared registry
# (~/Library/Application Support/OpenAI/Codex/chrome-native-hosts-v2.json)
# when it installs or reconciles the plugin, which the app does at start
# (26.928's bootstrap: DF → JF and AF). The local copy keeps Chrome off, but
# UM-Codex still keeps what was there: before the copy opens, the manifests
# are remembered (`chrome-manifests.json` in the local folder, kept until
# restored, so a crash doesn't lose them); after it quits (and at uninstall),
# a manifest that now leads into the local copy is put back, or removed if
# there was none, and the registry's entries for the local copy are taken out.
# A manifest that leads elsewhere (the person's own app rewrote it) is left.

CHROME_BACKUP = "chrome-manifests.json"


def chrome_registry(home: Path | None = None) -> Path:
    home = home or Path.home()
    return home / "Library" / "Application Support" / "OpenAI" / "Codex" / "chrome-native-hosts-v2.json"


def _leads_into_local(path: Path, data: Path) -> bool:
    try:
        target = json.loads(path.read_text(encoding="utf-8"))["path"]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return isinstance(target, str) and _inside(Path(target).resolve(), local_folder(data).resolve())


def remember_chrome_manifests(data: Path, home: Path | None = None) -> None:
    """Before the copy opens: what each manifest is now (None: there's none,
    or it's already the local copy's). A backup from a launch that didn't
    restore it is kept, never overwritten with the local copy's manifest."""
    backup = local_folder(data) / CHROME_BACKUP
    if backup.exists():
        return
    saved: dict[str, str | None] = {}
    for path in chrome_manifests(home):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = None
        saved[str(path)] = None if text is None or _leads_into_local(path, data) else text
    _private_folder(local_folder(data))
    _private_write(backup, json.dumps(saved))


def restore_chrome_manifests(data: Path, home: Path | None = None) -> list[str]:
    """After the copy quits (and at uninstall): put back the person's
    manifests that the copy replaced, remove the copy's own, and take the
    copy's entries out of the shared registry. Lines saying what changed."""
    backup = local_folder(data) / CHROME_BACKUP
    try:
        saved = json.loads(backup.read_text(encoding="utf-8"))
        saved = saved if isinstance(saved, dict) else {}
    except (OSError, ValueError):
        saved = {}
    changed = []
    for path in chrome_manifests(home):
        if not _leads_into_local(path, data):
            continue  # untouched, or the person's own app wrote it since
        before = saved.get(str(path))
        with contextlib.suppress(OSError):
            if isinstance(before, str):
                _replace(path, before.encode("utf-8"), mode=0o644)
                changed.append(f"Put back Chrome's link to your own ChatGPT app ({path.parent.parent.name}).")
            else:
                path.unlink()
                changed.append(
                    f"Removed Chrome's link to UM-Codex's local Codex window ({path.parent.parent.name})."
                )
    forget_chrome_registry(data, home)
    backup.unlink(missing_ok=True)
    return changed


def forget_chrome_registry(data: Path, home: Path | None = None) -> bool:
    """Take the local copy's entries out of the app's shared Chrome registry
    (only those whose paths lead into the local folder; the rest, and the
    file's shape, are kept). False when nothing was changed."""
    path = chrome_registry(home)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    entries = raw.get("entries") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return False
    ours = local_folder(data).resolve()

    def local_entry(entry: object) -> bool:
        paths = entry.get("paths") if isinstance(entry, dict) else None
        if not isinstance(paths, dict):
            return False
        return any(
            isinstance(paths.get(k), str) and _inside(Path(paths[k]).resolve(), ours)
            for k in ("codexHome", "extensionHostPath")
        )

    kept = [e for e in entries if not local_entry(e)]
    if len(kept) == len(entries):
        return False
    with contextlib.suppress(OSError):
        _replace(path, (json.dumps({**raw, "entries": kept}, indent=2) + "\n").encode("utf-8"), mode=0o644)
        return True
    return False


# What uninstall always removes from the local copy, even when the data is
# kept: the programs it holds (its Computer Use copy, which macOS's grants
# name, and the app's plugins). Its settings and chats stay unless the data
# goes too.
PROGRAMS = ("codex-home/computer-use", "codex-home/plugins")
PRIVACY_NOTE = (
    'If you granted Screen Recording or Accessibility to "Codex Computer Use" and no longer need '
    "it, remove it in System Settings → Privacy & Security (your own ChatGPT app may use the same "
    "entry, so UM-Codex leaves it to you)."
)
