"""The macOS installer's and uninstaller's steps, run for real against stand-ins.

Adapted from IHS DataLab's backend/tests/test_installer_macos.py at 6b6fdca.

`docker`, `uv`, `open`, `osascript` and `security` are small scripts on PATH,
and the "installed" UM-Codex is one too, logging what the installer asks of
it. Nothing is downloaded or installed, HOME is a temporary folder, and a
stand-in folder takes the place of /Applications. The real Docker, Keychain
and /Applications are never touched, and sudo is a stand-in that never asks
for a password.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from umcodex import launchers

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the macOS installer's shell")

INSTALLER = Path(__file__).resolve().parents[1] / "installer" / "macos" / "install.sh"
UNINSTALLER = INSTALLER.with_name("uninstall.sh")

FAKE_UMCODEX = """#!/bin/sh
echo "$*" >> "$UMCODEX_TEST_LOG"
if [ -n "${UMCODEX_TEST_WHO:-}" ]; then echo "$0" >> "$UMCODEX_TEST_WHO"; fi
if [ -n "${UMCODEX_TEST_PATHLOG:-}" ]; then echo "$PATH" >> "$UMCODEX_TEST_PATHLOG"; fi
case "$*" in
  --version) echo "UM-Codex $UMCODEX_TEST_VERSION" ;;
  pull)
    # Reads its input, as a command that asks something might.
    if [ -n "${UMCODEX_TEST_PULL_READS:-}" ]; then cat > /dev/null; fi
    exit "${UMCODEX_TEST_PULL:-0}" ;;
  key)
    # The real `um-codex key` (its masked prompt, its checks), with the
    # Toolkit and the keychain stood in for (KEY_TOOL).
    env >> "$UMCODEX_TEST_ENVLOG"
    exec "$UMCODEX_TEST_PYTHON" "$UMCODEX_TEST_KEYTOOL" ;;
  uninstall*)
    if [ -t 0 ]; then echo "uninstall read a terminal" >> "$UMCODEX_TEST_LOG"; fi
    exit "${UMCODEX_TEST_UNINSTALL:-0}" ;;
  launchers*)
    # The real `um-codex launchers` (umcodex/launchers.py): what the app
    # contains. UMCODEX_TEST_LAUNCHERS=fail: it writes half the app, then fails.
    if [ "${UMCODEX_TEST_LAUNCHERS:-}" = fail ] && [ "$2" = --write ]; then
      for last; do :; done
      mkdir -p "$last/Contents/MacOS" && echo half > "$last/Contents/Info.plist"
      echo "PermissionError: no" >&2
      exit 1
    fi
    exec "$UMCODEX_TEST_PYTHON" -m umcodex "$@" ;;
esac
exit 0
"""

# `um-codex key` as installed, with the Toolkit's check and the keychain
# stood in for: each key the Toolkit is asked about goes in
# UMCODEX_TEST_KEYS, and UMCODEX_TEST_KEY_EXITS="1 0" makes it refuse the
# first and accept the second.
KEY_TOOL = """
import os
import sys

from umcodex import cli

codes = os.environ.get("UMCODEX_TEST_KEY_EXITS", "0").split()
record = os.environ["UMCODEX_TEST_KEYS"]


def check_key(key, timeout=15):
    with open(record, "a", encoding="utf-8") as file:
        file.write(key + "\\n")
    with open(record, encoding="utf-8") as file:
        tries = len(file.read().splitlines())
    return "refused" if tries <= len(codes) and codes[tries - 1] == "1" else "ok"


cli.toolkit.check_key = check_key
cli.credentials.save_api_key = lambda key: None
sys.exit(cli._key_command())
"""

FAKE_UV = """#!/bin/sh
case "$1" in
  --version) echo "uv 0.12.19" ;;
  venv)
    for last; do :; done
    mkdir -p "$last/bin"
    # A real Python: the installer's masked prompt runs in it.
    ln -s "$UMCODEX_TEST_PYTHON" "$last/bin/python" ;;
  pip)
    here="$(basename "$(pwd)")"
    echo "pip $* (in $here) UV_INDEX_URL=${UV_INDEX_URL:-unset}" >> "$UMCODEX_TEST_UVLOG"
    while [ $# -gt 0 ]; do
      if [ "$1" = "--python" ]; then python="$2"; fi
      shift
    done
    cp "$UMCODEX_TEST_FAKE" "$(dirname "$python")/um-codex"
    chmod +x "$(dirname "$python")/um-codex" ;;
esac
"""

# The Keychain: whether a key is saved (44 is `security`'s "not found").
FAKE_SECURITY = """#!/bin/sh
echo "security $*" >> "${UMCODEX_TEST_SECURITYLOG:-/dev/null}"
exit "${UMCODEX_TEST_KEY_SAVED:-44}"
"""


def executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture(scope="session")
def system_bin(tmp_path_factory) -> Path:
    """The system's commands, without any `docker`: a CI runner (or this Mac)
    may have a real one on PATH, and the tests must never find it. Every
    installer run gets exactly the fakes plus this folder on PATH.
    UMCODEX_TEST_SYSTEM_BIN_EXTRA names a folder searched first (to check
    that a `docker` there is left out)."""
    folder = tmp_path_factory.mktemp("system-bin")
    sources = [*filter(None, [os.environ.get("UMCODEX_TEST_SYSTEM_BIN_EXTRA")]), "/usr/bin", "/bin"]
    for source in sources:
        for entry in sorted(Path(source).iterdir()) if Path(source).is_dir() else []:
            link = folder / entry.name
            if entry.name.startswith("docker") or link.exists() or link.is_symlink():
                continue
            link.symlink_to(entry)
    return folder


@pytest.fixture
def machine(tmp_path, system_bin) -> dict[str, Path]:
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    tools = tmp_path / "tools"
    tools.mkdir()
    executable(tools / "docker", "#!/bin/sh\nexit 0\n")
    executable(tools / "open", "#!/bin/sh\nexit 0\n")
    executable(tools / "security", FAKE_SECURITY)
    # Logs what it's asked to run: each argument as ARG:<value>, then the
    # script it reads from its input.
    executable(
        tools / "osascript",
        '#!/bin/sh\n{ for a; do echo "ARG:$a"; done; cat; } >> "${UMCODEX_TEST_OSA:-/dev/null}"\n',
    )
    executable(tools / "curl", "#!/bin/sh\necho 'no downloads in tests' >&2\nexit 1\n")
    executable(tools / "uv", FAKE_UV)
    keytool = tmp_path / "key_tool.py"
    keytool.write_text(KEY_TOOL)
    fake = tmp_path / "fake-um-codex"
    fake.write_text(FAKE_UMCODEX)
    packages = tmp_path / "release"
    packages.mkdir()
    (home / "Desktop").mkdir()
    # Stands in for /Applications, which the tests must never touch.
    system_apps = tmp_path / "Applications"
    system_apps.mkdir()
    return {
        "home": home,
        "system": system_bin,
        "apps": system_apps,
        "tools": tools,
        "fake": fake,
        "packages": packages,
        "log": tmp_path / "log",
        "uvlog": tmp_path / "uvlog",
        "keys": tmp_path / "keys",
        "envlog": tmp_path / "envlog",
        "keytool": keytool,
        "securitylog": tmp_path / "securitylog",
    }


def package_files(machine, version: str, pinned: bool = True) -> Path:
    wheel = f"umcodex-{version}-py3-none-any.whl"
    package = machine["packages"] / wheel
    package.write_bytes(f"package {version}".encode())
    digest = hashlib.sha256(package.read_bytes() if pinned else b"another").hexdigest()
    (machine["packages"] / "requirements.txt").write_text(
        f"httpx==0.28.1 \\\n    --hash=sha256:{'1' * 64}\n./{wheel} --hash=sha256:{digest}\n"
    )
    return package


def environment(machine, version: str, **extra_env: str) -> dict[str, str]:
    return {
        **extra_env,
        "HOME": str(machine["home"]),
        "PATH": extra_env.get("PATH", f"{machine['tools']}:{machine['system']}"),
        "UMCODEX_TEST_LOG": str(machine["log"]),
        "UMCODEX_TEST_FAKE": str(machine["fake"]),
        "UMCODEX_TEST_VERSION": version,
        "UMCODEX_TEST_UVLOG": str(machine["uvlog"]),
        "UMCODEX_TEST_KEYS": str(machine["keys"]),
        "UMCODEX_TEST_SECURITYLOG": str(machine["securitylog"]),
        "UMCODEX_TEST_PYTHON": sys.executable,
        "UMCODEX_TEST_KEYTOOL": str(machine["keytool"]),
        "UMCODEX_TEST_ENVLOG": str(machine["envlog"]),
        # Nothing a test runs reaches this computer's keychain.
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
        "UMCODEX_SYSTEM_APPLICATIONS": str(machine["apps"]),
        # macOS's Launch Services isn't told about the tests' apps.
        "UMCODEX_LSREGISTER": "",
    }


def install(
    machine,
    version: str,
    *args: str,
    pinned: bool = True,
    answers: list[str] | None = None,
    **extra_env: str,
) -> subprocess.CompletedProcess[str]:
    package = package_files(machine, version, pinned)
    env = environment(machine, version, **extra_env)
    command = ["sh", str(INSTALLER), "--package", str(package), *args]
    if answers is not None:
        return in_terminal(command, env, answers)
    return subprocess.run(
        command,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        # No terminal to ask: nothing is asked.
        start_new_session=True,
        stdin=subprocess.DEVNULL,
    )


# What the installer asks in a terminal: a [Y/n] question, or the key.
QUESTIONS = (b"] ", b"API key: ")


def waiting_after_trace(text: bytes) -> bool:
    """Whether `text` has a question (not inside a trace line) followed only
    by trace lines."""
    found = max(((text.rfind(q), q) for q in QUESTIONS), default=(-1, b""))
    at, question = found
    if at < 0:
        return False
    line_start = text.rfind(b"\n", 0, at) + 1
    if text[line_start:].startswith(b"+ "):
        return False
    rest = text[at + len(question) :].replace(b"\r", b"")
    return all(line.startswith(b"+ ") for line in rest.split(b"\n") if line)


def wait_until_waiting(pid: int, seconds: float = 20) -> None:
    """Until the process is asleep (blocked reading its terminal), seen three
    times in a row, however busy this computer is; at most `seconds`."""
    asleep = 0
    deadline = time.monotonic() + seconds
    while asleep < 3 and time.monotonic() < deadline:
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout
        asleep = asleep + 1 if state.strip()[:1] in ("S", "I") else 0
        time.sleep(0.05)


def in_terminal(
    command: list[str], env: dict[str, str], answers: list[str], timeout: float = 60
) -> subprocess.CompletedProcess[str]:
    """Run the installer in a terminal of its own, as a person would, typing
    `answers` in turn at its questions (a line ending in "] ", or the key
    prompt), then pressing Return at any others. Output and typing come back
    as stdout (the key prompt doesn't echo what's typed)."""
    import pty
    import select

    pid, fd = pty.fork()
    if pid == 0:  # the child: the terminal is its own
        try:
            os.execve("/bin/sh", command, env)
        finally:
            os._exit(127)
    pending = list(answers)
    out = b""
    mark = 0  # where the output since the last answer starts

    def answer() -> None:
        nonlocal mark
        typed = pending.pop(0) if pending else ""
        if typed.endswith("\x03"):
            # Ctrl-C only once the installer is waiting in `read`: sh (bash 3.2)
            # can lose a SIGINT that arrives between printing the question and
            # starting to read. And on its own, as a person presses it: no Return.
            wait_until_waiting(pid)
            os.write(fd, typed.encode())
        else:
            os.write(fd, (typed + "\n").encode())
        mark = len(out)

    deadline = time.monotonic() + timeout
    while True:
        if time.monotonic() > deadline:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
            raise AssertionError("installer didn't finish:\n" + out.decode(errors="replace"))
        ready, _, _ = select.select([fd], [], [], 0.2)
        if not ready:
            # Quiet after a question that more output followed (sh's xtrace
            # lines, "+ ..."): it's waiting for an answer all the same.
            if waiting_after_trace(out[mark:]):
                answer()
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:  # the installer has finished: its terminal is closed
            break
        if not chunk:
            break
        out += chunk
        if out[mark:].endswith(QUESTIONS):
            answer()
    os.close(fd)
    _, status = os.waitpid(pid, 0)
    text = out.decode("utf-8", errors="replace").replace("\r\n", "\n")
    return subprocess.CompletedProcess(command, os.waitstatus_to_exitcode(status), text, "")


def root(machine) -> Path:
    return machine["home"] / "Library" / "Application Support" / "UM-Codex" / "app"


def asked(machine) -> list[str]:
    lines = machine["log"].read_text().splitlines()
    machine["log"].unlink()
    return lines


def keys(machine) -> list[str]:
    return machine["keys"].read_text().splitlines() if machine["keys"].exists() else []


def test_it_installs_a_version_in_its_own_folder_then_pulls_the_images(machine):
    done = install(machine, "0.1.0a3")
    assert done.returncode == 0, done.stdout + done.stderr
    app = root(machine)
    assert (app / "versions" / "0.1.0a3" / ".complete").is_file()
    assert (app / "current").read_text() == "0.1.0a3\n"
    assert not (app / "previous").exists()
    assert asked(machine) == [
        "--version",  # the new folder's own check
        "launchers --write-command",  # bin/um-codex, as UM-Codex writes it
        "--version",  # through bin/um-codex, the launcher's command
        "--version",  # through ~/.local/bin/um-codex: the command link must work
        "pull",
        f"launchers --write {machine['apps'] / 'UM-Codex.app'}",  # the app, as UM-Codex writes it
    ]
    command = app / "bin" / "um-codex"
    assert command.read_bytes() == launchers.mac_command_file(app)
    assert (machine["home"] / ".local" / "bin" / "um-codex").readlink() == command
    launcher = machine["apps"] / "UM-Codex.app" / "Contents" / "MacOS" / "UM-Codex"
    text = launcher.read_text()
    # The launcher window, in the background: no Terminal window, no Dock icon.
    assert text.endswith(f"\nexec '{app}/bin/um-codex' ui --detach\n")
    assert text == launchers.mac_app_files(app, None)["Contents/MacOS/UM-Codex"].decode()
    plist = (machine["apps"] / "UM-Codex.app" / "Contents" / "Info.plist").read_text()
    assert "<key>LSUIElement</key><true/>" in plist
    # The format it was written in, so a later version knows whether to rewrite it.
    written = launchers.Launchers(app, platform="darwin").record()
    assert written is not None and (written.format, written.ok) == (launchers.FORMAT, True)


def test_installing_a_newer_version_keeps_the_one_before(machine):
    install(machine, "0.1.0a3")
    again = install(machine, "0.1.0a4")
    assert again.returncode == 0, again.stdout + again.stderr
    app = root(machine)
    assert (app / "current").read_text() == "0.1.0a4\n"
    assert (app / "previous").read_text() == "0.1.0a3\n"
    assert (app / "versions" / "0.1.0a3" / ".complete").is_file()
    # The shim runs whichever version `current` names.
    shim = subprocess.run(
        [str(app / "bin" / "um-codex"), "--version"],
        env={**os.environ, "UMCODEX_TEST_LOG": str(machine["log"]), "UMCODEX_TEST_VERSION": "x"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert shim.stdout.strip() == "UM-Codex x"


# bin/um-codex as alpha.1's and alpha.2's installers wrote it: its folder
# worked out from $0, which through the ~/.local/bin link is the link.
ALPHA_2_COMMAND = """#!/bin/sh
export PYTHONUTF8=1
root="$(cd "$(dirname "$0")/.." && pwd)"
version="$(head -n 1 "$root/current" 2>/dev/null || true)"
if [ -z "$version" ] || [ ! -x "$root/versions/$version/bin/um-codex" ]; then
  echo "UM-Codex ${version:-(none)} can't be opened; opening the version before it." >&2
  version="$(head -n 1 "$root/previous" 2>/dev/null || true)"
fi
exec "$root/versions/$version/bin/um-codex" "$@"
"""


def typed_um_codex(machine, cwd: Path) -> subprocess.CompletedProcess[str]:
    """`um-codex --version` typed in a new Terminal window: found on PATH as
    ~/.local/bin/um-codex (a link), run in another folder."""
    env = environment(machine, "x", PATH=f"{machine['home'] / '.local' / 'bin'}:{machine['system']}")
    return subprocess.run(
        ["/bin/sh", "-c", "um-codex --version"], cwd=cwd, env=env, capture_output=True, text=True, timeout=30
    )


def test_the_command_link_works_from_any_folder_with_a_quote_in_the_home_folder(machine, tmp_path):
    # A home folder like /Users/o'brien, with a space too.
    home = machine["home"].rename(machine["home"].with_name("o'brien home"))
    machine["home"] = home
    elsewhere = tmp_path / "some project"
    elsewhere.mkdir()
    # As alpha.2 left it: the link works only by the command's full path.
    install(machine, "0.1.0a2")
    command = root(machine) / "bin" / "um-codex"
    command.write_text(ALPHA_2_COMMAND)
    link = home / ".local" / "bin" / "um-codex"
    assert link.readlink() == command
    broken = typed_um_codex(machine, elsewhere)
    assert broken.returncode != 0 and "UM-Codex (none) can't be opened" in broken.stderr
    # The fixed installer (run again, or a newer version's) rewrites it.
    done = install(machine, "0.1.0a3")
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"The command:       {link}" in done.stdout
    assert "doesn't run UM-Codex" not in done.stdout
    works = typed_um_codex(machine, elsewhere)
    assert works.returncode == 0, works.stderr
    assert works.stdout.strip() == "UM-Codex x" and works.stderr == ""
    assert command.read_bytes() == launchers.mac_command_file(root(machine))


def test_a_command_link_that_doesnt_work_isnt_offered(machine):
    # A command that runs by its full path but not from another folder
    # through the link, as alpha.2's: the end says the full path instead.
    broken = FAKE_UMCODEX.replace(
        "case \"$*\" in", 'case "$(pwd)" in /) [ "$*" = --version ] && exit 1 ;; esac\ncase "$*" in', 1
    )
    executable(machine["fake"], broken)
    # ~/.local/bin on PATH: plain `um-codex` would be offered if the link worked.
    on_path = f"{machine['home'] / '.local' / 'bin'}:{machine['tools']}:{machine['system']}"
    done = install(machine, "0.1.0a3", PATH=on_path)
    assert done.returncode == 0, done.stdout + done.stderr
    link = machine["home"] / ".local" / "bin" / "um-codex"
    assert f"{link} doesn't run UM-Codex; use the full path below instead." in done.stdout
    assert f"run: '{root(machine)}/bin/um-codex'" in done.stdout
    assert "The command:" not in done.stdout


def test_a_package_without_a_version_in_its_name_is_refused(machine):
    package = machine["packages"] / "umcodex.whl"
    package.write_text("")
    done = subprocess.run(
        ["sh", str(INSTALLER), "--package", str(package)],
        env=environment(machine, "x"),
        capture_output=True,
        text=True,
        timeout=60,
        start_new_session=True,
    )
    assert done.returncode == 2 and "umcodex-<version>-py3-none-any.whl" in done.stdout


def test_without_a_package_it_says_how_to_run_it(machine):
    done = subprocess.run(
        ["sh", str(INSTALLER)], env=environment(machine, "x"), capture_output=True, text=True
    )
    assert done.returncode == 2 and "Usage: sh install.sh --package" in done.stdout


def test_uv_installs_only_what_requirements_txt_pins_by_hash(machine):
    done = install(machine, "0.1.0a3", UV_INDEX_URL="https://evil.example/simple")
    assert done.returncode == 0, done.stdout + done.stderr
    [pip] = machine["uvlog"].read_text().splitlines()
    assert (
        "pip install -q --no-config --require-hashes --only-binary :all: "
        "--default-index https://pypi.org/simple --link-mode copy --python "
    ) in pip
    assert pip.split(" (in ")[0].endswith("-r requirements.txt")
    assert "UV_INDEX_URL=unset" in pip  # the environment can't steer uv
    record = json.loads((root(machine) / "versions" / "0.1.0a3" / ".complete").read_text())
    package = machine["packages"] / "umcodex-0.1.0a3-py3-none-any.whl"
    assert record["wheel_sha256"] == hashlib.sha256(package.read_bytes()).hexdigest()


def test_a_package_requirements_txt_doesnt_pin_is_refused(machine):
    done = install(machine, "0.1.0a3", pinned=False)
    assert done.returncode == 1 and "doesn't name this package with this checksum" in done.stdout
    assert not (root(machine) / "versions" / "0.1.0a3").exists()


def test_without_requirements_txt_it_stops(machine):
    package = package_files(machine, "0.1.0a3")
    (machine["packages"] / "requirements.txt").unlink()
    done = subprocess.run(
        ["sh", str(INSTALLER), "--package", str(package)],
        env=environment(machine, "0.1.0a3"),
        capture_output=True,
        text=True,
        timeout=60,
        start_new_session=True,
    )
    assert done.returncode == 2 and "Pass --requirements." in done.stdout


def test_only_https_downloads(machine):
    done = install(machine, "0.1.0a3", "--requirements", "http://example.org/requirements.txt")
    assert done.returncode == 2 and "Only https downloads" in done.stdout


def test_the_same_version_with_another_package_is_reinstalled(machine):
    install(machine, "0.1.0a3")
    (root(machine) / "versions" / "0.1.0a3" / ".complete").write_text(
        json.dumps({"version": "0.1.0a3", "wheel_sha256": "0" * 64})
    )
    machine["uvlog"].unlink()
    done = install(machine, "0.1.0a3")
    assert done.returncode == 0 and machine["uvlog"].exists()


def test_the_same_package_isnt_installed_twice(machine):
    install(machine, "0.1.0a3")
    machine["uvlog"].unlink()
    done = install(machine, "0.1.0a3")
    assert done.returncode == 0 and "is installed already" in done.stdout
    assert not machine["uvlog"].exists()


def test_a_package_that_says_another_version_is_removed(machine):
    says_9 = FAKE_UMCODEX.replace('echo "UM-Codex $UMCODEX_TEST_VERSION"', 'echo "UM-Codex 9"')
    executable(machine["fake"], says_9)
    done = install(machine, "0.1.0a3")
    assert done.returncode == 1 and "says 'UM-Codex 9', not 0.1.0a3" in done.stdout
    assert not (root(machine) / "versions" / "0.1.0a3").exists()


def test_the_shim_falls_back_to_the_previous_version(machine):
    install(machine, "0.1.0a3")
    install(machine, "0.1.0a4")
    app = root(machine)
    (app / "versions" / "0.1.0a4" / "bin" / "um-codex").unlink()  # broken
    shim = subprocess.run(
        [str(app / "bin" / "um-codex"), "--version"],
        env={**os.environ, "UMCODEX_TEST_LOG": str(machine["log"]), "UMCODEX_TEST_VERSION": "x"},
        capture_output=True,
        text=True,
    )
    assert shim.returncode == 0 and "opening the version before it" in shim.stderr


def test_the_shim_sets_utf8_for_python(machine):
    install(machine, "0.1.0a3")
    assert "export PYTHONUTF8=1" in (root(machine) / "bin" / "um-codex").read_text()


def test_a_version_must_start_with_a_digit(machine):
    done = install(machine, "latest")
    assert done.returncode == 2 and "umcodex-<version>-py3-none-any.whl" in done.stdout


def test_it_refuses_to_run_as_root(machine):
    executable(machine["tools"] / "id", "#!/bin/sh\necho 0\n")
    done = install(machine, "0.1.0a3")
    assert done.returncode == 1 and "Run this without sudo." in done.stdout
    assert not root(machine).exists()


def test_failing_to_pull_the_images_stops_with_what_to_do(machine):
    done = install(machine, "0.1.0a3", UMCODEX_TEST_PULL="1")
    assert done.returncode == 1, done.stdout + done.stderr
    assert "container images couldn't all be downloaded" in done.stdout
    assert "run this installer again" in done.stdout
    assert "6/6 Launcher" not in done.stdout


def test_from_a_pipe_nothing_it_runs_reads_the_rest_of_the_script(machine):
    """`curl ... | sh -s -- ...`: sh reads the whole script first, so a
    command that reads its input gets nothing of it."""
    package = package_files(machine, "0.1.0a3")
    done = subprocess.run(
        ["sh", "-s", "--", "--package", str(package)],
        input=INSTALLER.read_text(encoding="utf-8"),
        env=environment(machine, "0.1.0a3", UMCODEX_TEST_PULL_READS="1"),
        capture_output=True,
        text=True,
        timeout=60,
        start_new_session=True,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "UM-Codex is installed." in done.stdout
    assert (machine["apps"] / "UM-Codex.app" / "Contents" / "MacOS" / "UM-Codex").is_file()


# A release's files, "downloaded": curl copies the file of that name from the
# release folder (UMCODEX_TEST_RELEASE), and logs each address.
FAKE_RELEASE_CURL = """#!/bin/sh
echo "curl $*" >> "$UMCODEX_TEST_CURLLOG"
out=""
url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    *) url="$1"; shift ;;
  esac
done
cp "$UMCODEX_TEST_RELEASE/$(basename "$url")" "$out"
"""


def test_a_releases_installer_needs_no_arguments(machine, tmp_path):
    """A release's install-macos.sh has its own release's address and package
    written in (scripts/build-release.sh), so
    `curl .../releases/latest/download/install-macos.sh | sh` needs nothing more."""
    package_files(machine, "0.1.0a3")
    base = "https://github.com/SripadaLab-UM/um-codex/releases/download/v0.1.0-alpha.3"
    lines = INSTALLER.read_text(encoding="utf-8").splitlines(keepends=True)
    stamped = {
        'RELEASE_BASE=""\n': f'RELEASE_BASE="{base}"\n',
        'RELEASE_WHEEL=""\n': 'RELEASE_WHEEL="umcodex-0.1.0a3-py3-none-any.whl"\n',
    }
    assert sum(line in stamped for line in lines) == 2
    executable(machine["tools"] / "curl", FAKE_RELEASE_CURL)
    curls = tmp_path / "curls"
    done = subprocess.run(
        ["sh"],
        input="".join(stamped.get(line, line) for line in lines),
        env=environment(
            machine, "0.1.0a3", UMCODEX_TEST_RELEASE=str(machine["packages"]), UMCODEX_TEST_CURLLOG=str(curls)
        ),
        capture_output=True,
        text=True,
        timeout=60,
        start_new_session=True,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert (root(machine) / "versions" / "0.1.0a3" / ".complete").is_file()
    fetched = [line.split()[-1] for line in curls.read_text().splitlines()]
    assert fetched == [f"{base}/umcodex-0.1.0a3-py3-none-any.whl", f"{base}/requirements.txt"]
    assert all("--proto =https" in line for line in curls.read_text().splitlines())


# ------------------------------------------------------------------ the um-codex command


def test_the_um_codex_command_goes_in_your_local_bin(machine):
    done = install(machine, "0.1.0a3")
    assert done.returncode == 0, done.stdout + done.stderr
    link = machine["home"] / ".local" / "bin" / "um-codex"
    assert link.is_symlink() and Path(os.readlink(link)) == root(machine) / "bin" / "um-codex"
    assert f"The command:       {link}" in done.stdout
    # ~/.local/bin wasn't on PATH: it says the full path.
    assert f"run: '{root(machine)}/bin/um-codex'" in done.stdout


def test_with_local_bin_on_path_it_says_um_codex(machine):
    local = machine["home"] / ".local" / "bin"
    done = install(machine, "0.1.0a3", PATH=f"{machine['tools']}:{local}:{machine['system']}")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "folder you want to work in, run: um-codex\n" in done.stdout


def test_another_um_codex_command_is_left_alone(machine):
    theirs = machine["home"] / ".local" / "bin" / "um-codex"
    theirs.write_text("#!/bin/sh\n")
    done = install(machine, "0.1.0a3")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "isn't UM-Codex's; it was left alone" in done.stdout
    assert theirs.read_text() == "#!/bin/sh\n"
    assert f"run: '{root(machine)}/bin/um-codex'" in done.stdout


# ------------------------------------------------------------------ the Toolkit key

THE_KEY = "sk-test-0123456789abcdef"


def test_without_a_terminal_the_key_isnt_asked_for(machine):
    done = install(machine, "0.1.0a3")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "no terminal to type the key in" in done.stdout
    assert "um-codex key" in done.stdout
    assert keys(machine) == [] and "key" not in asked(machine)


def test_the_key_is_masked_and_handed_to_um_codex_key(machine):
    done = install(machine, "0.1.0a3", answers=[f"  {THE_KEY}", "n", "n"])
    assert done.returncode == 0, done.stdout
    assert keys(machine) == [THE_KEY]  # spaces at its ends removed
    assert THE_KEY not in done.stdout  # never shown
    assert "*" * len(THE_KEY) in done.stdout
    assert f"Received {len(THE_KEY)} characters." in done.stdout
    assert "Removed 2 spaces from the start." in done.stdout
    assert "key" in asked(machine)
    assert "The Toolkit accepted the key." in done.stdout
    # Only whether a key is saved was looked up, under um-codex's names.
    [lookup] = machine["securitylog"].read_text().splitlines()
    assert lookup == "security find-generic-password -s UM-Codex -a toolkit-api-key"
    assert "6/6 Launcher" in done.stdout


def test_a_key_the_toolkit_refuses_is_asked_for_again(machine):
    done = install(machine, "0.1.0a3", answers=["wrong-key", THE_KEY, "n", "n"], UMCODEX_TEST_KEY_EXITS="1 0")
    assert done.returncode == 0, done.stdout
    assert keys(machine) == ["wrong-key", THE_KEY]
    assert "Try again" in done.stdout


def test_three_refused_keys_go_on_without_one(machine):
    tried = ["wrong-key-1", "wrong-key-2", "wrong-key-3"]
    done = install(machine, "0.1.0a3", answers=[*tried, "n", "n"], UMCODEX_TEST_KEY_EXITS="1 1 1")
    assert done.returncode == 0, done.stdout
    assert keys(machine) == tried
    assert "asks for it the first time it opens" in done.stdout
    assert "6/6 Launcher" in done.stdout


def test_something_that_isnt_a_key_is_refused_and_asked_again(machine):
    done = install(machine, "0.1.0a3", answers=["two words", THE_KEY, "n", "n"])
    assert done.returncode == 0, done.stdout
    assert "doesn't look like an API key" in done.stdout and "Try again" in done.stdout
    assert keys(machine) == [THE_KEY]


def test_pressing_enter_skips_the_key(machine):
    done = install(machine, "0.1.0a3", answers=["", "n", "n"])
    assert done.returncode == 0, done.stdout
    assert keys(machine) == [] and "Nothing was entered" in done.stdout
    assert "asks for it the first time it opens" in done.stdout


def test_ctrl_c_at_the_key_prompt_skips_the_key(machine):
    done = install(machine, "0.1.0a3", answers=["\x03", "n", "n"])
    assert done.returncode == 0, done.stdout
    assert keys(machine) == [] and "Cancelled: nothing was saved." in done.stdout
    assert "6/6 Launcher" in done.stdout


def test_a_paste_of_more_than_one_line_is_refused(machine):
    done = install(machine, "0.1.0a3", answers=["one\ntwo", THE_KEY, "n", "n"])
    assert done.returncode == 0, done.stdout
    assert "That paste had more than one line" in done.stdout
    assert keys(machine) == [THE_KEY]


def test_backspace_and_ctrl_u_edit_the_key(machine):
    done = install(machine, "0.1.0a3", answers=["junk\x15" + THE_KEY + "x\x7f", "n", "n"])
    assert done.returncode == 0, done.stdout
    assert keys(machine) == [THE_KEY]


def test_a_saved_key_is_kept(machine):
    done = install(machine, "0.1.0a3", answers=["n", "n"], UMCODEX_TEST_KEY_SAVED="0")
    assert done.returncode == 0, done.stdout
    assert "saved already, so it was kept" in done.stdout
    assert "API key: " not in done.stdout and keys(machine) == []


def test_replace_key_asks_even_with_one_saved(machine):
    done = install(
        machine, "0.1.0a3", "--replace-key", answers=[THE_KEY, "n", "n"], UMCODEX_TEST_KEY_SAVED="0"
    )
    assert done.returncode == 0, done.stdout
    assert keys(machine) == [THE_KEY]
    assert not machine["securitylog"].exists()


def test_the_key_never_passes_through_the_installers_shell(machine):
    """Even with every command traced and every variable exported (sh's
    xtrace and allexport, on from the start through SHELLOPTS), the key isn't
    in the trace or in the environment of anything the installer runs: it's
    only ever read by `um-codex key`, from the terminal."""
    done = install(
        machine,
        "0.1.0a3",
        answers=[THE_KEY, "n", "n"],
        SHELLOPTS="xtrace:allexport",
    )
    assert done.returncode == 0, done.stdout
    assert keys(machine) == [THE_KEY]  # it was typed, and reached `um-codex key`
    assert "+ " in done.stdout and "um-codex key" in done.stdout  # the trace is on (it's in the terminal)
    assert THE_KEY not in done.stdout  # not in the trace, nor shown
    environment_seen = machine["envlog"].read_text()
    assert THE_KEY not in environment_seen
    assert "\nUMCODEX=" not in environment_seen and "\nROOT=" not in environment_seen  # set +a


def test_the_key_is_read_from_the_terminal_by_um_codex_key():
    text = INSTALLER.read_text(encoding="utf-8")
    assert '"$UMCODEX" key < /dev/tty || saved=$?' in text
    assert "--from-stdin" not in text.split('step "5/6 Toolkit key"')[1]
    assert re.search(r"\{\nset -eu\n(#[^\n]*\n)*set \+a\n", text)  # nothing set is exported


# ------------------------------------------------------------------ the app, where people look


def open_app(machine, launcher: Path, tmp_path: Path) -> tuple[str, str]:
    """Run the app's launch script, as macOS does when the app is opened.
    Returns which um-codex program ran, and its arguments."""
    who = tmp_path / "who"
    who.unlink(missing_ok=True)
    log = tmp_path / "app-log"
    log.unlink(missing_ok=True)
    env = {
        **os.environ,
        "PATH": f"{machine['tools']}:{machine['system']}",
        "UMCODEX_TEST_LOG": str(log),
        "UMCODEX_TEST_WHO": str(who),
        "UMCODEX_TEST_VERSION": "x",
    }
    subprocess.run([str(launcher)], env=env, check=True)
    return who.read_text().strip(), log.read_text().strip()


def run_in_terminal(machine, command: str, tmp_path: Path) -> str:
    """Run what Terminal would; returns which um-codex program ran."""
    who = tmp_path / "who"
    who.unlink(missing_ok=True)
    env = {
        **os.environ,
        "UMCODEX_TEST_LOG": str(machine["log"]),
        "UMCODEX_TEST_WHO": str(who),
        "UMCODEX_TEST_VERSION": "x",
    }
    subprocess.run(["sh", "-c", command], env=env, check=True)
    return who.read_text().strip()


def test_the_app_goes_in_applications_with_its_icon_and_a_desktop_shortcut(machine):
    done = install(machine, "0.1.0a3")
    assert done.returncode == 0, done.stdout + done.stderr
    app = machine["apps"] / "UM-Codex.app"
    plist = (app / "Contents" / "Info.plist").read_text()
    assert "<key>CFBundleIconFile</key><string>UM-Codex</string>" in plist
    assert "<key>CFBundleIdentifier</key><string>edu.umich.umcodex</string>" in plist
    # The icon UM-Codex brings, the app's own copy.
    assert (app / "Contents" / "Resources" / "UM-Codex.icns").read_bytes() == launchers.mac_icon()
    link = machine["home"] / "Desktop" / "UM-Codex"
    assert link.is_symlink() and Path(os.readlink(link)) == app
    assert not (machine["home"] / "Applications").exists()
    # It says where everything went, and asks nothing without a terminal.
    assert f"The app:           {app}" in done.stdout
    assert f"Desktop shortcut:  {link}" in done.stdout
    assert f"Program files:     {root(machine)}" in done.stdout
    assert "Open UM-Codex now?" not in done.stdout and "Finder? [" not in done.stdout


def alpha_1_app(machine, folder: Path, command: Path) -> Path:
    """alpha.1's app (Terminal, `launch --from-app`, a Dock icon) for `command`."""
    app = folder / "UM-Codex.app"
    for name, content in launchers.mac_app_files(command.parent.parent, b"old icon", 1).items():
        (app / name).parent.mkdir(parents=True, exist_ok=True)
        (app / name).write_bytes(content)
    return app


def test_an_alpha_1_app_is_rewritten_as_this_version_writes_it(machine):
    alpha_1_app(machine, machine["apps"], root(machine) / "bin" / "um-codex")
    done = install(machine, "0.1.0a3")
    assert done.returncode == 0, done.stdout + done.stderr
    for name, content in launchers.mac_app_files(root(machine), launchers.mac_icon()).items():
        assert (machine["apps"] / "UM-Codex.app" / name).read_bytes() == content, name


def test_another_accounts_um_codex_app_is_left_alone(machine, tmp_path):
    # UM-Codex's bundle id, in a shared /Applications, but someone else's install.
    theirs = alpha_1_app(machine, machine["apps"], tmp_path / "someone-else" / "app" / "bin" / "um-codex")
    before = (theirs / "Contents" / "MacOS" / "UM-Codex").read_bytes()
    done = install(machine, "0.1.0a3")
    assert done.returncode == 0, done.stdout + done.stderr
    assert (theirs / "Contents" / "MacOS" / "UM-Codex").read_bytes() == before
    mine = machine["home"] / "Applications" / "UM-Codex.app"
    assert f"The app:           {mine}" in done.stdout
    uninstall(machine)
    assert (theirs / "Contents" / "MacOS" / "UM-Codex").read_bytes() == before
    assert not mine.exists()


def test_an_app_that_couldnt_be_written_is_removed_so_the_next_install_works(machine):
    done = install(machine, "0.1.0a3", UMCODEX_TEST_LAUNCHERS="fail")
    assert done.returncode == 1
    assert "The app couldn't be made in" in done.stdout
    assert not (machine["apps"] / "UM-Codex.app").exists()  # the half-made one
    again = install(machine, "0.1.0a3")
    assert again.returncode == 0, again.stdout + again.stderr
    assert launchers.is_our_app(machine["apps"] / "UM-Codex.app", root(machine))


def test_without_rights_to_applications_it_uses_your_own(machine):
    machine["apps"].chmod(0o555)
    try:
        done = install(machine, "0.1.0a3")
    finally:
        machine["apps"].chmod(0o755)
    assert done.returncode == 0, done.stdout + done.stderr
    app = machine["home"] / "Applications" / "UM-Codex.app"
    assert (app / "Contents" / "MacOS" / "UM-Codex").is_file()
    assert Path(os.readlink(machine["home"] / "Desktop" / "UM-Codex")) == app
    assert list(machine["apps"].iterdir()) == []


def test_someone_elses_app_of_that_name_is_left_alone(machine):
    theirs = machine["apps"] / "UM-Codex.app" / "Contents"
    theirs.mkdir(parents=True)
    (theirs / "Info.plist").write_text("<string>org.example.umcodex</string>")
    done = install(machine, "0.1.0a3")
    assert done.returncode == 0, done.stdout + done.stderr
    assert (theirs / "Info.plist").read_text() == "<string>org.example.umcodex</string>"
    assert (machine["home"] / "Applications" / "UM-Codex.app").is_dir()


def test_an_earlier_installers_copy_in_your_applications_goes(machine):
    machine["apps"].chmod(0o555)
    try:
        install(machine, "0.1.0a3")  # into ~/Applications, as before
    finally:
        machine["apps"].chmod(0o755)
    done = install(machine, "0.1.0a3")
    assert "Removed the copy an earlier installer put in" in done.stdout
    assert not (machine["home"] / "Applications" / "UM-Codex.app").exists()
    link = machine["home"] / "Desktop" / "UM-Codex"
    assert Path(os.readlink(link)) == machine["apps"] / "UM-Codex.app"  # moved with it


def test_other_things_on_the_desktop_are_left_alone(machine):
    desktop = machine["home"] / "Desktop"
    (desktop / "UM-Codex").write_text("my notes")
    done = install(machine, "0.1.0a3")
    assert "Your Desktop already has something called UM-Codex; it was left alone." in done.stdout
    assert (desktop / "UM-Codex").read_text() == "my notes"


def test_the_app_and_its_shortcut_keep_working_after_a_newer_version(machine, tmp_path):
    install(machine, "0.1.0a3")
    app = root(machine)
    launcher = machine["home"] / "Desktop" / "UM-Codex" / "Contents" / "MacOS" / "UM-Codex"
    assert "versions" not in launcher.read_text()  # never a version's own folder
    # A newer version beside the old one, the launcher's command switched to
    # it, then the old one removed (as an updater would).
    install(machine, "0.1.0a4")
    subprocess.run(["rm", "-rf", str(app / "versions" / "0.1.0a3")], check=True)
    # Open the app through the Desktop shortcut: it runs the shim, which runs
    # the new version's launcher window.
    assert f"exec '{app / 'bin' / 'um-codex'}' ui --detach" in launcher.read_text()
    ran, args = open_app(machine, launcher, tmp_path)
    assert Path(ran) == app / "versions" / "0.1.0a4" / "bin" / "um-codex"
    assert args == "ui --detach"
    assert (machine["apps"] / "UM-Codex.app" / "Contents" / "Resources" / "UM-Codex.icns").is_file()


def test_the_app_opens_from_a_home_folder_with_an_apostrophe(machine, tmp_path):
    home = tmp_path / "o'brien"
    (home / ".local" / "bin").mkdir(parents=True)
    (home / "Desktop").mkdir()
    machine = {**machine, "home": home}
    done = install(machine, "0.1.0a3")
    assert done.returncode == 0, done.stdout + done.stderr
    launcher = machine["apps"] / "UM-Codex.app" / "Contents" / "MacOS" / "UM-Codex"
    subprocess.run(["sh", "-n", str(launcher)], check=True)  # the launch script parses
    ran, args = open_app(machine, launcher, tmp_path)
    assert "o'brien" in ran and args == "ui --detach"
    assert Path(ran) == root(machine) / "versions" / "0.1.0a3" / "bin" / "um-codex"
    # And the command it says to run works as printed.
    how = done.stdout.split("folder you want to work in, run: ", 1)[1].split("\n", 1)[0]
    assert Path(run_in_terminal(machine, how, tmp_path)) == Path(ran)


def test_someone_elses_app_in_your_applications_stops_the_install_there(machine):
    machine["apps"].chmod(0o555)
    theirs = machine["home"] / "Applications" / "UM-Codex.app" / "Contents"
    theirs.mkdir(parents=True)
    (theirs / "Info.plist").write_text("<string>org.example.umcodex</string>")
    try:
        done = install(machine, "0.1.0a3")
    finally:
        machine["apps"].chmod(0o755)
    assert done.returncode == 1
    assert "is another app, not UM-Codex's, so it was left alone" in done.stdout
    assert (theirs / "Info.plist").read_text() == "<string>org.example.umcodex</string>"
    assert not (machine["home"] / "Desktop" / "UM-Codex").exists()


def test_our_app_that_cant_be_replaced_in_applications_falls_back_to_yours(machine):
    install(machine, "0.1.0a3")
    stuck = machine["apps"] / "UM-Codex.app" / "Contents"
    stuck.chmod(0o555)  # rm can't empty it
    try:
        done = install(machine, "0.1.0a3")
    finally:
        stuck.chmod(0o755)
    assert done.returncode == 0, done.stdout + done.stderr
    app = machine["home"] / "Applications" / "UM-Codex.app"
    assert f"The app:           {app}" in done.stdout
    assert "An earlier copy is still in" in done.stdout
    assert Path(os.readlink(machine["home"] / "Desktop" / "UM-Codex")) == app


def test_our_app_that_cant_be_replaced_in_your_applications_says_what_to_do(machine):
    machine["apps"].chmod(0o555)
    try:
        install(machine, "0.1.0a3")
        stuck = machine["home"] / "Applications" / "UM-Codex.app" / "Contents"
        stuck.chmod(0o555)
        try:
            done = install(machine, "0.1.0a3")
        finally:
            stuck.chmod(0o755)
    finally:
        machine["apps"].chmod(0o755)
    assert done.returncode == 1
    assert "couldn't be replaced. Quit UM-Codex if it's open" in done.stdout
    assert "rm:" not in done.stdout + done.stderr


def test_a_desktop_link_to_another_um_codex_app_is_left_alone(machine):
    link = machine["home"] / "Desktop" / "UM-Codex"
    link.symlink_to("/Vendor/UM-Codex.app")
    done = install(machine, "0.1.0a3")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "to something else; it was left alone" in done.stdout
    assert os.readlink(link) == "/Vendor/UM-Codex.app"
    uninstall(machine)
    assert os.readlink(link) == "/Vendor/UM-Codex.app"


# ------------------------------------------------------------------ uninstalling


def uninstall(machine, *args: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(UNINSTALLER), *args],
        env=environment(machine, "0.1.0a3", **extra_env),
        capture_output=True,
        text=True,
        timeout=60,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
    )


def test_uninstall_runs_um_codex_uninstall_then_removes_the_program_app_and_shortcuts(machine):
    install(machine, "0.1.0a3")
    other = machine["apps"] / "Other.app"
    other.mkdir()
    (machine["home"] / "Desktop" / "notes.txt").write_text("mine")
    cache = machine["home"] / "Library" / "Caches" / "UM-Codex" / "docker-desktop"
    cache.mkdir(parents=True)
    machine["log"].unlink()
    done = uninstall(machine, "--some-option")
    assert done.returncode == 0, done.stdout + done.stderr
    assert asked(machine) == ["uninstall --some-option"]  # its options passed on
    assert [p.name for p in machine["apps"].iterdir()] == ["Other.app"]
    assert [p.name for p in (machine["home"] / "Desktop").iterdir()] == ["notes.txt"]
    assert not root(machine).exists()
    assert not (machine["home"] / ".local" / "bin" / "um-codex").exists()
    assert not cache.parent.exists()
    assert "UM-Codex has been removed." in done.stdout


def test_uninstall_stops_if_um_codex_uninstall_does(machine):
    install(machine, "0.1.0a3")
    done = uninstall(machine, UMCODEX_TEST_UNINSTALL="1")
    assert done.returncode == 1
    assert "Nothing else was removed." in done.stdout
    assert "has been removed" not in done.stdout
    assert (root(machine) / "current").is_file()
    assert (machine["apps"] / "UM-Codex.app").is_dir()


def test_uninstall_leaves_someone_elses_app_and_command(machine):
    install(machine, "0.1.0a3")
    theirs = machine["home"] / "Applications" / "UM-Codex.app" / "Contents"
    theirs.mkdir(parents=True)
    (theirs / "Info.plist").write_text("<string>org.example.umcodex</string>")
    command = machine["home"] / ".local" / "bin" / "um-codex"
    command.unlink()
    command.symlink_to("/somewhere/else/um-codex")
    done = uninstall(machine)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (theirs / "Info.plist").is_file()
    assert os.readlink(command) == "/somewhere/else/um-codex"
    assert not (machine["apps"] / "UM-Codex.app").exists()


def test_uninstall_without_an_install_still_tidies_up(machine):
    done = uninstall(machine)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "program files weren't found" in done.stdout
    # It says what may still be there.
    assert "Toolkit key in your Keychain" in done.stdout and "saved setups" in done.stdout


def test_uninstall_answers_in_the_terminal(machine):
    """`um-codex uninstall` reads the terminal, even when the script's own
    input is something else (a pipe); without one it reads nothing."""
    install(machine, "0.1.0a3")
    machine["log"].unlink()
    command = ["sh", str(UNINSTALLER)]
    done = in_terminal(command, environment(machine, "0.1.0a3"), [])
    assert done.returncode == 0, done.stdout
    assert asked(machine) == ["uninstall", "uninstall read a terminal"]
    install(machine, "0.1.0a3")
    machine["log"].unlink()
    assert uninstall(machine).returncode == 0  # no terminal: stdin is /dev/null
    assert asked(machine) == ["uninstall"]


def test_uninstall_refuses_to_run_as_root(machine):
    executable(machine["tools"] / "id", "#!/bin/sh\necho 0\n")
    done = uninstall(machine)
    assert done.returncode == 1 and "Run this without sudo." in done.stdout


# ------------------------------------------------------------ Docker Desktop
#
# Docker Desktop, its disk image and macOS's tools are stand-ins too: `open`
# "starts" Docker by writing to a state file that the fake `docker` reads,
# `hdiutil` "mounts" a copy of a folder that stands in for the disk image
# (and "detaches" it by moving it aside), and `codesign`/`spctl` report the
# signer written in the fake app. `sleep` moves a fake clock (read by
# `date +%s`) on instead of waiting. `ps` lists Docker's programs as running
# for each Docker.app in the two Applications folders, `mdfind` finds what a
# test says, and `ditto` can be made to fail. The real Docker Desktop is never
# used.

FAKE_DOCKER = """#!/bin/sh
echo "docker $*" >> "$UMCODEX_TEST_DOCKERLOG"
if [ "$1" = desktop ]; then
  [ -z "${UMCODEX_TEST_NO_DESKTOP_COMMAND:-}" ] || { echo "unknown command" >&2; exit 1; }
  case "$*" in *--help*) exit 0 ;; esac
  echo restarted > "$UMCODEX_TEST_STATE.restarted"
  exit 0
fi
if [ "$1" = info ]; then
  # A stuck engine ("500 Internal Server Error"): answers only after a
  # restart ("stuck"), or never ("dead").
  case "${UMCODEX_TEST_ENGINE:-}" in
    dead) exit 1 ;;
    stuck) [ -f "$UMCODEX_TEST_STATE.restarted" ] || exit 1 ;;
  esac
  calls=$(( $(cat "$UMCODEX_TEST_STATE.calls" 2>/dev/null || echo 0) + 1 ))
  echo "$calls" > "$UMCODEX_TEST_STATE.calls"
  [ "$(cat "$UMCODEX_TEST_STATE" 2>/dev/null)" = running ] || exit 1
  [ "$calls" -ge "${UMCODEX_TEST_READY_AFTER:-0}" ] || exit 1
fi
exit 0
"""

DOCKER_TOOLS = {
    "open": """#!/bin/sh
echo "open $*" >> "$UMCODEX_TEST_OPENLOG"
case "$1" in
  *.app)
    [ -z "${UMCODEX_TEST_OPEN_FAILS:-}" ] || exit 1
    if [ "${UMCODEX_TEST_OPEN_STARTS:-1}" = 1 ]; then echo running > "$UMCODEX_TEST_STATE"; fi ;;
esac
exit 0
""",
    # Not an administrator unless a test says so.
    "id": """#!/bin/sh
case "$1" in
  -Gn) echo "${UMCODEX_TEST_GROUPS:-staff everyone}" ;;
  -un) echo tester ;;
  *) exec /usr/bin/id "$@" ;;
esac
""",
    # Never asks for a password: logs the command, then runs it (or is "cancelled").
    "sudo": """#!/bin/sh
echo "sudo $*" >> "$UMCODEX_TEST_SUDOLOG"
if [ -n "${UMCODEX_TEST_SUDO_CANCEL:-}" ]; then echo "sudo: a password is required" >&2; exit 1; fi
exec "$@"
""",
    # plutil -extract <key> raw -o - <plist>, for the fake apps' one-line keys.
    "plutil": """#!/bin/sh
for file; do :; done
value="$(sed -n "s|.*<key>$2</key><string>\\(.*\\)</string>.*|\\1|p" "$file" 2>/dev/null)"
value="${value%%
*}"
[ -n "$value" ] || exit 1
printf '%s\\n' "$value"
""",
    "ps": """#!/bin/sh
[ -z "${UMCODEX_TEST_NOT_ALIVE:-}" ] || exit 0
for app in "$UMCODEX_SYSTEM_APPLICATIONS/Docker.app" "$HOME/Applications/Docker.app" \\
  ${UMCODEX_TEST_ALIVE:+"$UMCODEX_TEST_ALIVE"}; do
  echo "$app/Contents/MacOS/com.docker.backend"
done
""",
    "sleep": """#!/bin/sh
echo $(( $(cat "$UMCODEX_TEST_CLOCK" 2>/dev/null || echo 1000) + $1 )) > "$UMCODEX_TEST_CLOCK"
""",
    "date": """#!/bin/sh
[ "$1" = +%s ] || exec /bin/date "$@"
cat "$UMCODEX_TEST_CLOCK" 2>/dev/null || echo 1000
""",
    "mdfind": '#!/bin/sh\necho "mdfind $*" >> "$UMCODEX_TEST_MDFINDLOG"\n'
    '[ -z "${UMCODEX_TEST_MDFIND:-}" ] || printf \'%s\\n\' "$UMCODEX_TEST_MDFIND"\n',
    "ditto": """#!/bin/sh
case "${UMCODEX_TEST_DITTO:-}" in
  # Ctrl-C, as a terminal sends it: to the whole foreground process group,
  # once the installer is waiting for this copy (asleep in wait), and the copy
  # dies of it. A copy that exited normally instead would tell sh (bash 3.2)
  # that it dealt with the Ctrl-C itself, and the installer would carry on.
  interrupt)
    mkdir -p "$2/Contents"; echo half > "$2/Contents/half"
    tries=0
    until /bin/ps -o stat= -p "$PPID" | grep -q '^ *[SI]' || [ "$tries" -ge 200 ]; do
      tries=$((tries + 1)); /bin/sleep 0.05
    done
    trap - INT
    kill -INT 0
    kill -INT $$
    /bin/sleep 30; exit 1 ;;  # (not reached: it has died of SIGINT by now)
  not-permitted) echo "ditto: $2: Operation not permitted" >&2; exit 1 ;;
  fails) echo "ditto: $2: No space left on device" >&2; exit 1 ;;
  tamper) cp -R "$1" "$2" && echo "Other (ABCDE12345)" > "$2/Contents/fake-signer" ;;
  race) cp -R "$1" "$2" && mkdir -p "$(dirname "$2")/Docker.app/Contents" ;;
  *) exec cp -R "$1" "$2" ;;  # what ditto does here, on any system
esac
""",
    "sysctl": """#!/bin/sh
case "$*" in *hw.optional.arm64*) echo "${UMCODEX_TEST_ARM64:-1}" ;; *) exit 1 ;; esac
""",
    "uname": """#!/bin/sh
if [ "$1" = -m ]; then echo "${UMCODEX_TEST_MACHINE:-arm64}"; else /usr/bin/uname "$@"; fi
""",
    "sw_vers": '#!/bin/sh\necho "${UMCODEX_TEST_MACOS:-15.1}"\n',
    "df": """#!/bin/sh
echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
echo "/dev/disk3s5 900000000 1 ${UMCODEX_TEST_FREE_KB:-104857600} 1% /"
""",
    # Docker's download: a stand-in disk image, or a failure.
    "curl": """#!/bin/sh
echo "curl $*" >> "$UMCODEX_TEST_CURLLOG"
case "$*" in
  *desktop.docker.com*) ;;
  *) echo 'no downloads in tests' >&2; exit 1 ;;
esac
while [ $# -gt 0 ]; do
  if [ "$1" = -o ]; then out="$2"; fi
  shift
done
if [ -n "${UMCODEX_TEST_CURL_FAILS:-}" ]; then
  echo partial >> "$out"
  exit "$UMCODEX_TEST_CURL_FAILS"
fi
echo "${UMCODEX_TEST_DMG:-image}" >> "$out"
""",
    "hdiutil": """#!/bin/sh
echo "hdiutil $*" >> "$UMCODEX_TEST_HDIUTILLOG"
case "$1" in
  attach)
    while [ $# -gt 0 ]; do
      if [ "$1" = -mountpoint ]; then mount="$2"; fi
      last="$1"; shift
    done
    if grep -q corrupt "$last"; then exit 1; fi
    cp -R "$UMCODEX_TEST_DMG_SOURCE/." "$mount/" ;;
  detach)
    for mount; do :; done
    if [ -d "$mount" ]; then mv "$mount" "$(mktemp -d "$UMCODEX_TEST_DETACHED/m.XXXXXX")/"; fi ;;
esac
""",
    "codesign": """#!/bin/sh
for app; do :; done
if [ -f "$app" ]; then
  signer="${UMCODEX_TEST_DMG_SIGNER:-Docker Inc (9BNSXJN65R)}"  # the disk image
else
  signer="$(cat "$app/Contents/fake-signer" 2>/dev/null)" || exit 1
fi
case "$*" in
  *'-R=anchor apple generic and certificate leaf[subject.OU] = "9BNSXJN65R"'*)
    case "$signer" in *"(9BNSXJN65R)") ;; *) exit 3 ;; esac ;;
  *-R=*) exit 3 ;;
esac
case "$1" in
  --verify) [ "$signer" != broken ] || exit 1 ;;
  -dv) echo "Identifier=com.docker.docker" >&2
       echo "TeamIdentifier=${signer##*(}" | tr -d ')' >&2 ;;
esac
""",
    "spctl": """#!/bin/sh
for app; do :; done
signer="$(cat "$app/Contents/fake-signer" 2>/dev/null)" || exit 3
if [ -n "${UMCODEX_TEST_SPCTL_REJECTS:-}" ]; then echo "$app: rejected" >&2; exit 3; fi
if [ -n "${UMCODEX_TEST_GATEKEEPER_OFF:-}" ]; then
  printf '%s: accepted\\noverride=security disabled\\n' "$app" >&2; exit 0
fi
printf '%s: accepted\\nsource=Notarized Developer ID\\norigin=Developer ID Application: %s\\n' \\
  "$app" "$signer" >&2
""",
}

FAKE_DOCKER_INSTALL = """#!/bin/sh
echo "install $*" >> "$UMCODEX_TEST_SUDOLOG"
[ -z "${UMCODEX_TEST_INSTALL_FAILS:-}" ] || exit 3
app="$(cd "$(dirname "$0")/../.." && pwd)"
cp -R "$app" "$UMCODEX_SYSTEM_APPLICATIONS/Docker.app"
"""

DOCKER_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>com.docker.docker</string>
  <key>CFBundleExecutable</key><string>com.docker.backend</string>
  <key>CFBundleShortVersionString</key><string>4.93.0</string>
  <key>LSMinimumSystemVersion</key><string>{minimum}</string>
</dict></plist>
"""


def fake_docker_app(where: Path, *, signer: str = "Docker Inc (9BNSXJN65R)") -> Path:
    app = where / "Docker.app"
    (app / "Contents" / "Resources" / "bin").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_text(DOCKER_PLIST.format(minimum="14.0"))
    (app / "Contents" / "fake-signer").write_text(signer)
    executable(app / "Contents" / "Resources" / "bin" / "docker", FAKE_DOCKER)
    (app / "Contents" / "MacOS").mkdir()
    executable(app / "Contents" / "MacOS" / "com.docker.backend", "#!/bin/sh\n")
    return app


@pytest.fixture
def mac(machine, tmp_path) -> dict[str, Path]:
    """A Mac without Docker Desktop: no docker on PATH, none installed."""
    (machine["tools"] / "docker").unlink()
    for name, text in DOCKER_TOOLS.items():
        executable(machine["tools"] / name, text)
    dmg = tmp_path / "dmg-contents"
    dmg.mkdir()
    # Docker's own installer: puts the app it's in into /Applications.
    install_command = fake_docker_app(dmg) / "Contents" / "MacOS" / "install"
    executable(install_command, FAKE_DOCKER_INSTALL)
    detached = tmp_path / "detached"
    detached.mkdir()
    names = ("open", "curl", "hdiutil", "docker", "path", "mdfind", "sudo")
    logs = {name: tmp_path / f"{name}.log" for name in names}
    return {**machine, "dmg": dmg, "detached": detached, "state": tmp_path / "docker-state", **logs}


def docker_install(
    mac, *args: str, answers: list[str] | None = None, **env: str
) -> subprocess.CompletedProcess[str]:
    return install(
        mac,
        "0.1.0a3",
        *args,
        answers=answers,
        UMCODEX_TEST_STATE=str(mac["state"]),
        UMCODEX_TEST_OPENLOG=str(mac["open"]),
        UMCODEX_TEST_CURLLOG=str(mac["curl"]),
        UMCODEX_TEST_HDIUTILLOG=str(mac["hdiutil"]),
        UMCODEX_TEST_DOCKERLOG=str(mac["docker"]),
        UMCODEX_TEST_PATHLOG=str(mac["path"]),
        UMCODEX_TEST_DMG_SOURCE=str(mac["dmg"]),
        UMCODEX_TEST_DETACHED=str(mac["detached"]),
        UMCODEX_TEST_MDFINDLOG=str(mac["mdfind"]),
        UMCODEX_TEST_SUDOLOG=str(mac["sudo"]),
        UMCODEX_TEST_CLOCK=str(mac["state"].with_name("clock")),
        UMCODEX_DOCKER_POLL_SECONDS="5",
        **env,
    )


def lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def cache(mac) -> Path:
    return mac["home"] / "Library" / "Caches" / "UM-Codex" / "docker-desktop"


def test_docker_already_running_is_used_as_it_is(mac):
    executable(mac["tools"] / "docker", FAKE_DOCKER)
    mac["state"].write_text("running")
    done = docker_install(mac)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "Docker Desktop is running." in done.stdout
    assert lines(mac["open"]) == [] and lines(mac["curl"]) == []
    assert "isn't on your PATH" not in done.stdout
    assert "6/6 Launcher" in done.stdout


def test_docker_installed_but_stopped_is_started_and_waited_for(mac):
    app = fake_docker_app(mac["apps"])
    (app / "Contents" / "mine").write_text("my settings")
    executable(mac["tools"] / "docker", FAKE_DOCKER)
    done = docker_install(mac, UMCODEX_TEST_READY_AFTER="10")
    assert done.returncode == 0, done.stdout + done.stderr
    assert lines(mac["open"]) == [f"open {app}"]
    assert "Starting Docker Desktop" in done.stdout
    assert "Still waiting for Docker Desktop (30 seconds)" in done.stdout
    assert "Docker Desktop is running." in done.stdout
    # Nothing downloaded or reinstalled; the app is as it was.
    assert lines(mac["curl"]) == [] and lines(mac["hdiutil"]) == []
    assert (app / "Contents" / "mine").read_text() == "my settings"
    assert "Docker Subscription Service Agreement" not in done.stdout
    assert "6/6 Launcher" in done.stdout


@pytest.mark.parametrize("where", ["system", "user"])
def test_docker_whose_command_isnt_on_path_is_found_in_the_app(mac, where):
    folder = mac["apps"] if where == "system" else mac["home"] / "Applications"
    folder.mkdir(exist_ok=True)
    app = fake_docker_app(folder)
    mac["state"].write_text("running")
    done = docker_install(mac)
    assert done.returncode == 0, done.stdout + done.stderr
    bin_dir = app / "Contents" / "Resources" / "bin"
    assert f"UM-Codex finds it in {bin_dir}" in done.stdout
    assert lines(mac["open"]) == []
    # The rest of the install (pulling images, setup) finds it on PATH.
    assert lines(mac["path"]) and all(str(bin_dir) in line.split(":") for line in lines(mac["path"]))
    assert "docker info" in lines(mac["docker"])


def test_docker_stopped_with_its_command_off_path_is_started(mac):
    app = fake_docker_app(mac["apps"])
    done = docker_install(mac)
    assert done.returncode == 0, done.stdout + done.stderr
    assert lines(mac["open"]) == [f"open {app}"]
    assert "UM-Codex finds it in" in done.stdout


def test_the_command_in_your_docker_folder_is_found(mac):
    folder = mac["home"] / ".docker" / "bin"
    folder.mkdir(parents=True)
    executable(folder / "docker", FAKE_DOCKER)
    mac["state"].write_text("running")
    done = docker_install(mac)
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"UM-Codex finds it in {folder}" in done.stdout


def test_pressing_return_at_the_docker_question_installs_it(mac):
    """In a terminal, the question's default is yes: pressing Return installs."""
    done = docker_install(mac, answers=[""])
    assert done.returncode == 0, done.stdout
    assert "Download and install Docker Desktop? [Y/n]" in done.stdout
    assert len(lines(mac["curl"])) == 1
    assert (mac["apps"] / "Docker.app" / "Contents" / "fake-signer").is_file()
    assert "6/6 Launcher" in done.stdout


@pytest.mark.parametrize("answer", ["n", "N", "no", "NO"])
def test_typing_n_at_the_docker_question_changes_nothing(mac, answer):
    done = docker_install(mac, answers=[answer])
    refused(done, mac, "Download and install Docker Desktop? [Y/n]", "wasn't installed")
    assert lines(mac["curl"]) == [] and not cache(mac).exists()


def test_typing_y_at_the_docker_question_installs_it(mac):
    done = docker_install(mac, answers=["y"])
    assert done.returncode == 0, done.stdout
    assert (mac["apps"] / "Docker.app" / "Contents" / "fake-signer").is_file()


def test_a_fresh_mac_gets_docker_desktop_downloaded_checked_and_installed(mac):
    done = docker_install(mac, "--install-docker")
    assert done.returncode == 0, done.stdout + done.stderr
    out = done.stdout
    [curl] = lines(mac["curl"])
    assert "https://desktop.docker.com/mac/main/arm64/Docker.dmg" in curl
    assert "--proto =https" in curl and "-C -" in curl
    assert "for this Mac (Apple silicon)" in out
    assert "this installer doesn't accept it for you" in out
    assert "your organisation may have its" in out
    assert "It's Docker Desktop 4.93.0, signed and notarized by Docker Inc." in out
    app = mac["apps"] / "Docker.app"
    assert (app / "Contents" / "fake-signer").is_file()
    assert not (mac["apps"] / ".Docker.app.umcodex-partial").exists()
    attach, detach = lines(mac["hdiutil"])
    assert attach.startswith("hdiutil attach -quiet -nobrowse -readonly -noautoopen -mountpoint ")
    assert detach.startswith("hdiutil detach")
    assert not cache(mac).exists()  # the download is deleted
    # First launch: the person accepts Docker's agreement in Docker's window.
    assert lines(mac["open"]) == [f"open {app}"]
    assert "It shows the Docker Subscription Service Agreement. Read it and choose" in out
    assert 'Choose "Use recommended settings", then Finish.' in out
    assert "choose Skip" in out
    assert "6/6 Launcher" in out
    # Run again: it's found, not downloaded again.
    again = docker_install(mac, "--install-docker")
    assert again.returncode == 0, again.stdout + again.stderr
    assert len(lines(mac["curl"])) == 1


@pytest.mark.parametrize(
    ("arm64", "machine_name", "url"),
    [("0", "x86_64", "amd64"), ("1", "x86_64", "arm64")],  # Intel; Apple silicon under Rosetta
)
def test_the_download_matches_the_processor(mac, arm64, machine_name, url):
    done = docker_install(
        mac, "--install-docker", UMCODEX_TEST_ARM64=arm64, UMCODEX_TEST_MACHINE=machine_name
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"/mac/main/{url}/Docker.dmg" in lines(mac["curl"])[0]


def test_without_rights_to_applications_docker_goes_in_yours(mac):
    mac["apps"].chmod(0o555)
    try:
        done = docker_install(mac, "--install-docker")
    finally:
        mac["apps"].chmod(0o755)
    assert done.returncode == 0, done.stdout + done.stderr
    app = mac["home"] / "Applications" / "Docker.app"
    assert (app / "Contents" / "fake-signer").is_file()
    assert lines(mac["open"])[0] == f"open {app}"
    assert 'the command line tools to "User"' in done.stdout


def refused(done: subprocess.CompletedProcess[str], mac, *phrases: str) -> None:
    assert done.returncode == 1, done.stdout + done.stderr
    for phrase in phrases:
        assert phrase in done.stdout
    assert "run this installer again" in done.stdout
    assert not (mac["apps"] / "Docker.app").exists()
    assert not (mac["home"] / "Applications" / "Docker.app").exists()
    assert "2/6 uv" not in done.stdout  # it stops at the Docker step


def test_no_terminal_to_answer_changes_nothing_and_running_again_carries_on(mac):
    done = docker_install(mac)  # no terminal to answer: no, whatever the default
    refused(done, mac, "Download and install Docker Desktop? [Y/n]", "wasn't installed")
    assert "drag Docker to Applications" in done.stdout
    assert lines(mac["curl"]) == [] and not cache(mac).exists()
    again = docker_install(mac, "--install-docker")
    assert again.returncode == 0, again.stdout + again.stderr


def test_an_unsupported_mac_is_told_so(mac):
    done = docker_install(mac, "--install-docker", UMCODEX_TEST_ARM64="0", UMCODEX_TEST_MACHINE="i386")
    assert done.returncode == 1 and "isn't one Docker Desktop supports" in done.stdout
    assert lines(mac["curl"]) == []


def test_an_old_macos_is_told_to_update_first(mac):
    done = docker_install(mac, "--install-docker", UMCODEX_TEST_MACOS="13.6.1")
    refused(done, mac, "needs macOS 14.0 or newer, and this Mac has macOS 13.6.1")
    assert "Software Update" in done.stdout and lines(mac["curl"]) == []


def test_a_macos_older_than_the_download_needs_stops_before_installing(mac):
    plist = mac["dmg"] / "Docker.app" / "Contents" / "Info.plist"
    plist.write_text(DOCKER_PLIST.format(minimum="15.0"))
    done = docker_install(mac, "--install-docker", UMCODEX_TEST_MACOS="14.7")
    refused(done, mac, "This Docker Desktop needs macOS 15.0 or newer")
    assert not (cache(mac) / "Docker-arm64.dmg").exists()


def test_not_enough_disk_space_is_said_before_downloading(mac):
    done = docker_install(mac, "--install-docker", UMCODEX_TEST_FREE_KB=str(2 * 1024 * 1024))
    refused(done, mac, "about 6 GB of free disk space", "this Mac has 2 GB free")
    assert lines(mac["curl"]) == []


def test_a_failed_download_is_resumed_next_time(mac):
    done = docker_install(mac, "--install-docker", UMCODEX_TEST_CURL_FAILS="56")
    refused(done, mac, "didn't finish (curl stopped with code 56)", "continues the download")
    part = cache(mac) / "Docker-arm64.dmg.part"
    assert part.read_text() == "partial\n"
    again = docker_install(mac, "--install-docker")
    assert again.returncode == 0, again.stdout + again.stderr
    assert all("-C -" in line and str(part) in line for line in lines(mac["curl"]))


def test_a_download_that_cant_be_resumed_starts_afresh_next_time(mac):
    done = docker_install(mac, "--install-docker", UMCODEX_TEST_CURL_FAILS="22")
    refused(done, mac, "curl stopped with code 22")
    assert not (cache(mac) / "Docker-arm64.dmg.part").exists()


def test_a_damaged_download_is_deleted(mac):
    done = docker_install(mac, "--install-docker", UMCODEX_TEST_DMG="corrupt")
    refused(done, mac, "couldn't be opened", "downloads it again")
    assert list(cache(mac).iterdir()) == []


@pytest.mark.parametrize(
    ("signer", "env"),
    [
        ("Someone Else (ABCDE12345)", {}),  # another developer
        ("broken", {}),  # a signature that doesn't verify
        ("Docker Inc (9BNSXJN65R)", {"UMCODEX_TEST_SPCTL_REJECTS": "1"}),  # not notarized
    ],
)
def test_a_download_not_signed_by_docker_is_refused(mac, signer, env):
    (mac["dmg"] / "Docker.app" / "Contents" / "fake-signer").write_text(signer)
    done = docker_install(mac, "--install-docker", **env)
    refused(done, mac, "didn't pass macOS's checks", "team 9BNSXJN65R", "Nothing from it was run")
    assert list(cache(mac).iterdir()) == []
    assert lines(mac["hdiutil"])[-1].startswith("hdiutil detach")
    assert lines(mac["open"]) == []


def test_a_blocked_copy_says_to_ask_it(mac):
    user_apps = mac["home"] / "Applications"
    mac["apps"].chmod(0o555)
    user_apps.mkdir(mode=0o555)
    try:
        done = docker_install(mac, "--install-docker")
    finally:
        mac["apps"].chmod(0o755)
        user_apps.chmod(0o755)
    refused(done, mac, "couldn't be copied to", "Self Service app or ask IT")
    assert not (user_apps / ".Docker.app.umcodex-partial").exists()
    assert lines(mac["hdiutil"])[-1].startswith("hdiutil detach")


def test_a_copy_left_half_done_is_replaced(mac):
    leftover = mac["apps"] / ".Docker.app.umcodex-partial"
    leftover.mkdir()
    (leftover / "half").write_text("")
    done = docker_install(mac, "--install-docker")
    assert done.returncode == 0, done.stdout + done.stderr
    assert not leftover.exists() and (mac["apps"] / "Docker.app").is_dir()


def test_declining_dockers_agreement_is_explained(mac):
    done = docker_install(mac, "--install-docker", UMCODEX_TEST_OPEN_STARTS="0", UMCODEX_TEST_NOT_ALIVE="1")
    assert done.returncode == 1, done.stdout + done.stderr
    assert "closed before it was ready. If you declined its agreement" in done.stdout
    assert "run this installer again" in done.stdout
    # Docker Desktop stays installed; running again just starts it.
    app = mac["apps"] / "Docker.app"
    again = docker_install(mac)
    assert again.returncode == 0, again.stdout + again.stderr
    assert lines(mac["open"])[-1] == f"open {app}" and len(lines(mac["curl"])) == 1


def test_docker_that_doesnt_start_in_time_is_explained(mac):
    fake_docker_app(mac["apps"])
    done = docker_install(mac, UMCODEX_TEST_OPEN_STARTS="0", UMCODEX_DOCKER_WAIT_SECONDS="60")
    assert done.returncode == 1, done.stdout + done.stderr
    # Its programs are running, so it's the engine that isn't answering.
    assert "its engine isn't answering after 60 seconds" in done.stdout
    assert "whale menu at the top of the screen > Restart" in done.stdout
    assert "Still waiting for Docker Desktop (30 seconds)" in done.stdout
    usual = docker_install(mac, UMCODEX_TEST_OPEN_STARTS="0")
    assert "isn't answering after 5 minutes" in usual.stdout


def test_docker_that_cant_be_opened_is_explained(mac):
    fake_docker_app(mac["apps"])
    done = docker_install(mac, UMCODEX_TEST_OPEN_FAILS="1")
    assert done.returncode == 1 and "couldn't be opened" in done.stdout


def test_another_docker_command_that_isnt_answering_is_mentioned(mac):
    executable(mac["tools"] / "docker", FAKE_DOCKER)
    done = docker_install(mac)
    refused(done, mac, "isn't answering, and Docker", "(Colima, OrbStack)")


def test_it_can_stop_after_the_docker_step(mac):
    mac["state"].write_text("running")
    executable(mac["tools"] / "docker", FAKE_DOCKER)
    done = docker_install(mac, UMCODEX_INSTALL_STOP_AFTER_DOCKER="1")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "Stopping here" in done.stdout and "2/6 uv" not in done.stdout
    assert not root(mac).exists() and not mac["log"].exists()


def test_the_installer_never_resets_prunes_or_accepts_for_you():
    text = INSTALLER.read_text()
    for never in ("prune", "docker rm", "--accept-license", "group.com.docker"):
        assert never not in text


def test_ctrl_c_while_copying_leaves_no_half_copy(mac):
    done = docker_install(mac, "--install-docker", UMCODEX_TEST_DITTO="interrupt")
    assert done.returncode == 130, done.stdout + done.stderr
    assert "Stopped. Run this installer again" in done.stdout
    assert not (mac["apps"] / ".Docker.app.umcodex-partial").exists()
    assert not (mac["apps"] / "Docker.app").exists()
    assert lines(mac["hdiutil"])[-1].startswith("hdiutil detach")
    again = docker_install(mac, "--install-docker")
    assert again.returncode == 0, again.stdout + again.stderr


def test_app_management_blocking_the_copy_says_how_to_allow_it(mac):
    done = docker_install(mac, "--install-docker", UMCODEX_TEST_DITTO="not-permitted")
    refused(done, mac, '"Operation not permitted"', "Privacy & Security > App Management")
    assert "Self Service" not in done.stdout
    assert not (mac["apps"] / ".Docker.app.umcodex-partial").exists()


def test_another_copy_failure_gets_the_general_message(mac):
    done = docker_install(mac, "--install-docker", UMCODEX_TEST_DITTO="fails")
    refused(done, mac, "couldn't be copied to", "Self Service app or ask IT")


def test_a_copy_that_differs_from_what_was_checked_is_removed(mac):
    done = docker_install(mac, "--install-docker", UMCODEX_TEST_DITTO="tamper")
    refused(done, mac, "didn't pass macOS's checks again")
    assert not (mac["apps"] / ".Docker.app.umcodex-partial").exists()
    assert list(cache(mac).iterdir()) == []


def test_a_docker_app_that_appears_while_copying_is_left_alone(mac):
    done = docker_install(mac, "--install-docker", UMCODEX_TEST_DITTO="race")
    assert done.returncode == 1, done.stdout + done.stderr
    assert "appeared in" in done.stdout and "that one was" in done.stdout
    theirs = mac["apps"] / "Docker.app"
    assert [p.name for p in theirs.iterdir()] == ["Contents"]  # not a copy inside it
    assert list((theirs / "Contents").iterdir()) == []
    assert not (mac["apps"] / ".Docker.app.umcodex-partial").exists()


def test_a_disk_image_not_signed_by_docker_isnt_opened(mac):
    done = docker_install(mac, "--install-docker", UMCODEX_TEST_DMG_SIGNER="Someone Else (ABCDE12345)")
    refused(done, mac, "isn't signed by Docker Inc", "deleted without being opened")
    assert lines(mac["hdiutil"]) == [] and list(cache(mac).iterdir()) == []


def test_gatekeeper_turned_off_is_said_so(mac):
    done = docker_install(mac, "--install-docker", UMCODEX_TEST_GATEKEEPER_OFF="1")
    refused(done, mac, "Gatekeeper is turned off", "Nothing from it was run")
    assert list(cache(mac).iterdir()) == []


def test_a_symlinked_app_in_the_disk_image_is_refused(mac, tmp_path):
    real = tmp_path / "elsewhere"
    real.mkdir()
    (mac["dmg"] / "Docker.app").rename(real / "Docker.app")
    (mac["dmg"] / "Docker.app").symlink_to(real / "Docker.app")
    done = docker_install(mac, "--install-docker")
    refused(done, mac, "didn't pass macOS's checks")


def test_docker_linked_from_path_to_an_app_elsewhere_is_used(mac, tmp_path):
    elsewhere = mac["apps"] / "Utilities"
    elsewhere.mkdir()
    renamed = fake_docker_app(elsewhere).rename(elsewhere / "Docker 4.84.app")
    (mac["tools"] / "docker").symlink_to(renamed / "Contents" / "Resources" / "bin" / "docker")
    done = docker_install(mac, UMCODEX_TEST_ALIVE=str(renamed))
    assert done.returncode == 0, done.stdout + done.stderr
    assert lines(mac["open"]) == [f"open {renamed}"]
    assert lines(mac["curl"]) == [] and not (mac["apps"] / "Docker.app").exists()
    assert "isn't on your PATH" not in done.stdout


def test_a_docker_app_spotlight_knows_is_used(mac, tmp_path):
    elsewhere = mac["home"] / "Applications" / "Other Apps"
    elsewhere.mkdir(parents=True)
    app = fake_docker_app(elsewhere)
    trash = mac["home"] / ".Trash"
    trash.mkdir()
    old = fake_docker_app(trash)
    done = docker_install(mac, UMCODEX_TEST_MDFIND=f"{old}\n{app}", UMCODEX_TEST_ALIVE=str(app))
    assert done.returncode == 0, done.stdout + done.stderr
    assert lines(mac["mdfind"]) == ["mdfind kMDItemCFBundleIdentifier == 'com.docker.docker'"]
    assert lines(mac["open"]) == [f"open {app}"]  # not the one in the Trash
    assert lines(mac["curl"]) == []
    assert f"UM-Codex finds it in {app / 'Contents' / 'Resources' / 'bin'}" in done.stdout


def test_an_empty_leftover_docker_app_is_explained(mac):
    (mac["apps"] / "Docker.app" / "Contents").mkdir(parents=True)
    done = docker_install(mac)
    assert done.returncode == 1, done.stdout + done.stderr
    assert "isn't a complete Docker Desktop" in done.stdout and "Drag it to the Trash" in done.stdout
    assert lines(mac["open"]) == [] and lines(mac["curl"]) == []


def test_after_installing_its_own_docker_command_is_used(mac):
    other = mac["tools"] / "docker"  # another Docker's command, not answering
    executable(other, "#!/bin/sh\nexit 1\n")
    done = docker_install(mac, "--install-docker")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "docker info" in lines(mac["docker"])  # the installed app's command answered
    bin_dir = mac["apps"] / "Docker.app" / "Contents" / "Resources" / "bin"
    assert all(line.split(":")[-1] == str(bin_dir) for line in lines(mac["path"]))


def test_the_wait_is_timed_by_the_clock(mac):
    fake_docker_app(mac["apps"])
    # Each `docker info` "takes" 50 seconds: the 60-second wait ends after two.
    slow = FAKE_DOCKER.replace(
        'if [ "$1" = info ]; then',
        'if [ "$1" = info ]; then\n  sleep 50',
    )
    executable(mac["apps"] / "Docker.app" / "Contents" / "Resources" / "bin" / "docker", slow)
    done = docker_install(mac, UMCODEX_TEST_OPEN_STARTS="0", UMCODEX_DOCKER_WAIT_SECONDS="60")
    assert done.returncode == 1 and "isn't answering after 60 seconds" in done.stdout
    assert len([x for x in lines(mac["docker"]) if x == "docker info"]) <= 3


def test_its_checks_use_dockers_code_requirement_and_notarization():
    text = INSTALLER.read_text(encoding="utf-8")
    assert 'certificate leaf[subject.OU] = \\"$DOCKER_TEAM_ID\\"' in text
    assert 'has_line "$assessed" "source=Notarized Developer ID"' in text
    assert "--speed-limit 10240 --speed-time 120" in text and "--tlsv1.2" in text


def staging_copy(mac) -> Path:
    """Docker's own half-done install or uninstall, with its programs running."""
    staging = mac["home"] / "Library" / "Application Support" / "com.docker.install"
    (staging / "in_progress").mkdir(parents=True)
    return fake_docker_app(staging / "in_progress")


def test_a_half_done_docker_install_isnt_taken_for_one(mac):
    app = staging_copy(mac)
    done = docker_install(mac, UMCODEX_TEST_MDFIND=str(app), UMCODEX_TEST_ALIVE=str(app))
    refused(done, mac, "Download and install Docker Desktop? [Y/n]")
    assert lines(mac["open"]) == []
    again = docker_install(mac, "--install-docker", UMCODEX_TEST_MDFIND=str(app))
    assert again.returncode == 0, again.stdout + again.stderr
    assert lines(mac["open"]) == [f"open {mac['apps'] / 'Docker.app'}"]


def test_a_docker_command_linked_into_a_half_done_install_isnt_followed(mac):
    app = staging_copy(mac)
    (mac["tools"] / "docker").symlink_to(app / "Contents" / "Resources" / "bin" / "docker")
    done = docker_install(mac)
    refused(done, mac, "isn't answering", "Download and install Docker Desktop? [Y/n]")
    assert lines(mac["open"]) == []


def test_spotlight_finding_only_leftovers_means_an_install_is_offered(mac, tmp_path):
    places = [
        mac["home"] / ".Trash",
        mac["home"] / "Library" / "Caches" / "x",
        tmp_path / "Volumes-like" / "Docker",  # not in an Applications folder
        mac["home"] / "Downloads",
    ]
    found = []
    for place in places:
        place.mkdir(parents=True)
        found.append(str(fake_docker_app(place)))
    done = docker_install(mac, UMCODEX_TEST_MDFIND="\n".join(found))
    refused(done, mac, "Download and install Docker Desktop? [Y/n]")
    assert lines(mac["open"]) == []


def test_leftover_docker_programs_are_mentioned_when_it_doesnt_start(mac):
    fake_docker_app(mac["apps"])
    done = docker_install(mac, UMCODEX_TEST_OPEN_STARTS="0", UMCODEX_DOCKER_WAIT_SECONDS="60")
    assert "programs\n    from it may still be running" in done.stdout
    assert "restart the Mac" in done.stdout


def test_no_variable_runs_into_a_non_ascii_character():
    # In a UTF-8 locale, sh reads "$place…" as a variable named place plus
    # the first byte of "…", which set -u stops on. ${place}… is safe.
    for script in (INSTALLER, UNINSTALLER):
        text = script.read_bytes()
        assert not re.search(rb"\$[A-Za-z_][A-Za-z0-9_]*[\x80-\xff]", text), script.name


def test_a_fresh_install_works_in_a_utf8_locale(mac):
    done = docker_install(mac, "--install-docker", LC_ALL="en_US.UTF-8", LANG="en_US.UTF-8")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "Copying Docker Desktop to" in done.stdout and "unbound variable" not in done.stderr


# Like Docker's engine hanging: `docker info` never returns, and (like a Go
# program) it ignores SIGALRM and SIGTERM. Only SIGKILL stops it.
HUNG_DOCKER = """#!/bin/sh
echo "docker $*" >> "$UMCODEX_TEST_DOCKERLOG"
trap '' ALRM TERM
[ "$1" = info ] && exec /bin/sleep 1017
exit 0
"""


@pytest.mark.parametrize("way", ["perl", "sh"])
def test_a_hung_docker_engine_is_given_up_on(mac, way):
    app = fake_docker_app(mac["apps"])
    executable(app / "Contents" / "Resources" / "bin" / "docker", HUNG_DOCKER)
    started = time.monotonic()
    done = docker_install(
        mac,
        UMCODEX_TEST_WITHIN=way,
        UMCODEX_DOCKER_INFO_SECONDS="1",
        UMCODEX_DOCKER_WAIT_SECONDS="10",
    )
    took = time.monotonic() - started
    assert done.returncode == 1, done.stdout + done.stderr
    assert "is open, but its engine isn't answering after 10 seconds" in done.stdout
    assert "whale menu at the top of the screen > Restart" in done.stdout
    assert "Troubleshoot > Restart" in done.stdout and "DELETE Docker's containers" in done.stdout
    # Each call was stopped after about 1 + 2 seconds, not left hanging.
    calls = [line for line in lines(mac["docker"]) if line == "docker info"]
    assert 2 <= len(calls) <= 5 and took < 40
    running = subprocess.run(["ps", "-A", "-o", "args="], capture_output=True, text=True).stdout
    assert "sleep 1017" not in running


def restarts(mac) -> list[str]:
    return [line for line in lines(mac["docker"]) if line == "docker desktop restart"]


def test_a_stuck_engine_is_restarted_once_and_then_answers(mac):
    fake_docker_app(mac["apps"])
    done = docker_install(mac, UMCODEX_TEST_ENGINE="stuck")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "engine isn't answering; restarting it" in done.stdout
    assert restarts(mac) == ["docker desktop restart"]
    assert "Docker Desktop is running." in done.stdout


def test_a_dead_engine_is_restarted_only_once(mac):
    fake_docker_app(mac["apps"])
    done = docker_install(mac, UMCODEX_TEST_ENGINE="dead")
    assert done.returncode == 1, done.stdout + done.stderr
    assert len(restarts(mac)) == 1
    assert "is open, but its engine isn't answering after 5 minutes" in done.stdout


def test_a_first_run_is_never_restarted(mac):
    done = docker_install(
        mac, "--install-docker", UMCODEX_TEST_ENGINE="dead", UMCODEX_DOCKER_WAIT_SECONDS="300"
    )
    assert done.returncode == 1, done.stdout + done.stderr
    assert restarts(mac) == [] and "restarting it" not in done.stdout
    assert "isn't ready after 5 minutes" in done.stdout  # its window may be waiting


def test_an_older_docker_without_its_restart_command_isnt_restarted(mac):
    fake_docker_app(mac["apps"])
    done = docker_install(mac, UMCODEX_TEST_ENGINE="dead", UMCODEX_TEST_NO_DESKTOP_COMMAND="1")
    assert done.returncode == 1, done.stdout + done.stderr
    assert restarts(mac) == [] and "restarting it" not in done.stdout


def test_no_printf_or_echo_is_piped_into_grep():
    # grep -q in a pipe exits early: "printf: write error: Broken pipe".
    text = INSTALLER.read_text(encoding="utf-8")
    assert not re.search(r"(printf|echo)[^\n|]*\|\s*grep", text)


ADMIN = {"UMCODEX_TEST_GROUPS": "staff everyone admin"}


def test_an_administrator_gets_dockers_own_installer(mac):
    done = docker_install(mac, "--install-docker", **ADMIN)
    assert done.returncode == 0, done.stdout + done.stderr
    [sudo, install] = lines(mac["sudo"])
    assert sudo.startswith("sudo ") and sudo.endswith("/Docker.app/Contents/MacOS/install --user tester")
    assert install == "install --user tester"  # no --accept-license
    assert "macOS asks for your password once" in done.stdout
    assert "macOS asks for your" in done.stdout and "to install Docker Desktop" in done.stdout
    app = mac["apps"] / "Docker.app"
    assert (app / "Contents" / "fake-signer").is_file()
    assert lines(mac["open"]) == [f"open {app}"]
    assert "It shows the Docker Subscription Service Agreement" in done.stdout
    assert not (mac["apps"] / ".Docker.app.umcodex-partial").exists()
    assert lines(mac["hdiutil"])[-1].startswith("hdiutil detach") and not cache(mac).exists()
    assert "6/6 Launcher" in done.stdout


def test_cancelling_the_password_stops_with_what_to_do(mac):
    done = docker_install(mac, "--install-docker", UMCODEX_TEST_SUDO_CANCEL="1", **ADMIN)
    refused(done, mac, "password wasn't given or accepted", "Nothing was changed.")
    assert "Copying Docker Desktop" not in done.stdout  # nothing else tried
    assert lines(mac["open"]) == []
    assert lines(mac["hdiutil"])[-1].startswith("hdiutil detach")
    # The download is kept, and checked again next time.
    again = docker_install(mac, "--install-docker", **ADMIN)
    assert again.returncode == 0, again.stdout + again.stderr
    assert "Using the Docker Desktop download from before." in again.stdout
    assert len(lines(mac["curl"])) == 1


def test_dockers_installer_failing_stops_with_what_to_do(mac):
    done = docker_install(mac, "--install-docker", UMCODEX_TEST_INSTALL_FAILS="1", **ADMIN)
    refused(done, mac, "installer stopped (code 3)")


def test_what_dockers_installer_put_in_applications_is_checked(mac):
    installer = mac["dmg"] / "Docker.app" / "Contents" / "MacOS" / "install"
    executable(
        installer,
        FAKE_DOCKER_INSTALL
        + 'echo "Other (ABCDE12345)" > '
        + '"$UMCODEX_SYSTEM_APPLICATIONS/Docker.app/Contents/fake-signer"\n',
    )
    done = docker_install(mac, "--install-docker", **ADMIN)
    assert done.returncode == 1, done.stdout + done.stderr
    assert "didn't pass macOS's checks" in done.stdout and lines(mac["open"]) == []


def test_a_non_administrator_gets_a_copy_without_sudo(mac):
    done = docker_install(mac, "--install-docker")
    assert done.returncode == 0, done.stdout + done.stderr
    assert lines(mac["sudo"]) == [] and "Copying Docker Desktop" in done.stdout


def test_without_dockers_install_command_an_administrator_gets_a_copy(mac):
    (mac["dmg"] / "Docker.app" / "Contents" / "MacOS" / "install").unlink()
    done = docker_install(mac, "--install-docker", **ADMIN)
    assert done.returncode == 0, done.stdout + done.stderr
    assert lines(mac["sudo"]) == [] and "Copying Docker Desktop" in done.stdout


def test_sudo_is_only_ever_dockers_installer_without_accepting_its_license():
    text = INSTALLER.read_text(encoding="utf-8")
    assert "accept-license" not in text and "sudo -S" not in text
    calls = [line.strip() for line in text.splitlines() if line.strip().startswith("sudo ")]
    assert calls == ['sudo "$installer_command" --user "$(id -un)" || status=$?']


def test_ctrl_c_at_the_optional_questions_after_done_just_ends(machine):
    # Ctrl-C (typed in the terminal: ETX) at "Show UM-Codex in Finder? [Y/n]",
    # once the install has finished, ends it quietly and successfully.
    done = install(machine, "0.1.0a3", answers=["", "\x03"])
    assert done.returncode == 0, done.stdout
    assert "UM-Codex is installed." in done.stdout and "Finder? [Y/n]" in done.stdout
    assert "OK." in done.stdout
    assert "Stopped. Run this installer again" not in done.stdout
    assert "Open UM-Codex now?" not in done.stdout
    assert (root(machine) / "current").read_text() == "0.1.0a3\n"


def test_at_a_terminal_it_offers_to_show_and_open_the_app(machine, tmp_path):
    opened = tmp_path / "opened"
    executable(machine["tools"] / "open", f'#!/bin/sh\necho "open $*" >> "{opened}"\n')
    done = install(machine, "0.1.0a3", answers=["", "", ""])
    assert done.returncode == 0, done.stdout
    app = machine["apps"] / "UM-Codex.app"
    assert opened.read_text().splitlines() == [f"open -R {app}", f"open {app}"]


def test_every_curl_ignores_curlrc_and_python_is_uvs_own():
    text = INSTALLER.read_text(encoding="utf-8")
    code = [line for line in text.splitlines() if not line.lstrip().startswith(("#", "echo"))]
    calls = [m for line in code for m in re.findall(r"(?<![\w-])curl (\S+)", line)]
    assert calls and all(first == "-q" for first in calls), calls
    assert "--python 3.13 --python-preference only-managed" in text
