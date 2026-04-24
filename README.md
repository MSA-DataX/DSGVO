# GDPR Scanner Tool

End-to-end GDPR compliance scanner for websites. A user enters a URL and
the system crawls the site, captures every outgoing request, classifies
cookies and trackers, runs the privacy policy through an LLM, analyzes
forms for consent gaps, and produces a weighted risk score with
prioritized recommendations.

## Repo layout

```
.
├── backend/    FastAPI + Playwright + OpenAI/Azure OpenAI
└── frontend/   Next.js 14 (App Router) + Tailwind + shadcn
```

Each side has its own README:

- **[backend/](backend/README.md)** — `POST /scan` endpoint, scoring engine,
  AI provider abstraction.
- **[frontend/](frontend/README.md)** — single-page dashboard that consumes
  the scan response.

## Quick start

Two terminals:

```bash
# Terminal 1 — backend
cd backend
python -m venv .venv && . .venv/Scripts/activate    # Windows; use bin/activate on Linux/macOS
pip install -r requirements.txt
playwright install chromium
cp .env.example .env                                # set OPENAI_API_KEY (optional)
uvicorn app.main:app --reload --port 8000
```

```bash
# Terminal 2 — frontend
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
# → open http://localhost:3000
```

## Pipeline overview

```
            ┌──────────────────────────────────────────────────────────────┐
            │                       POST /scan                             │
            └──────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
   ┌─────────────────────────────────────────────────────────────────────────┐
   │  one Playwright BrowserContext, attached request listeners              │
   │                                                                         │
   │   crawler.py        ──── BFS, depth-limited, per-page storage snapshot  │
   │       │                                                                 │
   │       ├── network_analyzer.py ── every request → domain → country/risk  │
   │       │                                                                 │
   │       ├── cookie_scanner.py   ── live cookie jar + storage classifier   │
   │       │                                                                 │
   │       └── policy_extractor.py ── privacy page → cleaned text            │
   │                                                                         │
   └─────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
                        ai_analyzer.py (OpenAI / Azure / NoOp)
                        + form_analyzer.py (deterministic)
                                         │
                                         ▼
                                 scoring.py
              5 weighted sub-scores → named hard caps → recommendations
                                         │
                                         ▼
                              JSON response → Next.js
```

## Privacy & compliance posture of the scanner itself

A GDPR audit tool that itself violates GDPR is a contradiction. So:

- **No third-party IP geolocation.** Country classification is offline
  (curated tracker map + EU/EEA ccTLD heuristic + honest `Unknown`
  fallback). Sending observed hostnames or IPs to an external API would
  itself be a small cross-border transfer.
- **No PII storage.** The scanner records request *metadata* only — no
  request bodies, no full cookie values, no response payloads. Cookie
  and storage values are masked to a short prefix/suffix preview.
  JWT-shaped values are reduced to `<jwt>` (the `eyJ…` prefix can leak
  the issuer).
- **AI provider keys stay server-side.** The frontend only ever talks to
  the Next.js proxy at `/api/scan`; the proxy talks to FastAPI; FastAPI
  talks to OpenAI/Azure. Browser never sees a key.
- **Graceful degradation.** Missing AI keys don't break a scan — they
  produce `privacy_analysis.provider="none"` and a neutral 50 in the
  privacy sub-score. The dashboard tells the user how to enable it.

## Deploying to production (Phase 6)

Single-host stack, all-in Docker Compose. Postgres + Redis + backend +
Arq worker + Next.js frontend + Caddy reverse proxy (auto-TLS via
Let's Encrypt). Designed for a 4 GB EU-hosted VM — tested shape is
Hetzner CPX21 (Nuremberg) or Scaleway DEV1-L (Paris), but any Linux
host with Docker + 443 / 80 reachable works.

### 1. DNS

Point your domain at the server's public IP **before** first boot.
Let's Encrypt will try to reach port 80 during cert issuance.

```
A  scanner.example.com   →  <server-ip>
```

### 2. Clone + configure

```bash
ssh root@scanner.example.com
git clone https://github.com/you/dsgvo-scanner.git
cd dsgvo-scanner

cp .env.production.example .env
# Fill in the REQUIRED values:
#   DOMAIN=scanner.example.com
#   TLS_EMAIL=ops@example.com
#   POSTGRES_PASSWORD=$(openssl rand -base64 32)
#   JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
#   OPENAI_API_KEY=sk-...                     # optional
#   MOLLIE_API_KEY=live_...                   # optional (billing)
#   MOLLIE_WEBHOOK_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
```

### 3. Boot

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

First build is slow (Playwright base image + Chromium ~1.5 GB). After
that, `docker compose ... up -d` reuses layers and comes up in seconds.

### 4. Bootstrap an admin

The CLI inside the backend container grants superuser — there's
deliberately no HTTP path for the first promotion (convention #18).

```bash
# First sign up at https://scanner.example.com/signup, then:
docker compose -f docker-compose.prod.yml exec backend \
  python -m app.cli.promote you@example.com
```

### 5. Verify

```bash
# HTTPS works, cert is valid, health endpoint responds:
curl -fsS https://scanner.example.com/api/scan/ -I >/dev/null || true
curl -fsS https://scanner.example.com/_health || true    # or just load in a browser

# Live logs across all services:
docker compose -f docker-compose.prod.yml logs -f --tail=200
```

### What the stack gives you

| Concern | How it's handled |
|---|---|
| TLS certificates | Caddy auto-issues + auto-renews via Let's Encrypt (`caddy_data` volume) |
| Security headers | Caddy injects HSTS + `X-Frame-Options` + `Referrer-Policy` + `Permissions-Policy` |
| Database isolation | Postgres/Redis only on the `internal` network — unreachable from outside the host |
| Zero-downtime migrations | Backend container runs `alembic upgrade head` before uvicorn starts |
| Scan queue | Arq worker is a separate service; scale with `--scale worker=N` |
| Non-root containers | Backend runs as `pwuser`, frontend as `nextjs`, Caddy as default unprivileged |
| Secrets hygiene | `.env` is `.gitignored`; no secrets in images, ever |
| Mollie webhook | Caddy routes `/billing/webhook/*` directly to the backend (Mollie can't send cookies) |

### Operational notes

**Updating.** On main branch push:

```bash
cd /opt/dsgvo-scanner
git pull
docker compose -f docker-compose.prod.yml up -d --build
# Old containers are replaced; migrations run on backend boot.
```

**Backups.** Postgres data lives in the `postgres_data` volume.
Minimum: nightly `pg_dump` via cron into off-host storage.

```bash
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U scanner scanner | gzip > /backup/scanner-$(date +%F).sql.gz
```

**Mollie webhook URL.** Once deployed, it's
`https://$DOMAIN/billing/webhook/$MOLLIE_WEBHOOK_TOKEN`. No separate
config in the Mollie dashboard — the backend passes it into every
payment-create call.

**Container registry (optional).** For faster deploys across multiple
hosts: tag and push images to GHCR / ECR / Scaleway Container
Registry, then replace `build:` with `image:` in the compose file.
That swap is intentionally **not** done here so `git clone && docker
compose up` keeps working as the zero-infrastructure path.

**What's NOT here (Phase 7 candidates).** Multi-host with an external
load balancer. Postgres streaming replication. Centralised logging
(Loki / Grafana Cloud). Prometheus metrics endpoint + dashboards.
Sentry error reporting. All of these are straight additions — the
compose file is the seam.
