"""Deterministic Google-Fonts-loaded-externally detector (Phase 10).

Inspects a :class:`NetworkResult` and reports:

  - whether the site contacted Google's font servers
    (``fonts.googleapis.com`` for the CSS, ``fonts.gstatic.com`` for the
    binary .woff2 / .ttf files)
  - which font families were requested (parsed from the CSS URL's
    ``family=`` query parameter)
  - which pages initiated those requests
  - up to three sample URLs as audit evidence

The legal anchor is **LG München I 3 O 17493/20 (20.01.2022)**, a German
civil-court ruling that awarded €100 immaterial damages to a website
visitor whose IP address was transmitted to Google during a Google-
Fonts load. The court held the transmission was an unjustified
Art. 44 ff. DSGVO third-country transfer because the fonts could
trivially be self-hosted from the operator's own origin. German DPAs
have continued to cite the case in compliance reviews.

Scope notes
-----------

* The detector runs against the *pre-consent* network capture — the
  legally relevant state under § 25 TDDDG. Loading Google Fonts
  *after* explicit opt-in is a separate (and arguably defensible)
  question; this module does not address it.
* Not every Google-served font is in scope. Adobe Fonts (use.typekit
  .net), Bunny Fonts (fonts.bunny.net), and self-hosted Google Fonts
  copies do NOT trigger — those are the exact recommended remediation
  paths.
* Family parsing is best-effort: real sites use ``?family=Roboto``,
  ``?family=Roboto:300,400``, ``?family=Roboto|Open+Sans``, and the
  newer ``/css2?family=Roboto:wght@400;700`` syntax. The detector
  normalises ``+`` → space, splits on ``|``, and drops the
  ``:weights`` / ``:wght@…`` suffix. URLs we can't parse contribute
  to ``binary_count`` / ``css_url_samples`` but yield no family name.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from app.models import GoogleFontsCheck, NetworkResult


# Hostnames that cause the Phase 10 finding. Both are owned by Google
# Ireland Limited but resolve to global-anycast IPs that can route the
# request to a US server depending on edge location — the legal
# transfer concern stands either way.
_GFONTS_CSS_HOST = "fonts.googleapis.com"
_GFONTS_BIN_HOST = "fonts.gstatic.com"


def detect_google_fonts(network: NetworkResult) -> GoogleFontsCheck:
    """Inspect ``network`` for Google-Fonts loads and return a structured
    :class:`GoogleFontsCheck`.

    Empty input or no Google-Fonts hits returns the zero-state
    (``detected=False`` and empty lists). Caller decides what to do
    with that — the scoring layer reads ``detected`` to fire the
    ``google_fonts_external`` hard cap.
    """
    families: list[str] = []
    binary_count = 0
    initiator_pages: list[str] = []
    css_url_samples: list[str] = []
    detected = False

    seen_families: set[str] = set()
    seen_pages: set[str] = set()

    for r in network.requests:
        host = (urlparse(r.url).hostname or "").lower()
        if host == _GFONTS_CSS_HOST:
            detected = True
            for fam in _parse_families(r.url):
                if fam not in seen_families:
                    seen_families.add(fam)
                    families.append(fam)
            if len(css_url_samples) < 3:
                css_url_samples.append(r.url)
            if r.initiator_page and r.initiator_page not in seen_pages:
                seen_pages.add(r.initiator_page)
                initiator_pages.append(r.initiator_page)
        elif host == _GFONTS_BIN_HOST:
            detected = True
            binary_count += 1
            if r.initiator_page and r.initiator_page not in seen_pages:
                seen_pages.add(r.initiator_page)
                initiator_pages.append(r.initiator_page)

    return GoogleFontsCheck(
        detected=detected,
        families=families,
        binary_count=binary_count,
        initiator_pages=initiator_pages,
        css_url_samples=css_url_samples,
    )


def _parse_families(url: str) -> list[str]:
    """Pull human-readable family names out of a fonts.googleapis.com URL.

    Handles the four URL shapes seen in the wild:

    1. ``/css?family=Roboto`` → ``["Roboto"]``
    2. ``/css?family=Roboto:300,400`` → ``["Roboto"]`` (weight stripped)
    3. ``/css?family=Roboto|Open+Sans`` → ``["Roboto", "Open Sans"]``
       (the legacy multi-family pipe syntax + ``+`` URL-encoding)
    4. ``/css2?family=Roboto:wght@400;700`` → ``["Roboto"]``
       (the v2 axis-tuple syntax)

    Modern v2 URLs also support multiple ``family=`` parameters
    (``parse_qs`` returns a list), so we iterate over all values.
    Returns an empty list when no ``family=`` parameter is present.
    """
    qs = parse_qs(urlparse(url).query)
    raw_values = qs.get("family", [])
    out: list[str] = []
    for raw in raw_values:
        # The legacy syntax pipe-separates multiple families in a single
        # `family=` value; v2 puts each into its own `family=` entry but
        # also sometimes keeps the pipe — handle both.
        for chunk in raw.split("|"):
            # Drop weight/style/axis suffix: everything after the first ":".
            name = chunk.split(":", 1)[0]
            # `+` → space (URL-encoded family names like "Open+Sans").
            name = name.replace("+", " ").strip()
            if name:
                out.append(name)
    return out
