"""Tests for the Phase 9e cookie-wall / "Pay or Okay" detector.

Two halves:
  - The pure ``detect_cookie_wall`` predicate against realistic banner
    text, English + German, plus the obvious false-positive shapes.
  - Scoring integration: when the upstream UX audit appends a
    ``cookie_wall_pay_or_okay`` HIGH finding, the existing
    ``consent_dark_pattern_high`` cap (45) trips AND the EDPB-Opinion-
    8/2024 recommendation surfaces.
"""

from __future__ import annotations

from app.models import (
    ConsentSimulation,
    ConsentUxAudit,
    DarkPatternFinding,
)
from app.modules.cookie_wall_detector import detect_cookie_wall
from app.modules.scoring import compute_risk

from .conftest import (
    make_channels,
    make_cookie_report,
    make_form_report,
    make_network,
    make_privacy,
    make_widgets,
)


# ---------------------------------------------------------------------------
# Pure detector
# ---------------------------------------------------------------------------

class TestEmptyOrNeutralInput:
    def test_empty_string_returns_none(self):
        assert detect_cookie_wall("") is None

    def test_whitespace_only_returns_none(self):
        assert detect_cookie_wall("   \n\n  ") is None

    def test_neutral_consent_banner_does_not_fire(self):
        # Standard consent banner — accept + reject + settings, no pay
        # path. The detector must NOT flag this.
        text = (
            "We use cookies and similar technologies to provide a "
            "better experience. You can accept all cookies, reject "
            "non-essential, or open Settings to choose. Read our "
            "privacy policy for details."
        )
        assert detect_cookie_wall(text) is None

    def test_german_neutral_consent_banner_does_not_fire(self):
        text = (
            "Wir verwenden Cookies. Sie können alle akzeptieren, "
            "ablehnen oder über Einstellungen einzelne Kategorien "
            "auswählen. Mehr in unserer Datenschutzerklärung."
        )
        assert detect_cookie_wall(text) is None


class TestEnglishPositive:
    def test_pay_to_reject(self):
        text = (
            "Accept all cookies to continue using our site for free, "
            "or pay to reject tracking via our ad-free subscription."
        )
        finding = detect_cookie_wall(text)
        assert finding is not None
        assert finding.code == "cookie_wall_pay_or_okay"
        assert finding.severity == "high"

    def test_pay_or_okay(self):
        text = "Pay or okay: Accept all cookies, or pay €5/month."
        finding = detect_cookie_wall(text)
        assert finding is not None
        assert "pay or okay" in str(finding.evidence.get("paywall_token_matched", "")).lower()

    def test_subscribe_to_remove_ads(self):
        text = (
            "Click 'I agree' to consent to ads. Or subscribe to remove "
            "ads for €4.99/month."
        )
        finding = detect_cookie_wall(text)
        assert finding is not None

    def test_consent_or_pay(self):
        text = "Consent or pay. Accept all cookies, or buy a premium subscription."
        finding = detect_cookie_wall(text)
        assert finding is not None


class TestGermanPositive:
    def test_pur_abo_pattern(self):
        # Classic SPIEGEL / Bild-style "PUR Abo" — the pattern that
        # triggered the German DPAs' "consent or pay" findings.
        text = (
            "Mit Klick auf 'Alle akzeptieren' willigen Sie in das "
            "Tracking ein. Alternativ können Sie unser PUR Abo für "
            "4,99 €/Monat abschließen — werbefrei und ohne Tracking."
        )
        finding = detect_cookie_wall(text)
        assert finding is not None
        assert finding.code == "cookie_wall_pay_or_okay"

    def test_werbefrei_abonnieren(self):
        text = (
            "Wählen Sie: Alle Cookies akzeptieren oder werbefrei "
            "abonnieren. Sie können sich jetzt entscheiden."
        )
        finding = detect_cookie_wall(text)
        assert finding is not None

    def test_ohne_werbung_abo(self):
        text = (
            "Akzeptieren Sie unsere Werbe-Cookies oder schließen Sie "
            "ein kostenpflichtiges Abo ohne Werbung ab."
        )
        finding = detect_cookie_wall(text)
        assert finding is not None


class TestNegativePaths:
    def test_paywall_only_without_accept_does_not_fire(self):
        # A pure subscription page that doesn't have a tracking-
        # consent prompt isn't a cookie wall — it's just a paywall.
        text = (
            "Subscribe to our ad-free premium tier for €9.99/month "
            "and get unlimited access."
        )
        assert detect_cookie_wall(text) is None

    def test_accept_only_without_paywall_does_not_fire(self):
        # Already covered by the neutral-banner test, but pin it: an
        # "accept all cookies" banner that mentions nothing about
        # paying is just consent UI.
        text = "Accept all cookies to continue. Privacy policy."
        assert detect_cookie_wall(text) is None

    def test_unrelated_pay_attention_phrase_does_not_match(self):
        # "Pay attention" is a common false-positive risk for a naive
        # `"pay" in text` check. Our detector requires multi-word
        # phrases, so this cleanly negatives.
        text = (
            "Please pay attention to our cookie policy. Accept all "
            "cookies to continue."
        )
        assert detect_cookie_wall(text) is None

    def test_multiline_text_normalises_whitespace(self):
        # The detector lower-cases + collapses \s+ → " " so cross-line
        # phrases still match. "subscribe instead" wraps over a newline.
        text = (
            "Accept all\ntracking, or\n"
            "subscribe instead\n"
            "for €5/month."
        )
        finding = detect_cookie_wall(text)
        assert finding is not None


# ---------------------------------------------------------------------------
# Scoring integration
# ---------------------------------------------------------------------------

def _has_cap(result, code: str) -> bool:
    return any(c.code == code for c in result.applied_caps)


def _consent_with_finding() -> ConsentSimulation:
    """Build a ConsentSimulation that reports a cookie-wall finding,
    matching the shape consent_ux_audit.py would produce on a real scan."""
    finding = DarkPatternFinding(
        code="cookie_wall_pay_or_okay",
        severity="high",
        description="Banner offers consent-or-pay …",
        evidence={"accept_token_matched": "accept all", "paywall_token_matched": "pur abo"},
    )
    audit = ConsentUxAudit(
        banner_detected=True,
        cmp="onetrust",
        accept_found=True,
        reject_found=False,
        findings=[finding],
        banner_text="Alle akzeptieren oder PUR Abo …",
    )
    return ConsentSimulation(
        enabled=True,
        accept_clicked=False,
        cmp_detected="onetrust",
        note="cookie wall detected",
        ux_audit=audit,
    )


class TestScoringWiring:
    def test_consent_dark_pattern_high_cap_fires(self):
        # The cookie-wall finding is severity="high", so the existing
        # consent_dark_pattern_high cap (45) must auto-apply without
        # any cookie-wall-specific scoring code.
        result = compute_risk(
            cookies=make_cookie_report(),
            network=make_network(),
            privacy=make_privacy(),
            forms=make_form_report(),
            channels=make_channels(),
            widgets=make_widgets(),
            has_policy=True,
            has_imprint=True,
            consent=_consent_with_finding(),
        )
        assert _has_cap(result, "consent_dark_pattern_high")
        assert result.score <= 45

    def test_specific_recommendation_emitted_in_english(self):
        result = compute_risk(
            cookies=make_cookie_report(),
            network=make_network(),
            privacy=make_privacy(),
            forms=make_form_report(),
            channels=make_channels(),
            widgets=make_widgets(),
            has_policy=True,
            has_imprint=True,
            consent=_consent_with_finding(),
            lang="en",
        )
        details = " ".join(r.detail for r in result.recommendations)
        # The EDPB opinion is the primary anchor for this finding.
        assert "EDPB Opinion 8/2024" in details
        # The fix path is the headline value of the recommendation.
        assert "behavioural advertising" in details

    def test_specific_recommendation_emitted_in_german(self):
        result = compute_risk(
            cookies=make_cookie_report(),
            network=make_network(),
            privacy=make_privacy(),
            forms=make_form_report(),
            channels=make_channels(),
            widgets=make_widgets(),
            has_policy=True,
            has_imprint=True,
            consent=_consent_with_finding(),
            lang="de",
        )
        titles = " ".join(r.title for r in result.recommendations)
        assert "EDPB Opinion 8/2024" in titles
        details = " ".join(r.detail for r in result.recommendations)
        assert "verhaltensbasierte" in details

    def test_no_finding_no_recommendation(self):
        # ConsentSimulation present but findings list empty — neither
        # cap nor recommendation should fire.
        clean = ConsentSimulation(
            enabled=True, accept_clicked=False,
            cmp_detected="onetrust",
            note="clean banner",
            ux_audit=ConsentUxAudit(
                banner_detected=True, cmp="onetrust",
                accept_found=True, reject_found=True,
                findings=[],
            ),
        )
        result = compute_risk(
            cookies=make_cookie_report(),
            network=make_network(),
            privacy=make_privacy(),
            forms=make_form_report(),
            channels=make_channels(),
            widgets=make_widgets(),
            has_policy=True,
            has_imprint=True,
            consent=clean,
        )
        titles = " ".join(r.title for r in result.recommendations).lower()
        assert "edpb opinion 8/2024" not in titles
