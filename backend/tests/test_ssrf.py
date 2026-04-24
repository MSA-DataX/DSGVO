"""Tests for the SSRF validator.

Mixes static IP-literal cases (no DNS involved) with a few DNS cases
that use ``monkeypatch`` to control what ``socket.getaddrinfo`` returns.
Tests NEVER hit real DNS — otherwise they'd be flaky on offline CI and
slow on every run.
"""

from __future__ import annotations

import socket

import pytest

from app.security.ssrf import SsrfError, validate_url_safe


def _fake_getaddrinfo(mapping: dict[str, list[str]]):
    """Build a fake getaddrinfo that looks up in ``mapping`` by hostname.

    Anything not in the mapping raises socket.gaierror — same as an
    NXDOMAIN, exercises the error path without a real resolver.
    """

    def impl(host, *_a, **_kw):
        ips = mapping.get(host)
        if ips is None:
            raise socket.gaierror(-2, "NXDOMAIN (mocked)")
        out = []
        for ip in ips:
            # Minimal 5-tuple: (family, type, proto, canonname, sockaddr)
            family = socket.AF_INET6 if ":" in ip else socket.AF_INET
            out.append((family, socket.SOCK_STREAM, 0, "", (ip, 0)))
        return out

    return impl


# ---------------------------------------------------------------------------
# Scheme checks — no DNS involved
# ---------------------------------------------------------------------------

class TestScheme:
    def test_https_ok(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo",
                            _fake_getaddrinfo({"example.com": ["93.184.216.34"]}))
        assert validate_url_safe("https://example.com/") == "https://example.com/"

    def test_http_ok(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo",
                            _fake_getaddrinfo({"example.com": ["93.184.216.34"]}))
        assert validate_url_safe("http://example.com/") == "http://example.com/"

    def test_file_scheme_rejected(self):
        with pytest.raises(SsrfError, match="scheme 'file'"):
            validate_url_safe("file:///etc/passwd")

    def test_gopher_scheme_rejected(self):
        with pytest.raises(SsrfError, match="scheme 'gopher'"):
            validate_url_safe("gopher://example.com/")

    def test_javascript_scheme_rejected(self):
        with pytest.raises(SsrfError, match="scheme 'javascript'"):
            validate_url_safe("javascript:alert(1)")

    def test_empty_url_rejected(self):
        with pytest.raises(SsrfError, match="URL is required"):
            validate_url_safe("")

    def test_whitespace_only_rejected(self):
        with pytest.raises(SsrfError, match="URL is required"):
            validate_url_safe("   ")

    def test_missing_hostname_rejected(self):
        with pytest.raises(SsrfError, match="hostname"):
            validate_url_safe("http:///")


# ---------------------------------------------------------------------------
# IP literals — hit the rejection paths without DNS
# ---------------------------------------------------------------------------

class TestIpLiterals:
    def test_loopback_v4_rejected(self):
        with pytest.raises(SsrfError, match="loopback"):
            validate_url_safe("http://127.0.0.1/")

    def test_loopback_v6_rejected(self):
        with pytest.raises(SsrfError, match="loopback"):
            validate_url_safe("http://[::1]/")

    def test_private_10_rejected(self):
        with pytest.raises(SsrfError, match="private|link-local"):
            validate_url_safe("http://10.0.0.5/")

    def test_private_192_168_rejected(self):
        with pytest.raises(SsrfError, match="private|link-local"):
            validate_url_safe("http://192.168.1.1/")

    def test_private_172_16_rejected(self):
        with pytest.raises(SsrfError, match="private|link-local"):
            validate_url_safe("http://172.16.0.1/")

    def test_aws_metadata_ip_literal_rejected(self):
        # 169.254.169.254 is link-local — AWS / Azure / GCP metadata endpoint.
        # The blocklist catches it by name as well, but IP literal must
        # ALSO fail via the range check.
        with pytest.raises(SsrfError, match="metadata|link-local"):
            validate_url_safe("http://169.254.169.254/latest/meta-data/")

    def test_aws_metadata_ipv6_rejected(self):
        with pytest.raises(SsrfError, match="metadata|private"):
            validate_url_safe("http://[fd00:ec2::254]/")

    def test_unspecified_address_rejected(self):
        with pytest.raises(SsrfError, match="0.0.0.0|loopback|private"):
            validate_url_safe("http://0.0.0.0/")

    def test_multicast_rejected(self):
        with pytest.raises(SsrfError, match="multicast"):
            validate_url_safe("http://224.0.0.1/")

    def test_public_ip_literal_ok(self):
        # 8.8.8.8 — public, should pass without DNS resolution.
        assert validate_url_safe("http://8.8.8.8/") == "http://8.8.8.8/"


# ---------------------------------------------------------------------------
# Hostname blocklist — independent of DNS resolution
# ---------------------------------------------------------------------------

class TestHostnameBlocklist:
    def test_gcp_metadata_hostname_rejected(self):
        with pytest.raises(SsrfError, match="metadata"):
            validate_url_safe("http://metadata.google.internal/computeMetadata/v1/")

    def test_oci_metadata_hostname_rejected(self):
        with pytest.raises(SsrfError, match="metadata"):
            validate_url_safe("http://metadata.internal/")


# ---------------------------------------------------------------------------
# DNS resolution path
# ---------------------------------------------------------------------------

class TestDnsResolution:
    def test_hostname_resolving_to_private_is_rejected(self, monkeypatch):
        # Classic DNS-rebinding setup: an attacker owns rebind.example.com
        # and points it at 10.0.0.5.
        monkeypatch.setattr(socket, "getaddrinfo",
                            _fake_getaddrinfo({"rebind.example.com": ["10.0.0.5"]}))
        with pytest.raises(SsrfError, match="private"):
            validate_url_safe("http://rebind.example.com/")

    def test_hostname_with_mixed_public_and_private_is_rejected(self, monkeypatch):
        # Attacker returns [public, private] hoping we only look at the
        # first entry. We iterate all and fail as soon as one is unsafe.
        monkeypatch.setattr(socket, "getaddrinfo",
                            _fake_getaddrinfo({"sneaky.example.com": ["93.184.216.34", "127.0.0.1"]}))
        with pytest.raises(SsrfError, match="loopback|private"):
            validate_url_safe("http://sneaky.example.com/")

    def test_hostname_resolving_to_public_is_allowed(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo",
                            _fake_getaddrinfo({"example.com": ["93.184.216.34"]}))
        assert validate_url_safe("https://example.com/pricing") == "https://example.com/pricing"

    def test_nxdomain_rejected_cleanly(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo({}))
        with pytest.raises(SsrfError, match="could not resolve"):
            validate_url_safe("https://does-not-exist.example.invalid/")

    def test_ipv6_public_allowed(self, monkeypatch):
        # 2606:4700:4700::1111 is Cloudflare public DNS — definitely public.
        monkeypatch.setattr(socket, "getaddrinfo",
                            _fake_getaddrinfo({"v6.example.com": ["2606:4700:4700::1111"]}))
        assert validate_url_safe("https://v6.example.com/") == "https://v6.example.com/"

    def test_ipv6_ula_rejected(self, monkeypatch):
        # fd00::/8 is the unique-local prefix — private under RFC 4193.
        monkeypatch.setattr(socket, "getaddrinfo",
                            _fake_getaddrinfo({"ula.example.com": ["fd12:3456:789a::1"]}))
        with pytest.raises(SsrfError, match="private|link-local"):
            validate_url_safe("http://ula.example.com/")
