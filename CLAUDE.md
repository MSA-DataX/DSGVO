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
├── backend/                    FastAPI + Playwright + OpenAI/Azure + SQLite
│   ├── app/
│   │   ├── main.py             HTTP endpoints (/scan, /scan/stream, /scans)
│   │   ├── scanner.py          Orchestrator — owns Playwright lifecycle
│   │   ├── config.py           Pydantic Settings (.env driven)
│   │   ├── models.py           ALL Pydantic models. Update with frontend/lib/types.ts in lockstep.
│   │   ├── progress.py         SSE progress reporter (asyncio.Queue pub/sub)
│   │   ├── storage.py          aiosqlite persistence — one `scans` table
│   │   └── modules/
│   │       ├── crawler.py              BFS crawl, emits per-page progress
│   │       ├── network_analyzer.py     Captures every request; offline country map
│   │       ├── cookie_scanner.py       Cookie + localStorage/sessionStorage classifier
│   │       ├── policy_extractor.py     Fetch + clean policy; probe_common_paths() fallback
│   │       ├── ai_analyzer.py          OpenAI / Azure OpenAI / NoOp abstraction
│   │       ├── consent_clicker.py      19 CMP selectors + multilingual text fallback
│   │       ├── consent_diff.py         Pre vs post-consent diff engine
│   │       ├── form_analyzer.py        Deterministic; owns PII_CATEGORIES (exported)
│   │       └── scoring.py              5 sub-scores → hard caps → recommendations
│   ├── run_dev.py              Entry point — pins Windows Proactor loop BEFORE uvicorn imports
│   ├── requirements.txt
│   └── .env.example
├── frontend/                   Next.js 14 App Router + Tailwind
│   ├── app/
│   │   ├── page.tsx            Whole single-page dashboard
│   │   ├── layout.tsx          MSA DataX branding, favicon
│   │   ├── api/scan/route.ts           Batch proxy to backend /scan
│   │   ├── api/scan/stream/route.ts    SSE proxy — duplex:half, no buffering
│   │   └── api/scans/(...)             History endpoints proxy
│   ├── components/
│   │   ├── ui/                 Inlined shadcn-compatible primitives (button, card, badge, …)
│   │   └── scan/               Domain components (RiskScoreCard, DataFlowTable, …)
│   ├── lib/
│   │   ├── types.ts            Hand-mirrored from backend/app/models.py — names MUST match
│   │   ├── api.ts              runScan / streamScan / listScans / getScan / deleteScan
│   │   └── utils.ts            cn() + color helpers keyed to Tailwind `risk-*` palette
│   ├── public/logo.png         MSA DataX brand logo
│   └── .env.local.example
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
