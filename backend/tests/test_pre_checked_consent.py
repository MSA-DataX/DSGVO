"""Tests for the EuGH Planet49 / Art. 7(2) DSGVO check (Phase 9).

Pre-ticked consent boxes are settled CJEU case law since C-673/17.
The detection has two halves:

  - **Crawler** (HTML → FormField.is_pre_checked + FormInfo.has_pre_checked_box)
    must read the `checked` attribute correctly across the syntactic
    forms browsers accept.
  - **form_analyzer** must combine "any pre-ticked checkbox" with
    "consent vocabulary nearby" to decide whether to fire — neutral
    pre-ticks ("remember me") shouldn't.

Plus the scoring layer: a hit drives a hard cap and a recommendation
that cites the case.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.modules.crawler import Crawler
from app.modules.form_analyzer import _has_pre_checked_consent, analyze_forms
from app.modules.scoring import compute_risk

from .conftest import (
    make_channels,
    make_cookie_report,
    make_field,
    make_form,
    make_form_report,
    make_network,
    make_privacy,
    make_widgets,
)


# ---------------------------------------------------------------------------
# Crawler — HTML extraction
# ---------------------------------------------------------------------------

class TestCrawlerExtraction:
    def test_checked_boolean_attribute(self):
        # `<input type="checkbox" checked>` — bare HTML5 boolean form.
        soup = BeautifulSoup(
            '<form><input type="checkbox" name="agree" checked></form>',
            "html.parser",
        )
        forms = Crawler._extract_forms(soup, "https://example.com/")
        assert len(forms) == 1
        assert forms[0].has_pre_checked_box is True
        assert forms[0].fields[0].is_pre_checked is True

    def test_checked_with_value(self):
        # `<input type="checkbox" checked="checked">` — XHTML form,
        # still common in legacy German B2B HTML.
        soup = BeautifulSoup(
            '<form><input type="checkbox" name="agree" checked="checked"></form>',
            "html.parser",
        )
        forms = Crawler._extract_forms(soup, "https://example.com/")
        assert forms[0].has_pre_checked_box is True
        assert forms[0].fields[0].is_pre_checked is True

    def test_unchecked_box_is_false(self):
        soup = BeautifulSoup(
            '<form><input type="checkbox" name="agree"></form>',
            "html.parser",
        )
        forms = Crawler._extract_forms(soup, "https://example.com/")
        assert forms[0].has_pre_checked_box is False
        assert forms[0].fields[0].is_pre_checked is False

    def test_checked_on_non_checkbox_does_not_count(self):
        # `<input type="text" checked>` is meaningless HTML; must not
        # set is_pre_checked or has_pre_checked_box.
        soup = BeautifulSoup(
            '<form><input type="text" name="x" checked></form>',
            "html.parser",
        )
        forms = Crawler._extract_forms(soup, "https://example.com/")
        assert forms[0].has_pre_checked_box is False
        assert forms[0].fields[0].is_pre_checked is False

    def test_multiple_checkboxes_one_pre_checked(self):
        # has_pre_checked_box is form-level OR; one is enough.
        soup = BeautifulSoup(
            '<form>'
            '  <input type="checkbox" name="a">'
            '  <input type="checkbox" name="b" checked>'
            '  <input type="checkbox" name="c">'
            '</form>',
            "html.parser",
        )
        forms = Crawler._extract_forms(soup, "https://example.com/")
        assert forms[0].has_pre_checked_box is True
        per_field = [f.is_pre_checked for f in forms[0].fields]
        assert per_field == [False, True, False]


# ---------------------------------------------------------------------------
# form_analyzer — consent-vocab heuristic
# ---------------------------------------------------------------------------

class TestPreCheckedConsentHeuristic:
    def test_pre_checked_with_german_consent_text(self):
        form = make_form(
            text_content="Ich bin mit der Verarbeitung meiner Daten einverstanden",
            has_checkbox=True, has_pre_checked_box=True,
            fields=[make_field("agree", "checkbox", is_pre_checked=True)],
        )
        assert _has_pre_checked_consent(form) is True

    def test_pre_checked_with_english_consent_text(self):
        form = make_form(
            text_content="I agree to the privacy policy",
            has_checkbox=True, has_pre_checked_box=True,
            fields=[make_field("agree", "checkbox", is_pre_checked=True)],
        )
        assert _has_pre_checked_consent(form) is True

    def test_pre_checked_newsletter_signup(self):
        # Most common abuse pattern in DACH B2B — "Yes, send me the
        # newsletter" pre-ticked at signup time.
        form = make_form(
            text_content="Ja, schickt mir den Newsletter",
            has_checkbox=True, has_pre_checked_box=True,
            fields=[make_field("newsletter", "checkbox", is_pre_checked=True)],
        )
        assert _has_pre_checked_consent(form) is True

    def test_pre_checked_remember_me_does_not_fire(self):
        # "Remember me" is NOT consent in the GDPR sense — it's a
        # session-management preference. Heuristic must skip it.
        form = make_form(
            text_content="Remember me on this device",
            has_checkbox=True, has_pre_checked_box=True,
            fields=[make_field("remember", "checkbox", is_pre_checked=True)],
        )
        assert _has_pre_checked_consent(form) is False

    def test_unchecked_box_with_consent_text_does_not_fire(self):
        # Consent text is fine; the box just has to be UN-checked.
        form = make_form(
            text_content="Ich bin einverstanden",
            has_checkbox=True, has_pre_checked_box=False,
            fields=[make_field("agree", "checkbox", is_pre_checked=False)],
        )
        assert _has_pre_checked_consent(form) is False

    def test_no_checkbox_at_all_does_not_fire(self):
        form = make_form(
            text_content="Mit Absenden willigen Sie ein",
            has_checkbox=False, has_pre_checked_box=False,
        )
        assert _has_pre_checked_consent(form) is False


class TestPlanet49IssueGeneration:
    def test_issue_appears_in_finding(self):
        form = make_form(
            method="POST",
            text_content="Ja, ich bin mit dem Newsletter einverstanden",
            fields=[
                make_field("email", "email"),
                make_field("agree", "checkbox", is_pre_checked=True),
            ],
            has_checkbox=True, has_pre_checked_box=True,
        )
        report = analyze_forms([form], known_privacy_url=None)
        finding = report.forms[0]
        assert finding.has_pre_checked_consent is True
        assert any(
            "planet49" in i.lower() and "pre-checked" in i.lower()
            for i in finding.issues
        ), finding.issues

    def test_summary_counts_pre_checked_forms(self):
        clean = make_form(
            method="POST",
            text_content="Ich bin einverstanden",
            fields=[
                make_field("email", "email"),
                make_field("agree", "checkbox", is_pre_checked=False),
            ],
            has_checkbox=True, has_pre_checked_box=False,
        )
        dirty = make_form(
            method="POST",
            text_content="Ja, Newsletter bitte",
            fields=[
                make_field("email", "email"),
                make_field("nl", "checkbox", is_pre_checked=True),
            ],
            has_checkbox=True, has_pre_checked_box=True,
        )
        report = analyze_forms([clean, dirty], known_privacy_url=None)
        assert report.summary["forms_with_pre_checked_consent"] == 1


# ---------------------------------------------------------------------------
# scoring — hard cap + recommendation
# ---------------------------------------------------------------------------

def _has_cap(result, code: str) -> bool:
    return any(c.code == code for c in result.applied_caps)


class TestScoringCap:
    def test_cap_triggers_when_summary_count_positive(self):
        forms = make_form_report(pii_forms=1, with_consent=1, with_link=1)
        forms.summary["forms_with_pre_checked_consent"] = 1
        forms.forms.append(  # populate forms list so the recommendation has rows to link
            __import__("app.models", fromlist=["FormFinding"]).FormFinding(
                page_url="https://example.com/signup",
                form_action="https://example.com/submit",
                method="POST", purpose="collection",
                collected_data=["email"], field_count=2,
                has_consent_checkbox=True, has_privacy_link=True,
                has_pre_checked_consent=True,
                legal_text_excerpt=None, issues=[],
            ),
        )
        result = compute_risk(
            cookies=make_cookie_report(),
            network=make_network(),
            privacy=make_privacy(),
            forms=forms,
            channels=make_channels(),
            widgets=make_widgets(),
            has_policy=True,
            has_imprint=True,
        )
        assert _has_cap(result, "pre_checked_consent_box")
        assert result.score <= 40

    def test_no_cap_when_summary_count_zero(self):
        forms = make_form_report(pii_forms=1, with_consent=1, with_link=1)
        # forms_with_pre_checked_consent absent → treated as 0.
        result = compute_risk(
            cookies=make_cookie_report(),
            network=make_network(),
            privacy=make_privacy(),
            forms=forms,
            channels=make_channels(),
            widgets=make_widgets(),
            has_policy=True,
            has_imprint=True,
        )
        assert not _has_cap(result, "pre_checked_consent_box")


class TestRecommendation:
    def test_planet49_recommendation_emitted_in_english(self):
        forms = make_form_report(pii_forms=1, with_consent=1, with_link=1)
        forms.summary["forms_with_pre_checked_consent"] = 1
        forms.forms.append(
            __import__("app.models", fromlist=["FormFinding"]).FormFinding(
                page_url="https://example.com/signup",
                form_action="https://example.com/submit",
                method="POST", purpose="collection",
                collected_data=["email"], field_count=2,
                has_consent_checkbox=True, has_privacy_link=True,
                has_pre_checked_consent=True,
                legal_text_excerpt=None, issues=[],
            ),
        )
        result = compute_risk(
            cookies=make_cookie_report(),
            network=make_network(),
            privacy=make_privacy(),
            forms=forms,
            channels=make_channels(),
            widgets=make_widgets(),
            has_policy=True,
            has_imprint=True,
            lang="en",
        )
        titles = " ".join(r.title for r in result.recommendations).lower()
        assert "planet49" in titles or "un-checked" in titles
        # The detail body cites the case AND the article number.
        details = " ".join(r.detail for r in result.recommendations)
        assert "C-673/17" in details
        assert "7(2)" in details

    def test_planet49_recommendation_emitted_in_german(self):
        forms = make_form_report(pii_forms=1, with_consent=1, with_link=1)
        forms.summary["forms_with_pre_checked_consent"] = 1
        forms.forms.append(
            __import__("app.models", fromlist=["FormFinding"]).FormFinding(
                page_url="https://example.com/signup",
                form_action="https://example.com/submit",
                method="POST", purpose="collection",
                collected_data=["email"], field_count=2,
                has_consent_checkbox=True, has_privacy_link=True,
                has_pre_checked_consent=True,
                legal_text_excerpt=None, issues=[],
            ),
        )
        result = compute_risk(
            cookies=make_cookie_report(),
            network=make_network(),
            privacy=make_privacy(),
            forms=forms,
            channels=make_channels(),
            widgets=make_widgets(),
            has_policy=True,
            has_imprint=True,
            lang="de",
        )
        titles = " ".join(r.title for r in result.recommendations)
        assert "Planet49" in titles
        details = " ".join(r.detail for r in result.recommendations)
        assert "DSGVO" in details
        assert "C-673/17" in details
