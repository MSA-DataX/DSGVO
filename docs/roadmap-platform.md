# Platform Roadmap — Vom Scanner zur DSGVO-Plattform

> **Status:** Plan, kein Spec. Vor Implementierung jeder Säule entsteht
> ein eigenes `docs/specs/saeule-{1,2,3}.md` mit konkreten Models,
> Endpoints, Tests und Edge Cases. Die hier genannten Aufwände sind
> Single-Dev-Schätzungen, keine garantierten Lieferzeiten. Pricing-
> Vorschläge sind Indikation; finale Preise legt Moussa fest.
> **Anker:** [CLAUDE.md](../CLAUDE.md) ist die Architektur-Quelle
> (insb. Conventions #2, #12, #15, #19, #20, #25). Es gibt heute
> kein separates `docs/architecture.md` / `docs/billing.md` — die
> Logik lebt in CLAUDE.md plus dem Code unter `backend/app/billing/`.

---

## Vision

**Heute** ist der MSA DataX Scanner ein hochwertiges Snapshot-Tool: ein
Klick, ein Report, eine PDF. Das ist eine Commodity-Kategorie — jeder
Lighthouse-Klon, jedes WordPress-Plugin, jede DPA-Boutique kann es in
sechs Wochen mit Headless Chromium und einer LLM-API selbst bauen. Die
Differenzierung über bessere Detektoren, schönere Recommendations und
Big4-Style PDFs ist real, aber nicht dauerhaft verteidigbar — wer den
Markt zuerst mit "Compliance as a Subscription" besetzt, gewinnt.

**Plattform** heißt drei Dinge gleichzeitig: **(1) kontinuierlich**
statt einmalig (Drift Alerts, Score-über-Zeit, Webhook-Pipelines in
Kunden-Tools), **(2) tief** statt breit (Branchen-Editions wie MedTech
mit Art. 9 DSGVO, BfArM, Patientendaten-Spezifika — höher gepreist,
weniger Wettbewerb), **(3) verifizierbar** statt fluechtig (Audit-
Evidence-Vault mit RFC-3161-Timestamps für DPA-Anfragen, Schadenersatz-
klagen, Behördenanfragen). Die drei Säulen sind technisch und
geschäftlich unabhängig sequenzierbar, aber sie ergänzen sich:
Continuous Monitoring liefert die Datenpunkte, die später als Audit-
Evidence eingefroren werden; MedTech-Edition produziert die
spezifischen Findings, die ein DPO im Vault sammeln will.

---

## Status Quo (Stand heute)

**Was der Scanner kann:**
- Snapshot-Scan einer URL via Playwright + AI-Policy-Review + 5
  gewichtete Sub-Scores + Hard-Caps (siehe Conventions #3, #19,
  #28-#33)
- Sync- und async Scan-Modi (Convention #15), Multi-Tenant-Isolation
  (Convention #12), Rate Limits + Quotas (Convention #14, #19)
- Hardcoded Plan-Katalog `free` / `pro` / `business` mit monatlichem
  Scan-Quota (Convention #19, [billing/plans.py](../backend/app/billing/plans.py))
- Mollie-Integration für Bezahl-Flow (Convention #20)
- Big4-Style PDF-Export (Convention nicht nummeriert, lebt in
  `frontend/components/scan/PdfReport.tsx`)

**Was der Scanner NICHT kann:**
- **Kein Re-Scan über Zeit** — Scans sind isolierte Events, kein
  Diff-Engine, keine Score-Verlauf-Visualisierung
- **Kein Multi-Domain-Dashboard** — eine Org sieht eine Scan-Historie,
  aber keine Domain-Liste mit Aggregaten
- **Keine Drift-Alerts** — wenn der Kunde morgen ein Meta-Pixel
  einbaut, merkt das Tool es erst beim nächsten manuellen Scan
- **Keine Branchen-Tiefe** — ein generischer SaaS-Scan und ein Kinder-
  Arztpraxis-Scan laufen durch denselben Code-Pfad. Art. 9 DSGVO
  (Gesundheitsdaten), Art. 8 (Minderjährige), § 22 BDSG werden nicht
  spezifisch geprüft. Die in Convention #28-#32 ergänzten Detektoren
  sind allgemein, nicht vertical-spezifisch.
- **Kein Audit-Trail nach außen** — der Kunde kann nicht beweisen,
  dass die Seite an einem konkreten Tag X compliant war. Die
  scan-Tabelle ist intern + mutable per Retention-Cron (Convention
  #25). Für DPA-Anfragen / Behörden braucht es einen unveränderlichen,
  verifizierbaren Beweis.

---

## Säule 1 — Continuous Monitoring + Drift Alerts

### Pitch
> "Sie schlafen, wir wachen."

Statt einmaligem Scan: täglicher (oder stündlicher) Re-Scan, Diff zum
Vortag, automatischer Alert bei neuen Trackern / neuen Cookies /
Policy-Text-Änderungen / signifikantem Score-Drop. Aus dem Werkzeug
("ich scanne mal eben") wird ein Service ("ich werde benachrichtigt").

### Pricing-Hebel
- **Free:** bleibt Snapshot-only — keine Domains monitorbar.
- **Pro (19€/Mo):** 1 Domain, täglich (24h-Cron).
- **Business (99€/Mo):** bis zu 10 Domains, stündlich konfigurierbar
  pro Domain.
- Add-On nicht vorgesehen — Monitoring zwingt User von Free → Pro,
  das ist der primäre Conversion-Hebel.

### Datenmodell

**Neue Tabellen** (Migration via Alembic, Convention #21 CMD startet
`alembic upgrade head`):

```sql
-- monitored_domain
id                  UUID PK
organization_id     UUID NOT NULL REFERENCES organization(id) ON DELETE CASCADE
url                 TEXT NOT NULL
schedule_cron       TEXT NOT NULL          -- "0 3 * * *" für 03:00 daily
alert_email         TEXT                    -- nullable — webhook reicht
alert_webhook_url   TEXT                    -- nullable
paused              BOOLEAN NOT NULL DEFAULT false
created_at          TIMESTAMPTZ NOT NULL
last_scan_at        TIMESTAMPTZ             -- nullable, Wartezustand
UNIQUE (organization_id, url)               -- eine Domain einmal pro Org

-- scan_diff
id                  UUID PK
scan_id_old         UUID NOT NULL REFERENCES scan(id) ON DELETE CASCADE
scan_id_new         UUID NOT NULL REFERENCES scan(id) ON DELETE CASCADE
diff_json           JSONB NOT NULL          -- die strukturierte DiffResult
score_delta         INTEGER NOT NULL        -- für schnellen Index
created_at          TIMESTAMPTZ NOT NULL
INDEX (scan_id_new)
```

**Erweiterung bestehender Tabellen:**

```sql
ALTER TABLE scan ADD COLUMN monitored_domain_id UUID
    REFERENCES monitored_domain(id) ON DELETE SET NULL;
```

`monitored_domain_id` ist nullable — manuelle Scans bleiben ohne Bezug,
nur Cron-getriggerte Scans verweisen auf ihre Quelle. Per Convention
#27 muss die SQLite-Variante FK-Cascade testen (`PRAGMA foreign_keys`).

### Backend-Module

- **`app/monitoring/scheduler.py`** — Arq Cron Job, der alle 5 Minuten
  `monitored_domain` liest, jeden Eintrag dessen `schedule_cron`
  fällig + `paused=false` ist enqueued via `enqueue_scan` (Convention
  #15, #16). Der Job stempelt `monitored_domain_id` auf das Scan-Row.
  Concurrency-Schutz: Arq's `unique_job_id` aus
  `monitored_domain.id + scheduled_minute`, damit überlappende Cron-
  Trigger keine doppelten Scans erzeugen.

- **`app/monitoring/diff_engine.py`** — pure async function:
  ```python
  def compute_scan_diff(old: ScanResponse, new: ScanResponse) -> DiffResult
  ```
  Liefert strukturiert:
  - `new_tracker_domains: list[str]` (set-Diff über `data_flow.domain`)
  - `removed_tracker_domains: list[str]`
  - `new_cookies: list[CookieDiffEntry]` (mit category, domain, vendor)
  - `score_delta: int` (new.score − old.score)
  - `policy_text_changed: bool` (SHA-256 hash vergleich auf
    `privacy_analysis.policy_text` falls vorhanden, sonst auf
    `privacy_analysis.summary`)
  - `new_hard_caps: list[str]` (cap codes die im neuen aber nicht
    im alten Scan auftauchen)
  - `removed_hard_caps: list[str]`
  Pure → trivial unit-testbar (Convention #-Testing-Targets).

- **`app/monitoring/alerter.py`** — zwei Wege, beide best-effort, kein
  Blocker für den eigentlichen Scan:
  - **E-Mail** via SMTP (neue ENV: `SMTP_HOST`, `SMTP_PORT`,
    `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`). Template: HTML + plaintext
    Fallback, mit DiffResult-Highlights + Link zum Dashboard.
  - **Webhook** via `httpx.AsyncClient.post(url, json=DiffResult)` —
    HMAC-Signatur per Convention-#11-Stil-Header (`X-MSADataX-
    Signature: sha256=...`), shared secret pro `monitored_domain`
    (neue Spalte `webhook_secret` ergänzen, generiert beim Anlegen).
  - Beide hängen an einer separaten Arq-Job-Queue (`alerts`), damit
    ein langsamer SMTP-Server keinen scan-Job blockiert.

- **`app/routers/monitoring.py`** — CRUD-Endpoints:
  - `POST   /monitoring` — neue Domain anlegen (Quota-Check via
    Convention #19!)
  - `GET    /monitoring` — Liste aller Domains der Org
  - `GET    /monitoring/{id}` — Details + neuester Diff
  - `PATCH  /monitoring/{id}` — pausieren / Cron ändern / Alert-Ziele
  - `DELETE /monitoring/{id}`
  - `GET    /monitoring/{id}/diffs?limit=30` — Diff-Timeline
  Alle Routes scoped per `organization_id` (Convention #12), cross-
  tenant 404 ist Pflicht — neuer Test in
  `tests/test_auth.py::TestTenantIsolation`.

### Frontend

- **`/monitoring`** — Liste der Monitored Domains pro Org als
  Card-Grid: pro Card aktueller Score (mit ↑/↓ vs. letzter Scan),
  Domain-URL, "Last scan: 23h ago", Pause/Resume-Toggle.
- **`/monitoring/[id]`** — Detail-Page:
  - **Timeline-Chart**: Score über die letzten 30 Tage (Line-Chart,
    farbcodiert nach Risk-Rating).
  - **Diff-Cards**: chronologisch absteigend, jeweils "Day X → Day Y:
    +1 new tracker, score −12, policy text changed". Klick öffnet
    den Voll-Diff.
  - **Alert-Konfiguration**: Email + Webhook-URL, Test-Button der
    eine Sample-Payload an den Webhook schickt.
- **Heatmap-Komponente** auf Org-Übersicht: Domain (Y-Achse) ×
  Risk-Kategorie (X-Achse: Cookies / Tracking / Data-Transfer /
  Privacy / Forms), Zellfarbe = Sub-Score. Single-View-Indikator
  welche Domain in welcher Domäne dringend ist.
- **Toast-Inbox** im UserMenu: ungelesene Alerts mit Counter-Badge,
  klickbar zur Diff-Ansicht.

### Convention-Hinweise
- **#2:** Neue Models in `models.py` + `frontend/lib/types.ts` im
  selben Commit.
- **#12:** `monitored_domain.organization_id` Pflicht; cross-tenant
  Lese-/Schreibzugriff → 404. `MonitoredDomain.affected_subscores`-
  Feld nicht relevant — gibt's nicht in dem Modell.
- **#15:** Re-Scans laufen über `enqueue_scan` (async), niemals sync
  inline — sonst blockiert ein laufender Scan den Cron.
- **#19:** Quota-Check beim Anlegen einer monitored_domain. Plan-
  Erweiterung: `monthly_monitored_domains_quota: int` — free=0,
  pro=1, business=10. `check_monitored_domain_quota(org_id)` analog
  zu `check_scan_quota` in dem 3-Schritt-Order: SSRF → Rate-Limit →
  402-Quota.
- **#21:** Worker-Dockerfile braucht keine Änderungen — der neue
  Cron-Job läuft im selben Arq-Worker-Prozess.
- **#22:** Neue Prometheus-Counter: `monitoring_scans_total`,
  `monitoring_alerts_sent_total{kind=email|webhook,status=ok|fail}`.

### Aufwand-Schätzung (Single-Dev)
- Backend (Models + Migration + Scheduler + Diff-Engine + Alerter +
  Routes): **~5 Tage**
- Frontend (3 Pages + Heatmap + Toast-Inbox): **~4 Tage**
- Tests (Diff-Engine pure, Scheduler integration, Alerter SMTP-Mock):
  **~2 Tage**
- Spec-Phase + Migration-Plan: **~1 Tag**
- **Gesamt: ~2 Wochen**

---

## Säule 2 — MedTech-Edition (Branchen-Vertikalisierung)

### Pitch
Generischer Scanner = austauschbar. **MedTech-Edition** kennt Art. 9
DSGVO (besondere Kategorien — Gesundheitsdaten), Art. 8 (Minderjährige),
BfArM-Hinweise bei Medical-Device-Software, Telemedizin-Spezifika.
Das ist ein **2-3× Premium-Pricing** rechtfertigbar — Arztpraxen,
Kliniken, MedTech-Startups zahlen mehr für ein Tool das ihre
Compliance-Sprache spricht.

### Was MedTech anders prüft

**Art. 9 DSGVO Detection (besondere Kategorien):**
- Health-Keywords im Hostname / Page-Title / H1 (paritätisch zur
  AUDIENCE-SAFETY-Rule in Convention #-AI-Analyzer):
  `praxis|klinik|arzt|medizin|therapie|gesundheit|diagnose|patient`
  und englisch `clinic|hospital|medical|therapy|patient|diagnosis`.
- Symptom-Tests / Selbsttests / Diagnose-Tools — Form-Detection-
  Heuristik (Convention #28-Stil): Form-Felder mit Health-spezifischen
  Patterns (`symptom`, `beschwerden`, `diagnose`, Skala-Inputs 0-10).
- Cookie/Tracker-Verbot bei Health-Kontext: Google Ads, Facebook Pixel,
  TikTok Pixel automatisch **HIGH severity** (statt der generischen
  medium/high-Mischung) — zusätzlicher Hard-Cap der härter beißt als
  `us_marketing_no_consent` (40) oder `tdddg_non_essential_without_consent`
  (50).

**Kinderdaten (KJP, ADHS, Autismus-Diagnostik):**
- Art. 8 DSGVO — Eltern-Einwilligung. Prüft ob die Policy einen
  expliziten Minderjährigen-Abschnitt hat (Token-Heuristik:
  `Eltern|Erziehungsberechtigt|minderjährig|Art.\s*8|Kinder`).
- Reuse der Site-Context-Heuristik aus dem AI-Analyzer (paediatrisches
  Hostname/Title-Signal) — wenn das Site-Context Indicator zieht UND
  der Policy-Text die Tokens nicht enthält → harter Cap.

**BfArM-Hinweise bei Medical-Device-Software:**
- Heuristik: bestimmte Keywords im Title/Body deuten auf MedTech-
  Software hin (`Medizinprodukt|Software-Medizinprodukt|MDR|CE
  certified|FDA cleared|BfArM`). Kein Cap, aber eine warnende
  Recommendation: "Diese Seite scheint ein Medizinprodukt zu
  bewerben. Stellen Sie sicher, dass die BfArM-Anzeigepflicht
  beachtet ist + DiGA-Verzeichnis-Status (falls einschlägig)
  korrekt dargestellt wird."

**Telemedizin-Spezifika:**
- Erkennt Videosprechstunden-Plattformen (TI-Messenger, RED Connect,
  ZAVA, Doxy.me, Doctolib-Visio, …) und prüft auf KBV-konforme
  Hinweise + § 365 SGB V Verschwiegenheit.
- eRezept-Integration: Token im DOM (`gem.epa`, `gematik`, `kbv`)
  triggert Hinweis auf TI-Anbindung-Compliance.

### Implementierung

**Neuer Modul `app/modules/vertical/medtech.py`** — pure function:

```python
def detect_medtech_context(scan_input: VerticalContextInput) -> MedTechContext
```

Eingabe: Hostname, Page-Title, H1, Crawl-Pages-Sample, Form-Liste,
Policy-Text-Snippet. Ausgabe:

```python
class MedTechContext(BaseModel):
    is_health_site: bool
    health_keywords_matched: list[str]    # Audit-Evidence
    has_symptom_tests: bool
    targets_minors: bool                  # ADHS, Autismus, Kinder
    is_medical_device_software: bool
    is_telemedizin: bool
    sample_pages: list[str]                # max 5 URLs als Belege
```

Reine Pattern-Matching-Funktion, keine I/O — testbar wie
`google_fonts_detector` (Convention #32).

**Neue Hard-Caps in `scoring.py`** (jeweils mit Mapping in
`_CAP_AFFECTS`):

| Cap-Code | Wert | `affected_subscores` | Trigger |
|---|---|---|---|
| `health_data_no_art9_consent` | 30 | `(privacy, forms)` | `is_health_site=True` AND Form sammelt PII AND keine Art. 9-Tokens in Policy |
| `minors_no_parental_consent_section` | 35 | `(privacy,)` | `targets_minors=True` AND keine Art. 8-Tokens in Policy |
| `marketing_tracker_on_health_site` | 25 | `(tracking, data_transfer)` | `is_health_site=True` AND Marketing-Tracker pre-consent erkannt |

Alle drei niedriger als die generischen Equivalente (z.B. `25` vs.
`40` für `us_marketing_no_consent`) — bewusst härter, weil Health-
Kontext der Anwendungsfall mit dem höchsten DPA-Risiko ist.

**Branchen-spezifische Recommendations** (neuer i18n-Block
`recs.medtech.*`): mit konkreten Verweisen auf BfArM-Leitlinien
(Stand der Technik 2024), DSK-Beschluss 4/2024 zum
Patientendatenschutz, Bayerische LDA-Leitlinie zu Praxis-Webseiten.

### Beziehung zwischen `is_health_site` und AI `AUDIENCE-SAFETY`

Eine Quelle der Wahrheit, deterministische Klassifikation
zuerst, AI verstärkt nur:

| Layer | Verantwortung | Output |
|---|---|---|
| `app/modules/vertical/medtech.py::is_health_site` | Deterministische Klassifikation (Hostname-Keywords, H1, Page-Title, Policy-Vokabular) | `bool` |
| AI Policy-Analyzer `AUDIENCE-SAFETY`-Block | Bekommt `is_health_site` als Input-Variable im Prompt | Eskaliert Severity bei Health-Kontext, klassifiziert NICHT selbst |

Begründung:

> Konsistent mit Convention #9 (deterministic beats AI when
> structure is regular). `is_health_site` ist regelbasiert und
> testbar; die AI bekommt das Ergebnis als Faktum geliefert
> und reasoned darauf — sie versucht nicht die Klassifikation
> zu wiederholen. Das verhindert Disagreement zwischen den
> beiden Layern und macht die Findings reproduzierbar.

Implikation für die Spec:
- `is_health_site(scan_input) -> bool` läuft VOR dem
  AI-Analyzer im Pipeline-Flow
- Ergebnis wird in `ScanContext` (oder vergleichbarer Struktur)
  abgelegt und in den AI-Prompt als Variable injected
- AI-Prompt-Template bekommt einen neuen Slot
  `{{is_health_site}}` mit klarem Wording: "Wenn true,
  betrachte alle Marketing-Tracker als Art. 9 DSGVO-relevant"

### Plan-Differenzierung

**Neuer Plan `medtech`** im Katalog:

```python
Plan(
    code="medtech",
    name="MedTech",
    price_eur_cents=3900,            # 39.00 EUR
    monthly_scan_quota=100,          # = pro
    description="…paediatrische und MedTech-Praxen…",
)
```

Mollie-Integration: neuer `mollie_price_id` per Convention #19/#20.
Existierende Pro-Subscriptions werden **nicht** automatisch migriert
— der Operator entscheidet pro Org via `POST /admin/organizations/{id}/set-plan`.

**ScanRequest-Erweiterung** (Convention #2 — beide Seiten gleichzeitig):

```python
ScanRequest.vertical: Literal["general", "medtech"] = "general"
```

Default `general` hält bestehende Scans rückwärtskompatibel. Wenn
`vertical="medtech"` UND der Plan ist nicht `medtech` oder `business`
→ 402 Payment Required (Convention #19, der `check_scan_quota`-3-
Schritt-Order erweitert sich um den Vertical-Check).

### Frontend

- **Plan-Selector** zeigt MedTech als eigene Option mit kleinem
  Stethoskop-Icon und der Tagline "Art. 9 + Art. 8 + BfArM-aware".
- **Im Report neue Section** "Branchen-spezifische Findings" — nur
  sichtbar wenn `vertical=medtech`. Cards mit eigenen Severity-
  Farbtoken (z.B. dunkelrot statt orange für MedTech-spezifische
  HIGH-Findings, damit ein DPO auf einen Blick sieht: "das ist
  branchenkritisch").
- **Badge auf Findings-Cards**: kleiner Text-Pin "Art. 9 DSGVO" /
  "Art. 8 DSGVO" / "BfArM" wenn das Finding aus der Vertical-
  Engine stammt (Backend-Feld `PolicyIssue.vertical_anchor: str | None`).
- **PDF-Export** rendert die zusätzliche Section automatisch im
  Privacy-Chapter mit Big4-Format (Convention nicht nummeriert,
  PdfReport.tsx).

### Erste Zielkunden
**`gam-medical.de`** ist der Live-Pilot — aktuell Score 45, kein
Art. 9-Hinweis, kein Kinder-Abschnitt, TikTok auf einer Health-
Site. Perfekter Sales-Case-Study: Screenshot der drei neuen Caps,
neben dem Big4-PDF, als Cold-Outreach-Material für andere Praxen.
Aufnahme der MedTech-Edition als USP in die Marketing-Seite.

### Convention-Hinweise
- **#1:** Health-Keywords-Liste lebt zentral in
  `app/modules/vertical/medtech.py` als Konstante. Keine Duplikation
  in scoring.py oder ai_analyzer.py — beide importieren.
- **#2:** `MedTechContext` und `vertical: Literal[...]` in models.py
  + types.ts.
- **#19:** Plan-Catalogue-Erweiterung als Code-Change + Migration —
  niemals Runtime-Toggle (Convention-Sentence: "a runtime swap can't
  accidentally reduce a paying customer's quota").
- **#-AUDIENCE-SAFETY (AI-Analyzer):** siehe eigene Subsection
  "Beziehung zwischen `is_health_site` und AI `AUDIENCE-SAFETY`"
  oben — der MedTech-Detektor ist die Single Source of Truth, die
  AI bekommt sein Ergebnis als Faktum geliefert und reasoned darauf,
  klassifiziert NICHT selbst.

### Aufwand-Schätzung (Single-Dev)
- Backend (Detector + 3 neue Caps + Recommendations + Plan-
  Erweiterung + Mollie-Wiring): **~4 Tage**
- Frontend (Plan-Selector + Vertical-Badge + Report-Section +
  PDF-Erweiterung): **~2 Tage**
- Recommendations-Texte (juristisch fundiert, BfArM/DSK/LDA
  Recherche): **~2 Tage**
- Spec + Tests + Doku: **~2 Tage**
- **Gesamt: ~1.5 Wochen**

---

## Säule 3 — Audit-Evidence-Vault

### Pitch
Bei DPA-Anfrage / Schadenersatzklage / Behördenanfrage: der Kunde
hat einen **unveränderlichen, kryptografisch verifizierbaren Beweis**,
dass seine Seite an Tag X compliant war (oder eben nicht). Hash +
RFC-3161-Timestamp + signiertes PDF/A-3. Premium-Feature für
Business-Tier, 10 Jahre Aufbewahrung (gesetzliche Frist).

### Datenmodell

```sql
-- audit_evidence — append-only, analog zu audit_logs (Convention #25)
id                    UUID PK
scan_id               UUID NOT NULL REFERENCES scan(id) ON DELETE RESTRICT
                      -- RESTRICT, nicht CASCADE: Vault-Eintrag MUSS
                      -- auf den ursprünglichen Scan zeigen können.
                      -- Löschung des Scans wird durch FK blockiert,
                      -- bis Vault-Eintrag selbst per Retention läuft.
content_hash          TEXT NOT NULL          -- SHA-256 hex
pdf_path              TEXT NOT NULL          -- Storage-URI (s3:// oder local)
timestamp_token       BYTEA NOT NULL         -- RFC-3161 TST
timestamp_authority   TEXT NOT NULL          -- "freetsa.org" / "d-trust.net"
timestamped_at        TIMESTAMPTZ NOT NULL
immutable_id          UUID UNIQUE NOT NULL   -- public verifier ID
created_at            TIMESTAMPTZ NOT NULL
INDEX (scan_id), INDEX (immutable_id)

-- Erweiterung
ALTER TABLE scan ADD COLUMN evidence_id UUID
    REFERENCES audit_evidence(id) ON DELETE SET NULL;
    -- nullable; nicht jeder Scan landet im Vault
```

**Append-only:** keine UPDATE-/DELETE-Statements im App-Code.
Convention #25 (Retention sweep darf audit_logs deleten) wird um
einen analogen Eintrag erweitert: `purge_audit_evidence_older_than(years=10)`
ist die EINZIGE app-Layer-Funktion die hier deleten darf, läuft im
selben Arq-Cron um 03:30 UTC.

### Backend

- **`app/evidence/hasher.py`** — kanonische JSON-Serialisierung des
  ScanResponse → SHA-256:
  - `json.dumps(payload, sort_keys=True, separators=(",", ":"))`
  - Whitespace-normalisierte Strings (`\r\n` → `\n`, trailing-WS
    raus) bevor sie in das Dict gehen.
  - PII-Felder (`cookies[].value_preview`, etc.) sind bereits
    gemasked (Convention #8) — wir hashen die gemaskte Repräsentation,
    nicht die Rohwerte.
  - Pure function, voll testbar.

- **`app/evidence/timestamper.py`** — RFC 3161 Trusted Timestamp:
  - Default: **FreeTSA** (https://freetsa.org) — kostenlos, RSA-2048,
    EU-zugänglich, gut für Free/Business-Bundle.
  - Optional konfigurierbar: **D-Trust** (Bundesdruckerei,
    qualifiziert eIDAS-konform) für Enterprise-Kunden, kostenpflichtig.
  - Implementierung: Request enthält den SHA-256-Hash, Antwort ist
    der TimeStampToken (`.tsr` Format, ASN.1 DER kodiert).
  - Wird via `httpx` an die TSA gepostet, mit Retry + Timeout.
  - Bibliothek: `rfc3161-client` (oder `asn1crypto` + manueller
    Build) — Spec-Phase entscheidet welche, beide sind
    permissive-licensed.

- **`app/evidence/pdf_signer.py`** — PDF/A-3 Export mit eingebettetem
  Hash + TimeStampToken:
  - Reuse `react-pdf/renderer` (oder Server-side via `reportlab` /
    `pikepdf`) — Spec-Phase entscheidet. Aktuell ist das PDF
    clientseitig generiert; für Vault muss das **serverseitig**
    laufen, weil das Hashing + Timestamping auf den Server-
    Roundtrip angewiesen ist (sonst kann der Client den Hash
    fälschen).
  - PDF/A-3 erlaubt eingebettete Anhänge — der `.tsr`-Token
    + ein `evidence-manifest.json` (Hash, Authority, immutable_id)
    werden als Attachments eingebettet.
  - Sichtbarer Footer auf Cover-Page: "Audit-Evidence ID: <uuid>
    · SHA-256: <prefix>... · TSA: freetsa.org · Verified at:
    https://msadatax.com/verify/<uuid>".

- **`app/routers/evidence.py`**:
  - `POST /evidence/from-scan/{scan_id}` — auth required, scoped
    per `organization_id` (Convention #12). Erstellt Vault-Eintrag
    (Hashing + Timestamping + PDF-Signing), gibt `immutable_id`
    zurück. Quota-Check (Convention #19) wenn Plan-spezifisch
    limitiert.
  - `GET /evidence/{immutable_id}` — **public, kein Auth.** Gibt
    Metadata + signiertes PDF zum Download. Begründung: der Kunde
    leitet die ID an Behörden / Gerichte / Gegenanwälte weiter,
    die haben keinen Account.
  - `GET /evidence/{immutable_id}/verify` — public; re-hashed das
    PDF + verifiziert das Timestamp-Token gegen die TSA-Public-
    Key-Chain, gibt `{valid: bool, hash_match: bool, tst_signature_valid: bool, ...}`.
  - **Rate-Limit** auf den public Endpoints: 60 Requests/Minute pro
    IP (Convention #14, neuer Bucket-Namespace). Sonst lädt jemand
    die ganze Vault-Eintrags-DB mit Zufalls-UUIDs.

### Frontend
- **Im Scan-Report ein "Als Audit-Evidence speichern"-Button** in
  der ExportButton-Gruppe (neben "PDF" / "JSON"). Disabled mit
  Tooltip wenn der Plan es nicht erlaubt + Upgrade-Link.
- **`/vault`** — Liste aller Vault-Einträge der Org: Datum,
  Domain, Score-Snapshot, immutable_id (kopierbar), Verify-Status-
  Pin, Download-PDF-Button.
- **`/verify/[id]`** — public Verifizierungs-Seite, kein Auth, nur
  immutable_id. Zeigt: Hash-Match ✓/✗, Timestamp-Authority +
  Datum, PDF-Download. Rendert in einem Branding-neutralen Layout
  (kein Login-Link, kein UserMenu) — die Seite ist für
  Behördenmitarbeiter / Anwälte gedacht.

### Pricing
- **Business Plan inkludiert** 50 Vault-Einträge / Monat.
- **Add-on** für Pro-Plan: 5€ pro Eintrag, manueller Buchungs-Flow.
- **Free** kann nichts in den Vault legen — der Button ist disabled
  mit Upgrade-CTA.

### Convention-Hinweise
- **#11 (Auth-Cookies httpOnly):** Vault-IDs sind public — KEIN
  Auth-Cookie. Aber: keine PII im Pfad; nur eine UUID. Frontend
  darf `localStorage.lastVaultId` nicht setzen, das wäre PII-
  Tracking-Risk.
- **#12 (org-scoping):** Vault-Eintrag-Erstellung scoped, Vault-
  Eintrag-Read public. Cross-org-create nicht möglich (kein Pfad).
- **#19 (Quotas):** Neue Plan-Spalte `monthly_vault_entries_quota:
  int`. Quota-Check beim POST analog zu `check_scan_quota`.
- **#20 (Mollie):** Add-on-Käufe (5€/Eintrag) sind one-time
  payments, nicht subscriptions — Mollie-Flow ist anders, separater
  Endpoint `POST /billing/vault-bundle` mit `quantity: int`.
- **#25 (Append-only):** Vault ist die zweite Tabelle nach
  `audit_logs` mit dieser Garantie. Convention #25 wird erweitert:
  "The retention helpers are the ONLY app-layer code paths that
  DELETE from `audit_logs` AND `audit_evidence`."
- **`docs/retention-policy.md`** wird aktualisiert: Vault-Einträge
  10 Jahre statt 12 Monate (gesetzliche Aufbewahrungsfrist nach
  HGB / AO für Geschäftsunterlagen, nach AVV-Pflicht für Auftrags-
  verarbeitung). Die Diskrepanz zur Scan-Retention (12 Monate) ist
  bewusst — Scans sind operative Daten, Vault-Einträge sind Beweise.

### Aufwand-Schätzung (Single-Dev, überarbeitet)

> **Hinweis zur Schätzung:** Der Wechsel von clientseitigem
> `@react-pdf/renderer` zu serverseitigem PDF-Rendering ist
> kein Refactor, sondern Architektur-Wechsel — der Client
> könnte sonst den Hash vor dem Timestamping manipulieren.
> RFC 3161 + PDF/A-3 mit LTV-Signatur ist Neuland im Repo,
> keine bestehenden Patterns zum Wiederverwenden. Daher
> 2.5 Wochen statt der 2 Wochen aus der Erstschätzung.

| Teilaufgabe | Tage |
|---|---|
| Migration: clientseitiges `@react-pdf/renderer` → serverseitiges Headless-Chromium oder WeasyPrint | 2 |
| Kanonische JSON-Serialisierung (deterministisch, Float-Precision-safe, Encoding-stabil) | 1 |
| RFC 3161 Timestamp-Client gegen FreeTSA + Fallback-Test gegen D-Trust | 2 |
| PDF/A-3 Export mit eingebettetem Hash + Timestamp-Token (LTV signature) | 2 |
| Migration bestehender Reports (Backfill nicht nötig, aber Frontend-Switch + Feature-Flag) | 1 |
| **Backend gesamt** | **8** |
| Frontend (Vault-Page, Verify-Page, Evidence-Button) | 3 |
| Tests + Hardening | 2 |
| **Gesamt** | **~2.5 Wochen** |

---

## Empfohlene Reihenfolge

| Phase | Säule | Aufwand | Warum jetzt? | Risiko |
|-------|-------|---------|--------------|--------|
| **1** | Continuous Monitoring | ~2 Wochen | Größter MRR-Hebel (Free→Pro Conversion-Driver), technisch nahe am bestehenden Scanner-Code, die Diff-Engine ist eine pure function | Niedrig — alle Bausteine (Arq, Mollie, RBAC) existieren |
| **2** | MedTech-Edition | ~1.5 Wochen | `gam-medical.de` als Live-Pilot vorhanden, sofortiger Sales-Hook für DACH-Health-Markt, kein technisches Neuland | Mittel — juristische Recherche-Aufwand für korrekte BfArM/DSK-Zitate |
| **3** | Audit-Vault | ~2.5 Wochen | Premium-Tier, sinnvoll erst wenn Phase 1+2 Traffic + Business-Plan-Konversionen erzeugen, sonst ist die Zahlungsbereitschaft zu gering | Hoch — Server-side PDF-Signing + RFC-3161 sind neu im Stack |

## Migration bestehender Kunden bei Plan-Einführungen

Wenn Säule 2 live geht und der `medtech`-Plan eingeführt
wird, müssen bestehende Kunden auf Health-Sites adressiert
werden — ohne sie zu überraschen oder zu vergrätzen.

| Kundengruppe | Behandlung |
|---|---|
| Bestehende Free-Tier Health-Site-Scans | Bleiben Free, sehen aber im Report einen Soft-Hinweis: "Branchen-Edition verfügbar — buchen Sie ein erweitertes Audit" |
| Bestehende Pro-Tier-Kunden mit Health-Site | Grandfather-Klausel: 6 Monate weiter im Pro-Plan mit MedTech-Findings als Bonus, danach manuelle Migration durch Sales |
| Neue Health-Site-Kunden ab Launch | Sehen MedTech als empfohlenen Plan im Checkout (nicht erzwungen — Pro bleibt wählbar) |

Implementierungs-Konsequenzen:
- Subscription-Modell braucht ein `grandfathered_until: Optional[date]` Feld
- Quota-Logic respektiert Grandfather-Datum vor Plan-Code
- Audit-Log-Eintrag bei jeder Grandfather-Aktivierung
  (Convention #18 — append-only)
- Sales-Dashboard im /admin braucht Filter "Health-Site auf
  Pro-Plan ohne Grandfather" für Outbound-Kampagnen

Analoge Migrations-Strategie wird für jeden zukünftigen
Branchen-Plan benötigt (FinTech, EdTech, HR-Tech) — also
generisch designen, nicht MedTech-spezifisch.

## Cross-cutting changes (alle drei Säulen betreffen)

- **Convention #19 (Plans):** erweitern um drei neue Quota-Felder:
  - `monthly_monitored_domains_quota: int` (Säule 1)
  - `vertical_editions_enabled: tuple[str, ...]` (Säule 2 — leer
    für free/pro, `("medtech",)` für medtech, alle für business)
  - `monthly_vault_entries_quota: int` (Säule 3)
- **`docs/billing.md`** anlegen (heute fehlend) mit der finalen
  Plan-Matrix, Mollie-Price-IDs, Quota-Übersicht. Single source
  of truth für Sales + Support.
- **`docs/architecture.md`** anlegen mit dem Pipeline-Diagramm —
  heute lebt das nur als ASCII-Block in CLAUDE.md. Ergänzt um
  den Monitoring-Loop (Cron → Scan → Diff → Alerter).
- **CLAUDE.md** Conventions ergänzen:
  - **#34 — Continuous Monitoring** (Trigger-Mechanik, Quota,
    Webhook-Signing)
  - **#35 — Vertical Editions** (Plan-Gating, Feature-Flag-Stil)
  - **#36 — Audit-Evidence Append-Only + Retention 10y**

---

## Out-of-Scope für diese Roadmap

Bewusst nicht enthalten — separate Diskussionen:

- **SSO (SAML / OIDC)** — Enterprise-Stage, separater Build, vermutlich
  via WorkOS. Nicht Plattform-USP, sondern Enterprise-Pflicht.
- **White-Label / Reseller** — eigener Plan + Branding-Override-
  System. Erst wenn drei zahlende Reseller-Interessenten da sind.
- **Multi-Region (EU/US-Hosting)** — relevant erst bei US-Enterprise-
  Deals. Heute: EU-only ist der USP, kein Bug.
- **API-First / Public API** — heute fehlt nur der dokumentierte
  Public-Auth-Flow (API-Tokens statt JWT). Kann jederzeit
  nachgeschoben werden, gehört nicht in die Plattform-Säulen.

---

## Konvention für die Datei selbst

Diese Roadmap ist **kein Spec** — sie ist ein **Plan**. Bevor eine
Säule implementiert wird, entsteht ein eigenes:

- `docs/specs/saeule-1-continuous-monitoring.md`
- `docs/specs/saeule-2-medtech-edition.md`
- `docs/specs/saeule-3-audit-vault.md`

…mit konkreten Models, Endpoints, Tests, Edge Cases, Migration-
Skripten, Mollie-Webhook-Handling. Diese Roadmap definiert **was**
gebaut wird; die Specs definieren **wie**.

Bei jedem Spec gilt:
1. Convention-#2-Lockstep zwischen `models.py` und `types.ts` ist
   Pflicht.
2. Mindestens ein Tenant-Isolation-Test pro neuem Endpoint
   (Convention #12).
3. Plan-Quota-Check VOR Rate-Limit-Check VOR SSRF-Check; das
   Reihenfolge-Muster aus Convention #19 ist load-bearing für
   die UX (richtige HTTP-Codes pro Fehlerursache).
4. Append-only-Garantien (Säule 3) müssen in CLAUDE.md
   dokumentiert sein, bevor der erste Insert-Statement gemerged
   wird.

---

*Letztes Update: 2026-04-26. Dieser Plan ersetzt keine Architektur-
Entscheidungen — er bündelt sie. Strittiges → Spec-Phase → Decision-
Doc → Code.*
