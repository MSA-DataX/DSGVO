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

CORE PRINCIPLE — DO NOT TRUST THE POLICY.
Always verify what the policy CLAIMS against what the site ACTUALLY DOES
(the evidence block in the user message lists every third-party domain the
site contacted). A domain the site contacts but the policy does not name
is a `missing_section` issue. A US-based recipient not accompanied by
SCC / adequacy-decision / EU-US Data Privacy Framework language is a
`third_country_transfer` issue of severity HIGH — this is the classic
Schrems II scenario and you must flag it every time.

General rules:
- Be strict and conservative. Flag only issues with a concrete legal basis
  (cite the Article when relevant). Do not invent issues to look thorough.
- For each issue, cite a short verbatim excerpt from the policy when one
  exists. For issues of *absence*, leave excerpt null.
- For each issue, when possible, provide `suggested_text` — a ready-to-paste
  draft paragraph the site operator can add to their policy to close the
  finding. CRITICAL: write `suggested_text` in the SAME LANGUAGE as the
  policy (detect from the text). If the policy is German, `suggested_text`
  must be German. If the policy is French, French. And so on. Do NOT
  translate to English. The draft must be legally accurate, concrete
  (name actual recipients / actual safeguards from the evidence), and
  directly insertable. Leave `suggested_text` null only when the fix is a
  rewrite of existing copy rather than an addition.
- Score `compliance_score` on 0-100. 100 = fully compliant and
  well-written; 0 = no policy or one that ignores GDPR. Use the full
  range; do not cluster around 70. Severe HIGH issues must pull the score
  well below 60.
- The `summary` field and every `issues[].description` MUST be written
  in {summary_language_name} ({summary_language_code}), regardless of the
  policy's own language. Only `suggested_text` follows the policy
  language as described above.
- Output strict JSON matching the schema in the user message. No prose
  outside the JSON. No markdown fences. No explanatory text before or
  after the JSON object.
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
Review this website's privacy policy against GDPR (Articles 12-14 in
particular) AND against the observed live-site behavior.

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
      "description": "what is wrong, in one sentence (English)",
      "excerpt": "verbatim quote from the policy, or null if the issue is an absence",
      "suggested_text": "ready-to-paste draft paragraph the operator can add to the policy to close this finding — IN THE SAME LANGUAGE AS THE POLICY (detect from the text). Concrete: name the actual recipient / actual safeguard from the evidence. Legally accurate. May be null only when the fix is a rewrite of existing copy rather than an insertion."
    }}
  ]
}}
"""


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
    ) -> PrivacyAnalysis:
        messages = [
            {"role": "system", "content": _system_prompt_for(lang)},
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(
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
