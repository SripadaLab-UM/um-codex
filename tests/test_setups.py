"""Saved setups, and the launch's questions driven by scripted answers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from umcodex.folders import plan
from umcodex.setups import Setup, SetupStore, choose, manage, new_id, summary


class Script:
    """Answers questions in order, and records them."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.asked: list[str] = []
        self.said: list[str] = []

    def ask(self, question: str) -> str:
        self.asked.append(question)
        if not self.answers:
            raise AssertionError(f"unexpected question: {question!r}")
        return self.answers.pop(0)

    def say(self, text: str) -> None:
        self.said.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self.said)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    folder = tmp_path / "projects" / "thesis"
    (folder / "raw").mkdir(parents=True)
    (tmp_path / "projects" / "outputs").mkdir()
    return Path(os.path.realpath(folder))


def make(project: Path, **changes) -> Setup:
    return Setup(id=new_id("thesis"), name="thesis", working=str(project), **changes)


def test_save_load_and_last_used_first(project):
    store = SetupStore()
    a = make(project)
    b = Setup(id=new_id("other"), name="other", working=str(project), internet=True, approvals="on-request")
    store.save(a)
    store.save(b, used=True)
    assert [s.id for s in store.all()] == [b.id, a.id]
    assert store.last_used() == b
    store.mark_used(a.id)
    assert store.all()[0] == a
    store.delete(a.id)
    assert store.all() == [b]
    assert store.last_used() is None
    reloaded = SetupStore().get(b.id)
    assert reloaded == b and reloaded.internet and reloaded.approvals == "on-request"


def test_store_lives_in_the_data_folder(data_folder):
    store = SetupStore()
    assert store.path == data_folder / "setups.toml"


def test_ids_are_docker_safe():
    setup_id = new_id("My Thesis (2026)!")
    assert setup_id.startswith("my-thesis-2026-")
    assert all(c.isalnum() or c == "-" for c in setup_id)


def test_a_new_setup_from_scratch(project):
    script = Script(
        "",  # working folder: the default (the folder um-codex was started in)
        "",  # name: the folder's
        str(project.parent / "outputs"),  # a folder to write
        "",  # done
        str(project / "raw"),  # a read-only folder
        "",  # done
        "y",  # internet on
        "",  # model: default
        "",  # approvals: default (never)
        "",  # Start? yes
    )
    chosen = choose(
        SetupStore(), script.ask, script.say, start_folder=project, models=lambda: ["gpt-5.6-terra"]
    )
    assert chosen is not None
    setup, layout = chosen
    assert setup.name == "thesis" and setup.working == str(project)
    assert setup.writes == (str(project.parent / "outputs"),)
    assert setup.reads == (str(project / "raw"),)
    assert setup.internet and setup.model == "gpt-5.6-terra" and setup.approvals == "never"
    assert layout.reads == ((project / "raw", "/mnt/read/raw"),)
    assert "DELETE" in script.text and "Internet: ON" in script.text
    assert "could send anything" in script.text
    assert "can still change it at /work/raw" in script.text
    assert SetupStore().last_used() == setup


def test_refused_folders_are_explained_and_asked_again(project, tmp_path):
    script = Script(
        str(Path.home()),  # refused: the whole home folder
        str(project),
        "",  # name
        "",  # no write folders
        str(project),  # a read-only folder that's also the working folder: refused at the check
        "",  # done
        "",  # internet: default off
        "",  # model
        "2",  # ask before commands
        "y",  # "This setup can't be used as it is ... Change it now?"
        "",  # working folder (kept)
        "",  # name (kept)
        "",  # write folders: none, so straight to the list: done
        "n",  # keep the read-only folders? no
        "",  # done
        "",  # internet (kept: off)
        "",  # model (kept)
        "",  # approvals (kept: 2)
        "",  # Start
    )
    chosen = choose(SetupStore(), script.ask, script.say, start_folder=tmp_path)
    assert "whole home folder can't be shared" in script.text
    assert "both read-only and writable" in script.text
    assert chosen is not None
    setup, _ = chosen
    assert setup.reads == () and setup.approvals == "on-request" and not setup.internet


def test_the_last_setup_is_offered_again(project):
    store = SetupStore()
    setup = make(project)
    store.save(setup, used=True)
    script = Script("", "")  # use it again; Start
    chosen = choose(store, script.ask, script.say, start_folder=project)
    assert chosen is not None and chosen[0] == setup
    assert script.asked[0].startswith("Use “thesis” again")


def test_saying_no_starts_nothing(project):
    store = SetupStore()
    store.save(make(project), used=True)
    script = Script("", "n", "")  # use again; Start? no; save anyway? (default no)
    assert choose(store, script.ask, script.say, start_folder=project) is None


def test_a_setup_whose_folder_went_is_offered_for_change(project, tmp_path):
    store = SetupStore()
    gone = tmp_path / "gone"
    store.save(Setup(id="gone-1", name="gone", working=str(gone)), used=True)
    script = Script("", "n")  # use again; Change it now? no
    assert choose(store, script.ask, script.say, start_folder=project) is None
    assert "doesn't exist" in script.text


def test_summary_without_internet(project):
    setup = make(project)
    text = "\n".join(summary(setup, plan(project, [], [])))
    assert "Internet: off" in text and "runs commands without asking" in text
    assert "never sees it" in text


def test_manage_deletes_and_removes_the_volume(project):
    store = SetupStore()
    setup = make(project)
    store.save(setup)
    removed = []
    script = Script("1", "d", "y", "")
    manage(store, script.ask, script.say, remove_volume=removed.append)
    assert store.all() == [] and removed == [setup]


def test_a_saved_folder_that_now_leads_elsewhere_needs_an_explicit_yes(project, tmp_path):
    store = SetupStore()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    moved_link = project.parent / "outputs-link"
    moved_link.symlink_to(elsewhere)
    # As if saved before a link was put in its place.
    setup = make(project, writes=(str(moved_link),))
    store.save(setup, used=True)
    script = Script("", "y")  # use it again; a plain "y" isn't enough, so it goes on to change the setup...
    script.answers += ["", "", "n", "", "", "", "", "", "n", "n"]  # ...where the person stops
    assert choose(store, script.ask, script.say, start_folder=project) is None
    assert "WARNING: a saved folder now leads somewhere else" in script.text
    assert f"now goes to {os.path.realpath(elsewhere)}" in script.text

    script = Script("", "yes", "")  # an explicit yes, then Start
    chosen = choose(store, script.ask, script.say, start_folder=project)
    assert chosen is not None
    assert chosen[0].writes == (os.path.realpath(elsewhere),)  # what was approved is saved


# --- Opened from the app (`um-codex launch --from-app`) ---------------------

NEW_SETUP_REST = ("", "", "", "", "", "", "")  # name, writes, reads, internet, model, approvals, Start


def test_from_the_app_a_new_setup_offers_documents_um_codex_and_makes_it(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    script = Script("", *NEW_SETUP_REST)  # Enter at the working folder
    chosen = choose(SetupStore(), script.ask, script.say, start_folder=None)
    assert chosen is not None
    folder = home / "Documents" / "UM-Codex"
    assert folder.is_dir()
    assert chosen[0].working == os.path.realpath(folder) and chosen[0].name == "UM-Codex"
    assert script.asked[0] == "Drag a folder here, or press Enter for ~/Documents/UM-Codex: "


def test_from_the_app_the_documents_folder_isnt_made_unless_chosen(tmp_path, monkeypatch, project):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    script = Script(str(project), *NEW_SETUP_REST)
    chosen = choose(SetupStore(), script.ask, script.say, start_folder=None)
    assert chosen is not None and chosen[0].working == str(project)
    assert not (home / "Documents" / "UM-Codex").exists()


def test_from_the_app_a_new_setup_offers_the_last_setups_folder(project, tmp_path):
    store = SetupStore()
    store.save(make(project), used=True)
    other = tmp_path / "elsewhere"
    other.mkdir()
    script = Script(
        "n",  # Use "thesis" again? no
        "n",  # a new setup
        "",  # working folder: the last setup's
        "fresh",  # name
        *NEW_SETUP_REST[1:],
    )
    chosen = choose(store, script.ask, script.say, start_folder=None)
    assert chosen is not None and chosen[0].working == str(project) and chosen[0].name == "fresh"
    assert f"press Enter for {project}: " in script.asked[2]


def test_the_current_folder_is_offered_from_a_terminal(project):
    script = Script("", *NEW_SETUP_REST)
    chosen = choose(SetupStore(), script.ask, script.say, start_folder=project)
    assert chosen is not None and chosen[0].working == str(project)
    assert script.asked[0] == f"Drag a folder here, or press Enter for {project}: "


def test_enter_with_no_folder_to_offer_says_what_to_do(project):
    # Started in the home folder, which can't be shared: nothing is offered.
    script = Script("", str(project), *NEW_SETUP_REST)
    chosen = choose(SetupStore(), script.ask, script.say, start_folder=Path.home())
    assert chosen is not None and chosen[0].working == str(project)
    assert script.asked[0] == "Drag a folder here, or type its path: "
    assert "Drag a folder from Finder or File Explorer into this window" in script.text
