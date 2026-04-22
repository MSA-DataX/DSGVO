"""Compute the diff between pre-consent and post-consent scan passes.

The core question: *what does this site additionally load once the user
clicks "Accept all"?* The diff answers it for cookies, web storage, and
third-party domains. Removed entries are uninteresting (sites rarely
delete things on consent).
"""

from __future__ import annotations

from app.models import (
    ConsentDiff,
    CookieEntry,
    CookieReport,
    DataFlowEntry,
    NetworkResult,
    StorageEntry,
)


def _cookie_key(c: CookieEntry) -> tuple[str, str]:
    return (c.name, c.domain)


def _storage_key(s: StorageEntry) -> tuple[str, str, str]:
    return (s.kind, s.page_url, s.key)


def compute_consent_diff(
    pre_cookies: CookieReport,
    post_cookies: CookieReport,
    pre_network: NetworkResult,
    post_network: NetworkResult,
) -> ConsentDiff:
    pre_cookie_keys = {_cookie_key(c) for c in pre_cookies.cookies}
    new_cookies = [c for c in post_cookies.cookies if _cookie_key(c) not in pre_cookie_keys]

    pre_storage_keys = {_storage_key(s) for s in pre_cookies.storage}
    new_storage = [s for s in post_cookies.storage if _storage_key(s) not in pre_storage_keys]

    pre_domains = {d.domain for d in pre_network.data_flow}
    new_data_flow: list[DataFlowEntry] = [
        d for d in post_network.data_flow if d.domain not in pre_domains
    ]

    extra_requests = max(0, len(post_network.requests) - len(pre_network.requests))

    return ConsentDiff(
        new_cookies=new_cookies,
        new_storage=new_storage,
        new_data_flow=new_data_flow,
        extra_request_count=extra_requests,
        new_marketing_count=sum(
            1 for c in new_cookies if c.category == "marketing"
        ) + sum(
            1 for s in new_storage if s.category == "marketing"
        ),
        new_analytics_count=sum(
            1 for c in new_cookies if c.category == "analytics"
        ) + sum(
            1 for s in new_storage if s.category == "analytics"
        ),
    )
