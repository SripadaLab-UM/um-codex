# Adapted from DataLab's backend/src/datalab/credentials.py at 6b6fdca.
"""The Toolkit key lives in the OS keychain (macOS Keychain, Windows
Credential Manager), under the service "UM-Codex".

Only the relay (relay.py) and the Toolkit checks (toolkit.py) read it, in the
`um-codex` process on the host. Unlike DataLab there is no environment
variable override: the key is never in an environment variable.
"""

from __future__ import annotations

import contextlib

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

KEY_SERVICE = "UM-Codex"
KEY_ACCOUNT = "toolkit-api-key"


class MissingCredential(RuntimeError):
    pass


def _from_keychain() -> str | None:
    # A computer with no usable keychain (e.g. a CI runner) has no saved key.
    try:
        return keyring.get_password(KEY_SERVICE, KEY_ACCOUNT)
    except KeyringError:
        return None


def api_key() -> str:
    """The Toolkit key. It never leaves the host process."""
    key = _from_keychain()
    if not key:
        raise MissingCredential("No Toolkit API key is saved. Run: um-codex key")
    return key


def has_api_key() -> bool:
    return bool(_from_keychain())


def save_api_key(key: str) -> None:
    keyring.set_password(KEY_SERVICE, KEY_ACCOUNT, key)


def delete_api_key() -> None:
    with contextlib.suppress(PasswordDeleteError, KeyringError):
        keyring.delete_password(KEY_SERVICE, KEY_ACCOUNT)
