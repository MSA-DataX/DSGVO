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

| Code                                         | Cap | Source |
| -------------------------------------------- | --- | --- |
| `no_privacy_policy`                          |  30 | Art. 13/14 DSGVO |
| `us_marketing_no_consent`                    |  40 | Art. 6 + § 25 TDDDG |
| `pre_checked_consent_box`                    |  40 | Art. 7(2) DSGVO + EuGH C-673/17 (Planet49) |
| `us_analytics_no_consent`                    |  50 | Art. 6 + § 25 TDDDG |
| `tdddg_non_essential_without_consent`        |  50 | § 25 TDDDG |
| `no_legal_basis_stated`                      |  55 | Art. 6 DSGVO |
| `policy_missing_user_rights`                 |  55 | Art. 13(2)(b) DSGVO (deterministic DSAR check) |
| `policy_silent_on_third_country_transfer`    |  60 | Art. 44–49 DSGVO |
| `tdddg_third_party_without_consent`          |  70 | § 25 TDDDG (light tier) |

Risk rating buckets: **80-100** low · **60-79** medium · **40-59** high ·
**0-39** critical.

## Frontend

The Next.js dashboard lives in [`../frontend`](../frontend) and consumes
the JSON above. See its README for setup. It calls the backend via a
same-origin proxy at `/api/scan` so you don't need to enable CORS in
production — only the dev `*` is set in `app/main.py`.

## Persistence (SQLite or Postgres)

The storage layer is SQLAlchemy 2.0 async, so the same code path runs
against either backend — only `DATABASE_URL` changes.

**Default (zero config):** `sqlite+aiosqlite:///scans.db` — a single file
in the backend directory. Good enough for local dev.

**Postgres (recommended for multi-user use):**

```powershell
# Start the local Postgres container
cd "D:\DSGVO Scanner Tool\backend"
docker compose up -d

# Point the backend at it (in backend/.env):
#   DATABASE_URL=postgresql+asyncpg://scanner:scanner@localhost:5432/scanner

# Apply migrations
alembic upgrade head

# Now run the backend as usual
python run_dev.py
```

### Migrations (Alembic)

```powershell
# Apply all pending migrations
alembic upgrade head

# Generate a new migration after editing app/db_models.py
alembic revision --autogenerate -m "add users table"

# Roll back the latest
alembic downgrade -1

# Inspect history
alembic history
```

`alembic/env.py` reads the URL from `DATABASE_URL` (or
`app.config.settings.database_url` as fallback), so the same migration
workflow works against the local SQLite file and the dockerized Postgres.

## Authentication (Phase 1.2)

JWT-based auth, bcrypt-hashed passwords. Every signup creates a user
**and** a personal organization (the per-user "workspace"). Every scan-
related endpoint (`/scan`, `/scan/stream`, `/scans*`) requires
`Authorization: Bearer <token>`.

```bash
# Signup → returns access_token + user
curl -X POST http://localhost:8080/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com","password":"long-enough-password","display_name":"Alice"}'

# Login → returns a fresh access_token
curl -X POST http://localhost:8080/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com","password":"long-enough-password"}'

# Use the token
curl http://localhost:8080/auth/me \
  -H "Authorization: Bearer <token>"
```

Set `JWT_SECRET` in `.env` to a strong random value before deploying:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Token TTL defaults to 7 days (`JWT_TTL_MINUTES`); the `/auth/me` endpoint
hits the DB on every request so revoking access is a single DB write —
no need to wait for the JWT to expire.

## Billing + quotas (Phase 5a)

Every scan endpoint (`/scan`, `/scan/stream`, `/scan/jobs`) enforces a
per-organization monthly quota. Phase 5a ships the tier architecture
WITHOUT payments wired — plans get assigned manually by an admin.
Mollie goes in Phase 5b using the same `set_plan` helper.

**Plan catalogue** ([app/billing/plans.py](app/billing/plans.py)):

| Code | Name | Price | Monthly scans |
|---|---|---|---|
| `free` | Free | 0 € | 5 |
| `pro` | Pro | 19 € | 100 |
| `business` | Business | 99 € | 1000 |

Absence of a `Subscription` row means the org is on the free tier —
upgrading inserts a row, nothing to backfill.

**Read endpoints:**

```bash
# Public: used by pricing pages + signup flow
curl http://localhost:8080/billing/plans

# Authed: current org's plan + usage
curl http://localhost:8080/billing/subscription \
  -H "Authorization: Bearer <token>"
# → {"plan":{...}, "status":"no_subscription",
#    "scans_used":3, "scans_quota":5, "quota_remaining":2, ...}
```

**Admin override** (Phase 5a's upgrade path — Mollie replaces it in 5b):

```bash
curl -X POST http://localhost:8080/admin/organizations/<org_id>/set-plan \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"plan_code":"pro"}'
# → {"organization_id":"...","plan_code":"pro","status":"active"}
# Writes action="organization.set_plan" to the audit log.
```

**What 402 means:** the caller used up their monthly allowance. SSRF
rejections stay 400, rate-limit rejections stay 429 — a 402 is only
ever a billing signal. The response detail carries `plan`,
`scans_used`, `scans_quota` so a UI can show "Upgrade" directly.

### Mollie integration (Phase 5b)

Opt-in via three env vars. Without any of them the app runs in the
Phase 5a mode (admin-assigned plans only).

```bash
# backend/.env
MOLLIE_API_KEY=test_xxx                    # or live_xxx
APP_BASE_URL=https://scanner.example.com   # public origin of THIS backend
MOLLIE_WEBHOOK_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
```

Mollie's test API key comes from
https://www.mollie.com/dashboard/developers/api-keys (after you create
a free Mollie account). For local development the webhook URL needs to
be publicly reachable — use `ngrok http 8080` or `cloudflared tunnel`
and set `APP_BASE_URL` to the tunnel URL.

**Checkout flow (from the customer's POV):**

```
Frontend: POST /billing/checkout {"plan_code": "pro"}
  → { "checkout_url": "https://www.mollie.com/checkout/..." }
Browser redirect to checkout_url
  → user enters payment details
  → Mollie returns browser to APP_BASE_URL/billing?status=return
Backend receives Mollie webhook at /billing/webhook/{MOLLIE_WEBHOOK_TOKEN}
  → fetches the payment via get_payment()
  → on `paid`: creates recurring Subscription in Mollie, flips our row to `active`
  → user's next /scan call has full Pro-tier quota
```

**Cancel flow:** `POST /billing/cancel` (authed) — tells Mollie to stop
future charges. User keeps their plan until `current_period_end`.
We re-use `set_plan` under the hood, so the same audit / storage path
applies as the admin override.

**Webhook security:** Mollie does NOT sign webhook payloads. The URL
path token IS the shared secret. We constant-time-compare it against
`MOLLIE_WEBHOOK_TOKEN` — wrong token yields 404 (not 403) so probers
can't distinguish from a non-existent route. After auth, we re-fetch
the payment from Mollie's API before touching any DB row, so a
forged "id" in the body can't alter state.

**Fully mocked in tests:** `_FakeMollieClient` in
`tests/test_billing_mollie.py` records every method call + returns
canned responses. No network, no real Mollie account needed for CI.

## Account deletion + retention (Phase 8)

Two GDPR primitives:

**`DELETE /auth/me`** — Article 17 right to erasure. The user calls
this and the system cascades: cancels Mollie subscriptions on orgs
they solely own, deletes those orgs (which cascades to scans,
memberships, subscription rows), then deletes the user. Audit
entries written by that user survive — `actor_user_id` becomes NULL
via `ON DELETE SET NULL` but `actor_email` is denormalised at write
time so the trail stays readable.

```bash
curl -X DELETE http://localhost:8080/auth/me \
  -H "Authorization: Bearer <token>"
# → {"status":"deleted","deleted_user_id":"...","deleted_organization_ids":[...],
#    "mollie_subscriptions_canceled":1}
```

The frontend is expected to follow up with `/api/auth/logout` to
clear the auth cookie — the JWT stays cryptographically valid until
TTL otherwise. Subsequent requests 401 anyway because
`get_current_user` can't find the user row.

**Automated retention** — runs nightly at 03:30 UTC inside the Arq
worker (`WorkerSettings.cron_jobs`). Enforces:

| Class | Default | Override env-side |
|---|---|---|
| Scans | 12 months | bump in `app/retention.py` (DEFAULT_SCAN_MONTHS) |
| Audit log | 3 years | bump in `app/retention.py` (DEFAULT_AUDIT_YEARS) |
| Orphan scans | immediate | n/a |

For one-off sweeps or operator inspection:

```bash
# Dry-run — count rows that would go, delete nothing
python -m app.cli.retention --dry-run

# Tighter retention for a one-off cleanup
python -m app.cli.retention --scan-months 6 --audit-years 1
```

The CLI shares a code path with the cron, so an interactive sweep
behaves identically to a scheduled one.

> **Important — SQLite FK enforcement.** SQLite ships with foreign-
> key checks OFF per connection. Without `PRAGMA foreign_keys=ON`,
> declared `ON DELETE CASCADE` / `SET NULL` silently no-op on dev
> while Postgres in production enforces them. `app.db.install_sqlite_fk_pragma`
> registers a connect-listener that flips it on; production wires
> it automatically, every test fixture creating a fresh engine
> calls it explicitly.

## System admin (Phase 4)

Super-admin privilege (`User.is_superuser`) is a separate dimension from
organization roles — members of an org never see other tenants' data
regardless of who they are, so the admin flag is an orthogonal
platform-level capability.

**Bootstrap the first admin** (CLI — intentionally not an HTTP endpoint):

```powershell
cd "D:\DSGVO Scanner Tool\backend"
.\.venv\Scripts\Activate.ps1

# Grant
python -m app.cli.promote admin@example.com

# Revoke (if needed)
python -m app.cli.promote --revoke admin@example.com
```

The user must already exist (sign them up via `/auth/signup` first). The
CLI writes an audit row with a null `actor_user_id` so even the
bootstrap is traceable.

**Admin HTTP surface** (all guarded by `require_superuser`, 403 for
non-admins):

| Method | Path | What it does |
|---|---|---|
| GET | `/admin/users` | List every account |
| GET | `/admin/organizations` | List orgs + member/scan counts |
| GET | `/admin/audit` | Audit log (filter with `?action=…`, `?actor_user_id=…`) |
| POST | `/admin/users/{id}/promote` | Grant superuser |
| POST | `/admin/users/{id}/demote` | Revoke superuser (blocked on self) |
| POST | `/admin/users/{id}/reset-password` | Force a new password |

Every mutation logs one `AuditLog` row with actor + action + target +
IP + user-agent. The log is append-only from the app (no UPDATE /
DELETE code path exists). Retention policy lives at the database
layer.

## Boundary guards (Phase 2 + 2b)

A GDPR-audit tool that fetches user-supplied URLs is an SSRF magnet.
Defence runs at three layers, all sharing the same `validate_url_safe`
logic:

1. **Entry** (`main.py` at `/scan` + `/scan/stream`) — first line of
   defence. Rejects `file://`, `javascript:`, IP literals in loopback /
   private / link-local / multicast / metadata ranges, and DNS
   hostnames whose resolution touches those ranges. All resolved
   addresses are checked, not just the first.
2. **Browser** (`scanner._install_ssrf_guard` on every
   `BrowserContext`) — Playwright `context.route("**/*", …)` handler
   that re-validates every request the browser makes. Catches `302`
   follow-ups to `http://169.254.169.254/…`, sub-resource embeds
   pointing at internal addresses, etc. Per-hostname cache so a
   same-host scan only pays one DNS lookup.
3. **httpx** (`policy_extractor._safe_fetch_follow`) — redirect
   chains are walked manually with `follow_redirects=False`. Each
   `Location` is SSRF-validated before the next request. Chain capped
   at a small number of hops to kill pathological loops.

Rate limits (both in-memory sliding windows, swap to Redis in Phase 3):

- **Scans**: 3/min + 50/day per organization. `Retry-After` included.
- **Auth** (signup + login combined, keyed by client IP): 5/min +
  50/day. Blocks credential-stuffing + signup-flood from one source.
  `X-Forwarded-For` honoured — trust a single-hop proxy.

Known gaps: DNS rebinding (host resolves public at validation time,
private at fetch time — fix needs IP pinning in the transport). Cover
at the network layer with an egress firewall / NetworkPolicy in
production.

## Async scan mode (Phase 3)

The sync `POST /scan` endpoint blocks the Uvicorn worker for the full
30-90s of a scan. Fine for single-user dev; a non-starter under any
load. Phase 3 adds an Arq-backed async path you can enable with one
env var.

**Enable:**

```powershell
# 1) Start Redis (docker compose already has the service)
docker compose up -d redis

# 2) Point the backend at it (backend/.env)
#    REDIS_URL=redis://localhost:6379

# 3) In a new terminal, start the worker
cd backend
.\.venv\Scripts\Activate.ps1
arq app.worker.WorkerSettings

# 4) Leave run_dev.py running as before
```

**Use:**

```bash
# Enqueue — returns 202 + scan_id immediately
curl -X POST http://localhost:8080/scan/jobs \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/"}'
# → {"id":"abc123","status":"queued","url":"https://…","created_at":"…"}

# Poll — returns the full ScanResponse in `result` once status=="done"
curl http://localhost:8080/scan/jobs/abc123 \
  -H "Authorization: Bearer <token>"
# → {"id":"abc123","status":"running", ...}
# … later …
# → {"id":"abc123","status":"done","result":{…full ScanResponse…}}
```

Status progression: `queued → running → done` (or `failed`).
Placeholders during queued/running carry `score=0`, `rating="critical"`
— the history list filters those out so they never surface.

### Live progress for async scans (Phase 3b)

The worker publishes every scanner event to a per-scan Redis channel
(`scan:progress:{scan_id}`). `GET /scan/jobs/{id}/events` is an SSE
stream that forwards those events to the browser, closing on the
final `done` / `error` event.

```bash
curl -N http://localhost:8080/scan/jobs/abc123/events \
  -H "Authorization: Bearer <token>"
# event: progress
# data: {"stage":"crawling","message":"BFS page 1/8",...}
#
# event: progress
# data: {"stage":"scoring","message":"Computing risk",...}
#
# event: progress
# data: {"stage":"done","message":"Scan complete",...}
```

The endpoint is race-free: it subscribes first, then re-checks the DB
status. Scans that finished before the client subscribed emit a
single snapshot event and close immediately. The authoritative state
is still the DB row; the stream is purely progress UX.

Sync (`/scan`, `/scan/stream`) and async (`/scan/jobs` +
`/scan/jobs/{id}/events`) co-exist indefinitely. Use sync for the
current browser flow; use async for API integrations, webhook
callbacks, long scans, or whenever you want the HTTP worker back
inside 100 ms.

### Switching the frontend to async mode (Phase 3c)

The frontend dashboard picks between the two paths with a build-time
env var. Default is sync so nothing changes until you flip it:

```bash
# frontend/.env.local
NEXT_PUBLIC_SCAN_MODE=async    # omit or set "sync" for the old path
```

Restart `npm run dev` after editing (Next.js inlines `NEXT_PUBLIC_*`
at boot, not per-request). The UI calls `streamScanAuto(...)` in
[lib/api.ts](../frontend/lib/api.ts) which routes to either
`streamScan` (sync, one SSE to `/scan/stream`) or `streamScanAsync`
(enqueue → subscribe `/scan/jobs/{id}/events` → fetch result on `done`).
The handler contract (`onProgress` / `onResult` / `onError`) is
identical so the rest of the dashboard is unchanged.

## Observability (Phase 7)

Three things land on every production request:

1. **Request-ID tracing.** A middleware reuses a trusted upstream
   `X-Request-ID` or mints one; every log record from that request
   carries it via a `ContextVar`. Echoed back in the response header
   so clients + edge logs line up.
2. **Structured logs.** `LOG_FORMAT=json` emits one JSON object per
   line — ready for Loki, CloudWatch, Datadog, or any shipper without
   a regex-parse step. Dev default stays `text` so the terminal is
   readable.
3. **Prometheus `/metrics`.** Plain-text scrape target. Serve it
   behind an IP allowlist (Caddy's `remote_ip` matcher, or internal-
   only port) — counter values aren't secret but aren't meant to be
   public either.

```bash
# Spot check
curl -s http://localhost:8080/health | jq
# → {"status":"ok","version":"dev","deps":{"db":"ok","redis":"disabled"}}

curl -s http://localhost:8080/metrics | head
# # HELP scanner_http_requests_total Total HTTP requests served by the backend.
# # TYPE scanner_http_requests_total counter
# scanner_http_requests_total{method="GET",path="/health",status="200"} 4.0
# ...
```

Counters worth dashboarding day one:

| Metric | Why |
|---|---|
| `scanner_http_requests_total{status}` | Error rate (5xx / total) |
| `scanner_http_request_duration_seconds` | p95 / p99 latency per route |
| `scanner_scans_total{mode, outcome}` | Business signal — scans completed, failed, blocked |
| `scanner_auth_attempts_total{result}` | Spike in `bad_credentials` = possible brute-force |
| `scanner_ssrf_blocks_total` | Spike = someone poking at URL inputs |
| `scanner_quota_exceeded_total{plan}` | Product signal — upgrade pressure per tier |

**Sentry** is opt-in via `SENTRY_DSN`. Without it the SDK is never
imported. With it, only 5xx + unhandled exceptions ship (4xx are
caller errors and would bury real signal). A `before_send` scrubber
redacts Authorization + Cookie headers, request bodies (replaced with
a size marker), and any extra field whose name contains "password",
"token", "secret", or "api_key" before the event leaves the process.

## Running the tests

The test suite now covers scoring / consent-diff / form-analyzer /
auth / SSRF / rate limits / runtime SSRF guards / Phase-3 async jobs /
Phase-3b progress pub/sub + SSE / Phase-4 admin + audit / Phase-5a
billing + quotas / Phase-5b Mollie checkout + webhook + cancel /
Phase-7 observability / Phase-7c security.txt / Phase-8 retention
sweeps + GDPR Art. 17 self-deletion / Phase-9 EuGH Planet49
pre-checked consent detection / Phase-9c tracking-pixel beacon
detection / Phase-9d deterministic DSAR check (Art. 13(2)(b)) /
Phase-9e cookie-wall "Pay or Okay" detection (EDPB Opinion 8/2024)
with 397 unit + integration tests.
All tests are pure-Python (no Playwright, no network, no real DNS,
no real Redis, no real Mollie, no real Sentry) and complete in
under twenty-five seconds.

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
