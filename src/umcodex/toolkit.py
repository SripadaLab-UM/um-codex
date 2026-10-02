"""U-M GPT Toolkit: the model list and the key check.

These run in the `um-codex` process on the host, with the key from the
keychain. Nothing here prints or logs the key, or any response body.
"""

from __future__ import annotations

import re
from typing import Literal

import httpx

from umcodex.relay import upstream_base_url

BASE_URL = "https://api.toolkit.umgpt.umich.edu/v1"
DEFAULT_MODEL = "gpt-5.6-terra"

KeyCheck = Literal["ok", "refused", "unreachable", "error"]

# OpenAI text models (what Codex's Responses wire speaks), shown in the model list.
_TEXT_MODEL = re.compile(r"(gpt-[0-9][a-z0-9.-]*|o[0-9][a-z0-9-]*)", re.ASCII)
_NOT_TEXT = ("image", "audio", "realtime", "tts", "transcribe", "embedding", "search")


def base_url() -> str:
    return upstream_base_url(BASE_URL)


def _get_models(key: str, timeout: float) -> httpx.Response:
    return httpx.get(
        f"{base_url().rstrip('/')}/models",
        headers={"authorization": f"Bearer {key}"},
        timeout=timeout,
    )


def check_key(key: str, timeout: float = 15) -> KeyCheck:
    """Whether the Toolkit accepts the key (by listing its models)."""
    try:
        response = _get_models(key, timeout)
    except httpx.HTTPError:
        return "unreachable"
    if response.status_code in (401, 403):
        return "refused"
    return "ok" if response.status_code < 400 else "error"


def list_models(key: str, timeout: float = 15) -> list[str]:
    """The Toolkit's Codex-capable models, newest first (by_release); [] if it can't say."""
    try:
        response = _get_models(key, timeout)
        listing = response.json() if response.status_code < 400 else {}
    except (httpx.HTTPError, ValueError):
        return []
    entries = listing.get("data") if isinstance(listing, dict) else None
    return by_release(
        {
            m["id"]
            for m in (entries if isinstance(entries, list) else [])
            if isinstance(m, dict) and isinstance(m.get("id"), str) and text_model(m["id"])
        }
    )


def text_model(model: str) -> bool:
    return bool(_TEXT_MODEL.fullmatch(model)) and not any(word in model for word in _NOT_TEXT)


# Within one version, the variants in the order Codex's own catalog gives them
# (`codex debug models --bundled`, 0.157.1: gpt-6-astra, gpt-6-sol,
# gpt-6-luna, gpt-5.6-sol, gpt-5.6-terra, gpt-5.6-luna, gpt-5.5), then the
# plain version, then any other variant (mini, nano, ...) by name.
VARIANTS = ("astra", "sol", "terra", "luna")
_RELEASE = re.compile(r"(gpt|o)-?([0-9]+(?:\.[0-9]+)*)-?(.*)", re.ASCII)


def release_key(model: str) -> tuple:
    """How a model sorts in the list: newest release first (by the version in
    its name: 6 before 5.6 before 5.5 before 5.4.1), GPT before the o-series,
    names without a version last."""
    found = _RELEASE.fullmatch(model)
    if found is None:
        return (2, (), 0, model)
    family, version, variant = found.group(1), found.group(2), found.group(3)
    # Each number descending; the 1 at the end puts 5.4.1 before 5.4.
    numbers = (*(-int(part) for part in version.split(".")), 1)
    if variant in VARIANTS:
        rank = VARIANTS.index(variant)
    elif not variant:
        rank = len(VARIANTS)
    else:
        rank = len(VARIANTS) + 1
    return (0 if family == "gpt" else 1, numbers, rank, model)


def by_release(models) -> list[str]:
    """The models, newest release first (release_key)."""
    return sorted(set(models), key=release_key)
