# MemoryKeychain and docker_app adapted from DataLab's backend/tests/conftest.py at 6b6fdca.
from __future__ import annotations

import os
from pathlib import Path

import pytest

# Processes the tests start (none should) get keyring's null backend: nothing
# saved, nothing found. The tests themselves use MemoryKeychain below.
os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"

FAKE_KEY = "sk-fake-toolkit-key-0123456789abcdef"


class MemoryKeychain:
    """Stands in for the OS keychain."""

    def __init__(self) -> None:
        self.saved: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.saved.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.saved[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        from keyring.errors import PasswordDeleteError

        if self.saved.pop((service, account), None) is None:
            raise PasswordDeleteError("not saved")


@pytest.fixture(autouse=True)
def memory_keychain(monkeypatch: pytest.MonkeyPatch) -> MemoryKeychain:
    """No test reads or writes this computer's keychain."""
    import keyring

    fake = MemoryKeychain()
    for name in ("get_password", "set_password", "delete_password"):
        monkeypatch.setattr(keyring, name, getattr(fake, name))

    def no_backend(*_: object, **__: object) -> None:
        raise AssertionError("A test reached the real keychain's backend.")

    monkeypatch.setattr(keyring, "get_keyring", no_backend)
    return fake


@pytest.fixture(autouse=True)
def data_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Every test gets its own UM-Codex data folder, and no stub upstream."""
    folder = tmp_path / "umcodex-data"
    monkeypatch.setenv("UMCODEX_DATA_DIR", str(folder))
    monkeypatch.delenv("UMCODEX_UPSTREAM", raising=False)
    monkeypatch.delenv("UMCODEX_AGENT_IMAGE", raising=False)
    # No test asks GitHub for releases (tests/test_update.py turns this off for its own).
    monkeypatch.setenv("UMCODEX_NO_UPDATE_CHECK", "1")
    monkeypatch.delenv("UMCODEX_RELEASES_API", raising=False)
    monkeypatch.delenv("UMCODEX_INSTALL_DIR", raising=False)
    return folder


@pytest.fixture(autouse=True)
def launcher_places(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """No test reaches the real /Applications, ~/Applications, Start menu or
    Desktop, or registers an app with macOS (launchers.py): stand-ins for each,
    and a home folder of its own."""
    for name in ("UMCODEX_SYSTEM_APPLICATIONS", "UMCODEX_START_MENU", "UMCODEX_DESKTOP"):
        monkeypatch.setenv(name, str(tmp_path_factory.mktemp(name.lower())))
    monkeypatch.setenv("UMCODEX_LSREGISTER", "")
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))


@pytest.fixture
def docker_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Docker Desktop's program on Windows, where UM-Codex opens it from
    (windows_vm.py): a stand-in file, so no test opens the real one."""
    from umcodex import windows_vm

    program = tmp_path / "Docker Desktop.exe"
    program.write_bytes(b"")
    monkeypatch.setattr(windows_vm, "docker_desktop", lambda: program)
    return program


@pytest.fixture(autouse=True)
def ssh_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory, data_folder: Path
) -> Path:
    """No test reads or writes this computer's ~/.ssh: codex_app's home is a
    folder of the test's own (outside tmp_path, which some tests list). The
    test's data folder stands for the installed copy's (plain host aliases,
    `umcodex-<setup>`); tests of other data folders pass theirs."""
    from umcodex import codex_app

    home = tmp_path_factory.mktemp("ssh-home")
    monkeypatch.setattr(codex_app, "user_home", lambda: home)
    monkeypatch.setattr(codex_app, "plain_alias_folder", lambda: data_folder)
    return home
