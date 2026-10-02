"""The commands the installers call: `key`, `pull`, `doctor --quiet` and
`uninstall`. Their names, flags and exit codes are an interface."""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import FAKE_KEY
from umcodex import cli, credentials, toolkit, uninstall
from umcodex.containers import images, instance_of, pull_images
from umcodex.launch import LaunchLock
from umcodex.paths import data_dir
from umcodex.setups import Setup, SetupStore


@pytest.fixture
def toolkit_says(monkeypatch):
    answers: list[str] = []

    def check_key(key: str, timeout: float = 15) -> str:
        assert key == FAKE_KEY
        return answers[0]

    monkeypatch.setattr(toolkit, "check_key", check_key)
    return answers


@pytest.mark.parametrize(
    ("answer", "code", "saved", "words"),
    [
        ("ok", 0, True, "accepted"),
        ("unreachable", 0, True, "Couldn't reach the Toolkit"),
        ("refused", 1, False, "refused"),
    ],
)
def test_key_from_stdin(monkeypatch, capsys, toolkit_says, answer, code, saved, words):
    toolkit_says.append(answer)
    monkeypatch.setattr("sys.stdin", io.StringIO(FAKE_KEY + "\r\n"))
    assert cli.main(["key", "--from-stdin"]) == code
    assert credentials.has_api_key() is saved
    out = capsys.readouterr().out
    assert words in out and FAKE_KEY not in out


def test_key_from_stdin_cancelled_or_invalid(monkeypatch, toolkit_says):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert cli.main(["key", "--from-stdin"]) == 2
    monkeypatch.setattr("sys.stdin", io.StringIO("not a key at all\n"))
    assert cli.main(["key", "--from-stdin"]) == 1
    assert not credentials.has_api_key()


def test_key_prompt_ctrl_c_is_cancelled(monkeypatch):
    def interrupted(*_, **__):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "ask_secret", interrupted)
    assert cli.main(["key"]) == 2


def test_the_key_goes_under_um_codex(memory_keychain, monkeypatch, toolkit_says):
    toolkit_says.append("ok")
    monkeypatch.setattr("sys.stdin", io.StringIO(FAKE_KEY + "\n"))
    cli.main(["key", "--from-stdin"])
    assert [service for service, _ in memory_keychain.saved] == ["UM-Codex"]


# --- pull ---------------------------------------------------------------------


GATEWAY = images()["gateway"]
# Docker's own words, from a live run (a digest the registry didn't find).
NOT_FOUND = (
    f'Error response from daemon: failed to resolve reference "{GATEWAY}": {GATEWAY}: not found'
)


class FakeRun:
    """subprocess.run for `docker`. `pulls`: what each `docker pull` does in
    turn ("ok", or Docker's error line); `stops`: Docker stops after this
    many pulls; `arrives`: the image is here after this many pulls."""

    def __init__(self, *, engine=True, present=(), pulls=("ok",), stops=None, arrives=None):
        self.engine, self.present = engine, set(present)
        self.pulls, self.stops, self.arrives = list(pulls), stops, arrives
        self.calls: list[list[str]] = []
        self.options: list[dict] = []
        self.pulled = 0

    def __call__(self, command, **options):
        self.calls.append(command)
        self.options.append(options)
        args = command[1:]
        code, err = 0, ""
        if args[0] == "info":
            running = self.engine and (self.stops is None or self.pulled < self.stops)
            code, err = (0, "") if running else (1, "Cannot connect to the Docker daemon. Is it running?")
        elif args[:2] == ["image", "inspect"]:
            here = args[-1] in self.present or (self.arrives is not None and self.pulled >= self.arrives)
            code = 0 if here else 1
        elif args[0] == "pull":
            outcome = self.pulls[min(self.pulled, len(self.pulls) - 1)]
            self.pulled += 1
            if outcome == "timeout":
                raise subprocess.TimeoutExpired(command, options["timeout"])
            code, err = (0, "") if outcome == "ok" else (1, f"Some progress\n{outcome}\n")
        return subprocess.CompletedProcess(command, code, "", err)


def _pull(run: FakeRun, said: list[str], waits: list[float] | None = None, quiet: bool = False) -> bool:
    return pull_images(said.append, run=run, sleep=(waits if waits is not None else []).append, quiet=quiet)


def test_pull_skips_a_local_dev_image_thats_here_and_pulls_the_gateway():
    run = FakeRun(present={"um-codex-agent:dev"})
    said: list[str] = []
    assert _pull(run, said)
    assert ["docker", "pull", GATEWAY] in run.calls
    assert not any(c[1] == "pull" and "um-codex-agent" in c[2] for c in run.calls)
    assert "already here: not pulled" in "\n".join(said)


def test_an_image_pinned_by_digest_thats_here_isnt_pulled_again():
    run = FakeRun(present={"um-codex-agent:dev", GATEWAY}, pulls=[NOT_FOUND])
    said: list[str] = []
    assert _pull(run, said)
    assert not any(c[1] == "pull" for c in run.calls)
    assert "The gateway image is already here" in "\n".join(said)


def test_a_pull_that_fails_once_is_tried_again():
    run = FakeRun(present={"um-codex-agent:dev"}, pulls=[NOT_FOUND, "ok"])
    said, waits = [], []
    assert _pull(run, said, waits)
    assert run.pulled == 2 and waits == [3.0]
    assert f"Docker said: Some progress / {NOT_FOUND}" in "\n".join(said)  # its last lines


def test_a_failed_pull_of_an_image_thats_here_after_all_is_fine():
    """The Windows tester's update: the registry said "not found" for the
    pinned digest, which was on the computer all along."""
    run = FakeRun(present={"um-codex-agent:dev"}, pulls=[NOT_FOUND], arrives=1)
    said: list[str] = []
    assert _pull(run, said)
    assert run.pulled == 1
    assert "that exact version" in "\n".join(said)


def test_a_registry_error_says_so_with_dockers_words():
    run = FakeRun(present={"um-codex-agent:dev"}, pulls=[NOT_FOUND])
    said, waits = [], []
    assert not _pull(run, said, waits)
    assert run.pulled == 3 and waits == [3.0, 10.0]
    text = "\n".join(said)
    assert "from its registry" in said[-1] and "Docker is running" in said[-1] and NOT_FOUND in said[-1]
    assert "Docker Desktop" not in text and "Docker isn't running" not in text


def test_docker_stopping_during_a_pull_says_so_and_isnt_tried_again():
    run = FakeRun(present={"um-codex-agent:dev"}, pulls=["error during connect: EOF"], stops=1)
    said, waits = [], []
    assert not _pull(run, said, waits)
    assert run.pulled == 1 and waits == []
    assert "Docker stopped running" in said[-1] and "error during connect: EOF" in said[-1]


def test_a_full_disk_says_so_and_isnt_tried_again():
    full = "write /var/lib/docker/tmp/x: no space left on device"
    run = FakeRun(present={"um-codex-agent:dev"}, pulls=[full])
    said, waits = [], []
    assert not _pull(run, said, waits)
    assert run.pulled == 1 and waits == []
    assert "out of disk space" in said[-1] and full in said[-1]


def test_a_pull_that_took_too_long_isnt_tried_again():
    run = FakeRun(present={"um-codex-agent:dev"}, pulls=["timeout"])
    said, waits = [], []
    assert not _pull(run, said, waits)
    assert run.pulled == 1 and waits == []
    assert "it took more than an hour" in said[-1]


def test_a_quiet_pull_says_one_line_instead_of_dockers_progress():
    run = FakeRun(present={"um-codex-agent:dev"})
    said: list[str] = []
    assert _pull(run, said, quiet=True)
    [options] = [o for c, o in zip(run.calls, run.options, strict=True) if c[1] == "pull"]
    assert ["docker", "pull", "--quiet", GATEWAY] in run.calls
    assert options["stdout"] == subprocess.DEVNULL
    assert "Downloaded the gateway image." in "\n".join(said)


def test_pull_fails_plainly():
    said: list[str] = []
    assert not _pull(FakeRun(engine=False), said)
    assert "Docker isn't running" in said[0]
    said.clear()
    assert not _pull(FakeRun(), said)  # the :dev image isn't here
    assert "can't be pulled" in "\n".join(said)


def test_our_lines_come_before_dockers_progress(tmp_path, monkeypatch):
    """With stdout a file (the launcher's Update, or Windows), each of our
    lines is out before `docker pull` writes its progress."""
    fake = tmp_path / "docker.py"
    fake.write_text(
        "import sys\n"
        "args = sys.argv[1:]\n"
        "if args[0] == 'info': print('29.0.0')\n"
        "elif args[:2] == ['image', 'inspect']: sys.exit(1)\n"
        "elif args[0] == 'pull':\n"
        "    for n in range(3): print(f'progress {args[-1][:7]} {n}', flush=True)\n"
    )
    script = tmp_path / "pull.py"
    script.write_text(
        "import subprocess, sys\n"
        "from umcodex import containers\n"
        "def run(command, **options):\n"
        "    return subprocess.run([sys.executable, sys.argv[1], *command[1:]], **options)\n"
        "sys.exit(0 if containers.pull_images(run=run, quiet=False) else 1)\n"
    )
    monkeypatch.setenv("UMCODEX_AGENT_IMAGE", "ghcr.io/example/agent@sha256:" + "a" * 64)
    out = tmp_path / "out.txt"
    with out.open("wb") as file:
        done = subprocess.run([sys.executable, str(script), str(fake)], stdout=file, timeout=60)
    assert done.returncode == 0
    lines = [line.split(" (")[0] for line in out.read_text().splitlines()]
    assert lines == [
        "Downloading the agent image",
        "progress ghcr.io 0", "progress ghcr.io 1", "progress ghcr.io 2",
        "Downloading the gateway image",
        "progress nginx@s 0", "progress nginx@s 1", "progress nginx@s 2",
    ]  # fmt: skip


# --- doctor --quiet -------------------------------------------------------------


def test_doctor_quiet_says_one_line_on_failure(monkeypatch, capsys):
    monkeypatch.setattr("shutil.which", lambda name, **_: None)
    assert cli.main(["doctor", "--quiet"]) == 1
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and out[0].startswith("UM-Codex doctor: Docker command: not found")


# --- uninstall ------------------------------------------------------------------


OTHER = "0123456789abcdef"  # another data folder's instance (a development copy's)


class UninstallDocker:
    """subprocess.run for `docker`, with listings in the shape `-q` and
    `--format '{{.ID}}|{{.Label "umcodex.instance"}}'` print (from a live
    run). `others`: another data folder's containers, networks and volumes
    are here too. `listings_fail`: Docker can't list them."""

    def __init__(self, others: bool = False, listings_fail: bool = False):
        self.listings_fail = listings_fail
        self.calls: list[list[str]] = []
        mine = instance_of(data_dir())
        self.objects = {
            ("ps", "-a"): [("3f9c2a1b7d4e", mine)] + ([("9e8d7c6b5a4f", OTHER)] if others else []),
            ("network", "ls"): [("0a1b2c3d4e5f", mine)] + ([("7a6b5c4d3e2f", OTHER)] if others else []),
            ("volume", "ls"): [("umcodex-home-thesis-a1b2c3", mine)]
            + ([("umcodex-home-dev-b2c3d4", OTHER)] if others else []),
        }

    def __call__(self, command, **options):
        self.calls.append(command)
        args = command[1:]
        out, code = "", 0
        kind = tuple(args[:2])
        if kind in self.objects and "label=umcodex.app=um-codex" in args and "--format" in args:
            code = 1 if self.listings_fail else 0
            out = "" if code else "".join(f"{name}|{owner}\n" for name, owner in self.objects[kind])
        elif args[:1] == ["rm"] or args[1:2] == ["rm"]:
            for listed in self.objects.values():
                listed[:] = [(name, owner) for name, owner in listed if name not in args]
        elif args[0] == "images":
            out = "5d6e7f8a9b0c\n" if args[-1] == "um-codex-agent" else ""
        elif args[:2] == ["ps", "-aq"]:
            out = ""  # nothing uses the gateway image
        return subprocess.CompletedProcess(command, code, out, "")


@pytest.fixture
def docker_here(monkeypatch):
    monkeypatch.setattr(uninstall.shutil, "which", lambda name: "/usr/local/bin/docker")


@pytest.fixture
def installed_copy(monkeypatch, data_folder):
    """The test's data folder is the installed UM-Codex's (the default one)."""
    monkeypatch.setattr(uninstall, "default_data_dir", lambda: data_folder)


@pytest.fixture(autouse=True)
def installed_program(monkeypatch, tmp_path) -> Path:
    """Where the installed UM-Codex's program files are (`app_dir()`): never
    this computer's. Not installed unless a test writes its `current`."""
    folder = tmp_path / "installed" / "app"
    monkeypatch.setattr(uninstall, "app_dir", lambda: folder)
    return folder


def _removed(run: UninstallDocker) -> list[list[str]]:
    return [c for c in run.calls if c[1] in ("rm", "rmi") or c[2:3] == ["rm"]]


MINE_REMOVED = [
    ["docker", "rm", "-f", "3f9c2a1b7d4e"],
    ["docker", "network", "rm", "0a1b2c3d4e5f"],
    ["docker", "volume", "rm", "umcodex-home-thesis-a1b2c3"],
]


def fill(data: Path) -> None:
    (data / "app" / "bin").mkdir(parents=True)
    (data / "app" / "bin" / "um-codex").write_text("program")
    (data / "setups.toml").write_text("x")
    (data / "launches").mkdir()


def test_uninstall_keeping_data(data_folder, memory_keychain, docker_here, installed_copy):
    fill(data_folder)
    credentials.save_api_key(FAKE_KEY)
    run = UninstallDocker()
    said: list[str] = []
    code = uninstall.uninstall(delete_data=False, yes=True, say=said.append, ask=_no_questions, run=run)
    assert code == 0
    assert not credentials.has_api_key()
    assert ["docker", "rm", "-f", "3f9c2a1b7d4e"] in run.calls
    assert ["docker", "network", "rm", "0a1b2c3d4e5f"] in run.calls
    assert ["docker", "rmi", "-f", "5d6e7f8a9b0c"] in run.calls
    assert not any(c[1:3] == ["volume", "rm"] for c in run.calls)
    assert (data_folder / "setups.toml").exists()
    assert "Kept. You can delete them yourself later." in said


def test_uninstalling_the_installed_copy_leaves_a_development_copys_containers(
    data_folder, memory_keychain, docker_here, installed_copy
):
    """A dev copy's launch may be running: with --yes its containers,
    networks and volumes stay, and so do the images it uses. The key goes."""
    fill(data_folder)
    credentials.save_api_key(FAKE_KEY)
    run = UninstallDocker(others=True)
    said: list[str] = []
    assert uninstall.uninstall(delete_data=True, yes=True, say=said.append, run=run) == 0
    assert not credentials.has_api_key()
    assert _removed(run) == MINE_REMOVED
    text = "\n".join(said)
    assert "Left 3 UM-Codex containers, networks and volumes from other data folders" in text
    assert "Kept UM-Codex's Docker images: another UM-Codex data folder's containers use them." in text


def test_the_installed_copys_uninstall_asks_about_other_data_folders_leftovers(
    data_folder, docker_here, installed_copy
):
    fill(data_folder)
    run = UninstallDocker(others=True)
    asked: list[str] = []
    answers = iter(["y", "y", "y", "y"])  # uninstall, the others' leftovers, images, data

    def ask(question: str) -> str:
        asked.append(question)
        return next(answers)

    said: list[str] = []
    assert uninstall.uninstall(delete_data=None, say=said.append, ask=ask, run=run) == 0
    assert asked[1].startswith(
        "Also remove 3 UM-Codex containers, networks and volumes from other data folders on this computer"
    )
    assert asked[1].endswith("[y/N] ")
    assert ["docker", "rm", "-f", "9e8d7c6b5a4f"] in run.calls
    assert ["docker", "network", "rm", "7a6b5c4d3e2f"] in run.calls
    assert ["docker", "volume", "rm", "umcodex-home-dev-b2c3d4"] in run.calls
    assert ["docker", "rmi", "-f", "5d6e7f8a9b0c"] in run.calls  # nothing else uses them now


def test_no_to_other_data_folders_leftovers_keeps_them(data_folder, docker_here, installed_copy):
    fill(data_folder)
    run = UninstallDocker(others=True)
    answers = iter(["y", "", "n"])  # uninstall; the others' leftovers: Enter (no); data: no
    said: list[str] = []
    assert uninstall.uninstall(delete_data=None, say=said.append, ask=lambda q: next(answers), run=run) == 0
    assert _removed(run) == MINE_REMOVED[:2]
    assert any(line.startswith("Left 3 UM-Codex containers") for line in said)


def test_a_failed_docker_listing_keeps_the_images(data_folder, docker_here, installed_copy):
    """Unknown isn't "nobody else uses them": the images stay, and it says why."""
    fill(data_folder)
    run = UninstallDocker(listings_fail=True)
    said: list[str] = []
    assert uninstall.uninstall(delete_data=True, yes=True, say=said.append, run=run) == 0
    assert _removed(run) == []
    text = "\n".join(said)
    assert "Docker couldn't list UM-Codex's containers or networks" in text
    assert "Kept UM-Codex's Docker images: Docker couldn't list UM-Codex's containers" in text


def test_uninstalling_another_data_folder_keeps_what_the_installed_copy_shares(
    data_folder, memory_keychain, docker_here, ssh_home, installed_program
):
    """UMCODEX_DATA_DIR (a development or test copy): only that folder's own
    things go. The one Toolkit key and the images are the installed copy's too."""
    from umcodex import codex_app

    installed_program.mkdir(parents=True)
    (installed_program / "current").write_text("0.1.0a4\n")
    assert not uninstall.is_installed_copy(data_folder)
    fill(data_folder)
    credentials.save_api_key(FAKE_KEY)
    install = codex_app.install_ssh_dir(data=data_folder)
    install.mkdir(parents=True)
    run = UninstallDocker(others=True)
    said: list[str] = []
    assert uninstall.uninstall(delete_data=True, yes=True, say=said.append, run=run) == 0
    assert credentials.has_api_key()
    assert not any(c[1] in ("rmi", "images") for c in run.calls)
    assert _removed(run) == MINE_REMOVED
    assert not install.exists()
    assert sorted(p.name for p in data_folder.iterdir()) == ["app"]
    text = "\n".join(said)
    assert "which isn't the installed one" in text
    assert "Kept the Toolkit key in the keychain" in text
    assert "Left 3 UM-Codex containers, networks and volumes from other data folders" in text
    assert "Kept UM-Codex's Docker images: the installed UM-Codex uses them too." in text


def test_a_development_copys_uninstall_removes_the_images_when_nothing_else_uses_them(
    data_folder, memory_keychain, docker_here
):
    """No installed UM-Codex (no `current`) and no other data folder's
    containers: the images are this copy's alone. The key still stays."""
    fill(data_folder)
    credentials.save_api_key(FAKE_KEY)
    run = UninstallDocker()
    assert uninstall.uninstall(delete_data=False, yes=True, say=[].append, run=run) == 0
    assert ["docker", "rmi", "-f", "5d6e7f8a9b0c"] in run.calls
    assert credentials.has_api_key()


def test_the_installed_program_wont_uninstall_another_data_folder(
    data_folder, memory_keychain, docker_here, installed_program, monkeypatch
):
    """The uninstaller scripts remove the program afterwards, which would
    orphan the installed data folder's containers, key and setups."""
    monkeypatch.setattr(uninstall.sys, "prefix", str(installed_program / "versions" / "0.1.0a4"))
    fill(data_folder)
    credentials.save_api_key(FAKE_KEY)
    run = UninstallDocker()
    said: list[str] = []
    assert uninstall.uninstall(delete_data=True, yes=True, say=said.append, run=run) == 1
    assert "UMCODEX_DATA_DIR points it at another data folder" in said[0]
    assert "Nothing was removed." in said[0]
    assert run.calls == [] and credentials.has_api_key()
    assert (data_folder / "setups.toml").exists()


def test_uninstall_takes_out_the_codex_apps_ssh_entries(data_folder, docker_here, ssh_home):
    from umcodex import codex_app

    ssh = ssh_home / ".ssh"
    ssh.mkdir()
    (ssh / "config").write_text("Host mine\n  User me\n")
    codex_app.add_include()
    # This data folder's setup, with its key in the layout before 0.1.0a4 (flat).
    SetupStore().save(Setup(id="thesis-a1b2c3", name="Thesis", working="/tmp"))
    (ssh / "um-codex").mkdir()
    (ssh / "um-codex" / "config").write_text("Host umcodex-thesis-a1b2c3\n")
    (ssh / "um-codex" / "thesis-a1b2c3_ed25519").write_text("key")
    said: list[str] = []
    assert uninstall.uninstall(delete_data=False, yes=True, say=said.append, run=UninstallDocker()) == 0
    assert (ssh / "config").read_text() == "Host mine\n  User me\n"
    assert not (ssh / "config.um-codex-backup").exists()  # the file is as it was before
    assert not (ssh / "um-codex").exists()
    assert any("Include ~/.ssh/um-codex/config" in line for line in said)


def test_uninstall_keeps_another_data_folders_ssh_entries(data_folder, docker_here, ssh_home, tmp_path):
    """Another UM-Codex data folder on this computer (a development copy's)
    keeps its hosts, its keys and the Include line."""
    from umcodex import codex_app

    if not shutil.which("ssh-keygen"):
        pytest.skip("no ssh-keygen here")
    ssh = ssh_home / ".ssh"
    ssh.mkdir()
    (ssh / "config").write_text("Host mine\n  User me\n")
    codex_app.add_include()
    other = tmp_path / "other-data"
    other.mkdir()
    proxy = lambda s: ["/x/um-codex", "ssh-proxy", s]  # noqa: E731
    codex_app.ensure_key("dev-b2", data=other)
    codex_app.write_config(proxy, setup_ids=["dev-b2"], data=other)
    codex_app.ensure_key("thesis-a1")
    codex_app.write_config(proxy, setup_ids=["thesis-a1"])
    said: list[str] = []
    assert uninstall.uninstall(delete_data=False, yes=True, say=said.append, run=UninstallDocker()) == 0
    assert codex_app.include_present()
    assert not codex_app.install_ssh_dir().exists()
    assert codex_app.known_setups(data=other) == ["dev-b2"]
    text = (ssh / "um-codex" / "config").read_text()
    assert f"Host {codex_app.alias('dev-b2', other)}" in text and "umcodex-thesis-a1" not in text
    assert any("another UM-Codex data folder" in line for line in said)


def _flat(ssh: Path, setup_id: str, data: Path | None = None) -> str:
    (ssh / "um-codex").mkdir(exist_ok=True)
    (ssh / "um-codex" / f"{setup_id}_ed25519").write_text("key")
    extra = f" --data-dir {data}" if data else ""
    return (
        f"Host umcodex-{setup_id}\n  IdentityFile ~/.ssh/um-codex/{setup_id}_ed25519\n"
        f"  ProxyCommand /old/um-codex ssh-proxy {setup_id}{extra}\n"
    )


def test_the_last_uninstall_takes_everything_out(data_folder, docker_here, ssh_home, tmp_path):
    """Flat keys whose data folder can't be found, or is gone, or is this
    one (with its setups file unreadable) don't keep the ssh entries."""
    from umcodex import codex_app

    ssh = ssh_home / ".ssh"
    ssh.mkdir()
    (ssh / "config").write_text("Host mine\n  User me\n")
    codex_app.add_include()
    (data_folder / "setups.toml").parent.mkdir(parents=True, exist_ok=True)
    (data_folder / "setups.toml").write_text("not toml [")
    config = _flat(ssh, "ours-a1") + _flat(ssh, "gone-b2", tmp_path / "gone")
    _flat(ssh, "nohost-c3")  # no Host names its data folder
    (ssh / "um-codex" / "config").write_text(config)
    said: list[str] = []
    assert uninstall.uninstall(delete_data=False, yes=True, say=said.append, run=UninstallDocker()) == 0
    assert not (ssh / "um-codex").exists()
    assert (ssh / "config").read_text() == "Host mine\n  User me\n"


def test_uninstall_keeps_an_older_um_codexs_flat_keys_still_in_use(
    data_folder, docker_here, ssh_home, tmp_path
):
    from umcodex import codex_app

    ssh = ssh_home / ".ssh"
    ssh.mkdir()
    (ssh / "config").write_text("Host mine\n  User me\n")
    codex_app.add_include()
    installed = tmp_path / "installed-a3"
    installed.mkdir()
    (ssh / "um-codex" / "config").parent.mkdir()
    (ssh / "um-codex" / "config").write_text(_flat(ssh, "first-project-c3", installed))
    said: list[str] = []
    assert uninstall.uninstall(delete_data=False, yes=True, say=said.append, run=UninstallDocker()) == 0
    assert codex_app.include_present()
    assert (ssh / "um-codex" / "first-project-c3_ed25519").exists()
    assert "Host umcodex-first-project-c3" in (ssh / "um-codex" / "config").read_text()


def test_uninstall_with_no_ssh_entries_says_nothing_about_them(data_folder, docker_here, ssh_home):
    said: list[str] = []
    uninstall.uninstall(delete_data=False, yes=True, say=said.append, run=UninstallDocker())
    assert not any(".ssh" in line for line in said)


def test_uninstall_deleting_data_keeps_the_program_files(data_folder, docker_here, tmp_path):
    fill(data_folder)
    outside = tmp_path / "your-thesis"
    outside.mkdir()
    (outside / "chapter.txt").write_text("precious")
    (data_folder / "link-to-yours").symlink_to(outside)
    run = UninstallDocker()
    said: list[str] = []
    uninstall.uninstall(delete_data=True, yes=True, say=said.append, ask=_no_questions, run=run)
    assert ["docker", "volume", "rm", "umcodex-home-thesis-a1b2c3"] in run.calls
    assert sorted(p.name for p in data_folder.iterdir()) == ["app"]
    assert (data_folder / "app" / "bin" / "um-codex").read_text() == "program"
    assert (outside / "chapter.txt").read_text() == "precious"  # a link is removed, never followed
    assert "Deleted." in said


def test_uninstall_asks_about_images_and_data_without_yes(data_folder, docker_here, installed_copy):
    fill(data_folder)
    run = UninstallDocker()
    answers = iter(["y", "n", "n"])  # uninstall? yes; images? no; data? no
    said: list[str] = []
    uninstall.uninstall(delete_data=None, say=said.append, ask=lambda q: next(answers), run=run)
    assert not any(c[1] == "rmi" for c in run.calls)
    assert (data_folder / "setups.toml").exists()
    assert "The images were kept." in said


def test_uninstall_refuses_while_a_launch_runs(data_folder):
    lock = LaunchLock(data_folder / "launches" / "1a2b3c4d" / "lock")
    assert lock.acquire()
    try:
        said: list[str] = []
        assert uninstall.uninstall(delete_data=True, yes=True, say=said.append, run=UninstallDocker()) == 1
        assert "Quit Codex first" in said[0]
    finally:
        lock.release()


def test_uninstall_reports_what_was_left(data_folder, docker_here, monkeypatch):
    fill(data_folder)
    monkeypatch.setattr(uninstall, "remove_tree", lambda path: None)  # a file in use: nothing goes
    said: list[str] = []
    uninstall.uninstall(delete_data=True, yes=True, say=said.append, run=UninstallDocker())
    text = "\n".join(said)
    assert "Deleted, except what couldn't be removed" in text and "setups.toml" in text
    assert "Deleted.\n" not in text + "\n"


def test_size_never_follows_links(tmp_path):
    (tmp_path / "a").write_bytes(b"x" * 100)
    big = tmp_path.parent / f"{tmp_path.name}-big"
    big.mkdir()
    (big / "f").write_bytes(b"x" * 10_000)
    (tmp_path / "link").symlink_to(big)
    assert uninstall.size_of(tmp_path) < 1000
    assert uninstall.human(1536) == "1.5 KB"


def _no_questions(question: str) -> str:
    raise AssertionError(f"asked {question!r}")


def test_key_from_stdin_drops_a_byte_order_mark(monkeypatch, toolkit_says):
    toolkit_says.append("ok")
    monkeypatch.setattr("sys.stdin", io.StringIO("\ufeff" + FAKE_KEY + "\r\n"))
    assert cli.main(["key", "--from-stdin"]) == 0
    assert credentials.api_key() == FAKE_KEY


def test_a_keychain_that_refuses_is_said_plainly(monkeypatch, capsys, toolkit_says):
    from keyring.errors import KeyringLocked

    toolkit_says.append("ok")

    def locked(*_):
        raise KeyringLocked("locked")

    monkeypatch.setattr("keyring.set_password", locked)
    monkeypatch.setattr("sys.stdin", io.StringIO(FAKE_KEY + "\n"))
    assert cli.main(["key", "--from-stdin"]) == 1
    assert "keychain refused it" in capsys.readouterr().out


def test_ctrl_c_while_checking_the_key_is_cancelled(monkeypatch):
    def interrupted(*_, **__):
        raise KeyboardInterrupt

    monkeypatch.setattr(toolkit, "check_key", interrupted)
    monkeypatch.setattr("sys.stdin", io.StringIO(FAKE_KEY + "\n"))
    assert cli.main(["key", "--from-stdin"]) == 2
    assert not credentials.has_api_key()


def test_only_the_first_double_dash_is_dropped(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_launch", lambda args, **_: seen.setdefault("args", args) and 0)
    cli.main(["launch", "--", "exec", "--", "echo"])
    assert seen["args"] == ["exec", "--", "echo"]


def test_doctor_quiet_off_the_vpn_is_not_a_failure(monkeypatch, capsys, memory_keychain):
    from umcodex import doctor
    from umcodex.containers import Docker

    credentials.save_api_key(FAKE_KEY)
    monkeypatch.setattr(toolkit, "check_key", lambda key: "unreachable")
    monkeypatch.setattr("shutil.which", lambda name, **_: "/usr/local/bin/docker")

    def docker_ok(command, **options):
        return subprocess.CompletedProcess(command, 0, "29.0.0\n", "")

    assert doctor.report(docker=Docker(docker_ok), quiet=True) is True
    assert capsys.readouterr().out == ""
    monkeypatch.setattr(toolkit, "check_key", lambda key: "refused")
    assert doctor.report(say=print, docker=Docker(docker_ok), quiet=True) is False
    assert "refused the key" in capsys.readouterr().out


def test_an_upstream_override_off_this_computer_is_refused(monkeypatch, capsys):
    monkeypatch.setenv("UMCODEX_UPSTREAM", "https://elsewhere.example.org/v1")
    monkeypatch.setattr("sys.stdin", io.StringIO(FAKE_KEY + "\n"))
    assert cli.main(["key", "--from-stdin"]) == 1
    assert "test stub on this computer" in capsys.readouterr().out
    assert not credentials.has_api_key()


def test_uninstall_asks_first_and_no_removes_nothing(data_folder, memory_keychain, docker_here):
    fill(data_folder)
    credentials.save_api_key(FAKE_KEY)
    run = UninstallDocker()
    asked: list[str] = []
    said: list[str] = []

    def ask(question: str) -> str:
        asked.append(question)
        return ""  # Enter: the default, no

    assert uninstall.uninstall(delete_data=None, say=said.append, ask=ask, run=run) == 1
    assert asked == ["Uninstall UM-Codex? [y/N] "]
    assert "Nothing was removed." in said
    assert run.calls == [] and credentials.has_api_key()
    assert (data_folder / "setups.toml").exists()


def test_uninstall_with_no_terminal_to_answer_is_no(
    data_folder, memory_keychain, docker_here, monkeypatch, capsys
):
    fill(data_folder)
    credentials.save_api_key(FAKE_KEY)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))  # input() raises EOFError
    assert cli.main(["uninstall"]) == 1
    out = capsys.readouterr().out
    assert "No answer" in out and "Traceback" not in out
    assert credentials.has_api_key() and (data_folder / "setups.toml").exists()


def test_uninstall_yes_asks_nothing(data_folder, docker_here):
    fill(data_folder)
    said: list[str] = []
    assert (
        uninstall.uninstall(
            delete_data=False, yes=True, say=said.append, ask=_no_questions, run=UninstallDocker()
        )
        == 0
    )


def test_launch_from_the_app_doesnt_offer_the_current_folder(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        cli, "_launch", lambda args, from_app=False, **_: seen.update(args=args, from_app=from_app) or 0
    )
    cli.main(["launch", "--from-app"])
    assert seen == {"args": [], "from_app": True}
    cli.main(["launch", "--", "--from-app"])  # after --, it's Codex's
    assert seen == {"args": ["--from-app"], "from_app": False}
    cli.main([])
    assert seen == {"args": [], "from_app": False}


def test_uninstall_waits_for_a_running_update(data_folder, docker_here):
    """The launcher's Update runs on its own (M7): its files must not go from under it."""
    from umcodex.launch import LaunchLock
    from umcodex.update import Layout, install_root

    fill(data_folder)
    lock = LaunchLock(Layout(install_root()).root / "update.lock")
    assert lock.acquire()
    said: list[str] = []
    try:
        code = uninstall.uninstall(delete_data=True, yes=True, say=said.append, run=UninstallDocker())
    finally:
        lock.release()
    assert code == 1 and "updating" in said[-1]
    assert (data_folder / "setups.toml").exists()
