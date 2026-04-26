"""Top-level orchestrator for the Phase-11 performance audit.

Combines the three pure analysers + the WebVitals collector + the
linear scoring function into one async entry point that the scanner
can call once.

Contract: never raises into the scanner. A failure in any sub-step
produces a partial :class:`PerformanceReport` with ``error`` populated;
the GDPR audit path is unaffected.
"""

from __future__ import annotations

import logging

from app.models import NetworkResult, PerformanceReport, WebVitals
from app.modules.performance.asset_audit import audit_assets
from app.modules.performance.network_metrics import compute_network_metrics
from app.modules.performance.scoring import score_performance

log = logging.getLogger(__name__)


def run_performance_audit(
    network: NetworkResult,
    web_vitals: WebVitals | None = None,
) -> PerformanceReport:
    """Build a :class:`PerformanceReport` from the captured network +
    optional web vitals.

    The web-vitals collection is async + needs an open Playwright Page;
    the scanner harvests it inline and passes the result here. When
    ``web_vitals`` is None (collection failed or was skipped), the
    network + asset analyses still run and the report carries an
    empty :class:`WebVitals`.
    """
    try:
        report = PerformanceReport(
            web_vitals=web_vitals or WebVitals(),
            network_metrics=compute_network_metrics(network),
            asset_audit=audit_assets(network),
        )
        score, breakdown = score_performance(report)
        report.score = score
        report.score_breakdown = breakdown
        return report
    except Exception as exc:
        # Never let performance issues kill a GDPR scan. Surface the
        # failure on the report so the dashboard can show "performance
        # audit failed" instead of silently dropping the section.
        log.exception("performance audit failed")
        return PerformanceReport(error=f"{type(exc).__name__}: {exc}")
