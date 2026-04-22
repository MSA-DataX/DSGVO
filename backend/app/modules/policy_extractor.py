"""Privacy-policy text extractor.

Given a privacy-policy URL discovered by the crawler, fetch the page (re-using
the live Playwright context if possible — many policies are SPA-rendered) and
return clean main-content text suitable for an LLM.

Why a separate module: privacy policies are uniquely hostile to plain HTML
parsing. They live behind cookie banners, are rendered into a single ``<div>``
with no semantic structure, often span 20k+ words, and frequently embed
nested iframes. Centralising the extraction logic here keeps that mess out
of the AI module.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import BrowserContext, TimeoutError as PWTimeout


log = logging.getLogger("policy_extractor")


# Probed in order on sites where BFS crawl + anchor-text detection found
# nothing. First 200-OK wins. German first because our primary market is DE.
COMMON_POLICY_PATHS: tuple[str, ...] = (
    "/datenschutz",
    "/datenschutz/",
    "/datenschutzerklaerung",
    "/datenschutzerklaerung/",
    "/datenschutzerklärung",
    "/datenschutzerklärung/",
    "/datenschutzhinweise",
    "/datenschutzhinweise/",
    "/datenschutzinformation",
    "/rechtliches/datenschutz",
    "/rechtliches/datenschutz/",
    "/ueber-uns/datenschutz",
    "/ueber-uns/datenschutz/",
    "/service/datenschutz",
    "/service/datenschutz/",
    "/legal/datenschutz",
    "/privacy",
    "/privacy/",
    "/privacy-policy",
    "/privacy-policy/",
    "/privacypolicy",
    "/legal/privacy",
    "/legal/privacy-policy",
    "/en/privacy",
    "/en/privacy-policy",
)


# Tags whose text is almost never part of policy content.
_DROP_TAGS = ("script", "style", "noscript", "svg", "header", "footer", "nav", "form")

# Selectors that often wrap the actual policy text. Tried in order; first hit wins.
# Falls back to <body> if nothing matches.
_MAIN_SELECTORS = (
    "main article",
    "article",
    "main",
    "[role=main]",
    "#content",
    ".content",
    "#privacy-policy",
    ".privacy-policy",
    ".legal",
    ".datenschutz",
    "#datenschutz",
)

_WHITESPACE_RE = re.compile(r"[ \t\u00a0]+")
_BLANKLINE_RE = re.compile(r"\n{3,}")


def _clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(list(_DROP_TAGS)):
        tag.decompose()

    container = None
    for sel in _MAIN_SELECTORS:
        container = soup.select_one(sel)
        if container is not None:
            break
    if container is None:
        container = soup.body or soup

    # Use newline as separator so paragraphs survive — model prompts ride on
    # paragraph structure to find sections.
    text = container.get_text(separator="\n", strip=True)
    text = _WHITESPACE_RE.sub(" ", text)
    text = _BLANKLINE_RE.sub("\n\n", text)
    return text.strip()


async def fetch_policy_text(
    context: BrowserContext,
    policy_url: str,
    timeout_ms: int,
) -> str | None:
    """Render the policy page and return cleaned main-content text.

    Returns ``None`` if the page cannot be fetched at all.
    """
    page = await context.new_page()
    try:
        try:
            await page.goto(policy_url, wait_until="networkidle", timeout=timeout_ms)
        except PWTimeout:
            try:
                await page.goto(policy_url, wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception:
                return None
        except Exception:
            return None

        html = await page.content()
    finally:
        await page.close()

    text = _clean_text(html)
    return text or None


async def probe_common_paths(
    base_url: str,
    timeout_s: float = 5.0,
    user_agent: str | None = None,
) -> str | None:
    """Try common privacy-policy paths against the base URL.

    Used when the crawler's anchor-text detection comes up empty (typical
    for large corporate sites with lazy-loaded footers). Uses cheap httpx
    HEAD requests — no Playwright, no JS, just "does this URL return 2xx?".
    Returns the first match, or None if nothing matched.
    """
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        return None
    origin = f"{parsed.scheme}://{parsed.netloc}"

    headers: dict[str, str] = {"accept": "text/html,*/*;q=0.1"}
    if user_agent:
        headers["user-agent"] = user_agent

    async with httpx.AsyncClient(
        timeout=timeout_s, follow_redirects=True, headers=headers,
    ) as client:
        for path in COMMON_POLICY_PATHS:
            candidate = urljoin(origin, path)
            try:
                # Some hosts refuse HEAD (405) or return misleading sizes;
                # fall back to GET but limit the response read.
                r = await client.head(candidate)
                if r.status_code == 405:
                    r = await client.get(candidate)
            except Exception:
                continue
            if 200 <= r.status_code < 300:
                log.info("probe_common_paths matched: %s", candidate)
                return str(r.url)  # use the final URL after redirects
    return None


def truncate_for_model(text: str, budget_chars: int) -> tuple[str, int]:
    """Trim policy text to fit a token budget.

    For long policies we keep the head AND tail (definitions live at the top,
    rights/contact info at the bottom — sampling only the head loses both).
    Returns the trimmed text and how many chars of the original were sent.
    """
    if len(text) <= budget_chars:
        return text, len(text)
    half = budget_chars // 2 - 100  # leave room for the marker
    head = text[:half].rstrip()
    tail = text[-half:].lstrip()
    sampled = f"{head}\n\n[…TRUNCATED {len(text) - 2 * half} CHARS…]\n\n{tail}"
    return sampled, len(text)
