"""Cookie-wall / "Pay or Okay" detector (Phase 9e).

Pattern: a consent banner offers two choices — "Accept all tracking"
OR "Pay a subscription to use the service ad-free". EDPB Opinion
8/2024 (April 2024) holds that this is NOT valid consent for
"large online platforms" without an "equivalent alternative without
behavioural advertising". German DPAs have followed the EDPB.

Detection runs on the raw banner text (collected by
``consent_ux_audit``). The rule is a two-part conjunction:

  1. The banner contains an "accept" prompt (any consent banner does
     by definition — but we still gate on it so we don't false-
     positive on a generic "subscribe" overlay that isn't a consent
     gate at all).
  2. The banner ALSO contains a "pay/subscribe to avoid tracking"
     prompt — the distinguishing signal.

Both gates must fire. False positives on legit cookie banners that
happen to also link to a subscription page (without making the
subscription a CONDITION of consent) are accepted as the price for a
deterministic, no-AI signal — the auditor verifies. This mirrors the
"verify manually" pattern from Phase 9 (pre-checked consent).
"""

from __future__ import annotations

import re
from typing import Iterable

from app.models import DarkPatternFinding


# "Accept" vocabulary. Cheap to add languages; the existing default-
# language scope is German + English to match the consent_clicker.
_ACCEPT_TOKENS: tuple[str, ...] = (
    "accept all", "accept cookies", "agree", "i agree",
    "alle akzeptieren", "akzeptieren", "zustimmen", "einwilligen",
)

# "Pay / subscribe / become premium to avoid tracking" vocabulary.
# These are the words that turn a consent banner into a cookie wall.
# Single-word matches are gated behind multi-word alternatives where
# the bare word is too generic ("pay" alone matches "pay attention to";
# the requirement to ALSO have the accept-vocab gate filters most of
# that out, but we still prefer multi-word phrases when available).
_PAYWALL_TOKENS: tuple[str, ...] = (
    # English
    "pay to reject", "pay or accept", "subscribe to remove ads",
    "subscribe instead", "ad-free subscription", "without ads",
    "remove ads", "premium subscription",
    # German
    "pur abo", "pur-abo", "werbefrei abonnieren", "werbefreies abo",
    "ohne werbung", "abo abschließen",
    "kostenpflichtiges abo", "abonnement abschließen",
    # Generic single-word fallbacks — kept short to limit false positives.
    # Pair with accept vocabulary in the conjunction below.
    "pay or okay",
    "consent or pay",
)


def _contains_any(haystack: str, tokens: Iterable[str]) -> str | None:
    """Return the first token found, or None. Case-insensitive,
    whitespace-normalised."""
    for token in tokens:
        if token in haystack:
            return token
    return None


def detect_cookie_wall(banner_text: str) -> DarkPatternFinding | None:
    """Inspect ``banner_text`` for the EDPB-Opinion-8/2024 pattern.

    Returns a HIGH-severity :class:`DarkPatternFinding` if both an
    accept prompt AND a pay/subscribe prompt are present in the same
    banner. Returns None otherwise — caller treats None as "no finding
    to add". Always returns a fresh object; never raises.
    """
    if not banner_text or not banner_text.strip():
        return None

    # Normalise whitespace + lowercase so multi-line banners + the
    # German `ß` / case differences both match cleanly.
    haystack = re.sub(r"\s+", " ", banner_text.lower())

    accept_hit = _contains_any(haystack, _ACCEPT_TOKENS)
    if accept_hit is None:
        return None
    paywall_hit = _contains_any(haystack, _PAYWALL_TOKENS)
    if paywall_hit is None:
        return None

    return DarkPatternFinding(
        code="cookie_wall_pay_or_okay",
        severity="high",
        description=(
            "Banner offers consent-or-pay: tracking acceptance is the only "
            "free path. Per EDPB Opinion 8/2024 (April 2024), large online "
            "platforms must offer an 'equivalent alternative without "
            "behavioural advertising' — typically a free, less-tracked tier."
        ),
        evidence={
            "accept_token_matched": accept_hit,
            "paywall_token_matched": paywall_hit,
        },
    )
