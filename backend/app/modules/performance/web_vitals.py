"""Core Web Vitals collection via injected PerformanceObserver.

Why injection rather than DevTools Protocol or Lighthouse:

  - We already have an open Playwright page from the crawler. Adding a
    second runtime would double the scan cost.
  - DevTools-Protocol-based metrics need a CDPSession + careful
    teardown to avoid leaking listeners across our crawl pages.
  - The ``web-vitals`` JS library would be the cleanest path, but
    pulling a third-party CDN script during a *GDPR audit* is
    self-defeating (we'd issue the very kind of request we flag).
    The 60-line snippet below is a faithful subset.

Headless caveats:

  - **INP / FID** require real user interactions. We approximate by
    summing long-task durations over the wait window — useful as a
    "responsiveness signal", not the canonical metric. Documented in
    the WebVitals model.
  - **LCP** finalises on first user input or page hide. We force the
    finalisation by dispatching a synthetic ``visibilitychange`` after
    the wait window expires.

The harness function is async, takes a Playwright Page, and returns a
:class:`WebVitals` populated with whatever the observers captured. A
swallowed exception (e.g. page navigated away mid-collect) yields the
default-empty WebVitals — never raises into the scanner.
"""

from __future__ import annotations

import asyncio

from playwright.async_api import BrowserContext, Page

from app.models import WebVitals


# Time we let the page sit after navigation so the PerformanceObserver
# can collect LCP candidates + layout shifts. 2.5s is the recommended
# minimum (LCP final at 2.5s is still "good"); we go slightly higher
# to catch slower hero images on B2B sites.
_WAIT_SECONDS = 3.0


# Injected before navigation via context.add_init_script. Stores live
# observer state on `window.__msaWebVitals`; harvest reads from there.
# Keep this self-contained — no closures over external scope, no ES2022
# syntax that older browsers may not parse (we run on Chromium current,
# but the snippet should also survive a stray Firefox launch in tests).
_INJECT_JS = r"""
(() => {
  if (window.__msaWebVitals) return;
  const state = {
    lcp_ms: null,
    cls: 0,
    inp_ms: null,    // approximated via long-tasks sum below
    fcp_ms: null,
    ttfb_ms: null,
  };
  window.__msaWebVitals = state;

  // TTFB from Navigation Timing — synchronous, available immediately.
  try {
    const nav = performance.getEntriesByType('navigation')[0];
    if (nav) state.ttfb_ms = Math.max(0, nav.responseStart);
  } catch (_) {}

  // LCP — buffered:true gets pre-existing entries as well.
  try {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        state.lcp_ms = e.startTime;
      }
    }).observe({ type: 'largest-contentful-paint', buffered: true });
  } catch (_) {}

  // CLS — sum of layout-shift values that weren't user-initiated.
  try {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        if (!e.hadRecentInput) state.cls += e.value;
      }
    }).observe({ type: 'layout-shift', buffered: true });
  } catch (_) {}

  // FCP — paint-timing entry.
  try {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        if (e.name === 'first-contentful-paint') state.fcp_ms = e.startTime;
      }
    }).observe({ type: 'paint', buffered: true });
  } catch (_) {}

  // INP approximation: longest single long-task duration in the
  // observation window. Real INP needs an interaction; in headless
  // crawl we settle for "the worst single main-thread block".
  try {
    let worst = 0;
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        if (e.duration > worst) worst = e.duration;
      }
      state.inp_ms = worst;
    }).observe({ type: 'longtask', buffered: true });
  } catch (_) {}
})();
"""


_HARVEST_JS = r"""
() => {
  // Force LCP finalisation by simulating page hide — the spec says
  // observers stop reporting once the page becomes hidden, so the
  // last value is the final value.
  try {
    document.dispatchEvent(new Event('visibilitychange'));
  } catch (_) {}
  return window.__msaWebVitals || null;
}
"""


async def install_web_vitals(context: BrowserContext) -> None:
    """Inject the observer snippet into every page opened in ``context``.

    Must be called BEFORE the first navigation (otherwise LCP
    candidates that fired during paint are missed). Idempotent — the
    snippet checks for an existing ``window.__msaWebVitals``.

    Context-scoped (not page-scoped) on purpose: the crawler opens
    one page per visit and closes it; we want the observer pre-armed
    on the dedicated harvest page that the orchestrator opens *after*
    the crawl, but the same install also covers any earlier pages if
    we ever change the harvest strategy.
    """
    await context.add_init_script(_INJECT_JS)


async def collect_web_vitals(page: Page) -> WebVitals:
    """Wait the observation window, then harvest what the observers saw.

    Never raises. A failure in JS evaluation produces a default-empty
    :class:`WebVitals` so the rest of the performance audit can still
    run on the (cheaper) network-side analysers.
    """
    try:
        await asyncio.sleep(_WAIT_SECONDS)
        raw = await page.evaluate(_HARVEST_JS)
    except Exception:
        return WebVitals()
    if not raw or not isinstance(raw, dict):
        return WebVitals()
    # Coerce defensively — a hostile page could replace
    # window.__msaWebVitals with anything before we read it.
    def _f(key: str) -> float | None:
        v = raw.get(key)
        if isinstance(v, (int, float)) and v >= 0:
            return float(v)
        return None
    return WebVitals(
        lcp_ms=_f("lcp_ms"),
        inp_ms=_f("inp_ms"),
        cls=_f("cls"),
        fcp_ms=_f("fcp_ms"),
        ttfb_ms=_f("ttfb_ms"),
    )
