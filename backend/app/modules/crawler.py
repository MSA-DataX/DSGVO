"""Website crawler.

BFS-crawls a target site (same registered domain) up to a depth/page limit
using Playwright. For each visited page, extracts links, scripts, and forms,
and flags privacy-policy candidates.

The crawler does NOT manage the browser lifecycle — callers pass in a
Playwright BrowserContext so that a NetworkAnalyzer can attach its own
listeners to the same context and observe every request the crawler triggers.
"""

from __future__ import annotations

import asyncio
from collections import deque
from urllib.parse import urldefrag, urljoin, urlparse

import tldextract
from bs4 import BeautifulSoup
from playwright.async_api import BrowserContext, Page, TimeoutError as PWTimeout

from app.models import CrawlResult, FormField, FormInfo, PageInfo
from app.modules.cookie_scanner import snapshot_page_storage
from app.progress import NoopReporter, ProgressReporter


PRIVACY_HINTS = (
    "datenschutz",
    "datenschutzerklaerung",
    "datenschutzerklärung",
    "privacy",
    "privacy-policy",
    "privacypolicy",
    "privacidad",
    "confidentialite",
    "confidentialité",
)

# § 5 TMG — German commercial sites must have an imprint. English "imprint"
# is the standard international equivalent.
IMPRINT_HINTS = (
    "impressum",
    "imprint",
    "mentions-legales",
    "mentions_legales",
    "legal-notice",
    "legalnotice",
)


def _registered_domain(url: str) -> str:
    ext = tldextract.extract(url)
    if not ext.domain:
        return ""
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain


def _looks_like_privacy_policy(url: str, anchor_text: str | None = None) -> bool:
    haystacks: list[str] = [url.lower()]
    if anchor_text:
        haystacks.append(anchor_text.lower())
    return any(h in s for s in haystacks for h in PRIVACY_HINTS)


def _looks_like_imprint(url: str, anchor_text: str | None = None) -> bool:
    haystacks: list[str] = [url.lower()]
    if anchor_text:
        haystacks.append(anchor_text.lower())
    return any(h in s for s in haystacks for h in IMPRINT_HINTS)


def _normalize(url: str) -> str:
    url, _ = urldefrag(url)
    return url.rstrip("/")


class Crawler:
    def __init__(
        self,
        context: BrowserContext,
        max_depth: int,
        max_pages: int,
        page_timeout_ms: int,
        progress: ProgressReporter | None = None,
    ) -> None:
        self.context = context
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.page_timeout_ms = page_timeout_ms
        self.progress = progress or NoopReporter()

    async def crawl(self, start_url: str) -> CrawlResult:
        start_url = _normalize(start_url)
        target_domain = _registered_domain(start_url)

        seen: set[str] = {start_url}
        queue: deque[tuple[str, int, str | None]] = deque([(start_url, 0, None)])
        pages: list[PageInfo] = []
        privacy_url: str | None = None

        while queue and len(pages) < self.max_pages:
            url, depth, anchor_text = queue.popleft()
            self.progress.emit(
                "crawling",
                f"Visiting page {len(pages) + 1}/{self.max_pages}: {url}",
                {"page_index": len(pages) + 1, "url": url, "depth": depth},
            )
            page = await self.context.new_page()
            try:
                info = await self._visit(page, url, depth, anchor_text)
            finally:
                await page.close()

            if info is None:
                continue

            pages.append(info)
            if info.is_privacy_policy and privacy_url is None:
                privacy_url = info.url

            if depth >= self.max_depth:
                continue

            for link, link_text in self._iter_internal_links(info, target_domain):
                norm = _normalize(link)
                if norm in seen:
                    continue
                seen.add(norm)
                queue.append((norm, depth + 1, link_text))

        # If we never visited a privacy page but discovered one, fetch it once
        # so it appears in the crawl result + network capture.
        if privacy_url is None:
            for p in pages:
                for link, link_text in self._iter_internal_links(p, target_domain):
                    if _looks_like_privacy_policy(link, link_text):
                        if len(pages) >= self.max_pages:
                            break
                        page = await self.context.new_page()
                        try:
                            info = await self._visit(page, link, p.depth + 1, link_text)
                        finally:
                            await page.close()
                        if info:
                            info.is_privacy_policy = True
                            pages.append(info)
                            privacy_url = info.url
                        break
                if privacy_url:
                    break

        # Imprint detection — URL only, we don't need to fetch its content
        # (yet). First check visited pages, then scan outgoing links.
        imprint_url: str | None = None
        for p in pages:
            if _looks_like_imprint(p.url):
                imprint_url = p.url
                break
        if imprint_url is None:
            for p in pages:
                for link, _ in self._iter_internal_links(p, target_domain):
                    if _looks_like_imprint(link):
                        imprint_url = link
                        break
                if imprint_url:
                    break

        return CrawlResult(
            start_url=start_url,
            pages=pages,
            privacy_policy_url=privacy_url,
            imprint_url=imprint_url,
        )

    async def _visit(
        self, page: Page, url: str, depth: int, anchor_text: str | None
    ) -> PageInfo | None:
        try:
            response = await page.goto(
                url, wait_until="networkidle", timeout=self.page_timeout_ms
            )
        except PWTimeout:
            try:
                response = await page.goto(
                    url, wait_until="domcontentloaded", timeout=self.page_timeout_ms
                )
            except Exception:
                return None
        except Exception:
            return None

        # Give late-firing trackers a moment to register.
        try:
            await asyncio.sleep(0.5)
        except Exception:
            pass

        status = response.status if response else None
        title = await page.title()
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        scripts: list[str] = []
        missing_sri: list[str] = []
        page_host = urlparse(page.url).hostname or ""
        for tag in soup.find_all("script"):
            src = tag.get("src")
            if not src:
                continue
            absolute = urljoin(page.url, src)
            scripts.append(absolute)
            # Phase 5 SRI check — cross-origin scripts should carry an
            # `integrity="sha384-…"` hash. Without it a compromised CDN
            # can serve altered JS and the browser runs it (see
            # polyfill.io supply-chain incident, 2024).
            script_host = urlparse(absolute).hostname or ""
            if script_host and script_host != page_host and not tag.get("integrity"):
                missing_sri.append(absolute)

        # Also grab <iframe src="..."> — Phase 2 widget detection keys off
        # these to distinguish e.g. youtube.com/embed (tracks) from
        # youtube-nocookie.com/embed (doesn't). Iframes can also be declared
        # on data-src for lazy loading; grab that too.
        iframes = [
            urljoin(page.url, src)
            for tag in soup.find_all("iframe")
            for src in [tag.get("src") or tag.get("data-src")]
            if src
        ]
        links = [urljoin(page.url, a.get("href")) for a in soup.find_all("a", href=True)]
        forms = self._extract_forms(soup, page.url)

        try:
            storage = await snapshot_page_storage(page)
        except Exception:
            storage = []

        return PageInfo(
            url=page.url,
            title=title or None,
            status=status,
            depth=depth,
            scripts=scripts,
            iframes=iframes,
            links=links,
            forms=forms,
            storage=storage,
            is_privacy_policy=_looks_like_privacy_policy(page.url, anchor_text),
            cross_origin_scripts_missing_sri=missing_sri,
        )

    @staticmethod
    def _extract_forms(soup: BeautifulSoup, page_url: str) -> list[FormInfo]:
        forms: list[FormInfo] = []
        for f in soup.find_all("form"):
            fields: list[FormField] = []
            has_checkbox = False
            for el in f.find_all(["input", "textarea", "select"]):
                el_type = (el.get("type") or el.name or "").lower()
                if el_type == "checkbox":
                    has_checkbox = True
                fields.append(
                    FormField(
                        name=el.get("name"),
                        type=el_type or None,
                        required=el.has_attr("required"),
                    )
                )

            # Collapse the form's visible text — labels, legal copy, button
            # text — into one blob. Form analysis greps this for privacy
            # cues; the model never sees it directly.
            text_content = f.get_text(separator=" ", strip=True)
            text_content = " ".join(text_content.split())[:1000]

            links = [
                urljoin(page_url, a.get("href"))
                for a in f.find_all("a", href=True)
            ]

            action = f.get("action")
            forms.append(
                FormInfo(
                    action=urljoin(page_url, action) if action else page_url,
                    method=(f.get("method") or "GET").upper(),
                    fields=fields,
                    page_url=page_url,
                    text_content=text_content,
                    links=links,
                    has_checkbox=has_checkbox,
                )
            )
        return forms

    @staticmethod
    def _iter_internal_links(page: PageInfo, target_domain: str):
        for link in page.links:
            try:
                parsed = urlparse(link)
            except Exception:
                continue
            if parsed.scheme not in ("http", "https"):
                continue
            if _registered_domain(link) != target_domain:
                continue
            yield link, None
