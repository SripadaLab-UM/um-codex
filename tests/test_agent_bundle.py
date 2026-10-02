"""Offline helper boundaries; full execution is covered by image smoke."""

import importlib.util
import socket
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1] / "images/agent"


def load(filename):
    spec = importlib.util.spec_from_file_location(filename, ROOT / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_environment_helper_preserves_existing_project(tmp_path, monkeypatch):
    env = tmp_path / ".venv"
    env.mkdir()
    marker = env / "user-work"
    marker.write_text("keep")
    monkeypatch.setattr(sys, "argv", ["um-codex-env", str(env), "--image-packages"])
    with pytest.raises(SystemExit) as error:
        load("project-env.py").main()
    assert error.value.code == 2
    assert marker.read_text() == "keep"
    assert list(env.iterdir()) == [marker]


def test_environment_helper_preserves_dangling_symlink(tmp_path, monkeypatch):
    target = tmp_path / "old-container-env"
    env = tmp_path / ".venv"
    env.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(sys, "argv", ["um-codex-env", str(env)])
    with pytest.raises(SystemExit) as error:
        load("project-env.py").main()
    assert error.value.code == 2
    assert env.is_symlink() and not target.exists()


def test_dashboard_busy_port_leaves_existing_service_alone(tmp_path, monkeypatch):
    app = tmp_path / "app.py"
    app.write_text("raise RuntimeError('must not execute')")
    module = load("dashboard.py")
    with socket.socket() as service:
        service.bind(("127.0.0.1", 0))
        service.listen()
        port = service.getsockname()[1]
        monkeypatch.setitem(module.PORTS, "dash", port)
        monkeypatch.setattr(sys, "argv", ["um-codex-dashboard", "dash", str(app)])
        with pytest.raises(SystemExit) as error:
            module.main()
        assert error.value.code == 2
        assert service.getsockname()[1] == port


def test_skill_catalog_is_valid_and_references_exist():
    names = []
    for path in (ROOT / "skills").glob("*/SKILL.md"):
        _, frontmatter, body = path.read_text().split("---", 2)
        info = yaml.safe_load(frontmatter)
        assert info["name"] == path.parent.name
        assert info["description"] and len(body.strip()) > 100
        names.append(info["name"])
    assert len(names) == len(set(names)) == 8
    assert (ROOT / "skills/documents-and-reports/references/software.md").is_file()
