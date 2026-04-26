# CLAUDE.md

Context for future Claude Code sessions on this repo. Read this first.

## What this project is

**MSA DataX GDPR Compliance Scanner** — a website audit SaaS. User enters a
URL; the system crawls the site with Playwright, captures every network
request, classifies cookies/trackers, runs the privacy policy through an LLM,
analyses forms for consent gaps, and produces a weighted risk score with
actionable recommendations and ready-to-paste policy drafts.

Currently a single-node dev tool, not yet a multi-tenant SaaS. See the
"Enterprise roadmap" section at the bottom for the path forward.

## Repo layout

```
.
├── backend/                    FastAPI + Playwright + OpenAI/Azure + SQLite/Postgres
│   ├── app/
│   │   ├── main.py             HTTP endpoints (/scan, /scan/stream, /scans)
│   │   ├── scanner.py          Orchestrator — owns Playwright lifecycle
│   │   ├── config.py           Pydantic Settings (.env driven)
│   │   ├── models.py           ALL Pydantic models. Update with frontend/lib/types.ts in lockstep.
│   │   ├── progress.py         SSE progress reporter (asyncio.Queue pub/sub)
│   │   ├── db.py               SQLAlchemy 2.0 async engine + session_scope (DATABASE_URL driven)
│   │   ├── db_models.py        ORM models — User, Organization, Membership, Scan
│   │   ├── storage.py          SQLAlchemy persistence — same code path for SQLite + Postgres
│   │   ├── auth.py             Password hashing (bcrypt) + JWT + get_current_user + require_superuser
│   │   ├── routers/auth.py     POST /auth/signup, POST /auth/login, GET /auth/me
│   │   ├── routers/admin.py    GET users/organizations/audit, POST promote/demote/reset-password
│   │   ├── audit.py            log_action helper — append-only AuditLog writes from admin paths
│   │   ├── cli/promote.py      `python -m app.cli.promote [--revoke] <email>` — bootstrap / revoke
│   │   ├── security/ssrf.py    validate_url_safe — blocks loopback/private/metadata at /scan
│   │   ├── security/rate_limit.py  Per-tenant + per-IP sliding-window (in-memory; swap to Redis when multi-worker)
│   │   ├── billing/plans.py    Hardcoded Plan catalogue (free / pro / business) — versioned in git
│   │   ├── billing/subscriptions.py  Quota + set_plan + get_subscription_summary
│   │   ├── billing/mollie.py   Async httpx wrapper around the 5 Mollie REST calls we use
│   │   ├── billing/checkout.py Checkout orchestration + webhook handler (Phase 5b)
│   │   ├── routers/billing.py  GET /billing/plans + /subscription · POST /checkout /cancel /webhook/{token}
│   │   ├── observability/logging.py  Request-ID ContextVar + JsonFormatter + configure_logging
│   │   ├── observability/metrics.py  Prometheus counters + /metrics renderer
│   │   ├── observability/sentry.py   Opt-in Sentry init with PII scrubber
│   │   ├── jobs.py             Arq enqueue helper — POST /scan/jobs calls enqueue_scan()
│   │   ├── worker.py           Arq WorkerSettings — run_scan_task + nightly retention_sweep_task cron
│   │   ├── retention.py        Pure helpers: purge_scans_older_than / purge_audit_older_than / purge_orphan_scans
│   │   ├── cli/retention.py    `python -m app.cli.retention [--dry-run]` for manual sweeps
│   │   ├── progress.py         ProgressReporter (asyncio.Queue) + RedisProgressReporter (drainer → pub/sub)
│   │   ├── progress_bus.py     publish_progress / subscribe_progress — Redis pub/sub wrapper for Phase 3b
│   │   └── modules/
│   │       ├── crawler.py              BFS crawl, emits per-page progress
│   │       ├── network_analyzer.py     Captures every request; offline country map
│   │       ├── cookie_scanner.py       Cookie + localStorage/sessionStorage classifier
│   │       ├── policy_extractor.py     Fetch + clean policy; probe_common_paths() fallback
│   │       ├── ai_analyzer.py          OpenAI / Azure OpenAI / NoOp abstraction
│   │       ├── consent_clicker.py      19 CMP selectors + multilingual text fallback
│   │       ├── consent_diff.py         Pre vs post-consent diff engine
│   │       ├── form_analyzer.py        Deterministic; owns PII_CATEGORIES (exported)
│   │       ├── scoring.py              5 sub-scores → hard caps → recommendations
│   │       └── performance/            Phase 11 — opt-in performance suite (Web Vitals + network + assets, linear no-cap score)
│   ├── alembic/                Migration scripts (env.py reads DATABASE_URL)
│   ├── alembic.ini
│   ├── Dockerfile              Production image — mcr.microsoft.com/playwright/python base
│   ├── docker-compose.yml      Local Postgres + Redis for the production code path
│   ├── run_dev.py              Entry point — pins Windows Proactor loop BEFORE uvicorn imports
│   ├── requirements.txt
│   └── .env.example
├── frontend/                   Next.js 14 App Router + Tailwind
│   ├── app/
│   │   ├── page.tsx            Whole single-page dashboard (gated by <RequireAuth>)
│   │   ├── login/page.tsx      Sign-in form
│   │   ├── signup/page.tsx     Sign-up form
│   │   ├── layout.tsx          MSA DataX branding, favicon, AuthProvider mount
│   │   ├── api/scan/route.ts           Batch proxy to backend /scan — forwards cookie→Bearer
│   │   ├── api/scan/stream/route.ts    SSE proxy — duplex:half, no buffering, Bearer forwarded
│   │   ├── api/scan/jobs/(...)         Async scan enqueue + status + events proxy (Phase 3c)
│   │   ├── api/scans/(...)             History endpoints proxy (auth-forwarded)
│   │   ├── api/admin/(...)             Admin endpoints proxy — forwards to /admin/* (Phase 4b)
│   │   ├── admin/page.tsx              /admin dashboard (Users · Orgs · Audit), gated by RequireAdmin
│   │   ├── api/billing/(...)           Billing endpoints proxy — plans/subscription/checkout/cancel (Phase 5c)
│   │   ├── billing/page.tsx            /billing — current plan + usage meter + upgrade / cancel UI
│   │   └── api/auth/(...)              signup / login / logout / me — owns the httpOnly cookie
│   ├── components/
│   │   ├── ui/                 Inlined shadcn-compatible primitives (button, card, badge, …)
│   │   ├── auth/               AuthProvider · RequireAuth · RequireAdmin · UserMenu
│   │   └── scan/               Domain components (RiskScoreCard, DataFlowTable, …)
│   ├── lib/
│   │   ├── types.ts            Hand-mirrored from backend/app/models.py — names MUST match
│   │   ├── api.ts              sync (streamScan) + async (streamScanAsync) + auto dispatch (streamScanAuto)
│   │   ├── auth.ts             Client-side signup / login / logout / fetchMe
│   │   ├── admin.ts            Client wrappers for /api/admin/* (listUsers, promoteUser, …)
│   │   ├── billing.ts          Client wrappers for /api/billing/* (getPlans, startCheckout, formatEuro)
│   │   ├── serverAuth.ts       Server-side cookie helpers (Next.js route handlers)
│   │   └── utils.ts            cn() + color helpers keyed to Tailwind `risk-*` palette
│   ├── public/logo.png         MSA DataX brand logo
│   ├── Dockerfile              Production image — multi-stage, Next.js standalone output
│   └── .env.local.example
├── deploy/
│   ├── Caddyfile               Production reverse proxy (Phase 6) — auto-TLS, sec headers
│   └── backup.sh               pg_dump rotation + optional GPG encrypt (Phase 7c)
├── docs/
│   ├── incident-response.md    On-call runbook + DSGVO Art. 33 72h timeline (Phase 7c)
│   ├── dpa-template.md         Art. 28 GDPR DPA template for customers (Phase 7c)
│   └── retention-policy.md     Per-data-class retention numbers (Phase 7c)
├── .github/workflows/
│   ├── ci.yml                  Tests + (on main) build + push to GHCR (Phase 7b)
│   └── deploy.yml              Manual SSH deploy — pin APP_VERSION, pull, up -d, health gate
├── docker-compose.prod.yml     Full production stack with pull-or-build image pointers
└── .env.production.example     Template for production .env
└── README.md
```

## Running locally (Windows)

Two terminals. Backend must be on **port 8080** (not 8000 — Windows reserves
some dynamic ports for Hyper-V/WSL).

```powershell
# Terminal 1 — backend
cd "D:\DSGVO Scanner Tool\backend"
.\.venv\Scripts\Activate.ps1
python run_dev.py                # http://localhost:8080

# Terminal 2 — frontend
cd "D:\DSGVO Scanner Tool\frontend"
npm run dev                      # http://localhost:3000
```

Health check: `GET http://localhost:8080/health` → `{"status":"ok"}`.

First-time setup:

```powershell
# Backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium

# Frontend
cd ../frontend
npm install
```

## Environment

- **`backend/.env`**: `OPENAI_API_KEY` or `AZURE_OPENAI_*`, `ALLOWED_ORIGINS`.
  Defaults in [backend/.env.example](backend/.env.example) are sensible for dev.
- **`frontend/.env.local`**: `NEXT_PUBLIC_BACKEND_URL=http://localhost:8080`.
  `NEXT_PUBLIC_*` vars are read at Next.js boot — restart `npm run dev` after
  changes.

Variable placement rule: `NEXT_PUBLIC_*` → `frontend/.env.local`. Everything
else → `backend/.env`.

## Critical conventions

**1. Never duplicate PII/compliance domain knowledge.**
- `PII_CATEGORIES` lives in [form_analyzer.py](backend/app/modules/form_analyzer.py)
  and is imported by scoring.py. Do NOT redefine locally — past bug.
- `_KNOWN_TRACKERS` lives in [network_analyzer.py](backend/app/modules/network_analyzer.py)
  and is imported by cookie_scanner.py.

**2. Model changes go in BOTH places.**
- Edit `backend/app/models.py` AND `frontend/lib/types.ts` in the same commit.
- Field names are identical on purpose — easier grep.

**3. Pre-consent pass is the source of truth for scoring.**
- Scanner runs one browser with 1 (or 2 with consent sim) contexts. The
  pre-consent state is legally relevant — never score against the post-consent
  "worse" state, that would punish sites that *correctly* gate trackers.
- Post-consent data lives under `ScanResponse.consent`, informational only.

**4. AI provider has three possible states.**
- `openai`, `azure`, `none`. `NoOpProvider` produces a neutral-50 privacy
  sub-score so scans still complete without keys.
- `privacy.error` starting with `"dropped "` is a **partial parse** —
  compliance_score is valid, don't zero it. Only true-fatal errors
  (non-JSON, schema mismatch, unhandled exception) defeat the score.
  This is enforced in `_score_privacy()`.

**5. AI suggested_text matches policy language.**
- If the policy is German, the auto-fix draft is German. Enforced in the
  system prompt. The `summary` field is always English.

**6. Disclaimer for AI-generated policy text lives in the UI, not the model.**
- `SuggestedTextBlock` in PrivacyAnalysisCard.tsx wraps every draft with an
  unmissable "legal review required" warning. The model must NOT be asked to
  include this — it could drop or paraphrase it.

**7. Offline country classification.**
- We do NOT call ipapi / ipgeo / any third-party geolocation API. Doing so
  during a GDPR audit would itself be a cross-border transfer. Curated
  tracker map + EU/EEA ccTLD fallback + honest `Unknown`.

**8. Value masking everywhere.**
- Cookie values, storage values, form inputs: masked prefix/suffix + length.
  JWT-shaped values become literal `<jwt>`. No PII ever persists.

**9. Deterministic beats AI when structure is regular.**
- Form analysis is regex-based, not LLM. ~5s per scan saved, reproducible
  results. Reserve AI budget for privacy policy language analysis.

**10. Form purpose classification.**
- `purpose: collection | search | authentication | unknown`. Search forms
  (GET + ≤2 fields + search-like field name) do NOT generate PII consent
  issues. Recommendations filter on `purpose == "collection"` — do NOT
  grep issue strings (past bug where "no consent checkbox" in negated text
  matched the filter).
- The pre-checked-consent issue (Phase 9) is the ONE form-issue that
  fires regardless of purpose — Planet49 applies wherever consent is
  the legal basis. Convention #28 spells out the heuristic.

**11. Auth token lives in an httpOnly cookie, never in JS.**
- The client NEVER sees the JWT. `/api/auth/{signup,login}` strip the
  `access_token` field from the backend response and write it to an
  `msadatax_auth` cookie (httpOnly, SameSite=Lax, Secure in prod).
- Every `/api/*` route handler in `frontend/app/api/` reads the cookie
  via `authHeaderFromCookie()` and forwards it as `Authorization: Bearer
  <token>` to FastAPI. Do NOT try to read `document.cookie` — it's not
  readable anyway, and the client libraries in `lib/api.ts` rely on the
  proxy to do the work.
- On logout, `/api/auth/logout` clears the cookie. The JWT itself is
  stateless so it keeps validating until TTL; the cookie-clear is what
  stops the browser from sending it. A future refresh-token flow adds
  server-side revocation.

**12. Every scan read/write is scoped by `organization_id`.**
- `AuthedUser.organization_id` is resolved in `get_current_user` from the
  user's oldest membership. Handlers MUST pass it to the storage layer:
  `save_scan(result, organization_id=...)`, `list_scans(organization_id,
  limit)`, `get_scan(id, organization_id)`, `delete_scan(id,
  organization_id)`. No "admin bypass" function exists; if you need one
  later, add a distinct function with a distinct name and test.
- Cross-tenant access returns `None` / empty list / `False`, which HTTP
  handlers translate to plain 404 — same as "ID doesn't exist". This is
  deliberate: leaking existence (403 vs 404) tells an attacker they hit
  a real scan ID belonging to someone else.
- `tests/test_auth.py::TestTenantIsolation` guards the invariant. When
  adding a new scan endpoint, add a test that asserts cross-tenant 404.

**13. SSRF validation happens at THREE layers.**
- **Entry** (`/scan`, `/scan/stream` in `main.py`): `validate_url_safe`
  rejects `file://` / `javascript:` etc, IP literals in private /
  loopback / link-local / multicast, and DNS hostnames that resolve
  there (iterated — `[public, private]` still loses).
- **Browser** (`scanner._install_ssrf_guard` via `context.route`):
  every request the browser makes — initial nav, 3xx follow-ups,
  subresources — is re-validated. Per-hostname cache so the same-host
  requests in a single scan only pay one DNS check. Data / blob / etc
  are passed through.
- **httpx** (`policy_extractor._safe_fetch_follow`): redirect chains
  are walked manually with `follow_redirects=False`. Each `Location`
  is validated before the next request, and the chain is capped at a
  small number of hops to kill pathological loops.
- What's still NOT covered: DNS rebinding (host resolves public at
  validation time, private at fetch time). Requires pinning the
  resolved IP in the transport — bigger change. Production should also
  have a network-layer control (egress firewall / NetworkPolicy).
- Metadata hostnames (`169.254.169.254`, `metadata.google.internal`)
  are in the blocklist by name even though the IP ranges catch them too.

**14. Rate limits are per-tenant (scans) and per-IP (auth).**
- `scan_rate_limiter.check(f"scan:{org_id}")` on `/scan` + `/scan/stream`.
  Default 3/min + 50/day. Checked AFTER SSRF so 400s don't burn budget.
- `auth_rate_limiter.check(f"auth:{client_ip}")` on `/auth/signup` +
  `/auth/login`. Default 5/min + 50/day. Signup and login share the
  bucket so an attacker can't rotate endpoints. Use `client_ip(request)`
  helper — it honours the leftmost `X-Forwarded-For` hop (trust a
  single proxy).
- Both are in-memory singletons. When moving to multiple workers
  (Phase 3), swap the internal dict for Redis; the public API stays
  identical. Tests reset both in the `app_with_db` fixture to isolate
  cases. 429s include `Retry-After` so clients back off.

**15. Sync mode and async mode both exist — different endpoints.**
- **Sync**: `POST /scan` and `POST /scan/stream` run the Playwright
  scan inline on the HTTP worker. Default deploy; no Redis needed.
  This is what the frontend uses today.
- **Async**: `POST /scan/jobs` creates a row in `queued` status via
  `create_pending_scan`, calls `enqueue_scan`, and returns 202 +
  `scan_id`. A separate `arq app.worker.WorkerSettings` process pops
  the job, calls `run_scan`, and updates the row through `mark_running`
  → `mark_done` / `mark_failed`. The frontend polls `GET /scan/jobs/{id}`
  for the result.
- Only enable async mode by setting `REDIS_URL`. `/scan/jobs` returns
  503 otherwise so the operator can't forget to start the worker.
- `list_scans` filters `status="done"` so queued/running placeholders
  (score=0 rating="critical") never appear in the history UI.
- Every write path — sync save_scan, create_pending_scan, mark_done —
  stamps `organization_id`. Cross-tenant reads still 404 (convention #12).

**16. Async-mode progress lives in Redis pub/sub (channel per scan).**
- Worker builds a `RedisProgressReporter(pool, scan_id)`, passes it to
  `run_scan(req, progress=reporter)`. Each `reporter.emit` queues
  locally; a background drainer publishes to channel
  `scan:progress:{scan_id}` preserving order. Worker publishes a final
  `stage="done"` / `stage="error"` event directly (bypassing the
  drainer) AFTER `mark_done` / `mark_failed` so subscribers always see
  a terminal event even if the scanner crashed mid-emit.
- `GET /scan/jobs/{id}/events` subscribes to that channel, re-checks
  DB status after subscribing (race-free: if the scan finished
  between the initial status check and subscribe, the re-check catches
  it and emits a snapshot + closes). Closes on receiving a terminal
  event.
- Events are ephemeral. The authoritative state is the Scan DB row;
  the stream is purely progress UX. A client that reconnects mid-scan
  gets the current DB state via the snapshot path and the rest via
  fresh subscriptions.
- Tests never touch real Redis: `tests/test_progress_bus.py` pairs a
  `_FakePool` with a `_FakePubSub` that routes publishes to in-memory
  queues, matching the real API surface we actually call.

**17. Frontend scan mode is a build-time env var, default sync.**
- `lib/api.ts` exports `streamScan` (sync path, inline SSE via
  `/api/scan/stream`) AND `streamScanAsync` (enqueue → SSE events →
  fetch result, via `/api/scan/jobs*`). `streamScanAuto` reads
  `NEXT_PUBLIC_SCAN_MODE` at build/boot and dispatches.
- `app/page.tsx` only ever calls `streamScanAuto` — the UI doesn't
  know which mode it's in. Switching modes is a one-line env change
  + rebuild.
- Unset / `"sync"` → behaves exactly like before Phase 3. `"async"`
  needs `REDIS_URL` + a running `arq app.worker.WorkerSettings`
  process; without those the enqueue call 503s and the UI surfaces it
  via `handlers.onError`.
- Both modes share `StreamHandlers` (onProgress / onResult / onError)
  so component code (ScanProgress, RiskScoreCard, …) is mode-agnostic.

**18. System-wide admin is a separate privilege, not a tenant role.**
- `User.is_superuser` is distinct from `Membership.role`. Owner-of-an-
  org is tenant-level; superuser is platform-level. Normal
  `get_current_user` ignores the flag; `/admin/*` sits behind
  `require_superuser` which 403s authenticated-but-not-admin callers
  (vs 404 that scan endpoints use — see #12). The distinction is
  intentional: "I know who you are, you can't do this" is the
  meaningful signal for an auditor reviewing access logs.
- First superuser is granted out-of-band via
  `python -m app.cli.promote <email>`. There is deliberately no HTTP
  path to bootstrap — someone has to own the server. CLI promotions
  also write an audit row (with a null `actor_user_id`), so even the
  first administrative action is traceable.
- Every admin mutation calls `app.audit.log_action(...)` after the
  guarded operation. `details` must be small and PII-free (field
  names, NOT plaintext secrets / scan payloads). A failure in the
  audit insert is logged but does not roll back the privileged op —
  the user-visible action is the contract we honour first.
- Self-demote is blocked at the HTTP layer (would lock the system
  out). Use the CLI with `--revoke` if that's genuinely wanted.
- `DELETE /admin/users/{id}` does NOT exist yet — deleting a user
  who is the last owner of an org is a design question (org
  deletion? membership reassignment?) we haven't answered.

**19. Plans are hardcoded, quotas reset on the 1st of each month.**
- Plan catalogue (`free` / `pro` / `business`) lives in
  [app/billing/plans.py](backend/app/billing/plans.py) — NOT in the DB.
  Price + quota changes ship as code changes so a runtime misconfig
  can't silently downgrade a paying customer. Phase 5b will add a
  `mollie_price_id` per plan; stays in the same module.
- `Subscription` row is absent for free-tier orgs. Absence ≡ free.
  When someone upgrades the row is inserted with `plan_code="pro"`.
  Only ONE subscription per org (organization_id is the PK).
- Quota window = first-of-current-month UTC. No pro-rata, no trial,
  no rollover. Phase 5b swaps this for Mollie's period boundaries on
  a per-subscription basis (`current_period_start` column already
  exists for that handoff).
- `check_scan_quota(org_id)` is called from all three scan entry
  points (/scan, /scan/stream, /scan/jobs) AFTER SSRF + rate-limit.
  Order matters: a 402 must mean "you used your allowance", never
  "you tried to SSRF us" (400) or "you spammed us" (429). Over-quota
  raises 402 Payment Required with a structured detail payload
  (`plan`, `scans_used`, `scans_quota`).
- Admin endpoint `POST /admin/organizations/{id}/set-plan` is the
  manual override. Every invocation writes
  `action="organization.set_plan"` to the audit log with the chosen
  plan_code in `details` — same rules as convention #18. Mollie's
  webhook handler (Phase 5b) calls the same `set_plan` helper.

**20. Mollie billing is opt-in via three env vars; graceful 503 otherwise.**
- `MOLLIE_API_KEY`, `APP_BASE_URL`, `MOLLIE_WEBHOOK_TOKEN` must ALL
  be set. Missing any → `/billing/checkout`, `/billing/cancel`, and
  `/billing/webhook/{token}` all return 503. Phase 5a (admin-assigned
  plans) still works in that mode — good for dev boxes.
- Webhook authentication is a random URL-path token + constant-time
  compare + refetch-from-Mollie. Mollie does not sign webhooks, so
  the path token IS the shared secret. Rotate it alongside the API
  key. Wrong token → 404 (not 403) so probers can't distinguish
  "no such endpoint" from "wrong token".
- Checkout flow mirrors Mollie's mandate pattern: create Customer →
  first-payment (sequenceType=first, full plan price) → on webhook
  `payment.paid` → create recurring Subscription. The row is parked
  with `status="past_due"` between checkout and first-payment-settled
  so quota enforcement doesn't let the user scan before they've paid.
- The webhook handler is idempotent on every branch — Mollie retries
  any non-2xx and occasionally double-delivers on flaky networks.
  Marker: a second `payment.paid` delivery sees
  `mollie_subscription_id` already populated and skips
  `create_subscription`; the `create_subscription` call count is
  the test invariant.
- Cancel is Mollie-side + DB-side: we call
  `DELETE /customers/{cid}/subscriptions/{sid}` and set
  `status="canceled"`. The user keeps their plan until
  `current_period_end` — we don't downgrade on cancel since they
  paid for this month. Period-end downgrade is future cron work.
- `MollieClient` is a Protocol, not a base class. Tests inject a
  `_FakeMollieClient` via `set_mollie_client_for_tests(...)`. Real
  Mollie API is never hit in tests.

**21. Production deploy is a single-host Docker Compose stack.**
- One Dockerfile per service folder (`backend/Dockerfile`,
  `frontend/Dockerfile`); the worker reuses the backend image with a
  different `command:`. That keeps migrations + scan logic bit-
  identical between HTTP and job-consumer paths.
- `docker-compose.prod.yml` wires postgres + redis + backend + worker
  + frontend + caddy. Two networks: `internal` (db / cache / app —
  marked `internal: true`, no host bridge) and `web` (caddy + the
  services caddy proxies to). The DB is unreachable from outside the
  host by construction.
- Caddy handles TLS (auto Let's Encrypt), HSTS, static-asset encoding,
  security headers. `deploy/Caddyfile` routes `/billing/webhook/*`
  straight to the backend (Mollie can't send cookies) and everything
  else to the Next.js frontend, which in turn proxies `/api/*` to the
  backend via service-name DNS. Same-origin-only for the FastAPI is
  the default — one less class of CSRF / token-in-URL bug.
- Backend's default CMD runs `alembic upgrade head` before uvicorn.
  A fresh VM boots into a migrated schema with zero manual steps.
  Worker depends on `backend` being healthy, so the worker never
  hits un-migrated tables.
- First superuser promotion happens via
  `docker compose exec backend python -m app.cli.promote …` — there
  is STILL no HTTP bootstrap (convention #18).
- The production compose file is the seam for horizontal scale:
  swap Postgres for a managed EU RDS, add a second host behind an
  external LB, push images to a registry instead of building in
  place. All additive — none of the app code changes.

**22. Observability is opt-in and PII-aware.**
- Structured logging: one middleware generates / reuses an
  ``X-Request-ID`` per request and stashes it on a ``ContextVar``.
  Every log record picks it up via ``RequestIdFilter`` so a single
  request is traceable across async tasks without threading a param.
  `LOG_FORMAT=json` emits one JSON line per record (Loki / CloudWatch
  ready); `LOG_FORMAT=text` keeps the dev terminal readable.
- Prometheus at `/metrics` — text format, scraped by a sidecar or
  external Prometheus. Metrics are **in-memory per process** for now.
  Multi-worker deploys want `prometheus_client.multiprocess` with a
  shared tmpfs; the counter API stays identical, so the swap is
  additive. Serve `/metrics` behind an IP allowlist on the reverse
  proxy — the counter values aren't secret but shouldn't be public.
- Route labels use the **FastAPI route template**
  (`/scans/{scan_id}`) not the concrete URL. Otherwise every scan id
  becomes its own series and Prometheus melts. ``normalise_path``
  enforces this.
- Sentry is opt-in via ``SENTRY_DSN``. Without it the SDK is not
  imported. With it, only 5xx + unhandled exceptions ship — 4xx are
  caller errors and would bury real signal. ``before_send`` scrubs
  Authorization + Cookie headers, replaces request bodies with a
  size marker, and redacts any extra with "password" / "token" /
  "secret" / "api_key" in its key name.
- `/health` now probes DB + Redis. Returns ``status="ok"`` only when
  DB is reachable AND Redis is either ``"ok"`` or explicitly
  ``"disabled"`` (no ``REDIS_URL``). Orchestrators read the top-level
  `status`; humans read `deps`.
- Domain counters live in ``app.observability.metrics`` as module-
  level globals. Callers in HTTP handlers increment directly — the
  low-level security/billing modules stay dep-free so they can be
  unit-tested without the metrics registry.

**23. CI builds + pushes images on main; deploy is manual.**
- `.github/workflows/ci.yml` runs pytest + frontend lint/typecheck on
  every push + PR. On `main` only, it also builds `backend` and
  `frontend` images via `docker/build-push-action@v6` with GHA layer
  cache + matrix parallelism, and pushes to GHCR with two tags:
  `latest` (moving pointer) and the 12-char SHA (deterministic
  rollback anchor).
- `.github/workflows/deploy.yml` is `workflow_dispatch` only. It
  SSHes to the production VM (secrets: `DEPLOY_SSH_KEY`,
  `DEPLOY_HOST`, `DEPLOY_PATH`), overwrites the `APP_VERSION=` line
  in the server's `.env`, runs `docker compose pull && up -d`, then
  waits for `/health` to go green before exiting. `concurrency:
  group: deploy-prod, cancel-in-progress: false` means overlapping
  deploys queue instead of racing.
- No auto-deploy on push. Explicit button-click with a version input
  is the lowest-regret default — prevents a green-main + manual-
  migration combo from being deployed accidentally.
- `docker-compose.prod.yml` uses `image: ${IMAGE_REGISTRY}-backend:${APP_VERSION}`
  with `build:` as fallback. Server deploys pull; dev still works with
  `docker compose up --build`. One file, two modes.
- Rollback = same deploy workflow, older SHA typed in the input.
  Images stay in GHCR indefinitely unless someone prunes them.

**24. Compliance artefacts are shipped in the repo, not generated.**
- `/.well-known/security.txt` is served from the backend router
  `app/routers/well_known.py`, NOT as a static file from Caddy. It
  reads `SECURITY_CONTACT_EMAIL` + `SECURITY_POLICY_URL` +
  `SECURITY_TXT_EXPIRES` + `SECURITY_ACKNOWLEDGMENTS_URL` + the
  shared `APP_BASE_URL`. Default-fallback Expires is boot + 365d so
  the file stays RFC 9116-valid even when the operator forgets.
- DPA, incident runbook, retention policy all live in
  [docs/](docs/) in Markdown — versioned with the code. Any customer
  asking for a DPA gets the current `main` revision filled in with
  their deal-specific placeholders. Legal review still required
  before signature.
- `deploy/backup.sh` is the one-true backup path. `docker compose
  exec postgres pg_dump` on an ad-hoc basis is fine for an incident
  evidence grab; nightly cron must call the script so rotation +
  optional GPG run consistently.
- Retention numbers in `docs/retention-policy.md` are AUTHORITATIVE —
  scan rows 12 months, audit log 3 years, DB backups 30 daily + 12
  monthly. When a new data class is added, update that file AND
  implement the enforcement (Phase 8 work for automatic pruning).
- Nothing in this convention produces a SOC 2 certificate — that's
  a 6-month audit with a vendor like Drata. These artefacts are the
  80% of evidence the auditor asks for; the remaining 20% is log
  preservation over the observation period.

**25. Retention is enforced by an Arq cron, plus a CLI for ops.**
- `app/retention.py` is the single source of truth: pure async
  functions `purge_scans_older_than(months=12)`,
  `purge_audit_older_than(years=3)`, `purge_orphan_scans()`. Numbers
  default to whatever `docs/retention-policy.md` says.
- `WorkerSettings.cron_jobs` includes a daily 03:30 UTC firing of
  `retention_sweep_task` — Arq distributes cron across worker
  instances so only ONE worker runs each firing even at scale.
- `python -m app.cli.retention --dry-run` for "how many rows would
  this delete?" inspections. `--scan-months` / `--audit-years`
  override defaults for one-off sweeps after a policy tightening.
- The retention helpers are the ONE app-layer code path that
  DELETEs from `audit_logs`. Convention #18 says audit is append-
  only from the app — this is the documented exception, guarded by
  the cron schedule. A new HTTP path that mutates audit_logs
  requires updating both #18 and this convention.

**26. Account self-deletion (Art. 17) cascades carefully.**
- `DELETE /auth/me` resolves the user's "sole-owner" org list, tries
  to cancel each org's Mollie subscription (best-effort — billing
  API outage MUST NOT block a GDPR right), audit-logs
  `user.self_delete`, then deletes the orgs (CASCADE drops their
  scans, memberships, subscription) and finally the user (CASCADE
  drops the remaining co-owner memberships).
- Audit rows survive: `audit_logs.actor_user_id` has
  `ON DELETE SET NULL`, so historical actions still read with the
  denormalised `actor_email` column.
- The mollie-cancel counter only ticks when
  `cancel_org_subscription` returns `status="canceled"` — orgs that
  never had a paid subscription return `status="no_active_subscription"`,
  not an error, and don't count.
- The user's JWT stays cryptographically valid until TTL after
  deletion; the frontend is expected to follow up with
  `/api/auth/logout` to clear the cookie. Subsequent requests 401
  anyway because `get_current_user` can't find the user row.

**27. SQLite needs `PRAGMA foreign_keys=ON` per connection.**
- SQLite ships with FK enforcement OFF. Without the PRAGMA,
  declared `ON DELETE CASCADE` / `SET NULL` are no-ops on dev/tests,
  while Postgres in production enforces them. That divergence hides
  bugs until production sees an Art. 17 erasure request.
- `app.db.install_sqlite_fk_pragma(engine)` registers a
  `connect`-event listener that runs the PRAGMA on every new
  connection. The module-level production engine wires it
  automatically; every test fixture that builds a fresh in-memory
  engine MUST also call it (search the test files for
  `install_sqlite_fk_pragma` — there's a copy in each `app_with_db`
  fixture).
- Consequence: a multi-row insert spanning a parent + child
  relationship needs an explicit `await session.flush()` between
  the parent and the child. SQLAlchemy's unit-of-work topo-sorts
  by declared `relationship()`, NOT by raw FK columns. The signup
  handler in `routers/auth.py` is the canonical example.

**28. Pre-checked consent boxes are detected via two-part heuristic.**
- Crawler reads HTML `checked` attribute → `FormField.is_pre_checked`
  (per-field) + `FormInfo.has_pre_checked_box` (form-level OR).
- `form_analyzer._has_pre_checked_consent(form)` requires BOTH:
  (a) any pre-ticked checkbox AND (b) the form's text_content
  contains a token from `_CONSENT_VOCAB` (DE: `einwilligung`,
  `einverstanden`, `newsletter`, `zustimm`…; EN: `consent`,
  `agree`, `subscribe`…). Without (b) we'd false-positive on
  benign pre-ticks like "Remember me" or "Show advanced options".
- A hit fires `pre_checked_consent_box` hard cap at 40 — same
  severity tier as `us_marketing_no_consent`. Settled CJEU case
  law (Planet49 / C-673/17, 2019); German DPAs cite it as a
  baseline finding.
- Recommendation cites the case + Art. 7(2) DSGVO + tells the
  auditor to manually verify when the affected box might be a
  non-consent purpose.

**29. Tracking pixels get their own detection separate from generic trackers.**
- `NetworkRequest.is_tracking_pixel` is set at request-emit time
  by `network_analyzer.is_tracking_pixel()` — pure function, no
  await on response body. Two rule families:
  (1) Meta-specific: `registered_domain == "facebook.com"` AND path
  is exactly `/tr` or starts with `/tr/`.
  (2) Generic: third-party image resource whose path contains one
  of `_PIXEL_GENERIC_PATH_TOKENS` (`/pixel`, `/beacon`,
  `/conversion`, `/__utm.gif`, `/1x1.gif`, `/clear.gif`,
  `/blank.gif`, `/spacer.gif`).
- Resource type MUST be `"image"` for the generic rule —
  `connect.facebook.net/.../fbevents.js` is the loader script, not
  a pixel hit. Counting both would double-flag the same event.
- Known precision gap (pinned in tests): the generic-token check
  uses `in path`, so `/pixelart/foo.gif` matches `/pixel`. Documented
  rather than silently fixed because the false-positive cost in
  practice is "auditor checks one extra URL". Tighten when we have
  evidence it matters.
- No new hard cap — existing `tdddg_non_essential_without_consent`
  (50) already catches pre-consent pixel loads. The pixel-specific
  recommendation gives the auditor a concrete remediation
  (Conversions API / Measurement Protocol server-side events)
  separate from the generic "block the script" advice.

**30. DSAR detection is deterministic — works without an AI provider.**
- `app/modules/dsar_detector.py` matches eight canonical Art. 15-22 +
  Art. 7(3) + Art. 77 rights against the raw policy text via DE + EN
  vocabulary. Output lands on `PrivacyAnalysis.dsar` (a `DsarCheck`).
- The detector runs from `scanner.py` AFTER `_run_ai_analysis`, even
  when the AI provider is `none`. That's the value:
  `PolicyTopicCoverage.user_rights_enumerated` is absent without AI,
  but the deterministic check still produces signal.
- Phrasing precision matters: `"complaint"` alone is too generic
  (customer-service contexts), so the detector pairs it with a
  supervisory-authority token (`aufsichtsbehörde` / `supervisory
  authority` / `data protection authority`). Same trick for
  withdrawal — `"einwilligung"` alone wouldn't match; only the
  paired phrasings `"widerruf der einwilligung"` /
  `"einwilligung widerrufen"` fire.
- Whitespace is normalised (`\s+ → " "`) before substring matching
  so a multi-line "the right to withdraw\nconsent" still hits.
- Cap `policy_missing_user_rights` (55) fires when `has_policy=True`
  AND `privacy.dsar is not None` AND `len(named_rights) == 0`.
  Same severity tier as `no_legal_basis_stated` — both are Art. 13
  enumeration failures, both produce DPA findings.
- Recommendation cites Art. 13(2)(b), points German operators at the
  DSK template, and lists the eight rights so the reader knows what
  the auditor expects to see.

**31. Cookie-wall ("Pay or Okay") detection runs on captured banner text.**
- `app/modules/cookie_wall_detector.py` is a pure function: text in,
  optional `DarkPatternFinding` out. Two-part conjunction — the banner
  must contain BOTH an accept token (`accept all`, `alle akzeptieren`,
  …) AND a pay/subscribe token (`pur abo`, `werbefrei abonnieren`,
  `subscribe to remove ads`, `pay or okay`, …). Either alone is not a
  cookie wall.
- `consent_ux_audit.audit_consent_ux` captures up to 2000 chars of
  banner text via a small `page.evaluate(...)` that walks up from the
  accept button to a "container-shaped" ancestor (`role=dialog`,
  class/id matching `cookie|consent|banner|cmp|privacy|gdpr`, or 8
  levels up). Stored on `ConsentUxAudit.banner_text` so the dashboard
  can show it.
- The detector gets called from inside `audit_consent_ux` and appends
  to the same `findings` list. NO new hard cap — the existing
  `consent_dark_pattern_high` (45) already trips on any HIGH-severity
  finding, including this one. We add a SPECIFIC bilingual
  recommendation in `scoring.py`'s `code_details` map that cites EDPB
  Opinion 8/2024 (April 2024) and tells the operator the fix path is
  a third no-tracking option (contextual ads / first-party-only).
- Same "verify manually" caveat as Phase 9 + 9c: a banner that links
  to an unrelated premium tier (not a tracking opt-out) will false-
  positive. The recommendation says so. False-positive cost is
  acceptable for a deterministic, no-AI signal.

**32. Google Fonts (LG München I 2022) detection is structured, not boolean.**
- `app/modules/google_fonts_detector.py` is a pure function over a
  `NetworkResult`: returns a `GoogleFontsCheck` with `detected` plus
  *which families*, *how many binary downloads*, *which initiator
  pages*, and up to three *css_url_samples*. The pre-Phase-10 version
  was a one-line bool helper inside `scoring.py` — gone now. Anything
  that needs the signal reads `network.google_fonts.detected`.
- Two hostnames in scope: `fonts.googleapis.com` (CSS) and
  `fonts.gstatic.com` (binaries). Adobe Fonts (`use.typekit.net`) and
  Bunny Fonts (`fonts.bunny.net`) deliberately do NOT trigger — Bunny
  is the EU-hosted mirror German DPAs explicitly bless as remediation,
  and Adobe is a separate compliance question.
- Family parsing handles all four URL shapes seen in the wild:
  `?family=Roboto`, `?family=Roboto:300,400` (weight stripped),
  `?family=Roboto|Open+Sans` (legacy pipe + `+`-encoded space),
  `/css2?family=Roboto:wght@400;700` (v2 axis syntax). Stable
  insertion order (first-seen) so the dashboard renders deterministic.
- Cap `google_fonts_external` is 55 (Phase-10 tightening from the
  earlier 65), aligned with `policy_missing_user_rights` /
  `no_legal_basis_stated` — same Art. 13 / Art. 44 ff. tier of
  routine DPA finding. The recommendation cites LG München I 3 O
  17493/20 (20.01.2022) + the €100 damages award and stitches the
  detected family list into the prose so the auditor sees concrete
  remediation targets without opening the raw network panel.
- Detector runs on the **pre-consent** network capture in
  `scanner.py` (after security audit, before vuln-libs scan). Loading
  Google Fonts *post*-consent is a separate question this module does
  not address.
- `network.google_fonts` is a Pydantic field with a default-empty
  `GoogleFontsCheck()` so callers / fixtures that don't run the
  detector still produce valid responses. Test fixtures that want
  the cap to fire MUST call `detect_google_fonts(net)` and assign
  the result — the scoring layer no longer re-walks `network.requests`.

**33. Performance suite is opt-in and KEPT SEPARATE from the GDPR risk score.**
- `app/modules/performance/` is a subpackage with four files:
  `web_vitals.py` (PerformanceObserver injection + harvest),
  `network_metrics.py` (pure: total bytes / type breakdown / render-
  blocking detection), `asset_audit.py` (pure: oversized images +
  scripts + uncompressed text responses), `scoring.py` (linear,
  weighted, capped-at-80-deductions). Orchestrator `audit.py` wraps
  them and never raises into the scanner.
- Gating: `ScanRequest.performance_audit: bool = False`. When false,
  `ScanResponse.performance` is None — zero overhead on the GDPR
  path. When true, the scanner installs the Web Vitals observer on
  the pre-context BEFORE any page is opened (`add_init_script`
  on the BrowserContext, so all subsequent pages auto-arm), then
  AFTER the crawl opens a dedicated harvest page on the homepage,
  waits ~3s, and reads `window.__msaWebVitals`.
- The score is **linear 0-100, no hard caps**, deliberately. Every
  point is traceable via `score_breakdown: dict[str, int]` (e.g.
  `{"lcp": -8, "render_blocking": -4, "uncompressed_responses": -3}`).
  Max deductions sum to 80, so a worst-case site shows 20/100 — never
  zero. Cross-contamination with the GDPR score would dilute both
  reports' meaning; performance never affects `risk.score`.
- Render-blocking detection uses a heuristic on the request side
  (resource_type ∈ {"script","stylesheet"} + status 200/304 +
  not in `_ASYNC_BY_DEFAULT_HOSTS`). Browser's authoritative
  `renderBlockingStatus` would need a per-page evaluate — too much
  for v1. Documented false-positive ~10-15% (e.g. `media="print"`
  stylesheets get flagged); the dashboard renders the URL list so
  the auditor can spot-check.
- `NetworkRequest` carries two Phase-11 fields populated by the
  network_analyzer's response listener: `response_size` (from
  Content-Length header — None when missing, e.g. chunked transfer)
  and `content_encoding` (verbatim header). Asset audit treats
  `response_size=None` as "skip the asset rather than guess".
- INP is approximated via the Long-Tasks API ("longest single
  main-thread block in the wait window") because real INP requires
  user interaction that doesn't happen in headless crawl. The
  WebVitals model documents this; the recommendation prose does
  not call it INP directly to avoid misleading customers.
- The web_vitals collector is NOT covered by unit tests — it
  needs a real Playwright page or a heavy mock. Pure functions
  (network_metrics, asset_audit, scoring, audit orchestrator) ARE
  fully covered (31 tests in `test_performance.py`). Document this
  gap rather than hide it.

## Known quirks / gotchas

- **Python 3.9 + Pydantic v2 + `X | None` syntax** needs
  `eval_type_backport` package (already in requirements.txt) + `from __future__
  import annotations` in all model files. Don't use `X | Y` as a runtime
  expression — only as type annotations. Regression will crash at import.
- **Windows + Playwright + asyncio** requires `WindowsProactorEventLoopPolicy`
  set BEFORE uvicorn imports. `run_dev.py` handles this; if someone tries to
  run `uvicorn app.main:app` directly on Windows it will hit `NotImplementedError`.
  See comment at the top of `run_dev.py`.
- **Playwright reload on Windows**: avoid `--reload` in uvicorn. The reload
  subprocess may not inherit the loop policy. `run_dev.py` uses `reload=False`
  intentionally — restart manually.
- **SSE proxy** in `app/api/scan/stream/route.ts` needs `duplex: "half"` for
  Node fetch (types lag behind, `@ts-expect-error` is intentional), plus
  explicit `cache-control: no-cache, no-transform` + `X-Accel-Buffering: no`
  headers or intermediate proxies will buffer the whole scan into one lump.
- **Hard caps don't stack** — the lowest `cap_value` wins. When adding new
  caps, think about overlap with existing ones (e.g. `us_marketing_no_consent`
  at 40 vs. new `tdddg_non_essential_without_consent` at 50; the stricter one
  takes precedence, both are still listed to show both legal arguments).
- **Frontend `.env.local` changes require `npm run dev` restart** — Next.js
  inlines `NEXT_PUBLIC_*` at build/dev-boot, not per-request.

## Testing

No automated tests yet. Manual verification is via the dashboard after a real
scan. Worth adding before Enterprise Stage 1 — see roadmap.

High-leverage targets when someone starts writing tests:
1. `scoring.py` — pure function, lots of branches, easy to unit test
2. `consent_diff.py` — pure function, clear inputs/outputs
3. `form_analyzer.py` — regex-heavy, needs coverage against edge-case form HTML
4. AI analyzer mock: assert prompt includes data_flow evidence block

## Git notes

- Branch: `main` (only branch so far)
- Backend ignores: `scans.db`, `.venv`, `__pycache__`, `.env` (see
  `backend/.gitignore`)
- Frontend ignores: standard Next.js `.gitignore`
- **Do not commit**: `backend/scans.db` (contains real scanned-site data),
  `backend/.env` (contains API keys), `node_modules`, `.venv`.
- No CI yet. Adding GitHub Actions for lint + typecheck + (eventual) tests is
  part of Enterprise Stage 1.

## Pipeline overview

```
POST /scan or /scan/stream
    │
    ▼
One Playwright BrowserContext (or two, with consent simulation)
    │   pre-pass:  no banner interaction → legally relevant state
    │   post-pass: click "Accept all" → informational diff
    │
    ├── crawler.py                BFS + per-page storage snapshot + progress events
    ├── network_analyzer.py       attached listeners, classifies country/risk offline
    ├── cookie_scanner.py         live cookie jar + classified storage
    └── policy_extractor.py       manual URL > crawl-discovered > probe_common_paths
    │
    ▼
ai_analyzer.py  (OpenAI / Azure / NoOp) — cross-checks policy vs. data_flow
form_analyzer.py (deterministic, purpose-aware)
scoring.py (sub-scores × weights → hard caps → recommendations)
    │
    ▼
Persist to scans.db via storage.py, return merged ScanResponse
```

## Enterprise roadmap (high level)

Currently single-tenant dev tool. Stages to enterprise, in order:

1. **Production-ready** — Postgres, Celery/RQ, Docker, CI, Sentry, PDF export
2. **SaaS MVP** — Multi-tenant, Stripe, API tokens, scheduled scans, webhooks
3. **Enterprise-ready** — SSO (SAML+OIDC via WorkOS), RBAC, audit logs, DPA,
   EU-region guarantee, white-label
4. **Enterprise-mature** — SOC 2 Type II, pen tests, multi-region, SLAs

The three deal-sealers at enterprise are: **SSO + DPA + SOC 2**. Everything
else is nice-to-have. Full rationale and sequencing: ask user for context —
this was discussed in chat and not captured in a separate doc yet.

## Memory location (for Claude Code sessions)

User-scoped memory for this repo:
`C:\Users\Moussa\.claude\projects\d--DSGVO-Scanner-Tool\memory\`

Current memories: one feedback entry saying "don't pause for step
confirmations in multi-step plans — run them through end-to-end, announce
each step but don't block for user 'ja' between them". Honor it.
