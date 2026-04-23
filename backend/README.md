# GDPR Scanner — Backend (Steps 1 – 4)

GDPR scanning platform backend. Currently implemented:

- **Step 1** — Playwright-driven crawler + network/data-flow analyzer.
- **Step 2** — Cookie + Web-Storage scanner with audit-grade classification.
- **Step 3** — Privacy-policy extractor + AI analyzer (OpenAI / Azure OpenAI
  abstraction) + deterministic form analyzer.
- **Step 4** — Weighted risk-scoring engine with named hard caps and
  prioritised, deduplicated recommendations.

The Next.js dashboard comes in the next step.

## What's in here

```
backend/
├── app/
│   ├── main.py              # FastAPI app — exposes POST /scan
│   ├── scanner.py           # Orchestrates Playwright + crawler + analyzer
│   ├── config.py            # Settings (.env)
│   ├── models.py            # Pydantic request/response models
│   └── modules/
│       ├── crawler.py            # BFS crawl, page parsing, privacy-page detection,
│       │                         # snapshots localStorage/sessionStorage + form context
│       ├── network_analyzer.py   # Captures every request, classifies country & risk
│       ├── cookie_scanner.py     # Cookie + storage classifier (necessary / functional /
│       │                         # analytics / marketing / unknown), with audit reasons
│       ├── policy_extractor.py   # Renders privacy page, strips chrome, head+tail truncation
│       ├── ai_analyzer.py        # OpenAI / Azure OpenAI abstraction, JSON-mode prompts,
│       │                         # cross-checks policy text against observed data flow
│       ├── form_analyzer.py      # Deterministic per-form PII / consent / privacy-link checks
│       └── scoring.py            # 5 sub-scores → weighted sum → named hard caps →
│                                 # priority-ranked recommendations (final RiskScore)
├── requirements.txt
└── .env.example
```

The crawler does *not* own the browser — `scanner.py` opens one Playwright
context, attaches `NetworkAnalyzer` to it, then hands the context to the
crawler. That way every request the crawler triggers is captured exactly once
in the same place, and future modules (cookie scanner, policy extractor) can
hook into the same context instead of reopening browsers.

## Setup

```bash
cd backend
python -m venv .venv
. .venv/Scripts/activate          # Windows
# source .venv/bin/activate       # macOS/Linux

pip install -r requirements.txt
playwright install chromium       # one-time browser download

cp .env.example .env
```

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

## Try it

```bash
curl -s http://localhost:8000/health

curl -s -X POST http://localhost:8000/scan \
  -H 'content-type: application/json' \
  -d '{"url":"https://example.com","max_depth":1,"max_pages":5}' | jq
```

## Sample response shape

```jsonc
{
  "target": "https://example.com",
  "crawl": {
    "start_url": "https://example.com",
    "privacy_policy_url": "https://example.com/datenschutz",
    "pages": [
      {
        "url": "https://example.com/",
        "title": "Example",
        "status": 200,
        "depth": 0,
        "scripts": ["https://www.googletagmanager.com/gtm.js?id=..."],
        "links":   ["https://example.com/datenschutz", "..."],
        "forms":   [{"method":"POST","action":"/contact","fields":[...], "page_url":"..."}],
        "is_privacy_policy": false
      }
    ]
  },
  "network": {
    "requests": [
      {"url":"...", "domain":"www.google-analytics.com",
       "registered_domain":"google-analytics.com",
       "method":"POST","resource_type":"xhr","status":200,
       "initiator_page":"https://example.com/", "is_third_party": true}
    ],
    "data_flow": [
      {"domain":"google-analytics.com","country":"USA",
       "request_count":4,"categories":["analytics","google"],"risk":"high"}
    ]
  },
  "risk": {
    "score": 50,
    "rating": "high",
    "weighted_score": 67,
    "sub_scores": [
      {"name":"cookies","score":76,"weight":0.20,"weighted_contribution":15.2,
       "notes":["1 marketing cookie(s) detected (-6 each)","6 analytics cookie(s) detected (-3 each)"]},
      {"name":"tracking","score":65,"weight":0.20,"weighted_contribution":13.0,
       "notes":["7 tracking/analytics domain(s) contacted (-5 each)"]},
      {"name":"data_transfer","score":52,"weight":0.25,"weighted_contribution":13.0,
       "notes":["4 high-risk transfer destination(s) (-12 each)"]},
      {"name":"privacy","score":64,"weight":0.25,"weighted_contribution":16.0,
       "notes":["AI compliance score: 64/100","Missing coverage: retention_period_stated, third_country_transfers_disclosed"]},
      {"name":"forms","score":100,"weight":0.10,"weighted_contribution":10.0,
       "notes":["No problematic forms detected"]}
    ],
    "applied_caps": [
      {"code":"us_analytics_no_consent",
       "description":"Site loads US analytics (e.g. GA, Clarity) but no consent-management cookie was observed.",
       "cap_value":50},
      {"code":"policy_silent_on_third_country_transfer",
       "description":"Site transfers data outside the EU/EEA but the privacy policy does not disclose it.",
       "cap_value":60}
    ],
    "recommendations": [
      {"priority":"high",
       "title":"Implement a consent-management platform (CMP)",
       "detail":"US analytics or marketing trackers are loading without a detectable consent banner. Block these scripts until the user has actively consented (opt-in, not opt-out).",
       "related":["us_analytics_no_consent"]},
      {"priority":"high",
       "title":"Disclose third-country transfers in the privacy policy",
       "detail":"Data is being transferred outside the EU/EEA but the policy does not mention it. Name the recipients, the country, the safeguard used (SCCs, adequacy decision), and where users can request a copy of those safeguards.",
       "related":["policy_silent_on_third_country_transfer"]},
      {"priority":"high",
       "title":"Replace or properly safeguard high-risk US transfers",
       "detail":"High-risk transfers detected to: google-analytics.com, doubleclick.net, facebook.com, hotjar.com. Either move to an EU-hosted alternative, or document SCCs + a Transfer Impact Assessment (Schrems II) for each recipient.",
       "related":["google-analytics.com","doubleclick.net","facebook.com","hotjar.com"]}
    ]
  },
  "privacy_analysis": {
    "provider": "openai",
    "model": "gpt-4o-mini",
    "policy_url": "https://example.com/datenschutz",
    "summary": "The policy describes use of Google Analytics and a contact form, lists a controller address, and references user rights but does not state retention periods or list third-country safeguards.",
    "compliance_score": 64,
    "excerpt_chars_sent": 18432,
    "coverage": {
      "legal_basis_stated": true,
      "data_categories_listed": true,
      "retention_period_stated": false,
      "third_party_recipients_listed": true,
      "third_country_transfers_disclosed": false,
      "user_rights_enumerated": true,
      "contact_for_data_protection": true,
      "cookie_section_present": true,
      "children_data_addressed": false
    },
    "issues": [
      {"category":"missing_retention","severity":"high",
       "description":"No retention period stated for any processing activity.",
       "excerpt":null},
      {"category":"third_country_transfer","severity":"high",
       "description":"Site loads google-analytics.com (USA) but policy does not disclose the transfer or its safeguards.",
       "excerpt":null}
    ],
    "error": null
  },
  "forms": {
    "forms": [
      {"page_url":"https://example.com/contact",
       "form_action":"https://example.com/contact",
       "method":"POST",
       "collected_data":["email","name","free_text"],
       "field_count":4,
       "has_consent_checkbox":false,
       "has_privacy_link":true,
       "legal_text_excerpt":"…Mit Klick auf Senden willigen Sie in die Verarbeitung Ihrer Daten ein…",
       "issues":["Form collects personal data but has no consent checkbox."]}
    ],
    "summary": {
      "total_forms": 2,
      "forms_collecting_pii": 1,
      "forms_with_consent_checkbox": 0,
      "forms_with_privacy_link": 1,
      "forms_with_issues": 1
    }
  },
  "cookies": {
    "cookies": [
      {"name":"_ga","domain":".example.com","path":"/",
       "value_preview":"GA1.…xy","value_length":30,
       "expires":1798765432.0,"secure":true,"http_only":false,
       "same_site":"Lax","is_third_party":false,"is_session":false,
       "category":"analytics","vendor":"google",
       "reason":"Google Analytics client/session id"},
      {"name":"PHPSESSID","domain":"example.com","path":"/",
       "value_preview":"a1b2…7f","value_length":26,
       "expires":null,"secure":true,"http_only":true,
       "same_site":"Strict","is_third_party":false,"is_session":true,
       "category":"necessary","vendor":null,
       "reason":"Server session cookie"}
    ],
    "storage": [
      {"page_url":"https://example.com/","kind":"local",
       "key":"_hjSessionUser_123","value_preview":"eyJ…","value_length":244,
       "category":"analytics","vendor":"hotjar",
       "reason":"Hotjar behavior analytics"}
    ],
    "summary": {
      "total_cookies": 12, "third_party_cookies": 7, "session_cookies": 3,
      "total_storage": 5,
      "cookies_necessary": 3, "cookies_functional": 1,
      "cookies_analytics": 4, "cookies_marketing": 3, "cookies_unknown": 1,
      "storage_necessary": 1, "storage_functional": 0,
      "storage_analytics": 3, "storage_marketing": 1, "storage_unknown": 0
    }
  }
}
```

## Design notes

- **Offline country classification.** We deliberately do *not* send observed
  hostnames or IPs to a third-party geolocation API — doing so during a GDPR
  audit would itself be a small cross-border transfer. Classification uses a
  curated tracker map plus an EU/EEA ccTLD heuristic, with `Unknown` as the
  honest fallback.
- **Schrems II–aware risk.** US destinations carrying analytics, marketing,
  or AI categories are flagged `high`; other US transfers `medium`. EU is
  `low`. Unknown is `medium` (don't reward opacity).
- **Cookie classification priority.** (1) name pattern, (2) cookie domain in
  the tracker registry, (3) first-party session/auth/consent heuristics,
  (4) `unknown` fallback. Every entry carries an `reason` string so an
  auditor can see *why* a cookie was placed in its bucket — guesses are
  visible as guesses, not laundered into confident labels.
- **Cookie values are masked.** Only a short prefix/suffix preview plus
  length is kept. Values that look like JWTs are replaced with `<jwt>`
  entirely (the `eyJ…` prefix can leak the issuer).
- **No PII storage.** The scanner logs request metadata, masked cookie/
  storage previews, and form schemas — never request bodies, full cookie
  values, or response payloads.
- **AI provider abstraction.** `AIProvider` is the only interface
  `scanner.py` knows about. `get_provider()` picks `OpenAIProvider`,
  `AzureOpenAIProvider`, or `NoOpProvider` based on `.env`. Missing keys
  degrade to `NoOpProvider` — a scan still completes, just with
  `privacy_analysis.provider = "none"` and `error = "no_provider_configured"`.
- **Cross-checking the policy against reality.** The AI prompt is given the
  observed third-party data flow as evidence. "The policy mentions X but
  the site actually contacts Y" is the single biggest signal that beats
  reading the policy in isolation, so we lean on it explicitly.
- **JSON-mode + Pydantic validation.** Both providers call with
  `response_format={"type":"json_object"}`. The reply is then parsed
  through Pydantic; on schema mismatch the analysis surfaces an `error`
  rather than a confidently-wrong result.
- **Head + tail truncation for long policies.** Definitions live at the top,
  rights/contact info live at the bottom. Sampling only the head loses
  both. We send the first ~12k chars, a `[…TRUNCATED N CHARS…]` marker,
  and the last ~12k chars (configurable via `AI_MAX_POLICY_CHARS`).
- **Forms are deterministic, not AI.** Form structure is regular HTML;
  spending an LLM call on it would burn ~5s for what regex does in
  microseconds. The AI budget is reserved for the privacy policy where
  language ambiguity actually matters.
- **Weighted sum + named hard caps.** A pure weighted average can be gamed
  — a site running a Meta Pixel without consent could still score 75
  because everything else is fine. Hard caps express "no matter what,
  presence of X means the site cannot score above N". Each cap has a
  `code` + `description` so the dashboard can show **why** the score was
  capped — opaque scores are useless for an audit.
- **Privacy sub-score is *neutral* (50) when no AI provider is configured.**
  We didn't measure it, so we don't punish or reward it. The auditor sees
  `privacy_analysis.provider="none"` and knows to re-run with a key.

### Scoring weights & caps

Weighted sum (must sum to 1.0):

| Sub-score        | Weight |
| ---------------- | ------ |
| `cookies`        | 20%    |
| `tracking`       | 20%    |
| `data_transfer`  | 25%    |
| `privacy`        | 25%    |
| `forms`          | 10%    |

Hard caps (any that triggers limits the *final* score):

| Code                                         | Cap |
| -------------------------------------------- | --- |
| `no_privacy_policy`                          |  30 |
| `us_marketing_no_consent`                    |  40 |
| `us_analytics_no_consent`                    |  50 |
| `tdddg_non_essential_without_consent`        |  50 |
| `no_legal_basis_stated`                      |  55 |
| `policy_silent_on_third_country_transfer`    |  60 |
| `tdddg_third_party_without_consent`          |  70 |

Risk rating buckets: **80-100** low · **60-79** medium · **40-59** high ·
**0-39** critical.

## Frontend

The Next.js dashboard lives in [`../frontend`](../frontend) and consumes
the JSON above. See its README for setup. It calls the backend via a
same-origin proxy at `/api/scan` so you don't need to enable CORS in
production — only the dev `*` is set in `app/main.py`.

## Running the tests

The test suite covers `scoring.py`, `consent_diff.py`, and `form_analyzer.py`
with 107 unit tests. All tests are pure-Python (no Playwright, no network, no
database) and complete in under a second.

```powershell
# Inside the backend venv
cd "D:\DSGVO Scanner Tool\backend"
.\.venv\Scripts\Activate.ps1

# First time only
pip install pytest pytest-asyncio

# Run all tests
pytest

# Verbose output (shows each test name)
pytest -v

# Run only scoring tests
pytest tests/test_scoring.py -v
```

Test files:

| File | What it covers |
|---|---|
| `tests/test_scoring.py` | Sub-scores, all 15 hard-cap codes, `compute_risk` integration |
| `tests/test_consent_diff.py` | Pre/post cookie dedup, storage dedup, data-flow dedup, request delta |
| `tests/test_form_analyzer.py` | Purpose detection (Gewobag fix), PII category regex, issue generation, summary counts |

Shared builders live in `tests/conftest.py`. Each builder returns a Pydantic
model with sensible defaults — override only the fields that matter for a
given test.
