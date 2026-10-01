"""Release signatures (signing.py) and scripts/sign-release.py, with throwaway keys only."""

from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path

import pytest

from umcodex import release_keys, signing

ROOT = Path(__file__).resolve().parents[1]
SUMS = b"0" * 64 + b"  umcodex-0.1.0a2-py3-none-any.whl\n"


def load_script():
    spec = importlib.util.spec_from_file_location("sign_release", ROOT / "scripts" / "sign-release.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_signature_verifies_with_its_own_public_key_only():
    private, public = signing.new_key()
    _, other = signing.new_key()
    signature = signing.sign(SUMS, private)
    assert signature.endswith(b"\n") and len(base64.b64decode(signature.strip())) == 64
    assert signing.verify(SUMS, signature, [public])
    assert signing.verify(SUMS, signature, [other, public])  # any pinned key will do
    assert not signing.verify(SUMS, signature, [other])
    assert not signing.verify(SUMS, signature, [])
    assert signing.public_of(private) == public


def test_a_changed_sums_file_or_signature_doesnt_verify():
    private, public = signing.new_key()
    signature = signing.sign(SUMS, private)
    assert not signing.verify(SUMS.replace(b"0", b"1", 1), signature, [public])
    assert not signing.verify(SUMS + b"\n", signature, [public])
    raw = bytearray(base64.b64decode(signature))
    raw[0] ^= 1
    assert not signing.verify(SUMS, base64.b64encode(bytes(raw)), [public])
    for junk in (b"", b"not base64!", b"\xff\xfe", base64.b64encode(b"short")):
        assert not signing.verify(SUMS, junk, [public])


def test_a_signature_of_the_same_bytes_without_umcodexs_context_doesnt_verify():
    """Only a release signature passes: not a bare Ed25519 signature of the
    file, nor DataLab's (another context)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private, public = signing.new_key()
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private))
    for message in (SUMS, b"DataLab release SHA256SUMS, v1\n" + SUMS):
        assert not signing.verify(SUMS, base64.b64encode(key.sign(message)), [public])


def test_keys_that_arent_keys_are_refused():
    _, public = signing.new_key()
    assert signing.valid_public(public)
    for bad in ("", "x", base64.b64encode(b"1" * 31).decode(), public[:-4] + "!!!!"):
        assert not signing.valid_public(bad)
    with pytest.raises(signing.BadKey):
        signing.sign(SUMS, "not a key")
    signature = signing.sign(SUMS, signing.new_key()[0])
    assert not signing.verify(SUMS, signature, ["not a key"])


def test_the_package_ships_with_no_key_pinned_until_the_maintainer_adds_one():
    """Until the maintainer pins the release key (docs/RELEASING.md), no key is
    trusted. Once one is pinned, every pinned key must be a valid one."""
    assert all(signing.valid_public(key) for key in release_keys.trusted_keys())


# ------------------------------------------------------------------ sign-release.py


def test_new_key_prints_a_pair_that_signs_and_verifies(capsys):
    script = load_script()
    assert script.main(["--new-key"]) == 0
    out = capsys.readouterr().out.splitlines()
    private, public = out[1].strip(), out[3].strip()
    assert "RELEASE_SIGNING_KEY" in out[0] and "release_keys.py" in out[2]
    assert signing.public_of(private) == public
    assert signing.verify(SUMS, signing.sign(SUMS, private), [public])


def test_it_signs_with_a_pinned_key(tmp_path, monkeypatch, capsys):
    script = load_script()
    private, public = signing.new_key()
    monkeypatch.setattr(release_keys, "RELEASE_KEYS", (public,))
    monkeypatch.setenv("RELEASE_SIGNING_KEY", private)
    sums = tmp_path / "SHA256SUMS"
    sums.write_bytes(SUMS)
    assert script.main([str(sums)]) == 0
    assert signing.verify(SUMS, (tmp_path / "SHA256SUMS.sig").read_bytes(), [public])
    assert private not in capsys.readouterr().out


def test_it_refuses_a_key_the_package_doesnt_pin(tmp_path, monkeypatch, capsys):
    script = load_script()
    private, _ = signing.new_key()
    _, other = signing.new_key()
    sums = tmp_path / "SHA256SUMS"
    sums.write_bytes(SUMS)
    monkeypatch.setenv("RELEASE_SIGNING_KEY", private)
    for pinned in ((), (other,)):
        monkeypatch.setattr(release_keys, "RELEASE_KEYS", pinned)
        assert script.main([str(sums)]) == 1
        assert "doesn't pin this signing key" in capsys.readouterr().err
    assert not (tmp_path / "SHA256SUMS.sig").exists()


def test_it_refuses_without_a_key_or_with_a_bad_one(tmp_path, monkeypatch, capsys):
    script = load_script()
    sums = tmp_path / "SHA256SUMS"
    sums.write_bytes(SUMS)
    monkeypatch.delenv("RELEASE_SIGNING_KEY", raising=False)
    assert script.main([str(sums)]) == 1
    assert "isn't set" in capsys.readouterr().err
    monkeypatch.setenv("RELEASE_SIGNING_KEY", "nope")
    assert script.main([str(sums)]) == 1
    assert "isn't an Ed25519 key" in capsys.readouterr().err
    assert not (tmp_path / "SHA256SUMS.sig").exists()


def test_check_pinned_fails_with_no_key_or_a_bad_one(monkeypatch, capsys):
    script = load_script()
    monkeypatch.setattr(release_keys, "RELEASE_KEYS", ())
    assert script.main(["--check-pinned"]) == 1
    assert "pins no release key" in capsys.readouterr().err
    _, public = signing.new_key()
    monkeypatch.setattr(release_keys, "RELEASE_KEYS", (public, "typo"))
    assert script.main(["--check-pinned"]) == 1
    monkeypatch.setattr(release_keys, "RELEASE_KEYS", (public,))
    assert script.main(["--check-pinned"]) == 0


def test_the_script_runs_as_the_release_workflow_runs_it(tmp_path):
    """PYTHONPATH=src python scripts/sign-release.py: refuses with no key set."""
    import os
    import subprocess

    sums = tmp_path / "SHA256SUMS"
    sums.write_bytes(SUMS)
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sign-release.py"), str(sums)],
        env={
            **{k: v for k, v in os.environ.items() if k != "RELEASE_SIGNING_KEY"},
            "PYTHONPATH": str(ROOT / "src"),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 1 and "RELEASE_SIGNING_KEY isn't set" in done.stderr
