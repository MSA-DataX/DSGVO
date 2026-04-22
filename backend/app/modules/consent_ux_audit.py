"""Cookie-banner dark-pattern detector.

Runs during the consent-simulation warmup (before the accept click). For
each visible cookie banner we:

  1. locate the Accept button (via the same selectors consent_clicker uses)
  2. locate the Reject button (via new REJECT selectors + a loose text
     fallback)
  3. measure both elements in the DOM — size, position, opacity, font
     weight, background — via a single ``page.evaluate(...)`` round-trip
  4. apply deterministic rules mapping the measurements to DarkPattern
     findings ("reject is 35% the area of accept" → ``reject_much_smaller``
     MEDIUM)

Why deterministic + measured: the EDPB and German DSK guidance is
objective — "equally prominent" is the standard, not a vibe. Pixel
measurements give an auditor something falsifiable instead of "looks
suspicious to me". We deliberately don't use AI here; if we can't measure
something (e.g. animated reveal tricks), we say so rather than guess.
"""

from __future__ import annotations

import logging
from typing import Any

from playwright.async_api import ElementHandle, Page

from app.models import ConsentUxAudit, DarkPatternFinding
from app.modules.consent_clicker import (
    _ACCEPT_RE,
    _REJECT_RE,
    CMP_REJECT_SELECTORS,
    CMP_SELECTORS,
)


log = logging.getLogger("consent_ux_audit")


# ---------------------------------------------------------------------------
# Element discovery
# ---------------------------------------------------------------------------

async def _find_accept_button(page: Page) -> tuple[ElementHandle | None, str | None]:
    """Return (handle, cmp_name). cmp_name is the matched CMP or
    "text-fallback" when only the generic phrase heuristic matched."""
    for name, selector in CMP_SELECTORS:
        try:
            loc = page.locator(selector).first
            if await loc.is_visible(timeout=200):
                handle = await loc.element_handle()
                if handle is not None:
                    return handle, name
        except Exception:
            continue
    # text fallback
    try:
        loc = page.get_by_role("button", name=_ACCEPT_RE).first
        if await loc.is_visible(timeout=300):
            handle = await loc.element_handle()
            if handle is not None:
                return handle, "text-fallback"
    except Exception:
        pass
    return None, None


async def _find_reject_button(
    page: Page,
    matched_cmp: str | None,
) -> tuple[ElementHandle | None, bool]:
    """Return (handle, via_text_fallback).

    Strategy:
    - If we matched a named CMP for Accept, try the matching reject
      selector for that CMP first. It's almost certainly on the same
      banner level.
    - Otherwise walk all reject selectors (cheap, most fail fast).
    - Finally fall back to the multilingual text regex.
    """
    # 1) preferred CMP match
    if matched_cmp and matched_cmp != "text-fallback":
        for name, selector in CMP_REJECT_SELECTORS:
            if name != matched_cmp:
                continue
            try:
                loc = page.locator(selector).first
                if await loc.is_visible(timeout=200):
                    handle = await loc.element_handle()
                    if handle is not None:
                        return handle, False
            except Exception:
                pass

    # 2) try all reject selectors
    for _, selector in CMP_REJECT_SELECTORS:
        try:
            loc = page.locator(selector).first
            if await loc.is_visible(timeout=150):
                handle = await loc.element_handle()
                if handle is not None:
                    return handle, False
        except Exception:
            continue

    # 3) text fallback — less reliable, mark it so the UI shows lower confidence
    try:
        loc = page.get_by_role("button", name=_REJECT_RE).first
        if await loc.is_visible(timeout=300):
            handle = await loc.element_handle()
            if handle is not None:
                return handle, True
    except Exception:
        pass

    return None, False


# ---------------------------------------------------------------------------
# Measurement — single JS call for both buttons for efficiency
# ---------------------------------------------------------------------------

_MEASURE_JS = """
(el) => {
    if (!el) return null;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    // walk up the parent chain to find the first non-transparent background
    // so we approximate the *actual* visible background, not just the
    // button's own declared one (which is often "transparent" on borderless
    // text buttons).
    let bg = s.backgroundColor;
    let node = el.parentElement;
    while (node && (bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent')) {
        const ps = getComputedStyle(node);
        bg = ps.backgroundColor;
        node = node.parentElement;
        if (!node) break;
    }
    return {
        width: r.width,
        height: r.height,
        top: r.top,
        left: r.left,
        fontSize: parseFloat(s.fontSize) || 0,
        fontWeight: parseInt(s.fontWeight) || 400,
        opacity: parseFloat(s.opacity) || 1,
        color: s.color,
        backgroundColor: bg,
        hasOwnBackground: s.backgroundColor !== 'rgba(0, 0, 0, 0)' && s.backgroundColor !== 'transparent',
        hasBorder: s.borderStyle !== 'none' && parseFloat(s.borderWidth) > 0,
        visible: r.width > 0 && r.height > 0 && s.visibility !== 'hidden',
        text: (el.innerText || el.textContent || '').trim().slice(0, 80),
    };
}
"""


async def _measure(page: Page, handle: ElementHandle | None) -> dict[str, Any] | None:
    if handle is None:
        return None
    try:
        return await page.evaluate(_MEASURE_JS, handle)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Rules — translate measurements into DarkPatternFindings
# ---------------------------------------------------------------------------

def _analyze(
    accept: dict[str, Any] | None,
    reject: dict[str, Any] | None,
    reject_via_text_fallback: bool,
    viewport_height: int,
) -> list[DarkPatternFinding]:
    out: list[DarkPatternFinding] = []

    if accept is None:
        # Can't audit without the reference button. The caller sets
        # banner_detected=False and we return no findings.
        return out

    if reject is None:
        out.append(DarkPatternFinding(
            code="no_direct_reject",
            severity="high",
            description=(
                "No first-level 'Reject all' button detected on the consent banner. "
                "EDPB guidance (03/2022) and German DSK require that refusing consent "
                "is as easy as giving it — a single click, same level. A hidden 'Reject' "
                "inside 'Settings' is considered a dark pattern and the consent is "
                "therefore invalid under Art. 4(11) GDPR."
            ),
            evidence={"accept_text": accept.get("text", "")},
        ))
        return out

    # Size comparison — area ratio reject/accept
    a_area = float(accept["width"]) * float(accept["height"])
    r_area = float(reject["width"]) * float(reject["height"])
    if a_area > 0:
        ratio = r_area / a_area
        if ratio < 0.7:  # reject is < 70% of accept size
            severity = "high" if ratio < 0.4 else "medium"
            out.append(DarkPatternFinding(
                code="reject_much_smaller",
                severity=severity,
                description=(
                    f"The Reject button is only {int(ratio * 100)}% the visual size "
                    f"of the Accept button. Consent must be equally easy to refuse "
                    f"as to grant (EDPB Guidelines 03/2022)."
                ),
                evidence={
                    "accept_area_px": round(a_area, 1),
                    "reject_area_px": round(r_area, 1),
                    "ratio": round(ratio, 3),
                },
            ))

    # Below-the-fold check — if reject requires scrolling, it's not "equally easy".
    # Use the bottom of the element; we tolerate a small grace to avoid false
    # positives on banners that straddle the viewport edge.
    reject_bottom = float(reject["top"]) + float(reject["height"])
    if viewport_height > 0 and reject_bottom > viewport_height + 16:
        out.append(DarkPatternFinding(
            code="reject_below_fold",
            severity="medium",
            description=(
                "The Reject button is positioned below the initial viewport; the "
                "user must scroll to see it. Under EDPB 03/2022 this asymmetry "
                "makes the reject option less accessible than accept, a recognised "
                "dark-pattern category."
            ),
            evidence={
                "reject_bottom_px": round(reject_bottom, 1),
                "viewport_height_px": viewport_height,
            },
        ))

    # Prominence asymmetry — accept has solid bg / bolder weight, reject doesn't.
    # We flag only when BOTH signals align, to avoid false positives on sites
    # where both buttons share the same minimal styling.
    weaker_weight = int(reject["fontWeight"]) + 200 <= int(accept["fontWeight"])
    weaker_bg = bool(accept.get("hasOwnBackground")) and not bool(reject.get("hasOwnBackground"))
    lower_opacity = float(reject["opacity"]) + 0.15 < float(accept["opacity"])
    if sum([weaker_weight, weaker_bg, lower_opacity]) >= 2:
        out.append(DarkPatternFinding(
            code="reject_low_prominence",
            severity="medium",
            description=(
                "The Reject button is styled notably less prominently than Accept "
                "(weaker font weight, missing background, or lower opacity). "
                "Visual asymmetry steers the user toward consent and invalidates "
                "the 'freely given' requirement of Art. 4(11) GDPR."
            ),
            evidence={
                "accept_weight": int(accept["fontWeight"]),
                "reject_weight": int(reject["fontWeight"]),
                "accept_has_bg": bool(accept.get("hasOwnBackground")),
                "reject_has_bg": bool(reject.get("hasOwnBackground")),
                "accept_opacity": float(accept["opacity"]),
                "reject_opacity": float(reject["opacity"]),
            },
        ))

    # Confidence note — we matched the reject only via the loose text heuristic.
    # Not a violation per se, but worth surfacing because false positives for
    # the other rules are more likely when the wrong element was measured.
    if reject_via_text_fallback:
        out.append(DarkPatternFinding(
            code="reject_via_text_fallback",
            severity="low",
            description=(
                "The Reject button was matched only via a multilingual text "
                "heuristic (no known CMP selector fit). Measurements below have "
                "lower confidence — manually verify the banner layout."
            ),
            evidence={},
        ))

    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def audit_consent_ux(page: Page) -> ConsentUxAudit:
    """Audit the consent banner on ``page`` without clicking anything.

    Caller is responsible for calling this BEFORE try_click_consent so the
    banner is still in its initial state when we measure it.
    """
    # Give the banner a moment to render (same grace as the clicker).
    try:
        await page.wait_for_timeout(400)
    except Exception:
        pass

    accept_handle, cmp_name = await _find_accept_button(page)
    if accept_handle is None:
        return ConsentUxAudit(
            banner_detected=False,
            cmp=None,
            accept_found=False,
            reject_found=False,
        )

    reject_handle, via_text = await _find_reject_button(page, cmp_name)

    # Single-round measurement for both buttons
    accept_metrics = await _measure(page, accept_handle)
    reject_metrics = await _measure(page, reject_handle) if reject_handle else None

    # viewport height (for the below-the-fold check)
    viewport = page.viewport_size or {"height": 720}
    vh = int(viewport.get("height", 720))

    findings = _analyze(
        accept=accept_metrics,
        reject=reject_metrics,
        reject_via_text_fallback=via_text,
        viewport_height=vh,
    )

    return ConsentUxAudit(
        banner_detected=True,
        cmp=cmp_name,
        accept_found=accept_handle is not None,
        reject_found=reject_handle is not None,
        reject_via_text_fallback=via_text,
        findings=findings,
        accept_metrics=accept_metrics,
        reject_metrics=reject_metrics,
    )
