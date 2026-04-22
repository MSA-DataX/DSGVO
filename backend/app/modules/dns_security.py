"""Passive DNS-security observations.

Queries public DNS records that describe how the domain defends against
phishing and cert mis-issuance. Every query is identical to what a mail
server or CA would do — no active probing, no credentials required, no
rate-sensitive endpoints hit.

What we check:

- **SPF** (TXT on apex) — SMTP senders authorised for this domain.
  Missing SPF = anyone can claim to be `@yourdomain` in phishing.
- **DMARC** (TXT on ``_dmarc.<domain>``) — policy for mail that fails
  SPF/DKIM. Parsed for the ``p=`` directive (none / quarantine / reject).
  ``p=none`` is observational only and is the single biggest gap
  between "has DMARC" and "DMARC actually prevents phishing".
- **DNSSEC** — the AD (Authenticated Data) flag on a resolver response
  or the presence of a DNSKEY record. Signed records cannot be spoofed.
- **CAA** (apex CAA record) — restricts which CAs may issue certs for
  this domain. Missing CAA means any trusted CA can issue; an attacker
  with a BGP hijack + LE accepts validation would win without CAA.

GDPR relevance: Art. 32 DSGVO ("appropriate technical measures"). A
domain that doesn't publish SPF/DMARC lets attackers phish its users
*in the operator's name* — a controllable risk the operator is not
controlling.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

import dns.asyncresolver
import dns.flags
import dns.rdatatype
import tldextract

from app.models import DnsSecurityInfo, DmarcPolicy


log = logging.getLogger("dns_security")


def _registered_domain(url_or_host: str) -> str | None:
    """Return the eTLD+1 for either a full URL or a bare hostname."""
    host = url_or_host
    if "://" in url_or_host:
        parsed = urlparse(url_or_host)
        host = parsed.hostname or ""
    if not host:
        return None
    ext = tldextract.extract(host)
    if not ext.domain:
        return None
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain


async def _txt_records(resolver: dns.asyncresolver.Resolver, name: str) -> list[str]:
    """Return TXT record strings for ``name``, or [] on NXDOMAIN / timeout."""
    try:
        answer = await resolver.resolve(name, "TXT", lifetime=4.0)
    except Exception:
        return []
    out: list[str] = []
    for rr in answer:
        # TXT strings are byte chunks; DNSpython exposes them as a list we
        # join and decode.
        parts = getattr(rr, "strings", None)
        if parts:
            out.append(b"".join(parts).decode("utf-8", errors="replace"))
        else:
            out.append(str(rr).strip('"'))
    return out


async def _has_record(
    resolver: dns.asyncresolver.Resolver, name: str, rdtype: str,
) -> bool:
    try:
        await resolver.resolve(name, rdtype, lifetime=4.0)
        return True
    except Exception:
        return False


async def _dnssec_enabled(
    resolver: dns.asyncresolver.Resolver, name: str,
) -> bool:
    """True if the answer has the AD (authenticated-data) flag OR a DNSKEY
    record exists. The AD flag means the *resolver* validated the chain;
    absence doesn't prove DNSSEC is off (resolver might not validate) so
    we also check for DNSKEY existence at the apex as a fallback signal.
    """
    try:
        answer = await resolver.resolve(name, "A", lifetime=4.0)
        if hasattr(answer, "response") and (answer.response.flags & dns.flags.AD):
            return True
    except Exception:
        pass
    # Fallback: does the zone publish a DNSKEY? Not proof the resolver
    # chain validated, but strong signal the operator configured DNSSEC.
    return await _has_record(resolver, name, "DNSKEY")


def _parse_dmarc(record: str) -> DmarcPolicy:
    """Extract the ``p=`` directive from a DMARC TXT record."""
    # Record looks like: "v=DMARC1; p=reject; rua=mailto:..."
    tokens = [t.strip() for t in record.split(";") if t.strip()]
    for tok in tokens:
        if tok.lower().startswith("p="):
            val = tok.split("=", 1)[1].strip().lower()
            if val in ("none", "quarantine", "reject"):
                return val  # type: ignore[return-value]
            return "unknown"
    return "unknown"


def _find_spf(records: list[str]) -> str | None:
    for r in records:
        if r.lower().startswith("v=spf1"):
            return r
    return None


def _find_dmarc(records: list[str]) -> str | None:
    for r in records:
        if r.lower().startswith("v=dmarc1"):
            return r
    return None


async def audit_dns_security(target: str) -> DnsSecurityInfo:
    domain = _registered_domain(target)
    if not domain:
        return DnsSecurityInfo(
            domain=target, spf_present=False, dmarc_present=False,
            dmarc_policy="missing", dnssec_enabled=False, caa_present=False,
            error="could not derive registered domain from target",
        )

    # Use a fresh resolver with 1.1.1.1 as upstream. We deliberately do NOT
    # read /etc/resolv.conf — a company-internal resolver might return
    # stub records for the scanned domain and mislead the audit. Cloudflare
    # 1.1.1.1 is DNSSEC-validating; we want its AD flag.
    resolver = dns.asyncresolver.Resolver(configure=False)
    resolver.nameservers = ["1.1.1.1", "8.8.8.8"]

    try:
        apex_txt, dmarc_txt, dnssec_ok, caa_ok = await asyncio.gather(
            _txt_records(resolver, domain),
            _txt_records(resolver, f"_dmarc.{domain}"),
            _dnssec_enabled(resolver, domain),
            _has_record(resolver, domain, "CAA"),
        )
    except Exception as e:
        log.warning("DNS audit for %s failed: %s", domain, e)
        return DnsSecurityInfo(
            domain=domain, spf_present=False, dmarc_present=False,
            dmarc_policy="missing", dnssec_enabled=False, caa_present=False,
            error=f"DNS resolver error: {e}",
        )

    spf_record = _find_spf(apex_txt)
    dmarc_record = _find_dmarc(dmarc_txt)
    dmarc_policy: DmarcPolicy = (
        _parse_dmarc(dmarc_record) if dmarc_record else "missing"
    )

    return DnsSecurityInfo(
        domain=domain,
        spf_present=spf_record is not None,
        spf_record=spf_record,
        dmarc_present=dmarc_record is not None,
        dmarc_policy=dmarc_policy,
        dmarc_record=dmarc_record,
        dnssec_enabled=dnssec_ok,
        caa_present=caa_ok,
    )
