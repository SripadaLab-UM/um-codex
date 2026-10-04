"""The launcher window (`um-codex ui`): its protection, its API, the opener."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from umcodex import credentials
from umcodex.containers import Docker, instance_of
from umcodex.launch import LaunchLock, launches_dir, running_launches, write_launch_info
from umcodex.paths import data_dir
from umcodex.setups import Setup, SetupStore, new_id
from umcodex.ui import opener as opening
from umcodex.ui import picker, server
from umcodex.ui.protection import BrowserSession

from .conftest import FAKE_KEY

REPO = Path(__file__).resolve().parents[1]


class FakeOpener:
    key = "terminal"
    label = "Terminal"

    def __init__(self) -> None:
        self.opened: list[str] = []

    def available(self) -> bool:
        return True

    def reason(self) -> str | None:
        return None

    def open(self, setup_id: str) -> None:
        self.opened.append(setup_id)


class FakeAppOpener(FakeOpener):
    key = "codex-app"
    label = "Codex app"


class FakeLocalOpener(FakeOpener):
    key = "this-computer"
    label = "Codex app, on this computer"


class FakeDocker:
    """`docker` as a list of the commands asked for; it answers `info`."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.listing = ""

    def __call__(self, command, **kwargs) -> subprocess.CompletedProcess:
        self.commands.append(list(command))
        out = self.listing if command[:2] in (["docker", "ps"], ["docker", "network"]) else ""
        if command[:3] == ["docker", "network", "rm"]:
            out = ""
        return subprocess.CompletedProcess(command, 0, out, "")


@pytest.fixture
def folders_here(tmp_path: Path) -> dict[str, Path]:
    found = {}
    for name in ("thesis", "data", "refs", "o'brien \"q\" ;x"):
        folder = tmp_path / "work" / name
        folder.mkdir(parents=True)
        found[name] = Path(os.path.realpath(folder))
    return found


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Harness:
    def __init__(self, launcher: server.Launcher, client: TestClient, session: BrowserSession, control: str):
        self.launcher = launcher
        self.client = client
        self.session = session
        self.control = control
        self.port = session.port

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def sign_in(self) -> None:
        answer = await self.client.get(self.session.sign_in_path(), allow_redirects=False)
        assert answer.status == 303

    async def post(self, path: str, body: object = None, **headers: str):
        sent = {"Content-Type": "application/json", "Origin": self.origin, "Sec-Fetch-Site": "same-origin"}
        sent.update(headers)
        return await self.client.post(path, data=json.dumps(body if body is not None else {}), headers=sent)

    async def put(self, path: str, body: object):
        headers = {"Content-Type": "application/json", "Origin": self.origin}
        return await self.client.put(path, data=json.dumps(body), headers=headers)

    async def delete(self, path: str):
        headers = {"Content-Type": "application/json", "Origin": self.origin}
        return await self.client.delete(path, data="{}", headers=headers)


def launcher_for_tests(**changes) -> server.Launcher:
    fake_docker = changes.pop("fake_docker", FakeDocker())
    options = {
        "store": SetupStore(),
        "data": data_dir(),
        "openers": {
            "terminal": FakeOpener(),
            "codex-app": opening.CodexAppOpener(find=lambda: None, platform="darwin"),
        },
        "local_opener": FakeLocalOpener(),
        "docker": Docker(fake_docker),
        "run": fake_docker,
        "check_key": lambda key: "ok",
        "list_models": lambda: ["gpt-5.6-terra", "gpt-5.5"],
        "platform": "darwin",
    }
    options.update(changes)
    return server.Launcher(**options)


def with_server(test: Callable, **changes):
    """Run `test(harness)` against the app on a real local port."""

    async def run() -> None:
        port = free_port()
        session = BrowserSession(port)
        launcher = launcher_for_tests(**changes)
        control = "control-secret-for-tests"
        app = server.make_app(launcher, session, control_secret=control)
        test_server = TestServer(app, host="127.0.0.1", port=port)
        async with TestClient(test_server) as client:
            await test(Harness(launcher, client, session, control))

    asyncio.run(run())


def setup_body(working: Path, **changes) -> dict:
    body = {
        "name": "thesis",
        "working": str(working),
        "folders": [],
        "internet": False,
        "approvals": "never",
        "model": "gpt-5.6-terra",
        "open_in": "terminal",
    }
    body.update(changes)
    return body


# --- Signing in, and who may ask ---------------------------------------------


def test_the_api_needs_the_cookie_from_the_one_time_link():
    async def test(h: Harness) -> None:
        assert (await h.client.get("/api/state")).status == 401
        page = await h.client.get("/")
        assert "isn't signed in" in await page.text()
        bad = await h.client.get("/sign-in?token=wrong", allow_redirects=False)
        assert bad.status == 303 and h.session.cookie_name not in bad.cookies
        good = await h.client.get(h.session.sign_in_path(), allow_redirects=False)
        assert good.status == 303 and good.headers["Location"] == "/"
        cookie = good.headers["Set-Cookie"]
        assert h.session.cookie_name in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie
        state = await h.client.get("/api/state")
        assert state.status == 200
        assert (await state.json())["key"] == {"saved": False}
        assert "Your setups" not in await (await h.client.get("/")).text()  # built by app.js
        assert 'src="/static/app.js"' in await (await h.client.get("/")).text()

    with_server(test)


def test_the_sign_in_link_works_once():
    async def test(h: Harness) -> None:
        path = h.session.sign_in_path()
        await h.client.get(path, allow_redirects=False)
        h.client.session.cookie_jar.clear()
        again = await h.client.get(path, allow_redirects=False)
        assert h.session.cookie_name not in again.cookies
        assert (await h.client.get("/api/state")).status == 401

    with_server(test)


def test_requests_for_another_host_name_are_refused():
    async def test(h: Harness) -> None:
        await h.sign_in()
        for host in (f"evil.example:{h.port}", f"127.0.0.1:{h.port + 1}", "127.0.0.1", f"0.0.0.0:{h.port}"):
            answer = await h.client.get("/api/state", headers={"Host": host})
            assert answer.status == 421, host
        assert (await h.client.get("/api/state", headers={"Host": f"localhost:{h.port}"})).status == 200

    with_server(test)


def test_changes_from_another_page_or_not_json_are_refused(folders_here):
    async def test(h: Harness) -> None:
        await h.sign_in()
        body = setup_body(folders_here["thesis"])
        refused = [
            await h.post("/api/setups", body, Origin="http://evil.example"),
            await h.post("/api/setups", body, Origin=f"http://localhost:{h.port + 1}"),
            await h.post("/api/setups", body, **{"Sec-Fetch-Site": "same-site"}),
            await h.post("/api/setups", body, **{"Content-Type": "text/plain"}),
            await h.post("/api/setups", body, **{"Content-Type": "application/x-www-form-urlencoded"}),
        ]
        assert [answer.status for answer in refused] == [403] * 5
        assert SetupStore().all() == []
        assert (await h.post("/api/setups", body)).status == 201

    with_server(test)


def test_no_cors_and_the_security_headers_on_every_answer():
    async def test(h: Harness) -> None:
        await h.sign_in()
        for answer in (
            await h.client.get("/api/state", headers={"Origin": "http://evil.example"}),
            await h.client.options("/api/state", headers={"Origin": "http://evil.example"}),
            await h.client.get("/static/app.js"),
            await h.client.get("/api/nothing"),
            await h.client.get("/api/state", headers={"Host": "evil.example"}),
        ):
            assert not [name for name in answer.headers if name.lower().startswith("access-control-")]
            assert "connect-src 'self'" in answer.headers["Content-Security-Policy"]
            assert answer.headers["X-Content-Type-Options"] == "nosniff"
        assert (await h.client.get("/static/../server.py")).status == 404
        assert (await h.client.get("/static/index.html")).status == 404

    with_server(test)


def test_the_control_link_needs_the_secret_and_gives_a_new_sign_in():
    async def test(h: Harness) -> None:
        refused = await h.post("/_control/sign-in", {}, **{"X-UMCodex-Control": "wrong"})
        assert refused.status == 403
        answer = await h.post("/_control/sign-in", {}, **{"X-UMCodex-Control": h.control})
        path = (await answer.json())["path"]
        assert (await h.client.get(path, allow_redirects=False)).status == 303
        assert (await h.client.get("/api/state")).status == 200

    with_server(test)


# --- Setups through the API ----------------------------------------------------


def test_setups_round_trip_through_the_api(folders_here):
    async def test(h: Harness) -> None:
        await h.sign_in()
        body = setup_body(
            folders_here["thesis"],
            folders=[{"path": str(folders_here["data"]), "write": True}, {"path": str(folders_here["refs"])}],
            internet=True,
            browser=True,
            browser_asks=False,
            approvals="on-request",
            model="gpt-5.5",
        )
        made = await (await h.post("/api/setups", body)).json()
        saved = SetupStore().get(made["id"])
        assert saved is not None
        assert saved.working == str(folders_here["thesis"])
        assert saved.writes == (str(folders_here["data"]),) and saved.reads == (str(folders_here["refs"]),)
        assert (saved.internet, saved.browser, saved.browser_asks) == (True, True, False)
        assert (saved.approvals, saved.model, saved.open_in) == ("on-request", "gpt-5.5", "terminal")
        state = await (await h.client.get("/api/state")).json()
        assert [s["name"] for s in state["setups"]] == ["thesis"]
        assert state["setups"][0]["folders"][0] == {
            "path": str(folders_here["data"]),
            "shown": str(folders_here["data"]),
            "write": True,
        }
        # Edit: the internet off turns the browser tool off.
        edited = await h.put(f"/api/setups/{made['id']}", {**body, "name": "thesis 2", "internet": False})
        assert edited.status == 200
        again = SetupStore().get(made["id"])
        assert again is not None and again.name == "thesis 2" and not again.internet and not again.browser
        copy = await (await h.post(f"/api/setups/{made['id']}/duplicate")).json()
        assert copy["name"] == "thesis 3" and copy["id"] != made["id"]
        assert (await h.delete(f"/api/setups/{made['id']}")).status == 200
        assert [s.name for s in SetupStore().all()] == ["thesis 3"]
        assert ["docker", "volume", "rm", f"umcodex-home-{made['id']}"] in h.launcher.run.commands  # type: ignore[attr-defined]
        assert (await h.delete(f"/api/setups/{made['id']}")).status == 404

    with_server(test)


@pytest.fixture
def home_with_keys(tmp_path, monkeypatch) -> Path:
    """A home folder with ~/.ssh and ~/.aws in it (a CI runner may have neither)."""
    home = tmp_path / "home"
    for name in (".ssh", ".aws"):
        (home / name).mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return Path(os.path.realpath(home))


def test_folder_refusals_come_back_in_plain_words(folders_here, home_with_keys):
    async def test(h: Harness) -> None:
        await h.sign_in()
        home = await h.post("/api/setups", setup_body(Path.home()))
        assert home.status == 400
        answer = await home.json()
        assert answer["field"] == "working" and "home folder can't be shared" in answer["error"]
        ssh = await h.post("/api/folders/check", {"path": str(Path.home() / ".ssh")})
        assert ssh.status == 400 and "SSH keys" in (await ssh.json())["error"]
        twice = setup_body(
            folders_here["thesis"],
            folders=[{"path": str(folders_here["data"]), "write": True}, {"path": str(folders_here["data"])}],
        )
        both = await (await h.post("/api/setups", twice)).json()
        assert both["field"] == "folders" and "both read-only and writable" in both["error"]
        relative = await (await h.post("/api/setups", setup_body(Path("thesis")))).json()
        assert "isn't a full path" in relative["error"]
        odd = await (await h.post("/api/setups", setup_body(folders_here["thesis"], name="a\u202eb"))).json()
        assert odd["field"] == "name"
        model = await (await h.post("/api/setups", setup_body(folders_here["thesis"], model="x; rm"))).json()
        assert model["field"] == "model"
        assert SetupStore().all() == []
        good = await (await h.post("/api/folders/check", {"path": str(folders_here["data"])})).json()
        assert good["path"] == str(folders_here["data"]) and good["warnings"] == []

    with_server(test)


def test_choose_folder_uses_the_picker_and_checks_what_it_returns(folders_here, monkeypatch, home_with_keys):
    chosen: list[Path | None] = [folders_here["data"], Path.home() / ".aws", None]
    starts = []

    async def pick(*, start_in=None):
        starts.append(start_in)
        return chosen.pop(0)

    monkeypatch.setattr(picker, "pick_folder", pick)

    async def test(h: Harness) -> None:
        await h.sign_in()
        first = await (await h.post("/api/folders/pick", {"start": str(folders_here["thesis"])})).json()
        assert first["path"] == str(folders_here["data"])
        assert starts[0] == folders_here["thesis"]
        refused = await h.post("/api/folders/pick", {})
        assert refused.status == 400 and "AWS credentials" in (await refused.json())["error"]
        assert await (await h.post("/api/folders/pick", {})).json() == {"cancelled": True}

    with_server(test)


def test_the_picker_reads_only_full_paths_from_its_json():
    assert picker.parse('["/a/b\\nc"]') == [Path("/a/b\nc")]
    assert picker.parse('"/a"') == [Path("/a")]
    assert picker.parse("relative") == [] and picker.parse('["x", 3]') == []
    command = picker.mac_command('/x"); doShellScript("rm')
    assert command[:4] == ["osascript", "-l", "JavaScript", "-e"]
    assert 'const START = "/x\\"); doShellScript(\\"rm";' in command[4]
    encoded = picker.windows_command()[-1]
    script = base64.b64decode(encoded).decode("utf-16-le")
    assert "$env:UMCODEX_PICK_START" in script and "AttachThreadInput" in script


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' own folder dialog")
def test_the_windows_folder_dialog_compiles_and_picks_folders(tmp_path):
    """Windows PowerShell 5.1 compiles the picker's dialog, and the dialog is
    made for folders on disk only, starting in a folder given (not shown)."""
    script = base64.b64decode(picker.windows_command()[-1]).decode("utf-16-le")
    source = script.split("Add-Type -TypeDefinition @'\n", 1)[1].split("\n'@", 1)[0]
    (tmp_path / "picker.cs").write_text(source, encoding="utf-8")
    check = (
        f"Add-Type -TypeDefinition (Get-Content -Raw -LiteralPath '{tmp_path / 'picker.cs'}'); "
        f"[UmCodexPicker.Folder]::Check('{tmp_path}')"
    )
    done = subprocess.run(
        ["powershell", "-NoProfile", "-STA", "-NonInteractive", "-Command", check],
        capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    options = int(done.stdout.strip())
    assert options & 0x20 and options & 0x40 and options & 0x800


# --- Starting -------------------------------------------------------------------


def test_start_shows_the_summary_then_opens_the_setup(folders_here, memory_keychain):
    async def test(h: Harness) -> None:
        await h.sign_in()
        made = await (await h.post("/api/setups", setup_body(folders_here["thesis"], internet=True))).json()
        prepared = await (await h.post(f"/api/setups/{made['id']}/prepare")).json()
        text = "\n".join(prepared["summary"])
        assert "your real files" in text and "local network and VPN" in text
        assert prepared["moved"] == []
        no_key = await h.post(f"/api/setups/{made['id']}/start", {})
        assert no_key.status == 409 and "key" in (await no_key.json())["error"]
        credentials.save_api_key(FAKE_KEY)
        started = await h.post(f"/api/setups/{made['id']}/start", {})
        assert started.status == 200
        assert (await started.json()) == {"opened": "Terminal", "in_background": False}
        assert h.launcher.openers["terminal"].opened == [made["id"]]  # type: ignore[attr-defined]
        assert SetupStore().last_used().id == made["id"]  # type: ignore[union-attr]

    with_server(test)


def test_a_folder_that_moved_needs_confirming_before_a_start(folders_here, tmp_path):
    credentials.save_api_key(FAKE_KEY)
    link = tmp_path / "link"
    link.symlink_to(folders_here["thesis"])
    setup = Setup(id=new_id("linked"), name="linked", working=str(link / "."), open_in="terminal")
    # Saved as the link's path, which now leads to another folder.
    setup = Setup(id=setup.id, name="linked", working=str(link), open_in="terminal")
    SetupStore().save(setup)

    async def test(h: Harness) -> None:
        await h.sign_in()
        prepared = await (await h.post(f"/api/setups/{setup.id}/prepare")).json()
        assert prepared["moved"] == [{"saved": str(link), "now": str(folders_here["thesis"])}]
        refused = await h.post(f"/api/setups/{setup.id}/start", {})
        assert refused.status == 409 and "confirm" in (await refused.json())["error"]
        assert h.launcher.openers["terminal"].opened == []  # type: ignore[attr-defined]
        # A plain yes isn't enough: the places shown must be the places now.
        vague = await h.post(f"/api/setups/{setup.id}/start", {"confirm_moved": True})
        assert vague.status == 409 and (await vague.json())["field"] == "moved"
        stale = await h.post(f"/api/setups/{setup.id}/start", {"confirm_moved": [str(tmp_path)]})
        assert stale.status == 409
        confirm = {"confirm_moved": [str(folders_here["thesis"])]}
        started = await h.post(f"/api/setups/{setup.id}/start", confirm)
        assert started.status == 200
        saved = SetupStore().get(setup.id)
        assert saved is not None and saved.working == str(folders_here["thesis"])

    with_server(test)


def test_codex_app_says_how_to_get_it_when_it_isnt_installed(folders_here):
    credentials.save_api_key(FAKE_KEY)

    async def test(h: Harness) -> None:
        await h.sign_in()
        state = await (await h.client.get("/api/state")).json()
        terminal, app = state["openers"]
        assert terminal == {"key": "terminal", "label": "Terminal", "available": True, "reason": None}
        assert app["key"] == "codex-app" and app["available"] is False
        assert "chatgpt.com/download" in app["reason"] and "Terminal" in app["reason"]
        body = setup_body(folders_here["thesis"], open_in="codex-app")
        made = await (await h.post("/api/setups", body)).json()
        answer = await h.post(f"/api/setups/{made['id']}/start", {})
        assert answer.status == 409 and "isn't installed" in (await answer.json())["error"]

    with_server(test)


def test_codex_app_start_asks_for_the_ssh_line_first(folders_here, ssh_home):
    credentials.save_api_key(FAKE_KEY)
    app = FakeAppOpener()

    async def test(h: Harness) -> None:
        await h.sign_in()
        state = await (await h.client.get("/api/state")).json()
        assert state["ssh_include"] is False
        assert "Include ~/.ssh/um-codex/config" in state["include_explained"]
        body = setup_body(folders_here["thesis"], open_in="codex-app")
        made = await (await h.post("/api/setups", body)).json()
        prepared = await (await h.post(f"/api/setups/{made['id']}/prepare")).json()
        assert any(f"Remote · umcodex-{made['id']}" in line for line in prepared["app_notes"])
        assert any("Browser tool" in line for line in prepared["app_notes"])
        refused = await h.post(f"/api/setups/{made['id']}/start", {})
        assert refused.status == 409 and (await refused.json())["field"] == "ssh_include"
        assert app.opened == [] and not (ssh_home / ".ssh" / "config").exists()
        allowed = await h.post("/api/codex-app/allow")
        assert (await allowed.json()) == {"result": "created"}
        assert (ssh_home / ".ssh" / "config").read_text() == "Include ~/.ssh/um-codex/config\n"
        started = await h.post(f"/api/setups/{made['id']}/start", {})
        assert (await started.json()) == {"opened": "Codex app", "in_background": True}
        assert app.opened == [made["id"]]
        state = await (await h.client.get("/api/state")).json()
        assert state["ssh_include"] is True

    with_server(test, openers={"terminal": FakeOpener(), "codex-app": app})


def test_a_running_launch_in_the_app_shows_its_state(folders_here):
    data = data_dir()
    folder = launches_dir(data) / "0123abcd"
    folder.mkdir(parents=True)
    setup = Setup(id="thesis-a1", name="Thesis", working=str(folders_here["thesis"]), open_in="codex-app")
    app = {"alias": "umcodex-thesis-a1", "connected": False, "first_time": True, "steps": ["x"]}
    write_launch_info(folder, setup, app=app)
    lock = LaunchLock(folder / "lock")
    assert lock.acquire()
    try:
        (running,) = launcher_for_tests().running()
    finally:
        lock.release()
    assert running["app"] == app


# --- Running launches -------------------------------------------------------------


def test_running_launches_are_found_by_their_lock_and_stopped_by_label(folders_here):
    data = data_dir()
    folder = launches_dir(data) / "0123abcd"
    folder.mkdir(parents=True)
    lock = LaunchLock(folder / "lock")
    assert lock.acquire()
    setup = Setup(id="thesis-abc123", name="thesis", working=str(folders_here["thesis"]))
    write_launch_info(folder, setup, started_at=time.mktime((2026, 10, 1, 14, 5, 0, 0, 0, -1)))
    # A folder of a launch that ended (no lock held) and one without its info yet.
    (launches_dir(data) / "deadbeef").mkdir()
    write_launch_info(launches_dir(data) / "deadbeef", setup)
    fake = FakeDocker()
    fake.listing = "c0ffee\n"

    async def test(h: Harness) -> None:
        await h.sign_in()
        state = await (await h.client.get("/api/state")).json()
        assert state["running"] == [
            {
                "launch_id": "0123abcd",
                "setup_id": "thesis-abc123",
                "setup_name": "thesis",
                "started_at": state["running"][0]["started_at"],
                "since": "14:05",
                "app": None,
            }
        ]
        assert (await h.post("/api/launches/deadbeef/stop")).status == 404
        assert (await h.post("/api/launches/..%2F..%2Fx/stop")).status == 404
        busy = await h.delete("/api/setups/thesis-abc123")
        assert busy.status in (404, 409)
        stopped = await h.post("/api/launches/0123abcd/stop")
        assert stopped.status == 200
        instance = f"label=umcodex.instance={instance_of(data)}"
        assert [
            "docker", "ps", "-a", "-q", "--filter", instance, "--filter", "label=umcodex.launch=0123abcd",
        ] in fake.commands  # fmt: skip
        assert ["docker", "rm", "-f", "c0ffee"] in fake.commands
        assert not [c for c in fake.commands if c[:2] == ["docker", "rm"] and "c0ffee" not in c]

    try:
        with_server(test, fake_docker=fake)
    finally:
        lock.release()
    assert running_launches(data) == []


def test_a_setup_with_a_running_launch_cant_be_deleted(folders_here):
    data = data_dir()
    setup = Setup(id="thesis-abc123", name="thesis", working=str(folders_here["thesis"]))
    SetupStore().save(setup)
    folder = launches_dir(data) / "0123abcd"
    folder.mkdir(parents=True)
    lock = LaunchLock(folder / "lock")
    assert lock.acquire()
    write_launch_info(folder, setup)

    async def test(h: Harness) -> None:
        await h.sign_in()
        answer = await h.delete("/api/setups/thesis-abc123")
        assert answer.status == 409 and "Stop" in (await answer.json())["error"]

    try:
        with_server(test)
    finally:
        lock.release()


def test_the_launch_lock_waits_a_moment_for_a_probe():
    path = data_dir() / "x" / "lock"
    probe = LaunchLock(path)
    assert probe.acquire()
    threading.Timer(0.2, probe.release).start()
    assert LaunchLock(path).acquire(tries=40)


# --- The key -----------------------------------------------------------------------


def test_the_key_form_saves_the_key_and_never_echoes_or_logs_it(memory_keychain, caplog):
    caplog.set_level(logging.DEBUG)
    checked = []

    def check(key: str) -> str:
        checked.append(key)
        return "ok"

    async def test(h: Harness) -> None:
        await h.sign_in()
        answer = await h.post("/api/key", {"key": FAKE_KEY})
        text = await answer.text()
        assert answer.status == 200 and FAKE_KEY not in text
        assert "accepted" in (await answer.json())["words"]
        assert credentials.api_key() == FAKE_KEY and checked == [FAKE_KEY]
        bad = await h.post("/api/key", {"key": "sk-secret with-a-space"})
        assert bad.status == 400 and "sk-secret" not in await bad.text()
        broken = await h.client.post(
            "/api/key",
            data='{"key": "' + FAKE_KEY + '"',  # not JSON
            headers={"Content-Type": "application/json", "Origin": h.origin},
        )
        assert broken.status == 400 and FAKE_KEY not in await broken.text()
        assert (await (await h.client.get("/api/state")).json())["key"] == {"saved": True}

    with_server(test, check_key=check)
    assert FAKE_KEY not in caplog.text


def test_a_refused_key_isnt_saved(memory_keychain):
    async def test(h: Harness) -> None:
        await h.sign_in()
        answer = await h.post("/api/key", {"key": FAKE_KEY})
        assert answer.status == 400 and "refused" in (await answer.json())["error"]
        assert FAKE_KEY not in await answer.text()
        assert not credentials.has_api_key()

    with_server(test, check_key=lambda key: "refused")


def test_the_key_field_is_masked_and_not_offered_for_saving():
    static = REPO / "src" / "umcodex" / "ui" / "static"
    page = (static / "index.html").read_text()
    field = re.search(r'<input id="key-input"[^>]*>', page, re.S).group(0)
    # Dots, but not a password field (so no "save password?"); password managers asked to keep off.
    assert 'type="text"' in field and 'class="masked"' in field
    assert 'autocomplete="new-password"' in field
    assert "data-1p-ignore" in field and 'data-lpignore="true"' in field
    assert "-webkit-text-security: disc" in (static / "app.css").read_text()
    script = (static / "app.js").read_text()
    assert 'if (!CSS.supports("-webkit-text-security", "disc")) keyField.type = "password"' in script
    # Cancel, Escape or saving empties it.
    assert 'function hideKeyPanel() {\n  keyField.value = "";' in script
    assert 'if (e.key === "Escape") {\n    keyField.value = "";' in script
    assert "<dialog" not in page.split('id="key-panel"')[0].rsplit("<section", 1)[-1]  # inline, not a pop-up


def test_destructive_questions_start_on_cancel():
    static = REPO / "src" / "umcodex" / "ui" / "static"
    page = (static / "index.html").read_text()
    assert page.index('id="confirm-no"') < page.index('id="confirm-yes"')
    assert 'document.getElementById("confirm-no").focus()' in (static / "app.js").read_text()


# --- Docker status ----------------------------------------------------------------


def test_docker_state_on_a_mac():
    async def test(h: Harness) -> None:
        await h.sign_in()
        state = await (await h.client.get("/api/state")).json()
        assert state["docker"]["state"] == "ready" and not state["docker"]["can_open"]
        opened = await h.post("/api/docker/open")
        assert opened.status == 200
        assert ["open", "-g", "-a", "Docker"] in h.launcher.run.commands  # type: ignore[attr-defined]
        fix = await h.post("/api/docker/fix")
        assert fix.status == 400

    with_server(test)


def test_on_windows_a_refused_vm_offers_the_fix():
    class Doctor:
        fixed = False

        def state(self, *, fresh: bool = False) -> str:
            return "ready" if self.fixed else "vm-refused"

        def fix(self):
            self.fixed = True
            from umcodex.windows_vm import FixResult

            return FixResult("fixed")

    doctor = Doctor()

    async def test(h: Harness) -> None:
        await h.sign_in()
        state = await (await h.client.get("/api/state")).json()
        assert state["docker"]["can_fix"] and "administrator prompt" in state["docker"]["fix_explained"]
        fixed = await (await h.post("/api/docker/fix")).json()
        assert fixed == {"outcome": "fixed", "words": "Fixed: Docker is running again."}
        state = await (await h.client.get("/api/state")).json()
        assert state["docker"]["state"] == "ready"

    with_server(test, platform="win32", windows_doctor=doctor)


# --- The opener's command lines ------------------------------------------------------

NASTY = [
    "plain",
    "with space",
    "o'brien",
    'say "hi"',
    "a;b&c|d$(e)`f`",
    "$Env:PATH; Remove-Item x",
    "it\u2019s",
    "--setup",
    "x y\\",
    'q\\"z w',
]
# Windows PowerShell 5.1 can't pass a double quote on reliably: refused (native_arg).
WINDOWS_NASTY = [text for text in NASTY if '"' not in text]


def echo_program(tmp_path: Path, name: str) -> list[str]:
    """A program, at a path with odd characters, that writes its arguments as JSON."""
    folder = tmp_path / name
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "echo args.py"
    script.write_text(
        "import json, os, sys\n"
        "out = {'argv': sys.argv[1:], 'data': os.environ.get('UMCODEX_DATA_DIR')}\n"
        "open(os.environ['ECHO_OUT'], 'w', encoding='utf-8').write(json.dumps(out))\n"
    )
    return [sys.executable, str(script)]


@pytest.mark.skipif(sys.platform == "win32", reason="the Mac's .command file runs in sh")
@pytest.mark.parametrize("setup_id", NASTY)
def test_the_mac_command_file_runs_exactly_the_launch(tmp_path, setup_id, monkeypatch):
    program = echo_program(tmp_path, "o'brien \"x\"")
    env = {"UMCODEX_DATA_DIR": "/tmp/a b'c", "UMCODEX_UPSTREAM": "http://127.0.0.1:9"}
    script = opening.mac_script(program, setup_id, env)
    path = tmp_path / "start.command"
    path.write_text(script)
    path.chmod(0o700)
    out = tmp_path / "out.json"
    subprocess.run([str(path)], check=True, env={**os.environ, "ECHO_OUT": str(out)})
    assert json.loads(out.read_text()) == {"argv": ["launch", "--setup", setup_id], "data": "/tmp/a b'c"}
    assert not path.exists()  # it removed itself


def test_the_mac_opener_opens_one_command_file_in_terminal(tmp_path):
    ran = []

    def run(command, **kwargs):
        ran.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    terminal = opening.TerminalOpener(
        program=["/x/um-codex"], platform="darwin", environ={"UMCODEX_DATA_DIR": "/d", "HOME": "/h"},
        run=run, folder=tmp_path,
    )  # fmt: skip
    terminal.open("thesis-abc123")
    assert len(ran) == 1 and ran[0][:3] == ["open", "-a", "Terminal"]
    file = Path(ran[0][3])
    assert file.parent == tmp_path and file.suffix == ".command"
    assert file.stat().st_mode & 0o777 == 0o700
    text = file.read_text()
    assert text.splitlines() == [
        "#!/bin/sh",
        'rm -f "$0"',
        "env UMCODEX_DATA_DIR=/d /x/um-codex launch --setup thesis-abc123",
    ]
    assert "HOME" not in text  # only UM-Codex's own development settings


def test_native_arguments_survive_windows_powershell_5():
    # What the program gets back (CommandLineToArgvW) from PowerShell 5.1's quoting.
    for quoted in ('say "hi"', 'a\\"b'):
        with pytest.raises(opening.OpenFailed):
            opening.native_arg(quoted)
    assert opening.native_arg("C:\\a b\\") == "C:\\a b\\\\"
    assert opening.native_arg("C:\\ab\\") == "C:\\ab\\"
    assert opening.native_arg("plain") == "plain"


def test_the_windows_command_is_encoded_and_quoted(tmp_path):
    terminal = Path("C:/Users/o'brien/AppData/Local/Microsoft/WindowsApps/wt.exe")
    for setup_id in WINDOWS_NASTY:
        program = ["C:\\Users\\o'brien\\um codex\\python.exe", "-m", "umcodex"]
        env = {"UMCODEX_DATA_DIR": "C:\\d'x"}
        with_wt = opening.windows_command(
            program, setup_id, env, terminal=terminal, powershell="powershell.exe"
        )
        assert with_wt[:7] == [str(terminal), "-w", "new", "new-tab", "--title", "UM-Codex", "--"]
        assert with_wt[7:12] == ["powershell.exe", "-NoProfile", "-NoExit", "-EncodedCommand", with_wt[11]]
        assert not any(";" in part for part in with_wt)  # Windows Terminal splits at ";"
        plain = opening.windows_command(program, setup_id, env, terminal=None, powershell="powershell.exe")
        assert plain == with_wt[7:]
        script = base64.b64decode(with_wt[11]).decode("utf-16-le")
        last = script.splitlines()[-1]
        # Every argument is one single-quoted PowerShell string, quotes doubled.
        parts = re.findall(r"'((?:[^'\u2018\u2019\u201a\u201b]|''|\u2018\u2018|\u2019\u2019)*)'", last)
        undo = [p.replace("''", "'").replace("\u2019\u2019", "\u2019") for p in parts]
        assert undo == [opening.native_arg(a) for a in [*program, "launch", "--setup", setup_id]]
        assert last.startswith("& '")
        assert "$Env:UMCODEX_DATA_DIR = 'C:\\d''x'" in script and "$Env:PYTHONUTF8 = '1'" in script


@pytest.mark.skipif(sys.platform != "win32", reason="runs Windows PowerShell")
@pytest.mark.parametrize("setup_id", WINDOWS_NASTY)
def test_the_windows_command_runs_exactly_the_launch(tmp_path, setup_id):
    program = echo_program(tmp_path, "o'brien x")
    script = opening.powershell_script(program, setup_id, {"UMCODEX_DATA_DIR": "C:\\a b'c"})
    out = tmp_path / "out.json"
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", opening.encoded(script)],
        check=True,
        env={**os.environ, "ECHO_OUT": str(out)},
    )
    assert json.loads(out.read_text(encoding="utf-8")) == {
        "argv": ["launch", "--setup", setup_id],
        "data": "C:\\a b'c",
    }


def test_an_odd_setup_id_isnt_opened(tmp_path):
    ran = []
    terminal = opening.TerminalOpener(
        program=["/x/um-codex"], platform="darwin", environ={}, folder=tmp_path,
        run=lambda command, **_: ran.append(command),
    )  # fmt: skip
    for odd in ("", "-rf", "a b", "a;b", "x" * 200, "a/b"):
        with pytest.raises(opening.OpenFailed):
            terminal.open(odd)
    assert ran == [] and list(tmp_path.iterdir()) == []


def test_the_codex_app_opener_starts_the_launch_in_the_background(tmp_path):
    started = []

    def popen(command, **options):
        started.append((command, options))

    app = opening.CodexAppOpener(
        program=["/py", "-m", "umcodex"], platform="darwin", popen=popen,
        find=lambda: Path("/Applications/ChatGPT.app"), folder=tmp_path,
    )  # fmt: skip
    assert app.available() and app.reason() is None
    app.open("thesis-a1b2c3")
    command, options = started[0]
    assert command == ["/py", "-m", "umcodex", "launch", "--setup", "thesis-a1b2c3", "--open", "app"]
    assert options["start_new_session"] is True and options["stdin"] == subprocess.DEVNULL
    assert (tmp_path / "app-launch.log").exists()
    with pytest.raises(opening.OpenFailed):
        app.open("../odd")


def test_the_codex_app_opener_says_why_it_cant(tmp_path, monkeypatch):
    monkeypatch.delenv("UMCODEX_WINDOWS_CODEX_APP", raising=False)
    missing = opening.CodexAppOpener(platform="darwin", find=lambda: None, folder=tmp_path)
    assert not missing.available() and "chatgpt.com/download" in (missing.reason() or "")
    with pytest.raises(opening.OpenFailed):
        missing.open("thesis")
    from umcodex import codex_app, codex_app_windows

    monkeypatch.setattr(codex_app_windows, "openssh_installed", lambda: True)
    windows = opening.CodexAppOpener(platform="win32", find=lambda: Path("C:/x"), folder=tmp_path)
    assert windows.reason() is None  # on Windows too (experimental)

    monkeypatch.setattr(codex_app, "WINDOWS_COPY", False)  # switched off again
    assert "Mac only" in (windows.reason() or "")
    monkeypatch.setenv("UMCODEX_WINDOWS_CODEX_APP", "1")  # the hands-on test's switch
    assert windows.reason() is None
    assert "Microsoft Store" in (
        opening.CodexAppOpener(platform="win32", find=lambda: None, folder=tmp_path).reason() or ""
    )


def test_the_codex_app_is_looked_for_at_most_once_a_minute():
    looks = []
    app = opening.CodexAppOpener(platform="darwin", find=lambda: looks.append(1) or None)
    for _ in range(5):
        app.reason()
    assert len(looks) == 1


# --- launch --setup ---------------------------------------------------------------


def test_launch_setup_starts_without_asking(folders_here, monkeypatch, capsys):
    from umcodex import cli

    setup = Setup(id="thesis-abc123", name="my thesis", working=str(folders_here["thesis"]))
    SetupStore().save(setup)
    assert cli._chosen_without_asking(SetupStore(), "nope") is None
    assert "no saved setup" in capsys.readouterr().out
    chosen = cli._chosen_without_asking(SetupStore(), "my thesis")
    assert chosen is not None and chosen[0].id == "thesis-abc123"
    assert SetupStore().last_used().id == "thesis-abc123"  # type: ignore[union-attr]
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("asked a question"))
    assert cli._chosen_without_asking(SetupStore(), "thesis-abc123") is not None


def test_launch_setup_stops_at_a_refused_or_moved_folder(folders_here, tmp_path, capsys):
    from umcodex import cli

    SetupStore().save(Setup(id="home-1", name="home", working=str(Path.home())))
    assert cli._chosen_without_asking(SetupStore(), "home-1") is None
    assert "can't be used as it is" in capsys.readouterr().out
    link = tmp_path / "link"
    link.symlink_to(folders_here["thesis"])
    SetupStore().save(Setup(id="linked-1", name="linked", working=str(link)))
    assert cli._chosen_without_asking(SetupStore(), "linked-1") is None
    out = capsys.readouterr().out
    assert "now goes to" in out and "Not started" in out


def test_the_cli_takes_launch_setup_and_ui(monkeypatch):
    from umcodex import cli

    seen = {}
    monkeypatch.setattr(cli, "_launch", lambda args, **kw: seen.update(kw, args=args) or 0)
    assert cli.main(["launch", "--setup", "x y"]) == 0
    assert seen == {"from_app": False, "setup_name": "x y", "args": [], "in_app": False, "local": False}
    assert cli.main(["launch", "--setup", "x y", "--open", "app"]) == 0
    assert seen["in_app"] is True
    monkeypatch.setattr(server, "detach", lambda open_browser: 7)
    monkeypatch.setattr(server, "main", lambda open_browser: 8 if open_browser else 9)
    assert cli.main(["ui", "--detach"]) == 7
    assert cli.main(["ui"]) == 8
    assert cli.main(["ui", "--no-browser"]) == 9


# --- One at a time -------------------------------------------------------------------


def test_a_second_ui_opens_the_running_one_again(monkeypatch):
    data = data_dir()
    data.mkdir(parents=True, exist_ok=True)
    started = threading.Event()
    stop: dict[str, object] = {}
    urls: list[str] = []

    def serve_in_thread() -> None:
        async def go() -> None:
            event = asyncio.Event()
            stop["event"], stop["loop"] = event, asyncio.get_running_loop()
            await server.serve(
                launcher_for_tests(),
                data=data,
                say=lambda _: None,
                ready=lambda port, url: started.set(),
                stop=event,
            )

        asyncio.run(go())

    thread = threading.Thread(target=serve_in_thread)
    thread.start()
    try:
        assert started.wait(10)
        info = json.loads((data / server.UI_INFO).read_text())
        assert (data / server.UI_INFO).stat().st_mode & 0o777 == 0o600 or sys.platform == "win32"
        assert server.reopen(data, say=lambda _: None, opening=urls.append) == 0
        assert re.fullmatch(rf"http://127\.0\.0\.1:{info['port']}/sign-in\?token=[\w-]+", urls[0])
        import httpx

        with httpx.Client() as client:
            signed = client.get(urls[0], follow_redirects=False)
            assert signed.status_code == 303 and "HttpOnly" in signed.headers["set-cookie"]
        # An uninstall closes it (its files are about to go).
        held = LaunchLock(data / server.UI_LOCK)
        assert held.acquire()  # serve() itself doesn't hold the lock: main() does
        held.release()
        server._ask_running(data, "quit")
        thread.join(10)
        assert not thread.is_alive()
    finally:
        if thread.is_alive():
            loop, event = stop["loop"], stop["event"]
            loop.call_soon_threadsafe(event.set)  # type: ignore[attr-defined]
            thread.join(10)
    assert not (data / server.UI_INFO).exists()


def test_the_ui_lock_sends_a_second_one_to_the_first(monkeypatch):
    data = data_dir()
    data.mkdir(parents=True, exist_ok=True)
    held = LaunchLock(data / server.UI_LOCK)
    assert held.acquire()
    asked = []
    monkeypatch.setattr(server, "reopen", lambda folder, say, opening: asked.append(folder) or 0)
    try:
        assert server.main(say=lambda _: None) == 0
    finally:
        held.release()
    assert asked == [data]


def test_close_running_leaves_a_free_lock_alone():
    data = data_dir()
    data.mkdir(parents=True, exist_ok=True)
    (data / server.UI_LOCK).write_text("")
    began = time.monotonic()
    server.close_running(data)
    assert time.monotonic() - began < 1


def test_the_server_ends_when_the_page_has_been_away(monkeypatch):
    data = data_dir()
    data.mkdir(parents=True, exist_ok=True)
    began = time.monotonic()
    asyncio.run(
        server.serve(
            launcher_for_tests(), data=data, say=lambda _: None, ready=lambda p, u: None, idle_seconds=0.3
        )
    )
    assert time.monotonic() - began < 10


# --- The page's files ----------------------------------------------------------------


def test_the_page_shows_the_package_mark_and_builds_with_text_only():
    static = REPO / "src" / "umcodex" / "ui" / "static"
    assert (static / "mark.svg").read_bytes() == (REPO / "branding" / "um-codex-mark.svg").read_bytes()
    script = (static / "app.js").read_text()
    assert ".innerHTML" not in script and "eval(" not in script
    assert '"Content-Type": "application/json"' in script
    page = (static / "index.html").read_text()
    assert "<script>" not in page and "style=" not in page  # the CSP allows only the files


def test_setups_keep_open_in(tmp_path):
    store = SetupStore()
    store.save(Setup(id="a-1", name="a", working=str(tmp_path), open_in="terminal"))
    assert store.get("a-1").open_in == "terminal"  # type: ignore[union-attr]
    raw = store.path.read_text(encoding="utf-8").replace('open_in = "terminal"', 'open_in = "elsewhere"')
    store.path.write_text(raw, encoding="utf-8")
    # Not understood (or not saved at all): the Codex app, the default.
    assert store.get("a-1").open_in == "codex-app"  # type: ignore[union-attr]


# --- Review fixes ----------------------------------------------------------------


def test_parallel_changes_to_setups_are_all_kept(folders_here):
    """Ten Duplicates at once (the page's API runs them on threads) all land."""
    store = SetupStore()
    original = Setup(id="thesis-abc123", name="thesis", working=str(folders_here["thesis"]))
    store.save(original)
    launcher = launcher_for_tests()
    threads = [threading.Thread(target=launcher.duplicate, args=("thesis-abc123",)) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(SetupStore().all()) == 11
    assert not list(store.path.parent.glob(".setups.toml.*.tmp"))


def test_changes_from_other_processes_are_all_kept(folders_here):
    """A launch's mark_used (another process) can't undo the page's saves."""
    script = (
        "import sys\n"
        "from umcodex.setups import Setup, SetupStore\n"
        "for n in range(15):\n"
        "    SetupStore().save(Setup(id=f'{sys.argv[1]}-{n}', name='x', working=sys.argv[2]))\n"
        "    SetupStore().mark_used(f'{sys.argv[1]}-{n}')\n"
    )
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", script, f"p{i}", str(folders_here["thesis"])], env=dict(os.environ)
        )
        for i in range(4)
    ]
    assert [worker.wait(60) for worker in workers] == [0] * 4
    assert len(SetupStore().all()) == 60


def test_every_problem_in_the_form_comes_back_at_once_in_order(folders_here, home_with_keys):
    async def test(h: Harness) -> None:
        await h.sign_in()
        body = {
            "name": "a\u202eb",
            "working": str(home_with_keys / ".ssh"),
            "folders": [{"path": "relative"}],
            "model": "no good",
            "approvals": "sometimes",
            "open_in": "elsewhere",
        }
        answer = await (await h.post("/api/setups", body)).json()
        assert list(answer["errors"]) == ["working", "name", "folders", "approvals", "model", "open_in"]
        assert answer["field"] == "working" and "SSH keys" in answer["errors"]["working"]
        assert "isn't a full path" in answer["errors"]["folders"]

    with_server(test)


def test_start_waits_for_docker(folders_here):
    credentials.save_api_key(FAKE_KEY)

    class Stopped(FakeDocker):
        def __call__(self, command, **kwargs):
            done = super().__call__(command, **kwargs)
            code = 1 if command[:2] == ["docker", "info"] else 0
            return subprocess.CompletedProcess(command, code, done.stdout, "")

    async def test(h: Harness) -> None:
        await h.sign_in()
        made = await (await h.post("/api/setups", setup_body(folders_here["thesis"]))).json()
        answer = await h.post(f"/api/setups/{made['id']}/start", {})
        body = await answer.json()
        assert answer.status == 409 and body["error"] == "Docker Desktop isn't running. Open it first."
        assert body["field"] == "docker"
        assert h.launcher.openers["terminal"].opened == []  # type: ignore[attr-defined]

    with_server(test, fake_docker=Stopped(), run=Stopped())


def test_one_docker_check_at_a_time():
    calls = []
    release = threading.Event()

    def slow(command, **kwargs):
        calls.append(command)
        release.wait(5)
        return subprocess.CompletedProcess(command, 0, "", "")

    launcher = launcher_for_tests(run=slow)
    first = threading.Thread(target=launcher.docker_state)
    first.start()
    time.sleep(0.2)
    assert launcher.docker_state() == "unknown"  # the running check's answer comes next time
    release.set()
    first.join()
    assert len(calls) == 1 and launcher.docker_state() == "ready"


def test_the_picker_tells_a_cancel_from_a_failure():
    picker.outcome(0, "")
    picker.outcome(1, "execution error: User canceled. (-128)", platform="darwin")
    with pytest.raises(picker.PickerFailed, match="Not authorized"):
        picker.outcome(1, "execution error: Not authorized to send Apple events. (-1743)", platform="darwin")
    with pytest.raises(picker.PickerFailed):
        picker.outcome(1, "Add-Type : failed", platform="win32")


def test_a_picker_failure_shows_on_the_page(monkeypatch):
    async def broken(*, start_in=None):
        raise picker.PickerFailed("The folder picker couldn't be shown (no display). Try again.")

    monkeypatch.setattr(picker, "pick_folder", broken)

    async def test(h: Harness) -> None:
        await h.sign_in()
        answer = await h.post("/api/folders/pick", {})
        assert answer.status == 409 and "couldn't be shown" in (await answer.json())["error"]

    with_server(test)


def test_old_command_files_are_swept(tmp_path):
    folder = tmp_path / "ui"
    folder.mkdir()
    old, new, other = folder / "start-old.command", folder / "start-new.command", folder / "keep.txt"
    for file in (old, new, other):
        file.write_text("x")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    os.utime(other, (time.time() - 3600, time.time() - 3600))
    server.sweep_command_files(tmp_path)
    assert not old.exists() and new.exists() and other.exists()


class FakeChild:
    def __init__(self, code=None, then=None):
        self.code = code
        self.then = then

    def poll(self):
        if self.then:
            self.then()
            self.then = None
        return self.code


def test_detach_returns_once_its_server_is_up():
    data = data_dir()
    alerts = []

    def popen(command, **options):
        assert command[-1] == "ui" and options["env"]["PYTHONUTF8"] == "1"
        nonce = options["env"][server.NONCE_ENV]
        return FakeChild(then=lambda: (data / server.UI_INFO).write_text(json.dumps({"nonce": nonce})))

    assert server.detach(popen=popen, alert=alerts.append, wait=3) == 0
    assert alerts == []
    # A second one hands over to the first and ends with 0: fine too.
    assert server.detach(popen=lambda c, **o: FakeChild(code=0), alert=alerts.append, wait=3) == 0
    assert alerts == []


def test_detach_says_so_in_a_message_box_when_it_fails(caplog):
    caplog.set_level(logging.INFO)
    data = data_dir()
    (data).mkdir(parents=True, exist_ok=True)
    (data / server.UI_INFO).write_text(json.dumps({"nonce": "an-older-one"}))
    alerts = []

    def popen(command, stdout, stderr, **options):
        assert stdout == subprocess.DEVNULL  # its normal output has the sign-in link
        stderr.write(b"Traceback: ModuleNotFoundError: no module named x\n")
        return FakeChild(code=1)

    assert server.detach(popen=popen, alert=alerts.append, wait=3) == 1
    assert "didn't start" in alerts[0] and str(data / "um-codex.log") in alerts[0]
    assert "ModuleNotFoundError" in caplog.text
    # And one that never comes up (no ui.json with its nonce in time).
    assert server.detach(popen=lambda c, **o: FakeChild(), alert=alerts.append, wait=0.3) == 1
    assert len(alerts) == 2


def test_the_mac_message_box_gets_the_text_as_an_argument():
    ran = []
    server.show_alert('a "quoted" message', platform="darwin", run=lambda c, **k: ran.append(c))
    assert ran[0][0] == "osascript" and ran[0][-1] == 'a "quoted" message'
    assert "display dialog (item 1 of argv)" in " ".join(ran[0])


def test_a_failing_server_is_logged(monkeypatch, caplog):
    async def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(server, "serve", broken)
    said = []
    assert server.main(say=said.append) == 1
    assert "the launcher window failed" in caplog.text and "boom" in caplog.text
    assert "um-codex.log" in said[-1]


def test_a_newer_install_is_noticed_and_reopened(monkeypatch):
    import umcodex.update as update

    class Installed:
        def __init__(self, *args, **kwargs):
            pass

        def pointer(self):
            return ("9.9.9", "0.1.0a1")

        def running_version(self):
            return "0.1.0a1"

    monkeypatch.setattr(update, "Layout", Installed)
    quits = []

    async def test(h: Harness) -> None:
        await h.sign_in()
        state = await (await h.client.get("/api/state")).json()
        assert state["installed"] == "9.9.9"
        assert (await h.post("/api/reopen")).status == 409  # no server to end in this test
        h.launcher.quit = lambda: quits.append(1)
        assert await (await h.post("/api/reopen")).json() == {"reopening": True}
        assert quits == [1] and h.launcher.reopen_after

    with_server(test)


def test_a_development_copy_notices_nothing(monkeypatch):
    launcher = launcher_for_tests()
    assert launcher.installed_version() is None  # not run from an installed layout


def test_stop_requests_are_logged(caplog):
    caplog.set_level(logging.INFO)
    launcher = launcher_for_tests()
    with pytest.raises(server.Invalid):
        launcher.stop("0123abcd")
    assert "Stop asked for launch 0123abcd" in caplog.text


def test_the_data_folder_override_is_resolved(monkeypatch, tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    monkeypatch.setenv("UMCODEX_DATA_DIR", str(tmp_path / "link"))
    assert data_dir() == Path(os.path.realpath(tmp_path / "real"))


def test_the_launch_logs_how_the_agent_ended(caplog):
    from umcodex.launch import log_agent_state

    caplog.set_level(logging.INFO)

    def run(command, **kwargs):
        if command[1] == "inspect":
            out = "status=exited exit_code=137 oom_killed=false finished_at=2026-10-01T21:00:00Z"
        else:
            out = "watchdog: launch gone, ending\n"
        return subprocess.CompletedProcess(command, 0, out, "")

    log_agent_state(Docker(run), "umcodex-x-agent", "0123abcd")
    assert "exit_code=137" in caplog.text and "watchdog: launch gone, ending" in caplog.text


# --- M7: one click -------------------------------------------------------------------


def test_a_folder_is_all_a_new_setup_needs(folders_here):
    """The first run's "Choose a folder to work in": the page sends only the
    folder; the setup is named after it (made unique), with the internet on,
    commands without asking, the default model, and the Codex app when it's
    installed."""
    credentials.save_api_key(FAKE_KEY)
    app = FakeAppOpener()

    async def test(h: Harness) -> None:
        await h.sign_in()
        state = await (await h.client.get("/api/state")).json()
        assert state["default_open_in"] == "codex-app" and state["last_used"] is None
        made = await (await h.post("/api/setups", {"working": str(folders_here["thesis"])})).json()
        assert made["name"] == "thesis"
        saved = SetupStore().get(made["id"])
        assert saved is not None
        assert (saved.internet, saved.browser, saved.approvals) == (True, False, "never")
        assert (saved.model, saved.open_in) == ("gpt-5.6-terra", "codex-app")
        again = await (await h.post("/api/setups", {"working": str(folders_here["thesis"])})).json()
        blank = {"working": str(folders_here["thesis"]), "name": " "}
        third = await (await h.post("/api/setups", blank)).json()
        assert (again["name"], third["name"]) == ("thesis 2", "thesis 3")
        # The page's own choices win over the defaults.
        chosen = setup_body(folders_here["data"], name="", internet=False, open_in="terminal")
        plain = await (await h.post("/api/setups", chosen)).json()
        assert (plain["name"], plain["internet"], plain["open_in"]) == ("data", False, "terminal")

    with_server(test, openers={"terminal": FakeOpener(), "codex-app": app})


def test_without_the_codex_app_a_new_setup_opens_in_terminal(folders_here):
    async def test(h: Harness) -> None:
        await h.sign_in()
        assert (await (await h.client.get("/api/state")).json())["default_open_in"] == "terminal"
        made = await (await h.post("/api/setups", {"working": str(folders_here["thesis"])})).json()
        assert made["open_in"] == "terminal"

    with_server(test)  # the Codex app isn't installed here


def test_an_edit_without_a_name_keeps_the_name_and_rename_changes_only_it(folders_here):
    async def test(h: Harness) -> None:
        await h.sign_in()
        thesis = folders_here["thesis"]
        made = await (await h.post("/api/setups", setup_body(thesis, name="My thesis"))).json()
        edited = await h.put(f"/api/setups/{made['id']}", setup_body(thesis, name="", internet=True))
        assert (await edited.json())["name"] == "My thesis"
        renamed = await (await h.post(f"/api/setups/{made['id']}/rename", {"name": "  Chapter   2 "})).json()
        assert renamed["name"] == "Chapter 2" and renamed["internet"] is True
        bad = await h.post(f"/api/setups/{made['id']}/rename", {"name": "a‮b"})
        assert bad.status == 400 and (await bad.json())["field"] == "name"
        assert (await h.post("/api/setups/nope/rename", {"name": "x"})).status == 404
        saved = SetupStore().get(made["id"])
        assert saved is not None and saved.name == "Chapter 2"

    with_server(test)


def test_a_card_knows_its_moved_folders_and_start_says_so(folders_here, tmp_path):
    credentials.save_api_key(FAKE_KEY)
    link = tmp_path / "link"
    link.symlink_to(folders_here["thesis"])
    SetupStore().save(Setup(id="linked-a1", name="linked", working=str(link), open_in="terminal"))

    async def test(h: Harness) -> None:
        await h.sign_in()
        state = await (await h.client.get("/api/state")).json()
        assert state["setups"][0]["moved"] == [{"saved": str(link), "now": str(folders_here["thesis"])}]
        refused = await h.post("/api/setups/linked-a1/start", {})
        assert refused.status == 409 and (await refused.json())["field"] == "moved"

    with_server(test)


def test_start_can_add_the_ssh_line_in_the_same_click(folders_here, ssh_home):
    """The card's "Add the line and start": the explanation is on the card,
    and the click is the consent. Without it, nothing is written."""
    credentials.save_api_key(FAKE_KEY)
    app = FakeAppOpener()

    async def test(h: Harness) -> None:
        await h.sign_in()
        made = await (await h.post("/api/setups", {"working": str(folders_here["thesis"])})).json()
        assert made["open_in"] == "codex-app"
        refused = await h.post(f"/api/setups/{made['id']}/start", {"allow_ssh_include": "yes"})
        assert (await refused.json())["field"] == "ssh_include"
        assert not (ssh_home / ".ssh" / "config").exists() and app.opened == []
        started = await h.post(f"/api/setups/{made['id']}/start", {"allow_ssh_include": True})
        assert (await started.json()) == {"opened": "Codex app", "in_background": True}
        assert (ssh_home / ".ssh" / "config").read_text() == "Include ~/.ssh/um-codex/config\n"
        assert app.opened == [made["id"]]
        assert (await (await h.client.get("/api/state")).json())["last_used"] == made["id"]

    with_server(test, openers={"terminal": FakeOpener(), "codex-app": app})


def test_models_come_newest_first_with_the_default_kept(folders_here):
    async def test(h: Harness) -> None:
        await h.sign_in()
        answer = await (await h.client.get("/api/models")).json()
        assert answer["default"] == "gpt-5.6-terra"
        assert answer["models"] == [
            "gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
            "gpt-5.5", "gpt-5.4",
        ]  # fmt: skip

    served = ["gpt-5.4", "gpt-5.5", "gpt-5.6-luna", "gpt-6-luna", "gpt-5.6-sol", "gpt-6-astra", "gpt-6-sol"]
    with_server(test, list_models=lambda: list(served))


def test_the_page_starts_at_once_and_asks_only_before_stop_and_delete():
    script = (REPO / "src" / "umcodex" / "ui" / "static" / "app.js").read_text()
    assert "/prepare" not in script  # no summary page before a start
    # Its definition, Stop, Delete, Windows' fix, and choosing "On this computer" (M4: the one
    # deliberate pop-up when the choice is made; Start never asks).
    assert script.count("confirmBox(") == 6  # and Stop on this computer (its own words)
    assert "/api/codex-app/allow" not in script and "allow_ssh_include: true" in script
    # The safety facts, short, on every card and under the form.
    for words in ("your real files, no undo", "could send what it can read anywhere", "only the model"):
        assert words in script


# --- M7: Update from the launcher ---------------------------------------------------


class FakeUpdate:
    """`um-codex update --from-launcher`, as the launcher runs it: prints `lines`."""

    def __init__(self, lines: list[str], code: int = 0) -> None:
        self.lines, self.code, self.commands = lines, code, []

    def __call__(self, command, **options):
        self.commands.append((command, options))
        # It writes to the file it's given, as the real one does in its own session.
        options["stdout"].write("".join(line + "\n" for line in self.lines).encode())
        code = self.code

        class Child:
            def poll(self) -> int:
                return code

        return Child()


def wait_for_update(h: Harness) -> dict:
    deadline = time.monotonic() + 10
    while h.launcher.update_job.phase == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    return {"phase": h.launcher.update_job.phase, "words": h.launcher.update_job.words}


UPDATE_OUTPUT = [
    "Checking for a newer UM-Codex...",
    "UM-Codex 0.1.0a5 is available (this is 0.1.0a4). Downloading it...",
    "Installing UM-Codex 0.1.0a5 beside this one...",
    "  Resolved 34 packages from /Users/someone/Library/Application Support/UM-Codex/app",
    "Downloading its container images...",
    "",
    "Updated to UM-Codex 0.1.0a5. The next launch uses it.",
]


def test_update_runs_the_update_command_and_shows_only_its_own_words(caplog):
    fake = FakeUpdate(UPDATE_OUTPUT)
    seen: list[str | None] = []

    async def test(h: Harness) -> None:
        await h.sign_in()
        h.launcher.status.update = "0.1.0a5"
        original = h.launcher._run_update

        def watched() -> None:
            # Every word the page could be shown while it runs.
            seen.append(h.launcher.update_job.words)
            original()

        h.launcher._run_update = watched  # type: ignore[method-assign]
        answer = await h.post("/api/update")
        assert answer.status == 200 and (await answer.json())["phase"] == "running"
        assert wait_for_update(h) == {"phase": "updated", "words": "Updated to UM-Codex 0.1.0a5."}
        state = await (await h.client.get("/api/state")).json()
        done = {"phase": "updated", "words": "Updated to UM-Codex 0.1.0a5.", "version": "0.1.0a5"}
        assert state["update"] == {"available": None, **done}
        ((command, options),) = fake.commands
        assert command[-2:] == ["update", "--from-launcher"] and command[1:3] == ["-m", "umcodex"]
        assert options["stdin"] == subprocess.DEVNULL and options["stderr"] == subprocess.STDOUT
        if sys.platform != "win32":
            assert options["start_new_session"] is True  # it goes on if this window ends
        assert (h.launcher.data / "ui" / "update.log").read_text().endswith("The next launch uses it.\n")

    with caplog.at_level(logging.INFO):
        with_server(test, spawn=fake)
    allowed = {words for _, words in server.UPDATE_STEPS} | {"Starting the update…"}
    assert all(word in allowed for word in seen)
    assert "update: Updated to UM-Codex 0.1.0a5" in caplog.text  # its output goes to the log


def test_update_progress_words_never_carry_what_the_update_printed():
    """The words come from a fixed list, whatever the update prints (a path,
    a token-looking string): none of its text reaches the page."""
    secret = "sk-not-a-real-key-0123456789"
    printed = [f"Installing UM-Codex {secret}", f"oops {secret}"]
    launcher = launcher_for_tests(spawn=FakeUpdate(printed, code=1))
    launcher.update_job = server.UpdateJob("running")
    launcher._run_update()
    assert launcher.update_job.phase == "failed"
    assert launcher.update_job.words == server.UPDATE_FAILED and "um-codex.log" in server.UPDATE_FAILED
    assert secret not in json.dumps(launcher.state()["update"])
    for _, words in server.UPDATE_STEPS:
        assert "{" not in words and "UM-Codex" not in words


def test_update_says_when_this_is_the_newest():
    printed = ["Checking for a newer UM-Codex...", "UM-Codex 0.1.0a4 is the newest version."]
    launcher = launcher_for_tests(spawn=FakeUpdate(printed))
    launcher.status.update = "0.1.0a4"
    launcher.update_job = server.UpdateJob("running")
    launcher._run_update()
    assert launcher.update_job.phase == "newest" and launcher.status.update is None


@pytest.mark.parametrize(("platform", "shell"), [("darwin", "Terminal"), ("win32", "Windows PowerShell")])
def test_update_without_uv_says_to_run_it_in_a_terminal(platform, shell, tmp_path):
    """The maintainer's Mac: the app's Update found no uv. The window says
    what to do (its own words, not the update's line, which names paths)."""
    from umcodex.update import uv_not_found

    printed = ["Checking for a newer UM-Codex...", uv_not_found(platform, root=tmp_path)]
    launcher = launcher_for_tests(spawn=FakeUpdate(printed, code=1), platform=platform)
    launcher.update_job = server.UpdateJob("running")
    launcher._run_update()
    assert launcher.update_job.phase == "failed"
    assert launcher.update_job.words == server.UPDATE_NO_UV.format(shell=shell)
    assert f"open {shell} and run: um-codex update" in launcher.update_job.words
    assert str(tmp_path) not in json.dumps(launcher.state()["update"])


def test_the_window_checks_for_updates_at_once_then_every_hour():
    launcher = launcher_for_tests()
    checked: list[int] = []
    slept: list[float] = []
    launcher.check_update = lambda: checked.append(len(slept))  # type: ignore[method-assign]

    async def sleep(seconds: float) -> None:  # a clock that jumps
        slept.append(seconds)
        if len(slept) == 3:
            raise asyncio.CancelledError

    async def run() -> None:
        with pytest.raises(asyncio.CancelledError):
            await server.check_updates(launcher, sleep=sleep)

    asyncio.run(run())
    assert checked == [0, 1, 2]  # at the start, then after each hour
    assert slept == [3600.0, 3600.0, 3600.0] and server.UPDATE_CHECK_EVERY == 3600.0


def test_a_failed_check_doesnt_stop_the_hourly_ones():
    launcher = launcher_for_tests()
    calls: list[int] = []

    def broken() -> None:
        calls.append(1)
        raise RuntimeError("anything at all")

    launcher.check_update = broken  # type: ignore[method-assign]

    async def sleep(_: float) -> None:
        if len(calls) == 2:
            raise asyncio.CancelledError

    async def run() -> None:
        with pytest.raises(asyncio.CancelledError):
            await server.check_updates(launcher, sleep=sleep)

    asyncio.run(run())
    assert len(calls) == 2


def test_the_hourly_checks_start_and_stop_with_the_window(monkeypatch):
    monkeypatch.setattr(server, "UPDATE_CHECK_EVERY", 0.05)  # an "hour"
    launcher = launcher_for_tests()
    checked: list[float] = []
    launcher.check_update = lambda: checked.append(time.monotonic())  # type: ignore[method-assign]
    data_dir().mkdir(parents=True, exist_ok=True)

    async def run() -> None:
        stop = asyncio.Event()
        quiet = {"say": lambda _: None, "ready": lambda *_: None}
        ended = asyncio.create_task(server.serve(launcher, data=data_dir(), stop=stop, **quiet))
        await asyncio.sleep(0.6)
        assert len(checked) >= 3
        stop.set()
        await ended
        after = len(checked)
        await asyncio.sleep(0.3)
        assert len(checked) == after  # none once the window has ended

    asyncio.run(run())


def test_a_check_shows_in_the_header_and_never_during_or_after_this_windows_update(monkeypatch):
    from umcodex import update

    found = ["0.1.0a9"]
    monkeypatch.setattr(update, "launch_notice", lambda say, **kw: found[0])
    launcher = launcher_for_tests()
    launcher.check_update()
    assert launcher.state()["update"]["available"] == "0.1.0a9"  # "UM-Codex 0.1.0a9 is available · Update"
    found[0] = None
    launcher.check_update()
    assert launcher.state()["update"]["available"] is None
    found[0] = "0.1.0a9"
    for phase in ("running", "updated"):
        launcher.update_job = server.UpdateJob(phase, version="0.1.0a9" if phase == "updated" else None)
        launcher.check_update()
        assert launcher.status.update is None


def test_update_is_refused_while_a_setup_runs(folders_here):
    data = data_dir()
    folder = launches_dir(data) / "0123abcd"
    folder.mkdir(parents=True)
    lock = LaunchLock(folder / "lock")
    assert lock.acquire()
    write_launch_info(folder, Setup(id="thesis-a1", name="thesis", working=str(folders_here["thesis"])))
    fake = FakeUpdate(UPDATE_OUTPUT)

    async def test(h: Harness) -> None:
        await h.sign_in()
        answer = await h.post("/api/update")
        body = await answer.json()
        assert answer.status == 409 and body["error"] == "Stop running setups first: “thesis”."
        assert fake.commands == [] and h.launcher.update_job.phase == "idle"

    try:
        with_server(test, spawn=fake)
    finally:
        lock.release()


def test_check_for_updates_asks_now_and_says_what_it_found():
    answers: list[object] = ["0.1.0a9", None]

    def check() -> str | None:
        found = answers.pop(0)
        if isinstance(found, Exception):
            raise found
        return found  # type: ignore[return-value]

    async def test(h: Harness) -> None:
        await h.sign_in()
        found = await (await h.post("/api/update/check")).json()
        assert found == {"available": "0.1.0a9", "words": "UM-Codex 0.1.0a9 is available."}
        assert (await (await h.client.get("/api/state")).json())["update"]["available"] == "0.1.0a9"
        newest = await (await h.post("/api/update/check")).json()
        assert newest["available"] is None and "is the newest version" in newest["words"]
        from umcodex.update import CheckFailed

        answers.append(CheckFailed("Couldn't check for updates: offline"))
        failed = await h.post("/api/update/check")
        assert failed.status == 409 and "offline" in (await failed.json())["error"]

    with_server(test, check_updates_now=check)


def test_saving_a_moved_folder_again_needs_the_same_confirmation(folders_here, tmp_path):
    """Edit → Save (or "Open in Terminal instead") sends the saved paths;
    saving them would store where they lead now and skip Start's question."""
    credentials.save_api_key(FAKE_KEY)
    link = tmp_path / "link"
    link.symlink_to(folders_here["thesis"])
    SetupStore().save(Setup(id="linked-a1", name="linked", working=str(link), open_in="terminal"))
    body = setup_body(link, name="linked")

    async def test(h: Harness) -> None:
        await h.sign_in()
        refused = await h.put("/api/setups/linked-a1", body)
        assert refused.status == 409 and (await refused.json())["field"] == "moved"
        terminal = await h.put("/api/setups/linked-a1", {**body, "open_in": "terminal"})
        assert terminal.status == 409
        stale = await h.put("/api/setups/linked-a1", {**body, "confirm_moved": [str(folders_here["data"])]})
        assert stale.status == 409
        saved = SetupStore().get("linked-a1")
        assert saved is not None and saved.working == str(link)  # unchanged
        assert (await h.post("/api/setups/linked-a1/start", {})).status == 409
        assert h.launcher.openers["terminal"].opened == []  # type: ignore[attr-defined]
        # Confirmed with the place shown, it's saved as it resolves.
        shown = {"confirm_moved": [str(folders_here["thesis"])]}
        confirmed = await h.put("/api/setups/linked-a1", {**body, **shown})
        assert confirmed.status == 200 and (await confirmed.json())["moved"] == []

    with_server(test)


def test_choosing_the_folder_again_replaces_a_moved_one(folders_here, tmp_path):
    link = tmp_path / "link"
    link.symlink_to(folders_here["thesis"])
    SetupStore().save(Setup(id="linked-a1", name="linked", working=str(link), open_in="terminal"))

    async def test(h: Harness) -> None:
        await h.sign_in()
        chosen = await h.put("/api/setups/linked-a1", setup_body(folders_here["data"], name="linked"))
        assert chosen.status == 200 and (await chosen.json())["moved"] == []

    with_server(test)


def test_rename_keeps_names_unique():
    store = SetupStore()
    store.save(Setup(id="a-1", name="Thesis", working="/x"))
    store.save(Setup(id="b-1", name="data", working="/y"))
    launcher = launcher_for_tests()
    with pytest.raises(server.Invalid, match="has that name"):
        launcher.rename("b-1", {"name": "thesis"})
    assert launcher.rename("a-1", {"name": "THESIS"})["name"] == "THESIS"  # its own name, recased


def test_while_an_update_runs_start_reopen_quit_and_reopen_offers_wait(folders_here, monkeypatch):
    credentials.save_api_key(FAKE_KEY)

    async def test(h: Harness) -> None:
        await h.sign_in()
        made = await (await h.post("/api/setups", setup_body(folders_here["thesis"]))).json()
        h.launcher.update_job = server.UpdateJob("running", "Downloading…")
        h.launcher.quit = lambda: pytest.fail("quit")
        start = await h.post(f"/api/setups/{made['id']}/start", {})
        assert start.status == 409 and "Updating" in (await start.json())["error"]
        assert h.launcher.openers["terminal"].opened == []  # type: ignore[attr-defined]
        assert (await h.post("/api/reopen")).status == 409
        quit = await h.post("/_control/quit", {}, **{"X-UMCodex-Control": h.control})
        assert quit.status == 409
        assert h.launcher.installed_version() is None
        again = await h.post("/api/update")
        assert again.status == 409 and "under way" in (await again.json())["error"]
        # Updated: only Reopen, never a second update that could prune the version in use.
        h.launcher.update_job = server.UpdateJob("updated", "Updated to UM-Codex 0.1.0a5.", "0.1.0a5")
        second = await h.post("/api/update")
        assert second.status == 409 and "Reopen first" in (await second.json())["error"]

    with_server(test)


def test_the_window_stays_up_while_its_update_runs():
    launcher = launcher_for_tests()
    launcher.update_job = server.UpdateJob("running")
    data_dir().mkdir(parents=True, exist_ok=True)

    async def run() -> None:
        stop = asyncio.Event()
        quiet = {"say": lambda _: None, "ready": lambda *_: None}
        serving = server.serve(launcher, data=data_dir(), idle_seconds=0.05, stop=stop, **quiet)
        ended = asyncio.create_task(serving)
        await asyncio.sleep(0.5)
        assert not ended.done()  # idle, but its update is running
        stop.set()
        await ended

    asyncio.run(run())


def test_a_missing_folder_doesnt_hide_a_moved_one_on_the_card_or_in_a_save(folders_here, tmp_path):
    """The re-review's case: the working folder is a link to thesis now, and
    a read-only folder is gone. The card shows both; removing the missing
    folder and saving still needs the moved one confirmed."""
    credentials.save_api_key(FAKE_KEY)
    link = tmp_path / "link"
    link.symlink_to(folders_here["thesis"])
    gone = tmp_path / "gone"
    SetupStore().save(Setup(id="linked-a1", name="linked", working=str(link), reads=(str(gone),)))
    thesis = str(folders_here["thesis"])

    async def test(h: Harness) -> None:
        await h.sign_in()
        (card,) = (await (await h.client.get("/api/state")).json())["setups"]
        assert "doesn't exist" in card["problem"]
        assert card["moved"] == [{"saved": str(link), "now": thesis}]
        body = setup_body(link, name="linked")  # the missing folder removed
        refused = await h.put("/api/setups/linked-a1", body)
        assert refused.status == 409 and (await refused.json())["field"] == "moved"
        for spelled in (f"{link}/", f"{link}/.", str(link).replace("/link", "//link")):
            again = await h.put("/api/setups/linked-a1", setup_body(Path(spelled), name="linked"))
            assert again.status == 409, spelled
        assert (await h.post("/api/setups/linked-a1/start", {})).status in (400, 409)
        assert h.launcher.openers["terminal"].opened == []  # type: ignore[attr-defined]
        saved = SetupStore().get("linked-a1")
        assert saved is not None and saved.working == str(link)
        confirmed = await h.put("/api/setups/linked-a1", {**body, "confirm_moved": [thesis]})
        assert confirmed.status == 200
        started = await h.post("/api/setups/linked-a1/start", {})
        assert started.status == 200 and h.launcher.openers["terminal"].opened == ["linked-a1"]  # type: ignore[attr-defined]

    with_server(test)


def test_the_form_shows_a_moved_folder_and_can_confirm_it():
    script = (REPO / "src" / "umcodex" / "ui" / "static" / "app.js").read_text()
    assert "errors.moved ? movedInForm(draft, errors.moved) : null" in script
    assert "confirm_moved: (draft.moved || []).map((m) => m.now)" in script


def test_choosing_terminal_after_a_fallback_clears_its_note(tmp_path):
    """The card's "Open in Terminal instead" (a save with open_in terminal):
    the Codex app's fallback note goes with it."""
    credentials.save_api_key(FAKE_KEY)
    from umcodex import codex_app

    thesis = tmp_path / "thesis"
    thesis.mkdir()

    async def test(h: Harness) -> None:
        await h.sign_in()
        made = await (await h.post("/api/setups", {"working": str(thesis)})).json()
        codex_app.record_fallback(made["id"], "The Codex app didn't connect.", data_dir())
        state = await (await h.client.get("/api/state")).json()
        assert next(s for s in state["setups"] if s["id"] == made["id"])["app_fallback"]
        body = setup_body(thesis, name="", internet=True, open_in="terminal")
        await h.put(f"/api/setups/{made['id']}", body)
        state = await (await h.client.get("/api/state")).json()
        assert next(s for s in state["setups"] if s["id"] == made["id"])["app_fallback"] is None

    with_server(test, openers={"terminal": FakeOpener(), "codex-app": FakeAppOpener()})
