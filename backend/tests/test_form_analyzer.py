"""Tests for form_analyzer.

Coverage focus:
- Purpose detection (search / authentication / collection / unknown) —
  the field that fixed the Gewobag false-positive bug, so regressions
  here would be felt immediately.
- PII category detection — regex-heavy, easy to break by adding new
  keywords.
- Issue generation rules per purpose — must not re-introduce the
  "search form flagged as PII collection" bug.
- Summary counts — scoring.py keys off these.
"""

from __future__ import annotations

from app.modules.form_analyzer import (
    PII_CATEGORIES,
    _detect_categories,
    _detect_purpose,
    analyze_forms,
)

from .conftest import make_field, make_form


# ---------------------------------------------------------------------------
# _detect_purpose — the Gewobag fix
# ---------------------------------------------------------------------------

class TestDetectPurpose:
    def test_password_field_is_authentication(self):
        form = make_form(fields=[
            make_field("user", "text"),
            make_field("pass", "password"),
        ])
        assert _detect_purpose(form) == "authentication"

    def test_get_with_single_address_field_is_search(self):
        # Literal Gewobag case: GET to find local service center by address.
        form = make_form(
            method="GET",
            fields=[make_field("address", "text")],
        )
        assert _detect_purpose(form) == "search"

    def test_get_with_query_field_is_search(self):
        form = make_form(
            method="GET",
            fields=[make_field("q", "text")],
        )
        assert _detect_purpose(form) == "search"

    def test_get_with_plz_field_is_search(self):
        form = make_form(
            method="GET",
            fields=[make_field("plz", "text")],
        )
        assert _detect_purpose(form) == "search"

    def test_post_with_address_is_collection_not_search(self):
        # Same field but POST — treated as data submission.
        form = make_form(
            method="POST",
            fields=[make_field("address", "text")],
        )
        assert _detect_purpose(form) == "collection"

    def test_get_with_many_fields_is_collection(self):
        # More than 2 input fields → likely not a search UI even on GET.
        form = make_form(method="GET", fields=[
            make_field("name", "text"),
            make_field("email", "email"),
            make_field("phone", "tel"),
        ])
        assert _detect_purpose(form) == "collection"

    def test_get_with_newsletter_is_not_search(self):
        # "email" is not in the search-field whitelist, so a GET newsletter
        # signup still gets full collection scrutiny.
        form = make_form(method="GET", fields=[make_field("email", "email")])
        assert _detect_purpose(form) == "collection"

    def test_empty_form_is_collection(self):
        # No data-input fields at all — default purpose.
        form = make_form(fields=[make_field("submit", "submit")])
        assert _detect_purpose(form) == "collection"


# ---------------------------------------------------------------------------
# _detect_categories — PII regex matrix
# ---------------------------------------------------------------------------

class TestDetectCategories:
    def test_email_via_type_attribute(self):
        form = make_form(fields=[make_field("anyname", "email")])
        assert "email" in _detect_categories(form)

    def test_email_via_field_name(self):
        form = make_form(fields=[make_field("mailadresse", "text")])
        assert "email" in _detect_categories(form)

    def test_password_detected(self):
        form = make_form(fields=[make_field("pwd", "password")])
        assert "password" in _detect_categories(form)

    def test_phone_via_type_tel(self):
        form = make_form(fields=[make_field("contact", "tel")])
        assert "phone" in _detect_categories(form)

    def test_phone_via_field_name(self):
        form = make_form(fields=[make_field("telefonnummer", "text")])
        assert "phone" in _detect_categories(form)

    def test_name_via_vorname(self):
        form = make_form(fields=[make_field("vorname", "text")])
        assert "name" in _detect_categories(form)

    def test_name_via_anrede(self):
        form = make_form(fields=[make_field("anrede", "text")])
        assert "name" in _detect_categories(form)

    def test_address_via_plz(self):
        form = make_form(fields=[make_field("plz", "text")])
        assert "address" in _detect_categories(form)

    def test_address_via_strasse(self):
        form = make_form(fields=[make_field("strasse", "text")])
        assert "address" in _detect_categories(form)

    def test_dob_via_geburtsdatum(self):
        form = make_form(fields=[make_field("geburtsdatum", "date")])
        cats = _detect_categories(form)
        assert "date_of_birth" in cats

    def test_payment_via_iban(self):
        form = make_form(fields=[make_field("iban", "text")])
        assert "payment" in _detect_categories(form)

    def test_free_text_via_nachricht(self):
        form = make_form(fields=[make_field("nachricht", "textarea")])
        assert "free_text" in _detect_categories(form)

    def test_company_via_firma(self):
        # Added in Phase 1 — investor-relations case
        form = make_form(fields=[make_field("firma", "text")])
        assert "company" in _detect_categories(form)

    def test_multiple_categories(self):
        form = make_form(fields=[
            make_field("email", "email"),
            make_field("vorname", "text"),
            make_field("firma", "text"),
        ])
        cats = set(_detect_categories(form))
        assert {"email", "name", "company"}.issubset(cats)

    def test_no_match_means_no_categories(self):
        form = make_form(fields=[make_field("__weird_field__", "text")])
        assert _detect_categories(form) == []


# ---------------------------------------------------------------------------
# PII_CATEGORIES export — scoring.py keys off this
# ---------------------------------------------------------------------------

def test_pii_categories_includes_company():
    # Regression guard: the bilingual refactor added 'company' to the set
    # so scoring.py now counts company-only forms as PII. Anyone dropping
    # it back would silently stop flagging investor-relations-style forms.
    assert "company" in PII_CATEGORIES


def test_pii_categories_excludes_free_text_and_website():
    # 'free_text' and 'website' exist as detection categories but are
    # intentionally NOT in PII_CATEGORIES — a contact form with only a
    # "Nachricht" field shouldn't flip on the strict PII scoring rules.
    assert "free_text" not in PII_CATEGORIES
    assert "website"   not in PII_CATEGORIES


# ---------------------------------------------------------------------------
# Issue generation rules per purpose
# ---------------------------------------------------------------------------

class TestIssueGeneration:
    def test_collection_form_without_consent_is_flagged(self):
        form = make_form(
            method="POST",
            fields=[make_field("email", "email"), make_field("name", "text")],
            has_checkbox=False,
        )
        report = analyze_forms([form], known_privacy_url=None)
        issues = report.forms[0].issues
        assert any("consent checkbox" in i.lower() for i in issues)

    def test_collection_form_with_consent_and_link_is_clean(self):
        form = make_form(
            method="POST",
            fields=[make_field("email", "email"), make_field("name", "text")],
            has_checkbox=True,
            text_content="Datenschutz einverstanden",
            links=["https://example.com/datenschutz"],
        )
        report = analyze_forms([form], known_privacy_url="https://example.com/datenschutz")
        assert report.forms[0].issues == []

    def test_search_form_does_not_flag_missing_consent_checkbox(self):
        # The regression we actually hit: Gewobag's "find my service
        # center" GET form used to throw 3 false-positive issues.
        form = make_form(
            method="GET",
            fields=[make_field("address", "text")],
            has_checkbox=False,
        )
        report = analyze_forms([form], known_privacy_url=None)
        issues = report.forms[0].issues
        # The specific false positives from before: a hard "no consent checkbox"
        # requirement must NOT appear. The soft note "no consent checkbox needed"
        # (which contains the phrase but negates it) IS acceptable.
        assert not any(
            "no consent checkbox" in i.lower() and "needed" not in i.lower()
            for i in issues
        ), issues
        # A softer "no privacy link" issue IS acceptable on search forms
        # (search-form message explicitly says "optional, no consent needed").
        assert report.forms[0].purpose == "search"

    def test_authentication_form_with_non_post_method_flagged(self):
        # Login form via GET leaks credentials in the URL.
        form = make_form(
            method="GET",
            fields=[make_field("user", "text"), make_field("pass", "password")],
        )
        report = analyze_forms([form], known_privacy_url=None)
        issues = report.forms[0].issues
        assert any("non-post" in i.lower() for i in issues)

    def test_password_in_non_auth_form_via_get_is_flagged(self):
        # Odd shape: password field on a GET form that isn't classified as
        # authentication. We still need to warn.
        form = make_form(
            method="GET",
            fields=[make_field("secret", "password")],
        )
        report = analyze_forms([form], known_privacy_url=None)
        # _detect_purpose returns "authentication" for any form with a
        # password field, so the auth branch catches it. The assertion:
        # whatever branch handles it, the non-POST warning must appear.
        assert any("non-post" in i.lower() for i in report.forms[0].issues)

    def test_payment_form_without_action_flagged(self):
        form = make_form(
            method="POST", action=None,
            fields=[make_field("iban", "text")],
        )
        report = analyze_forms([form], known_privacy_url=None)
        assert any("payment" in i.lower() and "action" in i.lower()
                   for i in report.forms[0].issues)


# ---------------------------------------------------------------------------
# Summary counts
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_only_counts_collection_forms_as_pii(self):
        # Mixed: one collection PII, one search with PII-looking field.
        # scoring.py uses forms_collecting_pii; must NOT include the search.
        collection = make_form(method="POST", fields=[make_field("email", "email")])
        search = make_form(method="GET", fields=[make_field("address", "text")])
        report = analyze_forms([collection, search], known_privacy_url=None)
        assert report.summary["forms_collecting_pii"] == 1
        assert report.summary["forms_search"] == 1
        assert report.summary["total_forms"] == 2

    def test_consent_checkbox_counted_only_for_collection(self):
        # Search form has a checkbox too, but it shouldn't count in the
        # "how many PII forms have consent" metric.
        collection_with_checkbox = make_form(
            method="POST",
            fields=[make_field("email", "email")],
            has_checkbox=True,
        )
        search_with_checkbox = make_form(
            method="GET",
            fields=[make_field("address", "text")],
            has_checkbox=True,
        )
        report = analyze_forms(
            [collection_with_checkbox, search_with_checkbox],
            known_privacy_url=None,
        )
        assert report.summary["forms_with_consent_checkbox"] == 1

    def test_empty_list_gives_zeros(self):
        report = analyze_forms([], known_privacy_url=None)
        assert report.forms == []
        assert report.summary["total_forms"] == 0
        assert report.summary["forms_collecting_pii"] == 0


# ---------------------------------------------------------------------------
# FormFinding integrity
# ---------------------------------------------------------------------------

def test_finding_carries_through_form_metadata():
    form = make_form(
        method="POST",
        action="https://example.com/x",
        page_url="https://example.com/kontakt",
        fields=[make_field("email", "email"), make_field("name", "text")],
        has_checkbox=True,
        links=["https://example.com/datenschutz"],
    )
    report = analyze_forms([form], known_privacy_url="https://example.com/datenschutz")
    f = report.forms[0]
    assert f.method == "POST"
    assert f.form_action == "https://example.com/x"
    assert f.page_url == "https://example.com/kontakt"
    assert f.field_count == 2
    assert f.has_consent_checkbox is True
    assert f.has_privacy_link is True
    assert set(f.collected_data) == {"email", "name"}
