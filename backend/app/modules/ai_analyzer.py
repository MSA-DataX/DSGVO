"""AI-driven privacy-policy analyzer.

Provides an :class:`AIProvider` abstraction with two real backends —
:class:`OpenAIProvider` and :class:`AzureOpenAIProvider` — plus a
:class:`NoOpProvider` so a scan still completes when no API key is set.

The analyzer asks the model to return strict JSON matching our
:class:`~app.models.PrivacyAnalysis` schema. We use ``response_format=
{"type": "json_object"}`` (supported by both OpenAI and Azure OpenAI on
recent models) so the model can't drift into prose, and we validate the
response with Pydantic on the way back. If validation fails, we surface
the parse error rather than silently returning a "passed" result —
auditors need to know when the AI step was unreliable.

Network analysis already produced the third-party data-flow picture; we
pass a *summary* of it into the prompt so the model can cross-check what
the policy *says* against what the site actually *does*. That cross-check
is the single biggest signal that beats reading the policy alone.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from openai import AsyncAzureOpenAI, AsyncOpenAI, APIError, RateLimitError
from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.models import (
    ContactChannel,
    DataFlowEntry,
    PolicyIssue,
    PolicyTopicCoverage,
    PrivacyAnalysis,
    ThirdPartyWidget,
    UiLanguage,
)


log = logging.getLogger("ai_analyzer")


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """\
You are a senior EU data-protection auditor and privacy lawyer. You review
website privacy policies for GDPR (DSGVO) compliance.

OUTPUT LANGUAGE — HARD REQUIREMENT (read this first, follow it last).
The user is reading the report in {summary_language_name}
({summary_language_code}). EVERY natural-language string you emit —
`summary`, every `issues[].description`, every `issues[].action_steps`
entry — MUST be written in {summary_language_name}. Do NOT default to
English just because the evidence blocks (data-flow URLs, domain
names) are English-formatted. Do NOT switch to the policy's language
for these fields. The two specific exceptions are:
  - `suggested_text` follows the POLICY's own language (so the operator
    can paste it directly into their existing policy);
  - `suggested_code` is language-agnostic (programming code).
This is the most common failure mode of past runs and the one that
auditors notice immediately. Re-check every string before finalising
the JSON.

CORE PRINCIPLE — DO NOT TRUST THE POLICY.
Always verify what the policy CLAIMS against what the site ACTUALLY DOES
(the evidence block in the user message lists every third-party domain the
site contacted). A domain the site contacts but the policy does not name
is a `missing_section` issue. A US-based recipient not accompanied by
SCC / adequacy-decision / EU-US Data Privacy Framework language is a
`third_country_transfer` issue of severity HIGH — this is the classic
Schrems II scenario and you must flag it every time.

PRIVACY DISCIPLINE — NEVER REPRODUCE PERSONAL DATA.
The policy text and evidence blocks may incidentally contain real email
addresses, names, phone numbers, contact persons, DPO identities, IBANs,
national IDs, or similar identifiers. Treat every such identifier as
input noise you must NOT echo into your output. Describe categories in
the abstract ("the policy lists a contact email address"), never quote
values ("the policy says 'dpo@example.com'"). Even when citing a
verbatim excerpt, redact PII before returning it. This rule trumps the
accuracy of excerpts — redacted excerpts are always preferable to
leaked identifiers.

EXECUTION FOCUS.
Each issue must be directly actionable. Provide every element the
operator needs to fix it: prose description, suggested policy text
where applicable, implementation code where applicable, a short
imperative action-step list, and a monitoring trigger when the issue
would recur.

General rules:
- Be strict and conservative. Flag only issues with a concrete legal basis
  (cite the Article when relevant). Do not invent issues to look thorough.
- For each issue, cite a short verbatim excerpt from the policy when one
  exists, PII-redacted per the discipline rule above. For issues of
  *absence*, leave excerpt null.
- For each issue, when possible, provide `suggested_text` — a ready-to-paste
  draft paragraph the site operator can add to their policy to close the
  finding. CRITICAL: write `suggested_text` in the SAME LANGUAGE as the
  policy (detect from the text). If the policy is German, `suggested_text`
  must be German. If the policy is French, French. And so on. Do NOT
  translate to English. The draft must be legally accurate, concrete
  (name actual recipients / actual safeguards from the evidence), and
  directly insertable. Leave `suggested_text` null only when the fix is a
  rewrite of existing copy rather than an addition.
- For TECHNICAL issues (missing security header, misconfigured cookie,
  HTML form without consent checkbox, etc.), also provide
  `suggested_code` — a minimal working snippet the operator can paste.
  Preferred formats: nginx/apache directive blocks, HTML fragments, or
  short JS. Leave null when the fix is purely policy-language.
- Always include `action_steps` — 2-4 imperative bullet points that
  execute the fix at the operational level ("Open nginx.conf", "Add
  X to server block", "Reload nginx"). Empty list ONLY when the fix is
  so small that the suggested_text alone is the action.
- Score each issue on TWO axes: `severity` (low/medium/high for UI
  colour coding) and `risk_score` (1-10 ordinal for fine-grained
  ranking — 10 = urgent legal risk, 1 = nice-to-have). risk_score
  should correlate with severity (low ≈ 1-3, medium ≈ 4-6, high ≈ 7-10)
  but give finer ordering within a bucket.
- Set `monitoring_trigger` when the issue could recur or change over time
  (e.g. "new third-party script appears on any page", "privacy policy
  URL changes", "new cookie domain observed"). Null for one-time fixes
  the operator completes once (e.g. "add HSTS header").
- Score `compliance_score` on 0-100. 100 = fully compliant and
  well-written; 0 = no policy or one that ignores GDPR. Use the full
  range; do not cluster around 70. Severe HIGH issues must pull the score
  well below 60.
- The `summary` field and every `issues[].description` MUST be written
  in {summary_language_name} ({summary_language_code}), regardless of the
  policy's own language. `action_steps` follows the same language as
  description. Only `suggested_text` follows the policy language.
  `suggested_code` is always language-agnostic (code).
- Output strict JSON matching the schema in the user message. No prose
  outside the JSON. No markdown fences. No explanatory text before or
  after the JSON object.

AUDIENCE-SAFETY RULE (critical to prevent liability traps in
`suggested_text`):
- Read the SITE CONTEXT block in the user message before drafting any
  policy paragraph. The hostname and page title carry a strong signal
  about who the site is for (e.g. "adhs-spezialambulanz.de" + title
  "ADHS Spezialambulanz für Kinder" = a paediatric ADHD clinic; data
  about minors is in scope by definition).
- If the SITE CONTEXT suggests the site processes data of MINORS,
  PATIENTS, EMPLOYEES, or another specific population, your
  `suggested_text` MUST reflect that — never default to the generic
  "we do not collect data of children / patients / employees"
  boilerplate, which becomes a liability trap when wrong.
- If the SITE CONTEXT is ambiguous about the audience, write the
  `suggested_text` as a CONDITIONAL paragraph that explicitly names
  the assumption ("Sofern Sie Daten von minderjährigen Patienten
  erheben, gilt: …" / "If you process data of minors, the following
  applies: …"). NEVER write an unconditional negative claim about a
  population the site might in fact serve.

STRICT VERIFICATION (companion rule — prevents the OPPOSITE failure
mode where SITE CONTEXT alone is treated as 'addressed'):
- When the SITE CONTEXT indicates a vulnerable population is in the
  site's audience (minors, patients, employees, jobseekers, …), you
  MUST verify the POLICY TEXT itself contains an explicit passage on
  HOW that population's data is handled. Concrete markers to look
  for: parental-consent language (Art. 8 DSGVO / Art. 8 GDPR),
  special-category data clauses (Art. 9 DSGVO — Gesundheitsdaten,
  biometrische Daten), employer-specific bases (§ 26 BDSG), etc.
- Absence of such an explicit passage is a HIGH-severity
  `missing_section` issue. Set
  `coverage.children_data_addressed = false` (or the analogous
  coverage flag for patients / employees) when the policy does not
  contain such a passage — even if the site clearly serves that
  population. Audience presence in SITE CONTEXT is NEVER sufficient
  on its own to flip a coverage flag to true; only explicit policy
  text content does that.
- Concretely: a paediatric clinic whose policy says nothing about
  Art. 8 / parental consent / special-category health data IS
  missing the children's section, and the finding's
  `suggested_text` MUST be the audience-aware draft (per the
  rule above), not the negative boilerplate.
"""


_LANG_NAME: dict[UiLanguage, str] = {
    "en": "English",
    "de": "German",
}


def _system_prompt_for(lang: UiLanguage) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        summary_language_name=_LANG_NAME.get(lang, "English"),
        summary_language_code=lang,
    )


USER_PROMPT_TEMPLATE = """\
RESPONSE LANGUAGE: {summary_language_name} ({summary_language_code})
— write `summary`, all `issues[].description`, and all
`issues[].action_steps` strictly in this language. `suggested_text`
follows the policy's own language. See system prompt for full rule.

Review this website's privacy policy against GDPR (Articles 12-14 in
particular) AND against the observed live-site behavior.

SITE CONTEXT — what this website is. Use this to ground audience-
sensitive drafts (children, patients, employees, …) per the audience-
safety rule in the system message. Hostnames and titles often encode
the audience explicitly (e.g. "kinderpraxis.de", "ADHS Spezialambulanz
für Kinder", "B2B HR Software"); when they do, your `suggested_text`
MUST reflect it.

{site_context_summary}

POLICY URL: {policy_url}
IMPRINT URL: {imprint_url}

EVIDENCE FROM THE LIVE SITE — third-party domains the site actually
contacts. USE THIS AS A CROSS-CHECK: every domain below that is not
acknowledged in the policy is an issue. Every USA-country entry that the
policy does not pair with SCC / EU-US Data Privacy Framework / adequacy
language is a `third_country_transfer` HIGH issue.

{data_flow_summary}

CONTACT CHANNELS EXPOSED ON THE SITE — communication links and buttons
visitors can click (WhatsApp / Messenger / mailto: / tel: / social
profiles …). Each of these triggers data processing: the user's phone
number or email reaches the operator, and for vendor channels
(WhatsApp/Meta/TikTok) the chat metadata reaches a US or other non-EU
platform. CROSS-CHECK AGAINST THE POLICY: every non-EU channel below
without matching legal-basis + third-country-transfer language is an
issue. WhatsApp / Meta / TikTok entries without SCC or EU-US DPF
language are `third_country_transfer` HIGH issues.

{contact_channels_summary}

THIRD-PARTY WIDGETS EMBEDDED ON THE SITE — iframes (video players, maps,
social embeds), chat widgets (Intercom / Drift / Zendesk etc.), and
social-login SDKs (Google / Facebook / Apple sign-in). An entry tagged
[privacy-enhanced] uses the non-tracking variant
(youtube-nocookie.com, Vimeo `?dnt=1`, OpenStreetMap) — those are the
recommended fix, not an issue. CROSS-CHECK AGAINST THE POLICY:
every widget below WITHOUT the [privacy-enhanced] marker, whose vendor
is not named in the policy, is a `missing_section` issue. Tracking
video embeds without consent disclosure + US-transfer disclosure are
HIGH. Chat widgets not named in the policy are HIGH.

{widgets_summary}

POLICY TEXT (may be truncated; truncation is marked with […TRUNCATED…]):
\"\"\"
{policy_text}
\"\"\"

Return JSON exactly matching this schema (all fields required, no extras,
no prose, no markdown fences):

{{
  "summary": "3-6 sentence plain-English summary of what this policy says (always English)",
  "compliance_score": 0-100 integer,
  "coverage": {{
    "legal_basis_stated": boolean,
    "data_categories_listed": boolean,
    "retention_period_stated": boolean,
    "third_party_recipients_listed": boolean,
    "third_country_transfers_disclosed": boolean,
    "user_rights_enumerated": boolean,
    "contact_for_data_protection": boolean,
    "cookie_section_present": boolean,
    "children_data_addressed": boolean
  }},
  "issues": [
    {{
      "category": "missing_section | unclear_wording | risky_processing | third_country_transfer | missing_user_rights | missing_legal_basis | missing_retention | missing_dpo | other",
      "severity": "low | medium | high",
      "risk_score": "integer 1-10, fine-grained priority. 10 = urgent legal risk, 1 = trivial. Must correlate with severity (low≈1-3, medium≈4-6, high≈7-10).",
      "description": "what is wrong, in one sentence, PII-redacted",
      "excerpt": "verbatim quote from the policy, PII-redacted, or null if the issue is an absence",
      "suggested_text": "ready-to-paste draft paragraph the operator can add to the policy to close this finding — IN THE SAME LANGUAGE AS THE POLICY (detect from the text). Concrete: name the actual recipient / actual safeguard from the evidence. Legally accurate. May be null only when the fix is a rewrite of existing copy rather than an insertion.",
      "suggested_code": "when the fix is technical, a minimal working snippet (nginx/apache directive, HTML fragment, short JS). Null for pure policy-language fixes.",
      "action_steps": ["2-4 imperative bullet points that execute the fix operationally, e.g. 'Open nginx.conf', 'Add `add_header X ...`', 'Run nginx -t', 'Reload'. Empty list allowed when suggested_text alone is the action."],
      "monitoring_trigger": "when should a re-scan alert on this? e.g. 'new third-party script on any page', 'privacy policy URL changes'. Null for one-time fixes."
    }}
  ]
}}
"""


def _format_site_context(site_context: dict[str, str] | None) -> str:
    """Render the SITE CONTEXT block.

    Accepts a small dict (kept loose so the caller doesn't need a
    dedicated Pydantic model) with keys ``hostname`` (required) and
    optional ``page_title`` / ``target_url``. Missing optional fields
    render as ``(unknown)`` — the model still gets the hostname which
    is itself a strong audience signal in most cases.
    """
    if not site_context:
        return "(no site context provided)"
    hostname = site_context.get("hostname") or "(unknown)"
    title = site_context.get("page_title") or "(no title tag)"
    target = site_context.get("target_url") or hostname
    return (
        f"- Hostname: {hostname}\n"
        f"- Homepage title: {title}\n"
        f"- Scanned URL: {target}"
    )


def _format_data_flow(data_flow: list[DataFlowEntry]) -> str:
    if not data_flow:
        return "(none observed)"
    lines = []
    for entry in data_flow[:30]:  # cap so prompt stays bounded
        cats = ", ".join(entry.categories) if entry.categories else "uncategorized"
        lines.append(
            f"- {entry.domain} ({entry.country}, risk={entry.risk}, "
            f"{entry.request_count} requests, categories: {cats})"
        )
    if len(data_flow) > 30:
        lines.append(f"- (… {len(data_flow) - 30} more domains omitted)")
    return "\n".join(lines)


def _format_channels(channels: list[ContactChannel]) -> str:
    """Render contact channels (WhatsApp, mailto:, social profiles, …) as
    evidence the model can cross-check against the policy text."""
    if not channels:
        return "(none observed)"
    lines = []
    for c in channels[:25]:
        vendor = c.vendor or "—"
        lines.append(f"- {c.kind}: {c.target} (vendor: {vendor}, country: {c.country})")
    if len(channels) > 25:
        lines.append(f"- (… {len(channels) - 25} more channels omitted)")
    return "\n".join(lines)


def _format_widgets(widgets: list[ThirdPartyWidget]) -> str:
    """Render embedded third-party widgets (YouTube/Maps iframes, chat
    widgets, social-login SDKs) as evidence for the policy cross-check."""
    if not widgets:
        return "(none observed)"
    lines = []
    for w in widgets[:25]:
        vendor = w.vendor or "—"
        enhanced = " [privacy-enhanced]" if w.privacy_enhanced else ""
        lines.append(
            f"- {w.category}/{w.kind}: {w.src} (vendor: {vendor}, "
            f"country: {w.country}){enhanced}"
        )
    if len(widgets) > 25:
        lines.append(f"- (… {len(widgets) - 25} more widgets omitted)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------

class AIProvider(ABC):
    name: str

    @abstractmethod
    async def analyze_policy(
        self,
        policy_text: str,
        policy_url: str,
        data_flow: list[DataFlowEntry],
        chars_sent: int,
        channels: list[ContactChannel] | None = None,
        imprint_url: str | None = None,
        widgets: list[ThirdPartyWidget] | None = None,
        lang: UiLanguage = "en",
        site_context: dict[str, str] | None = None,
    ) -> PrivacyAnalysis: ...


class NoOpProvider(AIProvider):
    name = "none"

    async def analyze_policy(
        self,
        policy_text: str,
        policy_url: str,
        data_flow: list[DataFlowEntry],
        chars_sent: int,
        channels: list[ContactChannel] | None = None,
        imprint_url: str | None = None,
        widgets: list[ThirdPartyWidget] | None = None,
        lang: UiLanguage = "en",
        site_context: dict[str, str] | None = None,
    ) -> PrivacyAnalysis:
        return PrivacyAnalysis(
            provider="none",
            model=None,
            policy_url=policy_url or None,
            summary="AI analysis skipped: no provider configured.",
            issues=[],
            coverage=None,
            compliance_score=0,
            excerpt_chars_sent=0,
            error="no_provider_configured",
        )


class _OpenAILikeProvider(AIProvider):
    """Shared logic for OpenAI / Azure OpenAI — the only difference is the
    client constructor and the model/deployment identifier."""

    def __init__(self, client: AsyncOpenAI | AsyncAzureOpenAI, model: str, name: str):
        self._client = client
        self._model = model
        self.name = name

    @retry(
        retry=retry_if_exception_type((RateLimitError, APIError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        reraise=True,
    )
    async def _call(self, messages: list[dict[str, str]]) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,
            timeout=settings.ai_request_timeout_s,
        )
        return resp.choices[0].message.content or "{}"

    async def analyze_policy(
        self,
        policy_text: str,
        policy_url: str,
        data_flow: list[DataFlowEntry],
        chars_sent: int,
        channels: list[ContactChannel] | None = None,
        imprint_url: str | None = None,
        widgets: list[ThirdPartyWidget] | None = None,
        lang: UiLanguage = "en",
        site_context: dict[str, str] | None = None,
    ) -> PrivacyAnalysis:
        messages = [
            {"role": "system", "content": _system_prompt_for(lang)},
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(
                    summary_language_name=_LANG_NAME.get(lang, "English"),
                    summary_language_code=lang,
                    site_context_summary=_format_site_context(site_context),
                    policy_url=policy_url or "(unknown)",
                    imprint_url=imprint_url or "(not located)",
                    data_flow_summary=_format_data_flow(data_flow),
                    contact_channels_summary=_format_channels(channels or []),
                    widgets_summary=_format_widgets(widgets or []),
                    policy_text=policy_text,
                ),
            },
        ]

        try:
            raw = await self._call(messages)
        except Exception as e:
            log.warning("AI provider call failed: %s", e)
            return _failed_analysis(self.name, self._model, policy_url, chars_sent, str(e))

        try:
            payload: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as e:
            return _failed_analysis(
                self.name, self._model, policy_url, chars_sent,
                f"model returned non-JSON: {e}"
            )

        # Parse issues one-by-one so a single malformed item from the model
        # doesn't void the entire analysis. Skip + count bad ones rather
        # than raising — auditors prefer partial results to none.
        raw_issues = payload.get("issues") or []
        issues: list[PolicyIssue] = []
        skipped = 0
        for raw_iss in raw_issues:
            try:
                issues.append(PolicyIssue(**raw_iss))
            except (ValidationError, TypeError) as e:
                log.debug("dropping malformed issue from model: %s", e)
                skipped += 1

        try:
            coverage = PolicyTopicCoverage(**payload["coverage"]) if payload.get("coverage") else None
            analysis = PrivacyAnalysis(
                provider=self.name,
                model=self._model,
                policy_url=policy_url or None,
                summary=str(payload.get("summary", "")).strip(),
                issues=issues,
                coverage=coverage,
                compliance_score=int(payload.get("compliance_score", 0)),
                excerpt_chars_sent=chars_sent,
                error=f"dropped {skipped} malformed issue(s) from model output" if skipped else None,
            )
            return analysis
        except (ValidationError, KeyError, TypeError, ValueError) as e:
            return _failed_analysis(
                self.name, self._model, policy_url, chars_sent,
                f"model output failed schema validation: {e}"
            )


def _failed_analysis(
    provider: str, model: str | None, policy_url: str, chars_sent: int, err: str
) -> PrivacyAnalysis:
    return PrivacyAnalysis(
        provider=provider,
        model=model,
        policy_url=policy_url or None,
        summary="AI analysis failed; see error field.",
        issues=[],
        coverage=None,
        compliance_score=0,
        excerpt_chars_sent=chars_sent,
        error=err,
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_provider() -> AIProvider:
    pick = (settings.ai_provider or "none").lower()

    if pick == "openai":
        if not settings.openai_api_key:
            log.warning("AI_PROVIDER=openai but OPENAI_API_KEY is empty; using NoOpProvider")
            return NoOpProvider()
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        return _OpenAILikeProvider(client, settings.openai_model, name="openai")

    if pick == "azure":
        missing = [
            n for n, v in {
                "AZURE_OPENAI_API_KEY": settings.azure_openai_api_key,
                "AZURE_OPENAI_ENDPOINT": settings.azure_openai_endpoint,
                "AZURE_OPENAI_DEPLOYMENT": settings.azure_openai_deployment,
            }.items() if not v
        ]
        if missing:
            log.warning("AI_PROVIDER=azure but %s missing; using NoOpProvider", ", ".join(missing))
            return NoOpProvider()
        client = AsyncAzureOpenAI(
            api_key=settings.azure_openai_api_key,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
        )
        # On Azure the "model" arg to chat.completions.create is the deployment name.
        return _OpenAILikeProvider(client, settings.azure_openai_deployment, name="azure")

    return NoOpProvider()
