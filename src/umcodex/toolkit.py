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
    """The Toolkit's Codex-capable models, the default first; [] if it can't say."""
    try:
        response = _get_models(key, timeout)
        listing = response.json() if response.status_code < 400 else {}
    except (httpx.HTTPError, ValueError):
        return []
    entries = listing.get("data") if isinstance(listing, dict) else None
    ids = sorted(
        {
            m["id"]
            for m in (entries if isinstance(entries, list) else [])
            if isinstance(m, dict) and isinstance(m.get("id"), str) and text_model(m["id"])
        }
    )
    if DEFAULT_MODEL in ids:
        ids.remove(DEFAULT_MODEL)
        ids.insert(0, DEFAULT_MODEL)
    return ids


def text_model(model: str) -> bool:
    return bool(_TEXT_MODEL.fullmatch(model)) and not any(word in model for word in _NOT_TEXT)
