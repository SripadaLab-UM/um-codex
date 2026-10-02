"""The relay: only the launch's token gets through, the key is swapped in on
the host, never echoed back or logged, and streams pass straight through."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

import httpx
import pytest
from aiohttp import web

from tests.conftest import FAKE_KEY
from umcodex import relay as relay_module
from umcodex.credentials import MissingCredential
from umcodex.relay import REDACTED, Relay, RelayServer, Scrubber, new_token

TOKEN = new_token()

# The start of a Responses stream as the Toolkit sends it (trimmed).
SSE = [
    b'event: response.created\ndata: {"type":"response.created","response":{"id":"resp_1"}}\n\n',
    b'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"Hel"}\n\n',
    b'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"lo"}\n\n',
    b'event: response.completed\ndata: {"type":"response.completed","response":{"id":"resp_1"}}\n\n',
]


class Upstream:
    """A local stand-in for the Toolkit."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str, dict[str, str], bytes]] = []
        self.mode = "sse"
        self.failures = 0
        self.gate = asyncio.Event()

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self.handle)
        return app

    async def handle(self, request: web.Request) -> web.StreamResponse:
        body = await request.read()
        self.seen.append((request.method, request.path_qs, dict(request.headers), body))
        if self.failures > 0:
            self.failures -= 1
            return web.json_response(
                {"error": {"code": "server_busy", "message": "busy"}},
                status=503,
                headers={"retry-after": "0"},
            )
        if self.mode == "echo":
            # A careless server that puts the credential in its answer.
            auth = request.headers.get("authorization", "")
            return web.json_response({"error": {"message": f"bad key {auth}"}}, status=401)
        if self.mode == "echo-id":
            auth = request.headers.get("authorization", "")[7:]
            return web.json_response(
                {"error": {"code": auth, "message": "bad"}}, status=400, headers={"x-request-id": auth}
            )
        if self.mode == "echo-stream":
            response = web.StreamResponse(headers={"content-type": "text/event-stream"})
            await response.prepare(request)
            auth = request.headers.get("authorization", "").encode()
            half = len(auth) // 2
            await response.write(b"data: " + auth[:half])
            await response.write(auth[half:] + b"\n\n")
            await response.write_eof()
            return response
        if request.path == "/v1/models":
            return web.json_response({"object": "list", "data": [{"id": "gpt-5.6-terra"}]})
        response = web.StreamResponse(headers={"content-type": "text/event-stream", "x-request-id": "req_1"})
        await response.prepare(request)
        await response.write(SSE[0])
        await self.gate.wait()  # the relay must pass the first event on before the rest exists
        for event in SSE[1:]:
            await response.write(event)
        await response.write_eof()
        return response


@contextlib.asynccontextmanager
async def serve(app: web.Application) -> AsyncIterator[int]:
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    server = site._server
    assert server is not None
    port = server.sockets[0].getsockname()[1]  # type: ignore[attr-defined]
    try:
        yield port
    finally:
        await runner.cleanup()


Body = Callable[[httpx.AsyncClient, Upstream], Awaitable[None]]


def run_with_relay(test: Body, key: Callable[[], str] = lambda: FAKE_KEY) -> Upstream:
    upstream = Upstream()

    async def main() -> None:
        async with serve(upstream.app()) as up_port, httpx.AsyncClient() as upstream_client:
            relay = Relay(TOKEN, key, f"http://127.0.0.1:{up_port}/v1", client=upstream_client)
            async with (
                serve(relay.app()) as port,
                httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as c,
            ):
                await test(c, upstream)

    asyncio.run(main())
    return upstream


def codex_request() -> bytes:
    return json.dumps({"model": "gpt-5.6-terra", "input": "hi", "stream": True, "store": False}).encode()


def bearer(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}", "content-type": "application/json"}


@pytest.mark.parametrize(
    "headers", [{}, bearer("umc_wrong"), bearer(TOKEN[:-1]), {"authorization": TOKEN}, {"x-api-key": TOKEN}]
)
def test_without_the_launch_token_nothing_reaches_the_toolkit(headers):
    async def test(client: httpx.AsyncClient, upstream: Upstream) -> None:
        response = await client.post("/relay/v1/responses", content=codex_request(), headers=headers)
        assert response.status_code == 401
        assert FAKE_KEY not in response.text

    assert run_with_relay(test).seen == []


def test_the_key_is_swapped_in_and_the_token_never_goes_upstream():
    async def test(client: httpx.AsyncClient, upstream: Upstream) -> None:
        upstream.gate.set()
        response = await client.post(
            "/relay/v1/responses",
            content=codex_request(),
            headers={**bearer(TOKEN), "cookie": "x=1", "x-codex-turn": "abc", "originator": "codex_cli_rs"},
        )
        assert response.status_code == 200
        assert response.content == b"".join(SSE)
        assert response.headers["x-request-id"] == "req_1"

    upstream = run_with_relay(test)
    [(method, path, headers, body)] = upstream.seen
    assert (method, path) == ("POST", "/v1/responses")
    assert headers["Authorization"] == f"Bearer {FAKE_KEY}"
    assert TOKEN not in json.dumps(headers) and TOKEN.encode() not in body
    assert "Cookie" not in headers
    assert headers["originator"] == "codex_cli_rs" and headers["x-codex-turn"] == "abc"
    assert body == codex_request()


def test_the_model_list_is_relayed():
    async def test(client: httpx.AsyncClient, upstream: Upstream) -> None:
        response = await client.get("/relay/v1/models", headers=bearer(TOKEN))
        assert response.json()["data"] == [{"id": "gpt-5.6-terra"}]

    run_with_relay(test)


def test_streams_pass_straight_through():
    async def test(client: httpx.AsyncClient, upstream: Upstream) -> None:
        request = client.build_request(
            "POST", "/relay/v1/responses", content=codex_request(), headers=bearer(TOKEN)
        )
        response = await client.send(request, stream=True)
        chunks = response.aiter_raw()
        first = await asyncio.wait_for(chunks.__anext__(), timeout=5)
        assert first == SSE[0]  # arrived while the upstream was still holding the rest
        upstream.gate.set()
        rest = b"".join([chunk async for chunk in chunks])
        assert first + rest == b"".join(SSE)
        await response.aclose()

    run_with_relay(test)


@pytest.mark.parametrize("mode", ["echo", "echo-stream"])
def test_the_key_is_never_echoed_back(mode, caplog):
    caplog.set_level(logging.DEBUG)

    async def test(client: httpx.AsyncClient, upstream: Upstream) -> None:
        upstream.mode = mode
        response = await client.post("/relay/v1/responses", content=codex_request(), headers=bearer(TOKEN))
        assert FAKE_KEY not in response.text
        assert REDACTED.decode() in response.text
        assert all(FAKE_KEY not in v for v in response.headers.values())

    run_with_relay(test)
    assert FAKE_KEY not in caplog.text
    assert TOKEN not in caplog.text


def test_busy_answers_are_retried_and_nothing_is_logged_but_metadata(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(relay_module, "MIN_DELAY", 0.0)

    async def test(client: httpx.AsyncClient, upstream: Upstream) -> None:
        upstream.failures = 2
        upstream.gate.set()
        response = await client.post("/relay/v1/responses", content=codex_request(), headers=bearer(TOKEN))
        assert response.status_code == 200

    upstream = run_with_relay(test)
    assert len(upstream.seen) == 3
    assert all(body == codex_request() for *_, body in upstream.seen)
    assert "server_busy" in caplog.text
    assert FAKE_KEY not in caplog.text and "hi" not in caplog.text


def test_without_a_saved_key_it_says_so():
    def missing() -> str:
        raise MissingCredential("none")

    async def test(client: httpx.AsyncClient, upstream: Upstream) -> None:
        response = await client.post("/relay/v1/responses", content=codex_request(), headers=bearer(TOKEN))
        assert response.status_code == 503
        assert "um-codex key" in response.json()["error"]["message"]

    assert run_with_relay(test, key=missing).seen == []


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("POST", "/v1/responses", 404),
        ("POST", "/relay/v2/responses", 404),
        ("POST", "/relay/v1/a/../../admin", 404),  # normalised to /relay/admin
        ("POST", "/relay/v1/a//b", 400),
        ("DELETE", "/relay/v1/files/x", 400),
    ],
)
def test_only_v1_paths_are_relayed(method, path, status):
    async def test(client: httpx.AsyncClient, upstream: Upstream) -> None:
        url = httpx.URL(f"{client.base_url}").copy_with(raw_path=path.encode())
        response = await client.request(method, url, headers=bearer(TOKEN))
        assert response.status_code == status

    assert run_with_relay(test).seen == []


def test_the_scrubber_finds_the_key_across_chunks():
    key = b"sk-secret-123"
    for split in range(1, len(key)):
        scrub = Scrubber(key)
        data = b"before " + key[:split]
        out = scrub.feed(data) + scrub.feed(key[split:] + b" after") + scrub.flush()
        assert out == b"before " + REDACTED + b" after"
    scrub = Scrubber(key)
    # A partial match that never completes comes out unchanged, and nothing is held otherwise.
    assert scrub.feed(b"data sk-") == b"data "
    assert scrub.feed(b"other") == b"sk-other"
    assert scrub.flush() == b""


def test_the_server_listens_only_on_localhost_and_stops():
    server = RelayServer(Relay(TOKEN, lambda: FAKE_KEY, "http://127.0.0.1:9/v1"))
    port = server.start()
    try:
        response = httpx.get(f"http://127.0.0.1:{port}/relay/v1/models", timeout=5)
        assert response.status_code == 401
    finally:
        server.stop()
    with pytest.raises(httpx.ConnectError):
        httpx.get(f"http://127.0.0.1:{port}/relay/v1/models", timeout=2)


def test_a_key_in_a_request_id_or_error_code_is_never_logged(caplog):
    """The review's reproduction: a server that returns the key as its request
    ID (or error code) must not get it into the log."""
    caplog.set_level(logging.DEBUG)
    headers = httpx.Headers({"x-request-id": FAKE_KEY, "retry-after": "0"})
    body = json.dumps({"error": {"code": FAKE_KEY, "type": FAKE_KEY[:20]}}).encode()
    trouble = relay_module.classify(503, headers, body, key=FAKE_KEY)
    assert trouble.request_id is None and trouble.code is None
    assert FAKE_KEY not in json.dumps(trouble.record())
    ordinary = relay_module.classify(503, httpx.Headers({"x-request-id": "req_1"}), b"", key=FAKE_KEY)
    assert ordinary.request_id == "req_1"

    async def test(client: httpx.AsyncClient, upstream: Upstream) -> None:
        upstream.mode = "echo-id"
        response = await client.post("/relay/v1/responses", content=codex_request(), headers=bearer(TOKEN))
        assert response.status_code == 400
        assert FAKE_KEY not in response.text and FAKE_KEY not in json.dumps(dict(response.headers))

    run_with_relay(test)
    assert FAKE_KEY not in caplog.text


def test_a_long_error_body_is_scrubbed_before_its_cut():
    async def main() -> None:
        key = FAKE_KEY.encode()
        limit = 100
        body = b"x" * (limit - 10) + key + b"tail"  # the cut falls inside the key

        class Upstream:
            async def aiter_bytes(self):
                yield body

            async def aclose(self):
                pass

        out = await relay_module._read_bounded(Upstream(), FAKE_KEY, limit)  # type: ignore[arg-type]
        assert len(out) <= limit
        assert not any(key[:n] in out for n in range(8, len(key) + 1))

    asyncio.run(main())


def test_the_watchdogs_alive_check_needs_the_token_and_never_goes_upstream():
    async def test(client: httpx.AsyncClient, upstream: Upstream) -> None:
        assert (await client.get("/relay/v1/_umcodex/alive")).status_code == 401
        assert (await client.get("/relay/v1/_umcodex/alive", headers=bearer(TOKEN))).status_code == 204

    assert run_with_relay(test).seen == []


@pytest.mark.parametrize(
    ("value", "allowed"),
    [
        ("http://127.0.0.1:5000/v1", True),
        ("http://localhost:5000/v1", True),
        ("http://[::1]:5000/v1", True),
        ("https://api.example.org/v1", False),
        ("http://192.0.2.10:5000/v1", False),
        ("http://127.0.0.1.example.org/v1", False),
        ("http://user@127.0.0.1:5000/v1", False),
        ("https://127.0.0.1:5000/v1", False),
    ],
)
def test_the_upstream_override_is_only_a_local_stub(monkeypatch, value, allowed):
    monkeypatch.setenv("UMCODEX_UPSTREAM", value)
    if allowed:
        assert relay_module.upstream_base_url("https://default/v1") == value
    else:
        with pytest.raises(relay_module.UpstreamRefused):
            relay_module.upstream_base_url("https://default/v1")


# --- The Codex app copy's local chats (M6): answered here, never upstream ---------


def _events(text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


LOCAL_RESPONSES = "/um-codex-local/umcodex-thesis-a1/v1/responses"


def run_local_chats(test, running=None) -> None:
    async def main() -> None:
        app = relay_module.local_chats_app("inst-1", running)
        async with serve(app) as port, httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            await test(client)

    asyncio.run(main())


def test_local_chats_get_the_remote_reminder_with_no_model_call():
    async def test(client: httpx.AsyncClient) -> None:
        response = await client.post(LOCAL_RESPONSES, content=codex_request())
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _events(response.text)
        assert [e["type"] for e in events] == [
            "response.created",
            "response.output_item.added",
            "response.output_text.delta",
            "response.output_item.done",
            "response.completed",
        ]
        text = events[3]["item"]["content"][0]["text"]
        assert text == relay_module.local_chats_message(["umcodex-now-b2"])  # what runs now, not the path's
        assert "Remote · umcodex-now-b2" in text and "outside the sandbox" in text
        assert events[-1]["response"]["status"] == "completed"
        for other in ("models", "chat/completions", "responses/x"):
            refused = await client.post(f"/um-codex-local/umcodex-thesis-a1/v1/{other}")
            assert refused.status_code == 404
        assert (await client.post("/um-codex-local/x/v1/responses")).status_code == 404
        assert (await client.post("/relay/v1/responses")).status_code == 404  # no relaying here at all
        whoami = await client.get("/um-codex-local/_whoami")
        assert whoami.json() == {"app": "um-codex-local-chats", "instance": "inst-1"}

    run_local_chats(test, running=lambda: ["umcodex-now-b2"])


def test_with_nothing_running_the_reminder_says_so():
    async def test(client: httpx.AsyncClient) -> None:
        response = await client.post(LOCAL_RESPONSES, content=codex_request())
        assert "no UM-Codex setup is running" in _events(response.text)[3]["item"]["content"][0]["text"]

    run_local_chats(test, running=lambda: [])


def test_the_relay_itself_doesnt_answer_local_chats():
    async def test(client: httpx.AsyncClient, upstream: Upstream) -> None:
        response = await client.post(LOCAL_RESPONSES, content=codex_request())
        assert response.status_code == 401

    assert run_with_relay(test).seen == []
