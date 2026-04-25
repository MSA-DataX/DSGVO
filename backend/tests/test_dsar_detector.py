"""Tests for the deterministic DSAR detector (Phase 9d).

Two halves:
  - The pure detector matches German + English vocabulary against
    realistic policy snippets. Empty / low-signal inputs produce a
    zero-score result rather than a false positive.
  - The scoring layer fires `policy_missing_user_rights` when a
    policy was found but the deterministic check named zero rights.
"""

from __future__ import annotations

from app.models import DsarCheck, PrivacyAnalysis
from app.modules.dsar_detector import detect_dsar
from app.modules.scoring import compute_risk

from .conftest import (
    make_channels,
    make_cookie_report,
    make_form_report,
    make_network,
    make_privacy,
    make_widgets,
    _full_coverage,
)


# ---------------------------------------------------------------------------
# Pure detector
# ---------------------------------------------------------------------------

class TestDetectorEmptyInput:
    def test_empty_string_returns_zero_score(self):
        result = detect_dsar("")
        assert result.named_rights == []
        assert result.has_rights_contact is False
        assert result.score == 0

    def test_whitespace_only_returns_zero_score(self):
        result = detect_dsar("   \n\t  ")
        assert result.score == 0

    def test_non_policy_text_finds_nothing(self):
        # Hardware specs page — no policy vocabulary anywhere.
        result = detect_dsar("This product features 16 GB RAM and a 512 GB SSD.")
        assert result.named_rights == []
        assert result.has_rights_contact is False


class TestGermanRightsVocab:
    def test_full_german_policy_finds_seven_rights(self):
        # A realistic boilerplate snippet with most of the canonical
        # German rights phrasings present.
        text = """
        Ihre Rechte: Sie haben jederzeit das Recht auf Auskunft über
        die zu Ihrer Person gespeicherten Daten. Daneben besteht ein
        Recht auf Berichtigung, Recht auf Löschung sowie ein Recht
        auf Einschränkung der Verarbeitung. Soweit Sie eine
        Einwilligung erteilt haben, können Sie diese Einwilligung
        jederzeit widerrufen (Widerruf der Einwilligung). Es besteht
        zudem ein Recht auf Datenübertragbarkeit und ein Recht auf
        Widerspruch gegen die Verarbeitung. Schließlich haben Sie das
        Recht, sich bei einer Aufsichtsbehörde zu beschweren.
        Kontakt: datenschutz@example.de
        """
        result = detect_dsar(text)
        # All eight canonical rights present + a contact email.
        assert set(result.named_rights) == {
            "access", "rectification", "erasure", "restriction",
            "portability", "objection", "complaint", "withdraw_consent",
        }
        assert result.has_rights_contact is True
        assert "@example.de" in (result.contact_excerpt or "")
        assert result.score == 100

    def test_partial_german_policy(self):
        text = (
            "Sie haben das Recht auf Auskunft. "
            "Wenden Sie sich an datenschutz@example.de."
        )
        result = detect_dsar(text)
        assert result.named_rights == ["access"]
        assert result.has_rights_contact is True
        # 1 right × 10 + 20 contact = 30.
        assert result.score == 30


class TestEnglishRightsVocab:
    def test_full_english_policy_finds_eight_rights(self):
        text = """
        Your rights under the GDPR include: the right of access to
        your personal data; the right to rectification; the right to
        erasure (also known as the right to be forgotten); the right
        to restriction of processing; the right to data portability;
        the right to object to processing; the right to withdraw
        consent at any time; and the right to lodge a complaint with
        a supervisory authority.

        Contact our Data Protection Officer at dpo@example.com.
        """
        result = detect_dsar(text)
        assert set(result.named_rights) == {
            "access", "rectification", "erasure", "restriction",
            "portability", "objection", "complaint", "withdraw_consent",
        }
        assert result.has_rights_contact is True
        assert result.score == 100

    def test_some_only(self):
        text = (
            "You have the right to data portability and the right to "
            "object. Contact: privacy@example.com."
        )
        result = detect_dsar(text)
        assert set(result.named_rights) == {"portability", "objection"}
        assert result.has_rights_contact is True


class TestContactDetection:
    def test_mailto_link_is_contact(self):
        text = (
            "You have the right of access. "
            "Email <a href=\"mailto:dsar@example.com\">us</a>."
        )
        result = detect_dsar(text)
        assert result.has_rights_contact is True

    def test_dpo_keyword_is_contact(self):
        # No email visible, but DPO mention still counts as a contact.
        text = "We have appointed a Data Protection Officer. You have the right of access."
        result = detect_dsar(text)
        assert result.has_rights_contact is True

    def test_german_dpo_keyword_is_contact(self):
        text = (
            "Sie haben das Recht auf Auskunft. Unsere "
            "Datenschutzbeauftragte ist erreichbar."
        )
        result = detect_dsar(text)
        assert result.has_rights_contact is True

    def test_no_contact_at_all_returns_false(self):
        text = "We process data. Recht auf Auskunft besteht."
        result = detect_dsar(text)
        assert result.has_rights_contact is False
        assert result.contact_excerpt is None


class TestComplaintRequiresAuthority:
    def test_lone_complaint_word_does_not_match(self):
        # Complaint by itself is too generic ("we'll handle complaints
        # to customer service"). Match requires a supervisory-authority
        # token nearby.
        text = "We try to resolve every complaint within 24 hours."
        result = detect_dsar(text)
        assert "complaint" not in result.named_rights

    def test_complaint_with_supervisory_authority_matches(self):
        text = "You may lodge a complaint with the supervisory authority."
        result = detect_dsar(text)
        assert "complaint" in result.named_rights


# ---------------------------------------------------------------------------
# Scoring integration
# ---------------------------------------------------------------------------

def _has_cap(result, code: str) -> bool:
    return any(c.code == code for c in result.applied_caps)


def _privacy_with_dsar(*, named: list[str]) -> PrivacyAnalysis:
    """Privacy analysis fixture pre-populated with a DsarCheck so we can
    pin the cap behaviour without re-running detect_dsar."""
    p = make_privacy()
    p.dsar = DsarCheck(
        named_rights=named,
        has_rights_contact=False,
        contact_excerpt=None,
        score=len(named) * 10,
    )
    # The AI's coverage object also exists in our default fixture; the
    # cap logic should NOT depend on it for this case.
    p.coverage = _full_coverage()
    return p


class TestPolicyMissingUserRightsCap:
    def test_cap_fires_when_zero_rights_found(self):
        result = compute_risk(
            cookies=make_cookie_report(),
            network=make_network(),
            privacy=_privacy_with_dsar(named=[]),
            forms=make_form_report(),
            channels=make_channels(),
            widgets=make_widgets(),
            has_policy=True,
            has_imprint=True,
        )
        assert _has_cap(result, "policy_missing_user_rights")
        assert result.score <= 55

    def test_cap_does_not_fire_when_at_least_one_right_found(self):
        result = compute_risk(
            cookies=make_cookie_report(),
            network=make_network(),
            privacy=_privacy_with_dsar(named=["access"]),
            forms=make_form_report(),
            channels=make_channels(),
            widgets=make_widgets(),
            has_policy=True,
            has_imprint=True,
        )
        assert not _has_cap(result, "policy_missing_user_rights")

    def test_cap_does_not_fire_without_policy(self):
        # has_policy=False is already covered by no_privacy_policy
        # (cap 30) — we don't double-fire policy_missing_user_rights
        # on top of it.
        priv = _privacy_with_dsar(named=[])
        result = compute_risk(
            cookies=make_cookie_report(),
            network=make_network(),
            privacy=priv,
            forms=make_form_report(),
            channels=make_channels(),
            widgets=make_widgets(),
            has_policy=False,
            has_imprint=True,
        )
        assert _has_cap(result, "no_privacy_policy")
        assert not _has_cap(result, "policy_missing_user_rights")

    def test_cap_does_not_fire_when_dsar_absent(self):
        # No policy_text fetched → privacy.dsar is None → no signal,
        # don't inadvertently fire just because the analysis has no
        # DSAR field populated.
        priv = make_privacy()  # dsar defaults to None
        priv.coverage = _full_coverage()
        result = compute_risk(
            cookies=make_cookie_report(),
            network=make_network(),
            privacy=priv,
            forms=make_form_report(),
            channels=make_channels(),
            widgets=make_widgets(),
            has_policy=True,
            has_imprint=True,
        )
        assert not _has_cap(result, "policy_missing_user_rights")


class TestRecommendation:
    def test_recommendation_emitted_in_german(self):
        result = compute_risk(
            cookies=make_cookie_report(),
            network=make_network(),
            privacy=_privacy_with_dsar(named=[]),
            forms=make_form_report(),
            channels=make_channels(),
            widgets=make_widgets(),
            has_policy=True,
            has_imprint=True,
            lang="de",
        )
        titles = " ".join(r.title for r in result.recommendations)
        assert "Betroffenenrechte" in titles
        details = " ".join(r.detail for r in result.recommendations)
        # The German output cites the article in DSGVO format AND
        # points to the DSK template — both auditor-friendly anchors.
        assert "Art. 13" in details
        assert "DSK" in details

    def test_recommendation_emitted_in_english(self):
        result = compute_risk(
            cookies=make_cookie_report(),
            network=make_network(),
            privacy=_privacy_with_dsar(named=[]),
            forms=make_form_report(),
            channels=make_channels(),
            widgets=make_widgets(),
            has_policy=True,
            has_imprint=True,
            lang="en",
        )
        details = " ".join(r.detail for r in result.recommendations)
        assert "Art. 13(2)(b)" in details
        # All eight canonical rights named in the recommendation body.
        for token in (
            "access", "rectification", "erasure", "restriction",
            "portability", "objection", "complaint", "withdraw consent",
        ):
            assert token in details.lower()
