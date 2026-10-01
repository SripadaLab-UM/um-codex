"""Whether the release being published becomes GitHub's "latest" release.

    python scripts/release-latest.py <tag> <owner/repo>

prints the flags for `gh release create`: `--latest`, `--latest=false`, or
`--latest=false --prerelease`.

GitHub's releases/latest never points at a pre-release, and the install
commands download from releases/latest/download. So until a full release
exists, every release (alphas included) is published as a normal release;
`um-codex update` tells pre-releases by their version anyway. A release
becomes the latest only when its version is newer (PEP 440,
`packaging.version.Version`) than every published release's tag, so a run
approved late (an older tag after a newer one) or a fix on an older line
never takes "latest" from a newer version. Once a full release exists, a
pre-release version is never the latest and is marked a GitHub pre-release,
so new installs keep getting the newest full release. Drafts and tags that
aren't versions don't count.

It asks `gh release list` (GH_TOKEN from the environment), and stops with
exit 1 if that fails or the tag isn't a version.
"""

from __future__ import annotations

import json
import subprocess
import sys

from packaging.version import InvalidVersion, Version


def version(tag: str) -> Version | None:
    try:
        return Version(tag)
    except InvalidVersion:
        return None


def decide(tag: str, published: list[str]) -> str:
    this = version(tag)
    if this is None:
        raise ValueError(f"{tag} isn't a version")
    others = [v for t in published if t != tag and (v := version(t)) is not None]
    if this.is_prerelease and any(not other.is_prerelease for other in others):
        return "--latest=false --prerelease"
    return "--latest" if all(this > other for other in others) else "--latest=false"


def published_tags(repository: str) -> list[str]:
    listed = subprocess.run(
        [
            "gh", "release", "list", "--repo", repository, "--exclude-drafts",
            "--limit", "1000", "--json", "tagName",
        ],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return [str(item["tagName"]) for item in json.loads(listed.stdout)]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    tag, repository = argv
    try:
        print(decide(tag, published_tags(repository)))
    except (ValueError, KeyError, TypeError, subprocess.CalledProcessError, OSError) as error:
        print(f"Couldn't decide whether {tag} is the latest release: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
