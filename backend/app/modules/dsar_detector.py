"""Deterministic Data Subject Access Request detector (Phase 9d).

Reads a privacy policy's plain text and answers: "does this policy
explain how a data subject exercises their GDPR Art. 15-22 rights?"

Why deterministic when we already have an AI analyzer:

  - The AI provider is opt-in (``AI_PROVIDER=none`` is a valid mode).
    Without the AI, ``PolicyTopicCoverage.user_rights_enumerated``
    is missing entirely and the scoring engine has no signal at all
    for "does the policy actually list the rights?". This module
    fills that gap.
  - It serves as a cross-check on the AI's prose-level judgement.
    If the AI says "rights enumerated" but our regex finds zero of
    the seven canonical rights, that's a useful hint that the AI
    saw something the auditor should re-read.

The check is bilingual (German + English) because the typical DACH
B2B policy is one of those two languages. Other languages will
silently produce ``score=0`` — operators can override with the AI
layer.
"""

from __future__ import annotations

import re
from typing import Iterable

from app.models import DsarCheck


# Each canonical right is matched by ANY of its phrases. Phrase
# choices favour precision: "auskunft" alone is too generic
# (it's used in many non-rights contexts, e.g.
# "Telefonauskunft"), so we anchor with "Recht auf Auskunft" or
# "Auskunftsrecht". For English, single-word matches like
# "rectification" are fine — they only appear in legal text.
_RIGHTS_VOCAB: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("access", (
        "right of access", "right to access",
        "recht auf auskunft", "auskunftsrecht",
    )),
    ("rectification", (
        "right to rectification", "rectification",
        "recht auf berichtigung", "berichtigungsrecht",
    )),
    ("erasure", (
        "right to erasure", "right to be forgotten", "right to erase",
        "recht auf löschung", "recht auf vergessenwerden",
        "loeschungsrecht", "löschungsrecht",
    )),
    ("restriction", (
        "right to restriction", "restriction of processing",
        "recht auf einschränkung",
        "einschraenkung der verarbeitung",
        "einschränkung der verarbeitung",
    )),
    ("portability", (
        "right to data portability", "data portability",
        "recht auf datenübertragbarkeit",
        "datenuebertragbarkeit", "datenübertragbarkeit",
    )),
    ("objection", (
        "right to object", "right of objection",
        "recht auf widerspruch", "widerspruchsrecht",
    )),
    ("complaint", (
        # Pair complaint with supervisory-authority keyword so a
        # general "complaint form" doesn't false-positive.
        "supervisory authority", "data protection authority",
        "aufsichtsbehörde", "aufsichtsbehoerde",
        "datenschutzbehörde", "datenschutzbehoerde",
    )),
    ("withdraw_consent", (
        "withdraw consent", "withdrawal of consent",
        "widerruf der einwilligung", "einwilligung widerrufen",
    )),
)

# Conservative contact signals. We don't try to verify the contact is
# specifically for rights requests (the AI's job) — just that A
# contact exists in the policy text.
_CONTACT_PATTERNS: tuple[str, ...] = (
    r"mailto:",
    r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",        # email-shaped
    r"datenschutzbeauftragt",                # DPO contact (DE)
    r"data protection officer",
    r"data protection contact",
    r"\bdpo\b",
)
_CONTACT_RE = re.compile("|".join(_CONTACT_PATTERNS), re.IGNORECASE)

# How many rights you'd expect a comprehensive policy to enumerate
# before we stop adding score weight. Eight named rights × 10.5 ≈ 84,
# leaving 16 for the contact bit. Anything ≥ 5 named rights gets
# rounded up generously.
_RIGHTS_FULL_COUNT = 8


def detect_dsar(policy_text: str) -> DsarCheck:
    """Inspect ``policy_text`` and return a :class:`DsarCheck`.

    Empty / whitespace-only input returns a zero-score result; the
    caller decides whether that means "fall back to AI judgement"
    or "flag as missing".
    """
    if not policy_text or not policy_text.strip():
        return DsarCheck()

    # Normalise whitespace so multi-line phrasings like
    # "the right to withdraw\nconsent" still match the canonical
    # "withdraw consent" token. Real policies wrap aggressively;
    # without this we false-negative on legit enumerations.
    haystack = re.sub(r"\s+", " ", policy_text.lower())

    named: list[str] = []
    for canonical, phrases in _RIGHTS_VOCAB:
        if any(phrase in haystack for phrase in phrases):
            named.append(canonical)

    contact_excerpt: str | None = None
    has_contact = False
    match = _CONTACT_RE.search(policy_text)
    if match is not None:
        has_contact = True
        # Trim to a short window around the match so the dashboard
        # has something concrete to display without hauling the whole
        # paragraph in.
        start = max(0, match.start() - 60)
        end = min(len(policy_text), match.end() + 120)
        snippet = policy_text[start:end].strip()
        contact_excerpt = f"…{snippet}…" if start > 0 or end < len(policy_text) else snippet

    score = _score(named, has_contact)
    return DsarCheck(
        named_rights=named,
        has_rights_contact=has_contact,
        contact_excerpt=contact_excerpt,
        score=score,
    )


def _score(named: Iterable[str], has_contact: bool) -> int:
    n = len(list(named))
    # 8 rights × 10 = 80 points max for the rights enumeration,
    # 20 points for the contact mention. Caps at 100 by construction.
    rights_score = min(_RIGHTS_FULL_COUNT, n) * 10
    contact_score = 20 if has_contact else 0
    return min(100, rights_score + contact_score)
