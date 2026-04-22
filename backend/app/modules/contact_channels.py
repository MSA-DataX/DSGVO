"""Contact-channel detector.

Walks every link the crawler captured and identifies direct communication
channels the site exposes — WhatsApp / Messenger / Telegram buttons,
`mailto:` / `tel:` / `sms:` schemes, and public social-media profile
links. These are legally relevant because:

- Clicking a WhatsApp button hands the user's phone number + the chat
  content to Meta (US transfer, Schrems II territory).
- A `mailto:` that resolves to an external mailer (Mailchimp, HubSpot)
  is a third-party processor the policy must name.
- Social profile links trigger referrer leakage plus implicit tracking
  once followed.

The policy should name each exposed channel, state a legal basis (usually
Art. 6(1)(a) consent when the user initiates contact, or (1)(f)
legitimate interest for a public profile page), and disclose any
third-country transfer. The AI analyzer gets this list as evidence so it
can cross-check the policy text.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from app.models import ContactChannel, ContactChannelKind, ContactChannelsReport, PageInfo


# Each rule: (kind, regex against the absolute link, vendor/operator, country).
# Regexes must be anchored at the start so we only match the link URL's
# scheme+authority, never an arbitrary substring.
_CHANNEL_RULES: list[tuple[ContactChannelKind, re.Pattern[str], str | None, str]] = [
    # ---- messaging platforms ----
    ("whatsapp",           re.compile(r"^https?://(api\.whatsapp\.com|wa\.me|chat\.whatsapp\.com)/", re.I), "Meta",      "USA"),
    ("whatsapp",           re.compile(r"^whatsapp://", re.I),                                                "Meta",      "USA"),
    ("telegram",           re.compile(r"^https?://(t\.me|telegram\.me)/", re.I),                             "Telegram",  "Other"),
    ("telegram",           re.compile(r"^tg://", re.I),                                                      "Telegram",  "Other"),
    ("signal",             re.compile(r"^https?://signal\.(me|art)/", re.I),                                 "Signal",    "USA"),
    ("facebook_messenger", re.compile(r"^https?://m\.me/", re.I),                                            "Meta",      "USA"),
    ("skype",              re.compile(r"^(skype:|https?://join\.skype\.com/)", re.I),                        "Microsoft", "USA"),

    # ---- direct schemes (destination depends on site backend) ----
    ("email",              re.compile(r"^mailto:", re.I),                                                    None,        "Unknown"),
    ("phone",              re.compile(r"^tel:", re.I),                                                       None,        "Unknown"),
    ("sms",                re.compile(r"^sms:", re.I),                                                       None,        "Unknown"),

    # ---- social profiles (reputation + referrer leakage) ----
    ("facebook_profile",   re.compile(r"^https?://(www\.|de-de\.)?facebook\.com/(?!sharer)[^?/]+", re.I),    "Meta",      "USA"),
    ("instagram_profile",  re.compile(r"^https?://(www\.)?instagram\.com/(?!p/|reel/)[^?/]+", re.I),         "Meta",      "USA"),
    ("linkedin_profile",   re.compile(r"^https?://(www\.|de\.)?linkedin\.com/(in|company|school)/", re.I),   "Microsoft", "USA"),
    ("twitter_profile",    re.compile(r"^https?://(www\.)?(twitter|x)\.com/(?!share|intent)[^?/]+", re.I),   "X (Twitter)","USA"),
    ("youtube_channel",    re.compile(r"^https?://(www\.)?youtube\.com/(@|channel/|c/|user/)", re.I),        "Google",    "USA"),
    ("tiktok_profile",     re.compile(r"^https?://(www\.)?tiktok\.com/@", re.I),                             "ByteDance", "Other"),
    ("xing_profile",       re.compile(r"^https?://(www\.)?xing\.com/(profile|companies|pages)/", re.I),      "New Work SE","EU"),
    ("pinterest_profile",  re.compile(r"^https?://(www\.|de\.)?pinterest\.(com|de)/(?!pin/)[^?/]+", re.I),   "Pinterest", "USA"),

    # ---- less common but worth catching ----
    ("discord",            re.compile(r"^https?://(discord\.gg|discord\.com/invite)/", re.I),                "Discord",   "USA"),
    ("github_profile",     re.compile(r"^https?://(www\.)?github\.com/[^?/]+$", re.I),                       "Microsoft", "USA"),
]


def _mask_email(target: str) -> str:
    """Redact the local-part of a mailto: link for the UI — we surface the
    *existence* of the address, not the address itself."""
    if not target.lower().startswith("mailto:"):
        return target
    rest = target[7:].split("?", 1)[0]
    if "@" not in rest:
        return target
    local, _, domain = rest.partition("@")
    if len(local) <= 2:
        masked_local = "…"
    else:
        masked_local = local[0] + "…" + local[-1]
    suffix = target[7 + len(rest):]  # keep ?subject=… etc
    return f"mailto:{masked_local}@{domain}{suffix}"


def _mask_tel(target: str) -> str:
    """Partially redact tel:/sms: — keep country code + last 2 digits."""
    if not (target.lower().startswith("tel:") or target.lower().startswith("sms:")):
        return target
    scheme, _, rest = target.partition(":")
    digits = re.sub(r"[^\d+]", "", rest)
    if len(digits) < 6:
        return f"{scheme}:…"
    return f"{scheme}:{digits[:3]}…{digits[-2:]}"


def _looks_like_share_widget(url: str) -> bool:
    """`facebook.com/sharer/...`, `twitter.com/intent/tweet?...`, etc. are
    share widgets (the site asks the *visitor* to share), not the site's
    own channel."""
    path = urlparse(url).path.lower()
    return any(
        segment in path
        for segment in ("/sharer", "/share", "/intent/", "/share_offsite")
    )


def detect_contact_channels(pages: list[PageInfo]) -> ContactChannelsReport:
    """Scan every link on every crawled page and return aggregated channels.

    A channel is keyed by (kind, target_url) so the same LinkedIn profile
    linked from 7 pages becomes one entry with ``pages`` listing all 7.
    """
    buckets: dict[tuple[ContactChannelKind, str], ContactChannel] = {}

    for page in pages:
        for href in page.links:
            if _looks_like_share_widget(href):
                continue
            for kind, pattern, vendor, country in _CHANNEL_RULES:
                if not pattern.match(href):
                    continue
                if kind == "email":
                    target = _mask_email(href)
                elif kind in ("phone", "sms"):
                    target = _mask_tel(href)
                else:
                    # Strip query/fragment so `wa.me/491234?text=Hi` and
                    # `wa.me/491234?text=Hello` count as one channel.
                    p = urlparse(href)
                    target = f"{p.scheme}://{p.netloc}{p.path}".rstrip("/")
                    if not target:
                        target = href
                key = (kind, target)
                entry = buckets.get(key)
                if entry is None:
                    buckets[key] = ContactChannel(
                        kind=kind,
                        target=target,
                        vendor=vendor,
                        country=country,  # type: ignore[arg-type]  (Region literal)
                        pages=[page.url],
                    )
                elif page.url not in entry.pages:
                    entry.pages.append(page.url)
                break  # first matching rule wins — don't double-count

    channels = list(buckets.values())

    # Summary counts: one row per kind, plus "high_risk_transfers" for any
    # US/Other/Unknown channel a site operator should pay attention to.
    summary: dict[str, int] = {"total_channels": len(channels)}
    for ch in channels:
        summary[f"kind_{ch.kind}"] = summary.get(f"kind_{ch.kind}", 0) + 1
    summary["us_transfer_channels"] = sum(1 for c in channels if c.country == "USA")
    summary["unknown_jurisdiction_channels"] = sum(1 for c in channels if c.country == "Unknown")

    return ContactChannelsReport(channels=channels, summary=summary)
