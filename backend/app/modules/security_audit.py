"""Passive security audit.

Observes only what a normal browser visit reveals:

- HTTP redirect chain (does ``http://`` redirect to ``https://``?)
- Response headers of the final page (HSTS, CSP, X-Frame-Options, Referrer-
  Policy, Permissions-Policy, COOP, plus information-leaking headers like
  ``Server`` and ``X-Powered-By``)
- TLS handshake metadata (protocol version, certificate expiry, issuer)
- Mixed content — HTTP resources pulled from an HTTPS page, derived from
  the network capture we already have

NO active probing. No directory bruteforce, no vulnerability payloads, no
port scans. Every observation here is legal to perform against any public
site under Germany's § 202c StGB because no protected information is
accessed — the target would serve the same bytes to any visitor.
"""

from __future__ import annotations

import asyncio
import logging
import re
import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from app.models import (
    InfoLeakHeader,
    NetworkResult,
    SecurityAudit,
    SecurityHeaderFinding,
    TlsInfo,
)


log = logging.getLogger("security_audit")


# ---------------------------------------------------------------------------
# Security-header rules.
# Each rule describes one header: how to judge when it's "present" enough,
# what severity to assign when it's missing, and what explanatory note to
# include. Evaluators run against a case-insensitive headers mapping.
# ---------------------------------------------------------------------------

def _eval_hsts(value: str | None) -> tuple[bool, str, str]:
    if not value:
        return False, "high", "Missing — no HSTS means visitors can be MitM-attacked on first connect."
    v = value.lower()
    # max-age=0 → disables HSTS, treat as missing
    m = re.search(r"max-age\s*=\s*(\d+)", v)
    max_age = int(m.group(1)) if m else 0
    if max_age == 0:
        return False, "high", "HSTS present but max-age=0 disables it — equivalent to missing."
    if max_age < 60 * 60 * 24 * 180:  # < 180 days
        return True, "medium", f"max-age is under 180 days ({max_age} s) — too short for meaningful protection."
    return True, "low", "Present with adequate max-age."


def _eval_csp(value: str | None) -> tuple[bool, str, str]:
    if not value:
        return False, "high", "Missing — the strongest browser-side XSS and injection mitigation."
    v = value.lower()
    if "default-src 'none'" in v or "default-src 'self'" in v:
        return True, "low", "Present with a restrictive default-src."
    if "'unsafe-inline'" in v and "script-src" in v:
        return True, "medium", "Present but uses 'unsafe-inline' in script-src — CSP's main benefit is lost."
    if "'unsafe-eval'" in v and "script-src" in v:
        return True, "medium", "Present but allows 'unsafe-eval' in script-src."
    return True, "low", "Present."


def _eval_xcto(value: str | None) -> tuple[bool, str, str]:
    if value and value.strip().lower() == "nosniff":
        return True, "low", "Present (nosniff)."
    return False, "medium", "Missing or not 'nosniff' — browsers may MIME-sniff responses into unexpected types."


def _eval_xfo_or_csp_fa(xfo: str | None, csp: str | None) -> tuple[bool, str, str]:
    """X-Frame-Options OR a CSP frame-ancestors directive is sufficient."""
    if xfo and xfo.strip().lower() in ("deny", "sameorigin"):
        return True, "low", "X-Frame-Options is set — clickjacking mitigated."
    if csp and "frame-ancestors" in csp.lower():
        return True, "low", "CSP frame-ancestors is set — clickjacking mitigated."
    return False, "medium", "Missing — page can be iframed by any origin (clickjacking risk)."


def _eval_referrer_policy(value: str | None) -> tuple[bool, str, str]:
    if not value:
        return False, "medium", "Missing — full URLs (incl. PII in query strings) may leak to third parties via Referer."
    v = value.strip().lower()
    strict_values = {
        "no-referrer", "same-origin", "strict-origin",
        "strict-origin-when-cross-origin",
    }
    # Comma-separated list allowed; treat as good if any item is strict
    parts = [p.strip() for p in v.split(",")]
    if any(p in strict_values for p in parts):
        return True, "low", "Present with a privacy-preserving directive."
    return True, "medium", f"Present but liberal ({v}) — may still leak referrers cross-origin."


def _eval_permissions_policy(value: str | None) -> tuple[bool, str, str]:
    if not value:
        return False, "low", "Missing — page does not restrict access to powerful browser APIs (geolocation, camera, etc.)."
    return True, "low", "Present."


def _eval_coop(value: str | None) -> tuple[bool, str, str]:
    if not value:
        return False, "low", "Missing — cross-origin window.opener attacks not mitigated (relevant when you link out to untrusted sites)."
    return True, "low", "Present."


# ---------------------------------------------------------------------------
# Information-leak header patterns.
# Not a DSGVO issue per se, but an audit finding: exposing exact versions
# makes targeted exploit work easier for anyone scanning.
# ---------------------------------------------------------------------------

_LEAKY_HEADERS = {
    "server": "Server software (and often version)",
    "x-powered-by": "Runtime / framework / version",
    "x-aspnet-version": "ASP.NET version",
    "x-aspnetmvc-version": "ASP.NET MVC version",
    "x-generator": "CMS / generator",
    "x-drupal-cache": "Drupal (reveals CMS)",
    "x-runtime": "Rails processing time (reveals Rails)",
    "x-rack-cache": "Rack/Ruby",
    "liferay-portal": "Liferay portal (reveals CMS + version)",
}

# Pattern: accept bare name header/version — flag anything that contains a
# version number like "1.2.3" or "/1.2"
_VERSION_RE = re.compile(r"(\d+\.\d+(\.\d+)?)")


def _headers_lower(resp: httpx.Response) -> dict[str, str]:
    # httpx.Headers is case-insensitive but still give us a lowercase dict
    return {k.lower(): v for k, v in resp.headers.items()}


def _parse_hsts(value: str | None) -> tuple[int | None, bool, bool]:
    """Return (max_age_days, include_subdomains, preload)."""
    if not value:
        return None, False, False
    v = value.lower()
    m = re.search(r"max-age\s*=\s*(\d+)", v)
    max_age = int(m.group(1)) if m else 0
    max_age_days = max_age // 86400 if max_age else 0
    include_subdomains = "includesubdomains" in v
    preload = "preload" in v
    return max_age_days, include_subdomains, preload


def _tls_handshake(host: str, port: int = 443) -> TlsInfo | None:
    """Synchronous TLS handshake — call via asyncio.to_thread."""
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=5.0) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert() or {}
                version = ssock.version()
        not_after = cert.get("notAfter")
        if not_after:
            try:
                expires = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(
                    tzinfo=timezone.utc,
                )
                days_left = (expires - datetime.now(timezone.utc)).days
            except Exception:
                days_left = None
        else:
            days_left = None
        issuer_parts = cert.get("issuer", ())
        issuer = None
        for tup in issuer_parts:
            for k, v in tup:
                if k == "organizationName":
                    issuer = v
                    break
            if issuer:
                break
        return TlsInfo(
            https_enforced=False,  # set later by caller
            tls_version=version,
            cert_expires_days=days_left,
            cert_issuer=issuer,
        )
    except Exception as e:
        log.info("TLS handshake for %s failed: %s", host, e)
        return None


async def _fetch_homepage(url: str, user_agent: str) -> httpx.Response | None:
    """Fetch the site with redirect following. Used to observe the final
    URL + the security headers the production endpoint actually returns."""
    headers = {"user-agent": user_agent, "accept": "text/html,*/*;q=0.1"}
    async with httpx.AsyncClient(
        timeout=10.0, follow_redirects=True, headers=headers,
    ) as client:
        try:
            return await client.get(url)
        except Exception as e:
            log.warning("homepage fetch failed: %s", e)
            return None


async def audit_security(
    target: str,
    network: NetworkResult,
    user_agent: str,
) -> SecurityAudit:
    # --- 1. Fetch homepage with redirect tracking ----------------------
    resp = await _fetch_homepage(target, user_agent)
    if resp is None:
        return SecurityAudit(
            final_url=target,
            headers=[],
            error="homepage fetch failed",
        )

    final_url = str(resp.url)
    headers = _headers_lower(resp)

    # HTTPS enforcement: did we start with http:// and end on https:// via
    # redirect? Or if user already passed https://, check that the final
    # URL is still https.
    start_scheme = urlparse(target).scheme.lower()
    final_scheme = urlparse(final_url).scheme.lower()
    https_enforced = final_scheme == "https"
    if start_scheme == "http" and final_scheme != "https":
        https_enforced = False  # explicit fail

    # --- 2. TLS handshake info (only when HTTPS) -----------------------
    tls_info: TlsInfo | None = None
    if final_scheme == "https":
        host = urlparse(final_url).hostname
        if host:
            tls_info = await asyncio.to_thread(_tls_handshake, host)
    if tls_info is None and final_scheme == "https":
        # Preserve the https_enforced signal even when the TLS probe itself
        # failed (e.g. host blocks non-browser clients).
        tls_info = TlsInfo(https_enforced=https_enforced)
    if tls_info is not None:
        tls_info.https_enforced = https_enforced
        # parse HSTS into structured fields
        hsts_value = headers.get("strict-transport-security")
        max_age_days, include_sub, preload = _parse_hsts(hsts_value)
        tls_info.hsts_max_age_days = max_age_days
        tls_info.hsts_include_subdomains = include_sub
        tls_info.hsts_preload_eligible = (
            preload and include_sub and (max_age_days or 0) >= 365
        )

    # --- 3. Evaluate security headers ----------------------------------
    findings: list[SecurityHeaderFinding] = []

    hsts_val = headers.get("strict-transport-security")
    present, sev, note = _eval_hsts(hsts_val)
    findings.append(SecurityHeaderFinding(
        name="Strict-Transport-Security", present=present, value=hsts_val,
        severity=sev, note=note,  # type: ignore[arg-type]
    ))

    csp_val = headers.get("content-security-policy")
    present, sev, note = _eval_csp(csp_val)
    findings.append(SecurityHeaderFinding(
        name="Content-Security-Policy", present=present, value=csp_val,
        severity=sev, note=note,  # type: ignore[arg-type]
    ))

    xcto_val = headers.get("x-content-type-options")
    present, sev, note = _eval_xcto(xcto_val)
    findings.append(SecurityHeaderFinding(
        name="X-Content-Type-Options", present=present, value=xcto_val,
        severity=sev, note=note,  # type: ignore[arg-type]
    ))

    xfo_val = headers.get("x-frame-options")
    present, sev, note = _eval_xfo_or_csp_fa(xfo_val, csp_val)
    findings.append(SecurityHeaderFinding(
        name="X-Frame-Options / CSP frame-ancestors",
        present=present, value=xfo_val, severity=sev, note=note,  # type: ignore[arg-type]
    ))

    rp_val = headers.get("referrer-policy")
    present, sev, note = _eval_referrer_policy(rp_val)
    findings.append(SecurityHeaderFinding(
        name="Referrer-Policy", present=present, value=rp_val,
        severity=sev, note=note,  # type: ignore[arg-type]
    ))

    pp_val = headers.get("permissions-policy")
    present, sev, note = _eval_permissions_policy(pp_val)
    findings.append(SecurityHeaderFinding(
        name="Permissions-Policy", present=present, value=pp_val,
        severity=sev, note=note,  # type: ignore[arg-type]
    ))

    coop_val = headers.get("cross-origin-opener-policy")
    present, sev, note = _eval_coop(coop_val)
    findings.append(SecurityHeaderFinding(
        name="Cross-Origin-Opener-Policy", present=present, value=coop_val,
        severity=sev, note=note,  # type: ignore[arg-type]
    ))

    # --- 4. Information-leak headers -----------------------------------
    info_leaks: list[InfoLeakHeader] = []
    for name, leaks in _LEAKY_HEADERS.items():
        val = headers.get(name)
        if not val:
            continue
        # Only flag when a version number is visible or the header exists
        # at all (X-Powered-By's presence alone is noteworthy).
        reveals_version = bool(_VERSION_RE.search(val))
        # The raw Server header "nginx" without version is borderline — we
        # don't flag it. For other headers presence alone leaks something.
        if name == "server" and not reveals_version:
            continue
        info_leaks.append(InfoLeakHeader(name=name, value=val[:120], leaks=leaks))

    # --- 5. Mixed content (HTTPS page → HTTP resource) ------------------
    mixed_samples: list[str] = []
    mixed_count = 0
    if final_scheme == "https":
        for r in network.requests:
            scheme = urlparse(r.url).scheme.lower()
            if scheme == "http":
                mixed_count += 1
                if len(mixed_samples) < 5:
                    mixed_samples.append(r.url)

    # --- 6. Summary ----------------------------------------------------
    summary = {
        "total_headers_checked": len(findings),
        "headers_missing_or_weak_high":
            sum(1 for f in findings if not f.present and f.severity == "high"),
        "headers_missing_or_weak_medium":
            sum(1 for f in findings if not f.present and f.severity == "medium"),
        "headers_missing_or_weak_low":
            sum(1 for f in findings if not f.present and f.severity == "low"),
        "info_leak_headers": len(info_leaks),
        "mixed_content_requests": mixed_count,
    }

    return SecurityAudit(
        final_url=final_url,
        headers=findings,
        tls=tls_info,
        mixed_content_count=mixed_count,
        mixed_content_samples=mixed_samples,
        info_leak_headers=info_leaks,
        summary=summary,
    )
