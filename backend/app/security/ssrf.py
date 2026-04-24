"""Server-Side Request Forgery (SSRF) defence.

A GDPR-audit tool is *designed* to fetch user-supplied URLs. That
makes it a textbook SSRF attack surface: a user types
``http://169.254.169.254/latest/meta-data/iam/security-credentials/``
and we happily render its response (AWS metadata → credentials).

This module validates a URL before Playwright / httpx touches it:

  - scheme MUST be http or https (``file://``, ``gopher://`` etc. rejected)
  - host MUST resolve exclusively to public IPs
  - loopback / private (RFC1918) / link-local / multicast / metadata
    hostnames are all rejected, both as IP literals AND as DNS names
    that resolve there

What this does NOT catch (documented limitations):

  - **DNS rebinding**: a host that resolves to a public IP at validation
    time and to 127.0.0.1 at actual-fetch time. Pinning the resolved IP
    in httpx/Playwright is a larger change — tracked for Phase 2b.
  - **Redirect chains**: a public URL that 302s to a private one. The
    browser (Playwright) follows blindly. Mitigation requires a request
    interceptor — also Phase 2b.

Production deployments should layer a network-level defence on top
(e.g. NetworkPolicy in Kubernetes, egress firewall rules) so even if the
app-layer check is bypassed, the instance metadata endpoint is
unreachable. Defence in depth, not instead-of.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Union
from urllib.parse import urlparse


class SsrfError(ValueError):
    """Raised when a submitted URL is rejected by the SSRF validator."""


# Hostnames that explicitly map to cloud-metadata endpoints. The IP
# literals among these are already caught by `_reject_if_unsafe_ip` (they
# fall into link-local / private ranges), but the *DNS* form may resolve
# to a public IP that the provider renamed — so we block by name too.
_BLOCKED_HOSTNAMES = frozenset({
    "metadata.google.internal",          # GCP
    "metadata.internal",                 # OCI
    "metadata",                          # shorthand some SDKs accept
    # Literals, blocked by name so the error message is self-describing:
    "169.254.169.254",
    "fd00:ec2::254",                     # AWS IPv6 metadata
})

_ALLOWED_SCHEMES = frozenset({"http", "https"})


def validate_url_safe(raw: str) -> str:
    """Return ``raw`` stripped if safe, otherwise raise :class:`SsrfError`."""
    if raw is None:
        raise SsrfError("URL is required")
    url = raw.strip()
    if not url:
        raise SsrfError("URL is required")

    try:
        parsed = urlparse(url)
    except Exception as e:
        raise SsrfError(f"invalid URL: {e}") from e

    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise SsrfError(f"scheme '{scheme}' not allowed — use http or https")

    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise SsrfError("URL must have a hostname")

    if host in _BLOCKED_HOSTNAMES:
        raise SsrfError(f"hostname '{host}' is a known cloud-metadata endpoint")

    # IP literal → check directly, no DNS round-trip.
    ip_obj = _maybe_ip_literal(host)
    if ip_obj is not None:
        _reject_if_unsafe_ip(ip_obj, host)
        return url

    # DNS name → resolve all addresses, reject if ANY is unsafe. An
    # attacker could game this by returning [public, private] on the
    # expectation we check only one; iterating every result closes that.
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SsrfError(f"could not resolve hostname '{host}': {e}") from e

    seen: set[str] = set()
    for info in infos:
        ip_str = info[4][0]
        if ip_str in seen:
            continue
        seen.add(ip_str)
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            # Extremely unusual (getaddrinfo returned something un-parseable) —
            # fail closed.
            raise SsrfError(f"hostname '{host}' resolved to an invalid address '{ip_str}'")
        _reject_if_unsafe_ip(ip_obj, host)

    return url


def _maybe_ip_literal(host: str) -> Union[ipaddress.IPv4Address, ipaddress.IPv6Address, None]:
    # urlparse strips IPv6 square brackets already, but be defensive.
    candidate = host.strip("[]")
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def _reject_if_unsafe_ip(
    ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address],
    host: str,
) -> None:
    """Raise :class:`SsrfError` for any IP in a non-public range.

    `is_private` in the stdlib already covers RFC1918, link-local,
    loopback, and ULA, but we also check each flag explicitly so the
    error message says *why*.
    """
    if ip.is_loopback:
        raise SsrfError(f"hostname '{host}' resolves to loopback {ip}")
    if ip.is_link_local:
        raise SsrfError(f"hostname '{host}' resolves to link-local {ip} (covers cloud metadata)")
    if ip.is_private:
        raise SsrfError(f"hostname '{host}' resolves to private network address {ip}")
    if ip.is_multicast:
        raise SsrfError(f"hostname '{host}' resolves to multicast {ip}")
    if ip.is_reserved:
        raise SsrfError(f"hostname '{host}' resolves to reserved range {ip}")
    if ip.is_unspecified:
        raise SsrfError(f"hostname '{host}' resolves to 0.0.0.0 / ::")
