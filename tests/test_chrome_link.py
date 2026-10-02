"""Keeping the person's Chrome connection from UM-Codex's app copies (chrome_link.py)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from umcodex import chrome_link, codex_app
from umcodex import this_computer as tc

PERSONS = json.dumps(
    {"name": "com.openai.codexextension", "path": "/Users/me/.codex/plugins/cache/chrome/host"}
)


def ours(copy: Path) -> str:
    host = copy / "codex-home" / "plugins" / "cache" / "openai-bundled" / "chrome" / "latest" / "host"
    return json.dumps({"name": "com.openai.codexextension", "path": str(host)})


def test_where_the_app_writes_on_a_mac_and_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mac = chrome_link.manifests(tmp_path, "darwin")
    assert (
        mac[0]
        == tmp_path
        / "Library/Application Support/Google/Chrome/NativeMessagingHosts/com.openai.codexextension.json"
    )
    assert len(mac) == 4
    assert chrome_link.registry(tmp_path, "darwin") == (
        tmp_path / "Library/Application Support/OpenAI/Codex/chrome-native-hosts-v2.json"
    )
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert chrome_link.manifests(tmp_path, "win32") == [
        tmp_path / "Local/OpenAI/extension/com.openai.codexextension.json"
    ]
    assert (
        chrome_link.registry(tmp_path, "win32") == tmp_path / "Local/OpenAI/Codex/chrome-native-hosts-v2.json"
    )


def test_inside_ignores_case_and_separators() -> None:
    assert chrome_link.inside(
        "C:\\Users\\Me\\AppData\\UM-Codex\\codex-app\\x", Path("c:/users/me/appdata/um-codex")
    )
    assert not chrome_link.inside("/a/um-codex-other/x", Path("/a/um-codex"))


def test_the_sandbox_copys_config_keeps_chrome_off() -> None:
    import tomllib

    existing = (
        '[plugins."chrome@openai-bundled"]\nenabled = true\n'
        '[plugins."latex@openai-bundled"]\nenabled = true\n'
    )
    config = tomllib.loads(codex_app.local_config(existing, 1234, "m", setup_alias="umcodex-a"))
    assert config["plugins"]["chrome@openai-bundled"] == {"enabled": False}
    assert config["plugins"]["latex@openai-bundled"] == {"enabled": True}  # the app's own choice


def test_uninstall_puts_back_what_either_copy_took(tmp_path: Path) -> None:
    data, home = tmp_path / "data", tmp_path / "home"
    sandbox, local = codex_app.app_folder(data), tc.local_folder(data)
    manifest = chrome_link.manifests(home)[0]
    manifest.parent.mkdir(parents=True)
    manifest.write_text(PERSONS)
    chrome_link.remember(sandbox, home)
    manifest.write_text(ours(sandbox))  # the sandbox copy took it
    chrome_link.remember(local, home)  # then a local launch saw the sandbox copy's as "before"
    manifest.write_text(ours(local))
    chrome_link.restore_all([local, sandbox], data, home)
    assert manifest.read_text() == PERSONS  # the sandbox copy's backup put the person's back
    assert not (local / chrome_link.BACKUP).exists() and not (sandbox / chrome_link.BACKUP).exists()


def test_a_backup_of_ours_alone_means_remove(tmp_path: Path) -> None:
    data, home = tmp_path / "data", tmp_path / "home"
    sandbox, local = codex_app.app_folder(data), tc.local_folder(data)
    manifest = chrome_link.manifests(home)[0]
    manifest.parent.mkdir(parents=True)
    manifest.write_text(ours(sandbox))  # no backup of the person's survived
    chrome_link.remember(local, home)
    manifest.write_text(ours(local))
    lines = chrome_link.restore_all([local, sandbox], data, home)
    assert not manifest.exists() and lines


def test_while_the_copy_runs_the_backup_stays(tmp_path: Path) -> None:
    copy, home = tmp_path / "copy", tmp_path / "home"
    manifest = chrome_link.manifests(home)[0]
    manifest.parent.mkdir(parents=True)
    manifest.write_text(PERSONS)
    chrome_link.remember(copy, home)
    for _ in range(2):  # it rewrites it again later: still put back
        manifest.write_text(ours(copy))
        chrome_link.restore(copy, home, final=False)
        assert manifest.read_text() == PERSONS and (copy / chrome_link.BACKUP).exists()
    chrome_link.restore(copy, home)
    assert not (copy / chrome_link.BACKUP).exists()


def test_windows_registry_entries_of_the_copy_go(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    copy = tmp_path / "data" / "codex-app"
    registry = chrome_link.registry(tmp_path, "win32")
    registry.parent.mkdir(parents=True)
    theirs = {"paths": {"codexHome": "C:\\Users\\me\\.codex"}}
    mine = {"paths": {"codexHome": str(copy / "codex-home").upper()}}
    registry.write_text(json.dumps({"entries": [theirs, mine]}))
    chrome_link.restore(copy, tmp_path, platform="win32")
    assert json.loads(registry.read_text())["entries"] == [theirs]


def _app_run(manifest: Path, copy: Path, calls: list):
    def run(command, **options):
        calls.append(command)
        if command[0] == "ssh-keygen":
            key = Path(command[command.index("-f") + 1])
            key.write_text("private")
            key.with_name(key.name + ".pub").write_text("ssh-ed25519 AAAA test\n")
        if command[0] == "/usr/bin/open":
            manifest.write_text(ours(copy))  # the copy's Chrome plugin, at start
        if command[0] == "/bin/ps":
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, "ok", "")

    return run


def test_a_sandbox_launch_puts_the_persons_manifest_back(tmp_path: Path, data_folder: Path) -> None:
    from .test_codex_app import FakeDocker, _running

    home = Path(os.environ["HOME"])
    manifest = chrome_link.manifests(home)[0]
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(PERSONS)
    calls: list = []
    hold = codex_app.AppHold(
        "thesis-a1", say=lambda _: None, data=data_folder, app=Path("/Applications/ChatGPT.app"),
        docker=FakeDocker(running_for=3, connects_after=1),
        run=_app_run(manifest, codex_app.app_folder(data_folder), calls),
        sleep=lambda _: None, proxy_for=lambda s: ["/x/um-codex", "ssh-proxy", s], platform="darwin",
    )  # fmt: skip
    assert hold(_running(tmp_path, data_folder)) == 0
    assert any(c[0] == "/usr/bin/open" for c in calls)
    assert manifest.read_text() == PERSONS
    assert not (codex_app.app_folder(data_folder) / chrome_link.BACKUP).exists()


def test_a_local_launch_puts_it_back_while_the_copy_runs(tmp_path: Path) -> None:
    from .test_this_computer import FakeCopy, run_held

    home = Path(os.environ["HOME"])
    manifest = chrome_link.manifests(home)[0]
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(PERSONS)
    data = tmp_path / "data"
    seen: list[str] = []

    class WritingCopy(FakeCopy):
        def __call__(self, command, **kwargs):
            if command[0] == "/usr/bin/open":
                manifest.write_text(ours(tc.local_folder(self.data)))
            return super().__call__(command, **kwargs)

    copy = WritingCopy(data, lifetime=0.4)

    def watch(seconds: float) -> None:
        if copy.alive():
            seen.append(manifest.read_text())
        import time

        time.sleep(0.05)

    code, *_ = run_held(tmp_path, watch, copy=copy)
    assert code == 0 and PERSONS in seen[1:]  # put back while the copy still ran
    assert manifest.read_text() == PERSONS
