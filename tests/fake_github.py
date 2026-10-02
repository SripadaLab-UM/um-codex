"""A stand-in for GitHub's Releases API, served on 127.0.0.1, and releases to put in it.

The shapes are GitHub's own (`GET /repos/{repo}/releases`; each asset's `url`
is the API address, which redirects to the file, and its `digest` is
`sha256:<hex>`), trimmed to the fields UM-Codex reads.
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
import zipfile
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from umcodex import signing

REPOSITORY = "SripadaLab-UM/um-codex"
AGENT = "ghcr.io/sripadalab-um/um-codex-agent@sha256:" + "a" * 64
GATEWAY = "nginx@sha256:" + "b" * 64
DEPENDENCY = f"httpx==0.28.1 \\\n    --hash=sha256:{'1' * 64}\n"


def wheel_bytes(version: str, images: dict[str, str] | None = None) -> bytes:
    """A package file with what UM-Codex reads in it: its images.json."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("umcodex/__init__.py", f'__version__ = "{version}"\n')
        package.writestr(
            "umcodex/images.json", json.dumps(images or {"agent": AGENT, "gateway": GATEWAY}, indent=2)
        )
    return buffer.getvalue()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class FakeRelease:
    tag: str
    files: dict[str, bytes]
    prerelease: bool = False
    draft: bool = False
    # Files GitHub gives no checksum for, and checksums GitHub gives wrongly.
    no_digest: set[str] = field(default_factory=set)
    wrong_digest: set[str] = field(default_factory=set)
    # What's actually sent for a file, if not what's listed (changed on the way).
    served: dict[str, bytes] = field(default_factory=dict)


def make_release(
    tag: str,
    version: str,
    private_key: str,
    *,
    wheel_version: str | None = None,
    release_images: dict[str, str] | None = None,
    package_images: dict[str, str] | None = None,
    requirements: str | None = None,
    sums_extra: str = "",
    tamper: dict[str, bytes] | None = None,
) -> FakeRelease:
    """A release as the workflow makes it: files, SHA256SUMS listing them, and
    its signature. `tamper` replaces files after they were listed and signed."""
    wheel_name = f"umcodex-{wheel_version or version}-py3-none-any.whl"
    wheel = wheel_bytes(version, package_images)
    images = json.dumps(release_images or {"agent": AGENT, "gateway": GATEWAY}, indent=2).encode()
    if requirements is None:
        requirements = DEPENDENCY + f"./{wheel_name} --hash=sha256:{sha256(wheel)}\n"
    files = {wheel_name: wheel, "requirements.txt": requirements.encode(), "images.json": images}
    files["install-macos.sh"] = b"#!/bin/sh\n"
    sums = "".join(f"{sha256(data)}  {name}\n" for name, data in sorted(files.items())) + sums_extra
    files["SHA256SUMS"] = sums.encode()
    files["SHA256SUMS.sig"] = signing.sign(files["SHA256SUMS"], private_key)
    files.update(tamper or {})
    return FakeRelease(tag, files)


class FakeGitHub:
    """Serves releases like GitHub's API. `api` is its address, for ReleaseSource."""

    def __init__(self) -> None:
        self.releases: list[FakeRelease] = []
        self.requests: list[str] = []
        self.list_status = 200
        self.delay = 0.0
        self.not_modified = 0  # lists answered 304 (GitHub doesn't count them)
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:  # quiet
                pass

            def do_GET(self) -> None:  # noqa: N802 (http.server's name)
                fake.requests.append(self.path)
                path = self.path.split("?", 1)[0]
                prefix = f"/repos/{REPOSITORY}/releases"
                if path == prefix:
                    if fake.delay:  # GitHub taking its time to list the releases
                        threading.Event().wait(fake.delay)
                    if fake.list_status != 200:
                        self._send(fake.list_status, b"{}")
                        return
                    body = json.dumps(fake.listing()).encode()
                    # As GitHub: a weak ETag on the list, and a 304 with no
                    # body when If-None-Match still matches it.
                    etag = f'W/"{sha256(body)}"'
                    if self.headers.get("if-none-match") == etag:
                        fake.not_modified += 1
                        self.send_response(304)
                        self.send_header("etag", etag)
                        self.end_headers()
                        return
                    self._send(200, body, "application/json", etag=etag)
                elif path.startswith(prefix + "/assets/"):
                    index, name = fake.asset(int(path.rsplit("/", 1)[1]))
                    self.send_response(302)
                    self.send_header("location", f"/files/{index}/{name}")
                    self.send_header("content-length", "0")
                    self.end_headers()
                elif path.startswith("/files/"):
                    _, _, index, name = path.split("/", 3)
                    release = fake.releases[int(index)]
                    self._send(200, release.served.get(name, release.files[name]), "application/octet-stream")
                else:
                    self._send(404, b"")

            def _send(self, status: int, body: bytes, kind: str = "text/plain", etag: str = "") -> None:
                self.send_response(status)
                self.send_header("content-type", kind)
                if etag:
                    self.send_header("etag", etag)
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.api = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True)
        self.thread.start()

    def asset(self, number: int) -> tuple[int, str]:
        return divmod(number, 1000)[0], self._names(divmod(number, 1000)[0])[divmod(number, 1000)[1]]

    def _names(self, index: int) -> list[str]:
        return sorted(self.releases[index].files)

    def listing(self) -> list[dict]:
        listed = []
        for index, release in enumerate(self.releases):
            assets = []
            for position, name in enumerate(self._names(index)):
                data = release.files[name]
                item: dict = {
                    "name": name,
                    "url": f"{self.api}/repos/{REPOSITORY}/releases/assets/{index * 1000 + position}",
                    "size": len(data),
                    "browser_download_url": f"https://github.com/{REPOSITORY}/releases/download/{release.tag}/{name}",
                }
                if name not in release.no_digest:
                    digest = sha256(b"wrong" if name in release.wrong_digest else data)
                    item["digest"] = f"sha256:{digest}"
                assets.append(item)
            listed.append(
                {
                    "tag_name": release.tag,
                    "name": f"UM-Codex {release.tag}",
                    "draft": release.draft,
                    "prerelease": release.prerelease,
                    "assets": assets,
                }
            )
        return listed

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
