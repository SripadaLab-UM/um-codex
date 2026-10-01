"""`um-codex update` and `--rollback` (update.py), against a fake release served on
127.0.0.1 (tests/fake_github.py) and stand-ins for uv and the new version's commands."""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

import pytest

from tests.fake_github import AGENT, GATEWAY, FakeGitHub, make_release, sha256
from umcodex import signing
from umcodex.launch import LaunchLock
from umcodex.releases import NOT_CONFIGURED, ChecksumMismatch, ReleaseSource
from umcodex.update import Layout, Updater, check_images, check_requirements, launch_notice, remember_check


class FakeTools:
    """uv, and the commands of the versions it installs, as far as an update uses them."""

    def __init__(self) -> None:
        self.commands: list[tuple[list[str], Path | None, bool]] = []
        self.pull_code = 0
        self.says: str | None = None  # what --version says, if not the folder's version
        self.pip_code = 0

    def __call__(
        self, command: Sequence[str], *, timeout: float, cwd: Path | None = None, capture: bool = True
    ) -> subprocess.CompletedProcess[str]:
        command = list(command)
        self.commands.append((command, cwd, capture))
        if command[:2] == ["uv", "venv"]:
            Path(command[-1]).mkdir(parents=True)
            return self.done()
        if command[:3] == ["uv", "pip", "install"]:
            assert cwd is not None and (cwd / "requirements.txt").is_file()
            python = Path(command[command.index("--python") + 1])
            name = "um-codex.exe" if python.name == "python.exe" else "um-codex"
            python.parent.mkdir(parents=True, exist_ok=True)
            (python.parent / name).write_text(f"launcher of {python.parent.parent.name}")
            return self.done(self.pip_code, err="error: hash mismatch" if self.pip_code else "")
        program = Path(command[0])
        if program.name.startswith("um-codex") and command[1:] == ["--version"]:
            return self.done(out=f"UM-Codex {self.says or program.parent.parent.name}\n")
        if program.name.startswith("um-codex") and command[1:] == ["pull"]:
            return self.done(self.pull_code)
        raise AssertionError(f"unexpected command {command}")

    @staticmethod
    def done(code: int = 0, out: str = "", err: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], code, out, err)

    def ran(self, first: str) -> list[list[str]]:
        return [c for c, _, _ in self.commands if c[0] == first or Path(c[0]).name == first]


@pytest.fixture
def github():
    fake = FakeGitHub()
    yield fake
    fake.close()


@pytest.fixture
def key() -> tuple[str, str]:
    return signing.new_key()


def installed(root: Path, version: str, windows: bool = False) -> Path:
    folder = root / "versions" / version
    scripts = folder / ("Scripts" if windows else "bin")
    scripts.mkdir(parents=True)
    (scripts / ("um-codex.exe" if windows else "um-codex")).write_text(f"launcher of {version}")
    (folder / ".complete").write_text(json.dumps({"version": version, "wheel_sha256": "0" * 64}) + "\n")
    return folder


@pytest.fixture
def app(tmp_path) -> Path:
    """An install as the installers leave it: 0.1.0a1 in use (and running), 0.0.9 before it."""
    root = tmp_path / "app"
    installed(root, "0.0.9")
    installed(root, "0.1.0a1")
    (root / "versions" / "notes").mkdir()  # not a version: never removed
    (root / "current").write_text("0.1.0a1\n")
    (root / "previous").write_text("0.0.9\n")
    return root


def updater(app: Path, github: FakeGitHub, public: str, tools: FakeTools, said: list[str], data: Path, **kw):
    windows = kw.pop("windows", False)
    layout = Layout(app, windows=windows, prefix=app / "versions" / "0.1.0a1")
    return Updater(
        layout=layout,
        source=ReleaseSource(api=github.api),
        keys=[public],
        current="0.1.0a1",
        run=tools,
        uv="uv",
        platform="win32" if windows else "darwin",
        data=data,
        say=said.append,
        **kw,
    )


def pointer(app: Path) -> tuple[str, str]:
    return (app / "current").read_text().strip(), (app / "previous").read_text().strip()


def test_an_update_installs_beside_pulls_switches_and_prunes(app, github, key, data_folder):
    private, public = key
    github.releases = [make_release("v0.1.0-alpha.3", "0.1.0a3", private)]
    tools, said = FakeTools(), []
    assert updater(app, github, public, tools, said, data_folder).update() == 0, said
    assert pointer(app) == ("0.1.0a3", "0.1.0a1")
    new = app / "versions" / "0.1.0a3"
    record = json.loads((new / ".complete").read_text())
    wheel = github.releases[0].files["umcodex-0.1.0a3-py3-none-any.whl"]
    assert record["version"] == "0.1.0a3" and record["wheel_sha256"] == sha256(wheel)
    # The one before it stays; older ones go; anything that isn't a version stays.
    assert sorted(p.name for p in (app / "versions").iterdir()) == ["0.1.0a1", "0.1.0a3", "notes"]
    assert not (app / "downloads").exists()
    # The installers' own uv flags (install.sh), and requirements.txt by its plain name.
    venv, pip = tools.ran("uv")
    assert venv == [
        "uv",
        "venv",
        "-q",
        "--no-config",
        "--python",
        "3.13",
        "--python-preference",
        "only-managed",
        str(new),
    ]
    assert pip == [
        "uv", "pip", "install", "-q", "--no-config", "--require-hashes", "--only-binary", ":all:",
        "--default-index", "https://pypi.org/simple", "--link-mode", "copy",
        "--python", str(new / "bin" / "python"), "-r", "requirements.txt",
    ]  # fmt: skip
    # The new version checks itself, then pulls its own images, showing Docker's progress.
    [version, pull] = tools.ran("um-codex")
    assert version == [str(new / "bin" / "um-codex"), "--version"]
    assert pull == [str(new / "bin" / "um-codex"), "pull"]
    assert [capture for c, _, capture in tools.commands if c[-1] == "pull"] == [False]
    assert "Updated to UM-Codex 0.1.0a3" in "\n".join(said)
    assert json.loads((data_folder / "update-check.json").read_text())["available"] is None


def test_windows_gets_a_copy_of_the_new_versions_launcher_in_bin(tmp_path, github, key, data_folder):
    private, public = key
    root = tmp_path / "app"
    installed(root, "0.1.0a1", windows=True)
    (root / "current").write_text("0.1.0a1\n")
    (root / "bin").mkdir()
    (root / "bin" / "um-codex.exe").write_text("launcher of 0.1.0a1")  # the one running now
    github.releases = [make_release("v0.1.0-alpha.3", "0.1.0a3", private)]
    tools, said = FakeTools(), []
    up = updater(root, github, public, tools, said, data_folder, windows=True)
    assert up.update() == 0, said
    new = root / "versions" / "0.1.0a3"
    venv, pip = tools.ran("uv")
    # install.ps1's flags: no --python-preference there.
    assert venv == ["uv", "venv", "-q", "--no-config", "--python", "3.13", str(new)]
    assert str(new / "Scripts" / "python.exe") in pip
    assert (root / "bin" / "um-codex.exe").read_text() == "launcher of 0.1.0a3"
    [aside] = list((root / "bin").glob("um-codex.exe.old-*"))
    assert aside.read_text() == "launcher of 0.1.0a1"  # renamed, never overwritten
    assert up.rollback() == 0
    assert (root / "bin" / "um-codex.exe").read_text() == "launcher of 0.1.0a1"
    # The copy moved aside earlier is gone once nothing runs it.
    assert not aside.exists() and len(list((root / "bin").glob("um-codex.exe.old-*"))) == 1


def test_rollback_switches_back_and_forth(app, github, key, data_folder):
    private, public = key
    github.releases = [make_release("v0.1.0-alpha.3", "0.1.0a3", private)]
    tools, said = FakeTools(), []
    up = updater(app, github, public, tools, said, data_folder)
    assert up.update() == 0
    assert up.rollback() == 0
    assert pointer(app) == ("0.1.0a1", "0.1.0a3")
    assert tools.ran("um-codex")[-1] == [str(app / "versions" / "0.1.0a1" / "bin" / "um-codex"), "pull"]
    assert "UM-Codex 0.1.0a1 is the one in use now" in "\n".join(said)
    assert up.rollback() == 0
    assert pointer(app) == ("0.1.0a3", "0.1.0a1")


def test_update_and_rollback_close_a_running_launcher_window(app, github, key, data_folder, monkeypatch):
    from umcodex.ui import server

    closed = []
    monkeypatch.setattr(server, "close_running", lambda data: closed.append(data))
    private, public = key
    github.releases = [make_release("v0.1.0-alpha.3", "0.1.0a3", private)]
    up = updater(app, github, public, FakeTools(), [], data_folder)
    assert up.update() == 0
    assert closed == [data_folder]
    assert up.rollback() == 0
    assert closed == [data_folder, data_folder]


def test_rollback_with_nothing_before_says_so(app, github, key, data_folder):
    _, public = key
    (app / "previous").unlink()
    tools, said = FakeTools(), []
    assert updater(app, github, public, tools, said, data_folder).rollback() == 1
    assert "no earlier version" in said[-1] and (app / "current").read_text() == "0.1.0a1\n"
    (app / "previous").write_text("0.0.8\n")  # named, but not installed
    assert updater(app, github, public, tools, said, data_folder).rollback() == 1
    assert pointer(app) == ("0.1.0a1", "0.0.8")


def test_rollback_whose_images_cant_be_pulled_still_switches_and_says_so(app, github, key, data_folder):
    _, public = key
    tools, said = FakeTools(), []
    tools.pull_code = 1
    assert updater(app, github, public, tools, said, data_folder).rollback() == 0
    assert pointer(app) == ("0.0.9", "0.1.0a1")
    assert "run `um-codex pull`" in said[-1]


def test_nothing_happens_while_a_launch_is_running(app, github, key, data_folder):
    private, public = key
    github.releases = [make_release("v0.1.0-alpha.3", "0.1.0a3", private)]
    lock = LaunchLock(data_folder / "launches" / "abc" / "lock")
    assert lock.acquire()
    try:
        tools, said = FakeTools(), []
        up = updater(app, github, public, tools, said, data_folder)
        assert up.update() == 1 and "Quit Codex there first" in said[-1]
        assert up.rollback() == 1
        assert github.requests == [] and tools.commands == []
        assert pointer(app) == ("0.1.0a1", "0.0.9")
    finally:
        lock.release()
    # A launch that has ended (its lock let go) doesn't count.
    assert updater(app, github, public, FakeTools(), [], data_folder).update() == 0


def test_a_launch_that_starts_during_the_update_stops_the_switch(app, github, key, data_folder):
    private, public = key
    github.releases = [make_release("v0.1.0-alpha.3", "0.1.0a3", private)]
    tools, said = FakeTools(), []
    lock = LaunchLock(data_folder / "launches" / "late" / "lock")
    real = tools.__call__

    def tools_then_launch(command, **kw):
        if command[-1] == "pull":
            assert lock.acquire()
        return real(command, **kw)

    try:
        up = updater(app, github, public, tools, said, data_folder)
        up._run = tools_then_launch  # type: ignore[assignment]
        assert up.update() == 1 and "Quit Codex there first" in said[-1]
        assert pointer(app) == ("0.1.0a1", "0.0.9")
        assert not (app / "versions" / "0.1.0a3").exists()
    finally:
        lock.release()


def test_one_update_at_a_time(app, github, key, data_folder):
    _, public = key
    lock = LaunchLock(app / "update.lock")
    assert lock.acquire()
    try:
        said: list[str] = []
        assert updater(app, github, public, FakeTools(), said, data_folder).update() == 1
        assert "Another `um-codex update` is running" in said[-1]
    finally:
        lock.release()


def test_a_development_copy_doesnt_update_itself(app, github, key, data_folder, tmp_path):
    _, public = key
    said: list[str] = []
    up = Updater(
        layout=Layout(app, windows=False, prefix=tmp_path / "somewhere" / ".venv"),
        source=ReleaseSource(api=github.api),
        keys=[public],
        run=FakeTools(),
        uv="uv",
        platform="darwin",
        data=data_folder,
        say=said.append,
    )
    assert up.update() == 1 and "wasn't installed by the UM-Codex installer" in said[-1]
    assert github.requests == []


def test_without_a_pinned_key_github_isnt_asked(app, github, data_folder):
    said: list[str] = []
    up = updater(app, github, "", FakeTools(), said, data_folder)
    up._keys = ()
    assert up.update() == 1 and said == [NOT_CONFIGURED]
    assert github.requests == []


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ("unsigned", "isn't signed by UM-Codex's release key"),
        ("tampered", "its checksums don't add up"),
        ("changed-on-the-way", "didn't pass their checks (images.json doesn't match its checksum"),
        ("images", "didn't pass their checks (images.json and the package name different images.)"),
        ("unpinned-image", "doesn't pin the agent image by digest"),
        ("another-agent", "agent image isn't ghcr.io/sripadalab-um/um-codex-agent"),
        ("requirements", "doesn't pin this by version and hash"),
    ],
)
def test_a_release_that_fails_a_check_changes_nothing(app, github, key, data_folder, change, why):
    private, public = key
    stranger, _ = signing.new_key()
    wheel_name = "umcodex-0.1.0a3-py3-none-any.whl"
    unpinned = {"agent": "ghcr.io/sripadalab-um/um-codex-agent:latest", "gateway": GATEWAY}
    another = {"agent": "ghcr.io/someone/agent@sha256:" + "c" * 64, "gateway": GATEWAY}
    release = {
        "unsigned": lambda: make_release("v0.1.0-alpha.3", "0.1.0a3", stranger),
        # A file replaced after signing, with GitHub's checksum to match.
        "tampered": lambda: _replaced(make_release("v0.1.0-alpha.3", "0.1.0a3", private), "images.json"),
        # GitHub lists the signed file, but something else arrives.
        "changed-on-the-way": lambda: _in_transit(
            make_release("v0.1.0-alpha.3", "0.1.0a3", private), "images.json"
        ),
        "images": lambda: make_release(
            "v0.1.0-alpha.3",
            "0.1.0a3",
            private,
            package_images={"agent": AGENT, "gateway": "nginx@sha256:" + "d" * 64},
        ),
        "unpinned-image": lambda: make_release(
            "v0.1.0-alpha.3", "0.1.0a3", private, release_images=unpinned, package_images=unpinned
        ),
        "another-agent": lambda: make_release(
            "v0.1.0-alpha.3", "0.1.0a3", private, release_images=another, package_images=another
        ),
        "requirements": lambda: make_release(
            "v0.1.0-alpha.3",
            "0.1.0a3",
            private,
            requirements=f"httpx>=0.28\n./{wheel_name} --hash=sha256:{'0' * 64}\n",
        ),
    }[change]()
    github.releases = [release]
    tools, said = FakeTools(), []
    assert updater(app, github, public, tools, said, data_folder).update() == 1
    assert why in "\n".join(said), said
    assert pointer(app) == ("0.1.0a1", "0.0.9")
    assert sorted(p.name for p in (app / "versions").iterdir()) == ["0.0.9", "0.1.0a1", "notes"]
    assert tools.commands == [] and not (app / "downloads").exists()


def _in_transit(release, name: str):
    release.served[name] = release.files[name].replace(b"aaaa", b"bbbb")
    return release


def _replaced(release, name: str):
    release.files[name] = release.files[name].replace(b"aaaa", b"bbbb")
    return release


def test_an_older_or_same_release_is_never_installed(app, github, key, data_folder):
    private, public = key
    github.releases = [
        make_release("v0.1.0-alpha.1", "0.1.0a1", private),
        make_release("v0.0.9", "0.0.9", private),
    ]
    tools, said = FakeTools(), []
    assert updater(app, github, public, tools, said, data_folder).update() == 0
    assert said[-1] == "UM-Codex 0.1.0a1 is the newest version."
    assert tools.commands == [] and pointer(app) == ("0.1.0a1", "0.0.9")


def test_install_refuses_an_offer_that_isnt_newer(app, github, key, data_folder):
    from umcodex.releases import find_update
    from umcodex.update import UpdateFailed

    private, public = key
    github.releases = [make_release("v0.1.0-alpha.3", "0.1.0a3", private)]
    offer = find_update(ReleaseSource(api=github.api), "0.1.0a1", [public])
    assert offer is not None
    up = updater(app, github, public, FakeTools(), [], data_folder)
    up.current = "0.1.0a3"
    with pytest.raises(UpdateFailed, match="isn't newer"):
        up.install(offer)


def test_images_that_cant_be_pulled_undo_the_install(app, github, key, data_folder):
    private, public = key
    github.releases = [make_release("v0.1.0-alpha.3", "0.1.0a3", private)]
    tools, said = FakeTools(), []
    tools.pull_code = 1
    assert updater(app, github, public, tools, said, data_folder).update() == 1
    assert "UM-Codex 0.1.0a1 is still the one in use" in said[-1]
    assert pointer(app) == ("0.1.0a1", "0.0.9")
    assert not (app / "versions" / "0.1.0a3").exists() and not (app / "downloads").exists()


def test_a_failed_install_says_why_and_undoes_itself(app, github, key, data_folder):
    private, public = key
    github.releases = [make_release("v0.1.0-alpha.3", "0.1.0a3", private)]
    tools, said = FakeTools(), []
    tools.pip_code = 1
    assert updater(app, github, public, tools, said, data_folder).update() == 1
    assert "  error: hash mismatch" in said and "while installing the package" in said[-1]
    assert not (app / "versions" / "0.1.0a3").exists() and pointer(app)[0] == "0.1.0a1"


def test_a_package_that_says_another_version_is_removed(app, github, key, data_folder):
    private, public = key
    github.releases = [make_release("v0.1.0-alpha.3", "0.1.0a3", private)]
    tools, said = FakeTools(), []
    tools.says = "0.1.0a2"
    assert updater(app, github, public, tools, said, data_folder).update() == 1
    assert "says 'UM-Codex 0.1.0a2'" in said[-1]
    assert not (app / "versions" / "0.1.0a3").exists() and pointer(app)[0] == "0.1.0a1"


def test_the_same_package_installed_before_is_reused(app, github, key, data_folder):
    private, public = key
    release = make_release("v0.1.0-alpha.3", "0.1.0a3", private)
    github.releases = [release]
    folder = installed(app, "0.1.0a3")
    wheel = release.files["umcodex-0.1.0a3-py3-none-any.whl"]
    (folder / ".complete").write_text(json.dumps({"version": "0.1.0a3", "wheel_sha256": sha256(wheel)}))
    tools, said = FakeTools(), []
    assert updater(app, github, public, tools, said, data_folder).update() == 0
    assert tools.ran("uv") == [] and pointer(app) == ("0.1.0a3", "0.1.0a1")


def test_requirements_must_pin_everything_by_hash():
    wheel, digest = "umcodex-0.1.0a3-py3-none-any.whl", "e" * 64
    tail = f"./{wheel} --hash=sha256:{digest}\n"
    # As uv export writes it: markers, continuation lines, comments.
    good = (
        "# This file was autogenerated by uv\n"
        "colorama==0.4.6 ; sys_platform == 'win32' \\\n"
        f"    --hash=sha256:{'1' * 64} \\\n    --hash=sha256:{'2' * 64}\n    # via click\n"
    )
    check_requirements(good + tail, wheel, digest)
    for bad in (
        "httpx==0.28.1\n",  # no hash
        "httpx>=0.28 --hash=sha256:" + "1" * 64 + "\n",  # not pinned
        "--index-url https://elsewhere.example/simple\n",
        "-e git+https://example.org/x\n",
        "umcodex==0.1.0a3 --hash=sha256:" + "1" * 64 + "\n",
        "httpx==0.28.1 --hash=sha256:" + "1" * 64 + " --trusted-host x\n",
        tail,  # the package twice
    ):
        with pytest.raises(ChecksumMismatch):
            check_requirements(bad + tail, wheel, digest)
    with pytest.raises(ChecksumMismatch, match="another checksum"):
        check_requirements(f"./{wheel} --hash=sha256:{'f' * 64}\n", wheel, digest)


def test_images_must_match_the_packages_own(tmp_path):
    from tests.fake_github import wheel_bytes

    wheel = tmp_path / "w.whl"
    wheel.write_bytes(wheel_bytes("0.1.0a3", {"_comment": "x", "agent": AGENT, "gateway": GATEWAY}))
    listed = json.dumps({"agent": AGENT, "gateway": GATEWAY}).encode()
    assert check_images(listed, wheel) == {"agent": AGENT, "gateway": GATEWAY}
    for bad in (
        {"agent": AGENT},
        {"agent": AGENT, "gateway": GATEWAY, "proxy": GATEWAY},
        {"agent": AGENT, "gateway": "nginx:latest"},
    ):
        with pytest.raises(ChecksumMismatch):
            check_images(json.dumps(bad).encode(), wheel)
    with pytest.raises(ChecksumMismatch):
        check_images(b"not json", wheel)


# ------------------------------------------------------------------ at launch


@pytest.fixture
def notice(app, github, key, data_folder, monkeypatch):
    monkeypatch.delenv("UMCODEX_NO_UPDATE_CHECK")
    private, public = key
    github.releases = [make_release("v0.1.0-alpha.3", "0.1.0a3", private)]
    said: list[str] = []
    clock = [1_000_000.0]

    def run(**kw) -> list[str]:
        said.clear()
        options = {
            "layout": Layout(app, windows=False, prefix=app / "versions" / "0.1.0a1"),
            "keys": [public],
            "source": lambda: ReleaseSource(api=github.api),
            "current": "0.1.0a1",
            "data": data_folder,
            "now": lambda: clock[0],
        }
        launch_notice(said.append, **{**options, **kw})
        return list(said)

    return run, clock


def test_a_launch_says_when_a_newer_release_is_out(notice, github):
    run, _ = notice
    assert run() == ["UM-Codex 0.1.0a3 is available: run um-codex update"]
    assert len(github.requests) > 0


def test_a_launch_asks_github_at_most_once_a_day(notice, github):
    run, clock = notice
    run()
    asked = len(github.requests)
    clock[0] += 23 * 3600
    assert run() == ["UM-Codex 0.1.0a3 is available: run um-codex update"]  # remembered
    assert len(github.requests) == asked
    clock[0] += 2 * 3600
    run()
    assert len(github.requests) > asked


def test_a_launch_never_waits_long_for_github(notice, github, data_folder):
    run, clock = notice
    github.delay = 0.8
    started = time.monotonic()
    assert run(wait=0.2) == []
    assert time.monotonic() - started < 0.7
    # It finished in the background, and the next launch says what it found.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        record = json.loads((data_folder / "update-check.json").read_text())
        if record["available"]:
            break
        time.sleep(0.05)
    github.delay = 0
    clock[0] += 60
    assert run() == ["UM-Codex 0.1.0a3 is available: run um-codex update"]


def test_offline_a_launch_says_nothing_and_waits_a_day(notice, github):
    run, clock = notice
    github.close()
    assert run() == []
    clock[0] += 3600
    assert run() == []  # not asked again today


def test_a_remembered_offer_is_dropped_once_installed(notice, data_folder):
    run, clock = notice
    remember_check(data_folder, "0.1.0a3", clock[0])
    assert run(current="0.1.0a3") == []


def test_no_check_for_a_development_copy_without_keys_or_when_turned_off(
    notice, github, tmp_path, monkeypatch
):
    run, _ = notice
    assert run(layout=Layout(tmp_path, prefix=tmp_path / ".venv")) == []
    assert run(keys=()) == []
    monkeypatch.setenv("UMCODEX_NO_UPDATE_CHECK", "1")
    assert run() == []
    assert github.requests == []


def test_the_cli_update_command_in_a_development_copy(capsys, monkeypatch):
    from umcodex import cli, release_keys

    _, public = signing.new_key()
    monkeypatch.setattr(release_keys, "RELEASE_KEYS", (public,))
    assert cli.main(["update"]) == 1
    out = capsys.readouterr().out
    assert "wasn't installed by the UM-Codex installer" in out or "works on Mac and Windows" in out
    assert cli.main(["update", "--rollback"]) == 1
    monkeypatch.setattr(release_keys, "RELEASE_KEYS", ())
    assert cli.main(["update"]) == 1
    assert "Updates aren't set up" in capsys.readouterr().out


def test_a_reused_version_that_doesnt_run_is_installed_afresh(app, github, key, data_folder):
    private, public = key
    release = make_release("v0.1.0-alpha.3", "0.1.0a3", private)
    github.releases = [release]
    folder = installed(app, "0.1.0a3")
    wheel = release.files["umcodex-0.1.0a3-py3-none-any.whl"]
    (folder / ".complete").write_text(json.dumps({"version": "0.1.0a3", "wheel_sha256": sha256(wheel)}))
    tools, said = FakeTools(), []
    first = [True]
    real = tools.__call__

    def broken_once(command, **kw):
        if command[1:] == ["--version"] and first[0]:
            first[0] = False
            return FakeTools.done(1, err="bad interpreter")
        return real(command, **kw)

    up = updater(app, github, public, tools, said, data_folder)
    up._run = broken_once  # type: ignore[assignment]
    assert up.update() == 0, said
    assert [c[1] for c in tools.ran("uv")] == ["venv", "pip"]
    assert pointer(app) == ("0.1.0a3", "0.1.0a1")
    assert json.loads((folder / ".complete").read_text())["wheel_sha256"] == sha256(wheel)


def test_pruning_unmarks_a_version_before_removing_it(app, monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: None)  # a removal that stops part way
    layout = Layout(app, windows=False, prefix=app / "versions" / "0.1.0a1")
    assert layout.prune({"0.1.0a1"}) == []
    assert (app / "versions" / "0.0.9").is_dir() and not layout.complete("0.0.9")
    assert layout.complete("0.1.0a1")


def test_on_windows_a_failed_copy_leaves_the_command_and_current_as_they_were(tmp_path):
    root = tmp_path / "app"
    installed(root, "0.1.0a1", windows=True)
    folder = installed(root, "0.1.0a3", windows=True)
    (root / "current").write_text("0.1.0a1\n")
    (root / "bin").mkdir()
    (root / "bin" / "um-codex.exe").write_text("launcher of 0.1.0a1")
    (folder / "Scripts" / "um-codex.exe").unlink()  # nothing to copy
    layout = Layout(root, windows=True, prefix=root / "versions" / "0.1.0a1")
    with pytest.raises(OSError):
        layout.switch("0.1.0a3", previous="0.1.0a1")
    assert (root / "current").read_text() == "0.1.0a1\n" and not (root / "previous").exists()
    assert (root / "bin" / "um-codex.exe").read_text() == "launcher of 0.1.0a1"
    (folder / "Scripts" / "um-codex.exe").write_text("launcher of 0.1.0a3")
    layout.switch("0.1.0a3", previous="0.1.0a1")
    assert (root / "bin" / "um-codex.exe").read_text() == "launcher of 0.1.0a3"
    assert not (root / "bin" / ".um-codex.exe.new").exists()


def test_uv_from_the_installer_comes_first(tmp_path, monkeypatch):
    from umcodex import update

    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    monkeypatch.setattr(update.Path, "home", lambda: home)
    monkeypatch.setattr(update.shutil, "which", lambda name: "/elsewhere/uv")
    assert update.find_uv("darwin") == "/elsewhere/uv"
    (home / ".local" / "bin" / "uv").write_text("")
    assert update.find_uv("darwin") == str(home / ".local" / "bin" / "uv")


def test_the_notice_can_never_stop_a_launch(monkeypatch, capsys):
    from umcodex import cli, update

    def broken(*_a, **_k):
        raise RuntimeError("anything at all")

    monkeypatch.setattr(update, "launch_notice", broken)
    cli._update_notice()  # doesn't raise
    assert capsys.readouterr().out == ""
