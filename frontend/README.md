# GDPR Scanner — Frontend (Step 5)

Next.js 14 + Tailwind dashboard that consumes `POST /scan` from the
FastAPI backend.

## What's in here

```
frontend/
├── app/
│   ├── layout.tsx
│   ├── page.tsx                  # The whole single-page dashboard
│   ├── globals.css               # Tailwind + shadcn CSS variables
│   └── api/scan/route.ts         # Same-origin proxy → http://localhost:8000/scan
├── components/
│   ├── ui/                       # shadcn-compatible primitives, inlined
│   │   (button, card, badge, input, progress, alert, accordion,
│   │    skeleton, tabs, separator)
│   └── scan/                     # Domain components
│       ├── ScanForm.tsx
│       ├── RiskScoreCard.tsx
│       ├── SubScores.tsx
│       ├── HardCapsList.tsx
│       ├── RecommendationsList.tsx
│       ├── DataFlowTable.tsx
│       ├── CookiesSection.tsx
│       ├── PrivacyAnalysisCard.tsx
│       └── FormsSection.tsx
├── lib/
│   ├── types.ts                  # Hand-written mirror of backend ScanResponse
│   ├── api.ts                    # runScan() → POST /api/scan
│   └── utils.ts                  # cn() + GDPR rating/category color helpers
├── components.json               # shadcn config (only matters if you later run `npx shadcn add`)
├── tailwind.config.ts
├── postcss.config.mjs
├── tsconfig.json
├── next.config.mjs
├── package.json
└── .env.local.example
```

The shadcn primitives are inlined so you don't need to run `npx shadcn add`
to get a working dashboard — but `components.json` is in place if you
later want to fetch additional ones.

## Setup

```bash
cd frontend
npm install
cp .env.local.example .env.local   # Edit if backend isn't on localhost:8000
npm run dev
# → open http://localhost:3000
```

The backend must be running on the URL configured in
`NEXT_PUBLIC_BACKEND_URL` (default `http://localhost:8000`). Browser calls
go through `/api/scan` (same origin), which proxies to the backend — this
side-steps CORS and lets you change the backend host with one env var.

## Dashboard layout

1. **URL form** — URL + crawl depth (0-3) + max pages (1-25).
2. **Risk score card** — final score + rating badge, with "weighted
   sub-score average was X — capped by N hard caps" footnote when caps
   triggered.
3. **Sub-scores card** — five bars (cookies / tracking / data_transfer /
   privacy / forms), each with its weight, contribution, and the `notes`
   the engine emitted.
4. **Hard caps** — only renders if any cap triggered. Each cap shows its
   `code`, `cap_value`, and plain-English description.
5. **Recommendations** — priority-sorted, each with `related[]` chips
   linking back to the cap codes / domains / form URLs that produced it.
6. **Data flow table** — third-party domains, sorted by risk then request
   count. Country and risk badges.
7. **Cookies & Web Storage** — category counters + tabbed table of cookies
   and storage entries with vendor + reason for each classification.
8. **Privacy policy analysis** — AI summary, GDPR coverage checklist
   (✓/✗ per topic), issues with severity and excerpts. Falls back to a
   helpful "set OPENAI_API_KEY" message when the backend ran with
   `provider="none"`.
9. **Forms** — accordion of every form, each one expanded shows method,
   action, data categories, consent/privacy flags, legal text excerpt,
   and the deterministic issues list.

## Design notes

- **Same-origin proxy via `app/api/scan/route.ts`.** No CORS config to
  maintain on the backend, no `NEXT_PUBLIC_*` URL leaking into client
  code, and `NEXT_PUBLIC_BACKEND_URL` can change per environment.
  `maxDuration = 120` because a real scan takes 20-60s.
- **Hand-written `lib/types.ts`.** Mirrors the backend Pydantic models
  rather than running an OpenAPI codegen — keeps the toolchain small.
  Update both sides together; the type names match 1:1 for grep-ability.
- **Inlined shadcn primitives.** The ones we need (10 components) are
  written into `components/ui/` so `npm install && npm run dev` is the
  only setup step. `components.json` stays so `npx shadcn add <x>` still
  works for new components.
- **Risk colors live in Tailwind config**, not scattered across components.
  `risk-low/medium/high/critical` map to a fixed HSL palette so badge,
  progress bar, score number, and card border all use the same hue.
- **No streaming progress yet.** The backend returns one big JSON when
  the scan finishes; the frontend shows a spinner + skeleton placeholders
  in the meantime. Add an SSE / polling endpoint to the backend later if
  you want live "crawled page 3/8" updates.

## Production deployment

The proxy route uses `runtime = "nodejs"` and `maxDuration = 120`. On
Vercel that requires a Pro plan (Hobby caps at 60s for serverless
functions). For longer scans, run Next.js on your own Node host
(`npm run build && npm start`) where there's no per-request limit.
