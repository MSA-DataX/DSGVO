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
