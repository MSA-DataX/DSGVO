"""Known-vulnerable JavaScript library detection (Retire.js-style).

Walks every script URL the site loaded and matches them against a
curated vulnerability database. The DB here is a hand-picked subset of
Retire.js's catalogue — the libraries that actually appear in DSGVO
audits with real-world frequency (jQuery, Bootstrap, AngularJS,
Moment.js, Lodash, etc.).

Why a subset and not the full Retire.js JSON:

- The full DB is ~700 KB and mostly covers libraries 99% of EU websites
  don't use. Shipping the whole thing inflates the image without
  benefit.
- Retire.js's regex catalogue uses JavaScript-flavoured patterns that
  don't port cleanly to Python `re`. The patterns below are re-expressed
  in Python `re` once, not translated at runtime.
- A smaller, readable DB means an auditor can verify "yes, these are
  real CVEs" without trusting an opaque blob.

GDPR relevance: Art. 32 DSGVO ("appropriate technical measures").
Running a library with a published XSS / prototype-pollution CVE is
the exact scenario Art. 32 targets — a known, documented weakness the
operator has had the opportunity and means to fix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import NetworkResult, Severity, VulnerableLibrariesReport, VulnerableLibrary


# ---------------------------------------------------------------------------
# Version comparison — semver-ish.
# ---------------------------------------------------------------------------

def _ver_tuple(v: str) -> tuple[int, ...]:
    """Turn '1.11.0' / '3.5.1-beta' into a comparable tuple of ints."""
    cleaned = re.sub(r"[^\d.]", "", v)
    parts = [p for p in cleaned.split(".") if p]
    return tuple(int(p) for p in parts) if parts else (0,)


def _ver_lt(a: str, b: str) -> bool:
    """a < b, element-wise comparison with zero-padding."""
    at, bt = _ver_tuple(a), _ver_tuple(b)
    n = max(len(at), len(bt))
    return (at + (0,) * (n - len(at))) < (bt + (0,) * (n - len(bt)))


def _ver_in_range(version: str, below: str) -> bool:
    """True if ``version`` is strictly less than ``below``."""
    return _ver_lt(version, below)


# ---------------------------------------------------------------------------
# Detection rules.
#
# Each library has:
#   - name: canonical display name
#   - url_patterns: regexes capturing the version from a script URL's
#     basename. Group 1 is the version string.
#   - vulnerabilities: list of (below_version, severity, cves, advisory,
#     fixed_in) — if detected version < below_version, report.
# ---------------------------------------------------------------------------

@dataclass
class _Vuln:
    below: str          # everything below this version is affected
    severity: Severity
    cves: list[str]
    advisory: str
    fixed_in: str       # first safe version (usually same as below)


@dataclass
class _LibRule:
    name: str
    url_patterns: list[re.Pattern[str]]
    vulns: list[_Vuln]


_LIBS: list[_LibRule] = [
    _LibRule(
        name="jquery",
        url_patterns=[
            re.compile(r"/jquery[-.](\d+\.\d+(?:\.\d+)?)(?:\.slim)?(?:\.min)?\.js", re.I),
            re.compile(r"/jquery/(\d+\.\d+(?:\.\d+)?)/jquery", re.I),
        ],
        vulns=[
            _Vuln("1.9.0",  "high",   ["CVE-2012-6708"],
                  "Selector parsing treats text starting with '<' as HTML — XSS in apps passing user input to $().",
                  "1.9.0"),
            _Vuln("3.0.0",  "medium", ["CVE-2015-9251"],
                  "Ajax requests with cross-domain responses could execute arbitrary code.",
                  "3.0.0"),
            _Vuln("3.4.0",  "medium", ["CVE-2019-11358"],
                  "Prototype pollution via $.extend(true, {}, …) with a constructor-shaped object.",
                  "3.4.0"),
            _Vuln("3.5.0",  "medium", ["CVE-2020-11022", "CVE-2020-11023"],
                  "HTML containing <option> elements from untrusted sources passed to DOM manipulation methods executes.",
                  "3.5.0"),
        ],
    ),
    _LibRule(
        name="jquery-ui",
        url_patterns=[
            re.compile(r"/jquery-ui[-.](\d+\.\d+(?:\.\d+)?)(?:\.min)?\.js", re.I),
            re.compile(r"/jqueryui/(\d+\.\d+(?:\.\d+)?)/", re.I),
        ],
        vulns=[
            _Vuln("1.12.0", "medium", ["CVE-2016-7103"],
                  "XSS in the closeText option of the dialog widget.",
                  "1.12.0"),
            _Vuln("1.13.0", "medium", ["CVE-2021-41182", "CVE-2021-41183", "CVE-2021-41184"],
                  "XSS via altField/showAnim/position options.",
                  "1.13.0"),
        ],
    ),
    _LibRule(
        name="bootstrap",
        url_patterns=[
            re.compile(r"/bootstrap[-.](\d+\.\d+(?:\.\d+)?)(?:\.min)?\.js", re.I),
            re.compile(r"/bootstrap/(\d+\.\d+(?:\.\d+)?)/js/bootstrap", re.I),
        ],
        vulns=[
            _Vuln("3.4.0",  "medium", ["CVE-2018-14041", "CVE-2018-14042", "CVE-2019-8331"],
                  "XSS in data-container / data-title / tooltip options.",
                  "3.4.0"),
            _Vuln("4.3.1",  "medium", ["CVE-2019-8331"],
                  "XSS in tooltip/popover data-template attribute.",
                  "4.3.1"),
        ],
    ),
    _LibRule(
        name="angular",
        url_patterns=[
            re.compile(r"/angular[-.](\d+\.\d+(?:\.\d+)?)(?:\.min)?\.js", re.I),
            re.compile(r"/angularjs/(\d+\.\d+(?:\.\d+)?)/angular", re.I),
        ],
        vulns=[
            _Vuln("1.8.0",  "high",   ["CVE-2020-7676"],
                  "AngularJS prototype pollution through merge/copy — upgrade to Angular 2+, AngularJS is EOL.",
                  "1.8.0 (end of life — migrate to Angular 2+)"),
        ],
    ),
    _LibRule(
        name="moment",
        url_patterns=[
            re.compile(r"/moment[-.](\d+\.\d+(?:\.\d+)?)(?:\.min)?\.js", re.I),
        ],
        vulns=[
            _Vuln("2.19.3", "medium", ["CVE-2017-18214"],
                  "ReDoS in the utils/is-date function.",
                  "2.19.3"),
            _Vuln("2.29.2", "medium", ["CVE-2022-24785"],
                  "Path traversal when using locale feature in Node — not exploitable in browser, still a signal of an outdated pin.",
                  "2.29.2"),
            _Vuln("2.29.4", "medium", ["CVE-2022-31129"],
                  "ReDoS in rfc2822 parsing of long strings.",
                  "2.29.4"),
        ],
    ),
    _LibRule(
        name="lodash",
        url_patterns=[
            re.compile(r"/lodash[-.](\d+\.\d+(?:\.\d+)?)(?:\.min)?\.js", re.I),
        ],
        vulns=[
            _Vuln("4.17.5",  "high",   ["CVE-2018-3721"],
                  "Prototype pollution in _.defaultsDeep / _.merge / _.mergeWith.",
                  "4.17.5"),
            _Vuln("4.17.11", "high",   ["CVE-2018-16487"],
                  "Prototype pollution variant.",
                  "4.17.11"),
            _Vuln("4.17.12", "high",   ["CVE-2019-10744"],
                  "Prototype pollution in _.defaultsDeep.",
                  "4.17.12"),
            _Vuln("4.17.21", "high",   ["CVE-2020-8203", "CVE-2021-23337"],
                  "Command injection in _.template + prototype pollution in _.zipObjectDeep.",
                  "4.17.21"),
        ],
    ),
    _LibRule(
        name="handlebars",
        url_patterns=[
            re.compile(r"/handlebars[-.](\d+\.\d+(?:\.\d+)?)(?:\.min)?\.js", re.I),
        ],
        vulns=[
            _Vuln("4.7.7",  "high",   ["CVE-2019-19919", "CVE-2021-23369", "CVE-2021-23383"],
                  "Prototype pollution / arbitrary code execution in template compilation.",
                  "4.7.7"),
        ],
    ),
    _LibRule(
        name="underscore",
        url_patterns=[
            re.compile(r"/underscore[-.](\d+\.\d+(?:\.\d+)?)(?:\.min)?\.js", re.I),
        ],
        vulns=[
            _Vuln("1.12.1", "high",   ["CVE-2021-23358"],
                  "Arbitrary code execution in _.template.",
                  "1.12.1"),
        ],
    ),
    _LibRule(
        name="dompurify",
        url_patterns=[
            re.compile(r"/(?:dompurify|purify)[-.](\d+\.\d+(?:\.\d+)?)(?:\.min)?\.js", re.I),
        ],
        vulns=[
            _Vuln("2.4.0",  "medium", ["CVE-2022-39299"],
                  "XSS via SVG+MathML namespace confusion.",
                  "2.4.0"),
        ],
    ),
    _LibRule(
        name="tinymce",
        url_patterns=[
            re.compile(r"/tinymce/(\d+\.\d+(?:\.\d+)?)/tinymce", re.I),
            re.compile(r"/tinymce[-.](\d+\.\d+(?:\.\d+)?)(?:\.min)?\.js", re.I),
        ],
        vulns=[
            _Vuln("5.10.0", "medium", ["CVE-2021-43811"],
                  "XSS via the 'contextmenu' plugin.",
                  "5.10.0"),
            _Vuln("6.7.3",  "medium", ["CVE-2023-45818"],
                  "XSS via malformed noneditable content.",
                  "6.7.3"),
        ],
    ),
    _LibRule(
        name="swfobject",
        url_patterns=[
            re.compile(r"/swfobject[-.]?(\d+\.\d+(?:\.\d+)?)?(?:\.min)?\.js", re.I),
        ],
        vulns=[
            # Any detected swfobject is suspicious — Flash died in 2020.
            _Vuln("9999.0", "high", [],
                  "SWFObject loads Flash, end-of-life since 2020. Remove entirely.",
                  "n/a"),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def detect_vulnerable_libraries(network: NetworkResult) -> VulnerableLibrariesReport:
    """Scan every captured script URL for known-vulnerable library versions."""
    findings: list[VulnerableLibrary] = []
    seen: set[tuple[str, str, str]] = set()  # dedupe on (lib, version, url)

    for req in network.requests:
        # Restrict to script resources — reduces false positives and noise.
        if (req.resource_type or "").lower() != "script":
            continue
        url = req.url
        for rule in _LIBS:
            version: str | None = None
            for pattern in rule.url_patterns:
                m = pattern.search(url)
                if m and m.group(1):
                    version = m.group(1)
                    break
            if version is None:
                continue
            for vuln in rule.vulns:
                # swfobject is flagged unconditionally — its sentinel version
                # is higher than any real release.
                if rule.name == "swfobject" or _ver_in_range(version, vuln.below):
                    key = (rule.name, version, url)
                    if key in seen:
                        continue
                    seen.add(key)
                    findings.append(VulnerableLibrary(
                        library=rule.name,
                        detected_version=version,
                        url=url,
                        severity=vuln.severity,
                        cves=list(vuln.cves),
                        advisory=vuln.advisory,
                        fixed_in=vuln.fixed_in,
                    ))
                    # Only report the worst vulnerability per (lib, version).
                    # vulns are ordered lowest→highest cutoff; the first
                    # matching one is the most severe version gap.
                    break
            # don't double-match rule against same URL
            break

    summary = {
        "total": len(findings),
        "high":   sum(1 for f in findings if f.severity == "high"),
        "medium": sum(1 for f in findings if f.severity == "medium"),
        "low":    sum(1 for f in findings if f.severity == "low"),
    }
    return VulnerableLibrariesReport(libraries=findings, summary=summary)
