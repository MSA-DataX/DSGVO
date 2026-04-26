from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, HttpUrl, Field


Risk = Literal["low", "medium", "high"]
Region = Literal["EU", "USA", "Other", "Unknown"]
CookieCategory = Literal["necessary", "functional", "analytics", "marketing", "unknown"]
StorageKind = Literal["local", "session"]
Severity = Literal["low", "medium", "high"]
FormPurpose = Literal["collection", "search", "authentication", "unknown"]
ContactChannelKind = Literal[
    # messaging
    "whatsapp", "telegram", "signal", "facebook_messenger", "skype", "discord",
    # direct schemes
    "email", "phone", "sms",
    # social profiles
    "facebook_profile", "instagram_profile", "linkedin_profile",
    "twitter_profile", "youtube_channel", "tiktok_profile",
    "xing_profile", "pinterest_profile", "github_profile",
]
WidgetCategory = Literal["video", "map", "chat", "auth", "social_embed", "other"]
DarkPatternCode = Literal[
    "no_direct_reject",         # only Accept + Settings, no reject on first level
    "reject_via_text_fallback", # only matched via loose text heuristic — low confidence
    "reject_much_smaller",      # reject area significantly smaller than accept
    "reject_below_fold",        # reject button not in the initial viewport
    "reject_low_prominence",    # weaker font-weight / no background / lower opacity
    "forced_interaction",       # banner blocks content and offers no opt-out
    # Phase 9e: "Pay or okay" cookie wall — accept tracking OR pay a
    # subscription. EDPB Opinion 8/2024 (April 2024): not valid consent
    # for large online platforms without an "equivalent alternative
    # without behavioural advertising".
    "cookie_wall_pay_or_okay",
]
WidgetKind = Literal[
    # video
    "youtube", "youtube_nocookie", "vimeo", "vimeo_dnt", "wistia",
    # maps
    "google_maps", "openstreetmap", "mapbox", "bing_maps", "apple_maps",
    # chat widgets
    "chat_intercom", "chat_drift", "chat_zendesk", "chat_tawk",
    "chat_crisp", "chat_livechat", "chat_hubspot", "chat_facebook",
    # auth / social login SDKs
    "auth_google", "auth_facebook", "auth_apple", "auth_microsoft",
    "auth_linkedin", "auth_twitter", "auth_github",
    # social embeds (feeds, like buttons, share widgets)
    "twitter_widget", "facebook_widget", "instagram_embed",
    "linkedin_widget", "tiktok_embed", "pinterest_widget",
    # catch-all for future additions
    "other",
]
RiskRating = Literal["low", "medium", "high", "critical"]
RecommendationPriority = Literal["low", "medium", "high"]
PolicyIssueCategory = Literal[
    "missing_section",         # required GDPR section absent
    "unclear_wording",         # vague / ambiguous language
    "risky_processing",        # broad consent, "may share with partners", etc.
    "third_country_transfer",  # transfer to non-adequate country
    "missing_user_rights",     # rights under Art. 15-22 not enumerated
    "missing_legal_basis",     # Art. 6 basis not stated
    "missing_retention",       # retention period not stated
    "missing_dpo",             # DPO contact missing where required
    "other",
]


UiLanguage = Literal["en", "de"]


class ScanRequest(BaseModel):
    url: HttpUrl
    max_depth: int | None = Field(default=None, ge=0, le=3)
    max_pages: int | None = Field(default=None, ge=1, le=25)
    # Run a second crawl that clicks "Accept all" before crawling. Doubles
    # scan time. Off by default — pre-consent state is the legally relevant
    # one; the post-consent picture is informational.
    consent_simulation: bool = False
    # Explicit privacy policy URL. Skips auto-detection entirely when set
    # — useful for large corporate sites where the link is buried in a
    # lazy-loaded footer and our BFS crawl misses it.
    privacy_policy_url: HttpUrl | None = None
    # Language for backend-generated prose (recommendations, AI summary,
    # AI issue descriptions). The UI chrome is translated client-side;
    # this field covers the content the server produces. Defaults to
    # English for CLI / API users; the dashboard always sends its current
    # language.
    ui_language: UiLanguage = "en"
    # Phase 11: opt-in performance audit (Web Vitals + network metrics +
    # asset audit). Off by default because it adds 2-5s per scan and
    # is informational rather than compliance-relevant. Premium plans
    # may flip this to default-true at the API layer later.
    performance_audit: bool = False


class FormField(BaseModel):
    name: str | None = None
    type: str | None = None
    required: bool = False
    # Phase 9: HTML `checked` attribute on a checkbox input — relevant
    # for the EuGH Planet49 / Art. 7(2) DSGVO check (pre-ticked
    # consent boxes are NOT valid consent). Always False for non-
    # checkbox inputs.
    is_pre_checked: bool = False


class FormInfo(BaseModel):
    action: str | None
    method: str
    fields: list[FormField]
    page_url: str
    text_content: str = ""           # visible text inside the form (labels, legal copy)
    links: list[str] = []            # absolute hrefs found inside the form
    has_checkbox: bool = False
    # Derived in the crawler so form_analyzer doesn't need to re-walk
    # the field list. True iff *any* checkbox in the form ships with
    # the HTML `checked` attribute set.
    has_pre_checked_box: bool = False


class StorageItem(BaseModel):
    page_url: str
    kind: StorageKind
    key: str
    value_preview: str
    value_length: int


class PageInfo(BaseModel):
    url: str
    title: str | None
    status: int | None
    depth: int
    scripts: list[str] = []
    iframes: list[str] = []              # absolute iframe srcs declared in HTML
    links: list[str] = []
    forms: list[FormInfo] = []
    storage: list[StorageItem] = []
    is_privacy_policy: bool = False
    # Cross-origin <script> tags declared without an `integrity=` attribute.
    # Supply-chain-attack exposure: a compromised CDN could serve altered
    # JavaScript and the browser would execute it without complaint.
    cross_origin_scripts_missing_sri: list[str] = []


class NetworkRequest(BaseModel):
    url: str
    domain: str
    registered_domain: str
    method: str
    resource_type: str | None
    status: int | None
    initiator_page: str
    is_third_party: bool
    # Phase 9c: 1×1 GIF / .png beacon to a known marketing endpoint
    # (Meta /tr, GA __utm.gif, generic /pixel|/beacon|/conversion).
    # Pre-consent loads of these are the textbook § 25 TDDDG /
    # ePrivacy violation; surfacing them separately gives auditors a
    # specific remediation hook (Conversions API / server-side events)
    # rather than the generic "third-party tracker contacted" finding.
    is_tracking_pixel: bool = False
    # Phase 11 — performance fields. All optional / default None so the
    # GDPR-only path stays unchanged: we only fill these when
    # performance_audit is requested AND the response actually arrived.
    # response_size is the on-the-wire transferred bytes (Content-Length
    # if announced, else `len(body)` after gunzip). content_encoding is
    # the verbatim header value (e.g. "br", "gzip", "identity") so the
    # asset audit can flag responses without compression.
    response_size: int | None = None
    content_encoding: str | None = None


class DataFlowEntry(BaseModel):
    domain: str
    country: Region
    request_count: int
    categories: list[str] = []
    risk: Risk


class CrawlResult(BaseModel):
    start_url: str
    pages: list[PageInfo]
    privacy_policy_url: str | None
    imprint_url: str | None = None     # § 5 TMG Impressum — mandatory for
                                       # German commercial sites. None = not
                                       # found via crawl or common-path probing.


class GoogleFontsCheck(BaseModel):
    """Phase 10 — deterministic detection of Google Fonts loaded from
    Google's servers (fonts.googleapis.com / fonts.gstatic.com).

    Confirmed GDPR violation under LG München I 3 O 17493/20 (20.01.2022),
    which awarded €100 immaterial damages against the operator. The court
    held that transmitting the visitor's IP to Google during font loading
    constitutes an unjustified third-country transfer when the fonts
    could trivially be self-hosted.

    The check is pure + structured so the dashboard can show *which*
    families were loaded (auditor evidence) without re-walking the raw
    request list.
    """
    detected: bool = False
    # Font families parsed from googleapis.com URLs
    # (e.g. ?family=Roboto|Open+Sans:300,400 → ["Roboto", "Open Sans"]).
    # Empty when only gstatic.com binaries were observed (CSS loaded
    # from cache or via a non-fonts.googleapis.com path).
    families: list[str] = []
    # Total number of binary requests to fonts.gstatic.com — useful as a
    # severity signal (one font ≠ the whole site is in violation).
    binary_count: int = 0
    # Pages that initiated at least one Google-Fonts request. Helps the
    # auditor target the fix to specific templates.
    initiator_pages: list[str] = []
    # Up to three example URLs for evidence. Trimmed because a real
    # site can fire dozens of /css and /s/* loads per page.
    css_url_samples: list[str] = []


class NetworkResult(BaseModel):
    requests: list[NetworkRequest]
    data_flow: list[DataFlowEntry]
    # Phase 10: structured Google-Fonts-loaded-externally signal.
    # Default empty (detected=False) so callers that don't run the
    # detector still produce valid responses.
    google_fonts: GoogleFontsCheck = GoogleFontsCheck()


class CookieEntry(BaseModel):
    name: str
    domain: str
    path: str
    value_preview: str
    value_length: int
    expires: float | None
    secure: bool
    http_only: bool
    same_site: str | None
    is_third_party: bool
    is_session: bool          # no expiry / session-only
    category: CookieCategory
    vendor: str | None = None
    reason: str               # why we chose this category — useful for audit


class StorageEntry(BaseModel):
    page_url: str
    kind: StorageKind
    key: str
    value_preview: str
    value_length: int
    category: CookieCategory
    vendor: str | None = None
    reason: str


class CookieReport(BaseModel):
    cookies: list[CookieEntry]
    storage: list[StorageEntry]
    summary: dict[str, int]   # category -> count, plus "third_party" / "total"


class PolicyIssue(BaseModel):
    category: PolicyIssueCategory
    severity: Severity
    # Finer-grained ordinal for sorting in dashboards with many issues.
    # 1 = trivial, 10 = urgent legal risk. Severity remains authoritative
    # for the three-bucket UI colour coding; risk_score lets the operator
    # rank within a bucket ("of my 4 'high' issues, which is the worst?").
    risk_score: int = Field(default=5, ge=1, le=10)
    description: str
    excerpt: str | None = None        # short verbatim quote from the policy
    # Ready-to-paste draft paragraph the operator can add to the policy to
    # close the finding. In the *same language as the policy* (so the user
    # can actually paste it in). May be null when the finding doesn't map
    # to an insertable text (e.g. "unclear wording" — operator must rewrite
    # existing copy rather than append new). The UI MUST render this with
    # a legal disclaimer; see PrivacyAnalysisCard.
    suggested_text: str | None = None
    # Implementation snippet when the finding is technical (missing header,
    # HTML form, JS). `nginx`/`apache` directives, HTML attributes etc.
    # Complements suggested_text — a policy issue can have both (add
    # paragraph to DSE + add nosniff header to server config). Null when
    # no code artefact is helpful.
    suggested_code: str | None = None
    # 2-4 imperative bullet points. TL;DR for implementers who want the
    # fix without reading the full description/draft. Empty list allowed
    # when the fix is entirely contained in suggested_text/suggested_code.
    action_steps: list[str] = []
    # If this finding is something that should be tracked over time
    # (e.g. "new third-party script", "policy URL changed"), describe the
    # trigger. Consumed by the scheduled-scan Stage-2 feature — today it's
    # surfaced as an informational line in the UI. Null for one-time fixes.
    monitoring_trigger: str | None = None


class PolicyTopicCoverage(BaseModel):
    """Hard checklist of GDPR sections — boolean per topic.

    The model fills this in alongside the prose summary so callers can render
    a checklist UI without re-parsing the issues array.
    """
    legal_basis_stated: bool
    data_categories_listed: bool
    retention_period_stated: bool
    third_party_recipients_listed: bool
    third_country_transfers_disclosed: bool
    user_rights_enumerated: bool
    contact_for_data_protection: bool
    cookie_section_present: bool
    children_data_addressed: bool


class DsarCheck(BaseModel):
    """Deterministic check for whether a privacy policy explains how a
    data subject exercises their GDPR Art. 15-22 rights (Phase 9d).

    Independent of the AI layer — runs on the raw policy text via
    keyword matching, so it produces a baseline signal even when the
    operator runs the scanner with ``AI_PROVIDER=none``. The AI layer's
    ``PolicyTopicCoverage.user_rights_enumerated`` is the prose-level
    judgement; this is the regex-level cross-check.
    """
    # Subset of:
    #   "access" (Art. 15), "rectification" (16), "erasure" (17),
    #   "restriction" (18), "portability" (20), "objection" (21),
    #   "complaint" (77), "withdraw_consent" (7(3)).
    named_rights: list[str] = []
    has_rights_contact: bool = False
    contact_excerpt: str | None = None
    # Convenience score 0-100. Each named right is worth ~12 points,
    # contact presence is worth 16. Used by scoring + UI badges.
    score: int = Field(ge=0, le=100, default=0)


class PrivacyAnalysis(BaseModel):
    provider: str                     # "openai" | "azure" | "none"
    model: str | None                 # model/deployment used, if any
    policy_url: str | None
    summary: str                      # 3-6 sentence plain-language summary
    issues: list[PolicyIssue]
    coverage: PolicyTopicCoverage | None
    compliance_score: int = Field(ge=0, le=100)
    excerpt_chars_sent: int = 0       # how much of the policy reached the model
    error: str | None = None          # set when AI step was skipped or failed
    # Phase 9d — deterministic DSAR check populated when the policy
    # text was fetched. None when no policy was found (the cap layer
    # already handles that case via has_policy=False).
    dsar: DsarCheck | None = None


class FormFinding(BaseModel):
    page_url: str
    form_action: str | None
    method: str
    # What the form is FOR. Search/auth forms get lighter GDPR scrutiny than
    # data-collection forms — a newsletter signup needs a consent checkbox,
    # a "find my local service center" address-lookup does not.
    purpose: FormPurpose = "collection"
    collected_data: list[str]         # ["email","name","phone","address","password","date_of_birth","national_id","payment"]
    field_count: int
    has_consent_checkbox: bool
    has_privacy_link: bool
    # Phase 9: True when a pre-ticked checkbox sits inside a form whose
    # surrounding text contains consent/marketing vocabulary. Settled
    # CJEU case law since Planet49 (C-673/17, 2019) — pre-ticked is
    # NOT valid consent under Art. 7(2) DSGVO. Drives a hard cap.
    has_pre_checked_consent: bool = False
    legal_text_excerpt: str | None
    issues: list[str]                 # human-readable findings


class FormReport(BaseModel):
    forms: list[FormFinding]
    summary: dict[str, int]           # totals: forms / with_consent / with_privacy_link / collecting_pii


class ContactChannel(BaseModel):
    kind: ContactChannelKind
    target: str                        # URL (for web links) or masked address (mailto:/tel:/sms:)
    vendor: str | None                 # "Meta", "Microsoft", … or None for generic schemes
    country: Region                    # transfer destination, "Unknown" for mailto:/tel:
    pages: list[str]                   # which crawled page(s) expose this channel


class ContactChannelsReport(BaseModel):
    channels: list[ContactChannel]
    summary: dict[str, int]


class ThirdPartyWidget(BaseModel):
    """A third-party UI element embedded in the site.

    Covers iframes (video, maps), chat widgets (Intercom etc.), and
    social-login SDK scripts. Each entry represents a distinct embed —
    the same YouTube video linked from 5 pages is one widget with five
    pages, not five widgets.
    """
    kind: WidgetKind
    category: WidgetCategory
    vendor: str | None
    country: Region
    src: str                               # iframe URL, script URL, or handler pattern
    pages: list[str]                       # crawled pages where it appears
    privacy_enhanced: bool = False         # True for youtube-nocookie.com, Vimeo ?dnt=1, etc.
    requires_consent: bool = True          # False if strictly necessary (e.g. auth on login page only)


class ThirdPartyWidgetsReport(BaseModel):
    widgets: list[ThirdPartyWidget]
    summary: dict[str, int]


# ---------------------------------------------------------------------------
# Passive security audit (Phase 4)
# All observations below come from inspecting the HTTP/TLS handshake and
# response headers only — i.e. information any normal browser visit would
# reveal. No active probing.
# ---------------------------------------------------------------------------

class SecurityHeaderFinding(BaseModel):
    name: str                                   # canonical header name
    present: bool
    value: str | None = None                    # actual header value if present
    severity: Severity                          # missing critical header → high
    note: str                                   # what's correct / what's wrong


class TlsInfo(BaseModel):
    https_enforced: bool                        # plain HTTP → 301/302 to HTTPS?
    tls_version: str | None = None              # "TLSv1.3" / "TLSv1.2" / …
    cert_expires_days: int | None = None        # None if parse failed
    cert_issuer: str | None = None
    hsts_max_age_days: int | None = None        # parsed from HSTS header
    hsts_include_subdomains: bool = False
    hsts_preload_eligible: bool = False         # has preload + includeSubdomains + max-age ≥ 1y


class InfoLeakHeader(BaseModel):
    name: str                                   # "Server" / "X-Powered-By" / …
    value: str
    leaks: str                                  # short description of what's exposed


DmarcPolicy = Literal["none", "quarantine", "reject", "unknown", "missing"]


class DnsSecurityInfo(BaseModel):
    """Public DNS observations about the scanned domain.

    Everything here comes from ordinary DNS queries — same information
    every mail server and CA does when deciding whether to trust the
    domain. No active probing.
    """
    domain: str                                 # registered domain we queried
    spf_present: bool
    spf_record: str | None = None
    dmarc_present: bool
    dmarc_policy: DmarcPolicy
    dmarc_record: str | None = None
    dnssec_enabled: bool                        # AD flag set by resolver OR DNSKEY present
    caa_present: bool                           # CAA records restrict cert-issuing CAs
    error: str | None = None                    # set when resolver was unreachable


class VulnerableLibrary(BaseModel):
    """One detected JavaScript library with known CVE(s)."""
    library: str                                # "jquery"
    detected_version: str                       # "1.11.0"
    url: str                                    # where we saw the file on the scanned site
    severity: Severity                          # worst CVE in the range
    cves: list[str] = []                        # ["CVE-2015-9251"]
    advisory: str | None = None                 # short summary of what it's vulnerable to
    fixed_in: str | None = None                 # first version that fixes it


class VulnerableLibrariesReport(BaseModel):
    libraries: list[VulnerableLibrary]
    summary: dict[str, int] = {}                # totals by severity


class SecurityAudit(BaseModel):
    final_url: str                              # URL after following HTTPS redirects
    headers: list[SecurityHeaderFinding]
    tls: TlsInfo | None = None
    mixed_content_count: int = 0                # HTTP resources loaded from HTTPS page
    mixed_content_samples: list[str] = []       # up to 5 example URLs
    info_leak_headers: list[InfoLeakHeader] = []
    # Phase 5 additions — passive infrastructure signals
    security_txt_url: str | None = None         # URL if /.well-known/security.txt exists
    sri_missing: list[str] = []                 # cross-origin script URLs without integrity=
    dns: DnsSecurityInfo | None = None          # DNS-level security record checks
    summary: dict[str, int] = {}                # high/medium/low counts + totals
    error: str | None = None                    # populated when the homepage fetch failed


class SubScore(BaseModel):
    name: str                          # cookies | tracking | data_transfer | privacy | forms
    score: int = Field(ge=0, le=100)   # higher = better
    weight: float = Field(ge=0.0, le=1.0)
    weighted_contribution: float       # score * weight, kept for transparency
    notes: list[str] = []              # short bullet explanations of *why* this score


class HardCap(BaseModel):
    code: str                          # machine-readable identifier (snake_case)
    description: str                   # one-line plain-English explanation
    cap_value: int = Field(ge=0, le=100)
    # Sub-score names this cap is conceptually rooted in. Caps don't
    # apply per-sub-score in the scoring engine (they pull down the
    # FINAL weighted score), but each cap is triggered by a finding
    # that lives in a specific GDPR domain — so the dashboard can show
    # "this 50/100 sub-score is what dragged the final score down,
    # here's the cap that fired". Allowed values are sub-score names
    # ("cookies", "tracking", "data_transfer", "privacy", "forms").
    # Empty list means the cap is cross-cutting (e.g. security caps
    # whose domain isn't represented as a sub-score). Default empty
    # so historical scans loaded from the DB pre-Phase-Caps don't
    # error on field absence.
    affected_subscores: list[str] = []


class Recommendation(BaseModel):
    priority: RecommendationPriority
    title: str
    detail: str
    related: list[str] = []            # tags pointing at the source finding(s)


class RiskScore(BaseModel):
    score: int = Field(ge=0, le=100)               # FINAL score after caps applied
    rating: RiskRating
    weighted_score: int = Field(ge=0, le=100)      # weighted sum BEFORE caps
    sub_scores: list[SubScore]
    applied_caps: list[HardCap]                    # caps that triggered (each lowered the score)
    recommendations: list[Recommendation]


class ConsentDiff(BaseModel):
    """What the site does *additionally* once the user clicks Accept all."""
    new_cookies: list[CookieEntry] = []
    new_storage: list[StorageEntry] = []
    new_data_flow: list[DataFlowEntry] = []        # domains contacted only post-consent
    extra_request_count: int = 0                   # post requests minus pre requests
    new_marketing_count: int = 0
    new_analytics_count: int = 0


class DarkPatternFinding(BaseModel):
    code: DarkPatternCode
    severity: Severity
    description: str
    # Numeric / boolean evidence behind the finding so the auditor can
    # re-verify ("reject was 42% the area of accept" instead of a vague
    # "smaller"). Kept flat + JSON-serializable.
    evidence: dict[str, float | int | str | bool] = {}


class ConsentUxAudit(BaseModel):
    """Objective measurement of how the consent banner presents Accept vs.
    Reject. Populated only when consent simulation is enabled AND a banner
    was actually detected."""
    banner_detected: bool
    cmp: str | None = None                         # same label as ConsentSimulation.cmp_detected
    accept_found: bool
    reject_found: bool
    reject_via_text_fallback: bool = False         # matched only via loose text heuristic
    findings: list[DarkPatternFinding] = []
    # Raw measurements for the dashboard — allows the UI to render a
    # side-by-side comparison without re-measuring.
    accept_metrics: dict[str, float | bool | str] | None = None
    reject_metrics: dict[str, float | bool | str] | None = None
    # Phase 9e: visible text inside the banner container, capped to a
    # reasonable size so we don't ship the whole modal verbatim. Fed
    # into cookie_wall_detector for the EDPB Opinion 8/2024 check.
    banner_text: str | None = None


class ConsentSimulation(BaseModel):
    """Result of the optional second crawl that clicks the cookie banner."""
    enabled: bool                                  # was simulation requested at all
    accept_clicked: bool                           # did we actually click something
    cmp_detected: str | None = None                # which CMP we matched (or "text-fallback")
    note: str                                      # human-readable status for the UI
    pre_summary: dict[str, int] = {}               # cookie/tracker counts before consent
    post_summary: dict[str, int] = {}              # … after consent
    diff: ConsentDiff | None = None
    ux_audit: ConsentUxAudit | None = None         # dark-pattern audit of the banner itself


# ---------------------------------------------------------------------------
# Phase 11 — Performance suite (opt-in, gated by ScanRequest.performance_audit).
# Deliberately KEPT SEPARATE from the GDPR risk score: performance is not a
# compliance question. The score below is informational and uses a linear
# 0-100 scale with NO hard caps — every point of deduction is metric-anchored
# so an auditor can read it back ("score is 62 because LCP=3.4s and 14 of 23
# JS responses lack compression"). Cross-contamination with the GDPR score
# would dilute both reports' meaning.
# ---------------------------------------------------------------------------

class WebVitals(BaseModel):
    """Core Web Vitals + the two supporting paint metrics.

    All fields optional because the PerformanceObserver may miss entries
    (no layout shifts, no input events, fast load with no LCP candidate).
    Times are in **milliseconds**; CLS is unitless.
    """
    lcp_ms: float | None = None         # Largest Contentful Paint
    inp_ms: float | None = None         # Interaction to Next Paint (approx via long-tasks)
    cls: float | None = None            # Cumulative Layout Shift (unitless score)
    fcp_ms: float | None = None         # First Contentful Paint
    ttfb_ms: float | None = None        # Time to First Byte (navigation timing)


class RenderBlockingResource(BaseModel):
    """A resource that delayed first paint."""
    url: str
    resource_type: str                  # "script" / "stylesheet"
    size_bytes: int | None = None       # transferred bytes if captured


class OversizedAsset(BaseModel):
    """An asset whose transferred size exceeds the per-type budget."""
    url: str
    resource_type: str                  # "image" / "script" / "stylesheet" / "font"
    size_bytes: int
    threshold_bytes: int                # the budget this asset blew through


class UncompressedResponse(BaseModel):
    """A text-shaped response delivered without HTTP compression."""
    url: str
    resource_type: str                  # "script" / "stylesheet" / "document" / "xhr"
    size_bytes: int
    content_encoding: str | None        # verbatim header value (None / "identity")


class NetworkMetrics(BaseModel):
    """Aggregated network footprint of the page load."""
    total_requests: int = 0
    total_transfer_bytes: int = 0
    requests_by_type: dict[str, int] = {}     # "script" -> 12, "image" -> 34, …
    bytes_by_type: dict[str, int] = {}
    third_party_request_count: int = 0
    third_party_transfer_bytes: int = 0
    render_blocking: list[RenderBlockingResource] = []


class AssetAudit(BaseModel):
    """Per-asset opportunities for byte-shaving."""
    oversized_images: list[OversizedAsset] = []
    oversized_scripts: list[OversizedAsset] = []
    uncompressed_responses: list[UncompressedResponse] = []


class PerformanceReport(BaseModel):
    """Full Phase-11 performance report. Attached to ``ScanResponse.performance``
    only when ``ScanRequest.performance_audit`` was true.

    ``score`` is a linear 0-100 (higher = better), computed in
    ``modules.performance.scoring.score_performance``. NO hard caps; every
    point is traceable to a specific metric so the dashboard can render
    the breakdown without an explanation modal.
    """
    web_vitals: WebVitals = WebVitals()
    network_metrics: NetworkMetrics = NetworkMetrics()
    asset_audit: AssetAudit = AssetAudit()
    score: int = Field(ge=0, le=100, default=100)
    score_breakdown: dict[str, int] = {}      # "lcp" -> deducted points, etc.
    error: str | None = None                  # populated when audit could not run


class ScanResponse(BaseModel):
    target: str
    risk: RiskScore
    crawl: CrawlResult
    network: NetworkResult
    cookies: CookieReport
    privacy_analysis: PrivacyAnalysis
    forms: FormReport
    contact_channels: ContactChannelsReport
    widgets: ThirdPartyWidgetsReport
    security: SecurityAudit | None = None
    vulnerable_libraries: VulnerableLibrariesReport | None = None
    consent: ConsentSimulation | None = None
    # Phase 11 — opt-in; None when performance_audit was false (or the
    # audit step itself raised before producing a partial report).
    performance: PerformanceReport | None = None
    # Populated by storage.save_scan(). Not set during scan execution.
    id: str | None = None
    created_at: str | None = None


class ScanListItem(BaseModel):
    """Lightweight row for the history list."""
    id: str
    url: str
    score: int
    rating: RiskRating
    created_at: str


# ---------------------------------------------------------------------------
# Phase 3: async scan job responses
# ---------------------------------------------------------------------------

ScanJobStatusName = Literal["queued", "running", "done", "failed"]


class ScanJobCreated(BaseModel):
    """Return value of POST /scan/jobs — the id the client polls against."""
    id: str
    status: ScanJobStatusName
    url: str
    created_at: str


class ScanJobStatusResponse(BaseModel):
    """Return value of GET /scan/jobs/{id}. ``result`` is populated only
    when ``status == 'done'``; ``error`` only when ``status == 'failed'``."""
    id: str
    status: ScanJobStatusName
    url: str
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    result: ScanResponse | None = None
