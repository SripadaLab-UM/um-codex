"""One launch, with Docker and `docker exec` faked: what's written, what's run,
and that everything goes afterwards."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import httpx
import pytest

from tests.conftest import FAKE_KEY
from umcodex import launch
from umcodex.containers import Docker
from umcodex.folders import plan
from umcodex.launch import LaunchLock, launch_is_live, launch_note
from umcodex.setups import Setup


@pytest.fixture
def folders(tmp_path: Path):
    root = Path(os.path.realpath(tmp_path))
    for name in ("thesis/raw", "outputs", "refs"):
        (root / name).mkdir(parents=True)
    return root


def make_setup(root: Path, **changes) -> tuple[Setup, object]:
    setup = Setup(
        id="thesis-a1b2c3",
        name="thesis",
        working=str(root / "thesis"),
        writes=(str(root / "outputs"),),
        reads=(str(root / "refs"), str(root / "thesis" / "raw")),
        **changes,
    )
    layout = plan(Path(setup.working), [Path(p) for p in setup.writes], [Path(p) for p in setup.reads])
    return setup, layout


def test_launch_note(folders):
    setup, layout = make_setup(folders, internet=True, approvals="on-request")
    note = launch_note(setup, layout)  # type: ignore[arg-type]
    assert "Setup: thesis" in note
    assert f"- /work (read, write, delete; Codex starts here) is {folders / 'thesis'}" in note
    assert f"- /mnt/write/outputs (read, write, delete) is {folders / 'outputs'}" in note
    assert f"- /mnt/read/refs (read only) is {folders / 'refs'}" in note
    assert f"- /mnt/read/raw (read only) is {folders / 'thesis' / 'raw'}" in note
    assert "can still change it at /work/raw" in note
    assert "On: the whole internet" in note
    assert "on-request" in note
    off = launch_note(*make_setup(folders))  # type: ignore[arg-type]
    assert "Off: only the model is reachable" in off and "never: commands run without asking" in off


def test_a_live_launch_holds_its_lock(data_folder):
    lock = LaunchLock(data_folder / "launches" / "abcd1234" / "lock")
    assert lock.acquire()
    assert launch_is_live(data_folder, "abcd1234")
    lock.release()
    assert not launch_is_live(data_folder, "abcd1234")
    assert not launch_is_live(data_folder, "never-was")


class FakeDocker:
    """subprocess.run for `docker`: everything exists and runs, and every
    command is kept, with the files the launch folder held at that moment."""

    def __init__(self, data_folder: Path) -> None:
        self.calls: list[list[str]] = []
        self.files: dict[str, str] = {}
        self.data_folder = data_folder

    def __call__(self, command, **options):
        self.calls.append(command)
        args = command[1:]
        if args[0] == "run" and "--env-file" in args:
            env_file = Path(args[args.index("--env-file") + 1])
            self.files["agent.env"] = env_file.read_text()
            for name in ("config.toml", "launch.md", "gateway.conf"):
                self.files[name] = (env_file.parent / name).read_text()
        out = "true\n" if args[:2] == ["inspect", "-f"] else ""
        code = 1 if args[:2] == ["volume", "inspect"] else 0  # a new setup: no volume yet
        return subprocess.CompletedProcess(command, code, out, "")


def run_launch(folders: Path, data_folder: Path, exec_result=None, **changes):
    setup, layout = make_setup(folders, **changes)
    fake = FakeDocker(data_folder)
    seen: dict[str, object] = {}

    def run_exec(command):
        seen["command"] = command
        # While Codex runs, the relay answers on localhost (wrong token: 401).
        gateway_conf = fake.files["gateway.conf"]
        port = int(gateway_conf.split("host.docker.internal:")[1].split("/")[0])
        seen["relay_status"] = httpx.get(f"http://127.0.0.1:{port}/relay/v1/models", timeout=5).status_code
        [launch_folder] = (data_folder / "launches").iterdir()
        seen["launch_files"] = sorted(p.name for p in launch_folder.iterdir())
        if isinstance(exec_result, Exception):
            raise exec_result
        return subprocess.CompletedProcess(command, exec_result or 0)

    said: list[str] = []
    code = launch.run(
        setup,
        layout,  # type: ignore[arg-type]
        say=said.append,
        docker=Docker(fake),
        tty=True,
        run_exec=run_exec,
        api_key=lambda: FAKE_KEY,
    )
    return code, fake, seen, said


def test_a_launch_end_to_end(folders, data_folder):
    code, fake, seen, _ = run_launch(folders, data_folder, exec_result=0)
    assert code == 0
    verbs = [" ".join(c[1:3]) for c in fake.calls]
    assert verbs.index("network create") < verbs.index("run -d") < verbs.index("rm -f")
    assert verbs[-2:] == ["rm -f", "network rm"]
    assert seen["command"][:4] == ["docker", "exec", "-it", "-w"]
    assert seen["command"][-2].endswith("-agent") and seen["command"][-1] == "codex"
    assert seen["relay_status"] == 401
    # The env file was there for `docker run` only.
    assert "agent.env" not in seen["launch_files"]
    assert fake.files["agent.env"].startswith("UMCODEX_TOKEN=umc_")
    assert "UMCODEX_INTERNET=off" in fake.files["agent.env"]
    assert 'base_url = "http://gateway/v1"' in fake.files["config.toml"]
    assert "Setup: thesis" in fake.files["launch.md"]
    # The launch folder is gone afterwards, and so is the relay.
    assert list((data_folder / "launches").iterdir()) == []
    with pytest.raises(httpx.ConnectError):
        port = int(fake.files["gateway.conf"].split("host.docker.internal:")[1].split("/")[0])
        httpx.get(f"http://127.0.0.1:{port}/relay/v1/models", timeout=2)


def test_the_key_is_in_no_command_and_no_file(folders, data_folder):
    _, fake, _, said = run_launch(folders, data_folder, internet=True)
    assert all(FAKE_KEY not in arg for call in fake.calls for arg in call)
    assert all(FAKE_KEY not in text for text in fake.files.values())
    assert all(FAKE_KEY not in line for line in said)
    log = data_folder / "um-codex.log"
    assert not log.exists() or FAKE_KEY not in log.read_text()


def test_launch_md_is_mounted_read_only_as_one_file(folders, data_folder):
    _, fake, _, _ = run_launch(folders, data_folder)
    [agent_run] = [c for c in fake.calls if c[1] == "run" and "--env-file" in c]
    mounts = [agent_run[i + 1] for i, a in enumerate(agent_run) if a == "--mount"]
    [note] = [m for m in mounts if "target=/etc/um-codex/launch.md" in m]
    assert note.startswith("type=bind,source=") and note.endswith(
        "launch.md,target=/etc/um-codex/launch.md,readonly"
    )


def test_everything_is_removed_even_when_codex_fails(folders, data_folder):
    with pytest.raises(OSError):
        run_launch(folders, data_folder, exec_result=OSError("terminal gone"))
    assert list((data_folder / "launches").iterdir()) == []


def test_internet_on_connects_the_bridge_network(folders, data_folder):
    _, fake, _, _ = run_launch(folders, data_folder, internet=True)
    connects = [c for c in fake.calls if c[1:3] == ["network", "connect"]]
    assert any(c[-2].endswith("-net") and c[-1].endswith("-agent") for c in connects)
    removal = [c for c in fake.calls if c[1:3] == ["network", "rm"]][-1]
    assert any(n.endswith("-net") for n in removal) and any(n.endswith("-int") for n in removal)


def test_a_missing_agent_image_stops_before_anything_starts(folders, data_folder):
    setup, layout = make_setup(folders)

    def no_image(command, **options):
        missing = command[1:3] == ["image", "inspect"]
        return subprocess.CompletedProcess(command, 1 if missing else 0, "", "")

    said: list[str] = []
    code = launch.run(setup, layout, say=said.append, docker=Docker(no_image), run_exec=None)  # type: ignore[arg-type]
    assert code == 1 and "isn't on this computer" in "\n".join(said)
