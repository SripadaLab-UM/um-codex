# Adapted from DataLab's backend/src/datalab/relay/__init__.py and relay/recovery.py at
# 6b6fdca: the data-session policy (relay/policy.py) and the status/turn callbacks are
# left out, and FastAPI is replaced by a small aiohttp server.
"""The model relay: every model request from a launch goes through here.

Codex in the agent container calls `http://gateway/v1/...` with the launch's
token as its API key. The gateway forwards to `/relay/v1/...` here, and the
relay:
1. checks the token (only this launch's is accepted);
2. swaps in the Toolkit key from the keychain;
3. streams the response straight back.

The relay runs inside the `um-codex` process, bound to 127.0.0.1 only, and
ends with the launch. The Toolkit key never leaves this process: it isn't
logged, and if the Toolkit ever echoed it in a response, it would be removed
before the response reached the container.

A failed request is retried here, within bounds, before any of the answer has
streamed (see "Recovery" below).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import secrets
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Literal
from urllib.parse import urlsplit

import httpx
from aiohttp import web

from umcodex.credentials import MissingCredential

log = logging.getLogger(__name__)
# httpcore's debug log prints response headers, which a careless server could
# fill with the key; httpx's prints request lines. Neither may log below WARNING,
# whatever the root logger's level.
for _noisy in ("httpcore", "httpx", "aiohttp.access"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

PREFIX = "/relay/v1/"
ALIVE = "_umcodex/alive"
REDACTED = b"[removed by UM-Codex]"

# Response headers passed back to Codex. Everything else (cookies, upstream
# infrastructure headers) stays here.
_PASS_BACK = (
    "content-type",
    "x-request-id",
    "openai-processing-ms",
    "openai-model",
    "retry-after",
    "retry-after-ms",
    "x-ratelimit-limit-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-requests",
    "x-ratelimit-reset-tokens",
)
# Request headers never forwarded upstream: the credential (replaced), and
# hop-by-hop or proxy headers.
_DROP = frozenset(
    {
        "authorization",
        "api-key",
        "x-api-key",
        "host",
        "content-length",
        "connection",
        "keep-alive",
        "transfer-encoding",
        "te",
        "upgrade",
        "accept-encoding",
        "cookie",
        "proxy-authorization",
        "proxy-connection",
        "x-real-ip",
        "forwarded",
    }
)
_SAFE_PATH = re.compile(r"[A-Za-z0-9_\-./]{1,200}")
_SAFE_QUERY = re.compile(r"[A-Za-z0-9_\-.=&%+,]{0,500}")


def new_token() -> str:
    """A launch's token: Codex's API key in the container."""
    return "umc_" + secrets.token_urlsafe(32)


def bearer_token(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


class Relay:
    def __init__(
        self,
        token: str,
        api_key: Callable[[], str],
        base_url: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = token
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client

    def app(self) -> web.Application:
        app = web.Application(client_max_size=64 * 1024 * 1024)
        app.router.add_route("*", "/{tail:.*}", self.handle)
        return app

    def token_ok(self, presented: str | None) -> bool:
        return presented is not None and secrets.compare_digest(presented.encode(), self._token.encode())

    async def handle(self, request: web.Request) -> web.StreamResponse:
        if not self.token_ok(bearer_token(request.headers.get("authorization"))):
            return _refused(401, "this launch's token is missing or wrong")
        if not request.path.startswith(PREFIX):
            return _refused(404, "only /v1/ is relayed")
        path = request.path[len(PREFIX) :]
        if path == ALIVE:
            # The agent's watchdog: the launch is still on. Never upstream.
            return web.Response(status=204)
        if (
            request.method not in ("GET", "POST")
            or not _SAFE_PATH.fullmatch(path)
            or any(part in ("", ".", "..") for part in path.split("/"))
            or not _SAFE_QUERY.fullmatch(request.query_string)
        ):
            return _refused(400, "that request can't be relayed")
        key = await asyncio.to_thread(_key_or_none, self._api_key)
        if key is None:
            return _refused(503, "no Toolkit API key is saved (run: um-codex key)")
        body = await request.read()
        url = f"{self._base_url}/{path}"
        if request.query_string:
            url += "?" + request.query_string
        headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP}
        headers["authorization"] = f"Bearer {key}"
        headers["accept-encoding"] = "identity"
        assert self._client is not None, "the relay's HTTP client isn't started"
        return await _forward(self._client, request, url, request.method, body, headers, key)


async def _forward(
    client: httpx.AsyncClient,
    request: web.Request,
    url: str,
    method: str,
    body: bytes,
    headers: dict[str, str],
    key: str,
) -> web.StreamResponse:
    """Send the request upstream and stream the answer back.

    A failure before any of the answer has streamed is retried here, within
    the bounds below, honouring the server's wait. The same bytes are sent
    each time. Nothing is sent again once Codex has stopped waiting.
    """
    scrub = Scrubber(key.encode())
    waited = 0.0
    attempt = 0
    while True:
        attempt += 1
        try:
            upstream = await client.send(
                client.build_request(method, url, content=body, headers=headers), stream=True
            )
        except httpx.HTTPError as error:
            trouble = connection_trouble(error)
            failure = _refused(502, f"couldn't reach the Toolkit ({type(error).__name__})")
        else:
            passed = _passed_headers(upstream.headers, key)
            if upstream.status_code < 400:
                if attempt > 1:
                    log.info("model request recovered on attempt %d", attempt)
                response = web.StreamResponse(status=upstream.status_code, headers=passed)
                try:
                    await response.prepare(request)
                    async for chunk in upstream.aiter_bytes():
                        if out := scrub.feed(chunk):
                            await response.write(out)
                    if out := scrub.flush():
                        await response.write(out)
                    await response.write_eof()
                except (ConnectionResetError, httpx.HTTPError) as error:
                    log.warning("model response stream ended early (%s)", type(error).__name__)
                finally:
                    await upstream.aclose()
                return response
            content = await _read_bounded(upstream, key)
            trouble = classify(upstream.status_code, upstream.headers, content, key=key)
            failure = web.Response(body=content, status=upstream.status_code, headers=passed)
        log.warning("model request failed (attempt %d): %s", attempt, trouble.record())
        delay = next_delay(trouble, attempt, waited)
        if delay is None:
            return failure
        if not await _wait_unless_gone(request, delay):
            return failure
        waited += delay


def _passed_headers(upstream: httpx.Headers, key: str) -> dict[str, str]:
    return {k: v for k, v in upstream.items() if k.lower() in _PASS_BACK and key not in v}


class Scrubber:
    """Removes a secret from a byte stream, even when it's split across chunks.

    Only the end of a chunk that could be the start of the secret is held
    back until the next chunk, so streaming isn't delayed otherwise.
    """

    def __init__(self, secret: bytes) -> None:
        self._secret = secret
        self._held = b""

    def feed(self, chunk: bytes) -> bytes:
        if not self._secret:
            return chunk
        buffer = (self._held + chunk).replace(self._secret, REDACTED)
        hold = 0
        for length in range(min(len(self._secret) - 1, len(buffer)), 0, -1):
            if buffer.endswith(self._secret[:length]):
                hold = length
                break
        self._held = buffer[len(buffer) - hold :] if hold else b""
        return buffer[: len(buffer) - hold]

    def flush(self) -> bytes:
        held, self._held = self._held, b""
        return held


async def _read_bounded(upstream: httpx.Response, key: str, limit: int = 65_536) -> bytes:
    """An error body, at most `limit` bytes, with the key removed before it's
    cut short (so a cut can't leave part of the key at the end)."""
    scrub = Scrubber(key.encode())
    content = b""
    complete = True
    try:
        async for chunk in upstream.aiter_bytes():
            content += scrub.feed(chunk)
            if len(content) >= limit:
                complete = False
                break
    finally:
        await upstream.aclose()
    if complete:
        content += scrub.flush()
    return content[:limit]


async def _wait_unless_gone(request: web.Request, seconds: float) -> bool:
    """Wait, checking every second that Codex is still waiting. False if it
    isn't: then nothing is sent again."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while (left := deadline - loop.time()) > 0:
        if _gone(request):
            return False
        await asyncio.sleep(min(1.0, left))
    return not _gone(request)


def _gone(request: web.Request) -> bool:
    transport = request.transport
    return transport is None or transport.is_closing()


def _key_or_none(api_key: Callable[[], str]) -> str | None:
    try:
        return api_key()
    except MissingCredential:
        return None


def _refused(status: int, reason: str) -> web.Response:
    return web.json_response(
        {"error": {"message": f"UM-Codex refused this request: {reason}.", "type": "umcodex_refused"}},
        status=status,
    )


class RelayServer:
    """Runs a Relay on 127.0.0.1, on a free port, in a background thread with
    its own event loop, so the launch's main thread can wait on `docker exec`."""

    def __init__(self, relay: Relay, *, host: str = "127.0.0.1") -> None:
        self.relay = relay
        self._host = host
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._runner: web.AppRunner | None = None
        self.port: int | None = None

    def start(self) -> int:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="umcodex-relay", daemon=True)
        self._thread.start()
        self.port = asyncio.run_coroutine_threadsafe(self._start(), self._loop).result(timeout=20)
        return self.port

    async def _start(self) -> int:
        self.relay._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=20, read=900, write=120, pool=20),
            follow_redirects=False,
        )
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind((self._host, 0))
        self._runner = web.AppRunner(self.relay.app(), access_log=None)
        await self._runner.setup()
        await web.SockSite(self._runner, sock).start()
        return sock.getsockname()[1]

    async def _stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
        if self.relay._client is not None:
            await self.relay._client.aclose()

    def stop(self) -> None:
        if self._loop is None or self._thread is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._stop(), self._loop).result(timeout=20)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=20)
            self._loop.close()
            self._loop = None
            self._thread = None


class UpstreamRefused(ValueError):
    pass


def upstream_base_url(default: str) -> str:
    """The Toolkit's base URL. `UMCODEX_UPSTREAM` replaces it, for tests only:
    a local stub on this computer (http://127.0.0.1, localhost or [::1]), never
    another host, so the variable can't send the key anywhere else. UM-Codex
    says so when it's set."""
    override = os.environ.get("UMCODEX_UPSTREAM")
    if not override:
        return default
    parsed = urlsplit(override)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1") or parsed.username:
        raise UpstreamRefused(
            "UMCODEX_UPSTREAM may only point at a test stub on this computer "
            "(http://127.0.0.1, http://localhost or http://[::1])."
        )
    return override


# ---------------------------------------------------------------------------
# Recovery (from DataLab's relay/recovery.py): what went wrong with a model
# request, and whether to try it again.
#
# The relay is the one place that retries a model request, and only before any
# of the response has reached Codex. Codex's own retries are kept to one
# (codex_config.py), so the attempts don't multiply. What is recorded about a
# failure is metadata (status, a provider code, a wait), never a body.
# ---------------------------------------------------------------------------

Kind = Literal["busy", "quota", "model_unavailable", "auth", "request", "connection"]

RETRYABLE: frozenset[Kind] = frozenset({"busy", "connection"})

# Bounds on retrying one request (tuning values, not measured service limits).
MAX_ATTEMPTS = 3
BUDGET_SECONDS = 60.0
MIN_DELAY = 1.0
FIRST_DELAY = 2.0
MAX_DELAY = 30.0

# Provider codes for a used-up allowance. Only the code decides, never the message.
_QUOTA_CODES = ("insufficient_quota", "quota_exceeded", "billing_hard_limit", "spend_limit")
_CODE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


@dataclass(frozen=True)
class Trouble:
    kind: Kind
    status: int | None
    code: str | None
    retry_after: float | None
    request_id: str | None

    def record(self) -> dict[str, object]:
        """The metadata that's kept: never a body or a header value other than the request ID."""
        return {
            "kind": self.kind,
            "status": self.status,
            "code": self.code,
            "retry_after": self.retry_after,
            "request_id": self.request_id,
        }


def classify(status: int, headers: httpx.Headers, body: bytes, *, key: str = "") -> Trouble:
    """What went wrong. A provider code or request ID that holds the key (or
    a piece of it) is dropped: they're logged."""
    code = _not_secret(_provider_code(body), key)
    lowered = (code or "").lower()
    wait = retry_after(headers)
    if status in (429, 403):
        # A server that says when to come back is busy, not out of allowance.
        if wait is None and any(word in lowered for word in _QUOTA_CODES):
            kind: Kind = "quota"
        else:
            kind = "busy" if status == 429 else "auth"
    elif status == 401:
        kind = "auth"
    elif status == 404:
        kind = "model_unavailable"
    elif status in (408, 409) or status >= 500:
        kind = "busy"
    else:
        kind = "request"
    request_id = _not_secret(headers.get("x-request-id"), key)
    return Trouble(
        kind=kind,
        status=status,
        code=code,
        retry_after=wait,
        request_id=request_id if request_id and _CODE.match(request_id) else None,
    )


def _not_secret(value: str | None, key: str) -> str | None:
    if value is None or not key:
        return value
    if key in value or (len(value) >= 8 and value in key):
        return None
    return value


def connection_trouble(error: httpx.HTTPError) -> Trouble:
    return Trouble("connection", None, type(error).__name__, None, None)


def retry_after(headers: httpx.Headers, now: datetime | None = None) -> float | None:
    """The server's wait, from `retry-after-ms` or `Retry-After` (seconds or an
    HTTP date). None when absent or unreadable."""
    if (ms := headers.get("retry-after-ms")) is not None:
        try:
            return max(0.0, float(ms) / 1000)
        except ValueError:
            pass
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - (now or datetime.now(UTC))).total_seconds())


def next_delay(trouble: Trouble, attempt: int, waited: float) -> float | None:
    """How long to wait before attempt `attempt + 1`, or None to stop.

    A server's wait is never shortened: if it doesn't fit in what's left of
    the budget, the relay stops rather than retrying early.
    """
    if trouble.kind not in RETRYABLE or attempt >= MAX_ATTEMPTS:
        return None
    if trouble.retry_after is not None:
        delay = trouble.retry_after
    else:
        delay = min(MAX_DELAY, FIRST_DELAY * 2 ** (attempt - 1))
        delay *= random.uniform(0.8, 1.2)  # jitter
    delay = max(MIN_DELAY, delay)
    return delay if waited + delay <= BUDGET_SECONDS else None


def _error_object(body: bytes) -> dict:
    try:
        parsed = json.loads(body[:16_384])
    except ValueError:
        return {}
    error = parsed.get("error") if isinstance(parsed, dict) else None
    return error if isinstance(error, dict) else {}


def _provider_code(body: bytes) -> str | None:
    error = _error_object(body)
    for key in ("code", "type"):
        value = error.get(key)
        if isinstance(value, str) and _CODE.match(value):
            return value
    return None
