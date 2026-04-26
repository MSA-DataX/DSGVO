"""Pure-function asset audit — flags concrete byte-shaving opportunities.

Three findings, all derived from the captured ``NetworkResult``:

  - **Oversized images**: image responses larger than 500 KB. Real-world
    fix is usually a smaller srcset variant, AVIF/WebP encode, or
    server-side resize for the actually-rendered viewport.
  - **Oversized scripts**: JS responses larger than 500 KB. Fix is
    code-splitting / dynamic import / dropping a no-longer-used dep.
  - **Uncompressed responses**: text-shaped resources (script /
    stylesheet / document / xhr / fetch) without
    ``Content-Encoding: gzip|br|deflate``. Single-line server-config fix
    that typically halves transfer bytes.

Threshold rationale
-------------------

500 KB is conservative — the Lighthouse default flags from 100 KB but
that's noisy on real B2B sites (a single hero image at 200 KB often
isn't actionable). 500 KB picks the assets that move the page-weight
needle and are realistically reducible.

Skip rules
----------

  * ``response_size`` is None → skip. The Content-Length header may
    not have been present (HTTP/2 server push, chunked transfer); we
    can't make a finding without a size to quote.
  * Status not 200/304 → skip. A 404 doesn't get bytes onto the page.
  * ``content_encoding`` already in {gzip, br, deflate, zstd} →
    compressed; nothing to flag.
"""

from __future__ import annotations

from app.models import (
    AssetAudit,
    NetworkRequest,
    NetworkResult,
    OversizedAsset,
    UncompressedResponse,
)


# Per-type byte budget. Crossed → finding.
_IMAGE_BUDGET_BYTES = 500 * 1024
_SCRIPT_BUDGET_BYTES = 500 * 1024


# Resource types where compression should ALWAYS be on. Excludes
# binary types (images, fonts, video, media) — those are already
# self-compressed and re-running gzip on them costs CPU for ~0% gain.
_COMPRESSIBLE_TYPES = frozenset({"script", "stylesheet", "document", "xhr", "fetch"})


# Encoding tokens we treat as "compressed". Verbatim header values from
# Playwright; lowercase comparison.
_COMPRESSED_TOKENS = frozenset({"gzip", "br", "deflate", "zstd"})


# Cap each finding list at 25 entries — enough for the auditor to see
# the pattern without dragging the dashboard payload past a sensible
# size. The page typically only has a handful of offenders worth
# flagging anyway.
_MAX_FINDINGS_PER_LIST = 25


def audit_assets(network: NetworkResult) -> AssetAudit:
    """Walk ``network.requests`` and flag byte-shaving opportunities.

    Pure function. Every output entry references a real captured
    request — no synthesis, no estimation.
    """
    oversized_images: list[OversizedAsset] = []
    oversized_scripts: list[OversizedAsset] = []
    uncompressed_responses: list[UncompressedResponse] = []

    for r in network.requests:
        if not _used_by_browser(r):
            continue
        rtype = r.resource_type or "other"
        size = r.response_size
        if size is None:
            continue

        if rtype == "image" and size > _IMAGE_BUDGET_BYTES:
            if len(oversized_images) < _MAX_FINDINGS_PER_LIST:
                oversized_images.append(OversizedAsset(
                    url=r.url, resource_type=rtype,
                    size_bytes=size,
                    threshold_bytes=_IMAGE_BUDGET_BYTES,
                ))
        elif rtype == "script" and size > _SCRIPT_BUDGET_BYTES:
            if len(oversized_scripts) < _MAX_FINDINGS_PER_LIST:
                oversized_scripts.append(OversizedAsset(
                    url=r.url, resource_type=rtype,
                    size_bytes=size,
                    threshold_bytes=_SCRIPT_BUDGET_BYTES,
                ))

        if rtype in _COMPRESSIBLE_TYPES and not _is_compressed(r.content_encoding):
            # Tiny responses aren't worth flagging — gzip overhead
            # exceeds the saving below ~1 KB.
            if size >= 1024 and len(uncompressed_responses) < _MAX_FINDINGS_PER_LIST:
                uncompressed_responses.append(UncompressedResponse(
                    url=r.url, resource_type=rtype,
                    size_bytes=size,
                    content_encoding=r.content_encoding,
                ))

    # Sort each list by size descending so the worst offenders surface
    # first in the dashboard — auditor scans top-to-bottom.
    oversized_images.sort(key=lambda a: a.size_bytes, reverse=True)
    oversized_scripts.sort(key=lambda a: a.size_bytes, reverse=True)
    uncompressed_responses.sort(key=lambda a: a.size_bytes, reverse=True)

    return AssetAudit(
        oversized_images=oversized_images,
        oversized_scripts=oversized_scripts,
        uncompressed_responses=uncompressed_responses,
    )


def _used_by_browser(r: NetworkRequest) -> bool:
    return r.status in (200, 304)


def _is_compressed(encoding: str | None) -> bool:
    if not encoding:
        return False
    # Header may be a comma-list (rare but spec-allowed) — match any token.
    tokens = {t.strip().lower() for t in encoding.split(",")}
    return bool(tokens & _COMPRESSED_TOKENS)
