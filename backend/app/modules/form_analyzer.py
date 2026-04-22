"""Form analyzer.

Walks every ``<form>`` the crawler captured and reports, deterministically:

- which categories of personal data the form collects (email, name, phone,
  address, password, date_of_birth, payment, national_id, free_text),
- whether there is a consent checkbox,
- whether the form links to the privacy policy,
- a short legal-text excerpt for an auditor to eyeball,
- a list of human-readable issues for the dashboard to render.

Why deterministic instead of AI: form structure is regular HTML and a model
costs ~5s per scan to do something a regex does in microseconds. The AI
budget is better spent on the privacy policy where language ambiguity
actually matters.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from app.models import FormFinding, FormInfo, FormPurpose, FormReport


# field-name / placeholder / type → personal-data category
# Order matters where one keyword could match multiple categories (e.g.
# "phone_number" → phone before national_id).
_FIELD_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(e[-_ ]?mail|email|mailadresse)\b", re.I),                 "email"),
    (re.compile(r"\b(password|passwort|kennwort|pwd)\b", re.I),                 "password"),
    (re.compile(r"\b(phone|telefon|mobile|handy|tel|telnr|telefonnummer|mobilnummer)\b", re.I),
                                                                                "phone"),
    # Names — plus salutation/Anrede which reveals gender and is personal data.
    (re.compile(r"\b(first[_-]?name|vorname|given[_-]?name|nachname|surname|last[_-]?name|name|fullname|"
                r"anrede|salutation|herr|frau|title)\b", re.I),
                                                                                "name"),
    (re.compile(r"\b(street|address|adresse|strasse|straße|plz|postal|zip|city|stadt|ort|country|land|"
                r"hausnummer|wohnort)\b", re.I),
                                                                                "address"),
    (re.compile(r"\b(dob|birth|geburt|geboren|geburtsdatum|birthday)\b", re.I), "date_of_birth"),
    (re.compile(r"\b(iban|bic|kontonr|credit[_-]?card|cc[_-]?number|cardnumber|card[_-]?holder|cvc|cvv)\b", re.I),
                                                                                "payment"),
    (re.compile(r"\b(ssn|tax[_-]?id|steuer|svnr|nationalid|personnummer|ahv|nin)\b", re.I),
                                                                                "national_id"),
    # Free-text / inquiry fields — German + English + a few French/Italian.
    (re.compile(r"\b(message|nachricht|comment|kommentar|inquiry|anfrage|feedback|"
                r"frage|anliegen|wunsch|thema|betreff|subject|"
                r"request|enquiry|question|demande|richiesta)\b", re.I),
                                                                                "free_text"),
    # Company / employer — under GDPR, individual-at-a-company is still PII.
    (re.compile(r"\b(company|firma|unternehmen|organisation|organization|"
                r"employer|arbeitgeber|corp|corporate|business)\b", re.I),
                                                                                "company"),
    # Website / homepage — can be PII when tied to the individual (e.g.
    # consultant contact forms asking for portfolio URL).
    (re.compile(r"\b(website|webseite|homepage|url|portfolio)\b", re.I),        "website"),
]

_INPUT_TYPE_TO_CATEGORY: dict[str, str] = {
    "email":    "email",
    "tel":      "phone",
    "password": "password",
    "date":     "date_of_birth",
}


# Field names that indicate a lookup/search intent rather than data collection.
# e.g. a form that asks for an address just to locate the nearest service
# center is NOT a GDPR contact form — a consent checkbox would be silly UX.
_SEARCH_FIELD_RE = re.compile(
    r"\b(q|query|search|suche|find|finden|lookup|zip|plz|postleitzahl|"
    r"location|ort|stadt|city|address|adresse|strasse|straße|keyword|"
    r"stichwort|filter|sort)\b",
    re.I,
)

# Non-input element types that never count as "data-collection fields" when
# we're deciding between search vs. collection purpose.
_NONDATA_INPUT_TYPES = {None, "submit", "button", "hidden", "reset", "image", "file"}


def _detect_purpose(form: FormInfo) -> FormPurpose:
    """Classify a form's intent.

    - ``authentication``: any password field → login/register form.
    - ``search``: GET method, ≤2 real input fields, and at least one field
      name matches a search/lookup pattern. The combination matters —
      GET alone produces false positives on small newsletter widgets;
      search-term regex alone catches forms with an "address" field that
      are actually full contact forms.
    - ``collection``: default for everything else.
    """
    has_password = any((f.type or "").lower() == "password" for f in form.fields)
    if has_password:
        return "authentication"

    if form.method.upper() == "GET":
        data_inputs = [
            f for f in form.fields
            if (f.type or "").lower() not in _NONDATA_INPUT_TYPES
        ]
        if 1 <= len(data_inputs) <= 2:
            names = " ".join(
                (f.name or "") + " " + (f.type or "") for f in data_inputs
            )
            if _SEARCH_FIELD_RE.search(names):
                return "search"

    return "collection"

# anchor-text / href hints that mean "link to the privacy policy"
_PRIVACY_HREF_HINTS = ("datenschutz", "privacy", "privacidad", "confidentialite", "confidentialité")
_PRIVACY_TEXT_HINTS = (
    "datenschutz", "datenschutzerklärung", "datenschutzhinweis", "privacy policy",
    "privacy notice", "privacy statement", "politique de confidentialité",
)

# Heuristic: if the form's text contains *any* of these tokens, we extract a
# short slice around the first hit as a "legal text" excerpt.
_LEGAL_KEYWORDS = (
    "datenschutz", "einwilligung", "verarbeitung", "consent", "agree",
    "privacy", "personenbezogen", "dsgvo", "gdpr", "i accept", "ich willige",
)


def _detect_categories(form: FormInfo) -> list[str]:
    found: set[str] = set()
    for field in form.fields:
        bag = " ".join(filter(None, [field.name, field.type])).lower()
        if not bag:
            continue
        if field.type and field.type.lower() in _INPUT_TYPE_TO_CATEGORY:
            found.add(_INPUT_TYPE_TO_CATEGORY[field.type.lower()])
        for pattern, category in _FIELD_PATTERNS:
            if pattern.search(bag):
                found.add(category)
    return sorted(found)


def _has_privacy_link(form: FormInfo, known_privacy_url: str | None) -> bool:
    # 1. Match the discovered privacy URL exactly.
    if known_privacy_url:
        for href in form.links:
            if href.rstrip("/") == known_privacy_url.rstrip("/"):
                return True
    # 2. Fall back to URL-path / text hints.
    for href in form.links:
        path = (urlparse(href).path or "").lower()
        if any(h in path for h in _PRIVACY_HREF_HINTS):
            return True
    text = form.text_content.lower()
    return any(h in text for h in _PRIVACY_TEXT_HINTS)


def _legal_excerpt(form: FormInfo) -> str | None:
    text = form.text_content
    if not text:
        return None
    lower = text.lower()
    for kw in _LEGAL_KEYWORDS:
        idx = lower.find(kw)
        if idx >= 0:
            start = max(0, idx - 60)
            end = min(len(text), idx + 220)
            snippet = text[start:end].strip()
            return f"…{snippet}…" if start > 0 or end < len(text) else snippet
    return None


# What we consider personal data (PII) for summary stats and scoring.
# Exported (no underscore prefix) so scoring.py can import it — one source
# of truth keeps the "is this a PII form?" definition identical on both
# sides of the scoring boundary.
PII_CATEGORIES: frozenset[str] = frozenset({
    "email", "phone", "name", "address",
    "date_of_birth", "payment", "national_id",
    "company",  # individual-at-a-company is still PII under GDPR
})
_PII_CATEGORIES = PII_CATEGORIES  # keep local alias for backwards compat within the module


def _build_finding(form: FormInfo, known_privacy_url: str | None) -> FormFinding:
    categories = _detect_categories(form)
    purpose = _detect_purpose(form)
    has_privacy_link = _has_privacy_link(form, known_privacy_url)
    legal_excerpt = _legal_excerpt(form)
    collects_pii = bool(set(categories) & _PII_CATEGORIES)

    issues: list[str] = []

    if purpose == "collection":
        # Full GDPR scrutiny — this is a form where data is submitted to
        # the operator, not a UI control that happens to read one text box.
        if collects_pii and not form.has_checkbox:
            issues.append("Form collects personal data but has no consent checkbox.")
        if collects_pii and not has_privacy_link:
            issues.append("Form collects personal data but does not link to a privacy policy.")
        if collects_pii and not legal_excerpt:
            issues.append("No legal/consent text visible inside the form.")

    elif purpose == "search":
        # Lookup UI. Server still receives the query (and the user's IP,
        # always PII), so a privacy link is still best practice — but a
        # consent checkbox would be absurd ("may we search for what you just
        # typed?"). Flag missing privacy link only, at informational level.
        if collects_pii and not has_privacy_link:
            issues.append(
                "Search form transmits user input to the server without a visible "
                "privacy-policy link (optional — no consent checkbox needed)."
            )

    elif purpose == "authentication":
        # Different ruleset. The password field is the collection boundary;
        # typical auth-form issues are about transport security and session
        # cookies, not consent UX.
        if form.method.upper() != "POST":
            issues.append("Authentication form uses non-POST method — credentials must not go in URL.")
        # Consent/privacy-link concerns don't apply to pure login/register
        # forms the same way. Registration forms that also collect profile
        # data would re-surface as `collection` due to their extra fields.

    # These apply regardless of purpose.
    if "password" in categories and form.method.upper() != "POST":
        # Redundant with the auth check above for auth forms, but covers
        # the rare case of a password field in a non-auth-classified form.
        msg = "Password field submitted via non-POST method."
        if msg not in issues:
            issues.append(msg)
    if "payment" in categories and not form.action:
        issues.append("Payment form has no action URL — cannot verify destination.")

    return FormFinding(
        page_url=form.page_url,
        form_action=form.action,
        method=form.method,
        purpose=purpose,
        collected_data=categories,
        field_count=len(form.fields),
        has_consent_checkbox=form.has_checkbox,
        has_privacy_link=has_privacy_link,
        legal_text_excerpt=legal_excerpt,
        issues=issues,
    )


def analyze_forms(forms: list[FormInfo], known_privacy_url: str | None) -> FormReport:
    findings = [_build_finding(f, known_privacy_url) for f in forms]
    # "Collecting PII" only counts *collection* forms — a search form that
    # happens to take an address field is not PII collection in the GDPR
    # sense, and the risk engine (scoring.py) keys off these counts.
    collection = [f for f in findings if f.purpose == "collection"]
    summary = {
        "total_forms": len(findings),
        "forms_collecting_pii": sum(1 for f in collection if set(f.collected_data) & _PII_CATEGORIES),
        "forms_with_consent_checkbox": sum(1 for f in collection if f.has_consent_checkbox),
        "forms_with_privacy_link": sum(1 for f in collection if f.has_privacy_link),
        "forms_with_issues": sum(1 for f in findings if f.issues),
        "forms_search": sum(1 for f in findings if f.purpose == "search"),
        "forms_authentication": sum(1 for f in findings if f.purpose == "authentication"),
    }
    return FormReport(forms=findings, summary=summary)
