"""Tests for Phase 7 observability — structured logs + request-ID +
Prometheus /metrics + extended /health.

Nothing below talks to a real Redis or Sentry — the logging tests are
pure-Python, the metrics tests drive the module-level counters through
the HTTP layer (in-memory SQLite fixture), and /health is exercised
with the DB probe live and the Redis probe disabled.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import db as db_module
from app.db_models import Base
from app.observability.logging import (
    JsonFormatter,
    RequestIdFilter,
    configure_logging,
    get_request_id,
    set_request_id,
)
from app.observability.metrics import (
    http_requests_total,
    normalise_path,
    render_metrics,
)


# ---------------------------------------------------------------------------
# Logging — formatter + request_id ContextVar
# ---------------------------------------------------------------------------

class TestJsonFormatter:
    def test_record_is_single_line_json(self):
        rec = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__,
            lineno=1, msg="hello %s", args=("world",), exc_info=None,
        )
        rec.request_id = "abc123"
        out = JsonFormatter().format(rec)
        assert "\n" not in out
        parsed = json.loads(out)
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test"
        assert parsed["msg"] == "hello world"
        assert parsed["request_id"] == "abc123"
        assert "ts" in parsed

    def test_extra_fields_are_preserved(self):
        rec = logging.LogRecord(
            name="test", level=logging.WARNING, pathname=__file__,
            lineno=1, msg="m", args=(), exc_info=None,
        )
        rec.request_id = "-"
        rec.scan_id = "s_123"
        rec.org_id = "o_abc"
        parsed = json.loads(JsonFormatter().format(rec))
        assert parsed["scan_id"] == "s_123"
        assert parsed["org_id"] == "o_abc"

    def test_non_serialisable_extras_become_repr(self):
        class Blob:
            def __repr__(self) -> str: return "<Blob x=1>"
        rec = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__,
            lineno=1, msg="m", args=(), exc_info=None,
        )
        rec.request_id = "-"
        rec.weird = Blob()
        parsed = json.loads(JsonFormatter().format(rec))
        assert parsed["weird"] == "<Blob x=1>"


class TestRequestIdContextVar:
    def test_default_is_none(self):
        set_request_id(None)
        assert get_request_id() is None

    def test_set_and_read_back(self):
        set_request_id("req-42")
        try:
            assert get_request_id() == "req-42"
        finally:
            set_request_id(None)

    def test_independent_across_tasks(self):
        """Each asyncio task has its own copy of the ContextVar — that's
        what makes request-id tagging work under concurrency."""
        results: dict[str, str | None] = {}

        async def task(name: str, rid: str) -> None:
            set_request_id(rid)
            await asyncio.sleep(0)      # let the other task interleave
            results[name] = get_request_id()

        async def run() -> None:
            await asyncio.gather(task("A", "req-A"), task("B", "req-B"))

        asyncio.run(run())
        assert results == {"A": "req-A", "B": "req-B"}


class TestConfigureLogging:
    def test_json_mode_emits_json(self):
        buf = io.StringIO()
        configure_logging(level="INFO", fmt="json", stream=buf)
        logging.getLogger("probe").info("hello", extra={"scan_id": "s1"})
        line = buf.getvalue().strip()
        assert line
        parsed = json.loads(line)
        assert parsed["msg"] == "hello"
        assert parsed["scan_id"] == "s1"
        # Reset to the test-suite's default text format so later
        # tests don't drown in JSON.
        configure_logging(level="WARNING", fmt="text")

    def test_text_mode_includes_request_id_placeholder(self):
        buf = io.StringIO()
        configure_logging(level="INFO", fmt="text", stream=buf)
        logging.getLogger("probe").info("hi")
        line = buf.getvalue().strip()
        assert "req=-" in line       # no request id set → dash
        configure_logging(level="WARNING", fmt="text")

    def test_is_idempotent(self):
        buf1 = io.StringIO()
        buf2 = io.StringIO()
        configure_logging(level="INFO", fmt="text", stream=buf1)
        configure_logging(level="INFO", fmt="text", stream=buf2)
        logging.getLogger("probe").info("hi")
        # Second call replaced the first handler — only buf2 got the line.
        assert buf1.getvalue() == ""
        assert buf2.getvalue() != ""
        configure_logging(level="WARNING", fmt="text")

    def test_filter_populates_request_id_attribute(self):
        rec = logging.LogRecord(
            name="t", level=logging.INFO, pathname=__file__,
            lineno=1, msg="m", args=(), exc_info=None,
        )
        set_request_id("req-xyz")
        try:
            assert RequestIdFilter().filter(rec) is True
            assert rec.request_id == "req-xyz"
        finally:
            set_request_id(None)


# ---------------------------------------------------------------------------
# Metrics — route normalisation + render format
# ---------------------------------------------------------------------------

class TestNormalisePath:
    def test_prefers_route_template(self):
        assert normalise_path("/scans/abc123", "/scans/{scan_id}") == "/scans/{scan_id}"

    def test_falls_back_to_raw_path_without_template(self):
        assert normalise_path("/health", None) == "/health"

    def test_empty_path_becomes_unknown(self):
        assert normalise_path("", None) == "unknown"


class TestRenderMetrics:
    def test_output_is_prometheus_text(self):
        # Tick the counter once so it shows up in the output.
        http_requests_total.labels("GET", "/probe", "200").inc()
        body, content_type = render_metrics()
        assert content_type.startswith("text/plain")
        text = body.decode("utf-8")
        assert "# HELP scanner_http_requests_total" in text
        assert 'scanner_http_requests_total{method="GET",path="/probe",status="200"}' in text


# ---------------------------------------------------------------------------
# HTTP — middleware + /health + /metrics against a real app fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def app_with_db(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.db import install_sqlite_fk_pragma
    from app.security.rate_limit import auth_rate_limiter, scan_rate_limiter

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    install_sqlite_fk_pragma(engine)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_engine", engine)
    monkeypatch.setattr(db_module, "_SessionLocal", SessionLocal)
    scan_rate_limiter.reset()
    auth_rate_limiter.reset()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    await engine.dispose()


@pytest.mark.asyncio
class TestRequestIdMiddleware:
    async def test_response_carries_x_request_id(self, app_with_db):
        r = await app_with_db.get("/health")
        assert "x-request-id" in r.headers
        assert 8 <= len(r.headers["x-request-id"]) <= 128

    async def test_incoming_header_is_reused(self, app_with_db):
        r = await app_with_db.get("/health", headers={"x-request-id": "upstream-trace-0001"})
        assert r.headers["x-request-id"] == "upstream-trace-0001"

    async def test_pathological_incoming_header_is_replaced(self, app_with_db):
        # Too long → mint fresh. Stops a caller from salting our logs
        # with a 10 KB request_id.
        r = await app_with_db.get("/health", headers={"x-request-id": "x" * 1000})
        assert r.headers["x-request-id"] != "x" * 1000

    async def test_empty_incoming_header_is_replaced(self, app_with_db):
        r = await app_with_db.get("/health", headers={"x-request-id": "short"})
        # 5 chars is below the sanity floor → minted.
        assert r.headers["x-request-id"] != "short"


@pytest.mark.asyncio
class TestHealthEndpoint:
    async def test_reports_ok_with_db_reachable_and_no_redis(self, app_with_db):
        r = await app_with_db.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["deps"]["db"] == "ok"
        # No REDIS_URL in tests → disabled, not fail.
        assert body["deps"]["redis"] == "disabled"
        assert body["version"]

    async def test_degrades_when_db_probe_fails(self, app_with_db, monkeypatch):
        # Patch session_scope to blow up the DB probe.
        from contextlib import asynccontextmanager
        from app import db as db_module

        @asynccontextmanager
        async def broken():
            raise RuntimeError("db is on fire")
            yield  # unreachable

        monkeypatch.setattr(db_module, "session_scope", broken)
        monkeypatch.setattr("app.main.session_scope", broken)
        r = await app_with_db.get("/health")
        body = r.json()
        assert body["deps"]["db"] == "fail"
        assert body["status"] == "degraded"


@pytest.mark.asyncio
class TestMetricsEndpoint:
    async def test_metrics_exposes_prometheus_text(self, app_with_db):
        # Drive one request through the middleware so the counter ticks.
        await app_with_db.get("/health")
        r = await app_with_db.get("/metrics")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")
        body = r.text
        assert "# HELP scanner_http_requests_total" in body
        assert "scanner_http_requests_total" in body
        # /health label should have ticked AT LEAST once; request path
        # must be the FastAPI route template, not some random value.
        assert 'path="/health"' in body

    async def test_metrics_is_not_self_recorded(self, app_with_db):
        # Hitting /metrics repeatedly must NOT make its own counter
        # explode — that's exactly how scrape loops lie to operators.
        for _ in range(3):
            await app_with_db.get("/metrics")
        r = await app_with_db.get("/metrics")
        assert 'path="/metrics"' not in r.text


# ---------------------------------------------------------------------------
# Domain counters — ssrf / quota / auth / scans
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestDomainCounters:
    async def _signup(self, client, email: str) -> str:
        r = await client.post("/auth/signup", json={
            "email": email, "password": "long-enough-password",
        })
        return r.json()["access_token"]

    async def test_signup_ok_ticks_auth_counter(self, app_with_db):
        await self._signup(app_with_db, "alice@example.com")
        r = await app_with_db.get("/metrics")
        assert 'scanner_auth_attempts_total{endpoint="signup",result="ok"}' in r.text

    async def test_bad_login_ticks_bad_credentials_label(self, app_with_db):
        await self._signup(app_with_db, "alice@example.com")
        await app_with_db.post("/auth/login", json={
            "email": "alice@example.com", "password": "wrong-but-long-enough",
        })
        r = await app_with_db.get("/metrics")
        assert 'result="bad_credentials"' in r.text

    async def test_ssrf_rejection_ticks_ssrf_counter(self, app_with_db):
        token = await self._signup(app_with_db, "alice@example.com")
        await app_with_db.post(
            "/scan",
            headers={"Authorization": f"Bearer {token}"},
            json={"url": "http://127.0.0.1/"},
        )
        r = await app_with_db.get("/metrics")
        # Counter line for ssrf_blocks_total shows up with at least 1.
        assert "scanner_ssrf_blocks_total" in r.text
        # Find the last non-comment line and parse the value.
        block_lines = [
            l for l in r.text.splitlines()
            if l.startswith("scanner_ssrf_blocks_total") and not l.startswith("#")
        ]
        assert block_lines and float(block_lines[0].split()[-1]) >= 1.0

    async def test_quota_exceeded_ticks_plan_label(self, app_with_db, monkeypatch):
        from app.security.rate_limit import scan_rate_limiter
        monkeypatch.setattr(scan_rate_limiter, "per_minute", 100)

        token = await self._signup(app_with_db, "alice@example.com")

        # Saturate the free-tier quota by inserting 5 completed scans
        # directly — no Playwright needed.
        from sqlalchemy import select
        from app.db import session_scope
        from app.db_models import Membership
        from app.models import (
            ContactChannelsReport, CookieReport, CrawlResult, FormReport,
            NetworkResult, PrivacyAnalysis, RiskScore, ScanResponse,
            ThirdPartyWidgetsReport,
        )
        from app.storage import save_scan

        # Figure out the alice org id.
        me = await app_with_db.get(
            "/auth/me", headers={"Authorization": f"Bearer {token}"},
        )
        async with session_scope() as session:
            org_id = (await session.execute(
                select(Membership.organization_id)
                .where(Membership.user_id == me.json()["id"])
            )).scalar_one()

        fake = ScanResponse(
            target="https://example.com/",
            risk=RiskScore(score=80, rating="low", weighted_score=80,
                           sub_scores=[], applied_caps=[], recommendations=[]),
            crawl=CrawlResult(start_url="https://example.com/", pages=[],
                              privacy_policy_url=None, imprint_url=None),
            network=NetworkResult(requests=[], data_flow=[]),
            cookies=CookieReport(cookies=[], storage=[], summary={}),
            privacy_analysis=PrivacyAnalysis(
                provider="none", model=None, policy_url=None, summary="",
                issues=[], coverage=None, compliance_score=50,
                error="no_provider_configured",
            ),
            forms=FormReport(forms=[], summary={"total_forms": 0}),
            contact_channels=ContactChannelsReport(channels=[], summary={}),
            widgets=ThirdPartyWidgetsReport(widgets=[], summary={}),
        )
        for _ in range(5):
            await save_scan(fake, organization_id=org_id)

        # 6th request trips the quota.
        r_over = await app_with_db.post(
            "/scan",
            headers={"Authorization": f"Bearer {token}"},
            json={"url": "https://example.com/"},
        )
        assert r_over.status_code == 402

        r_metrics = await app_with_db.get("/metrics")
        assert 'scanner_quota_exceeded_total{plan="free"}' in r_metrics.text
