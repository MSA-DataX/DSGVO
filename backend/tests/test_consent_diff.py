"""Tests for consent_diff.

Pure function; small surface. Keys we must get right:

- Dedup key for cookies is (name, domain) — a cookie present on both
  sides should NOT show up as "new" post-consent even if the values
  drifted.
- Dedup key for storage is (kind, page_url, key).
- `new_data_flow` compares on `domain` only — a domain that was already
  contacted pre-consent should never appear as "new".
- `extra_request_count` is floored at zero (a post-pass that somehow
  made fewer requests must not produce a negative number).
- `new_marketing_count` / `new_analytics_count` aggregate cookies + storage.
"""

from __future__ import annotations

from app.modules.consent_diff import compute_consent_diff

from .conftest import make_cookie, make_cookie_report, make_flow, make_network, make_request, make_storage


# ---------------------------------------------------------------------------
# No diff baseline
# ---------------------------------------------------------------------------

def test_identical_pre_post_yields_empty_diff():
    pre = make_cookie_report(
        cookies=[make_cookie("_ga", ".example.com", category="analytics")],
        storage=[make_storage("foo", kind="local")],
    )
    post = make_cookie_report(
        cookies=[make_cookie("_ga", ".example.com", category="analytics")],
        storage=[make_storage("foo", kind="local")],
    )
    pre_net = make_network(
        requests=[make_request("https://ga.example.com/collect")],
        data_flow=[make_flow("ga.example.com")],
    )
    post_net = make_network(
        requests=[make_request("https://ga.example.com/collect")],
        data_flow=[make_flow("ga.example.com")],
    )
    diff = compute_consent_diff(pre, post, pre_net, post_net)
    assert diff.new_cookies == []
    assert diff.new_storage == []
    assert diff.new_data_flow == []
    assert diff.extra_request_count == 0
    assert diff.new_marketing_count == 0
    assert diff.new_analytics_count == 0


# ---------------------------------------------------------------------------
# New cookies
# ---------------------------------------------------------------------------

def test_new_cookie_added_post_consent_is_flagged():
    pre = make_cookie_report(cookies=[])
    post = make_cookie_report(cookies=[
        make_cookie("_fbp", ".facebook.com", category="marketing"),
    ])
    diff = compute_consent_diff(pre, post, make_network(), make_network())
    assert len(diff.new_cookies) == 1
    assert diff.new_cookies[0].name == "_fbp"
    assert diff.new_marketing_count == 1


def test_cookie_present_in_both_is_not_new():
    shared = make_cookie("session", "example.com", category="necessary")
    pre = make_cookie_report(cookies=[shared])
    post = make_cookie_report(cookies=[shared])
    diff = compute_consent_diff(pre, post, make_network(), make_network())
    assert diff.new_cookies == []


def test_cookie_key_is_name_plus_domain():
    # Same name, different domain → should be treated as new.
    pre = make_cookie_report(cookies=[
        make_cookie("_ga", ".a.com", category="analytics"),
    ])
    post = make_cookie_report(cookies=[
        make_cookie("_ga", ".a.com", category="analytics"),
        make_cookie("_ga", ".b.com", category="analytics"),
    ])
    diff = compute_consent_diff(pre, post, make_network(), make_network())
    assert len(diff.new_cookies) == 1
    assert diff.new_cookies[0].domain == ".b.com"


# ---------------------------------------------------------------------------
# New storage
# ---------------------------------------------------------------------------

def test_new_storage_entry_detected():
    pre = make_cookie_report(storage=[])
    post = make_cookie_report(storage=[
        make_storage("_hj_session", kind="local", category="analytics"),
    ])
    diff = compute_consent_diff(pre, post, make_network(), make_network())
    assert len(diff.new_storage) == 1
    assert diff.new_analytics_count == 1


def test_storage_key_is_kind_plus_page_plus_key():
    # Same key, different kind (local vs session) → new.
    pre = make_cookie_report(storage=[
        make_storage("x", kind="local"),
    ])
    post = make_cookie_report(storage=[
        make_storage("x", kind="local"),
        make_storage("x", kind="session"),
    ])
    diff = compute_consent_diff(pre, post, make_network(), make_network())
    assert len(diff.new_storage) == 1
    assert diff.new_storage[0].kind == "session"


def test_storage_on_different_page_counts_as_new():
    pre = make_cookie_report(storage=[
        make_storage("k", page_url="https://example.com/"),
    ])
    post = make_cookie_report(storage=[
        make_storage("k", page_url="https://example.com/"),
        make_storage("k", page_url="https://example.com/other"),
    ])
    diff = compute_consent_diff(pre, post, make_network(), make_network())
    assert len(diff.new_storage) == 1
    assert diff.new_storage[0].page_url == "https://example.com/other"


# ---------------------------------------------------------------------------
# New data flow domains
# ---------------------------------------------------------------------------

def test_new_third_party_domain_flagged():
    pre_net = make_network(data_flow=[make_flow("jsdelivr.net")])
    post_net = make_network(data_flow=[
        make_flow("jsdelivr.net"),
        make_flow("google-analytics.com", country="USA", risk="high",
                  categories=["analytics"]),
    ])
    diff = compute_consent_diff(
        make_cookie_report(), make_cookie_report(), pre_net, post_net,
    )
    assert len(diff.new_data_flow) == 1
    assert diff.new_data_flow[0].domain == "google-analytics.com"


def test_shared_domains_not_flagged():
    flow = make_flow("googleapis.com")
    pre_net = make_network(data_flow=[flow])
    post_net = make_network(data_flow=[flow])
    diff = compute_consent_diff(
        make_cookie_report(), make_cookie_report(), pre_net, post_net,
    )
    assert diff.new_data_flow == []


# ---------------------------------------------------------------------------
# Request-count delta
# ---------------------------------------------------------------------------

def test_extra_requests_counts_positive_delta():
    pre = make_network(requests=[
        make_request("https://a.com/1"),
        make_request("https://a.com/2"),
    ])
    post = make_network(requests=[
        make_request("https://a.com/1"),
        make_request("https://a.com/2"),
        make_request("https://b.com/3"),
        make_request("https://b.com/4"),
    ])
    diff = compute_consent_diff(make_cookie_report(), make_cookie_report(), pre, post)
    assert diff.extra_request_count == 2


def test_extra_requests_floors_at_zero_when_post_has_fewer():
    # Shouldn't happen in practice but guard the invariant.
    pre = make_network(requests=[make_request(f"https://x/{i}") for i in range(5)])
    post = make_network(requests=[make_request("https://x/0")])
    diff = compute_consent_diff(make_cookie_report(), make_cookie_report(), pre, post)
    assert diff.extra_request_count == 0


# ---------------------------------------------------------------------------
# Marketing / analytics counters aggregate cookies AND storage
# ---------------------------------------------------------------------------

def test_marketing_count_sums_cookies_and_storage():
    pre = make_cookie_report()
    post = make_cookie_report(
        cookies=[
            make_cookie("_fbp", ".facebook.com", category="marketing"),
            make_cookie("fr", ".facebook.com", category="marketing"),
        ],
        storage=[
            make_storage("_hjSessionUser", category="marketing"),
        ],
    )
    diff = compute_consent_diff(pre, post, make_network(), make_network())
    assert diff.new_marketing_count == 3


def test_analytics_count_sums_cookies_and_storage():
    pre = make_cookie_report()
    post = make_cookie_report(
        cookies=[make_cookie("_ga", ".g.com", category="analytics")],
        storage=[make_storage("_hjSession", category="analytics")],
    )
    diff = compute_consent_diff(pre, post, make_network(), make_network())
    assert diff.new_analytics_count == 2


def test_necessary_cookies_do_not_inflate_marketing_count():
    pre = make_cookie_report()
    post = make_cookie_report(cookies=[
        make_cookie("OptanonConsent", ".example.com", category="necessary"),
    ])
    diff = compute_consent_diff(pre, post, make_network(), make_network())
    assert diff.new_marketing_count == 0
    assert diff.new_analytics_count == 0
