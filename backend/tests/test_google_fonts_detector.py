"""Tests for the Phase 10 Google-Fonts-loaded-externally detector.

Two halves:
  - The pure ``detect_google_fonts`` predicate against a realistic mix
    of Google-Fonts URL shapes, plus the negative cases (self-hosted
    copies, Adobe Fonts, Bunny Fonts).
  - Scoring integration: when the detector flags the network result,
    the ``google_fonts_external`` cap (55) trips and the LG-München-
    citing recommendation surfaces in BOTH languages.
"""

from __future__ import annotations

from app.modules.google_fonts_detector import detect_google_fonts
from app.modules.scoring import compute_risk

from .conftest import (
    make_channels,
    make_cookie_report,
    make_form_report,
    make_network,
    make_privacy,
    make_request,
    make_widgets,
)


# ---------------------------------------------------------------------------
# Pure detector
# ---------------------------------------------------------------------------

class TestEmptyOrNeutralInput:
    def test_empty_network_returns_zero_state(self):
        result = detect_google_fonts(make_network())
        assert result.detected is False
        assert result.families == []
        assert result.binary_count == 0
        assert result.initiator_pages == []
        assert result.css_url_samples == []

    def test_self_hosted_fonts_do_not_trigger(self):
        # The recommended remediation path: serve woff2 from your own
        # origin. Must NOT trip the detector.
        net = make_network(requests=[
            make_request(
                "https://example.com/static/fonts/roboto.woff2",
                resource_type="font",
                is_third_party=False,
            ),
        ])
        result = detect_google_fonts(net)
        assert result.detected is False

    def test_adobe_fonts_typekit_does_not_trigger(self):
        # Out of scope — Adobe Fonts is a separate compliance question
        # (different controller, different SCC posture). Don't false-
        # positive on it.
        net = make_network(requests=[
            make_request("https://use.typekit.net/abc1234.css"),
        ])
        result = detect_google_fonts(net)
        assert result.detected is False

    def test_bunny_fonts_does_not_trigger(self):
        # Bunny Fonts is the EU-hosted Google-Fonts mirror that German
        # DPAs explicitly bless as a remediation path. Must NOT trigger.
        net = make_network(requests=[
            make_request("https://fonts.bunny.net/css?family=Roboto"),
        ])
        result = detect_google_fonts(net)
        assert result.detected is False


class TestPositiveCases:
    def test_googleapis_css_only_detected_with_family(self):
        net = make_network(requests=[
            make_request(
                "https://fonts.googleapis.com/css?family=Roboto",
                initiator_page="https://example.com/",
            ),
        ])
        result = detect_google_fonts(net)
        assert result.detected is True
        assert result.families == ["Roboto"]
        assert result.binary_count == 0
        assert result.initiator_pages == ["https://example.com/"]
        assert result.css_url_samples == [
            "https://fonts.googleapis.com/css?family=Roboto"
        ]

    def test_gstatic_only_detected_with_binary_count(self):
        # Real sites sometimes hit gstatic.com without the CSS request
        # being recapture-able (cached upstream, or loaded from the
        # browser's HTTP cache). The detector must still flag.
        net = make_network(requests=[
            make_request(
                "https://fonts.gstatic.com/s/roboto/v30/abc.woff2",
                resource_type="font",
            ),
            make_request(
                "https://fonts.gstatic.com/s/roboto/v30/def.woff2",
                resource_type="font",
            ),
        ])
        result = detect_google_fonts(net)
        assert result.detected is True
        assert result.families == []
        assert result.binary_count == 2

    def test_both_hosts_combined(self):
        net = make_network(requests=[
            make_request(
                "https://fonts.googleapis.com/css?family=Roboto",
                initiator_page="https://example.com/",
            ),
            make_request(
                "https://fonts.gstatic.com/s/roboto/v30/abc.woff2",
                resource_type="font",
                initiator_page="https://example.com/",
            ),
        ])
        result = detect_google_fonts(net)
        assert result.detected is True
        assert "Roboto" in result.families
        assert result.binary_count == 1


class TestFamilyParsing:
    def test_weight_suffix_stripped(self):
        # `family=Roboto:300,400` — the weight tail must not bleed
        # into the family name.
        net = make_network(requests=[
            make_request("https://fonts.googleapis.com/css?family=Roboto:300,400"),
        ])
        result = detect_google_fonts(net)
        assert result.families == ["Roboto"]

    def test_pipe_separated_legacy_multi_family(self):
        # `family=Roboto|Open+Sans` — legacy multi-family syntax.
        # The `+` must be decoded to a space.
        net = make_network(requests=[
            make_request("https://fonts.googleapis.com/css?family=Roboto|Open+Sans"),
        ])
        result = detect_google_fonts(net)
        assert "Roboto" in result.families
        assert "Open Sans" in result.families
        assert len(result.families) == 2

    def test_v2_axis_syntax(self):
        # `/css2?family=Roboto:wght@400;700` — v2 axis-tuple syntax.
        net = make_network(requests=[
            make_request("https://fonts.googleapis.com/css2?family=Roboto:wght@400;700"),
        ])
        result = detect_google_fonts(net)
        assert result.families == ["Roboto"]

    def test_families_deduplicated_across_requests(self):
        # Multiple requests for the same family from different pages
        # should produce one entry, not duplicates.
        net = make_network(requests=[
            make_request(
                "https://fonts.googleapis.com/css?family=Roboto",
                initiator_page="https://example.com/",
            ),
            make_request(
                "https://fonts.googleapis.com/css?family=Roboto",
                initiator_page="https://example.com/about",
            ),
        ])
        result = detect_google_fonts(net)
        assert result.families == ["Roboto"]
        # But pages should NOT dedupe across distinct pages.
        assert set(result.initiator_pages) == {
            "https://example.com/",
            "https://example.com/about",
        }

    def test_family_order_preserved_first_seen(self):
        # Stable insertion order — the dashboard renders these in a
        # comma-separated list, so a predictable order matters.
        net = make_network(requests=[
            make_request("https://fonts.googleapis.com/css?family=Inter"),
            make_request("https://fonts.googleapis.com/css?family=Lato"),
            make_request("https://fonts.googleapis.com/css?family=Inter"),
        ])
        result = detect_google_fonts(net)
        assert result.families == ["Inter", "Lato"]


class TestSamplesAndPagesCapping:
    def test_css_url_samples_capped_at_three(self):
        # Real sites can fire 10+ /css requests per page (one per
        # font weight or per page template). The samples list must
        # cap at three to keep the dashboard readable.
        net = make_network(requests=[
            make_request(f"https://fonts.googleapis.com/css?family=F{i}")
            for i in range(8)
        ])
        result = detect_google_fonts(net)
        assert len(result.css_url_samples) == 3
        # All eight families still detected — only the URL samples cap.
        assert len(result.families) == 8


# ---------------------------------------------------------------------------
# Scoring integration
# ---------------------------------------------------------------------------

def _has_cap(result, code: str) -> bool:
    return any(c.code == code for c in result.applied_caps)


def _net_with_google_fonts() -> object:
    """Network result that already has google_fonts populated, the way
    scanner.py would emit after running the detector."""
    net = make_network(requests=[
        make_request(
            "https://fonts.googleapis.com/css?family=Roboto|Open+Sans",
            initiator_page="https://example.com/",
        ),
        make_request(
            "https://fonts.gstatic.com/s/roboto/v30/abc.woff2",
            resource_type="font",
            initiator_page="https://example.com/",
        ),
    ])
    net.google_fonts = detect_google_fonts(net)
    return net


class TestScoringWiring:
    def test_cap_fires_at_55(self):
        result = compute_risk(
            cookies=make_cookie_report(),
            network=_net_with_google_fonts(),
            privacy=make_privacy(),
            forms=make_form_report(),
            channels=make_channels(),
            widgets=make_widgets(),
            has_policy=True,
            has_imprint=True,
        )
        assert _has_cap(result, "google_fonts_external")
        assert result.score <= 55
        # Must NOT cap harder than 55 (regression guard against the
        # earlier 65 default — Phase-10 tightening).
        cap = next(c for c in result.applied_caps if c.code == "google_fonts_external")
        assert cap.cap_value == 55

    def test_cap_does_not_fire_when_no_google_fonts(self):
        # Plain network result, default GoogleFontsCheck (detected=False).
        result = compute_risk(
            cookies=make_cookie_report(),
            network=make_network(),
            privacy=make_privacy(),
            forms=make_form_report(),
            channels=make_channels(),
            widgets=make_widgets(),
            has_policy=True,
            has_imprint=True,
        )
        assert not _has_cap(result, "google_fonts_external")

    def test_recommendation_emitted_in_english_with_family_names(self):
        result = compute_risk(
            cookies=make_cookie_report(),
            network=_net_with_google_fonts(),
            privacy=make_privacy(),
            forms=make_form_report(),
            channels=make_channels(),
            widgets=make_widgets(),
            has_policy=True,
            has_imprint=True,
            lang="en",
        )
        details = " ".join(r.detail for r in result.recommendations)
        titles = " ".join(r.title for r in result.recommendations)
        # The LG München case is the legal anchor — must surface.
        assert "LG München I" in details
        assert "3 O 17493/20" in details
        # Detected families must surface so the operator knows what
        # to mirror locally.
        assert "Roboto" in details
        assert "Open Sans" in details
        # The fix path is the headline value of the recommendation.
        assert "Self-host" in titles

    def test_recommendation_emitted_in_german(self):
        result = compute_risk(
            cookies=make_cookie_report(),
            network=_net_with_google_fonts(),
            privacy=make_privacy(),
            forms=make_form_report(),
            channels=make_channels(),
            widgets=make_widgets(),
            has_policy=True,
            has_imprint=True,
            lang="de",
        )
        titles = " ".join(r.title for r in result.recommendations)
        details = " ".join(r.detail for r in result.recommendations)
        assert "selbst hosten" in titles
        assert "LG München I" in details
        assert "Schadensersatz" in details
