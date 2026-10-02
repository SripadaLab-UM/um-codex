from __future__ import annotations

import stat
import tomllib
from pathlib import Path

import httpx
import pytest

from umcodex import this_computer as tc
from umcodex.codex_app import ATOMS, StateUnknown

from .conftest import FAKE_KEY


def test_copy_is_separate_from_the_sandbox_copy(tmp_path: Path) -> None:
    home, user_data = tc.copy_paths(tmp_path)
    assert home == tmp_path / "codex-app-local" / "codex-home"
    assert user_data == tmp_path / "codex-app-local" / "user-data"
    command = tc.open_command(Path("/Applications/ChatGPT.app"), tmp_path)
    assert command[:2] == ["/usr/bin/open", "-n"]
    assert f"CODEX_HOME={home}" in command
    assert f"--user-data-dir={user_data}" in command
    assert "codex-app/" not in " ".join(command)


def test_local_config_provider_through_the_relay(tmp_path: Path) -> None:
    token_file = tmp_path / "relay-token"
    existing = '[tui]\ntheme = "dark"\n[model_providers.other]\nbase_url = "http://example.invalid"\n'
    text = tc.local_config(
        existing, port=43210, token_file=token_file, model="gpt-5.6-terra", folders=[tmp_path / "work"]
    )
    config = tomllib.loads(text)
    provider = config["model_providers"]["toolkit"]
    assert config["model_provider"] == "toolkit"
    assert provider["base_url"] == "http://127.0.0.1:43210/relay/v1"
    assert provider["auth"]["command"] == "/bin/cat"
    assert provider["auth"]["args"] == [str(token_file)]
    assert "requires_openai_auth" not in provider and "env_key" not in provider
    assert config["forced_login_method"] == "api"
    assert config["sandbox_mode"] == "danger-full-access"
    assert config["approval_policy"] == "on-request"  # "ask me" by default on this computer
    assert config["approvals_reviewer"] == "user"  # no "Approve for me": no reviewer model on the Toolkit
    assert config["projects"][str(tmp_path / "work")] == {"trust_level": "trusted"}
    # The app's own settings are kept.
    assert config["tui"] == {"theme": "dark"}
    assert config["model_providers"]["other"]["base_url"] == "http://example.invalid"
    assert FAKE_KEY not in text


def test_local_config_this_folder_only(tmp_path: Path) -> None:
    text = tc.local_config(
        "",
        port=43210,
        token_file=tmp_path / "t",
        model="m",
        folders=[],
        access="folder",
        approval_policy="on-request",
        internet=False,
    )
    config = tomllib.loads(text)
    assert config["sandbox_mode"] == "workspace-write"
    assert config["approval_policy"] == "on-request"
    assert config["sandbox_workspace_write"] == {"network_access": False}
    with pytest.raises(ValueError):
        tc.local_config("", port=1, token_file=tmp_path / "t", model="m", folders=[], access="anything")


def test_seeded_state_makes_and_selects_the_local_project(tmp_path: Path) -> None:
    folder = tmp_path / "work"
    state = tc.seeded_state(
        {"other": 1}, name="Thesis", folders=[folder], seen_models=["gpt-6-sol"], now=1000
    )
    project = state["local-projects"][state["selected-project"]["projectId"]]
    assert state["selected-project"]["type"] == "local"
    assert project["name"] == "Thesis" and project["rootPaths"] == [str(folder)]
    assert project["createdAt"] == project["updatedAt"] == 1_000_000
    assert state["project-order"][0] == project["id"]
    assert state[ATOMS]["electron:onboarding-projectless-completed"] is True
    assert state[ATOMS]["seen-model-upgrade-list"] == ["gpt-6-sol"]
    assert state["other"] == 1
    # Seeding again doesn't duplicate.
    again = tc.seeded_state(state, name="Thesis", folders=[folder], seen_models=["gpt-6-sol"], now=2000)
    assert len(again["local-projects"]) == 1 and again["project-order"].count(project["id"]) == 1
    # More folders join the same project (the working folder keeps its id).
    more = tc.seeded_state(again, name="Thesis 2", folders=[folder, tmp_path / "data"], now=3000)
    entry = more["local-projects"][project["id"]]
    assert entry["rootPaths"] == [str(folder), str(tmp_path / "data")] and entry["name"] == "Thesis 2"
    assert entry["createdAt"] == 1_000_000 and entry["updatedAt"] == 3_000_000
    with pytest.raises(StateUnknown):
        tc.seeded_state({"local-projects": []}, name="x", folders=[folder])


def test_relay_port_is_kept(tmp_path: Path) -> None:
    port = tc.relay_port(tmp_path)
    assert tc.relay_port(tmp_path) == port
    assert stat.S_IMODE((tmp_path / "codex-app-local" / "relay-port").stat().st_mode) == 0o600


def test_local_relay_token_file_and_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["authorization"])
        return httpx.Response(200, json={"object": "list", "data": []})

    relay = tc.LocalRelay(lambda: FAKE_KEY, "http://upstream.invalid/v1", tmp_path)
    port = relay.start()
    try:
        relay._server.relay._client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
        assert port == tc.relay_port(tmp_path)
        token = relay.token_file.read_text(encoding="utf-8")
        assert stat.S_IMODE(relay.token_file.stat().st_mode) == 0o600
        assert FAKE_KEY not in token
        base = f"http://127.0.0.1:{port}/relay/v1"
        assert httpx.get(f"{base}/models", timeout=10).status_code == 401
        answer = httpx.get(f"{base}/models", headers={"authorization": f"Bearer {token}"}, timeout=10)
        assert answer.status_code == 200
        assert seen == [f"Bearer {FAKE_KEY}"]
    finally:
        relay.stop()
    assert not relay.token_file.exists()


def test_local_relay_keeps_the_open_copys_token(tmp_path: Path) -> None:
    first = tc.LocalRelay(lambda: FAKE_KEY, "http://upstream.invalid/v1", tmp_path)
    first.start()
    first.stop(forget=False)  # the relay ended; the copy is still open
    again = tc.LocalRelay(lambda: FAKE_KEY, "http://upstream.invalid/v1", tmp_path, keep_token=True)
    assert again.token == first.token
    again.start()
    again.stop()
    assert not again.token_file.exists()
    fresh = tc.LocalRelay(lambda: FAKE_KEY, "http://upstream.invalid/v1", tmp_path, keep_token=True)
    assert fresh.token != first.token


# --- M4 as a feature: the setup, the launcher's API, the launch, uninstall ----------

import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

from umcodex import credentials  # noqa: E402
from umcodex.folders import plan  # noqa: E402
from umcodex.launch import RunningLaunch, running_launches  # noqa: E402
from umcodex.setups import Setup, SetupStore, local_summary, new_id, summary  # noqa: E402


def test_setup_keeps_where_it_runs(tmp_path: Path) -> None:
    old = Setup.from_toml({"id": "a", "working": str(tmp_path)})
    assert (old.runs_on, old.local_access, old.computer_use) == ("sandbox", "full", True)
    assert not old.on_this_computer
    local = Setup(
        id="b",
        name="b",
        working=str(tmp_path),
        runs_on="this-computer",
        local_access="folder",
        computer_use=False,
    )
    again = Setup.from_toml(local.to_toml())
    assert again == local and again.on_this_computer
    odd = Setup.from_toml({"id": "c", "working": str(tmp_path), "runs_on": "mars", "local_access": "all"})
    assert (odd.runs_on, odd.local_access) == ("sandbox", "full")


def test_the_summary_says_it_runs_on_this_computer(tmp_path: Path) -> None:
    setup = Setup(id="b", name="b", working=str(tmp_path), runs_on="this-computer", approvals="on-request")
    layout = plan(tmp_path, [], [])
    text = "\n".join(summary(setup, layout))
    assert text == "\n".join(local_summary(setup, layout))
    assert "ON THIS COMPUTER" in text and "any of your files" in text and "may be able to reach it" in text
    assert "Screen Recording and Accessibility" in text and "asks you before commands" in text
    folder_only = "\n".join(local_summary(Setup(**{**setup.__dict__, "local_access": "folder"}), layout))
    assert "only these folders" in folder_only and "doesn't limit computer and browser control" in folder_only


def test_the_caution_text() -> None:
    for words in ("not in the sandbox", "delete any of", "apps and browser", "accounts", "Toolkit key"):
        assert words in tc.WARNING
    assert "only when you need computer or browser control" in tc.WARNING


def test_local_config_switches_computer_and_browser_control(tmp_path: Path) -> None:
    off = tomllib.loads(
        tc.local_config("", port=1, token_file=tmp_path / "t", model="m", folders=[], computer_use=False)
    )
    for name in tc.CONTROL_PLUGINS:
        assert off["plugins"][f"{name}@openai-bundled"] == {"enabled": False}
    # Switched back on: the app's own choice again (what it saved stays).
    back = tomllib.loads(
        tc.local_config(
            tc.local_config(
                "", port=1, token_file=tmp_path / "t", model="m", folders=[], computer_use=False
            ).split("\n", 1)[1],
            port=1,
            token_file=tmp_path / "t",
            model="m",
            folders=[],
            computer_use=True,
        )
    )
    assert all(back["plugins"][f"{n}@openai-bundled"]["enabled"] is True for n in tc.CONTROL_PLUGINS)
    untouched = tomllib.loads(tc.local_config("", port=1, token_file=tmp_path / "t", model="m", folders=[]))
    assert "plugins" not in untouched


# --- The launcher's API


def ui_helpers():
    from . import test_ui

    return test_ui


def test_where_codex_runs_through_the_api(tmp_path: Path) -> None:
    ui = ui_helpers()
    work = tmp_path / "work"
    (work / "data").mkdir(parents=True)
    (work / "refs").mkdir()

    async def test(h) -> None:
        await h.sign_in()
        state = await (await h.client.get("/api/state")).json()
        assert state["this_computer"]["available"] is True
        assert state["this_computer"]["warning"] == tc.WARNING
        body = ui.setup_body(work, runs_on="this-computer", approvals="on-request", local_access="folder")
        body["internet"], body["browser"] = True, True
        body["folders"] = [{"path": str(work / "data"), "write": True}]
        made = await (await h.post("/api/setups", body)).json()
        assert made["runs_on"] == "this-computer" and made["local_access"] == "folder"
        assert made["computer_use"] is True and made["browser"] is False
        # Read-only folders aren't offered on this computer.
        body["folders"].append({"path": str(work / "refs"), "write": False})
        refused = await h.put(f"/api/setups/{made['id']}", body)
        assert refused.status == 400
        assert "Read-only folders aren't available" in (await refused.json())["errors"]["folders"]
        odd = await h.post("/api/setups", ui.setup_body(work, runs_on="mars"))
        assert "runs_on" in (await odd.json())["errors"]

    ui.with_server(test)


def test_start_on_this_computer_needs_no_docker_and_asks_nothing(tmp_path: Path) -> None:
    ui = ui_helpers()
    work = tmp_path / "work"
    work.mkdir()
    credentials.save_api_key(FAKE_KEY)
    docker = ui.FakeDocker()

    async def test(h) -> None:
        await h.sign_in()
        made = await (await h.post("/api/setups", ui.setup_body(work, runs_on="this-computer"))).json()
        started = await h.post(f"/api/setups/{made['id']}/start", {})
        assert started.status == 200
        assert await started.json() == {"opened": "Codex app, on this computer", "in_background": True}
        assert h.launcher.local_opener.opened == [made["id"]]
        assert h.launcher.openers["terminal"].opened == []
        assert not any(c[1:2] == ["info"] for c in docker.commands)  # Docker wasn't asked

    ui.with_server(test, fake_docker=docker)


def test_one_setup_on_this_computer_at_a_time(tmp_path: Path) -> None:
    ui = ui_helpers()
    work = tmp_path / "work"
    work.mkdir()
    credentials.save_api_key(FAKE_KEY)
    from umcodex.launch import LaunchLock, launches_dir, write_launch_info
    from umcodex.paths import data_dir

    other = Setup(id=new_id("other"), name="other", working=str(work), runs_on="this-computer")
    folder = launches_dir(data_dir()) / "0a0b0c0d"
    folder.mkdir(parents=True)
    lock = LaunchLock(folder / "lock")
    assert lock.acquire()
    write_launch_info(folder, other, app={"local": True, "pid": None})
    try:

        async def test(h) -> None:
            await h.sign_in()
            made = await (await h.post("/api/setups", ui.setup_body(work, runs_on="this-computer"))).json()
            refused = await h.post(f"/api/setups/{made['id']}/start", {})
            assert (
                refused.status == 409
                and "“other” is running on this computer" in (await refused.json())["error"]
            )
            assert h.launcher.local_opener.opened == []

        ui.with_server(test)
    finally:
        lock.release()


def test_on_this_computer_isnt_offered_on_windows() -> None:
    from umcodex.ui.opener import LocalAppOpener

    assert LocalAppOpener(platform="win32").reason() == tc.UNAVAILABLE_WINDOWS
    assert tc.unavailable_reason("win32") == tc.UNAVAILABLE_WINDOWS
    found = LocalAppOpener(platform="darwin", find=lambda: None).reason()
    assert found is not None and "isn't installed" in found
    assert LocalAppOpener(program=["um-codex"]).command("abc") == [
        "um-codex",
        "launch",
        "--setup",
        "abc",
        "--open",
        "local",
    ]


# --- The launch, with a stand-in copy of the app


class FakeCopy:
    """`ps` and `open` for a copy of the app: `open` starts a real short-lived
    process standing in for the copy's main process (so waiting on its PID
    works); `ps` lists it with the copy's profile folder while it lives."""

    def __init__(self, data: Path, lifetime: float = 0.5) -> None:
        self.data = data
        self.lifetime = lifetime
        self.process: subprocess.Popen | None = None
        self.commands: list[list[str]] = []

    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def __call__(self, command, **kwargs) -> subprocess.CompletedProcess:
        self.commands.append(list(command))
        if command[0] == "/usr/bin/open":
            self.process = subprocess.Popen(
                [sys.executable, "-c", f"import time; time.sleep({self.lifetime})"]
            )
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[0] == "/bin/ps":
            _, user_data = tc.copy_paths(self.data)
            out = ""
            if self.alive():
                assert self.process is not None
                program = "/Applications/ChatGPT.app/Contents/MacOS/ChatGPT"
                out = f"{self.process.pid} {program} --user-data-dir={user_data}\n"
            return subprocess.CompletedProcess(command, 0, out, "")
        if command[0] == "/usr/bin/osascript":
            assert self.process is not None
            self.process.terminate()
            return subprocess.CompletedProcess(command, 0, "ok\n", "")
        return subprocess.CompletedProcess(command, 1, "", "")


def local_setup(work: Path, **changes) -> Setup:
    return Setup(
        id="here-1",
        name="Here",
        working=str(work),
        runs_on="this-computer",
        approvals="on-request",
        **changes,
    )


def test_run_local_opens_the_copy_and_holds_the_relay_until_it_quits(tmp_path: Path) -> None:
    data, work = tmp_path / "data", tmp_path / "work"
    work.mkdir()
    copy = FakeCopy(data)
    said: list[str] = []
    seen: dict = {}

    def watching(seconds: float) -> None:
        # While the copy is open: the launch shows as running, the relay answers with the token.
        if copy.alive() and not seen:
            seen["running"] = running_launches(data)
            token = tc.local_folder(data).joinpath(tc.TOKEN_FILE).read_text()
            port = tc.relay_port(data)
            seen["status"] = httpx.get(
                f"http://127.0.0.1:{port}/relay/v1/_umcodex/alive",
                headers={"authorization": f"Bearer {token}"},
                timeout=5,
            ).status_code
        time.sleep(min(seconds, 0.05))

    setup = local_setup(work)
    code = tc.run_local(
        setup,
        plan(work, [], []),
        say=said.append,
        app=Path("/Applications/ChatGPT.app"),
        data=data,
        api_key=lambda: FAKE_KEY,
        base_url="http://upstream.invalid/v1",
        run=copy,
        sleep=watching,
        poll=0.05,
    )
    assert code == 0
    assert any(c[:2] == ["/usr/bin/open", "-n"] for c in copy.commands)
    [launch] = seen["running"]
    assert launch.setup_id == "here-1" and launch.app["local"] is True and launch.app["copy"] == "opened"
    assert launch.app["pid"] == copy.process.pid  # type: ignore[union-attr]
    assert seen["status"] == 204
    home, _ = tc.copy_paths(data)
    config = tomllib.loads((home / "config.toml").read_text())
    assert config["model_provider"] == "toolkit" and config["approval_policy"] == "on-request"
    state = json.loads((home / ".codex-global-state.json").read_text())
    assert state["selected-project"]["type"] == "local"
    # The copy quit: the launch ended, the token went, nothing of the key anywhere.
    assert running_launches(data) == []
    assert not (tc.local_folder(data) / tc.TOKEN_FILE).exists()
    for path in tc.local_folder(data).rglob("*"):
        if path.is_file():
            assert FAKE_KEY not in path.read_text(errors="ignore")
    assert any("UM-Codex's local Codex window was closed." in line for line in said)


def test_run_local_refuses_read_only_folders(tmp_path: Path) -> None:
    work, refs = tmp_path / "work", tmp_path / "refs"
    work.mkdir()
    refs.mkdir()
    said: list[str] = []
    setup = local_setup(work, reads=(str(refs),))
    code = tc.run_local(setup, plan(work, [], [refs]), say=said.append, app=None, data=tmp_path / "data")
    assert code == 1 and "Read-only folders" in said[0]


def test_stop_local_quits_only_ums_copy(tmp_path: Path) -> None:
    data = tmp_path / "data"
    copy = FakeCopy(data, lifetime=30)
    copy(["/usr/bin/open", "-n"])
    try:
        assert copy.process is not None
        launch = RunningLaunch(
            "0a0b0c0d", "here-1", "Here", time.time(), app={"local": True, "pid": copy.process.pid}
        )
        wrong = RunningLaunch("0a0b0c0d", "here-1", "Here", time.time(), app={"local": True, "pid": 1})
        assert tc.stop_local(data, wrong, run=copy) is False  # not UM-Codex's copy: left alone
        assert tc.stop_local(data, launch, run=copy) is True
        copy.process.wait(timeout=10)
        assert tc.stop_local(data, launch, run=copy) is False  # already gone
    finally:
        if copy.alive():
            copy.process.kill()  # type: ignore[union-attr]


# --- Uninstall


def test_chrome_manifests_into_the_local_copy_are_removed(tmp_path: Path) -> None:
    data, home = tmp_path / "data", tmp_path / "home"
    ours, theirs = tc.chrome_manifests(home)[:2]
    ours.parent.mkdir(parents=True)
    theirs.parent.mkdir(parents=True)
    host = tc.local_folder(data) / "codex-home" / "plugins" / "cache" / "openai-bundled" / "chrome" / "host"
    ours.write_text(json.dumps({"name": "com.openai.codexextension", "path": str(host)}))
    theirs.write_text(
        json.dumps({"name": "com.openai.codexextension", "path": "/Applications/elsewhere/host"})
    )
    lines = tc.forget_chrome_manifests(data, home)
    assert len(lines) == 1 and not ours.exists() and theirs.exists()


def test_uninstall_removes_the_local_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from umcodex import uninstall as un
    from umcodex.paths import data_dir

    data = data_dir()
    (tc.local_folder(data) / "codex-home").mkdir(parents=True)
    (tc.local_folder(data) / "codex-home" / "config.toml").write_text("x = 1\n")
    SetupStore().save(Setup(id="a", name="a", working=str(tmp_path)))
    monkeypatch.setattr(un.shutil, "which", lambda name: None)  # no Docker here
    monkeypatch.setattr(tc, "running_copy", lambda data=None, run=None: None)
    said: list[str] = []
    assert un.uninstall(delete_data=False, yes=True, say=said.append) == 0
    assert not tc.local_folder(data).exists()
    assert (data / "setups.toml").exists()  # the rest of the data was kept
    assert any("local Codex window's settings and chats" in line for line in said)


def test_uninstall_waits_for_the_local_copy_to_quit(monkeypatch: pytest.MonkeyPatch) -> None:
    from umcodex import uninstall as un

    monkeypatch.setattr(tc, "running_copy", lambda data=None, run=None: 4242)
    said: list[str] = []
    assert un.uninstall(delete_data=False, yes=True, say=said.append) == 1
    assert "Quit it first" in said[0]


def test_launch_of_a_setup_on_this_computer_skips_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from umcodex import cli, codex_app, doctor

    work = tmp_path / "work"
    work.mkdir()
    credentials.save_api_key(FAKE_KEY)
    SetupStore().save(local_setup(work))
    ran: list[str] = []
    monkeypatch.setattr(cli, "_refresh_launchers", lambda: None)
    monkeypatch.setattr(cli, "_update_notice", lambda: None)
    monkeypatch.setattr(doctor, "ensure_docker", lambda: pytest.fail("Docker isn't needed on this computer"))
    monkeypatch.setattr(codex_app, "find_app", lambda **kw: Path("/Applications/ChatGPT.app"))
    monkeypatch.setattr(tc, "unavailable_reason", lambda platform=None, app=None: None)
    monkeypatch.setattr(tc, "run_local", lambda setup, layout, **kw: ran.append(setup.id) or 0)
    assert cli.main(["launch", "--setup", "here-1", "--open", "local"]) == 0
    assert ran == ["here-1"]


def test_the_page_asks_once_and_marks_the_card() -> None:
    static = Path(__file__).resolve().parents[1] / "src" / "umcodex" / "ui" / "static"
    script = (static / "app.js").read_text()
    where = script[script.index("function whereField") :]
    where = where[: where.index("\n}\n")]
    # The one pop-up: when "On this computer" is chosen, Cancel focused (confirmBox), never at Start.
    assert 'confirmBox("Run Codex on this computer?", info.warning, "Run on this computer")' in where
    start = script[script.index("async function startSetup") :]
    assert "confirmBox" not in start[: start.index("\n}\n")]
    assert 'text: "On this computer" }' in script  # the card's marker
    assert 'option("sandbox", "In the sandbox (recommended)")' in where


def test_run_local_moves_off_a_port_another_program_took(tmp_path: Path) -> None:
    import socket

    data, work = tmp_path / "data", tmp_path / "work"
    work.mkdir()
    taken = tc.relay_port(data)
    with socket.socket() as other:
        other.bind(("127.0.0.1", taken))
        other.listen()
        code = tc.run_local(
            local_setup(work), plan(work, [], []), say=lambda _: None, app=None, data=data,
            api_key=lambda: FAKE_KEY, base_url="http://upstream.invalid/v1", run=FakeCopy(data),
        )  # fmt: skip
    assert code == 0
    moved_to = tc.relay_port(data)
    assert moved_to != taken
    config = tomllib.loads((tc.copy_paths(data)[0] / "config.toml").read_text())
    assert config["model_providers"]["toolkit"]["base_url"] == f"http://127.0.0.1:{moved_to}/relay/v1"
