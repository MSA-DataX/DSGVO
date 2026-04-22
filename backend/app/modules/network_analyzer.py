"""Network / data-flow analyzer.

Attaches to a Playwright BrowserContext, captures every outgoing request the
crawler triggers, and classifies third-party destinations by country and GDPR
transfer risk.

Country classification is intentionally OFFLINE: we do not send observed
hostnames or IPs to any third-party geolocation API, because doing so during a
GDPR audit would itself be a (small) cross-border transfer. Instead we rely
on a curated map of well-known trackers + a ccTLD heuristic, falling back to
``Unknown`` rather than guessing.
"""

from __future__ import annotations

from urllib.parse import urlparse

import tldextract
from playwright.async_api import BrowserContext, Request, Response

from app.models import DataFlowEntry, NetworkRequest, NetworkResult, Region, Risk


# Curated map: registered domain -> (country, categories)
# Categories drive the cookie/tracking module in STEP 2 — we record them here
# so the network capture is the single source of truth for "who did we talk to".
_KNOWN_TRACKERS: dict[str, tuple[Region, tuple[str, ...]]] = {
    # Google ecosystem
    "google-analytics.com":   ("USA", ("analytics", "google")),
    "googletagmanager.com":   ("USA", ("tag-manager", "google")),
    "googleadservices.com":   ("USA", ("marketing", "google")),
    "googlesyndication.com":  ("USA", ("marketing", "google")),
    "doubleclick.net":        ("USA", ("marketing", "google")),
    "google.com":             ("USA", ("google",)),
    "gstatic.com":            ("USA", ("cdn", "google")),
    "googleapis.com":         ("USA", ("api", "google")),
    "youtube.com":            ("USA", ("media", "google")),
    "ytimg.com":              ("USA", ("media", "google")),
    # Meta
    "facebook.com":           ("USA", ("marketing", "meta")),
    "facebook.net":           ("USA", ("marketing", "meta")),
    "fbcdn.net":              ("USA", ("cdn", "meta")),
    "instagram.com":          ("USA", ("media", "meta")),
    # Microsoft
    "bing.com":               ("USA", ("analytics", "microsoft")),
    "clarity.ms":             ("USA", ("analytics", "microsoft")),
    "live.com":               ("USA", ("microsoft",)),
    "office.com":             ("USA", ("microsoft",)),
    # AI providers
    "openai.com":             ("USA", ("ai",)),
    "oaistatic.com":          ("USA", ("ai",)),
    # Other US trackers
    "hotjar.com":             ("USA", ("analytics",)),
    "hotjar.io":              ("USA", ("analytics",)),
    "segment.com":            ("USA", ("analytics",)),
    "segment.io":             ("USA", ("analytics",)),
    "mixpanel.com":           ("USA", ("analytics",)),
    "amplitude.com":          ("USA", ("analytics",)),
    "fullstory.com":          ("USA", ("analytics",)),
    "linkedin.com":           ("USA", ("marketing",)),
    "licdn.com":              ("USA", ("cdn",)),
    "twitter.com":            ("USA", ("marketing",)),
    "x.com":                  ("USA", ("marketing",)),
    "tiktok.com":             ("Other", ("marketing",)),  # parent in CN
    "stripe.com":             ("USA", ("payments",)),
    "intercom.io":             ("USA", ("support",)),
    # CDNs (often EU-fronted but US-incorporated → keep USA)
    "cloudflare.com":         ("USA", ("cdn",)),
    "cloudfront.net":         ("USA", ("cdn",)),
    "amazonaws.com":          ("USA", ("infra",)),
    "akamai.net":             ("USA", ("cdn",)),
    "akamaihd.net":           ("USA", ("cdn",)),
    "fastly.net":              ("USA", ("cdn",)),
    "jsdelivr.net":           ("EU",  ("cdn",)),  # Cloudflare-fronted but org in EU/SG
    "unpkg.com":              ("USA", ("cdn",)),   # US-operated npm CDN
    "esm.sh":                 ("USA", ("cdn",)),
    "skypack.dev":            ("USA", ("cdn",)),
    "bootstrapcdn.com":       ("USA", ("cdn",)),
    "maxcdn.com":             ("USA", ("cdn",)),
    "fontawesome.com":        ("USA", ("fonts",)),
    "typekit.net":            ("USA", ("fonts", "adobe")),
    # EU services
    "matomo.cloud":            ("EU",  ("analytics",)),
    "etracker.com":            ("EU",  ("analytics",)),
    "etracker.de":             ("EU",  ("analytics",)),
    "usercentrics.eu":         ("EU",  ("consent",)),
    "cookiebot.com":           ("EU",  ("consent",)),
}

# ccTLDs that map to EU member states + EEA + UK (UK has adequacy decision).
_EU_TLDS = {
    "at", "be", "bg", "hr", "cy", "cz", "dk", "ee", "fi", "fr", "de", "gr", "hu",
    "ie", "it", "lv", "lt", "lu", "mt", "nl", "pl", "pt", "ro", "sk", "si", "es",
    "se", "eu",
    # EEA + adequacy
    "is", "li", "no", "ch", "uk",
}


def _registered_domain(url: str) -> str:
    ext = tldextract.extract(url)
    if not ext.domain:
        return ""
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain


def _classify_domain(registered: str) -> tuple[Region, tuple[str, ...]]:
    if registered in _KNOWN_TRACKERS:
        return _KNOWN_TRACKERS[registered]
    suffix = registered.rsplit(".", 1)[-1] if "." in registered else ""
    if suffix in _EU_TLDS:
        return ("EU", ())
    return ("Unknown", ())


def _risk_for(country: Region, categories: tuple[str, ...]) -> Risk:
    if country == "EU":
        return "low"
    if country == "USA":
        # Marketing/analytics transfers to the US are the classic Schrems II problem.
        if any(c in categories for c in ("marketing", "analytics", "ai")):
            return "high"
        return "medium"
    if country == "Other":
        return "high"
    return "medium"  # Unknown


class NetworkAnalyzer:
    def __init__(self, first_party_url: str) -> None:
        self.first_party_domain = _registered_domain(first_party_url)
        self._records: dict[int, NetworkRequest] = {}
        self._counter = 0

    def attach(self, context: BrowserContext) -> None:
        context.on("request", self._on_request)
        context.on("response", self._on_response)
        context.on("requestfailed", self._on_requestfailed)

    # --- event handlers ---------------------------------------------------

    def _on_request(self, request: Request) -> None:
        parsed = urlparse(request.url)
        # Skip non-network schemes (blob:, data:, about:, chrome-extension:,
        # javascript:, file:). These are browser-local and not a GDPR-relevant
        # transfer, and they pollute the data flow with fake "domains" like
        # "blob".
        if parsed.scheme not in ("http", "https"):
            return
        domain = parsed.hostname or ""
        registered = _registered_domain(request.url)
        if not registered:
            return
        self._counter += 1
        self._records[id(request)] = NetworkRequest(
            url=request.url,
            domain=domain,
            registered_domain=registered,
            method=request.method,
            resource_type=request.resource_type,
            status=None,
            initiator_page=(request.frame.url if request.frame else ""),
            is_third_party=registered != self.first_party_domain,
        )

    def _on_response(self, response: Response) -> None:
        rec = self._records.get(id(response.request))
        if rec is not None:
            rec.status = response.status

    def _on_requestfailed(self, request: Request) -> None:
        rec = self._records.get(id(request))
        if rec is not None and rec.status is None:
            rec.status = 0  # signals failure without inventing an HTTP code

    # --- aggregation ------------------------------------------------------

    def result(self) -> NetworkResult:
        requests = list(self._records.values())
        agg: dict[str, dict] = {}
        for r in requests:
            if not r.is_third_party:
                continue
            slot = agg.setdefault(
                r.registered_domain,
                {"count": 0, "categories": set()},
            )
            slot["count"] += 1
            country, categories = _classify_domain(r.registered_domain)
            slot["country"] = country
            slot["categories"].update(categories)

        data_flow = [
            DataFlowEntry(
                domain=domain,
                country=slot["country"],
                request_count=slot["count"],
                categories=sorted(slot["categories"]),
                risk=_risk_for(slot["country"], tuple(slot["categories"])),
            )
            for domain, slot in sorted(agg.items())
        ]
        return NetworkResult(requests=requests, data_flow=data_flow)
