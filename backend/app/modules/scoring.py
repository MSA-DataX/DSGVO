"""GDPR risk-scoring engine.

Combines all module outputs into:

  - five sub-scores (cookies / tracking / data_transfer / privacy / forms)
  - one weighted final score (cookies 20% / tracking 20% /
    data_transfer 25% / privacy 25% / forms 10%)
  - a list of *named* hard caps that can pull the final score down even when
    the weighted average looks acceptable
  - a deduplicated, priority-ordered list of actionable recommendations

Why the weighted-sum + hard-cap design:

A pure weighted average can be gamed — a site can run a Meta Pixel without
consent and still score 75 because everything else is fine. That is wrong.
Hard caps express "no matter what, presence of X means the site cannot
score above N", e.g. US analytics with no consent management → cap 50.
The caps are *named* (each has a code + description) so the dashboard can
show **why** a score was capped — opaque scores are useless for an audit.

All sub-scores are 0-100 where higher = better (more compliant). Final
score uses the same scale and is bucketed into a 4-tier risk rating.
"""

from __future__ import annotations

from app.models import (
    CookieReport,
    FormReport,
    HardCap,
    NetworkResult,
    PrivacyAnalysis,
    Recommendation,
    RiskRating,
    RiskScore,
    SubScore,
)
from app.modules.form_analyzer import PII_CATEGORIES


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------

WEIGHTS: dict[str, float] = {
    "cookies":       0.20,
    "tracking":      0.20,
    "data_transfer": 0.25,
    "privacy":       0.25,
    "forms":         0.10,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "weights must sum to 1.0"


def _clamp(value: int) -> int:
    return max(0, min(100, value))


# ---------------------------------------------------------------------------
# Sub-scores
# ---------------------------------------------------------------------------

def _score_cookies(cookies: CookieReport) -> SubScore:
    notes: list[str] = []
    deduction = 0
    s = cookies.summary

    marketing = s.get("cookies_marketing", 0)
    analytics = s.get("cookies_analytics", 0)
    unknown = s.get("cookies_unknown", 0)
    third_party = s.get("third_party_cookies", 0)

    deduction += marketing * 6
    deduction += analytics * 3
    deduction += unknown * 2
    deduction += max(0, third_party - marketing - analytics) * 2  # other 3rd-party not yet bucketed

    if marketing:
        notes.append(f"{marketing} marketing cookie(s) detected (-6 each)")
    if analytics:
        notes.append(f"{analytics} analytics cookie(s) detected (-3 each)")
    if unknown:
        notes.append(f"{unknown} unclassified cookie(s) detected (-2 each)")
    if not notes:
        notes.append("No tracking/marketing cookies observed")

    return SubScore(
        name="cookies", score=_clamp(100 - deduction), weight=WEIGHTS["cookies"],
        weighted_contribution=_clamp(100 - deduction) * WEIGHTS["cookies"],
        notes=notes,
    )


def _score_tracking(cookies: CookieReport, network: NetworkResult) -> SubScore:
    """Tracking = web-storage + tracking-script presence.

    Cookies are scored separately; this catches the modern pattern of
    "no cookies but a Hotjar localStorage entry and 14 GA hits".
    """
    notes: list[str] = []
    deduction = 0
    s = cookies.summary

    storage_marketing = s.get("storage_marketing", 0)
    storage_analytics = s.get("storage_analytics", 0)
    deduction += storage_marketing * 8
    deduction += storage_analytics * 4
    if storage_marketing:
        notes.append(f"{storage_marketing} marketing entry/entries in web storage (-8 each)")
    if storage_analytics:
        notes.append(f"{storage_analytics} analytics entry/entries in web storage (-4 each)")

    tracker_domains = sum(
        1 for d in network.data_flow
        if any(c in d.categories for c in ("analytics", "marketing", "ai"))
    )
    deduction += tracker_domains * 5
    if tracker_domains:
        notes.append(f"{tracker_domains} tracking/analytics domain(s) contacted (-5 each)")

    if not notes:
        notes.append("No tracking observed beyond cookies")

    return SubScore(
        name="tracking", score=_clamp(100 - deduction), weight=WEIGHTS["tracking"],
        weighted_contribution=_clamp(100 - deduction) * WEIGHTS["tracking"],
        notes=notes,
    )


def _score_data_transfer(network: NetworkResult) -> SubScore:
    notes: list[str] = []
    high = sum(1 for d in network.data_flow if d.risk == "high")
    medium = sum(1 for d in network.data_flow if d.risk == "medium")
    unknown_country = sum(1 for d in network.data_flow if d.country == "Unknown")
    deduction = high * 12 + medium * 5 + unknown_country * 2

    if high:
        notes.append(f"{high} high-risk transfer destination(s) (-12 each)")
    if medium:
        notes.append(f"{medium} medium-risk transfer destination(s) (-5 each)")
    if unknown_country:
        notes.append(f"{unknown_country} destination(s) with unknown jurisdiction (-2 each)")
    if not notes:
        notes.append("All observed destinations are EU/EEA or no third parties contacted")

    return SubScore(
        name="data_transfer", score=_clamp(100 - deduction), weight=WEIGHTS["data_transfer"],
        weighted_contribution=_clamp(100 - deduction) * WEIGHTS["data_transfer"],
        notes=notes,
    )


def _score_privacy(privacy: PrivacyAnalysis) -> SubScore:
    """Translate the AI privacy analysis into a sub-score.

    The ``error`` field in :class:`PrivacyAnalysis` mixes two very different
    conditions:

      - **Fatal**: the model returned non-JSON, failed schema validation,
        or the call itself raised. `compliance_score` is unreliable → 0.
      - **Partial**: the model returned a well-formed envelope but we
        dropped N individual issues whose schema was off
        (error starts with ``"dropped "``). The rest — summary, coverage,
        and the overall ``compliance_score`` — is still trustworthy.
        We MUST honor the score; defaulting to 0 here was a bug that made
        the UI show "85/100" in the policy card but "0" in the sub-score.

    Plus two explicit signal values (``no_provider_configured``,
    ``no_policy_text``) which are handled individually.
    """
    notes: list[str] = []
    err = privacy.error

    if err == "no_provider_configured":
        # Couldn't measure — don't penalize. Neutral 50 so the final score
        # isn't pushed either direction. Auditor sees provider="none".
        notes.append("AI provider not configured — privacy sub-score is neutral (50)")
        score = 50
    elif err == "no_policy_text":
        notes.append("No privacy policy could be fetched")
        score = 0
    elif err and not err.startswith("dropped "):
        # Fatal AI error (bad JSON, schema mismatch, exception)
        notes.append(f"AI analysis failed ({err}); defaulting to 0")
        score = 0
    else:
        # Success, or partial-parse with a valid compliance_score.
        score = privacy.compliance_score
        notes.append(f"AI compliance score: {score}/100")
        if err and err.startswith("dropped "):
            notes.append(f"Partial parse: {err} — score still valid")
        if privacy.coverage:
            missing = [k for k, v in privacy.coverage.model_dump().items() if not v]
            if missing:
                notes.append(f"Missing coverage: {', '.join(missing)}")

    return SubScore(
        name="privacy", score=_clamp(score), weight=WEIGHTS["privacy"],
        weighted_contribution=_clamp(score) * WEIGHTS["privacy"],
        notes=notes,
    )


def _score_forms(forms: FormReport) -> SubScore:
    notes: list[str] = []
    s = forms.summary
    pii_forms = s.get("forms_collecting_pii", 0)
    no_consent = pii_forms - s.get("forms_with_consent_checkbox", 0)
    no_link = pii_forms - s.get("forms_with_privacy_link", 0)
    issues = s.get("forms_with_issues", 0)
    deduction = max(0, no_consent) * 12 + max(0, no_link) * 8 + issues * 2

    if no_consent > 0:
        notes.append(f"{no_consent} PII form(s) without a consent checkbox (-12 each)")
    if no_link > 0:
        notes.append(f"{no_link} PII form(s) without a link to the privacy policy (-8 each)")
    if not notes:
        notes.append("No problematic forms detected")

    return SubScore(
        name="forms", score=_clamp(100 - deduction), weight=WEIGHTS["forms"],
        weighted_contribution=_clamp(100 - deduction) * WEIGHTS["forms"],
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Hard caps
# ---------------------------------------------------------------------------

def _has_consent_cmp(cookies: CookieReport) -> bool:
    """True if a known consent-management-platform cookie is present."""
    cmp_vendors = {"onetrust", "cookiebot", "borlabs", "usercentrics", "orestbida"}
    for c in cookies.cookies:
        if c.vendor in cmp_vendors:
            return True
        if c.category == "necessary" and "consent" in c.reason.lower():
            return True
    return False


def _compute_caps(
    cookies: CookieReport,
    network: NetworkResult,
    privacy: PrivacyAnalysis,
    has_policy: bool,
) -> list[HardCap]:
    caps: list[HardCap] = []
    has_cmp = _has_consent_cmp(cookies)

    us_analytics = any(
        d.country == "USA" and "analytics" in d.categories
        for d in network.data_flow
    )
    us_marketing = any(
        d.country == "USA" and "marketing" in d.categories
        for d in network.data_flow
    )

    if us_analytics and not has_cmp:
        caps.append(HardCap(
            code="us_analytics_no_consent",
            description="Site loads US analytics (e.g. GA, Clarity) but no consent-management cookie was observed.",
            cap_value=50,
        ))
    if us_marketing and not has_cmp:
        caps.append(HardCap(
            code="us_marketing_no_consent",
            description="Site loads US marketing pixels (e.g. Meta, DoubleClick) but no consent-management cookie was observed.",
            cap_value=40,
        ))

    # § 25 TDDDG (German Telemedia Data Protection Act, successor of the
    # ePrivacy transposition) — reading from OR writing to the user's
    # terminal device requires opt-in consent unless *strictly necessary*
    # for the requested service. The regulators (Datenschutzkonferenz) have
    # made clear that loading a third-party CDN, font, script, or pixel is
    # rarely "strictly necessary" — the site operator can self-host or at
    # least gate the load behind the consent banner. Country (EU vs US) is
    # IRRELEVANT for § 25 — even an EU-hosted jsdelivr call is covered.
    #
    # Tiered severity:
    #   heavy (marketing / analytics / ai) → presumed non-necessary → cap 50
    #   light (cdn / fonts / infra) → still needs consent, more defensible → cap 70
    #   nothing else → don't trigger
    if network.data_flow and not has_cmp:
        heavy = {"marketing", "analytics", "ai"}
        light = {"cdn", "fonts", "infra"}
        saw_heavy = any(set(d.categories) & heavy for d in network.data_flow)
        saw_light = any(set(d.categories) & light for d in network.data_flow)
        if saw_heavy:
            # The existing us_* caps already capture the country+consent combo
            # for US trackers; this cap additionally catches the EU/Unknown
            # case (e.g. Matomo Cloud loaded pre-consent).
            caps.append(HardCap(
                code="tdddg_non_essential_without_consent",
                description="§ 25 TDDDG: analytics or marketing third parties are loaded before a consent banner. Country (EU/US) is irrelevant here — any non-strictly-necessary load needs opt-in.",
                cap_value=50,
            ))
        elif saw_light:
            caps.append(HardCap(
                code="tdddg_third_party_without_consent",
                description="§ 25 TDDDG: the site loads third-party resources (CDN / fonts / infra) before consent. Regulators rarely accept these as 'strictly necessary' — self-host or gate behind the consent banner.",
                cap_value=70,
            ))
    if not has_policy:
        caps.append(HardCap(
            code="no_privacy_policy",
            description="No privacy policy page could be located on the site.",
            cap_value=30,
        ))
    if (
        privacy.coverage
        and not privacy.coverage.third_country_transfers_disclosed
        and any(d.country in ("USA", "Other") for d in network.data_flow)
    ):
        caps.append(HardCap(
            code="policy_silent_on_third_country_transfer",
            description="Site transfers data outside the EU/EEA but the privacy policy does not disclose it.",
            cap_value=60,
        ))
    if (
        privacy.coverage
        and not privacy.coverage.legal_basis_stated
        and privacy.error is None
    ):
        caps.append(HardCap(
            code="no_legal_basis_stated",
            description="Privacy policy does not state any Art. 6 GDPR legal basis for processing.",
            cap_value=55,
        ))
    return caps


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

def _build_recommendations(
    cookies: CookieReport,
    network: NetworkResult,
    privacy: PrivacyAnalysis,
    forms: FormReport,
    caps: list[HardCap],
) -> list[Recommendation]:
    recs: list[Recommendation] = []

    # --- top-priority items derived from caps ---------------------------
    cap_codes = {c.code for c in caps}
    if "no_privacy_policy" in cap_codes:
        recs.append(Recommendation(
            priority="high",
            title="Publish a privacy policy",
            detail="No privacy policy could be located. Publishing one is mandatory under Art. 13/14 GDPR. "
                   "Link it from the footer using a stable URL containing 'datenschutz' or 'privacy'.",
            related=["no_privacy_policy"],
        ))
    if "us_analytics_no_consent" in cap_codes or "us_marketing_no_consent" in cap_codes:
        recs.append(Recommendation(
            priority="high",
            title="Implement a consent-management platform (CMP)",
            detail="US analytics or marketing trackers are loading without a detectable consent banner. "
                   "Block these scripts until the user has actively consented (opt-in, not opt-out).",
            related=[c for c in cap_codes if c.startswith("us_")],
        ))
    if "tdddg_non_essential_without_consent" in cap_codes:
        recs.append(Recommendation(
            priority="high",
            title="Block analytics / marketing trackers until the user consents (§ 25 TDDDG)",
            detail="§ 25 TDDDG requires opt-in consent before reading from or writing to the user's "
                   "browser. Analytics/marketing third parties fired during this scan with no consent "
                   "banner observed — this exposes the operator to fines up to 300 000 EUR. Fix: "
                   "load these scripts only after the user has actively clicked 'Accept' on a CMP "
                   "(Cookiebot, Usercentrics, Borlabs, etc.), or remove them entirely.",
            related=["tdddg_non_essential_without_consent"],
        ))
    if "tdddg_third_party_without_consent" in cap_codes:
        # Aggregate domains that triggered this — useful context for the fix.
        third_party_domains = sorted({d.domain for d in network.data_flow})
        sample = ", ".join(third_party_domains[:5])
        more = f" (and {len(third_party_domains) - 5} more)" if len(third_party_domains) > 5 else ""
        recs.append(Recommendation(
            priority="medium",
            title="Self-host or gate third-party CDN / font loads behind consent (§ 25 TDDDG)",
            detail=f"The site loads assets from third parties before any consent is obtained: "
                   f"{sample}{more}. Even EU-hosted CDNs (e.g. jsDelivr, unpkg, Google Fonts) are "
                   f"not automatically 'strictly necessary' under § 25 TDDDG — the conservative "
                   f"interpretation from German regulators is that you must either self-host the "
                   f"assets or load them only after consent. Lowest-friction fix: download the "
                   f"library once, serve it from your own origin, done.",
            related=third_party_domains,
        ))
    if "policy_silent_on_third_country_transfer" in cap_codes:
        recs.append(Recommendation(
            priority="high",
            title="Disclose third-country transfers in the privacy policy",
            detail="Data is being transferred outside the EU/EEA but the policy does not mention it. "
                   "Name the recipients, the country, the safeguard used (SCCs, adequacy decision), "
                   "and where users can request a copy of those safeguards.",
            related=["policy_silent_on_third_country_transfer"],
        ))
    if "no_legal_basis_stated" in cap_codes:
        recs.append(Recommendation(
            priority="high",
            title="State the Art. 6 legal basis for each processing activity",
            detail="The policy must name the legal basis (consent, contract, legitimate interest, etc.) "
                   "for every category of processing. List them per processing purpose.",
            related=["no_legal_basis_stated"],
        ))

    # --- per-domain transfer recommendations ----------------------------
    high_us = sorted({
        d.domain for d in network.data_flow
        if d.country == "USA" and d.risk == "high"
    })
    if high_us:
        sample = ", ".join(high_us[:5])
        more = f" (and {len(high_us) - 5} more)" if len(high_us) > 5 else ""
        recs.append(Recommendation(
            priority="high",
            title="Replace or properly safeguard high-risk US transfers",
            detail=f"High-risk transfers detected to: {sample}{more}. "
                   "Either move to an EU-hosted alternative, or document SCCs + a Transfer Impact "
                   "Assessment (Schrems II) for each recipient.",
            related=high_us,
        ))

    # --- AI-detected policy issues → recommendations --------------------
    seen_titles: set[str] = set()
    for issue in privacy.issues[:8]:  # cap to keep the list usable
        title = f"Fix policy issue: {issue.category.replace('_', ' ')}"
        if title in seen_titles:
            continue
        seen_titles.add(title)
        recs.append(Recommendation(
            priority=issue.severity,  # severity literal matches priority literal
            title=title,
            detail=issue.description,
            related=[issue.category],
        ))

    # --- form-level recommendations -------------------------------------
    # Match against structured fields (purpose, has_consent_checkbox,
    # has_privacy_link) rather than grepping issue texts — the search-form
    # notice literally contains "no consent checkbox" (in a negated sense),
    # which fooled the old substring filter.
    def _is_collection_pii(f) -> bool:
        return (
            f.purpose == "collection"
            and bool(set(f.collected_data) & PII_CATEGORIES)
        )

    forms_no_consent = [f.page_url for f in forms.forms
                        if _is_collection_pii(f) and not f.has_consent_checkbox]
    if forms_no_consent:
        recs.append(Recommendation(
            priority="high",
            title="Add an explicit consent checkbox to forms collecting personal data",
            detail=f"{len(forms_no_consent)} form(s) collect personal data without an unticked consent "
                   "checkbox: " + ", ".join(forms_no_consent[:5])
                   + (f" (and {len(forms_no_consent) - 5} more)" if len(forms_no_consent) > 5 else ""),
            related=forms_no_consent,
        ))

    forms_no_link = [f.page_url for f in forms.forms
                     if _is_collection_pii(f) and not f.has_privacy_link]
    if forms_no_link:
        recs.append(Recommendation(
            priority="medium",
            title="Link to the privacy policy from every form collecting personal data",
            detail=f"{len(forms_no_link)} form(s) lack a visible privacy-policy link adjacent to the inputs.",
            related=forms_no_link,
        ))

    # --- cookie hygiene -------------------------------------------------
    cookies_unknown = cookies.summary.get("cookies_unknown", 0)
    if cookies_unknown:
        recs.append(Recommendation(
            priority="low",
            title="Document or remove unclassified cookies",
            detail=f"{cookies_unknown} cookie(s) could not be auto-classified. Either remove them or add an "
                   "entry to the cookie table in the privacy policy describing purpose + retention.",
            related=["cookies_unknown"],
        ))

    # --- dedupe + cap ---------------------------------------------------
    deduped: list[Recommendation] = []
    seen: set[tuple[str, str]] = set()
    for r in recs:
        key = (r.priority, r.title)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    priority_order = {"high": 0, "medium": 1, "low": 2}
    deduped.sort(key=lambda r: priority_order[r.priority])
    return deduped[:15]


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------

def _rate(score: int) -> RiskRating:
    if score >= 80:
        return "low"
    if score >= 60:
        return "medium"
    if score >= 40:
        return "high"
    return "critical"


def compute_risk(
    cookies: CookieReport,
    network: NetworkResult,
    privacy: PrivacyAnalysis,
    forms: FormReport,
    has_policy: bool,
) -> RiskScore:
    sub_scores = [
        _score_cookies(cookies),
        _score_tracking(cookies, network),
        _score_data_transfer(network),
        _score_privacy(privacy),
        _score_forms(forms),
    ]
    weighted = round(sum(s.weighted_contribution for s in sub_scores))
    weighted = _clamp(weighted)

    caps = _compute_caps(cookies, network, privacy, has_policy)
    final = weighted
    for cap in caps:
        if final > cap.cap_value:
            final = cap.cap_value

    recommendations = _build_recommendations(cookies, network, privacy, forms, caps)

    return RiskScore(
        score=final,
        rating=_rate(final),
        weighted_score=weighted,
        sub_scores=sub_scores,
        applied_caps=caps,
        recommendations=recommendations,
    )
