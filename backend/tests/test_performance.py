"""Tests for the Phase-11 performance suite.

Three pure-function units (no Playwright, no I/O) plus the
end-to-end orchestrator + scoring integration.

The web_vitals collector is NOT covered here — it would require
a real Playwright page or a heavy mock; the value is in the JS
snippet which is best validated by an integration scan against a
real site. Documented as a known gap.
"""

from __future__ import annotations

from app.models import (
    AssetAudit,
    NetworkMetrics,
    NetworkRequest,
    NetworkResult,
    PerformanceReport,
    WebVitals,
)
from app.modules.performance.asset_audit import audit_assets
from app.modules.performance.audit import run_performance_audit
from app.modules.performance.network_metrics import compute_network_metrics
from app.modules.performance.scoring import score_performance


# ---------------------------------------------------------------------------
# helpers — small builders so each test reads as the scenario it covers
# ---------------------------------------------------------------------------

def _req(
    url: str = "https://example.com/asset",
    *,
    resource_type: str = "script",
    status: int | None = 200,
    is_third_party: bool = False,
    response_size: int | None = None,
    content_encoding: str | None = None,
    registered_domain: str | None = None,
) -> NetworkRequest:
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    parts = host.split(".")
    rd = registered_domain or (".".join(parts[-2:]) if len(parts) >= 2 else host)
    return NetworkRequest(
        url=url, domain=host, registered_domain=rd,
        method="GET", resource_type=resource_type, status=status,
        initiator_page="https://example.com/", is_third_party=is_third_party,
        response_size=response_size, content_encoding=content_encoding,
    )


def _net(*requests: NetworkRequest) -> NetworkResult:
    return NetworkResult(requests=list(requests), data_flow=[])


# ---------------------------------------------------------------------------
# compute_network_metrics
# ---------------------------------------------------------------------------

class TestNetworkMetrics:
    def test_empty_network(self):
        m = compute_network_metrics(_net())
        assert m.total_requests == 0
        assert m.total_transfer_bytes == 0
        assert m.requests_by_type == {}
        assert m.render_blocking == []

    def test_aggregates_by_type(self):
        m = compute_network_metrics(_net(
            _req("https://example.com/a.js", resource_type="script", response_size=1000),
            _req("https://example.com/b.js", resource_type="script", response_size=2000),
            _req("https://example.com/img.png", resource_type="image", response_size=500),
        ))
        assert m.total_requests == 3
        assert m.total_transfer_bytes == 3500
        assert m.requests_by_type == {"script": 2, "image": 1}
        assert m.bytes_by_type == {"script": 3000, "image": 500}

    def test_third_party_counted_separately(self):
        m = compute_network_metrics(_net(
            _req("https://example.com/own.js", is_third_party=False, response_size=1000),
            _req("https://cdn.foo.com/lib.js", is_third_party=True, response_size=5000),
            _req("https://cdn.foo.com/x.js", is_third_party=True, response_size=2000),
        ))
        assert m.third_party_request_count == 2
        assert m.third_party_transfer_bytes == 7000

    def test_render_blocking_script_in_head_no_async(self):
        # Synchronous third-party script — render-blocking by default.
        m = compute_network_metrics(_net(
            _req("https://cdn.foo.com/sync.js", resource_type="script",
                 status=200, is_third_party=True, response_size=8000),
        ))
        assert len(m.render_blocking) == 1
        assert m.render_blocking[0].url == "https://cdn.foo.com/sync.js"

    def test_image_not_render_blocking(self):
        m = compute_network_metrics(_net(
            _req("https://example.com/hero.jpg", resource_type="image",
                 status=200, response_size=80_000),
        ))
        assert m.render_blocking == []

    def test_failed_request_not_render_blocking(self):
        # 4xx/5xx didn't actually paint — don't count as blocking.
        m = compute_network_metrics(_net(
            _req("https://cdn.foo.com/missing.js", resource_type="script",
                 status=404, response_size=0),
        ))
        assert m.render_blocking == []

    def test_async_by_default_host_excluded(self):
        # GTM is async-by-default — skipped from render-blocking even
        # though it's a third-party script.
        m = compute_network_metrics(_net(
            _req("https://www.googletagmanager.com/gtm.js",
                 resource_type="script", status=200,
                 is_third_party=True, response_size=50_000,
                 registered_domain="googletagmanager.com"),
        ))
        assert m.render_blocking == []


# ---------------------------------------------------------------------------
# audit_assets
# ---------------------------------------------------------------------------

class TestAssetAudit:
    def test_empty_network(self):
        a = audit_assets(_net())
        assert a.oversized_images == []
        assert a.oversized_scripts == []
        assert a.uncompressed_responses == []

    def test_oversized_image_flagged(self):
        a = audit_assets(_net(
            _req("https://example.com/huge.jpg", resource_type="image",
                 response_size=2_000_000),
        ))
        assert len(a.oversized_images) == 1
        assert a.oversized_images[0].size_bytes == 2_000_000
        assert a.oversized_images[0].threshold_bytes == 500 * 1024

    def test_under_threshold_image_not_flagged(self):
        a = audit_assets(_net(
            _req("https://example.com/ok.jpg", resource_type="image",
                 response_size=400_000),
        ))
        assert a.oversized_images == []

    def test_oversized_script_flagged(self):
        a = audit_assets(_net(
            _req("https://example.com/bundle.js", resource_type="script",
                 response_size=900_000),
        ))
        assert len(a.oversized_scripts) == 1

    def test_uncompressed_text_response_flagged(self):
        # Script of decent size with no Content-Encoding header → flag.
        a = audit_assets(_net(
            _req("https://example.com/app.js", resource_type="script",
                 response_size=10_000, content_encoding=None),
        ))
        assert len(a.uncompressed_responses) == 1
        assert a.uncompressed_responses[0].content_encoding is None

    def test_compressed_response_not_flagged(self):
        a = audit_assets(_net(
            _req("https://example.com/app.js", resource_type="script",
                 response_size=10_000, content_encoding="br"),
            _req("https://example.com/style.css", resource_type="stylesheet",
                 response_size=10_000, content_encoding="gzip"),
        ))
        assert a.uncompressed_responses == []

    def test_tiny_response_not_flagged_for_compression(self):
        # Sub-1KB responses don't benefit from compression — no finding.
        a = audit_assets(_net(
            _req("https://example.com/tiny.js", resource_type="script",
                 response_size=500, content_encoding=None),
        ))
        assert a.uncompressed_responses == []

    def test_image_compression_not_flagged(self):
        # Already-compressed binary types skip the encoding check.
        a = audit_assets(_net(
            _req("https://example.com/photo.jpg", resource_type="image",
                 response_size=200_000, content_encoding=None),
        ))
        assert a.uncompressed_responses == []

    def test_findings_sorted_by_size_desc(self):
        a = audit_assets(_net(
            _req("https://example.com/small.jpg", resource_type="image",
                 response_size=600_000),
            _req("https://example.com/huge.jpg", resource_type="image",
                 response_size=3_000_000),
            _req("https://example.com/medium.jpg", resource_type="image",
                 response_size=1_500_000),
        ))
        sizes = [f.size_bytes for f in a.oversized_images]
        assert sizes == [3_000_000, 1_500_000, 600_000]

    def test_response_size_none_is_skipped(self):
        # Missing Content-Length → can't make any finding about this asset.
        a = audit_assets(_net(
            _req("https://example.com/unknown.js", resource_type="script",
                 response_size=None, content_encoding=None),
        ))
        assert a.oversized_scripts == []
        assert a.uncompressed_responses == []

    def test_failed_request_skipped(self):
        # 404 didn't get bytes onto the page — don't make findings.
        a = audit_assets(_net(
            _req("https://example.com/big.jpg", resource_type="image",
                 status=404, response_size=2_000_000),
        ))
        assert a.oversized_images == []


# ---------------------------------------------------------------------------
# score_performance — linear, weighted, traceable
# ---------------------------------------------------------------------------

class TestScorePerformance:
    def test_perfect_report_scores_100(self):
        report = PerformanceReport()
        score, breakdown = score_performance(report)
        assert score == 100
        assert breakdown == {}

    def test_lcp_at_good_threshold_no_deduction(self):
        report = PerformanceReport(web_vitals=WebVitals(lcp_ms=2500.0))
        score, breakdown = score_performance(report)
        assert score == 100
        assert "lcp" not in breakdown

    def test_lcp_at_poor_threshold_max_deduction(self):
        report = PerformanceReport(web_vitals=WebVitals(lcp_ms=4000.0))
        score, breakdown = score_performance(report)
        # _LCP_MAX_DEDUCTION = 18
        assert breakdown["lcp"] == -18
        assert score == 100 - 18

    def test_lcp_midpoint_linear_interpolation(self):
        # midpoint between 2500 and 4000 → half the max deduction.
        report = PerformanceReport(web_vitals=WebVitals(lcp_ms=3250.0))
        score, breakdown = score_performance(report)
        assert breakdown["lcp"] == -9     # round(0.5 * 18)

    def test_cls_poor_max_deduction(self):
        report = PerformanceReport(web_vitals=WebVitals(cls=0.25))
        score, breakdown = score_performance(report)
        assert breakdown["cls"] == -16

    def test_render_blocking_capped(self):
        # 5 render-blocking resources × 4 pts = 20, capped at 8.
        from app.models import RenderBlockingResource
        report = PerformanceReport(network_metrics=NetworkMetrics(
            render_blocking=[
                RenderBlockingResource(url=f"u{i}", resource_type="script")
                for i in range(5)
            ],
        ))
        score, breakdown = score_performance(report)
        assert breakdown["render_blocking"] == -8

    def test_transfer_size_under_budget_no_deduction(self):
        report = PerformanceReport(network_metrics=NetworkMetrics(
            total_transfer_bytes=1_000_000,    # under 1.5 MB
        ))
        score, breakdown = score_performance(report)
        assert "transfer_size" not in breakdown

    def test_transfer_size_over_budget_linear(self):
        # 1.5MB budget + 700KB extra → 2 steps of 500KB → -2 points.
        report = PerformanceReport(network_metrics=NetworkMetrics(
            total_transfer_bytes=int(1.5 * 1024 * 1024) + 700 * 1024,
        ))
        score, breakdown = score_performance(report)
        assert breakdown["transfer_size"] == -2

    def test_asset_findings_per_category_capped(self):
        from app.models import OversizedAsset, UncompressedResponse
        report = PerformanceReport(asset_audit=AssetAudit(
            oversized_images=[
                OversizedAsset(url=f"img{i}", resource_type="image",
                               size_bytes=600_000, threshold_bytes=500_000)
                for i in range(10)
            ],
            uncompressed_responses=[
                UncompressedResponse(url=f"js{i}", resource_type="script",
                                     size_bytes=10_000, content_encoding=None)
                for i in range(10)
            ],
        ))
        score, breakdown = score_performance(report)
        assert breakdown["oversized_images"] == -5
        assert breakdown["uncompressed_responses"] == -5

    def test_score_never_below_zero_or_above_hundred(self):
        # Worst-case stack — every single deduction maxed out at once.
        from app.models import OversizedAsset, RenderBlockingResource, UncompressedResponse
        report = PerformanceReport(
            web_vitals=WebVitals(lcp_ms=10_000, inp_ms=5_000, cls=2.0),
            network_metrics=NetworkMetrics(
                total_transfer_bytes=100 * 1024 * 1024,
                render_blocking=[
                    RenderBlockingResource(url=f"u{i}", resource_type="script")
                    for i in range(20)
                ],
            ),
            asset_audit=AssetAudit(
                oversized_images=[
                    OversizedAsset(url=f"i{i}", resource_type="image",
                                   size_bytes=10_000_000, threshold_bytes=500_000)
                    for i in range(10)
                ],
                oversized_scripts=[
                    OversizedAsset(url=f"s{i}", resource_type="script",
                                   size_bytes=2_000_000, threshold_bytes=500_000)
                    for i in range(10)
                ],
                uncompressed_responses=[
                    UncompressedResponse(url=f"u{i}", resource_type="script",
                                         size_bytes=10_000, content_encoding=None)
                    for i in range(10)
                ],
            ),
        )
        score, breakdown = score_performance(report)
        # 18 + 16 + 16 + 8 + 7 + 5 + 5 + 5 = 80 max deductions → score 20.
        assert score == 20
        assert sum(breakdown.values()) == -80


# ---------------------------------------------------------------------------
# run_performance_audit (orchestrator)
# ---------------------------------------------------------------------------

class TestPerformanceOrchestrator:
    def test_default_perfect_report(self):
        report = run_performance_audit(_net())
        assert report.score == 100
        assert report.score_breakdown == {}
        assert report.error is None
        assert report.web_vitals.lcp_ms is None

    def test_real_world_mid_score(self):
        # LCP slightly poor + some render-blocking + some oversize → mid-60s.
        net = _net(
            _req("https://example.com/sync.js", resource_type="script",
                 status=200, is_third_party=True, response_size=120_000),
            _req("https://example.com/style.css", resource_type="stylesheet",
                 status=200, response_size=20_000, content_encoding=None),
            _req("https://example.com/hero.jpg", resource_type="image",
                 status=200, response_size=1_500_000),
        )
        vitals = WebVitals(lcp_ms=3500.0, cls=0.18)
        report = run_performance_audit(net, vitals)
        assert 30 <= report.score <= 80
        assert "lcp" in report.score_breakdown
        assert "cls" in report.score_breakdown
        assert "uncompressed_responses" in report.score_breakdown
        assert "oversized_images" in report.score_breakdown

    def test_web_vitals_none_falls_back_to_default(self):
        # Network-only audit with no web vitals at all — score still
        # computes against the network/asset signals.
        net = _net(
            _req("https://example.com/huge.jpg", resource_type="image",
                 response_size=10_000_000),
        )
        report = run_performance_audit(net, web_vitals=None)
        assert report.score < 100
        assert report.web_vitals.lcp_ms is None
        assert report.error is None
