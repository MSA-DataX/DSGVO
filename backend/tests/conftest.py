"""Shared fixtures + builders for the backend test suite.

Why builders and not a fixture library: most of the scoring / consent-
diff / form-analyzer logic keys off very specific model fields, so each
test wants to construct a minimal object with one or two fields set.
Full-featured fixtures would either carry so much default state that
tests drift (unclear what's actually under test) or require per-test
overrides that read worse than a plain builder call. These helpers
return ``BaseModel`` instances with sensible defaults for the fields
irrelevant to the test at hand — override what matters by keyword.
"""

from __future__ import annotations

from app.models import (
    ContactChannel,
    ContactChannelsReport,
    CookieEntry,
    CookieReport,
    CrawlResult,
    DataFlowEntry,
    FormField,
    FormFinding,
    FormInfo,
    FormReport,
    NetworkRequest,
    NetworkResult,
    PageInfo,
    PolicyTopicCoverage,
    PrivacyAnalysis,
    StorageEntry,
    ThirdPartyWidget,
    ThirdPartyWidgetsReport,
)


# ---------------------------------------------------------------------------
# Cookie + storage builders
# ---------------------------------------------------------------------------

def make_cookie(
    name: str = "session",
    domain: str = "example.com",
    *,
    category: str = "necessary",
    is_third_party: bool = False,
    is_session: bool = True,
    vendor: str | None = None,
    expires: float | None = None,
    reason: str = "test",
) -> CookieEntry:
    return CookieEntry(
        name=name, domain=domain, path="/",
        value_preview="ab…xy", value_length=10,
        expires=expires, secure=True, http_only=True, same_site="Lax",
        is_third_party=is_third_party, is_session=is_session,
        category=category,  # type: ignore[arg-type]
        vendor=vendor, reason=reason,
    )


def make_storage(
    key: str = "k",
    *,
    kind: str = "local",
    page_url: str = "https://example.com/",
    category: str = "necessary",
    vendor: str | None = None,
    reason: str = "test",
) -> StorageEntry:
    return StorageEntry(
        page_url=page_url, kind=kind,  # type: ignore[arg-type]
        key=key, value_preview="ab…", value_length=5,
        category=category,  # type: ignore[arg-type]
        vendor=vendor, reason=reason,
    )


def make_cookie_report(
    cookies: list[CookieEntry] | None = None,
    storage: list[StorageEntry] | None = None,
) -> CookieReport:
    """Build a CookieReport with summary numbers computed from contents
    so scoring/diff code that reads `summary[…]` sees consistent values.
    """
    cs = cookies or []
    ss = storage or []
    summary: dict[str, int] = {
        "total_cookies": len(cs),
        "third_party_cookies": sum(1 for c in cs if c.is_third_party),
        "session_cookies":     sum(1 for c in cs if c.is_session),
        "total_storage":       len(ss),
    }
    for cat in ("necessary", "functional", "analytics", "marketing", "unknown"):
        summary[f"cookies_{cat}"] = sum(1 for c in cs if c.category == cat)
        summary[f"storage_{cat}"] = sum(1 for s in ss if s.category == cat)
    return CookieReport(cookies=cs, storage=ss, summary=summary)


# ---------------------------------------------------------------------------
# Network builders
# ---------------------------------------------------------------------------

def make_request(
    url: str,
    *,
    method: str = "GET",
    resource_type: str = "script",
    status: int | None = 200,
    initiator_page: str = "https://example.com/",
    is_third_party: bool = True,
) -> NetworkRequest:
    # Cheap hostname/registered-domain derivation — good enough for tests.
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    # registered_domain: take last two labels for tests (doesn't need to be
    # tldextract-correct as long as it's deterministic).
    parts = host.split(".")
    registered = ".".join(parts[-2:]) if len(parts) >= 2 else host
    return NetworkRequest(
        url=url, domain=host, registered_domain=registered,
        method=method, resource_type=resource_type, status=status,
        initiator_page=initiator_page, is_third_party=is_third_party,
    )


def make_flow(
    domain: str,
    *,
    country: str = "EU",
    risk: str = "low",
    categories: list[str] | None = None,
    request_count: int = 1,
) -> DataFlowEntry:
    return DataFlowEntry(
        domain=domain, country=country,  # type: ignore[arg-type]
        request_count=request_count,
        categories=categories or [],
        risk=risk,  # type: ignore[arg-type]
    )


def make_network(
    requests: list[NetworkRequest] | None = None,
    data_flow: list[DataFlowEntry] | None = None,
) -> NetworkResult:
    return NetworkResult(requests=requests or [], data_flow=data_flow or [])


# ---------------------------------------------------------------------------
# Form + page builders
# ---------------------------------------------------------------------------

def make_form(
    *,
    method: str = "POST",
    action: str | None = "https://example.com/submit",
    page_url: str = "https://example.com/contact",
    fields: list[FormField] | None = None,
    has_checkbox: bool = False,
    has_pre_checked_box: bool = False,
    text_content: str = "",
    links: list[str] | None = None,
) -> FormInfo:
    return FormInfo(
        action=action, method=method, fields=fields or [],
        page_url=page_url, text_content=text_content,
        links=links or [], has_checkbox=has_checkbox,
        has_pre_checked_box=has_pre_checked_box,
    )


def make_field(
    name: str, type_: str = "text", required: bool = False,
    *, is_pre_checked: bool = False,
) -> FormField:
    # `type` is a keyword in Python but not a reserved word in kwargs; we
    # still prefer `type_` on the helper so callers don't shadow the
    # built-in and get nasty surprises.
    return FormField(
        name=name, type=type_, required=required,
        is_pre_checked=is_pre_checked,
    )


def make_page(
    url: str = "https://example.com/",
    *,
    forms: list[FormInfo] | None = None,
    iframes: list[str] | None = None,
    scripts: list[str] | None = None,
) -> PageInfo:
    return PageInfo(
        url=url, title="Home", status=200, depth=0,
        scripts=scripts or [], iframes=iframes or [],
        links=[], forms=forms or [],
        is_privacy_policy=False,
    )


def make_crawl(pages: list[PageInfo] | None = None) -> CrawlResult:
    return CrawlResult(
        start_url="https://example.com/",
        pages=pages or [make_page()],
        privacy_policy_url=None,
        imprint_url=None,
    )


# ---------------------------------------------------------------------------
# Scoring builders
# ---------------------------------------------------------------------------

def _full_coverage(*, third_country: bool = True, legal_basis: bool = True) -> PolicyTopicCoverage:
    return PolicyTopicCoverage(
        legal_basis_stated=legal_basis,
        data_categories_listed=True,
        retention_period_stated=True,
        third_party_recipients_listed=True,
        third_country_transfers_disclosed=third_country,
        user_rights_enumerated=True,
        contact_for_data_protection=True,
        cookie_section_present=True,
        children_data_addressed=True,
    )


def make_privacy(
    *,
    compliance_score: int = 80,
    error: str | None = None,
    issues: list | None = None,
    coverage: PolicyTopicCoverage | None = None,
    provider: str = "openai",
) -> PrivacyAnalysis:
    return PrivacyAnalysis(
        provider=provider,
        model="gpt-4o",
        policy_url="https://example.com/datenschutz",
        summary="Good policy.",
        issues=issues or [],
        coverage=coverage if coverage is not None else _full_coverage(),
        compliance_score=compliance_score,
        error=error,
    )


def make_form_report(
    forms: list[FormFinding] | None = None,
    *,
    pii_forms: int = 0,
    with_consent: int = 0,
    with_link: int = 0,
    with_issues: int = 0,
    search_forms: int = 0,
) -> FormReport:
    return FormReport(
        forms=forms or [],
        summary={
            "total_forms": (pii_forms + search_forms),
            "forms_collecting_pii": pii_forms,
            "forms_with_consent_checkbox": with_consent,
            "forms_with_privacy_link": with_link,
            "forms_with_issues": with_issues,
            "forms_search": search_forms,
        },
    )


def make_channels(channels: list[ContactChannel] | None = None) -> ContactChannelsReport:
    return ContactChannelsReport(channels=channels or [], summary={})


def make_channel(
    kind: str = "whatsapp",
    *,
    country: str = "USA",
    target: str = "https://wa.me/example",
    vendor: str | None = "Meta",
) -> ContactChannel:
    return ContactChannel(
        kind=kind,  # type: ignore[arg-type]
        target=target,
        vendor=vendor,
        country=country,  # type: ignore[arg-type]
        pages=["https://example.com/contact"],
    )


def make_widgets(widgets: list[ThirdPartyWidget] | None = None) -> ThirdPartyWidgetsReport:
    return ThirdPartyWidgetsReport(widgets=widgets or [], summary={})


def make_widget(
    kind: str = "youtube",
    *,
    category: str = "video",
    country: str = "USA",
    privacy_enhanced: bool = False,
    vendor: str | None = "Google",
    src: str = "https://www.youtube.com/embed/abc",
) -> ThirdPartyWidget:
    return ThirdPartyWidget(
        kind=kind,  # type: ignore[arg-type]
        category=category,  # type: ignore[arg-type]
        vendor=vendor,
        country=country,  # type: ignore[arg-type]
        src=src,
        pages=["https://example.com/"],
        privacy_enhanced=privacy_enhanced,
    )
