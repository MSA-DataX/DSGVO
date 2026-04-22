"""Scan orchestrator.

One Playwright lifecycle per scan, optionally with two passes:

  1. **Pre-consent pass** (always): launch browser, open a fresh context,
     attach a NetworkAnalyzer, run the crawler. This is the legally
     relevant state — what the site does *before* the user touches the
     banner. Cookies, network, storage, forms all come from this pass.

  2. **Post-consent pass** (opt-in): open a *second* fresh context in the
     same browser, navigate to the home page, click the cookie banner's
     "Accept all", then crawl normally. The diff against pass 1 reveals
     which trackers are gated behind consent (good UX) vs. which load
     unconditionally (problem).

The pre-consent pass feeds AI / forms / scoring. The post-consent pass is
informational only — gating trackers behind consent is the *correct*
behavior, so we don't score against finding more trackers post-consent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import tldextract
from playwright.async_api import BrowserContext, async_playwright

from app.config import settings
from app.models import (
    ConsentSimulation,
    CookieReport,
    CrawlResult,
    NetworkResult,
    PrivacyAnalysis,
    ScanRequest,
    ScanResponse,
)
from app.modules.ai_analyzer import get_provider
from app.modules.consent_clicker import try_click_consent
from app.modules.consent_diff import compute_consent_diff
from app.modules.cookie_scanner import build_report
from app.modules.crawler import Crawler
from app.modules.form_analyzer import analyze_forms
from app.modules.network_analyzer import NetworkAnalyzer
from app.modules.policy_extractor import (
    fetch_policy_text,
    probe_common_paths,
    truncate_for_model,
)
from app.modules.scoring import compute_risk
from app.progress import NoopReporter, ProgressReporter


log = logging.getLogger("scanner")


def _registered_domain(url: str) -> str:
    ext = tldextract.extract(url)
    if not ext.domain:
        return ""
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain


@dataclass
class _PassResult:
    """Output of one scan pass — everything the diff or downstream needs."""
    crawl: CrawlResult
    cookies: CookieReport
    network: NetworkResult
    policy_text: str | None
    chars_sent: int


async def _run_pass(
    *,
    target: str,
    context: BrowserContext,
    analyzer: NetworkAnalyzer,
    first_party: str,
    max_depth: int,
    max_pages: int,
    p: ProgressReporter,
    label: str,
    accept_consent: bool,
    explicit_policy_url: str | None = None,
) -> tuple[_PassResult, str | None]:
    """Run one full crawl + cookie/storage capture in the given context.

    If ``accept_consent`` is True, navigate to ``target`` first and try to
    click the cookie banner before letting the crawler loose. Returns the
    pass result plus the CMP name (or None) for the caller to record.
    """
    cmp_name: str | None = None
    if accept_consent:
        p.emit("crawling", f"[{label}] Loading home page to find consent banner…")
        warmup = await context.new_page()
        try:
            try:
                await warmup.goto(target, wait_until="networkidle",
                                  timeout=settings.scan_page_timeout_ms)
            except Exception:
                pass  # banner might still be present even if networkidle timed out
            clicked, cmp_name = await try_click_consent(warmup)
            if clicked:
                p.emit("crawling", f"[{label}] Clicked consent banner ({cmp_name})",
                       {"cmp": cmp_name})
            else:
                p.emit("crawling", f"[{label}] No consent banner detected — proceeding")
        finally:
            await warmup.close()

    crawler = Crawler(
        context=context,
        max_depth=max_depth,
        max_pages=max_pages,
        page_timeout_ms=settings.scan_page_timeout_ms,
        progress=p,
    )
    crawl_result = await crawler.crawl(target)
    p.emit("crawling", f"[{label}] Crawled {len(crawl_result.pages)} page(s)",
           {"pages": len(crawl_result.pages), "pass": label})

    page_storage = [s for pg in crawl_result.pages for s in pg.storage]
    cookie_report = await build_report(
        context=context, first_party_domain=first_party, page_storage=page_storage,
    )

    # Privacy policy text only on the pre-consent pass — re-extracting it
    # post-consent would just waste a request.
    policy_text: str | None = None
    chars_sent = 0
    policy_url: str | None = None

    if not accept_consent:
        # Resolution order: explicit override → crawler-discovered → probe
        # common paths via cheap httpx HEAD. First hit wins.
        if explicit_policy_url:
            policy_url = explicit_policy_url
            p.emit("policy_extraction",
                   f"Using user-provided privacy policy URL: {policy_url}",
                   {"source": "manual"})
        elif crawl_result.privacy_policy_url:
            policy_url = crawl_result.privacy_policy_url
            p.emit("policy_extraction",
                   f"Discovered privacy policy during crawl: {policy_url}",
                   {"source": "crawl"})
        else:
            p.emit("policy_extraction",
                   "Privacy policy not linked from crawled pages — probing common paths…")
            probed = await probe_common_paths(
                base_url=target, user_agent=settings.scan_user_agent,
            )
            if probed:
                policy_url = probed
                p.emit("policy_extraction",
                       f"Found privacy policy via common-path probing: {probed}",
                       {"source": "probe"})
                # Update the crawl result so downstream consumers (stored scan,
                # "found at" link in the UI) see it.
                crawl_result.privacy_policy_url = probed

        if policy_url:
            policy_text = await fetch_policy_text(
                context=context, policy_url=policy_url,
                timeout_ms=settings.scan_page_timeout_ms,
            )
            if policy_text:
                _, chars_sent = truncate_for_model(policy_text, settings.ai_max_policy_chars)
                p.emit("policy_extraction", f"Extracted {chars_sent} chars of policy text",
                       {"chars": chars_sent})
            else:
                p.emit("policy_extraction",
                       f"Privacy policy URL known but content could not be fetched: {policy_url}")

    return _PassResult(
        crawl=crawl_result,
        cookies=cookie_report,
        network=analyzer.result(),
        policy_text=policy_text,
        chars_sent=chars_sent,
    ), cmp_name


async def run_scan(
    req: ScanRequest,
    progress: ProgressReporter | None = None,
) -> ScanResponse:
    p = progress or NoopReporter()
    target = str(req.url)
    max_depth = req.max_depth if req.max_depth is not None else settings.scan_max_depth
    max_pages = req.max_pages if req.max_pages is not None else settings.scan_max_pages
    do_consent = req.consent_simulation

    p.emit("started",
           f"Scanning {target}" + (" (with consent simulation)" if do_consent else ""),
           {"max_depth": max_depth, "max_pages": max_pages, "consent_simulation": do_consent})

    first_party = _registered_domain(target)
    pre: _PassResult
    post: _PassResult | None = None
    consent_cmp: str | None = None

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            # --- PRE-consent pass (always) -------------------------------
            pre_ctx = await browser.new_context(
                user_agent=settings.scan_user_agent,
                ignore_https_errors=True,
                java_script_enabled=True,
            )
            pre_analyzer = NetworkAnalyzer(first_party_url=target)
            pre_analyzer.attach(pre_ctx)
            try:
                pre, _ = await _run_pass(
                    target=target, context=pre_ctx, analyzer=pre_analyzer,
                    first_party=first_party, max_depth=max_depth, max_pages=max_pages,
                    p=p, label="pre", accept_consent=False,
                    explicit_policy_url=(
                        str(req.privacy_policy_url) if req.privacy_policy_url else None
                    ),
                )
            finally:
                await pre_ctx.close()

            # --- POST-consent pass (opt-in) ------------------------------
            if do_consent:
                p.emit("crawling", "Starting post-consent pass…")
                post_ctx = await browser.new_context(
                    user_agent=settings.scan_user_agent,
                    ignore_https_errors=True,
                    java_script_enabled=True,
                )
                post_analyzer = NetworkAnalyzer(first_party_url=target)
                post_analyzer.attach(post_ctx)
                try:
                    post, consent_cmp = await _run_pass(
                        target=target, context=post_ctx, analyzer=post_analyzer,
                        first_party=first_party, max_depth=max_depth, max_pages=max_pages,
                        p=p, label="post", accept_consent=True,
                    )
                finally:
                    await post_ctx.close()
        finally:
            await browser.close()

    p.emit("cookie_analysis",
           f"Found {len(pre.cookies.cookies)} cookie(s), {len(pre.cookies.storage)} storage entry/entries",
           {"cookies": len(pre.cookies.cookies), "storage": len(pre.cookies.storage)})

    # --- AI privacy analysis (uses pre-pass) ----------------------------
    ai_provider = get_provider()
    policy_url = pre.crawl.privacy_policy_url
    privacy_analysis = await _run_ai_analysis(
        ai_provider, pre, policy_url, p,
    )

    # --- form analysis (deterministic) ----------------------------------
    p.emit("form_analysis", "Analyzing forms…")
    all_forms = [f for pg in pre.crawl.pages for f in pg.forms]
    form_report = analyze_forms(all_forms, known_privacy_url=policy_url)
    p.emit("form_analysis", f"Analyzed {len(form_report.forms)} form(s)",
           {"forms": len(form_report.forms),
            "issues": form_report.summary.get("forms_with_issues", 0)})

    # --- consent simulation result --------------------------------------
    consent_block: ConsentSimulation | None = None
    if do_consent and post is not None:
        diff = compute_consent_diff(
            pre_cookies=pre.cookies, post_cookies=post.cookies,
            pre_network=pre.network, post_network=post.network,
        )
        clicked = consent_cmp is not None
        if clicked:
            note = (
                f"Consent banner detected ({consent_cmp}) and accepted. "
                f"After consent the site set {len(diff.new_cookies)} additional cookie(s), "
                f"{len(diff.new_storage)} storage entry/entries, and contacted "
                f"{len(diff.new_data_flow)} new third-party domain(s)."
            )
        else:
            note = (
                "No cookie banner was detected. The pre/post diff is unlikely to be "
                "meaningful — the site may have no banner, or our selectors didn't match it."
            )
        consent_block = ConsentSimulation(
            enabled=True,
            accept_clicked=clicked,
            cmp_detected=consent_cmp,
            note=note,
            pre_summary=dict(pre.cookies.summary),
            post_summary=dict(post.cookies.summary),
            diff=diff,
        )

    # --- risk score (uses pre-pass) -------------------------------------
    p.emit("scoring", "Computing risk score…")
    risk = compute_risk(
        cookies=pre.cookies, network=pre.network,
        privacy=privacy_analysis, forms=form_report,
        has_policy=policy_url is not None,
    )
    p.emit("scoring", f"Final score: {risk.score}/100 ({risk.rating})",
           {"score": risk.score, "rating": risk.rating,
            "caps": len(risk.applied_caps),
            "recommendations": len(risk.recommendations)})

    return ScanResponse(
        target=target, risk=risk,
        crawl=pre.crawl, network=pre.network, cookies=pre.cookies,
        privacy_analysis=privacy_analysis, forms=form_report,
        consent=consent_block,
    )


async def _run_ai_analysis(
    ai_provider, pre: _PassResult, policy_url: str | None, p: ProgressReporter,
) -> PrivacyAnalysis:
    if pre.policy_text:
        excerpt, _ = truncate_for_model(pre.policy_text, settings.ai_max_policy_chars)
        p.emit("ai_analysis",
               f"Sending policy text to {ai_provider.name} for GDPR review…",
               {"provider": ai_provider.name})
        try:
            analysis = await ai_provider.analyze_policy(
                policy_text=excerpt, policy_url=policy_url or "",
                data_flow=pre.network.data_flow, chars_sent=pre.chars_sent,
            )
            p.emit("ai_analysis",
                   f"AI analysis complete — compliance score {analysis.compliance_score}/100",
                   {"compliance_score": analysis.compliance_score,
                    "issues": len(analysis.issues)})
            return analysis
        except Exception as e:
            log.exception("AI provider raised; returning placeholder analysis")
            p.emit("ai_analysis", f"AI analysis failed: {e}", {"error": str(e)})
            return PrivacyAnalysis(
                provider=ai_provider.name, model=None, policy_url=policy_url,
                summary="AI analysis failed unexpectedly.", issues=[], coverage=None,
                compliance_score=0, excerpt_chars_sent=pre.chars_sent,
                error=f"unhandled: {e}",
            )

    return PrivacyAnalysis(
        provider=ai_provider.name, model=None, policy_url=policy_url,
        summary=("No privacy policy was found on the site."
                 if not policy_url
                 else "Privacy policy URL was discovered but the page could not be fetched."),
        issues=[], coverage=None, compliance_score=0, excerpt_chars_sent=0,
        error="no_policy_text",
    )
