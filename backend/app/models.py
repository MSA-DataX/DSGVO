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


class FormField(BaseModel):
    name: str | None = None
    type: str | None = None
    required: bool = False


class FormInfo(BaseModel):
    action: str | None
    method: str
    fields: list[FormField]
    page_url: str
    text_content: str = ""           # visible text inside the form (labels, legal copy)
    links: list[str] = []            # absolute hrefs found inside the form
    has_checkbox: bool = False


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


class NetworkResult(BaseModel):
    requests: list[NetworkRequest]
    data_flow: list[DataFlowEntry]


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
