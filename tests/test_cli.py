"""The commands the installers call: `key`, `pull`, `doctor --quiet` and
`uninstall`. Their names, flags and exit codes are an interface."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pytest

from tests.conftest import FAKE_KEY
from umcodex import cli, credentials, toolkit, uninstall
from umcodex.containers import images, pull_images
from umcodex.launch import LaunchLock


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


class FakeRun:
    def __init__(self, *, engine=True, present=(), pull_fails=False):
        self.engine, self.present, self.pull_fails = engine, set(present), pull_fails
        self.calls: list[list[str]] = []

    def __call__(self, command, **options):
        self.calls.append(command)
        args = command[1:]
        code = 0
        if args[0] == "info":
            code = 0 if self.engine else 1
        elif args[:2] == ["image", "inspect"]:
            code = 0 if args[-1] in self.present else 1
        elif args[0] == "pull":
            code = 1 if self.pull_fails else 0
        return subprocess.CompletedProcess(command, code, "", "")


def test_pull_skips_a_local_dev_image_thats_here_and_pulls_the_gateway():
    run = FakeRun(present={"um-codex-agent:dev"})
    said: list[str] = []
    assert pull_images(said.append, run=run)
    assert ["docker", "pull", images()["gateway"]] in run.calls
    assert not any(c[1] == "pull" and "um-codex-agent" in c[2] for c in run.calls)
    assert "already here: not pulled" in "\n".join(said)


def test_pull_fails_plainly():
    said: list[str] = []
    assert not pull_images(said.append, run=FakeRun(engine=False))
    assert "Docker isn't running" in said[0]
    said.clear()
    assert not pull_images(said.append, run=FakeRun(present={"um-codex-agent:dev"}, pull_fails=True))
    assert "Couldn't pull the gateway image" in "\n".join(said)
    said.clear()
    assert not pull_images(said.append, run=FakeRun())  # the :dev image isn't here
    assert "can't be pulled" in "\n".join(said)


# --- doctor --quiet -------------------------------------------------------------


def test_doctor_quiet_says_one_line_on_failure(monkeypatch, capsys):
    monkeypatch.setattr("shutil.which", lambda name, **_: None)
    assert cli.main(["doctor", "--quiet"]) == 1
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and out[0].startswith("UM-Codex doctor: Docker command: not found")


# --- uninstall ------------------------------------------------------------------


class UninstallDocker:
    """subprocess.run for `docker`, with listings in the shape `-q` prints."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, command, **options):
        self.calls.append(command)
        args = command[1:]
        out, code = "", 0
        if args[:2] == ["ps", "-aq"] and "label=umcodex.app=um-codex" in args:
            out = "3f9c2a1b7d4e\n"
        elif args[:2] == ["network", "ls"]:
            out = "0a1b2c3d4e5f\n"
        elif args[:2] == ["volume", "ls"]:
            out = "umcodex-home-thesis-a1b2c3\n"
        elif args[0] == "images":
            out = "5d6e7f8a9b0c\n" if args[-1] == "um-codex-agent" else ""
        elif args[:2] == ["ps", "-aq"]:
            out = ""  # nothing uses the gateway image
        return subprocess.CompletedProcess(command, code, out, "")


@pytest.fixture
def docker_here(monkeypatch):
    monkeypatch.setattr(uninstall.shutil, "which", lambda name: "/usr/local/bin/docker")


def fill(data: Path) -> None:
    (data / "app" / "bin").mkdir(parents=True)
    (data / "app" / "bin" / "um-codex").write_text("program")
    (data / "setups.toml").write_text("x")
    (data / "launches").mkdir()


def test_uninstall_keeping_data(data_folder, memory_keychain, docker_here):
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


def test_uninstall_takes_out_the_codex_apps_ssh_entries(data_folder, docker_here, ssh_home):
    from umcodex import codex_app

    ssh = ssh_home / ".ssh"
    ssh.mkdir()
    (ssh / "config").write_text("Host mine\n  User me\n")
    codex_app.add_include()
    (ssh / "um-codex").mkdir()
    (ssh / "um-codex" / "config").write_text("Host umcodex-thesis-a1b2c3\n")
    (ssh / "um-codex" / "thesis-a1b2c3_ed25519").write_text("key")
    said: list[str] = []
    assert uninstall.uninstall(delete_data=False, yes=True, say=said.append, run=UninstallDocker()) == 0
    assert (ssh / "config").read_text() == "Host mine\n  User me\n"
    assert not (ssh / "config.um-codex-backup").exists()  # the file is as it was before
    assert not (ssh / "um-codex").exists()
    assert any("Include ~/.ssh/um-codex/config" in line for line in said)


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


def test_uninstall_asks_about_images_and_data_without_yes(data_folder, docker_here):
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
