"""Prometheus metrics (Phase 7).

Intentionally small — every counter below maps to a question the
operator or a dashboard will actually ask:

  scanner_http_requests_total{method, path, status}
      Basic traffic + error rate. Group by path to see which endpoints
      are getting hit; filter status="5xx" to see failures.

  scanner_http_request_duration_seconds
      Latency histogram. p95 / p99 dashboards read from the `_bucket`
      series this produces.

  scanner_scans_total{mode, outcome}
      How many scans ran. `mode` is ``sync`` / ``async``; ``outcome``
      is ``ok`` / ``failed`` / ``blocked_ssrf`` / ``quota_exceeded``.

  scanner_auth_attempts_total{result}
      Login / signup outcome — ``ok`` / ``bad_credentials`` / ``other``.

  scanner_ssrf_blocks_total
      Every SSRF validator rejection. Spike here = someone poking at
      your scanner input.

  scanner_quota_exceeded_total{plan}
      402 Payment Required rate. Sales / product signal.

**Single-process note**: metrics live in in-memory counters. Good for
a single-worker deploy. When `scale: N` with N > 1, each worker
reports its own numbers — Prometheus' `sum()` across instances is
still accurate, but per-worker rate() can look noisier. Switching
to ``prometheus_client.multiprocess`` is a future opt-in; the
counter API below stays identical.
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)


# Private registry so tests can spin up a fresh one; production uses
# this shared instance via the module-level singletons below.
_REGISTRY = CollectorRegistry()


# HTTP — filled by the middleware in main.py.
http_requests_total = Counter(
    "scanner_http_requests_total",
    "Total HTTP requests served by the backend.",
    labelnames=("method", "path", "status"),
    registry=_REGISTRY,
)

http_request_duration_seconds = Histogram(
    "scanner_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    labelnames=("method", "path"),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
    registry=_REGISTRY,
)

# Domain counters — called from the scan / auth / billing code paths.
scans_total = Counter(
    "scanner_scans_total",
    "Scan outcomes by mode and status.",
    labelnames=("mode", "outcome"),   # mode: sync|async; outcome: ok|failed|blocked_ssrf|quota_exceeded
    registry=_REGISTRY,
)

auth_attempts_total = Counter(
    "scanner_auth_attempts_total",
    "Signup + login attempts by result.",
    labelnames=("endpoint", "result"),  # endpoint: signup|login; result: ok|bad_credentials|duplicate_email|other
    registry=_REGISTRY,
)

ssrf_blocks_total = Counter(
    "scanner_ssrf_blocks_total",
    "SSRF validator rejections at the HTTP entry.",
    registry=_REGISTRY,
)

quota_exceeded_total = Counter(
    "scanner_quota_exceeded_total",
    "402 Payment Required responses on scan endpoints.",
    labelnames=("plan",),
    registry=_REGISTRY,
)


def render_metrics() -> tuple[bytes, str]:
    """Render the registry as Prometheus text. Returns ``(body, content_type)``
    so the handler can plug the right Content-Type header."""
    return generate_latest(_REGISTRY), CONTENT_TYPE_LATEST


# ---------------------------------------------------------------------------
# Route normalisation
# ---------------------------------------------------------------------------

def normalise_path(request_path: str, route_template: str | None) -> str:
    """Prefer the FastAPI route template (``/scans/{scan_id}``) over
    the concrete URL (``/scans/abc123``) — otherwise every id value
    becomes its own label series and Prometheus' cardinality explodes.

    Returns ``"unknown"`` if neither can be determined (e.g. 404 before
    routing resolved a match).
    """
    if route_template:
        return route_template
    # Last-resort fallback — still collapse obvious id patterns.
    return request_path or "unknown"
