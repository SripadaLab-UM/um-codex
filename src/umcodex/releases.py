# Adapted from IHS DataLab's backend/src/datalab/releases.py at 6b6fdca: the
# rules for which release is offered and how its files are checked are
# DataLab's; its settings, channels and hourly check are left out.
"""Checking GitHub for a newer UM-Codex release.

`um-codex update` (and, at most once a day, a launch) asks the GitHub Releases
API of SripadaLab-UM/um-codex for its releases, without signing in: the repo
is public. Nothing else makes this call, and never a container.

Which release is offered (DataLab's rules):

- never a draft, and only a release whose tag is a PEP 440 version newer than
  the installed one (`v0.1.0-alpha.3` is 0.1.0a3);
- pre-releases while the installed UM-Codex is itself a pre-release (as
  DataLab's "auto" channel); full releases only after that. A release counts
  as a pre-release if GitHub marks it so or its version is one;
- only a release that carries everything an update needs: the package for
  exactly that version (`umcodex-<version>-py3-none-any.whl`),
  `requirements.txt`, `images.json`, `SHA256SUMS` and `SHA256SUMS.sig`.
  GitHub must give its own checksum (`digest`) of every one of them. Anything
  else is skipped, and the newest of the rest is offered;
- its `SHA256SUMS` must be signed by a key pinned in this package
  (release_keys.py), and list the other three files with the checksums
  GitHub gives. A newest release that fails this is refused, not passed over;
- nothing at all while this UM-Codex pins no release key: updates aren't set
  up, and GitHub isn't asked.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from packaging.version import InvalidVersion, Version

from umcodex import release_keys, signing

REPOSITORY = "SripadaLab-UM/um-codex"
API = "https://api.github.com"
# For tests only: a stand-in for GitHub's API on this computer.
API_ENV = "UMCODEX_RELEASES_API"
SUMS = "SHA256SUMS"
REQUIREMENTS = "requirements.txt"
IMAGES = "images.json"
SIGNATURE = signing.SIGNATURE
MAX_SUMS_BYTES = 64 * 1024
MAX_SIGNATURE_BYTES = 1024
# Where GitHub serves release files from, after the API redirects there.
DOWNLOAD_HOSTS = frozenset(
    {"objects.githubusercontent.com", "release-assets.githubusercontent.com", "github.com"}
)
TIMEOUT = httpx.Timeout(connect=10, read=30, write=10, pool=10)
_HEADERS = {"accept": "application/vnd.github+json", "x-github-api-version": "2022-11-28"}
_WHEEL = re.compile(r"umcodex-([A-Za-z0-9.+!]+)-py3-none-any\.whl")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")

NOT_CONFIGURED = (
    "Updates aren't set up in this UM-Codex: it pins no release signing key to check new versions "
    "with, so it never installs one. Install new versions with the installer."
)
BAD_KEY = (
    "Updates aren't set up in this UM-Codex: a release signing key it pins isn't a valid key "
    "(release_keys.py), so it never installs one. Tell the UM-Codex maintainer."
)


class CheckProblem(RuntimeError):
    """The check couldn't finish (offline, rate-limited, GitHub answered oddly)."""


class ChecksumMismatch(RuntimeError):
    """A release's files don't match its SHA256SUMS (or GitHub's own checksums)."""


class NotSigned(ChecksumMismatch):
    """A release's SHA256SUMS has no valid signature from a pinned key."""


class NotConfigured(RuntimeError):
    """This UM-Codex pins no (valid) release key: it never offers an update."""


def parse_version(text: str) -> Version | None:
    """A tag or package version as PEP 440 sees it ("v0.1.0-alpha.2" is 0.1.0a2)."""
    try:
        return Version(text.strip())
    except InvalidVersion:
        return None


def is_newer(candidate: str, current: str) -> bool:
    new, old = parse_version(candidate), parse_version(current)
    return new is not None and old is not None and new > old


def pinned_keys(keys: Sequence[str] | None = None) -> tuple[str, ...]:
    """The keys a release must be signed with. A key that isn't one (a typo when
    pasting it in) makes this trust nothing, rather than the others quietly."""
    pinned = tuple(release_keys.trusted_keys() if keys is None else keys)
    if not pinned:
        raise NotConfigured(NOT_CONFIGURED)
    if any(not signing.valid_public(key) for key in pinned):
        raise NotConfigured(BAD_KEY)
    return pinned


@dataclass(frozen=True)
class Asset:
    name: str
    # The API's address for the file (`.../releases/assets/<id>`).
    url: str
    size: int
    # GitHub's own SHA-256 of the file (its `digest`). Required.
    sha256: str


@dataclass(frozen=True)
class Release:
    tag: str
    version: str  # normalised PEP 440
    prerelease: bool
    wheel: Asset
    requirements: Asset
    images: Asset
    sums: Asset
    signature: Asset

    @property
    def files(self) -> tuple[Asset, ...]:
        """What an update downloads, besides SHA256SUMS and its signature."""
        return (self.wheel, self.requirements, self.images)


@dataclass(frozen=True)
class Offer:
    """A newer release that passed the check, and the checksum each of its files must have."""

    release: Release
    expected: dict[str, str]


def releases_from(raw: Any, repository: str, api: str = API) -> tuple[list[Release], list[str]]:
    """The releases GitHub listed that an update could install, and why each other was skipped."""
    found: list[Release] = []
    skipped: list[str] = []
    if not isinstance(raw, list):
        raise CheckProblem("GitHub's list of releases couldn't be read.")
    for item in raw:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        tag = str(item.get("tag_name") or "")
        release, why = _release(item, tag, repository, api)
        if release is None:
            skipped.append(f"{tag or '(no tag)'}: {why}")
        else:
            found.append(release)
    return found, skipped


def choose(releases: list[Release], current: str) -> Release | None:
    """The newest release newer than `current`; pre-releases only while `current` is one."""
    installed = parse_version(current)
    pre = installed is not None and installed.is_prerelease
    offered = [r for r in releases if is_newer(r.version, current) and (pre or not r.prerelease)]
    return max(offered, key=lambda r: Version(r.version), default=None)


def parse_sums(text: str) -> dict[str, str]:
    """SHA256SUMS as `sha256sum` writes it: `<hex>  <name>` (or `<hex> *<name>`).

    Only plain file names are accepted, and a name listed twice with two
    checksums makes the whole file unusable."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](.+)", line)
        if match is None:
            raise ChecksumMismatch(f"SHA256SUMS has a line that isn't a checksum: {line[:80]!r}")
        digest, name = match.group(1).lower(), match.group(2)
        if not _plain_name(name):
            raise ChecksumMismatch(f"SHA256SUMS names something that isn't a plain file: {name!r}")
        if sums.get(name, digest) != digest:
            raise ChecksumMismatch(f"SHA256SUMS lists {name} twice, with different checksums.")
        sums[name] = digest
    return sums


def check_listing(release: Release, sums: dict[str, str]) -> dict[str, str]:
    """Every file an update downloads, with the checksum it must have: SHA256SUMS's,
    which GitHub's own must match."""
    expected: dict[str, str] = {}
    for asset in release.files:
        listed = sums.get(asset.name)
        if listed is None:
            raise ChecksumMismatch(f"SHA256SUMS for {release.tag} doesn't list {asset.name}.")
        if asset.sha256 != listed:
            raise ChecksumMismatch(
                f"{asset.name} in {release.tag}: SHA256SUMS and GitHub have different checksums."
            )
        expected[asset.name] = listed
    return expected


def find_update(source: ReleaseSource, current: str, keys: Sequence[str]) -> Offer | None:
    """The newest release to install over `current`, checked, or None if there's none.

    Raises CheckProblem when GitHub can't be asked, NotSigned or
    ChecksumMismatch when the newest release doesn't pass."""
    releases, _skipped = releases_from(source.list(), source.repository, source.api)
    release = choose(releases, current)
    if release is None:
        return None
    raw_sums = source.read_small(release.sums, MAX_SUMS_BYTES)
    signature = source.read_small(release.signature, MAX_SIGNATURE_BYTES)
    if not signing.verify(raw_sums, signature, keys):
        raise NotSigned(f"{release.tag}'s SHA256SUMS isn't signed by the release key")
    sums = parse_sums(raw_sums.decode("utf-8", "replace"))
    return Offer(release, check_listing(release, sums))


# ------------------------------------------------------------------ GitHub


def api_base() -> str:
    """GitHub's API, or `UMCODEX_RELEASES_API` for tests: a stand-in on this
    computer only (http://127.0.0.1, localhost or [::1])."""
    override = os.environ.get(API_ENV)
    if not override:
        return API
    parsed = urlsplit(override)
    if parsed.scheme != "http" or parsed.hostname not in _LOCAL_HOSTS or parsed.username:
        raise CheckProblem(f"{API_ENV} may only point at a test stand-in on this computer.")
    return override.rstrip("/")


class ReleaseSource:
    """The repo's releases on GitHub, read without signing in."""

    def __init__(
        self,
        repository: str = REPOSITORY,
        *,
        api: str | None = None,
        http: httpx.Client | None = None,
        timeout: httpx.Timeout = TIMEOUT,
    ) -> None:
        self.repository = repository
        self.api = api or api_base()
        self._http = http or httpx.Client(timeout=timeout)

    def list(self) -> list[Any]:
        try:
            response = self._http.get(
                f"{self.api}/repos/{self.repository}/releases",
                params={"per_page": "30"},
                headers=_HEADERS,
            )
        except httpx.HTTPError:
            raise CheckProblem("Couldn't reach GitHub (no internet connection?).") from None
        _raise_for(response)
        try:
            return response.json()
        except ValueError:
            raise CheckProblem("GitHub's list of releases couldn't be read.") from None

    def read_small(self, asset: Asset, limit: int) -> bytes:
        """A small release file (SHA256SUMS, its signature), whole, checked
        against GitHub's checksum."""
        if asset.size > limit or asset.size == 0:
            raise ChecksumMismatch(f"{asset.name} isn't the size a checksum file should be.")
        chunks = bytearray()
        with self._download(asset) as response:
            for chunk in response.iter_bytes():
                chunks.extend(chunk)
                if len(chunks) > asset.size:
                    raise ChecksumMismatch(f"{asset.name} is larger than GitHub said.")
        data = bytes(chunks)
        if hashlib.sha256(data).hexdigest() != asset.sha256:
            raise ChecksumMismatch(f"{asset.name} doesn't match GitHub's checksum for it.")
        return data

    def download(self, asset: Asset, target: Path, *, sha256: str) -> None:
        """Save a release file to `target`, refusing it unless it has `sha256`.

        It's written beside `target` first and moved into place only once
        whole and checked, so `target` is never a partial or wrong file."""
        partial = target.with_name(f".{target.name}.partial")
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        try:
            with self._download(asset) as response, partial.open("wb") as out:
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > asset.size:
                        raise ChecksumMismatch(f"{asset.name} is larger than GitHub said.")
                    digest.update(chunk)
                    out.write(chunk)
            if digest.hexdigest() != sha256:
                raise ChecksumMismatch(f"{asset.name} doesn't match its checksum in SHA256SUMS.")
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)

    def _allowed(self, url: str) -> bool:
        """Where a download may go: GitHub's own hosts over https, or the test
        stand-in's own address."""
        target = urlsplit(url)
        if self.api == API:
            return target.scheme == "https" and target.hostname in DOWNLOAD_HOSTS
        here = urlsplit(self.api)
        return (target.scheme, target.hostname, target.port) == (here.scheme, here.hostname, here.port)

    @contextlib.contextmanager
    def _download(self, asset: Asset) -> Iterator[httpx.Response]:
        if not asset.url.startswith(f"{self.api}/repos/{self.repository}/releases/assets/"):
            raise ChecksumMismatch(f"{asset.name} isn't a file of {self.repository}'s releases.")
        url = asset.url
        # Redirects are followed by hand, and only to GitHub's own hosts, over
        # https: GitHub sends release files from its storage.
        for _ in range(5):
            try:
                request = self._http.build_request("GET", url, headers={"accept": "application/octet-stream"})
                response = self._http.send(request, stream=True, follow_redirects=False)
            except httpx.HTTPError:
                raise CheckProblem("Couldn't reach GitHub (no internet connection?).") from None
            if response.is_redirect:
                location = response.headers.get("location", "")
                response.close()
                url = str(httpx.URL(url).join(location))
                if not self._allowed(url):
                    raise CheckProblem("GitHub sent the download somewhere unexpected.")
                continue
            try:
                _raise_for(response)
                yield response
            finally:
                response.close()
            return
        raise CheckProblem("GitHub redirected the download too many times.")


def _raise_for(response: httpx.Response) -> None:
    status = response.status_code
    if status == 200:
        return
    if status == 429 or (status == 403 and response.headers.get("x-ratelimit-remaining") == "0"):
        raise CheckProblem("GitHub asked UM-Codex to wait before checking again; try again later.")
    if status == 404:
        raise CheckProblem("GitHub didn't show UM-Codex's releases.")
    raise CheckProblem(f"GitHub answered {status}.")


# ------------------------------------------------------------------ helpers


def _release(item: dict[str, Any], tag: str, repository: str, api: str) -> tuple[Release | None, str]:
    version = parse_version(tag)
    if version is None:
        return None, "the tag isn't a version"
    assets: dict[str, Asset] = {}
    unchecked: set[str] = set()
    wheels: list[str] = []
    for raw in item.get("assets") or []:
        listed = _asset(raw, repository, api)
        if listed is None:
            continue
        name, asset = listed
        if asset is None:
            unchecked.add(name)
        else:
            assets[name] = asset
        match = _WHEEL.fullmatch(name)
        if match and parse_version(match.group(1)) == version:
            wheels.append(name)
    needed = [*wheels, REQUIREMENTS, IMAGES, SUMS, SIGNATURE]
    missing = [n for n in needed[len(wheels) :] if n not in assets and n not in unchecked]
    if len(wheels) != 1:
        missing.insert(0, f"the UM-Codex {version} package")
    if missing:
        return None, f"it doesn't have {', '.join(missing)}"
    # GitHub's own checksum of every file used is required, never optional.
    without = sorted(n for n in needed if n in unchecked)
    if without:
        return None, f"GitHub gives no checksum for {', '.join(without)}"
    return (
        Release(
            tag=tag,
            version=str(version),
            prerelease=bool(item.get("prerelease")) or version.is_prerelease,
            wheel=assets[wheels[0]],
            requirements=assets[REQUIREMENTS],
            images=assets[IMAGES],
            sums=assets[SUMS],
            signature=assets[SIGNATURE],
        ),
        "",
    )


def _asset(raw: Any, repository: str, api: str) -> tuple[str, Asset | None] | None:
    """A listed file of this repo's release: its name, and the Asset if GitHub
    gave its checksum (None if it didn't)."""
    if not isinstance(raw, dict):
        return None
    name, url = raw.get("name"), raw.get("url")
    if not isinstance(name, str) or not isinstance(url, str) or not _plain_name(name):
        return None
    if not url.startswith(f"{api}/repos/{repository}/releases/assets/"):
        return None
    digest = raw.get("digest")
    value = digest.removeprefix("sha256:").lower() if isinstance(digest, str) else ""
    if not (isinstance(digest, str) and digest.startswith("sha256:") and _SHA256.fullmatch(value)):
        return name, None
    size = raw.get("size")
    return name, Asset(name, url, size if isinstance(size, int) and size >= 0 else 0, value)


def _plain_name(name: str) -> bool:
    return bool(name) and name not in (".", "..") and not any(c in name for c in "/\\\0") and len(name) <= 200
