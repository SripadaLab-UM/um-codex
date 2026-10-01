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

    def open(self, setup_id: str) -> None:
        self.opened.append(setup_id)


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
        "openers": {"terminal": FakeOpener(), "codex-app": opening.CodexAppOpener()},
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
        assert copy["name"] == "thesis 2 (copy)" and copy["id"] != made["id"]
        assert (await h.delete(f"/api/setups/{made['id']}")).status == 200
        assert [s.name for s in SetupStore().all()] == ["thesis 2 (copy)"]
        assert ["docker", "volume", "rm", f"umcodex-home-{made['id']}"] in h.launcher.run.commands  # type: ignore[attr-defined]
        assert (await h.delete(f"/api/setups/{made['id']}")).status == 404

    with_server(test)


def test_folder_refusals_come_back_in_plain_words(folders_here):
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
        nameless = await (await h.post("/api/setups", setup_body(folders_here["thesis"], name="  "))).json()
        assert nameless["field"] == "name"
        odd = await (await h.post("/api/setups", setup_body(folders_here["thesis"], name="a\u202eb"))).json()
        assert odd["field"] == "name"
        model = await (await h.post("/api/setups", setup_body(folders_here["thesis"], model="x; rm"))).json()
        assert model["field"] == "model"
        assert SetupStore().all() == []
        good = await (await h.post("/api/folders/check", {"path": str(folders_here["data"])})).json()
        assert good["path"] == str(folders_here["data"]) and good["warnings"] == []

    with_server(test)


def test_choose_folder_uses_the_picker_and_checks_what_it_returns(folders_here, monkeypatch):
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
        assert started.status == 200 and (await started.json()) == {"opened": "Terminal"}
        assert h.launcher.openers["terminal"].opened == [made["id"]]  # type: ignore[attr-defined]
        assert SetupStore().last_used().id == made["id"]  # type: ignore[union-attr]

    with_server(test)


def test_a_folder_that_moved_needs_confirming_before_a_start(folders_here, tmp_path):
    credentials.save_api_key(FAKE_KEY)
    link = tmp_path / "link"
    link.symlink_to(folders_here["thesis"])
    setup = Setup(id=new_id("linked"), name="linked", working=str(link / "."))
    # Saved as the link's path, which now leads to another folder.
    setup = Setup(id=setup.id, name="linked", working=str(link))
    SetupStore().save(setup)

    async def test(h: Harness) -> None:
        await h.sign_in()
        prepared = await (await h.post(f"/api/setups/{setup.id}/prepare")).json()
        assert prepared["moved"] == [{"saved": str(link), "now": str(folders_here["thesis"])}]
        refused = await h.post(f"/api/setups/{setup.id}/start", {})
        assert refused.status == 409 and "confirm" in (await refused.json())["error"]
        assert h.launcher.openers["terminal"].opened == []  # type: ignore[attr-defined]
        started = await h.post(f"/api/setups/{setup.id}/start", {"confirm_moved": True})
        assert started.status == 200
        saved = SetupStore().get(setup.id)
        assert saved is not None and saved.working == str(folders_here["thesis"])

    with_server(test)


def test_codex_app_is_shown_but_not_available_yet(folders_here):
    credentials.save_api_key(FAKE_KEY)

    async def test(h: Harness) -> None:
        await h.sign_in()
        state = await (await h.client.get("/api/state")).json()
        assert state["openers"] == [
            {"key": "terminal", "label": "Terminal", "available": True},
            {"key": "codex-app", "label": "Codex app", "available": False},
        ]
        body = setup_body(folders_here["thesis"], open_in="codex-app")
        made = await (await h.post("/api/setups", body)).json()
        answer = await h.post(f"/api/setups/{made['id']}/start", {})
        assert answer.status == 409 and "Terminal" in (await answer.json())["error"]

    with_server(test)


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


def test_the_key_page_field_is_masked():
    page = (REPO / "src" / "umcodex" / "ui" / "static" / "index.html").read_text()
    assert re.search(r'<input id="key-input" type="password" autocomplete="off"', page)


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
]


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


def test_the_windows_command_is_encoded_and_quoted(tmp_path):
    terminal = Path("C:/Users/o'brien/AppData/Local/Microsoft/WindowsApps/wt.exe")
    for setup_id in NASTY:
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
        assert undo == [*program, "launch", "--setup", setup_id]
        assert last.startswith("& '")
        assert "$Env:UMCODEX_DATA_DIR = 'C:\\d''x'" in script and "$Env:PYTHONUTF8 = '1'" in script


@pytest.mark.skipif(sys.platform != "win32", reason="runs Windows PowerShell")
@pytest.mark.parametrize("setup_id", NASTY)
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


def test_the_codex_app_opener_is_a_placeholder():
    app = opening.CodexAppOpener()
    assert not app.available()
    with pytest.raises(opening.OpenFailed):
        app.open("x")


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
    assert seen == {"from_app": False, "setup_name": "x y", "args": []}
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
    store.save(Setup(id="a-1", name="a", working=str(tmp_path), open_in="codex-app"))
    assert store.get("a-1").open_in == "codex-app"  # type: ignore[union-attr]
    raw = store.path.read_text().replace('open_in = "codex-app"', 'open_in = "elsewhere"')
    store.path.write_text(raw)
    assert store.get("a-1").open_in == "terminal"  # type: ignore[union-attr]
