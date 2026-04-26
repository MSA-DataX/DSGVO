"""Linear, weighted, cap-free performance score (0-100).

Why linear weighting and not Lighthouse's log-normal curves
-----------------------------------------------------------

Lighthouse maps each Core Web Vital through its own log-normal CDF
fit to HTTP-Archive percentiles. That gives a "score 50 means median
of the web" semantic but is opaque to anyone reading the report — you
can't explain to a customer why LCP=2.6s scored 78 vs LCP=2.7s scoring
74. We optimise for **explainability over benchmark fidelity**: every
deduction is a flat point cost crossed at a documented threshold.
The score moves linearly with the metric, so "60 wegen LCP=3.4s and
14 uncompressed JS responses" is a single sentence the auditor can
parse without a manual.

Weight rationale
----------------

The breakdown below sums to **80 max deductions**, leaving 20 points of
headroom — a site that hits *every* threshold simultaneously still
shows 20/100, never 0. That preserves enough resolution that two
genuinely-bad sites can be distinguished from each other.

Bucket weights:

  - **Core Web Vitals (50 max deductions)** — the user-experience
    primary signal. LCP / CLS / INP carry equal weight because Google
    treats them equally for Search ranking.
  - **Network footprint (15 max deductions)** — render-blocking
    + total bytes. Capped per category so a single offender can't
    dominate.
  - **Asset audit (15 max deductions)** — concrete byte-shaving
    opportunities. Each finding category contributes up to 5 points.

All thresholds are documented as constants below. Move them in one
place; the breakdown dict labels stay stable so the dashboard renders
the same chart layout across releases.
"""

from __future__ import annotations

from app.models import PerformanceReport


# --- Core Web Vitals thresholds (Google "Good" / "Needs improvement" / "Poor")
#     https://web.dev/articles/vitals — values in milliseconds (CLS unitless)
_LCP_GOOD_MS = 2500.0
_LCP_POOR_MS = 4000.0
_LCP_MAX_DEDUCTION = 18

_INP_GOOD_MS = 200.0
_INP_POOR_MS = 500.0
_INP_MAX_DEDUCTION = 16

_CLS_GOOD = 0.1
_CLS_POOR = 0.25
_CLS_MAX_DEDUCTION = 16

# FCP and TTFB are supporting metrics — smaller weights.
_FCP_GOOD_MS = 1800.0
_FCP_POOR_MS = 3000.0
_FCP_MAX_DEDUCTION = 0   # informational only — no deduction; UI shows the value

_TTFB_GOOD_MS = 800.0
_TTFB_POOR_MS = 1800.0
_TTFB_MAX_DEDUCTION = 0  # informational only

# --- Network footprint
# 4 points per render-blocking resource (linear), capped at 8.
_RENDER_BLOCKING_POINTS_PER = 4
_RENDER_BLOCKING_MAX_DEDUCTION = 8

# Total transfer size: 1 point per 500 KB above 1.5 MB, capped at 7.
_TRANSFER_BUDGET_BYTES = int(1.5 * 1024 * 1024)
_TRANSFER_OVERAGE_STEP_BYTES = 500 * 1024
_TRANSFER_MAX_DEDUCTION = 7

# --- Asset audit
# 1 point per finding (linear), capped at 5 per category.
_ASSET_POINTS_PER_FINDING = 1
_ASSET_MAX_DEDUCTION_PER_CATEGORY = 5


def score_performance(report: PerformanceReport) -> tuple[int, dict[str, int]]:
    """Compute the performance score for a populated :class:`PerformanceReport`.

    Returns ``(score, breakdown)`` where ``breakdown`` maps each
    contributing factor to the points it deducted (always ≤ 0). The
    caller (audit orchestrator) assigns both back onto the report.

    The function does NOT mutate the input — staying a pure function
    keeps test setup trivial.
    """
    breakdown: dict[str, int] = {}

    # --- Core Web Vitals -----------------------------------------------------
    breakdown["lcp"] = -_linear_deduction(
        report.web_vitals.lcp_ms,
        good=_LCP_GOOD_MS, poor=_LCP_POOR_MS,
        max_deduction=_LCP_MAX_DEDUCTION,
    )
    breakdown["inp"] = -_linear_deduction(
        report.web_vitals.inp_ms,
        good=_INP_GOOD_MS, poor=_INP_POOR_MS,
        max_deduction=_INP_MAX_DEDUCTION,
    )
    breakdown["cls"] = -_linear_deduction(
        report.web_vitals.cls,
        good=_CLS_GOOD, poor=_CLS_POOR,
        max_deduction=_CLS_MAX_DEDUCTION,
    )
    if _FCP_MAX_DEDUCTION:
        breakdown["fcp"] = -_linear_deduction(
            report.web_vitals.fcp_ms,
            good=_FCP_GOOD_MS, poor=_FCP_POOR_MS,
            max_deduction=_FCP_MAX_DEDUCTION,
        )
    if _TTFB_MAX_DEDUCTION:
        breakdown["ttfb"] = -_linear_deduction(
            report.web_vitals.ttfb_ms,
            good=_TTFB_GOOD_MS, poor=_TTFB_POOR_MS,
            max_deduction=_TTFB_MAX_DEDUCTION,
        )

    # --- Network footprint ---------------------------------------------------
    rb_count = len(report.network_metrics.render_blocking)
    breakdown["render_blocking"] = -min(
        rb_count * _RENDER_BLOCKING_POINTS_PER,
        _RENDER_BLOCKING_MAX_DEDUCTION,
    )
    excess = max(0, report.network_metrics.total_transfer_bytes - _TRANSFER_BUDGET_BYTES)
    if excess > 0:
        steps = (excess + _TRANSFER_OVERAGE_STEP_BYTES - 1) // _TRANSFER_OVERAGE_STEP_BYTES
        breakdown["transfer_size"] = -min(int(steps), _TRANSFER_MAX_DEDUCTION)
    else:
        breakdown["transfer_size"] = 0

    # --- Asset audit ---------------------------------------------------------
    breakdown["oversized_images"] = -min(
        len(report.asset_audit.oversized_images) * _ASSET_POINTS_PER_FINDING,
        _ASSET_MAX_DEDUCTION_PER_CATEGORY,
    )
    breakdown["oversized_scripts"] = -min(
        len(report.asset_audit.oversized_scripts) * _ASSET_POINTS_PER_FINDING,
        _ASSET_MAX_DEDUCTION_PER_CATEGORY,
    )
    breakdown["uncompressed_responses"] = -min(
        len(report.asset_audit.uncompressed_responses) * _ASSET_POINTS_PER_FINDING,
        _ASSET_MAX_DEDUCTION_PER_CATEGORY,
    )

    # Drop zero-deduction entries so the dashboard renders only the
    # rows that actually contributed.
    breakdown = {k: v for k, v in breakdown.items() if v != 0}

    score = 100 + sum(breakdown.values())
    score = max(0, min(100, score))
    return score, breakdown


def _linear_deduction(
    value: float | None,
    *,
    good: float,
    poor: float,
    max_deduction: int,
) -> int:
    """Linearly interpolate ``value`` between ``good`` and ``poor`` thresholds.

    Returns the integer deduction in [0, max_deduction]. ``None`` → 0
    (we never deduct for missing metrics — the report shows them as
    "not measured" so the absence is visible).
    """
    if value is None or max_deduction <= 0:
        return 0
    if value <= good:
        return 0
    if value >= poor:
        return max_deduction
    # Linear interpolation between the two thresholds.
    fraction = (value - good) / (poor - good)
    return int(round(fraction * max_deduction))
