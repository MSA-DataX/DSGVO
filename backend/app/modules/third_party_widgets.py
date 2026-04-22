"""Detect third-party UI elements embedded in the site.

Three related concerns collapse into one module because they answer the
same question — *what third-party experience does the visitor get that
the operator is responsible for disclosing?*

  1. **Iframe embeds** — video players (YouTube, Vimeo, Wistia), maps
     (Google Maps, OpenStreetMap, Mapbox), social embeds (Twitter timeline,
     Instagram feed). The big distinction is the **privacy-enhanced
     variant**: `youtube-nocookie.com` (no tracking until play) vs.
     `youtube.com/embed/` (tracks immediately). An auditor needs to see
     which variant is in use.
  2. **Chat widgets** — Intercom, Drift, Zendesk, Tawk, Crisp, LiveChat,
     HubSpot. Detected via known script URLs in page HTML or captured
     network requests. These widgets almost always load a session cookie
     and send visitor data pre-consent.
  3. **Social-login SDKs** — "Sign in with Google / Facebook / Apple /
     Microsoft / LinkedIn / Twitter / GitHub". Detected via known SDK URLs.
     Many sites load the SDK on every page even though the login button
     only appears on one — classic pre-consent tracking leak.

All three produce :class:`ThirdPartyWidget` entries with a consistent
shape so the dashboard can render them in one section.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from app.models import (
    NetworkResult,
    PageInfo,
    ThirdPartyWidget,
    ThirdPartyWidgetsReport,
    WidgetCategory,
    WidgetKind,
)


# ---------------------------------------------------------------------------
# Iframe-src rules.
# Ordered: privacy-enhanced variants BEFORE default variants so the more
# specific pattern wins (e.g. youtube-nocookie.com must match before the
# generic youtube.com rule).
# ---------------------------------------------------------------------------

_IFRAME_RULES: list[tuple[re.Pattern[str], WidgetKind, WidgetCategory, str, str, bool]] = [
    # (regex, kind, category, vendor, country, privacy_enhanced)
    # --- video ---
    (re.compile(r"^https?://(www\.)?youtube-nocookie\.com/embed/", re.I),
                                                "youtube_nocookie",    "video", "Google",  "USA", True),
    (re.compile(r"^https?://(www\.)?youtube\.com/embed/", re.I),
                                                "youtube",             "video", "Google",  "USA", False),
    # Vimeo: the "Do Not Track" variant uses `?dnt=1`. Query-string match
    # happens AFTER we pick the kind — base kind is Vimeo either way, we
    # just set privacy_enhanced based on dnt param further below.
    (re.compile(r"^https?://player\.vimeo\.com/video/", re.I),
                                                "vimeo",               "video", "Vimeo",   "USA", False),
    (re.compile(r"^https?://fast\.wistia\.net/embed/", re.I),
                                                "wistia",              "video", "Wistia",  "USA", False),

    # --- maps ---
    (re.compile(r"^https?://(www\.)?google\.com/maps/embed", re.I),
                                                "google_maps",         "map",   "Google",          "USA", False),
    (re.compile(r"^https?://maps\.google\.", re.I),
                                                "google_maps",         "map",   "Google",          "USA", False),
    (re.compile(r"^https?://(www\.)?openstreetmap\.org/export/embed", re.I),
                                                "openstreetmap",       "map",   "OpenStreetMap",   "EU",  True),
    (re.compile(r"^https?://(api|www)\.mapbox\.com/", re.I),
                                                "mapbox",              "map",   "Mapbox",          "USA", False),
    (re.compile(r"^https?://www\.bing\.com/maps/embed", re.I),
                                                "bing_maps",           "map",   "Microsoft",       "USA", False),

    # --- social embeds (in iframe form) ---
    (re.compile(r"^https?://platform\.twitter\.com/embed", re.I),
                                                "twitter_widget",      "social_embed", "X (Twitter)",  "USA", False),
    (re.compile(r"^https?://(www\.)?instagram\.com/p/.*/embed", re.I),
                                                "instagram_embed",     "social_embed", "Meta",          "USA", False),
    (re.compile(r"^https?://(www\.)?facebook\.com/plugins/", re.I),
                                                "facebook_widget",     "social_embed", "Meta",          "USA", False),
    (re.compile(r"^https?://(www\.)?tiktok\.com/embed", re.I),
                                                "tiktok_embed",        "social_embed", "ByteDance",     "Other", False),
    (re.compile(r"^https?://(www\.)?linkedin\.com/embed/", re.I),
                                                "linkedin_widget",     "social_embed", "Microsoft",     "USA", False),
]

# ---------------------------------------------------------------------------
# Script-URL rules for chat widgets + social-login SDKs.
# We match against the *request URL* the browser actually issued, not
# against arbitrary inline script content — that's too noisy.
# ---------------------------------------------------------------------------

_SCRIPT_RULES: list[tuple[re.Pattern[str], WidgetKind, WidgetCategory, str, str]] = [
    # (regex, kind, category, vendor, country)
    # --- chat widgets ---
    (re.compile(r"^https?://widget\.intercom\.io/", re.I),          "chat_intercom",   "chat", "Intercom",   "USA"),
    (re.compile(r"^https?://js\.intercomcdn\.com/", re.I),          "chat_intercom",   "chat", "Intercom",   "USA"),
    (re.compile(r"^https?://js\.driftt?\.com/", re.I),              "chat_drift",      "chat", "Drift",      "USA"),
    (re.compile(r"^https?://static\.zdassets\.com/ekr/", re.I),     "chat_zendesk",    "chat", "Zendesk",    "USA"),
    (re.compile(r"^https?://v2\.zopim\.com/", re.I),                "chat_zendesk",    "chat", "Zendesk",    "USA"),
    (re.compile(r"^https?://embed\.tawk\.to/", re.I),               "chat_tawk",       "chat", "Tawk.to",    "USA"),
    (re.compile(r"^https?://client\.crisp\.chat/", re.I),           "chat_crisp",      "chat", "Crisp",      "EU"),
    (re.compile(r"^https?://cdn\.livechatinc\.com/", re.I),         "chat_livechat",   "chat", "LiveChat",   "USA"),
    (re.compile(r"^https?://js\.usemessages\.com/", re.I),          "chat_hubspot",    "chat", "HubSpot",    "USA"),
    (re.compile(r"^https?://connect\.facebook\.net/.*customerchat", re.I),
                                                                     "chat_facebook",   "chat", "Meta",       "USA"),

    # --- social-login SDKs ---
    (re.compile(r"^https?://accounts\.google\.com/gsi/client", re.I),
                                                                     "auth_google",     "auth", "Google",     "USA"),
    (re.compile(r"^https?://apis\.google\.com/js/platform\.js", re.I),
                                                                     "auth_google",     "auth", "Google",     "USA"),
    (re.compile(r"^https?://connect\.facebook\.net/.*/sdk\.js", re.I),
                                                                     "auth_facebook",   "auth", "Meta",       "USA"),
    (re.compile(r"^https?://appleid\.cdn-apple\.com/appleauth", re.I),
                                                                     "auth_apple",      "auth", "Apple",      "USA"),
    (re.compile(r"^https?://(login\.live\.com|login\.microsoftonline\.com)/", re.I),
                                                                     "auth_microsoft",  "auth", "Microsoft",  "USA"),
    (re.compile(r"^https?://platform\.linkedin\.com/in\.js", re.I),
                                                                     "auth_linkedin",   "auth", "Microsoft",  "USA"),
    (re.compile(r"^https?://platform\.twitter\.com/widgets\.js", re.I),
                                                                     "auth_twitter",    "auth", "X (Twitter)","USA"),
    (re.compile(r"^https?://github\.com/login/oauth", re.I),
                                                                     "auth_github",     "auth", "Microsoft",  "USA"),
]


def _classify_iframe(src: str) -> tuple[WidgetKind, WidgetCategory, str, str, bool] | None:
    for pattern, kind, category, vendor, country, base_enhanced in _IFRAME_RULES:
        if not pattern.match(src):
            continue
        enhanced = base_enhanced
        # Vimeo's ?dnt=1 flips the privacy-enhanced flag at URL level.
        if kind == "vimeo" and re.search(r"[?&]dnt=1(?:&|$)", src):
            enhanced = True
            kind_override: WidgetKind = "vimeo_dnt"
            return kind_override, category, vendor, country, True
        return kind, category, vendor, country, enhanced
    return None


def _classify_script(url: str) -> tuple[WidgetKind, WidgetCategory, str, str] | None:
    for pattern, kind, category, vendor, country in _SCRIPT_RULES:
        if pattern.match(url):
            return kind, category, vendor, country
    return None


def _normalize_iframe_src(src: str) -> str:
    """Strip tracking query params so `youtube.com/embed/XYZ?t=1` and
    `?t=2` count as one widget. Keeps the path + the YouTube-specific
    ``dnt`` / ``rel`` params if present (affect behavior)."""
    try:
        p = urlparse(src)
    except Exception:
        return src
    return f"{p.scheme}://{p.netloc}{p.path}" if p.netloc else src


def detect_widgets(
    pages: list[PageInfo],
    network: NetworkResult,
) -> ThirdPartyWidgetsReport:
    """Produce the consolidated widgets report.

    Two passes:

      - walk every page's ``iframes`` list → iframe-based widgets
      - walk ``network.requests`` → chat + auth widgets (matched by URL)

    A widget is keyed by (kind, normalized_src). Duplicates across pages
    collapse into one entry with a ``pages`` list.
    """
    buckets: dict[tuple[WidgetKind, str], ThirdPartyWidget] = {}

    # --- Pass 1: iframes (HTML-declared, reliable) ---------------------
    for page in pages:
        for raw_src in page.iframes:
            classified = _classify_iframe(raw_src)
            if classified is None:
                continue
            kind, category, vendor, country, enhanced = classified
            normalized = _normalize_iframe_src(raw_src)
            key = (kind, normalized)
            entry = buckets.get(key)
            if entry is None:
                buckets[key] = ThirdPartyWidget(
                    kind=kind, category=category, vendor=vendor,
                    country=country,  # type: ignore[arg-type]
                    src=normalized, pages=[page.url],
                    privacy_enhanced=enhanced,
                    requires_consent=not enhanced,
                )
            elif page.url not in entry.pages:
                entry.pages.append(page.url)

    # --- Pass 2: chat + auth via actual network requests --------------
    # Using the request log (not just HTML scripts) catches widgets that
    # dynamically inject their script tag after page load.
    seen_script_keys: set[tuple[WidgetKind, str]] = set()
    for req in network.requests:
        classified = _classify_script(req.url)
        if classified is None:
            continue
        kind, category, vendor, country = classified
        # Use hostname + first path segment as the de-dup key — the exact
        # URL varies (versions, query strings) but the widget identity
        # doesn't.
        p = urlparse(req.url)
        first_seg = p.path.split("/", 2)[1] if p.path.count("/") >= 1 else ""
        dedup_src = f"{p.scheme}://{p.netloc}/{first_seg}"
        key = (kind, dedup_src)
        if key in seen_script_keys:
            continue
        seen_script_keys.add(key)
        # Find which page(s) this loaded on. initiator_page is the frame URL.
        page_url = req.initiator_page or ""
        entry = buckets.get(key)
        if entry is None:
            buckets[key] = ThirdPartyWidget(
                kind=kind, category=category, vendor=vendor,
                country=country,  # type: ignore[arg-type]
                src=dedup_src, pages=[page_url] if page_url else [],
                privacy_enhanced=False,
                # Auth SDKs on a dedicated /login page are defensible;
                # everything else loaded pre-consent is a problem.
                requires_consent=(category != "auth" or "login" not in page_url.lower()),
            )
        elif page_url and page_url not in entry.pages:
            entry.pages.append(page_url)

    widgets = list(buckets.values())

    # summary counts
    summary: dict[str, int] = {"total_widgets": len(widgets)}
    for category in ("video", "map", "chat", "auth", "social_embed", "other"):
        summary[f"category_{category}"] = sum(1 for w in widgets if w.category == category)
    summary["privacy_enhanced"] = sum(1 for w in widgets if w.privacy_enhanced)
    summary["us_widgets"] = sum(1 for w in widgets if w.country == "USA")
    summary["non_enhanced_video"] = sum(
        1 for w in widgets if w.category == "video" and not w.privacy_enhanced
    )

    return ThirdPartyWidgetsReport(widgets=widgets, summary=summary)
