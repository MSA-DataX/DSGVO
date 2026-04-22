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

from urllib.parse import urlparse

from app.models import (
    ConsentSimulation,
    ContactChannelsReport,
    CookieReport,
    FormReport,
    HardCap,
    NetworkResult,
    PrivacyAnalysis,
    Recommendation,
    RiskRating,
    RiskScore,
    SubScore,
    ThirdPartyWidgetsReport,
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

def _has_external_google_fonts(network: NetworkResult) -> bool:
    """Detect requests to Google's font servers.

    ``fonts.googleapis.com`` (CSS loader) and ``fonts.gstatic.com`` (the
    actual font binaries) are the exact hostnames flagged by LG München I
    in its 2022 ruling — loading either from Google is a confirmed GDPR
    violation under that case law, cap required.
    """
    for r in network.requests:
        host = (urlparse(r.url).hostname or "").lower()
        if host in ("fonts.googleapis.com", "fonts.gstatic.com"):
            return True
    return False


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
    has_imprint: bool,
    channels: ContactChannelsReport,
    widgets: ThirdPartyWidgetsReport,
    consent: ConsentSimulation | None,
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

    # § 5 TMG / Telemediengesetz — German commercial sites must have an
    # Impressum. If we couldn't find one via crawl OR common-path probe,
    # that's a concrete Abmahnrisiko.
    if not has_imprint:
        caps.append(HardCap(
            code="no_imprint",
            description="No Impressum page could be located. § 5 TMG requires German commercial sites to publish an imprint with operator identity, contact, and register information.",
            cap_value=50,
        ))

    # Google Fonts loaded externally from google.com servers is a confirmed
    # GDPR violation under LG München I 2022. The ruling specifically
    # condemned the unnecessary transmission of user IP addresses to Google
    # — easy to fix (self-host fonts) and hard to defend.
    if _has_external_google_fonts(network):
        caps.append(HardCap(
            code="google_fonts_external",
            description="Site loads Google Fonts from Google's servers (fonts.googleapis.com / fonts.gstatic.com). Under LG München I ruling (2022) this is a GDPR violation — self-host the fonts instead.",
            cap_value=65,
        ))

    # Third-party widgets (YouTube in tracking mode, Google Maps, chat
    # widgets, social-login SDKs) loaded pre-consent. The privacy-enhanced
    # variants (youtube-nocookie, Vimeo ?dnt=1, OpenStreetMap) don't
    # trigger; they're the recommended fix.
    if not has_cmp:
        tracking_video = [
            w for w in widgets.widgets
            if w.category == "video" and not w.privacy_enhanced
        ]
        chat_widgets = [w for w in widgets.widgets if w.category == "chat"]
        tracking_maps = [
            w for w in widgets.widgets
            if w.category == "map" and not w.privacy_enhanced
        ]
        if tracking_video or chat_widgets:
            caps.append(HardCap(
                code="embed_or_chat_without_consent",
                description="Site embeds tracking-variant video players (YouTube instead of youtube-nocookie) or chat widgets (Intercom, Drift, Zendesk, …) that fire network requests before the user consents.",
                cap_value=55,
            ))
        elif tracking_maps:
            caps.append(HardCap(
                code="map_embed_without_consent",
                description="Site embeds Google Maps / Mapbox / Bing Maps before consent. Use a click-to-activate overlay or switch to OpenStreetMap export embed.",
                cap_value=70,
            ))

    # Contact channels to US platforms (WhatsApp / Messenger / Meta /
    # TikTok etc.) WITHOUT mention in the privacy policy — the AI analyzer
    # handles the policy-cross-check separately, but having the channel at
    # all without a stated legal basis is a hard signal. We only apply the
    # cap when the policy is present and the AI explicitly says
    # third-country transfers are NOT disclosed.
    high_risk_channels = [c for c in channels.channels if c.country in ("USA", "Other")]
    if (
        high_risk_channels
        and privacy.coverage
        and not privacy.coverage.third_country_transfers_disclosed
    ):
        caps.append(HardCap(
            code="contact_channel_transfer_not_disclosed",
            description=f"Site exposes {len(high_risk_channels)} contact channel(s) that transfer data outside the EU/EEA (e.g. WhatsApp, Meta, TikTok) but the policy does not disclose this.",
            cap_value=60,
        ))

    # Consent-banner dark patterns — cap depends on the worst finding.
    # Rationale: the EDPB position is that a banner with a dark pattern
    # does not produce valid consent, so *everything* the site loads after
    # that banner is effectively without legal basis. We only cap when a
    # HIGH finding is present so we don't double-penalise subtle issues
    # that already show up as MEDIUM notes.
    if consent and consent.ux_audit:
        has_high = any(f.severity == "high" for f in consent.ux_audit.findings)
        has_medium = any(f.severity == "medium" for f in consent.ux_audit.findings)
        if has_high:
            # Typical trigger: "no_direct_reject" — banner has Accept +
            # Settings only. Invalid consent → cap hard.
            caps.append(HardCap(
                code="consent_dark_pattern_high",
                description="Consent banner contains a HIGH-severity dark pattern (e.g. no first-level 'Reject all' button). Under EDPB Guidelines 03/2022 this invalidates the obtained consent — the site effectively has no legal basis for the tracking it runs.",
                cap_value=45,
            ))
        elif has_medium:
            caps.append(HardCap(
                code="consent_dark_pattern_medium",
                description="Consent banner shows asymmetric treatment of Accept vs Reject (size, position, or visual prominence). Steers users toward consent and weakens the 'freely given' requirement.",
                cap_value=65,
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
    channels: ContactChannelsReport,
    widgets: ThirdPartyWidgetsReport,
    consent: ConsentSimulation | None,
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

    # --- Third-party widgets (Phase 2) ---------------------------------
    # Tracking-variant video embeds — actionable fix: swap the host.
    tracking_video_widgets = [
        w for w in widgets.widgets
        if w.category == "video" and not w.privacy_enhanced
    ]
    if tracking_video_widgets:
        sample = ", ".join(sorted({w.vendor or w.kind for w in tracking_video_widgets}))
        recs.append(Recommendation(
            priority="high",
            title="Switch video embeds to the privacy-enhanced variant",
            detail=f"Detected tracking-variant video embeds ({sample}). Quick wins: "
                   f"replace `youtube.com/embed/VIDEO_ID` with `youtube-nocookie.com/embed/VIDEO_ID` "
                   f"(zero functional difference, no cookies until play); append `?dnt=1` to "
                   f"`player.vimeo.com/video/...` URLs. Alternatively wrap each video in a "
                   f"click-to-activate overlay so the iframe only loads after the user clicks Play.",
            related=[w.src for w in tracking_video_widgets[:5]],
        ))

    tracking_map_widgets = [
        w for w in widgets.widgets
        if w.category == "map" and not w.privacy_enhanced
    ]
    if tracking_map_widgets:
        recs.append(Recommendation(
            priority="medium",
            title="Replace map embeds with a privacy-friendly alternative",
            detail="Google Maps / Mapbox / Bing Maps iframes load trackers and transmit the "
                   "visitor's IP to the provider before any interaction. Options: "
                   "(1) OpenStreetMap via the export-embed URL (fully EU, no tracking), "
                   "(2) click-to-activate overlay on the existing map, "
                   "(3) a static map image generated server-side.",
            related=[w.vendor or w.kind for w in tracking_map_widgets[:5]],
        ))

    chat_widgets = [w for w in widgets.widgets if w.category == "chat"]
    if chat_widgets:
        names = ", ".join(sorted({w.vendor or w.kind for w in chat_widgets}))
        recs.append(Recommendation(
            priority="high",
            title="Gate chat widgets behind consent",
            detail=f"Chat widget(s) detected: {names}. These scripts load session cookies and "
                   f"transmit visitor metadata as soon as the page opens — well before the user "
                   f"decides to chat. Load the widget script only after the user actively opts in "
                   f"(CMP consent or a user-triggered 'Chat with us' button), and name the "
                   f"provider + US transfer in the privacy policy.",
            related=[w.vendor or w.kind for w in chat_widgets],
        ))

    auth_widgets = [w for w in widgets.widgets if w.category == "auth"]
    if auth_widgets:
        names = ", ".join(sorted({w.vendor or w.kind for w in auth_widgets}))
        recs.append(Recommendation(
            priority="medium",
            title="Load social-login SDKs only on pages that need them",
            detail=f"Social-login SDK(s) detected: {names}. Many sites include these on every "
                   f"page even though the button exists only on /login or /register. Load the "
                   f"SDK lazily (e.g. after a user clicks 'Sign in with …') so non-authenticating "
                   f"visitors don't trigger third-party script execution and the associated "
                   f"cookie/fingerprint leakage.",
            related=[w.vendor or w.kind for w in auth_widgets],
        ))

    # --- Consent-banner dark patterns ----------------------------------
    if consent and consent.ux_audit and consent.ux_audit.findings:
        # Give one grouped recommendation per finding code so the detail
        # text can be specific (the generic cap description is too abstract
        # for the fix).
        code_details: dict[str, tuple[str, str, str]] = {
            "no_direct_reject": (
                "high",
                "Add a first-level 'Reject all' button to the consent banner",
                "The banner only offers 'Accept' + 'Settings'. Under EDPB Guidelines "
                "03/2022 (§ 3.2) and the German DSK, refusing must be as easy as "
                "consenting — one click, same level, same visual weight. Put a "
                "'Reject all' button next to 'Accept all'. This alone is the most "
                "common Datenschutzbehörde finding in Germany (cf. DSK decision "
                "Tracking 2023).",
            ),
            "reject_much_smaller": (
                "high",
                "Make Reject and Accept buttons the same size",
                "Reject is visually smaller than Accept. Auditable fix: give both "
                "buttons identical width, height, padding, and font size. If you "
                "want visual hierarchy, keep it symmetric (both plain, or both "
                "filled in your brand color).",
            ),
            "reject_below_fold": (
                "medium",
                "Position Reject in the same viewport region as Accept",
                "Reject is below the initial viewport; the user must scroll to find "
                "it. Auditable fix: both buttons visible without scrolling on 1366×768, "
                "ideally side-by-side or one above the other within the banner.",
            ),
            "reject_low_prominence": (
                "medium",
                "Style Reject with the same prominence as Accept",
                "Reject has weaker font weight, no background, or lower opacity than "
                "Accept. Auditable fix: both buttons share the same CSS class for "
                "background, color, weight, and border. Visual hierarchy implies "
                "preferred action; that's exactly what EDPB forbids for consent.",
            ),
            "reject_via_text_fallback": (
                "low",
                "Verify banner layout manually",
                "Our automated detection matched Reject only via multilingual text "
                "heuristics — measurements below may be imprecise. Manually verify "
                "that Reject is a visible first-level button.",
            ),
            "forced_interaction": (
                "high",
                "Don't block content without offering a direct opt-out",
                "The banner blocks the page with no refusal option. Users cannot "
                "consent freely under Art. 4(11) GDPR when the only path forward is "
                "to accept.",
            ),
        }
        seen_codes: set[str] = set()
        for f in consent.ux_audit.findings:
            if f.code in seen_codes:
                continue
            seen_codes.add(f.code)
            meta = code_details.get(f.code)
            if meta is None:
                continue
            priority, title, detail = meta
            recs.append(Recommendation(
                priority=priority,  # type: ignore[arg-type]
                title=title,
                detail=detail,
                related=[f"consent:{f.code}"],
            ))

    # --- Google Fonts (LG München I 2022) ------------------------------
    if "google_fonts_external" in cap_codes:
        recs.append(Recommendation(
            priority="high",
            title="Self-host your fonts instead of loading from Google",
            detail="Google Fonts requests transmit the visitor's IP to Google (USA) without consent. "
                   "LG München I (Az. 3 O 17493/20, 20.01.2022) ruled this a GDPR violation and "
                   "awarded damages against the operator. Fix: download the font files once, serve "
                   "them from your own origin (e.g. via @font-face with local .woff2 files), drop "
                   "the <link> to fonts.googleapis.com. Tools like google-webfonts-helper automate "
                   "this in under a minute.",
            related=["google_fonts_external"],
        ))

    # --- § 5 TMG Impressum --------------------------------------------
    if "no_imprint" in cap_codes:
        recs.append(Recommendation(
            priority="high",
            title="Publish an Impressum (§ 5 TMG)",
            detail="No imprint page could be located. Commercial German websites must publish an "
                   "Impressum with at least: operator name and legal form, postal address, contact "
                   "(email + phone or fax), register (Handelsregister) info where applicable, VAT "
                   "ID (USt-IdNr.), and, for journalistic content, a responsible person (V.i.S.d.P.). "
                   "Missing or hidden imprint is the single most common Abmahngrund (cease-and-"
                   "desist trigger) in Germany. Link from the footer at a stable URL such as "
                   "/impressum.",
            related=["no_imprint"],
        ))

    # --- Contact channels -------------------------------------------------
    # Always worth surfacing a recommendation when we found any US / non-EU
    # channel, regardless of whether the cap triggered — the cap only fires
    # if the policy is *silent*, but the recommendation is still useful as
    # a checklist item for the operator.
    us_channels = [c for c in channels.channels if c.country in ("USA", "Other")]
    if us_channels:
        by_kind: dict[str, int] = {}
        for c in us_channels:
            by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
        kinds_str = ", ".join(f"{n}× {k.replace('_', ' ')}" for k, n in sorted(by_kind.items()))
        priority = "high" if "contact_channel_transfer_not_disclosed" in cap_codes else "medium"
        recs.append(Recommendation(
            priority=priority,
            title="Document each non-EU contact channel in the privacy policy",
            detail=f"The site exposes contact channels that transfer user data outside the EU/EEA "
                   f"({kinds_str}). For each one the policy must name the provider (e.g. 'Meta "
                   f"Platforms Inc., WhatsApp'), state the legal basis (typically Art. 6(1)(a) "
                   f"consent because the user initiates contact, or Art. 6(1)(f) legitimate "
                   f"interest for publicly-facing profile links), and disclose the third-country "
                   f"transfer with its safeguard (SCCs / EU-US Data Privacy Framework).",
            related=sorted({c.kind for c in us_channels}),
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
    channels: ContactChannelsReport,
    widgets: ThirdPartyWidgetsReport,
    has_policy: bool,
    has_imprint: bool,
    consent: ConsentSimulation | None = None,
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

    caps = _compute_caps(
        cookies=cookies, network=network, privacy=privacy,
        has_policy=has_policy, has_imprint=has_imprint,
        channels=channels, widgets=widgets, consent=consent,
    )
    final = weighted
    for cap in caps:
        if final > cap.cap_value:
            final = cap.cap_value

    recommendations = _build_recommendations(
        cookies, network, privacy, forms, channels, widgets, consent, caps,
    )

    return RiskScore(
        score=final,
        rating=_rate(final),
        weighted_score=weighted,
        sub_scores=sub_scores,
        applied_caps=caps,
        recommendations=recommendations,
    )
