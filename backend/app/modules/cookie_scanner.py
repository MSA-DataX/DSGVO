"""Cookie + Web-Storage scanner and classifier.

Pulls cookies from the Playwright BrowserContext after a crawl finishes, plus
localStorage/sessionStorage entries that the crawler captured per page.
Classifies each entry into:

  necessary | functional | analytics | marketing | unknown

Classification priority (most specific first):

  1. Well-known cookie/storage name patterns (e.g. ``_ga``, ``_fbp``) — these
     are definitive: no first-party site sets ``_fbp`` for fun.
  2. Cookie/storage domain matches a known third-party vendor (re-uses the
     curated tracker map from :mod:`app.modules.network_analyzer`).
  3. First-party session/auth/CSRF/consent name patterns → ``necessary``.
  4. Fallback → ``unknown`` (we deliberately do not guess; auditors need to
     know what we couldn't classify).

Cookie *values* are never stored in full — only a short masked preview plus
length. Auditors rarely need the value itself, and storing them would put
session tokens / consent IDs on disk.
"""

from __future__ import annotations

import re
from typing import Iterable

import tldextract
from playwright.async_api import BrowserContext, Page

from app.models import (
    CookieCategory,
    CookieEntry,
    CookieReport,
    StorageEntry,
    StorageItem,
)
from app.modules.network_analyzer import _KNOWN_TRACKERS


# ---------------------------------------------------------------------------
# Name-based rules. Order matters: first match wins.
# Each rule: (regex, category, vendor-or-None, reason).
# ---------------------------------------------------------------------------

_NAME_RULES: list[tuple[re.Pattern[str], CookieCategory, str | None, str]] = [
    # --- Google Analytics / GA4 / GTM ---
    (re.compile(r"^_ga(_.*)?$"),         "analytics",  "google",   "Google Analytics client/session id"),
    (re.compile(r"^_gid$"),               "analytics",  "google",   "Google Analytics user id (legacy)"),
    (re.compile(r"^_gat(_.*)?$"),         "analytics",  "google",   "Google Analytics throttle"),
    (re.compile(r"^_dc_gtm_.*$"),         "analytics",  "google",   "Google Tag Manager"),
    (re.compile(r"^AMP_TOKEN$"),          "analytics",  "google",   "GA AMP token"),

    # --- Google Ads / DoubleClick ---
    (re.compile(r"^IDE$"),                "marketing",  "google",   "DoubleClick advertising id"),
    (re.compile(r"^NID$"),                "marketing",  "google",   "Google preferences/advertising"),
    (re.compile(r"^1P_JAR$"),             "marketing",  "google",   "Google ad personalization"),
    (re.compile(r"^DSID$"),               "marketing",  "google",   "DoubleClick cross-device id"),

    # --- Meta / Facebook ---
    (re.compile(r"^_fbp$"),               "marketing",  "meta",     "Facebook Pixel browser id"),
    (re.compile(r"^_fbc$"),               "marketing",  "meta",     "Facebook Pixel click id"),
    (re.compile(r"^fr$"),                 "marketing",  "meta",     "Facebook ad targeting"),
    (re.compile(r"^tr$"),                 "marketing",  "meta",     "Facebook conversion tracking"),

    # --- Microsoft Clarity / Bing ---
    (re.compile(r"^_clck$"),              "analytics",  "microsoft","Microsoft Clarity user id"),
    (re.compile(r"^_clsk$"),              "analytics",  "microsoft","Microsoft Clarity session"),
    (re.compile(r"^MUID$"),               "marketing",  "microsoft","Microsoft user/ads id"),

    # --- LinkedIn ---
    (re.compile(r"^li_(at|gc|sugr)$"),    "marketing",  "linkedin", "LinkedIn ads/tracking"),
    (re.compile(r"^bcookie$"),            "marketing",  "linkedin", "LinkedIn browser id"),
    (re.compile(r"^lidc$"),               "marketing",  "linkedin", "LinkedIn data center routing"),
    (re.compile(r"^UserMatchHistory$"),   "marketing",  "linkedin", "LinkedIn ad targeting"),

    # --- Hotjar ---
    (re.compile(r"^_hj.*"),               "analytics",  "hotjar",   "Hotjar behavior analytics"),

    # --- Hubspot ---
    (re.compile(r"^__hs(s?c|tc|pa)$"),    "analytics",  "hubspot",  "HubSpot analytics"),
    (re.compile(r"^hubspotutk$"),         "marketing",  "hubspot",  "HubSpot visitor id"),

    # --- TikTok / X / Pinterest ---
    (re.compile(r"^_ttp$"),               "marketing",  "tiktok",   "TikTok pixel"),
    (re.compile(r"^_pin_unauth$"),        "marketing",  "pinterest","Pinterest ads"),
    (re.compile(r"^muc_ads$"),            "marketing",  "twitter",  "X/Twitter ads"),

    # --- Stripe (payments — necessary if checkout is on this site) ---
    (re.compile(r"^__stripe_(mid|sid)$"), "necessary",  "stripe",   "Stripe payment fraud prevention"),

    # --- Cloudflare / hosting (necessary) ---
    (re.compile(r"^__cf_bm$"),            "necessary",  "cloudflare","Cloudflare bot management"),
    (re.compile(r"^cf_clearance$"),       "necessary",  "cloudflare","Cloudflare challenge clearance"),

    # --- Consent management platforms (necessary, by definition) ---
    (re.compile(r"^OptanonConsent$"),     "necessary",  "onetrust", "OneTrust consent record"),
    (re.compile(r"^OptanonAlertBoxClosed$"), "necessary","onetrust","OneTrust banner state"),
    (re.compile(r"^CookieConsent$"),      "necessary",  "cookiebot","Cookiebot consent record"),
    (re.compile(r"^borlabs-cookie$"),     "necessary",  "borlabs",  "Borlabs consent record"),
    (re.compile(r"^cc_cookie$"),          "necessary",  "orestbida","cookieconsent (orestbida)"),
    (re.compile(r"^uc_(consent|user_interaction|settings).*$"),
                                          "necessary",  "usercentrics","Usercentrics consent record"),
    (re.compile(r".*[_-]?consent$", re.I),"necessary",  None,       "Consent state cookie"),

    # --- First-party session / auth / CSRF (necessary) ---
    (re.compile(r"^(PHPSESSID|JSESSIONID|ASP\.NET_SessionId|ci_session)$"),
                                          "necessary",  None,       "Server session cookie"),
    (re.compile(r"^connect\.sid$"),       "necessary",  None,       "Express session cookie"),
    (re.compile(r"^csrftoken$"),          "necessary",  None,       "Django CSRF token"),
    (re.compile(r"^XSRF-TOKEN$"),         "necessary",  None,       "Angular/Laravel CSRF token"),
    (re.compile(r"^(_csrf|csrf|_token)$", re.I), "necessary", None, "CSRF/anti-forgery token"),
    (re.compile(r".*session.*", re.I),    "necessary",  None,       "Session cookie (heuristic)"),
    (re.compile(r"^(remember_.*|auth.*|access_token|refresh_token|jwt)$", re.I),
                                          "necessary",  None,       "Authentication cookie"),

    # --- WordPress / common CMSes ---
    (re.compile(r"^wordpress_.*"),        "necessary",  "wordpress","WordPress login state"),
    (re.compile(r"^wp-settings.*"),       "functional", "wordpress","WordPress UI preferences"),
    (re.compile(r"^woocommerce_.*"),      "necessary",  "woocommerce","WooCommerce cart/session"),

    # --- Locale / theme prefs ---
    (re.compile(r"^(lang|locale|i18n|theme|tz|timezone)$", re.I),
                                          "functional", None,       "User preference cookie"),
]


def _classify_by_name(name: str) -> tuple[CookieCategory, str | None, str] | None:
    for pattern, category, vendor, reason in _NAME_RULES:
        if pattern.match(name):
            return category, vendor, reason
    return None


def _classify_by_domain(domain: str) -> tuple[CookieCategory, str | None, str] | None:
    """Map cookie domain → category via the tracker registry.

    Cookie domains often start with a leading dot (``.google-analytics.com``);
    strip it and resolve to the registered domain before lookup.
    """
    cleaned = domain.lstrip(".")
    ext = tldextract.extract(cleaned)
    if not ext.domain:
        return None
    registered = f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain
    info = _KNOWN_TRACKERS.get(registered)
    if not info:
        return None
    _country, categories = info
    cats = set(categories)
    vendor = next((c for c in ("google", "meta", "microsoft", "linkedin",
                                "hotjar", "hubspot", "tiktok", "pinterest",
                                "twitter", "stripe", "cloudflare") if c in cats), None)
    if "marketing" in cats:
        return "marketing", vendor, f"Vendor domain {registered} is a known marketing tracker"
    if "analytics" in cats:
        return "analytics", vendor, f"Vendor domain {registered} is a known analytics tracker"
    if "consent" in cats:
        return "necessary", vendor, f"Vendor domain {registered} is a consent platform"
    if "payments" in cats:
        return "necessary", vendor, f"Vendor domain {registered} handles payments"
    if "cdn" in cats or "infra" in cats:
        return "functional", vendor, f"Vendor domain {registered} is infrastructure/CDN"
    return None


def _mask_value(value: str) -> tuple[str, int]:
    if not value:
        return "", 0
    length = len(value)
    if length <= 8:
        return value[:2] + "…", length
    return value[:4] + "…" + value[-2:], length


def _registered(host: str) -> str:
    ext = tldextract.extract(host.lstrip("."))
    if not ext.domain:
        return host
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain


def classify_cookie(cookie: dict, first_party_domain: str) -> CookieEntry:
    name = cookie.get("name", "")
    domain = cookie.get("domain", "") or ""
    expires = cookie.get("expires")
    is_session = expires in (None, -1, 0) or (isinstance(expires, (int, float)) and expires < 0)

    classification = _classify_by_name(name) or _classify_by_domain(domain)
    if classification is None:
        # First-party with no known pattern: cautiously unknown rather than
        # auto-marking necessary — first-party trackers exist (server-side GA4).
        classification = ("unknown", None, "No matching name or domain rule")

    category, vendor, reason = classification
    preview, length = _mask_value(cookie.get("value", ""))
    is_third_party = _registered(domain) != first_party_domain if domain else False

    return CookieEntry(
        name=name,
        domain=domain,
        path=cookie.get("path", "/"),
        value_preview=preview,
        value_length=length,
        expires=None if is_session else float(expires) if expires is not None else None,
        secure=bool(cookie.get("secure", False)),
        http_only=bool(cookie.get("httpOnly", False)),
        same_site=cookie.get("sameSite"),
        is_third_party=is_third_party,
        is_session=is_session,
        category=category,
        vendor=vendor,
        reason=reason,
    )


def classify_storage_item(item: StorageItem, page_first_party_domain: str) -> StorageEntry:
    classification = _classify_by_name(item.key)
    # Storage is always set by JS running on the *visited* page, so domain
    # comes from the page URL — but third-party scripts can still write keys
    # like `_ga` into first-party storage.
    if classification is None:
        classification = ("unknown", None, "No matching name rule for storage key")
    category, vendor, reason = classification
    return StorageEntry(
        page_url=item.page_url,
        kind=item.kind,
        key=item.key,
        value_preview=item.value_preview,
        value_length=item.value_length,
        category=category,
        vendor=vendor,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Page-side collection (called by the crawler during _visit)
# ---------------------------------------------------------------------------

# Skip values that look like JWTs / very long blobs entirely from preview —
# masked length is enough, and a JWT prefix can leak the issuer.
_JWT_RE = re.compile(r"^eyJ[A-Za-z0-9_-]{10,}\.")


async def snapshot_page_storage(page: Page) -> list[StorageItem]:
    """Read localStorage + sessionStorage from the current page.

    Returns masked items only — full values never leave the browser context.
    """
    raw: dict = await page.evaluate(
        """() => {
            const dump = (s) => {
                const out = [];
                try {
                    for (let i = 0; i < s.length; i++) {
                        const k = s.key(i);
                        out.push([k, s.getItem(k) ?? ""]);
                    }
                } catch (e) { /* storage access denied */ }
                return out;
            };
            return { local: dump(localStorage), session: dump(sessionStorage) };
        }"""
    )
    items: list[StorageItem] = []
    for kind in ("local", "session"):
        for key, value in raw.get(kind, []) or []:
            value = value or ""
            if _JWT_RE.match(value):
                preview, length = "<jwt>", len(value)
            else:
                preview, length = _mask_value(value)
            items.append(
                StorageItem(
                    page_url=page.url,
                    kind=kind,  # type: ignore[arg-type]
                    key=key,
                    value_preview=preview,
                    value_length=length,
                )
            )
    return items


# ---------------------------------------------------------------------------
# Top-level entry point: build the report after the crawl finishes.
# ---------------------------------------------------------------------------

async def build_report(
    context: BrowserContext,
    first_party_domain: str,
    page_storage: Iterable[StorageItem],
) -> CookieReport:
    raw_cookies = await context.cookies()
    cookies = [classify_cookie(c, first_party_domain) for c in raw_cookies]
    storage = [classify_storage_item(s, first_party_domain) for s in page_storage]

    summary: dict[str, int] = {
        "total_cookies": len(cookies),
        "third_party_cookies": sum(1 for c in cookies if c.is_third_party),
        "session_cookies": sum(1 for c in cookies if c.is_session),
        "total_storage": len(storage),
    }
    for cat in ("necessary", "functional", "analytics", "marketing", "unknown"):
        summary[f"cookies_{cat}"] = sum(1 for c in cookies if c.category == cat)
        summary[f"storage_{cat}"] = sum(1 for s in storage if s.category == cat)

    return CookieReport(cookies=cookies, storage=storage, summary=summary)
