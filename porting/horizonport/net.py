"""HTTP for the few endpoints a port talks to: GitHub releases and Microsoft.

`urllib` only, so nothing has to be installed. Every request carries a
HorizonPort user agent, follows redirects (GitHub release assets redirect to a
CDN), and turns HTTP errors into messages a launcher can show.

The Microsoft endpoints are used by `auth.py`; this module only moves bytes.
Tests replace `request` with a fake, so no test touches the network.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from .util import CHUNK, PortError

USER_AGENT = "HorizonPort/1 (launcher porting toolkit; +https://github.com/horizon-rust/horizon)"
TIMEOUT = 60.0


class Response:
    def __init__(self, status: int, headers: dict[str, str], body: bytes):
        self.status = status
        self.headers = headers
        self.body = body

    def json(self) -> object:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PortError(f"the server answered with something that is not JSON: {exc}") from None

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


def request(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    method: str | None = None,
    timeout: float = TIMEOUT,
) -> Response:
    """One HTTPS request. Raises PortError with the server's own words on failure."""
    merged = {"User-Agent": USER_AGENT, "Accept": "application/json, */*"}
    merged.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=merged, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as answer:
            return Response(answer.status, dict(answer.headers), answer.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        detail = body[:400].decode("utf-8", "replace").strip()
        raise PortError(f"{url} answered {exc.code} {exc.reason}" + (f": {detail}" if detail else "")) from None
    except urllib.error.URLError as exc:
        raise PortError(
            f"could not reach {url}: {exc.reason}",
            hint="Check the connection, or use a local archive with --archive.",
        ) from None
    except TimeoutError:
        raise PortError(f"{url} did not answer within {timeout:.0f}s") from None


def get(url: str, headers: dict[str, str] | None = None) -> Response:
    return request(url, headers=headers)


def post_form(url: str, fields: dict[str, str]) -> Response:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    return request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )


def post_json(url: str, payload: object, headers: dict[str, str] | None = None) -> Response:
    merged = {"Content-Type": "application/json", "Accept": "application/json"}
    merged.update(headers or {})
    return request(url, data=json.dumps(payload).encode("utf-8"), headers=merged, method="POST")


def download(
    url: str,
    destination: Path,
    *,
    expected_sha256: str | None = None,
    progress: Callable[[int, int | None], None] | None = None,
) -> Path:
    """Stream a file to `destination` (atomically) and check its SHA-256."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    import hashlib

    digest = hashlib.sha256()
    written = 0
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as answer, open(temporary, "wb") as handle:
            total = answer.headers.get("Content-Length")
            total_bytes = int(total) if total and total.isdigit() else None
            while chunk := answer.read(CHUNK):
                handle.write(chunk)
                digest.update(chunk)
                written += len(chunk)
                if progress:
                    progress(written, total_bytes)
    except urllib.error.HTTPError as exc:
        temporary.unlink(missing_ok=True)
        raise PortError(f"{url} answered {exc.code} {exc.reason}") from None
    except urllib.error.URLError as exc:
        temporary.unlink(missing_ok=True)
        raise PortError(f"could not reach {url}: {exc.reason}") from None
    actual = digest.hexdigest()
    if expected_sha256 and actual != expected_sha256.lower():
        temporary.unlink(missing_ok=True)
        raise PortError(
            f"{destination.name} does not match its checksum: got {actual}, expected {expected_sha256}",
            hint="Nothing was installed. Try again, and report a mismatch that repeats.",
        )
    os.replace(temporary, destination)
    return destination


def retry(times: int, delay: float, call):
    """Run `call` up to `times`, retrying only network errors."""
    last: Exception | None = None
    for attempt in range(times):
        try:
            return call()
        except PortError as exc:
            last = exc
            if attempt + 1 < times:
                time.sleep(delay)
    assert last is not None
    raise last
