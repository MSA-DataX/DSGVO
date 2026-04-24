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

**Container registry (Phase 7b).** CI builds images automatically on
every push to `main` and pushes them to GitHub Container Registry as
`ghcr.io/<owner>/<repo>-{backend,frontend}:<tag>`. Tags:

- `latest` — the moving pointer (last green main build)
- `<sha>` — 12-char git SHA (deterministic rollback target)

Compose already has the `image:` pointer wired in. On the server:

```bash
# .env — point at your registry + pin a version
IMAGE_REGISTRY=ghcr.io/your-org/your-repo
APP_VERSION=abc123def456    # SHA from the CI run

# Pull and restart
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

The same compose file still supports `docker compose up --build` for
local dev (build is the fallback when the remote image isn't
available). No separate prod/dev compose files.

## CI/CD pipeline (Phase 7b)

Two GitHub Actions workflows:

| File | Trigger | What it does |
|---|---|---|
| [.github/workflows/ci.yml](.github/workflows/ci.yml) | Every push + PR to `main` | Backend pytest (294 tests), frontend lint + typecheck. On `main` only: build + push Docker images to GHCR with GHA layer cache. |
| [.github/workflows/deploy.yml](.github/workflows/deploy.yml) | Manual (workflow_dispatch) | SSH to the server, pin `APP_VERSION` in `.env`, pull, `up -d`, wait for `/health`, prune dangling images. |

**Why deploy is manual, not on-push.** Production is one VM, one
compose stack, one operator. Auto-deploy on main is a nice-to-have
that bites you the first time main is green but the change needs a
manual migration step or a feature-flag toggle. Explicit button-click
with image SHA in the form is the lowest-regret default.

**Repo secrets required** (Settings → Secrets and variables → Actions):

| Name | Used by | Example |
|---|---|---|
| `GITHUB_TOKEN` | ci.yml | auto-provided; no action needed |
| `DEPLOY_SSH_KEY` | deploy.yml | private key (full file contents, not path) |
| `DEPLOY_HOST` | deploy.yml | `deploy@scanner.example.com` |
| `DEPLOY_PATH` | deploy.yml | `/opt/dsgvo-scanner` |
| `DEPLOY_PORT` | deploy.yml (optional) | `22` |

**Repo variables** (optional — used at image build time):

| Name | Used by | Example |
|---|---|---|
| `NEXT_PUBLIC_BACKEND_URL` | ci.yml frontend build | `https://scanner.example.com` |
| `NEXT_PUBLIC_SCAN_MODE` | ci.yml frontend build | `async` |

**Deploying:**

1. Land a PR on `main`. CI runs tests + pushes the new images.
2. Open the Deploy workflow in GitHub Actions → Actions tab → Deploy.
3. Click "Run workflow" → enter the image tag (either `latest` or a
   specific 12-char SHA from the CI run) → confirm.
4. The SSH job waits for `/health` to report `ok` before it exits —
   green = users are on the new build.

**Rolling back:**

Same workflow, type an older SHA. Image is still in GHCR (GHCR keeps
tags forever unless you prune manually). The server only has to
`pull + up -d`; the new containers start against the old image in
seconds.

**One-time server setup** (before the first deploy):

```bash
ssh root@scanner.example.com
adduser --disabled-password --gecos "" deploy
usermod -aG docker deploy
su - deploy

# Clone for the static files (compose + Caddyfile live in git)
git clone https://github.com/you/dsgvo-scanner.git /opt/dsgvo-scanner
cd /opt/dsgvo-scanner
cp .env.production.example .env
nano .env   # fill in secrets + IMAGE_REGISTRY

# Add the deploy user's public key to ~/.ssh/authorized_keys so the
# workflow can SSH in. Private key goes to the DEPLOY_SSH_KEY secret.

# Log into GHCR once so subsequent pulls work unattended. Use a
# Classic PAT with `read:packages` scope for private repos; public
# repos need no login at all.
echo $GHCR_TOKEN | docker login ghcr.io -u <your-github-user> --password-stdin

# First boot — local build to get the stack running BEFORE CI has
# populated the registry. After this, deploys come from GHCR.
docker compose -f docker-compose.prod.yml up -d --build
```

From then on, every release is a click in the Actions tab.

**What's NOT here (Phase 7 candidates).** Multi-host with an external
load balancer. Postgres streaming replication. Centralised logging
(Loki / Grafana Cloud). Prometheus metrics endpoint + dashboards.
Sentry error reporting. All of these are straight additions — the
compose file is the seam.

## Compliance (Phase 7c)

A scanner product needs to be exemplary about its own data handling —
otherwise the sales conversation is over in the first procurement
email. What's shipped:

| Artefact | Location | When to touch it |
|---|---|---|
| `/.well-known/security.txt` | Served by backend; configured via `SECURITY_*` env vars | Rotate `SECURITY_TXT_EXPIRES` annually |
| Incident response runbook | [docs/incident-response.md](docs/incident-response.md) | Before every on-call shift; drill yearly |
| Data Processing Agreement template | [docs/dpa-template.md](docs/dpa-template.md) | Fill in `<PLACEHOLDERS>` per customer; have legal review before sending |
| Data retention policy | [docs/retention-policy.md](docs/retention-policy.md) | Review annually; update when a new data class is added |
| Backup script | [deploy/backup.sh](deploy/backup.sh) | Install via cron (`0 3 * * *`); `BACKUP_GPG_RECIPIENT` for off-site storage |
| Audit log | `audit_logs` table, `GET /admin/audit` | Keep the 3-year retention default unless legal tells you otherwise |

**What this gets you:**

- Standard DSGVO Art. 28 DPA to send prospects who ask (every B2B
  DACH lead will ask, sooner rather than later).
- A documented 72-hour breach-notification plan that actually
  survives contact with an incident.
- Retention numbers for every data class the system stores — the
  first thing a SOC 2 auditor asks.
- RFC 9116 security.txt so vulnerability researchers know where to
  send a report, not where to post one publicly.

**What this does NOT get you:**

- SOC 2 Type II certification. That's a 6-month audit with a firm
  like Drata / Vanta driving it. These artefacts are 80% of the
  prep work; the remaining 20% is evidence collection over the
  observation period.
- ISO 27001. Same story — this is the narrative, not the audit.

**Set before going live:**

```bash
# backend/.env (production)
SECURITY_CONTACT_EMAIL=security@your-company.com
SECURITY_POLICY_URL=https://your-company.com/security
SECURITY_TXT_EXPIRES=2027-01-01T00:00:00Z    # rotate before then

# Backup cron (on the production host)
echo '0 3 * * * deploy /opt/dsgvo-scanner/deploy/backup.sh >> /var/log/scanner-backup.log 2>&1' \
  | sudo tee /etc/cron.d/scanner-backup
```
