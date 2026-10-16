"""Concurrent link health checking (stdlib only).

Strategy per URL:
- Try ``HEAD`` first (cheap); if the server rejects it with 405/403/501,
  fall back to ``GET`` (body is never read in full).
- Follow redirects (``urllib`` default); the final URL is recorded.
- One retry on network-level failures (timeout, DNS, refused) and on 5xx.
- Polite User-Agent identifying the tool.

Classification:
- ``ok``   - HTTP status < 400
- ``dead``  - HTTP status >= 400, DNS failure, timeout, connection error
"""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor, as_completed

USER_AGENT = "linkrot/1.0 (+https://github.com/agenticspring/linkrot)"
_RETRYABLE_STATUS = {405, 403, 501}  # HEAD not allowed -> fall back to GET


class LinkResult(namedtuple("LinkResult", ["url", "final_url", "status", "ok", "detail"])):
    """Result of checking one URL.

    ``status`` is the HTTP status code, or ``None`` for network errors.
    ``detail`` is a short human/machine readable explanation.
    """

    __slots__ = ()


def _fetch(url: str, timeout: float, method: str) -> urllib.response.addinfourl:
    request = urllib.request.Request(
        url,
        method=method,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )
    return urllib.request.urlopen(request, timeout=timeout)


def _classify_error(exc: Exception) -> str:
    if isinstance(exc, socket.timeout) or "timed out" in str(exc).lower():
        return "timeout"
    msg = str(exc).lower()
    if "name or service not known" in msg or "nodename nor servname" in msg or "dns" in msg:
        return "dns error"
    if "connection refused" in msg or "connection reset" in msg:
        return "connection error"
    return "network error"


def check_url(url: str, timeout: float = 10.0, retries: int = 1) -> LinkResult:
    """Check a single URL and return a :class:`LinkResult`."""
    attempts = 1 + max(0, retries)
    last_error: Exception | None = None

    for attempt in range(attempts):
        for method in ("HEAD", "GET"):
            try:
                with _fetch(url, timeout, method) as response:
                    status = response.status
                    final_url = response.geturl()
                    if status < 400:
                        return LinkResult(url, final_url, status, True, f"HTTP {status}")
                    if 400 <= status < 500:
                        return LinkResult(url, final_url, status, False, f"HTTP {status}")
                    # 5xx: retryable once across attempts.
                    last_error = urllib.error.HTTPError(
                        url, status, f"HTTP {status}", {}, None
                    )
                    break
            except urllib.error.HTTPError as exc:
                status = exc.code
                final_url = getattr(exc, "url", url)
                if status < 400:
                    return LinkResult(url, final_url, status, True, f"HTTP {status}")
                if status in _RETRYABLE_STATUS and method == "HEAD":
                    continue  # fall back to GET
                if 400 <= status < 500:
                    return LinkResult(url, final_url, status, False, f"HTTP {status}")
                last_error = exc  # 5xx -> retry
                break
            except Exception as exc:  # URLError, socket errors, ssl errors...
                last_error = exc
                break  # do not try GET after a network error; retry whole attempt
        # Small pause between retries so we do not hammer a flaky host.
        if attempt < attempts - 1:
            time.sleep(1)

    if last_error is not None:
        if isinstance(last_error, urllib.error.HTTPError):
            return LinkResult(url, url, last_error.code, False, f"HTTP {last_error.code}")
        detail = _classify_error(last_error)
        reason = str(last_error).split(":", 1)[0][:120]
        return LinkResult(url, url, None, False, f"{detail}: {reason}")

    return LinkResult(url, url, None, False, "unknown error")


def check_urls(urls: list[str], concurrency: int = 10, timeout: float = 10.0) -> dict[str, LinkResult]:
    """Check many URLs concurrently; returns {url: LinkResult}."""
    results: dict[str, LinkResult] = {}
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        future_to_url = {pool.submit(check_url, url, timeout): url for url in urls}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                results[url] = future.result()
            except Exception as exc:  # never let one thread kill the run
                results[url] = LinkResult(url, url, None, False, f"checker error: {exc}")
    return results
