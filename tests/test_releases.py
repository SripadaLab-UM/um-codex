"""Which release `um-codex update` offers, and the checks before it trusts one (releases.py)."""

from __future__ import annotations

import pytest

from tests.fake_github import FakeGitHub, make_release
from umcodex import release_keys, signing
from umcodex.releases import (
    BAD_KEY,
    NOT_CONFIGURED,
    CheckProblem,
    ChecksumMismatch,
    NotConfigured,
    NotSigned,
    ReleaseSource,
    api_base,
    choose,
    find_update,
    parse_sums,
    pinned_keys,
    releases_from,
)


@pytest.fixture
def github():
    fake = FakeGitHub()
    yield fake
    fake.close()


@pytest.fixture
def key() -> tuple[str, str]:
    return signing.new_key()


def source(github: FakeGitHub) -> ReleaseSource:
    return ReleaseSource(api=github.api)


def test_the_newest_signed_release_newer_than_this_one_is_offered(github, key):
    private, public = key
    github.releases = [
        make_release("v0.1.0-alpha.2", "0.1.0a2", private),
        make_release("v0.1.0-alpha.4", "0.1.0a4", private),
        make_release("v0.1.0-alpha.3", "0.1.0a3", private),
    ]
    offer = find_update(source(github), "0.1.0a2", [public])
    assert offer is not None and offer.release.version == "0.1.0a4" and offer.release.tag == "v0.1.0-alpha.4"
    assert set(offer.expected) == {"umcodex-0.1.0a4-py3-none-any.whl", "requirements.txt", "images.json"}


def test_nothing_newer_means_no_offer(github, key):
    private, public = key
    github.releases = [make_release("v0.1.0-alpha.2", "0.1.0a2", private)]
    assert find_update(source(github), "0.1.0a2", [public]) is None
    # An older release is never offered, signed or not.
    assert find_update(source(github), "0.1.0a3", [public]) is None
    assert find_update(source(github), "0.1.0", [public]) is None


def test_pre_releases_are_offered_only_while_this_is_one(github, key):
    private, public = key
    beta = make_release("v0.2.0-beta.1", "0.2.0b1", private)
    beta.prerelease = True
    github.releases = [make_release("v0.1.0", "0.1.0", private), beta]
    assert find_update(source(github), "0.1.0a2", [public]).release.version == "0.2.0b1"  # type: ignore[union-attr]
    assert find_update(source(github), "0.1.0", [public]) is None
    # Not marked on GitHub, but its version is a pre-release: still one.
    github.releases[1].prerelease = False
    assert find_update(source(github), "0.1.0", [public]) is None


def test_drafts_and_releases_missing_files_are_skipped_for_the_next_newest(github, key):
    private, public = key
    draft = make_release("v0.1.0-alpha.9", "0.1.0a9", private)
    draft.draft = True
    incomplete = make_release("v0.1.0-alpha.8", "0.1.0a8", private)
    del incomplete.files["images.json"]
    no_digest = make_release("v0.1.0-alpha.7", "0.1.0a7", private)
    no_digest.no_digest = {"requirements.txt"}
    github.releases = [draft, incomplete, no_digest, make_release("v0.1.0-alpha.3", "0.1.0a3", private)]
    found, skipped = releases_from(source(github).list(), "SripadaLab-UM/um-codex", github.api)
    assert [r.version for r in found] == ["0.1.0a3"]
    assert any("doesn't have images.json" in why for why in skipped)
    assert any("no checksum for requirements.txt" in why for why in skipped)
    assert find_update(source(github), "0.1.0a2", [public]).release.version == "0.1.0a3"  # type: ignore[union-attr]


def test_a_package_for_another_version_than_the_tag_is_skipped(github, key):
    private, public = key
    github.releases = [make_release("v0.1.0-alpha.5", "0.1.0a5", private, wheel_version="0.1.0a4")]
    found, skipped = releases_from(source(github).list(), "SripadaLab-UM/um-codex", github.api)
    assert found == [] and "the UM-Codex 0.1.0a5 package" in skipped[0]
    assert find_update(source(github), "0.1.0a2", [public]) is None


def test_a_tag_that_isnt_a_version_is_skipped(github, key):
    private, _ = key
    github.releases = [make_release("latest", "0.1.0a5", private)]
    found, skipped = releases_from(source(github).list(), "SripadaLab-UM/um-codex", github.api)
    assert found == [] and "isn't a version" in skipped[0]


def test_a_release_signed_by_another_key_is_refused(github, key):
    _, public = key
    stranger, _ = signing.new_key()
    github.releases = [make_release("v0.1.0-alpha.3", "0.1.0a3", stranger)]
    with pytest.raises(NotSigned):
        find_update(source(github), "0.1.0a2", [public])


def test_a_release_with_a_bad_or_missing_signature_is_refused(github, key):
    private, public = key
    for signature in (b"", b"bm90IGEgc2lnbmF0dXJl\n", signing.sign(b"something else", private)):
        github.releases = [
            make_release("v0.1.0-alpha.3", "0.1.0a3", private, tamper={"SHA256SUMS.sig": signature})
        ]
        with pytest.raises(ChecksumMismatch):  # NotSigned, or a signature file of the wrong size
            find_update(source(github), "0.1.0a2", [public])
    release = make_release("v0.1.0-alpha.3", "0.1.0a3", private)
    del release.files["SHA256SUMS.sig"]
    github.releases = [release]
    assert find_update(source(github), "0.1.0a2", [public]) is None  # not a complete release


def test_sums_changed_after_signing_are_refused(github, key):
    private, public = key
    release = make_release("v0.1.0-alpha.3", "0.1.0a3", private)
    release.files["SHA256SUMS"] += b"\n"
    github.releases = [release]
    with pytest.raises(NotSigned):
        find_update(source(github), "0.1.0a2", [public])


def test_a_file_whose_github_checksum_disagrees_with_the_signed_sums_is_refused(github, key):
    private, public = key
    release = make_release("v0.1.0-alpha.3", "0.1.0a3", private)
    release.wrong_digest = {"images.json"}
    github.releases = [release]
    with pytest.raises(ChecksumMismatch, match="different checksums"):
        find_update(source(github), "0.1.0a2", [public])
    release.wrong_digest = {"SHA256SUMS"}
    with pytest.raises(ChecksumMismatch, match="GitHub's checksum"):
        find_update(source(github), "0.1.0a2", [public])


def test_sums_that_dont_list_a_needed_file_are_refused(github, key):
    private, public = key
    release = make_release("v0.1.0-alpha.3", "0.1.0a3", private)
    sums = b"".join(
        line + b"\n" for line in release.files["SHA256SUMS"].splitlines() if b"images.json" not in line
    )
    release.files["SHA256SUMS"] = sums
    release.files["SHA256SUMS.sig"] = signing.sign(sums, private)
    github.releases = [release]
    with pytest.raises(ChecksumMismatch, match="doesn't list images.json"):
        find_update(source(github), "0.1.0a2", [public])


def test_sums_are_read_strictly():
    good = "a" * 64
    assert parse_sums(f"{good}  x.whl\n{good} *y.txt\n\n") == {"x.whl": good, "y.txt": good}
    for bad in (f"{good}  ../x", f"{good}  a/b", "nope  x", f"{good}  x\n{'b' * 64}  x"):
        with pytest.raises(ChecksumMismatch):
            parse_sums(bad)


def test_offline_or_refused_listings_are_problems_not_crashes(github, key):
    _, public = key
    github.list_status = 404
    with pytest.raises(CheckProblem, match="didn't show"):
        find_update(source(github), "0.1.0a2", [public])
    github.list_status = 500
    with pytest.raises(CheckProblem, match="500"):
        find_update(source(github), "0.1.0a2", [public])
    github.close()
    with pytest.raises(CheckProblem, match="Couldn't reach GitHub"):
        find_update(source(github), "0.1.0a2", [public])


def test_downloads_only_go_to_githubs_own_hosts():
    real = ReleaseSource(api="https://api.github.com")
    assert real._allowed("https://release-assets.githubusercontent.com/x")
    assert not real._allowed("http://release-assets.githubusercontent.com/x")
    assert not real._allowed("https://example.org/x")


def test_no_pinned_key_means_updates_arent_set_up(monkeypatch):
    monkeypatch.setattr(release_keys, "RELEASE_KEYS", ())
    with pytest.raises(NotConfigured, match=NOT_CONFIGURED):
        pinned_keys()
    _, public = signing.new_key()
    with pytest.raises(NotConfigured, match="isn't a valid key"):
        pinned_keys([public, "typo"])
    assert BAD_KEY.startswith("Updates aren't set up")
    assert pinned_keys([public]) == (public,)


def test_the_api_override_is_for_this_computer_only(monkeypatch):
    monkeypatch.setenv("UMCODEX_RELEASES_API", "http://127.0.0.1:9/")
    assert api_base() == "http://127.0.0.1:9"
    for elsewhere in ("https://example.org", "http://10.0.0.1:80", "http://user@localhost"):
        monkeypatch.setenv("UMCODEX_RELEASES_API", elsewhere)
        with pytest.raises(CheckProblem):
            api_base()
    monkeypatch.delenv("UMCODEX_RELEASES_API")
    assert api_base() == "https://api.github.com"


def test_choose_compares_versions_not_text():
    from umcodex.releases import Asset, Release

    def release(version: str) -> Release:
        asset = Asset("x", "u", 1, "0" * 64)
        return Release(f"v{version}", version, False, asset, asset, asset, asset, asset)

    assert choose([release("0.10.0"), release("0.9.0")], "0.2.0").version == "0.10.0"  # type: ignore[union-attr]
    assert choose([release("1.0.0rc1"), release("1.0.0")], "1.0.0rc1").version == "1.0.0"  # type: ignore[union-attr]
