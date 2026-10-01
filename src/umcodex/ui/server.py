"""`um-codex ui`: the launcher window's server and its JSON API.

A small aiohttp server on 127.0.0.1 (a free port) serves one page and the API
under /api; protection.py keeps other programs and pages out. The page is
opened in the default browser with a one-time sign-in link.

One server per data folder: it holds `ui.lock`, and writes its port and a
private control secret to `ui.json`. A second `um-codex ui` asks it, with
that secret, for a new sign-in link and opens that instead. The server ends
by itself after IDLE_SECONDS with no request from the page.

Starting a setup opens a new terminal window running `um-codex launch
--setup <id>` (opener.py), or, for a setup opened in the Codex app, starts
that launch in the background (`--open app`, codex_app.py); either way the
launch runs on its own, and goes on if this server ends.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from importlib import resources
from pathlib import Path
from typing import Any

from aiohttp import web
from keyring.errors import KeyringError

from umcodex import __version__, codex_app, credentials, folders, toolkit, windows_vm
from umcodex.containers import Docker, DockerError, volume_name
from umcodex.docker_path import ensure_docker_on_path
from umcodex.folders import FolderRefused
from umcodex.launch import LaunchLock, running_launches, stop_launch
from umcodex.paths import data_dir
from umcodex.setups import (
    OPEN_IN,
    Setup,
    SetupStore,
    check,
    moved,
    new_id,
    resolved,
    shown,
    summary,
)
from umcodex.ui import picker
from umcodex.ui.opener import Opener, OpenFailed, openers
from umcodex.ui.protection import BrowserSession, add_security_headers, protection

log = logging.getLogger(__name__)

IDLE_SECONDS = 15 * 60
STATIC = "static"
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-/]{0,99}")
_UNPRINTABLE = re.compile(
    "[\\x00-\\x1f\\x7f\\u0085\\u2028\\u2029\\u200b-\\u200f\\u202a-\\u202e\\u2066-\\u2069]"
)
MAX_NAME = 80


class Invalid(ValueError):
    """A request that can't be done; the message is for the person."""

    def __init__(
        self,
        message: str,
        field: str | None = None,
        status: int = 400,
        errors: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.field = field
        self.status = status
        # Every problem found, by field, in the form's order (the first is `field`).
        self.errors = errors if errors is not None else ({field: message} if field else {})


# --- What the page sees -----------------------------------------------------


def folder_json(path: str, *, write: bool | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"path": path, "shown": shown(path)}
    if write is not None:
        entry["write"] = write
    return entry


def setup_json(setup: Setup, *, own_data: Path | None = None) -> dict[str, Any]:
    problem = None
    try:
        check(setup, own_data=own_data)
    except FolderRefused as why:
        problem = str(why)
    return {
        "id": setup.id,
        "name": setup.name,
        "working": folder_json(setup.working),
        "folders": [folder_json(p, write=True) for p in setup.writes]
        + [folder_json(p, write=False) for p in setup.reads],
        "internet": setup.internet,
        "browser": setup.internet and setup.browser,
        "browser_asks": setup.browser_asks,
        "approvals": setup.approvals,
        "model": setup.model,
        "open_in": setup.open_in,
        "problem": problem,
    }


def checked_folder(raw: object, *, own_data: Path | None, field: str) -> tuple[str, tuple[str, ...]]:
    if not isinstance(raw, str) or not raw.strip():
        raise Invalid("Choose a folder.", field)
    try:
        found = folders.check_folder(raw, own_data=own_data)
    except FolderRefused as why:
        raise Invalid(str(why), field) from None
    return str(found.path), found.warnings


def setup_from(body: object, *, setup_id: str | None, own_data: Path | None = None) -> Setup:
    """A setup from the page's form, checked as the terminal's questions check
    it. Every problem is reported at once, in the form's order."""
    if not isinstance(body, dict):
        raise Invalid("That request wasn't understood.")
    errors: dict[str, str] = {}

    def check_part(field: str, step: Callable[[], Any]) -> Any:
        try:
            return step()
        except Invalid as why:
            errors.setdefault(field, str(why))
            return None

    working = check_part(
        "working", lambda: checked_folder(body.get("working"), own_data=own_data, field="working")[0]
    )
    name = check_part("name", lambda: _name(body.get("name")))
    writes: list[str] = []
    reads: list[str] = []
    raw_folders = body.get("folders", [])
    if not isinstance(raw_folders, list) or len(raw_folders) > 50:
        errors.setdefault("folders", "That list of folders wasn't understood.")
        raw_folders = []
    for entry in raw_folders:
        if not isinstance(entry, dict):
            errors.setdefault("folders", "That list of folders wasn't understood.")
            continue
        raw_path = entry.get("path")
        path = check_part(
            "folders", lambda raw=raw_path: checked_folder(raw, own_data=own_data, field="folders")[0]
        )
        if path is not None:
            (writes if entry.get("write") is True else reads).append(path)
    if working is not None and "folders" not in errors:
        try:
            folders.plan(Path(working), [Path(p) for p in writes], [Path(p) for p in reads])
        except FolderRefused as why:
            errors["folders"] = str(why)
    internet = body.get("internet") is True
    browser = internet and body.get("browser") is True
    approvals = body.get("approvals", "never")
    if approvals not in ("never", "on-request"):
        errors["approvals"] = "That approval choice wasn't understood."
    model = body.get("model") or toolkit.DEFAULT_MODEL
    if not isinstance(model, str) or not _MODEL.fullmatch(model):
        errors["model"] = "That isn't a model name."
    open_in = body.get("open_in", "terminal")
    if open_in not in OPEN_IN:
        errors["open_in"] = "That choice of where to open Codex wasn't understood."
    if errors:
        field, message = next(iter(errors.items()))
        raise Invalid(message, field, errors=errors)
    assert working is not None and name is not None
    return Setup(
        id=setup_id or new_id(name),
        name=name,
        working=working,
        writes=tuple(writes),
        reads=tuple(reads),
        internet=internet,
        model=model,
        approvals=approvals,
        browser=browser,
        browser_asks=body.get("browser_asks") is not False,
        open_in=open_in,
    )


def _name(raw: object) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise Invalid("Give the setup a name.", "name")
    name = " ".join(raw.split())
    if len(name) > MAX_NAME or _UNPRINTABLE.search(name):
        raise Invalid(f"Use a shorter name, of ordinary characters (at most {MAX_NAME}).", "name")
    return name


# Why Start can't go ahead, by Docker's state (the page offers what fixes it).
DOCKER_NOT_READY = {
    "stopped": "Docker Desktop isn't running. Open it first.",
    "starting": "Docker Desktop is still starting. Wait until it's running, then Start.",
    "not-installed": "Docker Desktop isn't installed. Install it, then Start.",
    "vm-refused": "Docker can't start until Windows' policy is fixed: use Fix it… first.",
    "unknown": "Docker isn't answering. Restart Docker Desktop, then Start.",
}

DOCKER_WORDS = {
    "ready": "Docker is running.",
    "stopped": "Docker Desktop isn't running.",
    "starting": "Docker Desktop is starting…",
    "not-installed": "Docker Desktop isn't installed.",
    "vm-refused": "Docker can't start: Windows won't let its virtual machine sign in.",
    "unknown": "Docker isn't answering.",
}

# The terminal's explanation (windows_vm.check_before_launch), for the page.
FIX_EXPLAINED = (
    "Windows won't let Docker's virtual machine sign in (a Windows policy took away a right it "
    "needs; this happens on the Michigan Medicine network). UM-Codex can put the right back: "
    "Windows will show one administrator prompt, then Docker Desktop is restarted. On a Michigan "
    "Medicine computer, turn on your temporary administrator access first. (Restarting Windows "
    "also fixes it, for a while.)"
)

FIX_WORDS = {
    "fixed": "Fixed: Docker is running again.",
    "declined": "The administrator prompt was closed or refused, so nothing changed.",
    "still-refused": "The change went through, but Windows still refuses. Restart Windows.",
    "restart-failed": "The right is back, but Docker Desktop didn't restart. Open it yourself.",
    "not-needed": "Docker doesn't need the fix now.",
    "busy": "The fix is already under way.",
    "unsupported": "This fix is for Windows only.",
}

KEY_WORDS = {
    "ok": "The Toolkit accepted the key. It's saved in this computer's keychain.",
    "unreachable": "Couldn't reach the Toolkit to check the key (no network, or off the VPN?). "
    "It was saved anyway.",
    "error": "The Toolkit couldn't check the key just now. It was saved anyway.",
}


def _quiet_run(*args, **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run with no console window of its own on Windows."""
    if sys.platform == "win32":
        kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    return subprocess.run(*args, **kwargs)


@dataclass
class Status:
    """Things that take a moment to find out, kept for a few seconds."""

    docker: str = "unknown"
    docker_checked: float = 0.0
    key_saved: bool | None = None
    key_checked: float = 0.0
    update: str | None = None
    models: list[str] = field(default_factory=list)
    # One Docker check at a time: a page polling while another check runs
    # gets the last answer instead of starting a second one.
    docker_checking: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class Launcher:
    """The API's state and actions, apart from HTTP (tests call these too)."""

    store: SetupStore = field(default_factory=SetupStore)
    data: Path = field(default_factory=data_dir)
    openers: dict[str, Opener] = field(default_factory=openers)
    docker: Docker = field(default_factory=lambda: Docker(_quiet_run))
    run: Callable[..., subprocess.CompletedProcess] = _quiet_run
    has_key: Callable[[], bool] = credentials.has_api_key
    check_key: Callable[[str], str] = toolkit.check_key
    save_key: Callable[[str], None] = credentials.save_api_key
    list_models: Callable[[], list[str]] = lambda: toolkit.list_models(credentials.api_key())
    platform: str = sys.platform
    status: Status = field(default_factory=Status)
    windows_doctor: windows_vm.DockerDoctor | None = None
    own_data: Path | None = None  # for the folder rules (tests)
    quit: Callable[[], None] | None = None  # set by serve(): ends the server
    reopen_after: bool = False  # start the installed version's window once this one has ended
    ssh_home: Path | None = None  # where ~/.ssh is (tests)

    # ----------------------------------------------------------- reading

    def docker_state(self, *, fresh: bool = False) -> str:
        if not fresh and time.monotonic() - self.status.docker_checked < 5:
            return self.status.docker
        checking = self.status.docker_checking
        if not checking.acquire(blocking=fresh):
            return self.status.docker  # a check is running: its answer comes next time
        try:
            return self._check_docker(fresh=fresh)
        finally:
            checking.release()

    def _check_docker(self, *, fresh: bool) -> str:
        if self.platform == "win32":
            self.windows_doctor = self.windows_doctor or windows_vm.DockerDoctor(run=self.run)
            state = self.windows_doctor.state(fresh=fresh)
        else:
            ensure_docker_on_path()
            if windows_vm.docker_answers(self.run):
                state = "ready"
            elif shutil.which("docker") is None:
                state = "not-installed"
            else:
                state = "stopped"
        self.status.docker, self.status.docker_checked = state, time.monotonic()
        return state

    def key_saved(self, *, fresh: bool = False) -> bool:
        if fresh or self.status.key_saved is None or time.monotonic() - self.status.key_checked > 30:
            self.status.key_saved, self.status.key_checked = self.has_key(), time.monotonic()
        return bool(self.status.key_saved)

    def state(self) -> dict[str, Any]:
        docker = self.docker_state()
        return {
            "version": __version__,
            "home": str(Path.home()),  # for showing paths as ~/…
            "setups": [setup_json(s, own_data=self.own_data) for s in self.store.all()],
            "running": self.running(),
            "docker": {
                "state": docker,
                "words": DOCKER_WORDS.get(docker, DOCKER_WORDS["unknown"]),
                "can_open": docker == "stopped",
                "can_fix": docker == "vm-refused" and self.platform == "win32",
                "fix_explained": FIX_EXPLAINED if docker == "vm-refused" else None,
            },
            "key": {"saved": self.key_saved()},
            "update": self.status.update,
            "installed": self.installed_version(),
            "openers": [
                {"key": key, "label": opener.label, "available": reason is None, "reason": reason}
                for key, opener in self.openers.items()
                for reason in [opener.reason()]
            ],
            # The Codex app (M6): whether ~/.ssh/config has UM-Codex's line yet.
            "ssh_include": codex_app.include_present(self.ssh_home),
            "include_explained": codex_app.INCLUDE_EXPLAINED,
        }

    def installed_version(self) -> str | None:
        """The version the installed launchers now open, when it isn't this
        server's own (an update or a new install happened while it ran)."""
        from umcodex.update import Layout, install_root

        with contextlib.suppress(Exception):
            layout = Layout(install_root(), windows=self.platform == "win32")
            current = layout.pointer()[0]
            if layout.running_version() is not None and current and current != __version__:
                return current
        return None

    def reopen_newer(self) -> dict[str, Any]:
        """Close this server and start the installed version's launcher window."""
        if self.quit is None:
            raise Invalid("This window can't reopen itself. Open UM-Codex again from its app.", status=409)
        self.reopen_after = True
        self.quit()
        return {"reopening": True}

    def running(self) -> list[dict[str, Any]]:
        return [
            {
                "launch_id": launch.launch_id,
                "setup_id": launch.setup_id,
                "setup_name": launch.setup_name,
                "started_at": launch.started_at,
                "since": time.strftime("%H:%M", time.localtime(launch.started_at)),
                "app": launch.app,
            }
            for launch in running_launches(self.data)
        ]

    def models(self) -> list[str]:
        if not self.status.models:
            try:
                self.status.models = self.list_models()
            except credentials.MissingCredential:
                self.status.models = []
        found = list(self.status.models)
        if toolkit.DEFAULT_MODEL not in found:
            found.insert(0, toolkit.DEFAULT_MODEL)
        return found

    def setup(self, setup_id: str) -> Setup:
        found = self.store.get(setup_id)
        if found is None:
            raise Invalid("That setup isn't saved any more.", status=404)
        return found

    # ----------------------------------------------------------- setups

    def create(self, body: object) -> dict[str, Any]:
        setup = setup_from(body, setup_id=None, own_data=self.own_data)
        self.store.save(setup)
        return setup_json(setup, own_data=self.own_data)

    def update(self, setup_id: str, body: object) -> dict[str, Any]:
        self.setup(setup_id)
        setup = setup_from(body, setup_id=setup_id, own_data=self.own_data)
        self.store.save(setup)
        return setup_json(setup, own_data=self.own_data)

    def duplicate(self, setup_id: str) -> dict[str, Any]:
        original = self.setup(setup_id)
        name = f"{original.name} (copy)"[:MAX_NAME]
        copy = replace(original, id=new_id(name), name=name)
        self.store.save(copy)
        return setup_json(copy, own_data=self.own_data)

    def delete(self, setup_id: str) -> None:
        setup = self.setup(setup_id)
        if any(launch.setup_id == setup_id for launch in running_launches(self.data)):
            raise Invalid("Stop this setup's running launch first.", status=409)
        self.store.delete(setup.id)
        codex_app.forget_setup(setup.id, self.ssh_home)  # its ssh host for the Codex app, if any
        with contextlib.suppress(DockerError):  # its Codex history; Docker may be closed
            self.docker("volume", "rm", volume_name(setup.id), check=False, timeout=30)

    def check_folder(self, body: object) -> dict[str, Any]:
        raw = body.get("path") if isinstance(body, dict) else None
        path, warnings = checked_folder(raw, own_data=self.own_data, field="folder")
        return {**folder_json(path), "warnings": list(warnings)}

    # ----------------------------------------------------------- starting

    def prepare(self, setup_id: str) -> dict[str, Any]:
        """What the page shows before Start: the terminal's own summary, and
        any saved folder that now leads somewhere else."""
        setup = self.setup(setup_id)
        try:
            layout = check(setup, own_data=self.own_data)
            changed = moved(setup, own_data=self.own_data)
        except FolderRefused as why:
            raise Invalid(f"This setup can't be used as it is: {why} Edit it to change that.") from None
        return {
            "setup": setup_json(setup, own_data=self.own_data),
            "summary": summary(resolved(setup, layout), layout),
            "moved": [{"saved": saved, "now": str(now)} for saved, now in changed],
            "app_notes": codex_app.notes(setup.id) if setup.open_in == "codex-app" else [],
        }

    def start(self, setup_id: str, body: object) -> dict[str, Any]:
        setup = self.setup(setup_id)
        confirmed = isinstance(body, dict) and body.get("confirm_moved") is True
        if not self.key_saved(fresh=True):
            raise Invalid("Save your Toolkit key first (Add key…).", "key", status=409)
        docker = self.docker_state(fresh=True)
        if docker != "ready":
            raise Invalid(DOCKER_NOT_READY.get(docker, DOCKER_NOT_READY["unknown"]), "docker", status=409)
        opener = self.openers.get(setup.open_in)
        if opener is None:
            raise Invalid("Codex can't be opened there: edit the setup and choose Terminal.", status=409)
        if not opener.available():
            raise Invalid(opener.reason() or "Codex can't be opened there now: choose Terminal.", status=409)
        if opener.key == "codex-app":
            if not codex_app.include_present(self.ssh_home):
                raise Invalid(
                    "The Codex app needs one line in your ssh settings first.", "ssh_include", status=409
                )
            if any(launch.setup_id == setup.id and launch.app for launch in running_launches(self.data)):
                raise Invalid("This setup is already running in the Codex app.", status=409)
        try:
            layout = check(setup, own_data=self.own_data)
            changed = moved(setup, own_data=self.own_data)
        except FolderRefused as why:
            raise Invalid(f"This setup can't be used as it is: {why} Edit it to change that.") from None
        if changed and not confirmed:
            raise Invalid("A saved folder now leads somewhere else: check it and confirm first.", status=409)
        if changed:
            setup = resolved(setup, layout)  # what the person confirmed
        self.store.save(setup, used=True)
        try:
            opener.open(setup.id)
        except OpenFailed as why:
            raise Invalid(str(why), status=500) from None
        return {"opened": opener.label, "in_background": opener.key == "codex-app"}

    def allow_ssh_include(self) -> dict[str, Any]:
        """The person chose Allow: the Include line at the top of ~/.ssh/config
        (backed up first)."""
        try:
            result = codex_app.add_include(self.ssh_home)
        except OSError:
            raise Invalid("Your ssh settings (~/.ssh/config) couldn't be changed.", status=500) from None
        log.info("launcher window: ~/.ssh/config Include line %s", result)
        return {"result": result}

    def stop(self, launch_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{8}", launch_id):
            raise Invalid("There's no such launch.", status=404)
        log.info("launcher window: Stop asked for launch %s", launch_id)
        try:
            found = stop_launch(self.docker, self.data, launch_id)
        except DockerError:
            raise Invalid("Docker didn't answer, so the launch couldn't be stopped.", status=500) from None
        if not found:
            raise Invalid("That launch has already ended.", status=404)
        return {"stopped": True}

    # ----------------------------------------------------------- the key and Docker

    def replace_key(self, body: object) -> dict[str, Any]:
        """Check and save the key. Nothing here returns, logs or keeps it."""
        key = body.get("key") if isinstance(body, dict) else None
        if not isinstance(key, str) or not key.strip():
            raise Invalid("Paste your Toolkit API key.", "key")
        key = key.strip()
        if not credentials.KEY_SHAPE.fullmatch(key):
            raise Invalid(
                "That doesn't look like an API key (it has spaces or unusual characters), "
                "so it wasn't saved.",
                "key",
            )
        result = self.check_key(key)
        if result == "refused":
            raise Invalid("The Toolkit refused that key, so it wasn't saved. Check it and try again.", "key")
        try:
            self.save_key(key)
        except KeyringError:
            raise Invalid(
                "The key couldn't be saved: this computer's keychain refused it or isn't available.", "key"
            ) from None
        del key
        self.status.key_saved, self.status.key_checked = True, time.monotonic()
        self.status.models = []
        return {"result": result, "words": KEY_WORDS.get(result, KEY_WORDS["error"])}

    def open_docker(self) -> dict[str, Any]:
        if self.platform == "win32":
            self.windows_doctor = self.windows_doctor or windows_vm.DockerDoctor(run=self.run)
            self.windows_doctor.start()
        elif self.platform == "darwin":
            self.run(["open", "-g", "-a", "Docker"], capture_output=True, timeout=30)
        else:
            raise Invalid("Start Docker yourself on this computer.")
        return {"words": "Opening Docker Desktop (this can take a minute)…"}

    def fix_docker(self) -> dict[str, Any]:
        if self.platform != "win32":
            raise Invalid(FIX_WORDS["unsupported"])
        self.windows_doctor = self.windows_doctor or windows_vm.DockerDoctor(run=self.run)
        result = self.windows_doctor.fix()
        self.status.docker_checked = 0.0
        return {"outcome": result.outcome, "words": FIX_WORDS.get(result.outcome, result.outcome)}

    def check_update(self) -> None:
        """The daily check, as a launch does it (update.launch_notice)."""
        from umcodex.update import launch_notice

        said: list[str] = []
        launch_notice(said.append, wait=10)
        if said:
            self.status.update = said[0]


# --- HTTP -------------------------------------------------------------------


async def _body(request: web.Request) -> object:
    try:
        return await request.json()
    except (ValueError, UnicodeDecodeError):
        raise Invalid("That request wasn't understood.") from None


def _page(name: str) -> bytes:
    return resources.files(__package__).joinpath(STATIC, name).read_bytes()


_TYPES = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".html": "text/html"}
STATIC_FILES = ("app.js", "app.css", "mark.svg")


def make_app(
    launcher: Launcher,
    session: BrowserSession,
    *,
    control_secret: str,
    seen: list[float] | None = None,
    quit: Callable[[], None] | None = None,
) -> web.Application:
    app = web.Application(
        middlewares=[_errors, protection(session, control_secret=control_secret, seen=seen)],
        client_max_size=64 * 1024,
    )
    app.on_response_prepare.append(add_security_headers)

    def blocking(function: Callable[..., Any], *args: Any) -> Any:
        return asyncio.get_running_loop().run_in_executor(None, function, *args)

    async def index(request: web.Request) -> web.Response:
        signed_in = session.valid(request.cookies.get(session.cookie_name))
        page = "index.html" if signed_in else "signed-out.html"
        return web.Response(body=_page(page), content_type="text/html", charset="utf-8")

    async def static(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        if name not in STATIC_FILES:
            raise web.HTTPNotFound()
        suffix = Path(name).suffix
        return web.Response(body=_page(name), content_type=_TYPES[suffix], charset="utf-8")

    async def sign_in(request: web.Request) -> web.Response:
        cookie = session.redeem(request.query.get("token", ""))
        response = web.Response(status=303, headers={"Location": "/"})
        if cookie is not None:
            response.set_cookie(session.cookie_name, cookie, httponly=True, samesite="Strict", path="/")
        return response

    async def control_sign_in(request: web.Request) -> web.Response:
        return web.json_response({"path": session.new_sign_in_path()})

    async def control_quit(request: web.Request) -> web.Response:
        if quit is not None:
            quit()
        return web.json_response({"quitting": True})

    async def state(request: web.Request) -> web.Response:
        return web.json_response(await blocking(launcher.state))

    async def models(request: web.Request) -> web.Response:
        found = await blocking(launcher.models)
        return web.json_response({"models": found, "default": toolkit.DEFAULT_MODEL})

    async def create(request: web.Request) -> web.Response:
        body = await _body(request)
        return web.json_response(await blocking(launcher.create, body), status=201)

    async def update(request: web.Request) -> web.Response:
        body = await _body(request)
        return web.json_response(await blocking(launcher.update, request.match_info["id"], body))

    async def delete(request: web.Request) -> web.Response:
        await blocking(launcher.delete, request.match_info["id"])
        return web.json_response({"deleted": True})

    async def duplicate(request: web.Request) -> web.Response:
        return web.json_response(await blocking(launcher.duplicate, request.match_info["id"]), status=201)

    async def prepare(request: web.Request) -> web.Response:
        return web.json_response(await blocking(launcher.prepare, request.match_info["id"]))

    async def start(request: web.Request) -> web.Response:
        body = await _body(request)
        return web.json_response(await blocking(launcher.start, request.match_info["id"], body))

    async def stop(request: web.Request) -> web.Response:
        return web.json_response(await blocking(launcher.stop, request.match_info["id"]))

    async def check_folder(request: web.Request) -> web.Response:
        body = await _body(request)
        return web.json_response(await blocking(launcher.check_folder, body))

    async def pick_folder(request: web.Request) -> web.Response:
        body = await _body(request)
        start_in = None
        if isinstance(body, dict) and isinstance(body.get("start"), str) and Path(body["start"]).is_dir():
            start_in = Path(body["start"])
        try:
            chosen = await picker.pick_folder(start_in=start_in)
        except (picker.PickerUnavailable, picker.PickerBusy, picker.PickerFailed) as why:
            raise Invalid(str(why), "folder", status=409) from None
        if chosen is None:
            return web.json_response({"cancelled": True})
        return web.json_response(await blocking(launcher.check_folder, {"path": str(chosen)}))

    async def key(request: web.Request) -> web.Response:
        body = await _body(request)
        return web.json_response(await blocking(launcher.replace_key, body))

    async def docker_open(request: web.Request) -> web.Response:
        await _body(request)
        return web.json_response(await blocking(launcher.open_docker))

    async def reopen_newer(request: web.Request) -> web.Response:
        await _body(request)
        return web.json_response(launcher.reopen_newer())

    async def allow_ssh(request: web.Request) -> web.Response:
        await _body(request)
        return web.json_response(await blocking(launcher.allow_ssh_include))

    async def docker_fix(request: web.Request) -> web.Response:
        await _body(request)
        return web.json_response(await blocking(launcher.fix_docker))

    app.router.add_get("/", index)
    app.router.add_get("/static/{name}", static)
    app.router.add_get("/sign-in", sign_in)
    app.router.add_post("/_control/sign-in", control_sign_in)
    app.router.add_post("/_control/quit", control_quit)
    app.router.add_get("/api/state", state)
    app.router.add_get("/api/models", models)
    app.router.add_post("/api/setups", create)
    app.router.add_put("/api/setups/{id}", update)
    app.router.add_delete("/api/setups/{id}", delete)
    app.router.add_post("/api/setups/{id}/duplicate", duplicate)
    app.router.add_post("/api/setups/{id}/prepare", prepare)
    app.router.add_post("/api/setups/{id}/start", start)
    app.router.add_post("/api/launches/{id}/stop", stop)
    app.router.add_post("/api/folders/check", check_folder)
    app.router.add_post("/api/folders/pick", pick_folder)
    app.router.add_post("/api/key", key)
    app.router.add_post("/api/docker/open", docker_open)
    app.router.add_post("/api/docker/fix", docker_fix)
    app.router.add_post("/api/reopen", reopen_newer)
    app.router.add_post("/api/codex-app/allow", allow_ssh)
    return app


@web.middleware
async def _errors(request: web.Request, handler) -> web.StreamResponse:
    """Plain answers for the page; nothing from the request in a log."""
    try:
        return await handler(request)
    except Invalid as why:
        return web.json_response(
            {"error": str(why), "field": why.field, "errors": why.errors}, status=why.status
        )
    except web.HTTPException:
        raise
    except Exception as error:  # a bug: say so plainly, log only its type
        log.error("launcher window: %s in %s %s", type(error).__name__, request.method, request.path)
        return web.json_response({"error": "Something went wrong in UM-Codex. Try again."}, status=500)


# --- Running it -------------------------------------------------------------

UI_LOCK = "ui.lock"
UI_INFO = "ui.json"


def open_in_browser(url: str) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", url], capture_output=True, timeout=30)
    elif sys.platform == "win32":
        os.startfile(url)  # type: ignore[attr-defined]
    else:
        webbrowser.open(url)


def _write_private(path: Path, text: str) -> None:
    path.unlink(missing_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(text)


def _ask_running(data: Path, what: str, timeout: float = 5) -> dict[str, Any]:
    """Ask the running launcher window's server (ui.json) over its control link."""
    import httpx

    info = json.loads((data / UI_INFO).read_text(encoding="utf-8"))
    port, control = int(info["port"]), str(info["control"])
    answer = httpx.post(
        f"http://127.0.0.1:{port}/_control/{what}",
        headers={"X-UMCodex-Control": control, "Content-Type": "application/json"},
        content=b"{}",
        timeout=timeout,
    )
    answer.raise_for_status()
    return {"port": port, **answer.json()}


def close_running(data: Path, wait: float = 5.0) -> None:
    """Close a running launcher window's server (before an uninstall removes
    its files). Never raises."""
    import httpx

    if not (data / UI_LOCK).exists():
        return
    probe = LaunchLock(data / UI_LOCK)
    if probe.acquire():
        probe.release()
        return
    with contextlib.suppress(OSError, ValueError, KeyError, TypeError, httpx.HTTPError):
        _ask_running(data, "quit")
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if probe.acquire():
            probe.release()
            return
        time.sleep(0.2)


def reopen(
    data: Path,
    *,
    say: Callable[[str], None] = print,
    opening: Callable[[str], None] = open_in_browser,
    wait: float = 5.0,
) -> int:
    """Another `um-codex ui` is running: open its page again, with a new sign-in link."""
    import httpx

    deadline = time.monotonic() + wait
    while True:
        try:
            answer = _ask_running(data, "sign-in")
            port, path = answer["port"], str(answer["path"])
            break
        except (OSError, ValueError, KeyError, TypeError, httpx.HTTPError):
            if time.monotonic() > deadline:
                say("UM-Codex's window is already running, but it didn't answer. Try again in a minute.")
                return 1
            time.sleep(0.25)
    url = f"http://127.0.0.1:{port}{path}"
    say("UM-Codex was already open: its window is opening in your browser again.")
    opening(url)
    return 0


COMMAND_FILES_KEPT_SECONDS = 10 * 60
NONCE_ENV = "UMCODEX_UI_NONCE"


def sweep_command_files(data: Path, now: float | None = None) -> None:
    """Remove the Mac's start-*.command files that never ran (Terminal
    removes each when it runs it), once they're older than a few minutes."""
    now = time.time() if now is None else now
    for leftover in (data / "ui").glob("start-*.command"):
        with contextlib.suppress(OSError):
            if now - leftover.lstat().st_mtime > COMMAND_FILES_KEPT_SECONDS:
                leftover.unlink()


async def serve(
    launcher: Launcher,
    *,
    data: Path,
    opening: Callable[[str], None] = open_in_browser,
    say: Callable[[str], None] = print,
    idle_seconds: float = IDLE_SECONDS,
    ready: Callable[[int, str], None] | None = None,
    stop: asyncio.Event | None = None,
) -> None:
    """Serve until the page has been away for `idle_seconds` (or `stop` is set)."""
    control = secrets.token_urlsafe(32)
    seen = [time.monotonic()]
    sweep_command_files(data)
    # The port is known only once the socket is bound: bind first, then build
    # the session (the cookie's name carries the port) and the app.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    session = BrowserSession(port)
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()

    def quit() -> None:  # from any thread
        loop.call_soon_threadsafe(stop.set)

    launcher.quit = quit
    app = make_app(launcher, session, control_secret=control, seen=seen, quit=quit)
    runner = web.AppRunner(app, access_log=None, handle_signals=False)
    await runner.setup()
    site = web.SockSite(runner, sock)
    await site.start()
    info = data / UI_INFO
    record = {"port": port, "control": control, "pid": os.getpid(), "nonce": os.environ.pop(NONCE_ENV, None)}
    _write_private(info, json.dumps(record) + "\n")
    url = f"http://127.0.0.1:{port}{session.sign_in_path()}"
    loop.run_in_executor(None, launcher.check_update)
    say(f"UM-Codex's window (if your browser doesn't open it, go here): {url}")
    say("It closes by itself a while after its page is closed. Ctrl-C ends it now.")
    if ready is not None:
        ready(port, url)
    else:
        await loop.run_in_executor(None, opening, url)
    try:
        while not stop.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=min(30.0, idle_seconds))
            if time.monotonic() - seen[-1] > idle_seconds:
                log.info("launcher window: idle, ending")
                break
    finally:
        info.unlink(missing_ok=True)
        await runner.cleanup()


def _no_browser(url: str) -> None:
    """`--no-browser`: serve() has printed the link already."""


def _say(text: str) -> None:
    print(text, flush=True)  # at once, even when the output is a pipe or a file


def main(*, say: Callable[[str], None] = _say, open_browser: bool = True) -> int:
    """`um-codex ui` (`open_browser=False`: the link is only printed)."""
    data = data_dir()
    data.mkdir(parents=True, exist_ok=True)
    lock = LaunchLock(data / UI_LOCK)
    if not lock.acquire(tries=3):
        return reopen(data, say=say, opening=open_in_browser if open_browser else say)
    launcher = Launcher(data=data)
    try:
        opening = open_in_browser if open_browser else _no_browser
        asyncio.run(serve(launcher, data=data, say=say, opening=opening))
    except KeyboardInterrupt:
        say("Closed.")
    except Exception:
        log.exception("the launcher window failed")
        say(f"UM-Codex's window stopped because of a problem. Details are in {data / 'um-codex.log'}.")
        return 1
    finally:
        lock.release()
    if launcher.reopen_after:
        start_installed()
    return 0


def start_installed() -> None:
    """Start the installed version's launcher window (after an update)."""
    from umcodex.update import Layout, install_root

    command = Layout(install_root()).command
    log.info("launcher window: reopening as the installed version")
    with contextlib.suppress(OSError):
        subprocess.Popen([str(command), "ui", "--detach"], **_background())


def _background() -> dict[str, Any]:
    options: dict[str, Any] = {"stdin": subprocess.DEVNULL, "close_fds": True}
    if sys.platform == "win32":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200
        )
    else:
        options["start_new_session"] = True
    return options


def show_alert(message: str, *, platform: str = sys.platform, run=subprocess.run) -> None:
    """A native message box (the app and shortcuts have no window to say it in)."""
    with contextlib.suppress(Exception):
        if platform == "darwin":
            script = [
                "on run argv",
                'display dialog (item 1 of argv) with title "UM-Codex" buttons {"OK"} '
                'default button "OK" with icon caution',
                "end run",
            ]
            args = [part for line in script for part in ("-e", line)]
            run(["osascript", *args, message], capture_output=True, timeout=600)
        elif platform == "win32":
            import ctypes

            # MB_OK | MB_ICONWARNING | MB_SETFOREGROUND
            ctypes.windll.user32.MessageBoxW(None, message, "UM-Codex", 0x0 | 0x30 | 0x10000)  # type: ignore[attr-defined]
        else:
            print(message, file=sys.stderr)


DETACH_WAIT_SECONDS = 10.0


def detach(
    *,
    open_browser: bool = True,
    wait: float = DETACH_WAIT_SECONDS,
    popen: Callable[..., Any] = subprocess.Popen,
    alert: Callable[[str], None] = show_alert,
) -> int:
    """`um-codex ui --detach`: start the server in the background, with no
    window (on Windows, a console of its own that's never shown, which the
    Docker commands it runs share), and wait until it's serving (its ui.json,
    with this start's nonce) or has handed over to one already running (it
    ends with 0). Anything else is shown in a native message box: the app and
    the shortcuts have no window of their own to say it in."""
    data = data_dir()
    data.mkdir(parents=True, exist_ok=True)
    nonce = secrets.token_hex(8)
    command = [sys.executable, "-m", "umcodex", "ui", *([] if open_browser else ["--no-browser"])]
    env = {**os.environ, "PYTHONUTF8": "1", NONCE_ENV: nonce}
    # Its error output, if it fails early (a traceback). Not its normal output:
    # that has the sign-in link in it.
    errors = data / "ui-start.log"
    with errors.open("wb") as output:
        child = popen(command, stdout=subprocess.DEVNULL, stderr=output, env=env, **_background())
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError, ValueError, AttributeError):
            if json.loads((data / UI_INFO).read_text(encoding="utf-8")).get("nonce") == nonce:
                return 0
        code = child.poll()
        if code == 0:
            return 0  # another window was running: it was opened again
        if code is not None:
            break
        time.sleep(0.1)
    with contextlib.suppress(OSError):
        tail = errors.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-20:]
        if tail:
            log.error("the launcher window didn't start; it printed:\n%s", "\n".join(tail))
    log.error("the launcher window didn't start (exit code %s)", child.poll())
    alert(
        "UM-Codex's window didn't start.\n\n"
        f"What went wrong is in its log: {data / 'um-codex.log'}\n\n"
        "Try again; if it still doesn't start, send that file to whoever looks after UM-Codex."
    )
    return 1
