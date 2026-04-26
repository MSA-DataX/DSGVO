"""Tests for scoring.py.

Coverage targets:
- Each sub-score function's deduction arithmetic and edge cases.
- Each named hard-cap code: trigger condition → cap appears in output.
- compute_risk integration: weighted average, cap lowers final score,
  recommendations list non-empty when problems exist.
- `_score_privacy` distinguishes fatal errors from partial parses correctly.
"""

from __future__ import annotations

import time

import pytest

from app.models import (
    DarkPatternFinding,
    DnsSecurityInfo,
    ConsentSimulation,
    ConsentUxAudit,
    SecurityAudit,
    SecurityHeaderFinding,
    TlsInfo,
    VulnerableLibrariesReport,
    VulnerableLibrary,
)
from app.modules.scoring import (
    WEIGHTS,
    _score_cookies,
    _score_data_transfer,
    _score_forms,
    _score_privacy,
    _score_tracking,
    compute_risk,
)

from .conftest import (
    make_channels,
    make_channel,
    make_cookie,
    make_cookie_report,
    make_flow,
    make_form_report,
    make_network,
    make_privacy,
    make_request,
    make_storage,
    make_widgets,
    make_widget,
)


# ---------------------------------------------------------------------------
# _score_cookies
# ---------------------------------------------------------------------------

class TestScoreCookies:
    def test_clean_site_scores_100(self):
        report = make_cookie_report()
        sub = _score_cookies(report)
        assert sub.score == 100
        assert sub.name == "cookies"
        assert sub.weight == WEIGHTS["cookies"]

    def test_marketing_cookies_deduct_6_each(self):
        report = make_cookie_report(cookies=[
            make_cookie("fbp", ".fb.com", category="marketing"),
            make_cookie("fr", ".fb.com", category="marketing"),
        ])
        sub = _score_cookies(report)
        assert sub.score == 100 - 6 * 2

    def test_analytics_cookies_deduct_3_each(self):
        report = make_cookie_report(cookies=[
            make_cookie("_ga", ".google.com", category="analytics"),
        ])
        sub = _score_cookies(report)
        assert sub.score == 100 - 3

    def test_unknown_cookies_deduct_2_each(self):
        report = make_cookie_report(cookies=[
            make_cookie("__weird", ".x.com", category="unknown"),
            make_cookie("__weird2", ".x.com", category="unknown"),
        ])
        sub = _score_cookies(report)
        assert sub.score == 100 - 2 * 2

    def test_score_floored_at_zero(self):
        # 17 marketing cookies = -102 deduction
        cookies = [make_cookie(f"m{i}", ".x.com", category="marketing") for i in range(17)]
        report = make_cookie_report(cookies=cookies)
        sub = _score_cookies(report)
        assert sub.score == 0

    def test_weighted_contribution_equals_score_times_weight(self):
        report = make_cookie_report(cookies=[
            make_cookie("_ga", ".g.com", category="analytics"),
        ])
        sub = _score_cookies(report)
        assert abs(sub.weighted_contribution - sub.score * WEIGHTS["cookies"]) < 1e-9


# ---------------------------------------------------------------------------
# _score_tracking
# ---------------------------------------------------------------------------

class TestScoreTracking:
    def test_no_tracking_scores_100(self):
        sub = _score_tracking(make_cookie_report(), make_network())
        assert sub.score == 100

    def test_marketing_storage_deducts_8_each(self):
        report = make_cookie_report(storage=[
            make_storage("hjUser", category="marketing"),
        ])
        sub = _score_tracking(report, make_network())
        assert sub.score == 100 - 8

    def test_analytics_storage_deducts_4_each(self):
        report = make_cookie_report(storage=[
            make_storage("hjSession", category="analytics"),
        ])
        sub = _score_tracking(report, make_network())
        assert sub.score == 100 - 4

    def test_tracker_domain_deducts_5_each(self):
        net = make_network(data_flow=[
            make_flow("google-analytics.com", categories=["analytics"]),
            make_flow("facebook.com", categories=["marketing"]),
        ])
        sub = _score_tracking(make_cookie_report(), net)
        assert sub.score == 100 - 5 * 2

    def test_non_tracker_domain_not_counted(self):
        net = make_network(data_flow=[
            make_flow("cdn.example.com", categories=["cdn"]),
        ])
        sub = _score_tracking(make_cookie_report(), net)
        assert sub.score == 100

    def test_name_is_tracking(self):
        sub = _score_tracking(make_cookie_report(), make_network())
        assert sub.name == "tracking"


# ---------------------------------------------------------------------------
# _score_data_transfer
# ---------------------------------------------------------------------------

class TestScoreDataTransfer:
    def test_no_flows_scores_100(self):
        sub = _score_data_transfer(make_network())
        assert sub.score == 100

    def test_high_risk_deducts_12_each(self):
        net = make_network(data_flow=[
            make_flow("doubleclick.net", risk="high"),
        ])
        sub = _score_data_transfer(net)
        assert sub.score == 100 - 12

    def test_medium_risk_deducts_5_each(self):
        net = make_network(data_flow=[
            make_flow("cloudflare.com", risk="medium"),
        ])
        sub = _score_data_transfer(net)
        assert sub.score == 100 - 5

    def test_unknown_country_deducts_2_each(self):
        net = make_network(data_flow=[
            make_flow("someblob.net", country="Unknown"),
        ])
        sub = _score_data_transfer(net)
        assert sub.score == 100 - 2

    def test_eu_low_risk_no_deduction(self):
        net = make_network(data_flow=[
            make_flow("eu-cdn.example.de", country="EU", risk="low"),
        ])
        sub = _score_data_transfer(net)
        assert sub.score == 100


# ---------------------------------------------------------------------------
# _score_privacy
# ---------------------------------------------------------------------------

class TestScorePrivacy:
    def test_no_provider_gives_neutral_50(self):
        priv = make_privacy(error="no_provider_configured", provider="none",
                            compliance_score=0)
        sub = _score_privacy(priv)
        assert sub.score == 50

    def test_no_policy_text_gives_zero(self):
        priv = make_privacy(error="no_policy_text", compliance_score=0)
        sub = _score_privacy(priv)
        assert sub.score == 0

    def test_fatal_error_gives_zero(self):
        priv = make_privacy(error="JSONDecodeError: …", compliance_score=85)
        sub = _score_privacy(priv)
        assert sub.score == 0

    def test_partial_parse_dropped_uses_compliance_score(self):
        # The "dropped N malformed issues" path must NOT zero the score.
        priv = make_privacy(error="dropped 2 malformed issues", compliance_score=85)
        sub = _score_privacy(priv)
        assert sub.score == 85

    def test_clean_analysis_uses_compliance_score(self):
        priv = make_privacy(compliance_score=72)
        sub = _score_privacy(priv)
        assert sub.score == 72

    def test_score_clamped_to_100(self):
        priv = make_privacy(compliance_score=100)
        sub = _score_privacy(priv)
        assert sub.score == 100

    def test_name_is_privacy(self):
        sub = _score_privacy(make_privacy())
        assert sub.name == "privacy"


# ---------------------------------------------------------------------------
# _score_forms
# ---------------------------------------------------------------------------

class TestScoreForms:
    def test_no_pii_forms_scores_100(self):
        sub = _score_forms(make_form_report())
        assert sub.score == 100

    def test_pii_form_without_consent_deducts_12(self):
        report = make_form_report(pii_forms=1, with_consent=0, with_link=1)
        sub = _score_forms(report)
        assert sub.score == 100 - 12

    def test_pii_form_without_link_deducts_8(self):
        report = make_form_report(pii_forms=1, with_consent=1, with_link=0)
        sub = _score_forms(report)
        assert sub.score == 100 - 8

    def test_pii_form_with_both_no_deduction(self):
        report = make_form_report(pii_forms=1, with_consent=1, with_link=1)
        sub = _score_forms(report)
        assert sub.score == 100

    def test_name_is_forms(self):
        sub = _score_forms(make_form_report())
        assert sub.name == "forms"


# ---------------------------------------------------------------------------
# Hard caps — one test per named cap code
# ---------------------------------------------------------------------------

def _cap_codes(result) -> set[str]:
    return {c.code for c in result.applied_caps}


def _base_compute_risk(**kwargs):
    """compute_risk with maximally-clean defaults; override via kwargs."""
    defaults = dict(
        cookies=make_cookie_report(),
        network=make_network(),
        privacy=make_privacy(),
        forms=make_form_report(),
        channels=make_channels(),
        widgets=make_widgets(),
        has_policy=True,
        has_imprint=True,
        consent=None,
        security=None,
        libs=None,
    )
    defaults.update(kwargs)
    return compute_risk(**defaults)


class TestHardCaps:
    def test_us_analytics_no_consent(self):
        net = make_network(data_flow=[
            make_flow("google-analytics.com", country="USA", categories=["analytics"]),
        ])
        result = _base_compute_risk(network=net)
        assert "us_analytics_no_consent" in _cap_codes(result)
        assert result.score <= 50

    def test_us_marketing_no_consent(self):
        net = make_network(data_flow=[
            make_flow("facebook.com", country="USA", categories=["marketing"]),
        ])
        result = _base_compute_risk(network=net)
        assert "us_marketing_no_consent" in _cap_codes(result)
        assert result.score <= 40

    def test_us_caps_absent_when_cmp_present(self):
        # A CMP cookie (vendor="onetrust") suppresses US caps.
        cookies = make_cookie_report(cookies=[
            make_cookie("OptanonConsent", ".onetrust.com",
                        category="necessary", vendor="onetrust", reason="consent management"),
        ])
        net = make_network(data_flow=[
            make_flow("google-analytics.com", country="USA", categories=["analytics"]),
        ])
        result = _base_compute_risk(cookies=cookies, network=net)
        assert "us_analytics_no_consent" not in _cap_codes(result)

    def test_tdddg_non_essential_without_consent(self):
        net = make_network(data_flow=[
            make_flow("matomo-cloud.example.com", country="EU", categories=["analytics"]),
        ])
        result = _base_compute_risk(network=net)
        assert "tdddg_non_essential_without_consent" in _cap_codes(result)
        assert result.score <= 50

    def test_tdddg_third_party_without_consent_light(self):
        net = make_network(data_flow=[
            make_flow("cdn.jsdelivr.net", country="EU", categories=["cdn"]),
        ])
        result = _base_compute_risk(network=net)
        assert "tdddg_third_party_without_consent" in _cap_codes(result)
        assert result.score <= 70

    def test_no_privacy_policy_cap(self):
        result = _base_compute_risk(has_policy=False)
        assert "no_privacy_policy" in _cap_codes(result)
        assert result.score <= 30

    def test_no_imprint_cap(self):
        result = _base_compute_risk(has_imprint=False)
        assert "no_imprint" in _cap_codes(result)
        assert result.score <= 50

    def test_google_fonts_external_cap(self):
        # Phase 10: detector populates network.google_fonts; scoring
        # reads the structured field rather than re-walking requests.
        from app.modules.google_fonts_detector import detect_google_fonts
        net = make_network(requests=[
            make_request("https://fonts.googleapis.com/css?family=Roboto"),
        ])
        net.google_fonts = detect_google_fonts(net)
        result = _base_compute_risk(network=net)
        assert "google_fonts_external" in _cap_codes(result)
        # Phase 10 tightened from 65 → 55, aligned with policy_missing_user_rights.
        assert result.score <= 55

    def test_google_fonts_gstatic_triggers_same_cap(self):
        from app.modules.google_fonts_detector import detect_google_fonts
        net = make_network(requests=[
            make_request("https://fonts.gstatic.com/s/roboto/v30/file.woff2"),
        ])
        net.google_fonts = detect_google_fonts(net)
        result = _base_compute_risk(network=net)
        assert "google_fonts_external" in _cap_codes(result)

    def test_no_email_authentication_cap(self):
        dns = DnsSecurityInfo(
            domain="example.com",
            spf_present=False,
            dmarc_present=False,
            dmarc_policy="missing",
            dnssec_enabled=False,
            caa_present=False,
        )
        sec = SecurityAudit(
            final_url="https://example.com/",
            headers=[],
            dns=dns,
        )
        result = _base_compute_risk(security=sec)
        assert "no_email_authentication" in _cap_codes(result)
        assert result.score <= 75

    def test_known_vulnerable_library_cap_high(self):
        lib = VulnerableLibrary(
            library="jquery", detected_version="1.11.0",
            url="https://example.com/jquery.min.js",
            severity="high", cves=["CVE-2015-9251"],
        )
        libs = VulnerableLibrariesReport(
            libraries=[lib], summary={"high": 1, "medium": 0, "low": 0},
        )
        result = _base_compute_risk(libs=libs)
        assert "known_vulnerable_library" in _cap_codes(result)
        assert result.score <= 55

    def test_outdated_vulnerable_library_cap_medium(self):
        lib = VulnerableLibrary(
            library="lodash", detected_version="4.17.4",
            url="https://example.com/lodash.js",
            severity="medium", cves=["CVE-2021-23337"],
        )
        libs = VulnerableLibrariesReport(
            libraries=[lib], summary={"high": 0, "medium": 1, "low": 0},
        )
        result = _base_compute_risk(libs=libs)
        assert "outdated_vulnerable_library" in _cap_codes(result)
        assert result.score <= 75

    def test_embed_or_chat_without_consent_tracking_video(self):
        widget = make_widget(kind="youtube", category="video", privacy_enhanced=False)
        result = _base_compute_risk(widgets=make_widgets([widget]))
        assert "embed_or_chat_without_consent" in _cap_codes(result)
        assert result.score <= 55

    def test_map_embed_without_consent(self):
        widget = make_widget(kind="google_maps", category="map",
                             src="https://maps.google.com/embed", privacy_enhanced=False)
        result = _base_compute_risk(widgets=make_widgets([widget]))
        assert "map_embed_without_consent" in _cap_codes(result)
        assert result.score <= 70

    def test_privacy_enhanced_video_does_not_cap(self):
        widget = make_widget(kind="youtube_nocookie", category="video",
                             privacy_enhanced=True,
                             src="https://www.youtube-nocookie.com/embed/abc")
        result = _base_compute_risk(widgets=make_widgets([widget]))
        assert "embed_or_chat_without_consent" not in _cap_codes(result)

    def test_consent_dark_pattern_high_cap(self):
        finding = DarkPatternFinding(
            code="no_direct_reject",
            severity="high",
            description="No first-level reject button",
        )
        ux = ConsentUxAudit(
            banner_detected=True, accept_found=True, reject_found=False,
            findings=[finding],
        )
        consent = ConsentSimulation(
            enabled=True, accept_clicked=True, note="clicked", ux_audit=ux,
        )
        result = _base_compute_risk(consent=consent)
        assert "consent_dark_pattern_high" in _cap_codes(result)
        assert result.score <= 45

    def test_cert_expired_cap(self):
        tls = TlsInfo(https_enforced=True, cert_expires_days=-5)
        sec = SecurityAudit(final_url="https://example.com/", headers=[], tls=tls)
        result = _base_compute_risk(security=sec)
        assert "cert_expired" in _cap_codes(result)
        assert result.score <= 20

    def test_no_https_enforcement_cap(self):
        tls = TlsInfo(https_enforced=False)
        sec = SecurityAudit(final_url="http://example.com/", headers=[], tls=tls)
        result = _base_compute_risk(security=sec)
        assert "no_https_enforcement" in _cap_codes(result)
        assert result.score <= 35

    def test_lowest_cap_wins_when_multiple_apply(self):
        # no_privacy_policy (30) + no_imprint (50) → final must be ≤ 30
        result = _base_compute_risk(has_policy=False, has_imprint=False)
        codes = _cap_codes(result)
        assert "no_privacy_policy" in codes
        assert "no_imprint" in codes
        assert result.score <= 30


# ---------------------------------------------------------------------------
# Cap → sub-score routing (HardCap.affected_subscores + _CAP_AFFECTS map)
# ---------------------------------------------------------------------------
#
# The dashboard reads HardCap.affected_subscores to render per-sub-score
# cap badges. The mapping lives in scoring._CAP_AFFECTS as a single
# source of truth (Convention #1). The tests below pin that mapping at
# three levels: shape (only valid sub-score names), specific entries
# (regression guard for individual cap → sub-score links), and coverage
# (every cap code that _compute_caps can emit must have an entry, so a
# new cap added without a mapping entry breaks CI rather than silently
# rendering without a badge).

_VALID_SUBSCORE_NAMES = {"cookies", "tracking", "data_transfer", "privacy", "forms"}


class TestCapAffectsMapping:
    def test_central_mapping_uses_only_valid_subscore_names(self):
        from app.modules.scoring import _CAP_AFFECTS
        for code, subs in _CAP_AFFECTS.items():
            for sub in subs:
                assert sub in _VALID_SUBSCORE_NAMES, (
                    f"Cap {code!r} maps to unknown sub-score {sub!r}; "
                    f"allowed: {_VALID_SUBSCORE_NAMES}"
                )

    def test_security_caps_are_cross_cutting_empty_affects(self):
        # Security caps (HTTPS / mixed-content / cert / DMARC / vuln-libs)
        # have no sub-score representation, so their affected_subscores
        # MUST be empty. The HardCapsList card still surfaces them; only
        # the per-sub-score badges skip them.
        from app.modules.scoring import _CAP_AFFECTS
        for code in (
            "no_https_enforcement", "mixed_content",
            "cert_expired", "cert_expiring_soon",
            "no_email_authentication",
            "known_vulnerable_library", "outdated_vulnerable_library",
        ):
            assert _CAP_AFFECTS[code] == (), (
                f"Security cap {code!r} should be cross-cutting "
                f"(empty affected_subscores), got {_CAP_AFFECTS[code]}"
            )

    def test_google_fonts_external_affects_data_transfer_and_cookies(self):
        # Pin the multi-affected example from the brief.
        from app.modules.scoring import _CAP_AFFECTS
        assert set(_CAP_AFFECTS["google_fonts_external"]) == {"data_transfer", "cookies"}

    def test_pre_checked_consent_box_affects_forms_and_cookies(self):
        from app.modules.scoring import _CAP_AFFECTS
        assert set(_CAP_AFFECTS["pre_checked_consent_box"]) == {"forms", "cookies"}

    def test_no_legal_basis_stated_affects_privacy_only(self):
        from app.modules.scoring import _CAP_AFFECTS
        assert _CAP_AFFECTS["no_legal_basis_stated"] == ("privacy",)

    def test_emitted_caps_carry_affected_subscores_field(self):
        # End-to-end: trigger a real cap, assert the field arrives
        # populated on the HardCap instance (i.e. the post-hoc
        # enrichment loop actually ran, not just the mapping is defined).
        net = make_network(data_flow=[
            make_flow("google-analytics.com", country="USA", categories=["analytics"]),
        ])
        result = _base_compute_risk(network=net)
        cap = next(c for c in result.applied_caps if c.code == "us_analytics_no_consent")
        assert set(cap.affected_subscores) == {"tracking", "data_transfer"}

    def test_every_emitted_cap_code_has_mapping_entry(self):
        # Coverage check: trigger as many caps as we can in one
        # kitchen-sink scenario, then assert each emitted cap.code has
        # a known _CAP_AFFECTS entry. A new cap added in scoring.py
        # without a mapping entry breaks here. This is the load-bearing
        # test for "do not silently drop the per-sub-score badge".
        from app.modules.scoring import _CAP_AFFECTS

        # Build a scenario that fires lots of caps at once:
        #   - US analytics + marketing tracker (us_*_no_consent)
        #   - EU CDN tracker hit (tdddg_third_party_*)
        #   - missing privacy policy + missing imprint
        #   - Google Fonts request
        #   - tracking-variant YouTube widget
        #   - WhatsApp contact channel without policy disclosure
        #   - pre-checked consent form
        from app.models import (
            ConsentSimulation, ConsentUxAudit, DarkPatternFinding,
        )
        from .conftest import make_channel, make_widget

        net = make_network(
            requests=[
                make_request("https://fonts.googleapis.com/css?family=Roboto"),
            ],
            data_flow=[
                make_flow("google-analytics.com", country="USA", categories=["analytics"]),
                make_flow("facebook.com", country="USA", categories=["marketing"]),
                make_flow("cdn.jsdelivr.net", country="EU", categories=["cdn"]),
            ],
        )
        # Re-run the GoogleFonts detector on the network so the cap
        # actually fires (Phase-10 contract: scoring reads
        # network.google_fonts.detected, not the requests list).
        from app.modules.google_fonts_detector import detect_google_fonts
        net.google_fonts = detect_google_fonts(net)

        widgets = make_widgets([
            make_widget(kind="youtube", category="video", privacy_enhanced=False),
        ])
        channels = make_channels([
            make_channel(kind="whatsapp", country="USA", vendor="Meta"),
        ])
        # Coverage object whose third_country_transfers_disclosed=False
        # → fires policy_silent_on_third_country_transfer +
        # contact_channel_transfer_not_disclosed.
        privacy = make_privacy(
            coverage=_full_coverage(third_country=False, legal_basis=False),
        )
        # Pre-checked consent form → pre_checked_consent_box.
        forms = make_form_report(
            forms=[],
            pii_forms=1, with_consent=1,
        )
        forms.summary["forms_with_pre_checked_consent"] = 1

        # Consent dark pattern → consent_dark_pattern_high.
        consent = ConsentSimulation(
            enabled=True, accept_clicked=True,
            cmp_detected=None, note="t",
            ux_audit=ConsentUxAudit(
                banner_detected=True, accept_found=True, reject_found=False,
                findings=[DarkPatternFinding(
                    code="no_direct_reject", severity="high", description="t",
                )],
            ),
        )

        result = _base_compute_risk(
            network=net, widgets=widgets, channels=channels,
            privacy=privacy, forms=forms, consent=consent,
            has_policy=False, has_imprint=False,
        )
        emitted = {c.code for c in result.applied_caps}
        # Sanity: scenario triggered enough caps to make the coverage
        # check meaningful (not just one or two).
        assert len(emitted) >= 6, (
            f"kitchen-sink scenario fired only {len(emitted)} cap(s); "
            f"check the scenario builders haven't drifted: {emitted}"
        )
        missing = emitted - set(_CAP_AFFECTS.keys())
        assert not missing, (
            f"Cap code(s) {missing} emitted by _compute_caps but missing "
            f"from scoring._CAP_AFFECTS — add an entry there (or "
            f"explicitly map to () for cross-cutting/security caps)."
        )


def _full_coverage(*, third_country: bool = True, legal_basis: bool = True):
    """Local copy of the conftest helper to keep the new test class
    self-contained — same shape, different defaults at call time."""
    from app.models import PolicyTopicCoverage
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


# ---------------------------------------------------------------------------
# compute_risk integration
# ---------------------------------------------------------------------------

class TestComputeRisk:
    def test_clean_site_no_caps_high_score(self):
        result = _base_compute_risk()
        assert result.applied_caps == []
        # With neutral privacy score (80) and no deductions, weighted ≈ 80 × 0.25
        # + 100 * 0.75 → well above 60.
        assert result.score >= 60

    def test_weighted_score_before_caps_computed(self):
        result = _base_compute_risk()
        # Confirm weighted_score reflects the raw weighted average.
        expected = round(sum(s.weighted_contribution for s in result.sub_scores))
        assert result.weighted_score == expected

    def test_cap_lowers_final_below_weighted(self):
        result = _base_compute_risk(has_policy=False)
        assert result.score <= 30
        # The weighted_score stays at whatever arithmetic gave us — caps only touch final.
        assert result.weighted_score >= result.score

    def test_rating_is_critical_below_40(self):
        # Expired cert (cap 20) → score ≤ 20 → critical
        tls = TlsInfo(https_enforced=True, cert_expires_days=-1)
        sec = SecurityAudit(final_url="https://example.com/", headers=[], tls=tls)
        result = _base_compute_risk(security=sec)
        assert result.rating == "critical"

    def test_rating_is_low_for_clean_site(self):
        result = _base_compute_risk(privacy=make_privacy(compliance_score=100))
        assert result.rating in ("low", "medium")

    def test_recommendations_nonempty_when_policy_missing(self):
        result = _base_compute_risk(has_policy=False)
        assert len(result.recommendations) > 0
        titles = [r.title for r in result.recommendations]
        assert any("privacy policy" in t.lower() or "datenschutz" in t.lower() for t in titles)

    def test_recommendations_empty_or_low_priority_for_clean_site(self):
        result = _base_compute_risk(privacy=make_privacy(compliance_score=100))
        # A truly clean site may still get low-priority recommendations but
        # should have no HIGH items.
        high_recs = [r for r in result.recommendations if r.priority == "high"]
        assert high_recs == []

    def test_german_recommendations_when_lang_de(self):
        result = compute_risk(
            cookies=make_cookie_report(),
            network=make_network(),
            privacy=make_privacy(),
            forms=make_form_report(),
            channels=make_channels(),
            widgets=make_widgets(),
            has_policy=False,
            has_imprint=False,
            lang="de",
        )
        titles = " ".join(r.title for r in result.recommendations)
        assert "Datenschutzerklärung" in titles or "Impressum" in titles

    def test_five_sub_scores_present(self):
        result = _base_compute_risk()
        names = {s.name for s in result.sub_scores}
        assert names == {"cookies", "tracking", "data_transfer", "privacy", "forms"}

    def test_cookie_retention_recommendation_for_long_lived_marketing_cookie(self):
        far_future = time.time() + 60 * 60 * 24 * 500  # 500 days
        cookies = make_cookie_report(cookies=[
            make_cookie("_fbp", ".fb.com", category="marketing",
                        is_session=False, expires=far_future),
        ])
        result = _base_compute_risk(cookies=cookies)
        rec_titles = " ".join(r.title for r in result.recommendations).lower()
        assert "13 month" in rec_titles or "13 monate" in rec_titles or "retention" in rec_titles
