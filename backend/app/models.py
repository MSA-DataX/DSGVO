from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, HttpUrl, Field


Risk = Literal["low", "medium", "high"]
Region = Literal["EU", "USA", "Other", "Unknown"]
CookieCategory = Literal["necessary", "functional", "analytics", "marketing", "unknown"]
StorageKind = Literal["local", "session"]
Severity = Literal["low", "medium", "high"]
FormPurpose = Literal["collection", "search", "authentication", "unknown"]
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
    links: list[str] = []
    forms: list[FormInfo] = []
    storage: list[StorageItem] = []
    is_privacy_policy: bool = False


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
    description: str
    excerpt: str | None = None        # short verbatim quote from the policy
    # Ready-to-paste draft paragraph the operator can add to the policy to
    # close the finding. In the *same language as the policy* (so the user
    # can actually paste it in). May be null when the finding doesn't map
    # to an insertable text (e.g. "unclear wording" — operator must rewrite
    # existing copy rather than append new). The UI MUST render this with
    # a legal disclaimer; see PrivacyAnalysisCard.
    suggested_text: str | None = None


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


class ConsentSimulation(BaseModel):
    """Result of the optional second crawl that clicks the cookie banner."""
    enabled: bool                                  # was simulation requested at all
    accept_clicked: bool                           # did we actually click something
    cmp_detected: str | None = None                # which CMP we matched (or "text-fallback")
    note: str                                      # human-readable status for the UI
    pre_summary: dict[str, int] = {}               # cookie/tracker counts before consent
    post_summary: dict[str, int] = {}              # … after consent
    diff: ConsentDiff | None = None


class ScanResponse(BaseModel):
    target: str
    risk: RiskScore
    crawl: CrawlResult
    network: NetworkResult
    cookies: CookieReport
    privacy_analysis: PrivacyAnalysis
    forms: FormReport
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
