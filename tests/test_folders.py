"""Folder rules: what a launch may share, resolved, and how ro/rw overlaps are handled."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from umcodex.folders import FolderRefused, check_folder, mount_name, parse_path_input, plan


@pytest.fixture
def home(tmp_path: Path) -> Path:
    folder = tmp_path / "home" / "person"
    for sub in (".ssh", ".aws", ".config/gh", ".codex", ".docker", "Library/Keychains", "thesis/data"):
        (folder / sub).mkdir(parents=True)
    return folder


def check(path, home, data=None, platform="darwin"):
    return check_folder(path, home=home, own_data=data or (home.parent / "data"), platform=platform)


def test_a_subfolder_of_home_is_fine(home):
    assert check(home / "thesis", home).path == Path(os.path.realpath(home / "thesis"))


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        (lambda h: "thesis", "isn't a full path"),
        (lambda h: str(h / "nope"), "doesn't exist"),
        (lambda h: str(h), "whole home folder"),
        (lambda h: str(h.parent), "holds your home folder"),
        (lambda h: "/", "whole drive"),
        (lambda h: str(h / ".ssh"), "SSH keys"),
        (lambda h: str(h / ".ssh"), ".ssh"),
        (lambda h: str(h / ".aws"), "AWS"),
        (lambda h: str(h / ".config" / "gh"), "GitHub"),
        (lambda h: str(h / ".config"), "holds"),
        (lambda h: str(h / ".codex"), "Codex"),
        (lambda h: str(h / ".docker"), "Docker"),
        (lambda h: str(h / "Library" / "Keychains"), "keychain"),
        (lambda h: str(h / "Library"), "holds"),
    ],
)
def test_refused(home, make, reason):
    with pytest.raises(FolderRefused, match=reason):
        check(make(home), home)


def test_a_file_is_refused(home):
    (home / "thesis" / "notes.txt").write_text("x")
    with pytest.raises(FolderRefused, match="file, not a folder"):
        check(home / "thesis" / "notes.txt", home)


def test_inside_a_protected_folder_is_refused_too(home):
    (home / ".ssh" / "inner").mkdir()
    with pytest.raises(FolderRefused, match="SSH"):
        check(home / ".ssh" / "inner", home)


def test_umcodex_own_data_folder_is_refused_inside_and_around(home, tmp_path):
    data = home / "thesis" / "umc-data"
    (data / "launches").mkdir(parents=True)
    for folder in (data, data / "launches", home / "thesis"):
        with pytest.raises(FolderRefused, match="UM-Codex's own data folder"):
            check(folder, home, data=data)


def test_links_are_resolved_so_they_cant_widen_whats_shared(home, tmp_path):
    link = home / "thesis" / "keys"
    link.symlink_to(home / ".ssh")
    with pytest.raises(FolderRefused, match="SSH"):
        check(link, home)
    to_home = tmp_path / "innocent"
    to_home.symlink_to(home)
    with pytest.raises(FolderRefused, match="whole home folder"):
        check(to_home, home)
    fine = tmp_path / "shortcut"
    fine.symlink_to(home / "thesis" / "data")
    assert check(fine, home).path == Path(os.path.realpath(home / "thesis" / "data"))


def test_docker_desktops_folders_on_windows(home, monkeypatch):
    local = home / "AppData" / "Local"
    (local / "Docker" / "wsl").mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    with pytest.raises(FolderRefused, match="Docker"):
        check(local / "Docker" / "wsl", home, platform="win32")


def test_dropped_paths_are_understood():
    assert parse_path_input("'/Users/a/My Thesis'") == "/Users/a/My Thesis"
    assert parse_path_input('"/Users/a/My Thesis" ') == "/Users/a/My Thesis"
    if os.name != "nt":
        assert parse_path_input(r"/Users/a/My\ Thesis") == "/Users/a/My Thesis"
    assert parse_path_input("~/x") == str(Path.home() / "x")


# --- overlaps ----------------------------------------------------------------


def test_the_same_folder_cant_be_read_only_and_writable(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    with pytest.raises(FolderRefused, match="both read-only and writable"):
        plan(a, [b], [b])
    with pytest.raises(FolderRefused, match="both read-only and writable"):
        plan(a, [], [a])
    with pytest.raises(FolderRefused, match="listed twice"):
        plan(a, [a], [])


def test_a_read_only_folder_inside_a_writable_one_is_noted(tmp_path):
    work = tmp_path / "work"
    layout = plan(work, [], [work / "raw"])
    assert layout.reads == ((work / "raw", "/mnt/read/raw"),)
    assert len(layout.notes) == 1
    assert "/work/raw" in layout.notes[0]


def test_mount_targets(tmp_path):
    layout = plan(
        tmp_path / "w",
        [tmp_path / "x" / "out", tmp_path / "y" / "out"],
        [tmp_path / "r" / "Data, 2026"],
    )
    assert [t for _, t in layout.writes] == ["/mnt/write/out", "/mnt/write/out-2"]
    assert [t for _, t in layout.reads] == ["/mnt/read/Data, 2026"]
    assert layout.notes == ()


def test_mount_names_are_clean():
    taken: set[str] = set()
    assert mount_name("..", taken) == "folder"
    assert mount_name("a‮b", taken) == "ab"
    assert mount_name("AB", taken) == "AB-2"  # case-insensitive clash with "ab"


@pytest.mark.parametrize(
    "sub",
    [".gnupg", ".kube", ".azure", ".config/gcloud", ".local/bin", ".local/share/uv", "Library/LaunchAgents"],
)
def test_more_protected_places(home, sub):
    (home / sub).mkdir(parents=True)
    with pytest.raises(FolderRefused):
        check(home / sub, home)


def test_umcodex_program_files_are_protected(home, tmp_path, monkeypatch):
    from umcodex import folders as module

    program = tmp_path / "elsewhere" / "UM-Codex" / "app"
    program.mkdir(parents=True)
    monkeypatch.setattr(module, "app_dir", lambda platform=None: program)
    with pytest.raises(FolderRefused, match="program files"):
        check(program, home)
    with pytest.raises(FolderRefused, match="program files"):
        check(program.parent, home)


def test_windows_startup_folder_is_protected(home, monkeypatch):
    roaming = home / "AppData" / "Roaming"
    startup = roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(roaming))
    with pytest.raises(FolderRefused, match="log in"):
        check(startup, home, platform="win32")


def test_the_same_folder_by_another_name_is_caught_by_its_identity(home, tmp_path, monkeypatch):
    """A Mac firmlink or a Windows \\\\localhost\\C$ path names the same folder
    differently; realpath doesn't unify them, the disk's identity does. A
    folder whose identity matches ~/.ssh is refused whatever its name."""
    from umcodex import folders as module

    other_name = tmp_path / "other-name"
    other_name.mkdir()
    real_ids = module._ids

    def ids(path):
        found = real_ids(path)
        if path == other_name or str(path) == str(other_name):
            return [real_ids(home / ".ssh")[0], *found[1:]]
        return found

    monkeypatch.setattr(module, "_ids", ids)
    with pytest.raises(FolderRefused, match="SSH"):
        check(other_name, home)


@pytest.mark.skipif(not Path("/System/Volumes/Data").is_dir(), reason="a Mac with a firmlinked data volume")
def test_a_mac_firmlink_to_home_is_refused():
    firmlinked = Path("/System/Volumes/Data") / Path.home().relative_to("/")
    with pytest.raises(FolderRefused, match="whole home folder"):
        check_folder(firmlinked)


@pytest.mark.skipif(not Path("/System/Volumes/Data").is_dir(), reason="a Mac with a separate data volume")
def test_the_data_volume_holding_home_under_another_name_is_refused():
    with pytest.raises(FolderRefused, match="holds your home folder|whole drive"):
        check_folder("/System/Volumes/Data")
