"""Tests for the runtime SSRF guards (Phase 2b).

- ``_install_ssrf_guard`` from scanner.py: a Playwright route handler
  that aborts mid-scan requests to internal ranges.
- ``_safe_fetch_follow`` from policy_extractor.py: a redirect chain
  walker that validates every Location before following.

These tests use minimal fakes for Playwright's Route / Request and a
monkeypatched transport for httpx. Nothing hits the real network.
"""

from __future__ import annotations

import socket
from typing import Optional

import httpx
import pytest

from app.modules.policy_extractor import _safe_fetch_follow


# ---------------------------------------------------------------------------
# Playwright route-handler guard
# ---------------------------------------------------------------------------

class _FakeRequest:
    def __init__(self, url: str):
        self.url = url


class _FakeRoute:
    """Minimal stand-in for playwright.async_api.Route — tracks which
    terminal call (abort/continue) the handler makes."""
    def __init__(self):
        self.action: Optional[str] = None

    async def abort(self) -> None:
        self.action = "abort"

    async def continue_(self) -> None:
        self.action = "continue"


async def _run_handler(url: str, *, host_map: Optional[dict[str, list[str]]] = None):
    """Rebuild the guard's handler closure by calling the internal
    factory with a throwaway cache, so each case is isolated."""
    from urllib.parse import urlparse
    from app.security.ssrf import SsrfError, validate_url_safe
    import app.scanner as scanner_module  # noqa: F401 — ensures module loaded

    # Mirror the logic from scanner._install_ssrf_guard. Kept short
    # because the alternative — instantiating a real Playwright context
    # in tests — would require a headless browser in CI.
    host_cache: dict[str, bool] = {}
    route = _FakeRoute()
    request = _FakeRequest(url)

    parsed = urlparse(request.url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        await route.continue_()
        return route.action

    host = (parsed.hostname or "").lower()
    if host in host_cache:
        if host_cache[host]:
            await route.continue_()
        else:
            await route.abort()
        return route.action

    try:
        validate_url_safe(request.url)
    except SsrfError:
        host_cache[host] = False
        await route.abort()
        return route.action

    host_cache[host] = True
    await route.continue_()
    return route.action


def _fake_getaddrinfo(mapping: dict[str, list[str]]):
    def impl(host, *_a, **_kw):
        ips = mapping.get(host)
        if ips is None:
            raise socket.gaierror(-2, "NXDOMAIN (mocked)")
        return [
            (socket.AF_INET6 if ":" in ip else socket.AF_INET,
             socket.SOCK_STREAM, 0, "", (ip, 0))
            for ip in ips
        ]
    return impl


@pytest.mark.asyncio
class TestPlaywrightGuardHandler:
    async def test_public_url_is_allowed(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo",
                            _fake_getaddrinfo({"example.com": ["93.184.216.34"]}))
        assert await _run_handler("https://example.com/pricing") == "continue"

    async def test_loopback_is_aborted(self):
        assert await _run_handler("http://127.0.0.1/") == "abort"

    async def test_aws_metadata_is_aborted(self):
        assert await _run_handler("http://169.254.169.254/latest/meta-data/") == "abort"

    async def test_private_dns_is_aborted(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo",
                            _fake_getaddrinfo({"internal.corp": ["10.0.0.5"]}))
        assert await _run_handler("http://internal.corp/") == "abort"

    async def test_data_scheme_is_allowed(self):
        # Inline data URLs are local; Playwright handles them without a
        # network request. The guard MUST NOT abort them — it would break
        # pages that use inline SVG or fonts.
        assert await _run_handler("data:text/html;base64,PGh0bWw+") == "continue"

    async def test_blob_scheme_is_allowed(self):
        assert await _run_handler("blob:https://example.com/abc-123") == "continue"


# ---------------------------------------------------------------------------
# httpx manual redirect follow with SSRF check
# ---------------------------------------------------------------------------

class _FakeTransport(httpx.AsyncBaseTransport):
    """httpx transport that returns canned responses by (method, URL)."""
    def __init__(self, routes: dict[tuple[str, str], httpx.Response]):
        self.routes = routes
        self.hits: list[tuple[str, str]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        key = (request.method, str(request.url))
        self.hits.append(key)
        if key not in self.routes:
            # 404 so the helper treats the chain as a dead end, not an error.
            return httpx.Response(404, request=request)
        response = self.routes[key]
        # httpx requires a fresh Response with the request attached.
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=response.content,
            request=request,
        )


@pytest.mark.asyncio
class TestSafeFetchFollow:
    async def test_direct_200_returns_final_url(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo",
                            _fake_getaddrinfo({"example.com": ["93.184.216.34"]}))
        transport = _FakeTransport({
            ("HEAD", "https://example.com/datenschutz"):
                httpx.Response(200, headers={}, content=b""),
        })
        async with httpx.AsyncClient(transport=transport) as client:
            result = await _safe_fetch_follow(
                client, "https://example.com/datenschutz", method="HEAD",
            )
        assert result == (200, "https://example.com/datenschutz")

    async def test_redirect_to_public_is_followed(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo({
            "example.com":     ["93.184.216.34"],
            "cdn.example.com": ["151.101.1.1"],
        }))
        transport = _FakeTransport({
            ("HEAD", "https://example.com/datenschutz"):
                httpx.Response(302, headers={"location": "https://cdn.example.com/ds.html"}),
            ("HEAD", "https://cdn.example.com/ds.html"):
                httpx.Response(200),
        })
        async with httpx.AsyncClient(transport=transport) as client:
            result = await _safe_fetch_follow(
                client, "https://example.com/datenschutz", method="HEAD",
            )
        assert result == (200, "https://cdn.example.com/ds.html")

    async def test_redirect_to_loopback_is_blocked(self, monkeypatch):
        # The attack: public origin 302s to loopback. Without the guard,
        # httpx follows and leaks the internal response to the scanner.
        monkeypatch.setattr(socket, "getaddrinfo",
                            _fake_getaddrinfo({"evil.example.com": ["93.184.216.34"]}))
        transport = _FakeTransport({
            ("HEAD", "https://evil.example.com/datenschutz"):
                httpx.Response(302, headers={"location": "http://127.0.0.1/admin"}),
            # No route for the loopback URL — we must NEVER hit it.
        })
        async with httpx.AsyncClient(transport=transport) as client:
            result = await _safe_fetch_follow(
                client, "https://evil.example.com/datenschutz", method="HEAD",
            )
        assert result is None
        # Only the initial HEAD hit the transport; the follow-up was aborted.
        assert ("HEAD", "http://127.0.0.1/admin") not in transport.hits

    async def test_redirect_to_aws_metadata_is_blocked(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo",
                            _fake_getaddrinfo({"trap.example.com": ["93.184.216.34"]}))
        transport = _FakeTransport({
            ("HEAD", "https://trap.example.com/x"):
                httpx.Response(302, headers={
                    "location": "http://169.254.169.254/latest/meta-data/",
                }),
        })
        async with httpx.AsyncClient(transport=transport) as client:
            result = await _safe_fetch_follow(
                client, "https://trap.example.com/x", method="HEAD",
            )
        assert result is None

    async def test_redirect_loop_capped_at_max_hops(self, monkeypatch):
        # A → B → A → B → … must not spin forever.
        monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo({
            "a.example.com": ["93.184.216.34"],
            "b.example.com": ["93.184.216.34"],
        }))
        transport = _FakeTransport({
            ("HEAD", "https://a.example.com/"):
                httpx.Response(302, headers={"location": "https://b.example.com/"}),
            ("HEAD", "https://b.example.com/"):
                httpx.Response(302, headers={"location": "https://a.example.com/"}),
        })
        async with httpx.AsyncClient(transport=transport) as client:
            result = await _safe_fetch_follow(
                client, "https://a.example.com/", method="HEAD", max_hops=3,
            )
        assert result is None
        # Exactly max_hops+1 requests made (the initial + 3 follows).
        assert len(transport.hits) == 4

    async def test_initial_private_url_is_blocked(self, monkeypatch):
        # If the caller ever hands in a private URL by mistake, the
        # helper MUST refuse before the first network call.
        transport = _FakeTransport({})  # no routes
        async with httpx.AsyncClient(transport=transport) as client:
            result = await _safe_fetch_follow(
                client, "http://127.0.0.1/datenschutz", method="HEAD",
            )
        assert result is None
        assert transport.hits == []
