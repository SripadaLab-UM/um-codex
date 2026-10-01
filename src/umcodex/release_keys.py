# Adapted from IHS DataLab's backend/src/datalab/release_keys.py at 6b6fdca.
"""The public keys a release must be signed with (signing.py).

Each installed UM-Codex trusts only the keys listed here, in its own package.
With none listed it trusts no release: `um-codex update` says updates aren't
set up and never asks GitHub, and the release workflow refuses to publish
(its `version` job, and scripts/sign-release.py, which also refuses a key
that isn't listed here). docs/RELEASING.md has the steps.

To change keys, a release signed with the current key lists both the current
and the next key; the release after that can be signed with the next one.
"""

from __future__ import annotations

# TODO(maintainer): before the first release, make the release key on your
# own computer (`uv run python scripts/sign-release.py --new-key`), put its
# private half in the "release" environment's RELEASE_SIGNING_KEY secret, and
# paste its public half here, as a string, with the date it was made.
RELEASE_KEYS: tuple[str, ...] = ()


def trusted_keys() -> tuple[str, ...]:
    """The pinned keys (empty strings left out)."""
    return tuple(key.strip() for key in RELEASE_KEYS if key.strip())
