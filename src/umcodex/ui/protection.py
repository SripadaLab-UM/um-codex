# Adapted from DataLab's backend/src/datalab/web.py (BrowserSession,
# refuse_cross_site, ApiProtection, the security headers) at 6b6fdca, for aiohttp.
"""What keeps other programs and web pages out of the launcher window's API.

- The server listens on 127.0.0.1 only, on a port chosen when it starts.
- The page is opened with a one-time sign-in link; the token in it is
  exchanged for a cookie (HttpOnly, SameSite=Strict, named for the port), and
  every /api request needs that cookie.
- The Host header must be this server's own (127.0.0.1 or localhost, this
  port): a page on another name that resolves here (DNS rebinding) is refused.
- Every request that changes something must be JSON, from this very origin
  (refuse_cross_site).
- No CORS headers, ever: another page can't read an answer. Every response
  carries DataLab's Content Security Policy and other security headers.
"""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Mapping

from aiohttp import web

CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "X-DNS-Prefetch-Control": "off",
    "Cache-Control": "no-store",
}

# Methods that change nothing: the only ones a request from another page may make.
SAFE_METHODS = frozenset({"GET", "HEAD"})


class BrowserSession:
    """The one-time sign-in link and the cookie it sets."""

    def __init__(self, port: int) -> None:
        self.port = port
        self._sign_in_token: str | None = secrets.token_urlsafe(24)
        self._cookie = secrets.token_urlsafe(32)
        # Named for the port: browsers share cookies between ports of one host.
        self.cookie_name = f"umcodex_session_{port}"

    def sign_in_path(self) -> str:
        assert self._sign_in_token is not None
        return f"/sign-in?token={self._sign_in_token}"

    def new_sign_in_path(self) -> str:
        """A new one-time link (a second `um-codex ui` opens the page again).
        Any earlier unused link stops working."""
        self._sign_in_token = secrets.token_urlsafe(24)
        return self.sign_in_path()

    def redeem(self, token: str) -> str | None:
        """Exchange the sign-in token for the cookie value. Works once."""
        if self._sign_in_token and hmac.compare_digest(token.encode(), self._sign_in_token.encode()):
            self._sign_in_token = None
            return self._cookie
        return None

    def valid(self, cookie: str | None) -> bool:
        return bool(cookie) and hmac.compare_digest((cookie or "").encode(), self._cookie.encode())


def own_hosts(port: int) -> frozenset[str]:
    return frozenset({f"127.0.0.1:{port}", f"localhost:{port}"})


def refuse_host(headers: Mapping[str, str], port: int) -> str | None:
    """Why the request isn't for this server by its own name, or None."""
    if headers.get("Host", "").lower() not in own_hosts(port):
        return "Refused: this isn't UM-Codex's own address."
    return None


def refuse_cross_site(headers: Mapping[str, str], method: str) -> str | None:
    """Why a request that changes something isn't this page's own, or None.

    Browsers count every port of 127.0.0.1 as one site, so another local web
    page gets the SameSite=Strict cookie sent with its requests. A form or a
    no-cors fetch from there can only send a "simple" request: no JSON content
    type, and no way to hide where it's from. So every request but GET and
    HEAD must:
    - come from this origin (Sec-Fetch-Site same-origin; absent in older
      browsers and in tests),
    - if it says where it's from (Origin), be this very scheme, host and port,
    - be JSON (`content-type: application/json`), which only a same-origin
      page's fetch can send without the browser asking first (a CORS
      preflight, which is never allowed here)."""
    if method in SAFE_METHODS:
        return None
    site = headers.get("Sec-Fetch-Site")
    if site is not None and site != "same-origin":
        return f"Refused a request from another site ({site})."
    origin = headers.get("Origin")
    if origin is not None and origin.lower() != f"http://{headers.get('Host', '').lower()}":
        return "Refused a request from another origin."
    content_type = headers.get("Content-Type", "").split(";")[0].strip().lower()
    if content_type != "application/json":
        return "UM-Codex's API takes JSON requests only."
    return None


def refused(why: str, status: int) -> web.Response:
    return web.json_response({"error": why}, status=status)


def protection(session: BrowserSession, *, control_secret: str, seen: list[float] | None = None):
    """The middleware: Host, then (for anything that changes something) the
    cross-site rules, then the cookie for /api and the control secret for
    /_control. `seen` gets the time of each signed-in API request (for the
    idle shutdown)."""
    import time

    @web.middleware
    async def middleware(request: web.Request, handler) -> web.StreamResponse:
        if why := refuse_host(request.headers, session.port):
            return refused(why, 421)
        path = request.path
        if why := refuse_cross_site(request.headers, request.method):
            return refused(why, 403)
        if path.startswith("/api/"):
            if not session.valid(request.cookies.get(session.cookie_name)):
                return refused("Open UM-Codex from its app (or run um-codex ui) to sign in.", 401)
            if seen is not None:
                seen.append(time.monotonic())
                del seen[:-1]
        elif path.startswith("/_control/"):
            given = request.headers.get("X-UMCodex-Control", "")
            if not hmac.compare_digest(given.encode(), control_secret.encode()):
                return refused("Refused.", 403)
        return await handler(request)

    return middleware


async def add_security_headers(request: web.Request, response: web.StreamResponse) -> None:
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    for name in [h for h in response.headers if h.lower().startswith("access-control-")]:
        del response.headers[name]
