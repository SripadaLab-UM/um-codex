# Adapted from IHS DataLab's scripts/sign-release.py at 6b6fdca.
"""Sign a release's SHA256SUMS, or make the release key (once).

uv run python scripts/sign-release.py --new-key
    Prints a new key pair, on the maintainer's own computer. The private key
    goes into the "release" GitHub environment as the secret
    RELEASE_SIGNING_KEY, and nowhere else; the public key goes into
    src/umcodex/release_keys.py. See docs/RELEASING.md.

uv run python scripts/sign-release.py --check-pinned
    Exit 0 if release_keys.py pins at least one key, and every key it pins is
    a valid one. The release workflow runs this before it builds anything.

RELEASE_SIGNING_KEY=... uv run python scripts/sign-release.py assets/SHA256SUMS
    The release workflow: writes assets/SHA256SUMS.sig. It refuses unless
    the package being released pins this key's public key, so the next
    release, signed with the same key, is accepted by this one.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from umcodex import release_keys, signing


def check_pinned() -> int:
    keys = release_keys.trusted_keys()
    if not keys:
        print(
            "src/umcodex/release_keys.py pins no release key, so no installed UM-Codex could check "
            "this release. Pin the public key first (docs/RELEASING.md).",
            file=sys.stderr,
        )
        return 1
    bad = [key for key in keys if not signing.valid_public(key)]
    if bad:
        print(
            f"src/umcodex/release_keys.py pins {len(bad)} key(s) that aren't Ed25519 public keys "
            "(paste the public key exactly as --new-key printed it).",
            file=sys.stderr,
        )
        return 1
    print(f"{len(keys)} release key(s) pinned.")
    return 0


def main(argv: list[str]) -> int:
    if argv == ["--new-key"]:
        private, public = signing.new_key()
        print("Private key (the RELEASE_SIGNING_KEY secret; never commit it or paste it elsewhere):")
        print(f"  {private}")
        print("Public key (paste into RELEASE_KEYS in src/umcodex/release_keys.py):")
        print(f"  {public}")
        return 0
    if argv == ["--check-pinned"]:
        return check_pinned()
    if len(argv) != 1 or argv[0].startswith("-"):
        print(__doc__, file=sys.stderr)
        return 2
    private = os.environ.get("RELEASE_SIGNING_KEY", "").strip()
    if not private:
        print(
            "RELEASE_SIGNING_KEY isn't set: releases must be signed (docs/RELEASING.md).",
            file=sys.stderr,
        )
        return 1
    try:
        public = signing.public_of(private)
    except signing.BadKey as error:
        print(f"RELEASE_SIGNING_KEY isn't an Ed25519 key in base64 ({error}).", file=sys.stderr)
        return 1
    if public not in release_keys.trusted_keys():
        print(
            "The package doesn't pin this signing key's public key (src/umcodex/release_keys.py), "
            "so UM-Codex would refuse the next release signed with it. Add the public key first.",
            file=sys.stderr,
        )
        return 1
    sums = Path(argv[0])
    data = sums.read_bytes()
    signature = signing.sign(data, private)
    if not signing.verify(data, signature, [public]):
        print("The signature didn't verify.", file=sys.stderr)
        return 1
    sums.with_name(signing.SIGNATURE).write_bytes(signature)
    print(f"Signed {sums.name} ({signing.SIGNATURE}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
