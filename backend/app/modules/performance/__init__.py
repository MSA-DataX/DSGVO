"""Phase 11 performance suite.

Three sub-modules, deliberately separate from the GDPR scoring path:

* :mod:`web_vitals` — collects Core Web Vitals + supporting paint metrics
  by injecting a small ``PerformanceObserver`` snippet into the page and
  reading the harvested values via ``page.evaluate(...)``.
* :mod:`network_metrics` — pure function over a captured
  :class:`NetworkResult`. Aggregates total bytes / requests / type
  breakdown and detects render-blocking resources.
* :mod:`asset_audit` — pure function. Flags oversized images, oversized
  scripts, and uncompressed text responses.

The orchestrator :func:`run_performance_audit` ties them together and
returns a :class:`PerformanceReport`. Score is 0-100 linear, no caps —
see :mod:`scoring`.
"""

from app.modules.performance.audit import run_performance_audit
from app.modules.performance.scoring import score_performance

__all__ = ["run_performance_audit", "score_performance"]
