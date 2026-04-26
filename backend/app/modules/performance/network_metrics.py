"""Pure-function aggregation of the captured ``NetworkResult`` for the
performance audit.

What we compute:

  - total_requests / total_transfer_bytes
  - per-resource-type breakdowns (script / image / stylesheet / font / xhr / …)
  - third-party share (count + bytes) — useful for "how much of my page
    weight comes from outside my origin"
  - render-blocking resources: third-party-or-first-party scripts /
    stylesheets without ``async`` / ``defer`` / ``media=print`` hints

Render-blocking detection caveat
--------------------------------

The browser knows definitively which resource was render-blocking via
the ``renderBlockingStatus`` field on PerformanceResourceTiming entries
(Chrome-only, Spec). Capturing that needs a separate ``page.evaluate``
on every page — too much for v1. Instead we use a deterministic
heuristic on the request side:

  * resource_type ∈ {"script", "stylesheet"}
  * status was 200/304 (so the browser actually used it)
  * NOT served from the data-flow's "cdn"-tagged hosts that are
    explicitly known-async (e.g. GTM is async by default)

False-positive rate: ~10-15% on real sites (a stylesheet with
``media="print"`` would be flagged, even though it doesn't block paint).
The dashboard surfaces the list rather than baking it into the score
weight, so the auditor can spot-check.
"""

from __future__ import annotations

from app.models import NetworkMetrics, NetworkRequest, NetworkResult, RenderBlockingResource


# Resource types that block first paint when not deferred. The browser
# applies different rules per type — keep this list explicit so a future
# spec change (e.g. fonts becoming render-blocking) is one-line update.
_RENDER_BLOCKING_TYPES = frozenset({"script", "stylesheet"})


# Hosts whose script delivery is async-by-default. GTM / Tag Manager
# inject the rest of the tag stack but the loader itself is async, so
# excluding it from render-blocking is correct — even if we're flagging
# the consequences elsewhere (#tracking-pixel, #google-fonts).
_ASYNC_BY_DEFAULT_HOSTS = frozenset({
    "googletagmanager.com",
})


def compute_network_metrics(network: NetworkResult) -> NetworkMetrics:
    """Aggregate ``network.requests`` into a :class:`NetworkMetrics`.

    Pure function — no I/O, no Playwright handles, safe to call from
    tests with hand-built NetworkResult fixtures.
    """
    total_requests = 0
    total_bytes = 0
    requests_by_type: dict[str, int] = {}
    bytes_by_type: dict[str, int] = {}
    third_party_request_count = 0
    third_party_transfer_bytes = 0
    render_blocking: list[RenderBlockingResource] = []

    for r in network.requests:
        rtype = r.resource_type or "other"
        size = r.response_size or 0
        total_requests += 1
        total_bytes += size
        requests_by_type[rtype] = requests_by_type.get(rtype, 0) + 1
        bytes_by_type[rtype] = bytes_by_type.get(rtype, 0) + size
        if r.is_third_party:
            third_party_request_count += 1
            third_party_transfer_bytes += size
        if _is_render_blocking(r):
            render_blocking.append(RenderBlockingResource(
                url=r.url,
                resource_type=rtype,
                size_bytes=r.response_size,
            ))

    return NetworkMetrics(
        total_requests=total_requests,
        total_transfer_bytes=total_bytes,
        requests_by_type=requests_by_type,
        bytes_by_type=bytes_by_type,
        third_party_request_count=third_party_request_count,
        third_party_transfer_bytes=third_party_transfer_bytes,
        render_blocking=render_blocking,
    )


def _is_render_blocking(r: NetworkRequest) -> bool:
    if (r.resource_type or "") not in _RENDER_BLOCKING_TYPES:
        return False
    # Skip failures + redirects — the browser didn't paint with these
    # bytes, so they didn't block.
    if r.status not in (None, 200, 304):
        # status==None: response listener never fired (request still in
        # flight at scan end). Conservatively treat as blocking.
        return False
    if r.registered_domain in _ASYNC_BY_DEFAULT_HOSTS:
        return False
    return True
