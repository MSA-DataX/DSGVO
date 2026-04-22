"""Detect and click cookie-banner "Accept all" buttons.

Used by the second scan pass when consent simulation is enabled. Two-stage
detection:

  1. Try a curated list of selectors for the well-known CMPs (OneTrust,
     Cookiebot, Usercentrics, Borlabs, Klaro, Cookieyes, Iubenda, Didomi,
     Sourcepoint, Complianz, Osano, …). These are the cheapest and most
     reliable when they match.
  2. Fall back to a multilingual text-based heuristic: any visible button
     whose accessible name contains a known "accept" phrase.

Why so many selectors: a "generic accept" heuristic alone clicks the wrong
thing on plenty of sites (newsletter signups, age gates). Naming the CMP
also lets the report show *which* banner was bypassed, which is useful for
auditors.

This module is intentionally tolerant of failure — most ``try`` blocks
swallow exceptions because a missing selector should never abort a scan.
The return value tells the caller whether a click actually landed.
"""

from __future__ import annotations

import re

from playwright.async_api import Page


# (CMP display name, CSS selector for "Accept all" / "Allow all")
CMP_SELECTORS: list[tuple[str, str]] = [
    ("OneTrust",          "#onetrust-accept-btn-handler"),
    ("Cookiebot",         "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll"),
    ("Cookiebot (legacy)","#CybotCookiebotDialogBodyButtonAccept"),
    ("Usercentrics",      "[data-testid='uc-accept-all-button']"),
    ("Usercentrics v2",   "button[mode='primary'][aria-label*='Accept' i]"),
    ("Borlabs Cookie",    "a.brlbs-btn-accept-all, ._brlbs-btn-accept-all"),
    ("Klaro",             ".cm-btn-accept-all, .cm-btn-accept"),
    ("CookieScript",      "#cookiescript_accept"),
    ("CookieYes",         "#cky-btn-accept, .cky-btn-accept"),
    ("Iubenda",           ".iubenda-cs-accept-btn"),
    ("Quantcast",         "button.qc-cmp2-summary-buttons[mode='primary']"),
    ("Didomi",            "#didomi-notice-agree-button"),
    ("Sourcepoint",       ".sp_choice_type_11, button[title='Accept All']"),
    ("Complianz",         ".cmplz-btn.cmplz-accept, button.cmplz-accept"),
    ("Osano",             ".osano-cm-accept-all, button.osano-cm-accept-all"),
    ("WP Cookie Notice",  "#cn-accept-cookie"),
    ("Tarteaucitron",     "#tarteaucitronPersonalize2, button#tarteaucitronAllAllowed2"),
    ("HubSpot",           "#hs-eu-confirmation-button"),
    ("TrustArc",          "#truste-consent-button"),
    ("Mediavine",         "button[data-testid='mediavine-gdpr-cmp-accept-all']"),
]

# Text-based fallback. Keep narrow — we only match if the button is
# *visible* anyway, but loose phrases like just "OK" attract false positives.
ACCEPT_TEXTS: list[str] = [
    # English
    "accept all", "accept all cookies", "allow all", "agree to all",
    "i accept", "i agree", "accept and continue",
    # German
    "alle akzeptieren", "alle cookies akzeptieren", "alle zulassen",
    "akzeptieren und schließen", "ich stimme zu", "einverstanden",
    "alles akzeptieren",
    # French
    "tout accepter", "accepter tout", "tout autoriser", "j'accepte",
    # Italian
    "accetta tutti", "accetta tutto", "accetto",
    # Spanish
    "aceptar todo", "aceptar todas", "aceptar y continuar",
    # Dutch
    "alles accepteren", "akkoord",
]
_ACCEPT_RE = re.compile("|".join(re.escape(t) for t in ACCEPT_TEXTS), re.IGNORECASE)


async def try_click_consent(
    page: Page,
    settle_ms: int = 800,
) -> tuple[bool, str | None]:
    """Try to click an "Accept all" button on ``page``.

    Returns ``(clicked, cmp_name)``. ``cmp_name`` is the CMP we matched, or
    ``"text-fallback"`` for the heuristic, or ``None`` if nothing was clicked.
    """
    # Banners often render asynchronously after `domcontentloaded`. Give
    # the page a tiny moment before we go hunting.
    try:
        await page.wait_for_timeout(400)
    except Exception:
        pass

    for name, selector in CMP_SELECTORS:
        try:
            loc = page.locator(selector).first
            if await loc.is_visible(timeout=300):
                await loc.click(timeout=2000)
                await page.wait_for_timeout(settle_ms)
                return True, name
        except Exception:
            continue

    # Text fallback — restrict to <button> and role="button" so we don't
    # click random <a> tags that happen to say "accept".
    try:
        btn = page.get_by_role("button", name=_ACCEPT_RE).first
        if await btn.is_visible(timeout=400):
            await btn.click(timeout=2000)
            await page.wait_for_timeout(settle_ms)
            return True, "text-fallback"
    except Exception:
        pass

    return False, None
