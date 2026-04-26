# Sprint 0 — Fundament für Continuous Monitoring

> **Status:** Spec, kein Code. Definiert Models, Endpoints, Tests
> und Edge Cases für die drei Features die VOR Säule 1 entstehen
> müssen. Aufwände sind Single-Dev-Schätzungen. Nach Sprint 0
> entstehen Specs für Säule 1, 2, 3 separat.
> **Anker:** [CLAUDE.md](../../CLAUDE.md), insb. Conventions
> #2, #11, #12, #14, #15, #19, #25, #28, sowie
> [docs/roadmap-platform.md](../roadmap-platform.md). Es existiert
> heute kein eigenständiges `docs/architecture.md` — die
> Pipeline-Logik lebt in CLAUDE.md "Pipeline overview" + dem Code
> unter `backend/app/scanner.py` + `backend/app/modules/`.

---

## Warum Sprint 0 existiert

**Säule 1 (Continuous Monitoring) ist ohne diese drei Features
unbenutzbar.** Ein täglicher Re-Scan ohne Suppression-Mechanismus
erzeugt für jede Org binnen einer Woche Hunderte identischer
Alerts ("noch immer kein Reject-Button auf der Subseite X") und
trainiert den DPO darauf, die Mails zu ignorieren — Alert-Fatigue
killt die Reten­tion bevor sie aufgebaut werden konnte. Reject-All-
Simulation ist parallel der größte echte Wettbewerbsvorteil heute:
keiner der Konkurrenten testet, ob "Alle ablehnen" tatsächlich
Tracking blockt — der Markt prüft nur "Accept-All". Wer Reject als
Erstes strukturiert ausliefert, hat einen unmittelbaren Sales-
Hook in jedem Audit-Gespräch.

**Reihenfolge ist nicht beliebig.** Custom Findings entsteht zuerst,
weil das DB-Schema (`suppressed_finding` Tabelle + Fingerprint-Logik)
Vorgriffe auf die Reject-Simulation hat (deren neue Findings müssen
ebenfalls suppressbar sein) und auf das PDF-Branding (Suppressed-
Findings müssen im PDF mit "Akzeptiert"-Pin gerendert werden,
nicht weggelassen). Reject-Simulation kommt zweitens, weil sie auf
dem bestehenden `consent_clicker.py` aufbaut und die größte Stand-
Alone-Komponente ist. PDF-Branding zuletzt, weil es nur die
Render-Schicht berührt und die anderen beiden Features in den
generierten Reports konsumiert. Die Aufwände summieren sich auf
**8 Tage Backend + Frontend** (3 + 3 + 2), ohne Tests +
Hardening (≈2 zusätzliche Tage).

---

## Sprint-0-Gate: Sales-Pilot parallel

Während Sprint 0 läuft (8 Tage Backend + Frontend), läuft parallel
ein Sales-Pilot. Ziel: validieren ob Pricing + Pitch funktionieren
BEVOR weitere 8 Wochen in Säule 1-3 fließen. Code-Arbeit ohne
Sales-Validierung ist Frühpolitur eines Produkts das niemand
gekauft hat.

| Tag | Sales-Aktion |
|-----|--------------|
| Tag 1 | 5 LinkedIn-Nachrichten an Health-Site-Geschäftsführer in Berlin (gam-medical.de Paul Gramlich + 4 vergleichbare) |
| Tag 3 | Follow-up an die ersten 5, weitere 5 Erstkontakte |
| Tag 5 | Bei 0 Antworten → Pitch + Pricing überarbeiten, NICHT weiter Code schreiben |
| Tag 7 | Bei 1+ Antwort → Sales-Call führen, Sprint A planen mit Kundenfeedback |
| Tag 8 | Sprint-0-Code merge-ready, Sales-Insights in Roadmap einarbeiten |

**Gate-Regel:** Wenn nach Sprint 0 KEIN einziger Sales-Call geführt
wurde, geht Sprint A NICHT los. Stattdessen: Pricing-Tag, Pitch-
Iteration, neue 10 Outreaches. Code-Arbeit pausiert. Diese Regel
ist hart — der häufigste Grund, warum Solo-Founder-SaaS nach 6
Monaten an der Wand stehen, ist die Annahme "wenn ich noch ein
Feature baue, kommen die Kunden". Sie kommen nicht. Sales-Validation
zuerst, Code danach.

**Was bedeutet "ein Sales-Call"?** Mindestens 20 Minuten Gespräch
mit Entscheider:in (Geschäftsführung, DPO, IT-Leitung), in dem
mindestens einer dieser drei Punkte konkret diskutiert wurde:
(a) Wie viel würden Sie monatlich für eine Live-Compliance-
Überwachung zahlen, (b) Welches Feature wäre für Sie der
Buying-Trigger, (c) Wann wäre der frühestmögliche Vertragsstart.
"Vielleicht später" zählt nicht. "Schicken Sie mir Infomaterial"
zählt nicht. Konkrete Zahlen oder konkretes Datum.

---

## Feature 1 — Custom Findings (Suppression)

### Ziel
Auditor markiert ein Finding als **"false positive"** oder
**"akzeptiertes Risiko"** → bei nächstem Re-Scan wird das Finding
nicht erneut als Alert geworfen, taucht aber im Report mit Hinweis-
Badge auf ("Akzeptiert von <user>, Grund: <reason>"). Beim Risk-
Scoring werden suppressed Findings **NICHT** abgezogen — der Score
spiegelt die kommunizierte Risiko-Toleranz wider, nicht eine
schöngerechnete Realität. Diese Trennung ist load-bearing für die
Audit-Glaubwürdigkeit: ein DPA-Prüfer muss erkennen können, was
das Tool gefunden UND was der Operator bewusst akzeptiert hat.

### Datenmodell

**Neue Tabelle:**

```sql
suppressed_finding
  id                       UUID PK
  organization_id          UUID NOT NULL
                           REFERENCES organization(id) ON DELETE CASCADE
  fingerprint              TEXT NOT NULL          -- siehe "Fingerprint-Logik"
  finding_kind             TEXT NOT NULL          -- "policy_issue" | "hard_cap" | "dark_pattern" | "form_issue" | "tracking_pixel"
  reason_code              TEXT NOT NULL          -- "false_positive" | "accepted_risk" | "compensating_control"
  reason_note              TEXT                   -- nullable, freitext-Begründung (max 500 chars)
  suppressed_by_user_id    UUID REFERENCES "user"(id) ON DELETE SET NULL
  suppressed_at            TIMESTAMPTZ NOT NULL
  expires_at               TIMESTAMPTZ            -- nullable; ohne Wert = unbefristet
  revoked_at               TIMESTAMPTZ            -- nullable; soft-delete
  revoked_by_user_id       UUID REFERENCES "user"(id) ON DELETE SET NULL
  UNIQUE (organization_id, fingerprint, revoked_at)
  INDEX (organization_id, revoked_at)
```

**Migration:** Alembic Revision, idempotent. Per Convention #27
muss SQLite die `ON DELETE CASCADE`-Constraints via `PRAGMA
foreign_keys=ON` enforcen — bestehender Pragma-Listener deckt das ab.

**Soft-delete statt Hard-delete:** `revoked_at IS NOT NULL` markiert
revoked, der UNIQUE-Constraint inkludiert die Spalte damit ein
revoked Finding später erneut suppressed werden kann. Hard-delete
würde den Audit-Trail brechen — gleicher Stil wie Convention #25
(Audit-Logs). Retention-Sweep löscht revoked Suppressions nach 3
Jahren analog zu Audit-Logs.

### Fingerprint-Logik

Das Fingerprint identifiziert ein Finding **stabil über Re-Scans
hinweg**, ohne von volatilen Feldern abhängig zu sein (Score,
Timestamp, Excerpt-Index). Pure function, deterministisch.

```python
def fingerprint(finding_kind: str, payload: dict) -> str:
    """SHA-256 hex über die kanonisch sortierte JSON-Repräsentation
    der Identifikations-Schlüssel des Findings."""
```

**Identifikations-Schlüssel pro `finding_kind`:**

| Kind | Schlüsselfelder |
|---|---|
| `policy_issue` | `category` + normalisierter `description` (lowercase, whitespace-collapsed, max 200 chars) |
| `hard_cap` | `code` |
| `dark_pattern` | `code` |
| `form_issue` | normalisierte `form_action` + sortierte Issue-Codes-Liste |
| `tracking_pixel` | `registered_domain` + Path-Pattern (z.B. `/tr` für Meta) |

**Was NICHT in den Fingerprint gehört:** Score, Timestamp, AI-
generierte `description` Sätze (variieren zwischen Runs), `excerpt`
(zitiert volatile Policy-Stellen). Wenn eine Policy umgeschrieben
wird und derselbe Mangel weiter existiert, soll das Fingerprint
gleich bleiben — sonst muss der DPO denselben Akzeptanz-Vermerk
nach jeder Policy-Änderung neu setzen.

**Edge case Documentation:** wenn ein Finding leicht variiert
(z.B. die AI-Description generiert beim nächsten Lauf ein anderes
Synonym), könnte das Fingerprint kollidieren oder differieren.
Konservativ: nur stabile Strukturfelder im Fingerprint, niemals
LLM-Output. Test-Case unten verifiziert dies.

### Backend-Module

- **`app/findings/suppressions.py`** — pure async functions:
  - `compute_fingerprint(kind: str, payload: dict) -> str`
  - `is_suppressed(org_id: UUID, fingerprint: str, session) -> bool`
  - `list_active_suppressions(org_id: UUID, session) -> list[Suppression]`
  - `apply_suppressions_to_scan(scan: ScanResponse, org_id: UUID, session) -> ScanResponse`
    annotiert jedes Finding mit `is_suppressed: bool` + `suppression_reason: str | None`

- **`app/routers/findings.py`** — neue Routes:
  - `POST /findings/suppress` — body: `{scan_id, finding_kind, payload, reason_code, reason_note?, expires_at?}` → 201 mit Suppression-ID
  - `DELETE /findings/suppress/{suppression_id}` — soft-delete, setzt `revoked_at` + `revoked_by_user_id`
  - `GET /findings/suppressions?status=active|revoked|all&limit=50` — paginiert
  - Alle Routes scoped per `organization_id` (Convention #12), cross-tenant 404, `tests/test_auth.py::TestTenantIsolation` bekommt zwei neue Cases.

- **`app/scanner.py` Anpassung** — am Ende von `run_scan()`,
  nach dem Persist via `save_scan`: `apply_suppressions_to_scan`
  läuft inline, BEVOR die Response zurück geht. Für **async-Mode**
  (Convention #15, #16) läuft das im Worker-Prozess analog vor dem
  `mark_done`. Die Suppression-Annotation IST Teil des
  Scan-Snapshots — sonst zeigt der ÄLTERE Report keine Suppression-
  Pins, und der DPO sieht beim Re-Lesen verwirrt einen "akzeptiert"-
  Pin der erst nach dem Scan gesetzt wurde.

### Scoring-Anpassung

`compute_risk` lässt suppressed Findings **unangetastet** im
Score-Beitrag. Begründung im Code-Kommentar erforderlich:

```python
# Suppressed findings DO NOT reduce score deductions. The score
# reflects the audit-evidenced reality of the site, not the
# operator's risk tolerance. Suppression only silences alerts +
# annotates the report; the underlying score signal is preserved
# for DPA + insurance review.
```

**Test-Pin:** ein Test, der einen Scan mit suppressed `google_fonts_external`
laufen lässt und prüft dass der Cap-Wert (55) trotzdem im Score
ankommt. Sub-Score-Badge im Frontend zeigt den Cap weiter — nur
der Alert-Pfad (Säule 1 später) liest `is_suppressed` und stille.

### Frontend

- **Pro Finding-Card** ein neues kleines Pin-Set:
  - Vor Suppression: dezenter "✕ Akzeptieren / Als false positive
    markieren"-Link unten rechts in der Card.
  - Klick öffnet Modal: Reason-Code (Radio: `false_positive` /
    `accepted_risk` / `compensating_control`), optional Freitext,
    optional Ablaufdatum (Default: unbefristet). "Bestätigen"-Button.
  - Nach Suppression: Card behält Finding-Inhalt, kriegt grauen
    Overlay-Streifen oben mit "Akzeptiert von <user> am <date>
    · <reason_code> · [Aufheben]".

- **Settings-Page `/settings/suppressions`** (Org-Admin only):
  Liste aller aktiven Suppressions, Filter nach `finding_kind`,
  Bulk-Revoke-Button. Audit-Log-Eintrag bei jedem Revoke
  (Convention #18 erweitern: `suppression.revoked` ist ein
  privilegierter Action-Type).

- **PDF-Render:** Suppressed Findings im Big4-PDF kriegen eine
  zusätzliche Zeile in der FindingCard ("Status: Akzeptiert ·
  von <user> · Grund: <reason>"). Tracker-Row zeigt Status
  "Akzeptiert" statt "Offen".

### Convention-Hinweise

- **#2:** `Suppression` Pydantic-Modell + frontend `Suppression`-
  Interface, gleichnamig.
- **#12:** `organization_id` an JEDEM Read/Write der Tabelle,
  Cross-Tenant 404. Neuer Test:
  `test_cross_tenant_cannot_revoke_other_orgs_suppression`.
- **#14:** Rate-Limit auf POST `/findings/suppress`: 30/min
  pro Org (höher als Scan-Limit, weil Bulk-Suppress in der
  Settings-Page realistisch ist).
- **#18:** Suppression + Revoke schreiben Audit-Log-Einträge
  (`finding.suppressed`, `finding.revoked`) mit Fingerprint
  in `details`, NICHT mit dem PII-haltigen `reason_note`.
- **#19:** Quota-Erweiterung: `monthly_suppressions_quota:
  int = 0` für free, `100` für pro, unlimited (`0`) für
  business. Im Plan-Catalogue analog zu Scan-Quota.
- **#25:** Retention-Sweep wird um eine vierte Funktion
  erweitert: `purge_revoked_suppressions_older_than(years=3)`.

### Edge Cases / Risks

| Risiko | Mitigation |
|---|---|
| Zwei DPOs suppressen denselben Finding fast gleichzeitig (Race) | UNIQUE-Constraint auf (org_id, fingerprint, revoked_at IS NULL) — DB-Level, deterministisch |
| Fingerprint-Drift wenn ein Cap-Code umbenannt wird | Migrations-Skript bei Cap-Renames muss Suppression-Fingerprints mappen. Dokumentiert in CLAUDE.md Convention bei `_CAP_AFFECTS`-Erweiterung. |
| Permanente Suppression eines kritischen Findings durch unaufmerksamen Praktikanten | Audit-Log + /settings/suppressions sichtbar für Owner/Admins; Suppressions von HIGH-Severity Findings emittieren Audit-Event mit Schwellen-Tag, Sales-Dashboard kann filter "HIGH suppressed in last 7d" für Account-Health-Reviews |
| Suppressed Finding im PDF — DPA-Prüfer denkt es ist erledigt | "Akzeptiert"-Pin mit Begründung explizit im PDF, nicht weggelassen. Methodology-Page erklärt die Trennung Score ≠ Alert. |

### Tests

- `tests/test_suppressions.py`:
  - `test_compute_fingerprint_stable_across_runs` (gleicher Input → gleicher Hash, 100×)
  - `test_compute_fingerprint_excludes_volatile_fields` (AI-generierte Description-Synonyme produzieren KEIN unterschiedliches Fingerprint)
  - `test_apply_suppressions_annotates_finding` (suppression in DB → finding kommt mit `is_suppressed=true` zurück)
  - `test_score_unchanged_by_suppression` (Cap-Score bleibt erhalten)
  - `test_revoke_then_resuppress_succeeds` (UNIQUE-Constraint inkl. revoked_at zulässt das)
- `tests/test_auth.py::TestTenantIsolation`:
  - `test_cross_tenant_cannot_read_suppressions`
  - `test_cross_tenant_cannot_revoke_other_orgs_suppression`

### Aufwand-Schätzung

| Teilaufgabe | Tage |
|---|---|
| Migration + Suppression-Modul + Routes + Audit-Log-Wiring | 1.5 |
| Scanner-Hook (apply_suppressions inline) + Tests | 0.5 |
| Frontend Modal + FindingCard-Annotation + Settings-Page | 1 |
| **Gesamt** | **3 Tage** |

---

## Feature 2 — Reject-All Consent-Simulation

### Ziel
Heute simuliert der Scanner nur **Accept-All**: Click auf "Alle
akzeptieren" + Diff zum Pre-Consent-State. Die Lücke: niemand
prüft, ob "Alle ablehnen" auch tatsächlich Tracking blockt — viele
Banner zeigen einen Reject-Button, lassen aber Pixel/Cookies
trotzdem laufen. Auditoren prüfen genau das. Dieser Feature liefert
einen **dritten Pass**, der Reject-All klickt und einen separaten
Diff erzeugt. Wenn Reject neue Tracker zum Pre-Consent-State
hinzufügt → HIGH-Finding, denn der Banner lügt.

### Datenmodell

**Erweiterung des bestehenden `ConsentSimulation`-Modells**
([app/models.py](../../backend/app/models.py)):

```python
class ConsentSimulation(BaseModel):
    enabled: bool
    accept_clicked: bool
    cmp_detected: str | None
    note: str
    pre_summary: dict[str, int] = {}
    post_summary: dict[str, int] = {}
    diff: ConsentDiff | None
    ux_audit: ConsentUxAudit | None

    # NEU — Reject-All Phase. Optional wie post_*: nur befüllt
    # wenn `consent_simulation` requestet UND ein Reject-Button
    # aufgespürt wurde.
    reject_clicked: bool = False
    reject_summary: dict[str, int] = {}
    reject_diff: ConsentDiff | None = None

    # NEU — Reject-spezifische Findings, getrennt von ux_audit.findings
    # damit der DPO im UI klar sieht "das hier ist ein Reject-Bug".
    reject_findings: list[DarkPatternFinding] = []
```

**Neuer `DarkPatternCode`** in `models.py`:

```python
DarkPatternCode = Literal[
    # ... bestehende ...
    "reject_does_not_block_trackers",      # Reject geklickt, neue Tracker laufen trotzdem
    "reject_button_not_found",             # Banner hat keinen erkennbaren Reject-Button
]
```

**Convention #2:** Beide neuen Felder + Codes auch in
`frontend/lib/types.ts`.

### Backend-Module

- **`app/modules/consent_clicker.py`** wird symmetrisch erweitert:
  - Bestehender `try_click_accept(...)` bleibt.
  - Neu: `try_click_reject(...)` — gleiche 19 CMP-Selektoren-Map,
    aber per CMP der Reject-Pfad (z.B. OneTrust:
    `#onetrust-reject-all-handler`, Cookiebot: `#CybotCookiebotDialogBodyButtonDecline`).
  - Neu: Multilingual-Text-Fallback-Liste für Reject:
    `Alle ablehnen|Reject all|Alles ablehnen|Refuse all|Decline|Tout refuser|…`.

- **`app/scanner.py`** — neuer dritter Browser-Context wenn
  `consent_simulation=true`:

```
pre_ctx        → already exists (no banner click)
accept_ctx     → already exists (click Accept-All, full crawl)
reject_ctx     → NEW (click Reject-All, full crawl)
```

  Sequentiell, nicht parallel — eine Browser-Instance, drei
  Contexts hintereinander. Cost: ~+30s pro Scan, deshalb gated
  via `consent_simulation` Flag (das ist heute schon opt-in).

- **`app/modules/consent_diff.py`** — bestehendes
  `compute_consent_diff(pre, post)` wird erweitert:
  - Neu: `compute_reject_diff(pre, reject) -> ConsentDiff` —
    derselbe Diff-Algorithmus, aber semantisch anders interpretiert:
    new_marketing_count > 0 ⇒ Banner lügt.

- **Neuer Heuristik-Block in `consent_ux_audit.py`** (analog zu
  cookie_wall_detector.py / Convention #31):
  - Wenn `reject_diff.new_marketing_count > 0` OR
    `reject_diff.new_analytics_count > 0` →
    `DarkPatternFinding(code="reject_does_not_block_trackers",
    severity="high", description=...)`.
  - Wenn Reject-Button nicht gefunden →
    `DarkPatternFinding(code="reject_button_not_found",
    severity="medium", ...)`.

### Scoring-Anpassung

Neuer Hard-Cap in `scoring.py`:

| Cap-Code | cap_value | affected_subscores |
|---|---|---|
| `reject_ignored` | 35 | `("tracking", "cookies")` |

Trigger: irgendein `DarkPatternFinding(code="reject_does_not_block_trackers", ...)`
in `consent.reject_findings`. Härter als
`consent_dark_pattern_high` (45) — Reject-Bug ist *nachweislich*
ungültige Einwilligung, nicht nur "wahrscheinlich".

`_CAP_AFFECTS` Eintrag: `"reject_ignored": ("tracking", "cookies")`.
`TestCapAffectsMapping::test_every_emitted_cap_code_has_mapping_entry`
deckt das automatisch ab — ein vergessener Eintrag bricht CI.

**Bilinguale Recommendation** in `scoring.py` `code_details` Map:
- Title (DE): "Reject-Button blockiert Tracking nicht — Banner ist
  nicht-konform"
- Detail: zitiert EuGH Planet49 Tz. 49 ("Einwilligung muss in
  einem Klick widerrufbar sein"), nennt die nach Reject
  weitergeladenen Domains konkret, gibt Fix-Pfad ("CMP-Konfiguration
  prüfen, Tag-Manager-Trigger an Consent-State binden").

### Frontend

- **`/scan/[id]` ConsentSection erweitert:**
  - Heute zeigt sie pre/post Diff. NEU: drei Spalten oder Tabs —
    "Vor Consent · Nach Accept · Nach Reject".
  - Nach-Reject-Spalte zeigt Diff zum Pre-State; rote Highlights
    auf Marketing/Analytics-Hits.
  - Wenn `reject_findings` Einträge hat: prominenter roter
    Alert-Block "Reject-Bug gefunden" oben in der Section.

- **PDF (PdfReport.tsx):** im Privacy-Chapter unter "Consent-
  Simulation" wird die dreispaltige Übersicht gerendert. Bei
  `reject_does_not_block_trackers`-Finding bekommt die Cover-
  Page einen zusätzlichen "Reject Bug Detected"-Pin neben dem
  Risk-Score.

### Convention-Hinweise

- **#3:** Pre-Consent-State bleibt der Scoring-Anker. Reject-Diff
  ist informational im Sinne von "verifying a CLAIM the banner
  makes" — er fließt nur über den Hard-Cap, nicht ins Sub-Score-
  Gewicht.
- **#13:** Der dritte Browser-Context erbt denselben SSRF-Guard.
  Kein separater Code-Pfad nötig.
- **#28-#31:** Reject-Findings reihen sich in das bestehende
  `DarkPatternFinding`-System ein.

### Edge Cases / Risks

| Risiko | Mitigation |
|---|---|
| Banner hat Reject erst auf 2. Ebene (Settings-Modal) | Klick-Sequenz erweitern: erst Settings öffnen, dann Reject — fallback-Pfad in `try_click_reject` mit Pattern `Settings → Reject all` |
| Reject schließt Modal aber lädt Page nicht neu, Tracker waren schon im Pre-State drin | Vergleichsbasis ist Pre-Consent (sauber) — Diff zeigt nur, was NACH Reject zusätzlich kam. Sauber semantisch. |
| Site hat keine Banner überhaupt | `reject_clicked=false`, `reject_findings=[]`, kein Cap. Sauberer No-Op. |
| Reject-Click crasht den Browser | Try/except um den Reject-Pass; im Fehlerfall `reject_clicked=false` + Warning-Log. Pre + Accept-Pass werden nicht zurückgehalten. |
| Multi-CMP Sites (Hauptbanner Cookiebot, Sub-Banner Borlabs) | Erste CMP gewinnt, dokumentierte Limitation. Selten in der Praxis. |

### Tests

- `tests/test_reject_simulation.py`:
  - Unit: `try_click_reject` matched OneTrust / Cookiebot / Borlabs / Usercentrics — gemockter Page mit jeweils erwartetem Selector
  - Unit: `compute_reject_diff` ist symmetrisch zu `compute_consent_diff`
  - Unit: `DarkPatternFinding(code="reject_does_not_block_trackers")` wird emittiert wenn `reject_diff.new_marketing_count > 0`
  - Integration (mocked Playwright): scan mit `consent_simulation=true` → ConsentSimulation hat befüllte reject_*-Felder
- `tests/test_scoring.py`:
  - Pin: `reject_ignored` cap fired bei reject_findings
  - Pin: `_CAP_AFFECTS["reject_ignored"] == ("tracking", "cookies")`

### Aufwand-Schätzung

| Teilaufgabe | Tage |
|---|---|
| Reject-Selectors für 19 CMPs + Multilingual-Fallback | 1 |
| Dritter Browser-Context in scanner.py + Diff + Findings | 1 |
| Hard-Cap + bilinguale Recommendation + Tests | 0.5 |
| Frontend ConsentSection-Update + PDF-Erweiterung | 0.5 |
| **Gesamt** | **3 Tage** |

---

## Feature 3 — PDF-Branding pro Kunde

### Ziel
Pro Org: eigenes Logo (oben auf Cover) + Brand-Primary-Color
(ersetzt das MSA-Teal in Header-Streifen, Score-Akzent, Section-
Titles). White-Label-tauglich — für Pro/Business gedacht, Free
Tier behält MSA DataX Branding. Voraussetzung für Säule 2
(MedTech-Edition) — eine Praxis brandet ihren eigenen Audit-
Report.

### Datenmodell

**Erweiterung des bestehenden `Organization`-Modells:**

```sql
ALTER TABLE organization
  ADD COLUMN logo_url           TEXT,           -- nullable; storage URI
  ADD COLUMN brand_color_primary TEXT,           -- nullable; "#0891b2" Hex
  ADD COLUMN brand_color_text    TEXT;           -- nullable; "#0f172a" Hex
```

Brand-Settings sind **org-scoped, nicht user-scoped**: ein Wechsel
betrifft alle Reports der Org gleichermaßen. Die Werte werden in
den Scan-Snapshot zum Zeitpunkt der Generierung KOPIERT (siehe
"Snapshot-Stempel" unten), damit ein später geändertes Logo
historische Reports nicht rückwirkend verändert.

**Snapshot-Stempel:** der `ScanResponse` bekommt drei optionale
Felder:

```python
class ScanResponse(BaseModel):
    # ... bestehende ...
    branded_logo_url: str | None = None
    branded_color_primary: str | None = None
    branded_color_text: str | None = None
```

Beim Persist im Scanner (`storage.save_scan`) werden die Org-
Werte einmalig kopiert. PDF-Render liest aus dem ScanResponse,
nicht aus der Org-Tabelle direkt — historische Reports bleiben
mit ihrem ursprünglichen Branding stabil. Audit-relevant:
ein Report bleibt visuell identisch zu seinem Erzeugungs-
Zeitpunkt, auch nach Logo-Wechsel.

### Logo-Storage

**Single-host Phase (heute):** lokal unter `/var/lib/msadatax/logos/<org_id>.png`,
Caddy proxied `/static/logos/*` direkt. Größenlimit 200 KB,
Format PNG/JPEG/WebP, max. 800×400 px (Pillow-Resize beim Upload
falls überschritten).

**Multi-Host-Zukunft:** S3-kompatible Storage via `BLOB_STORAGE_URL`
ENV. Code-Pfad bleibt identisch, nur das Backend hinter dem
URI-Schema ändert sich. Jetzt nicht implementieren, aber das
`storage_uri` als TEXT speichern (nicht `path`!) macht den
späteren Switch trivial.

### Backend-Module

- **`app/branding/uploader.py`**:
  - `validate_logo(file: UploadFile) -> ValidatedLogo`:
    Content-Type-Check, Magic-Byte-Sniffing (nicht nur Extension —
    Convention #13-Style Defense), Größenlimit 200 KB.
  - `resize_if_needed(image_bytes, max_w=800, max_h=400) -> bytes`:
    Pillow-Resize, Aspect-Ratio-bewahrend.
  - `store_logo(org_id, image_bytes) -> storage_uri` — schreibt
    auf den lokalen Pfad oder S3 je nach `BLOB_STORAGE_URL`.
  - `delete_logo(org_id)` — auch wenn Org gelöscht wird (Cascade-
    Trigger im Org-Delete-Path).

- **`app/routers/branding.py`**:
  - `POST /branding/logo` (multipart) — Owner/Admin only via
    `require_org_admin`. Body: file. Returns: `{logo_url, size_bytes, dimensions}`.
  - `DELETE /branding/logo`
  - `PATCH /branding/colors` — body: `{primary?: "#hex", text?: "#hex"}`. Hex-Validation regex.
  - `GET /branding` — current org branding state.

- **`app/scanner.py`**: am Ende von `run_scan`, vor dem Return,
  Branding-Snapshot kopieren:
  ```python
  org = await get_organization(req.organization_id, session)
  result.branded_logo_url = org.logo_url
  result.branded_color_primary = org.brand_color_primary
  result.branded_color_text = org.brand_color_text
  ```

### Frontend

- **`/settings/branding`** Page (Owner/Admin only):
  - Logo-Upload-Dropzone, Live-Preview im A4-Cover-Mockup rechts
  - Color-Picker für Primary + Text (mit Reset-zu-Default-Button)
  - "Vorschau-PDF generieren"-Button — rendert ein Sample-PDF mit
    aktuellem Branding ohne dass dafür ein echter Scan nötig ist
  - Plan-Gating: Free sieht "Upgrade auf Pro für Custom-Branding"
    statt der Upload-Felder

- **`PdfReport.tsx`**:
  - `CoverPage` rendert `result.branded_logo_url` falls vorhanden,
    sonst MSA-Logo. Logo skaliert auf max. 80pt Höhe.
  - `ClassificationRibbon` + Footer + Section-Titles nutzen
    `result.branded_color_primary` falls vorhanden, sonst
    `COLORS.classification` / `COLORS.brand`.
  - **Free-Tier-Garantie:** wenn Org auf Free-Plan ist, werden
    `branded_*`-Felder beim Snapshot ignoriert (Backend stempelt
    nur wenn Plan ≠ free). PDF behält MSA-Branding.

### Convention-Hinweise

- **#2:** `Organization` und ScanResponse-Snapshot-Felder in
  models.py + types.ts.
- **#13 (SSRF):** Logo-URLs sind self-hosted, kein Risiko hier.
  Aber: Multi-Host-Phase mit S3-pre-signed URLs muss
  Convention #13 erneut prüfen — ein attacker könnte versuchen,
  via gefälschter PATCH-Request eine `logo_url` auf eine interne
  Adresse zu setzen und das PDF-Render-Backend zum SSRF zu
  zwingen. Daher: `logo_url` ist NIEMALS user-supplied URL,
  sondern server-side-gesetzt nach Upload.
- **#19:** Quota-Erweiterung: `custom_branding_enabled: bool`.
  Free=false, Pro/Business=true. Branding-Routes 402 wenn Plan
  branding nicht erlaubt.

### Edge Cases / Risks

| Risiko | Mitigation |
|---|---|
| Kunde lädt PNG mit Alpha-Channel hoch, schwarzer Cover-Streifen wird darunter sichtbar | Cover-Streifen ist solid Brand-Color, Logo wird mit weißem Backdrop unterlegt im PDF — Pillow-Layer-Composit oder PdfReport-Rendering-Logic |
| Color-Picker liefert ungültiges Hex ("#GGGGGG") | Backend regex-validation `^#[0-9a-fA-F]{6}$`, frontend HTML5 `<input type="color">` |
| Org wechselt Logo, Kunde lädt alten Report in PDF runter — sollte das alte Logo zeigen? | Snapshot-Stempel garantiert Stabilität: alter Report = altes Logo. Wenn der Kunde den NEUEN Branding will, muss er den Scan neu generieren. |
| 50 Orgs uploaden 200KB-Logos → 10MB Storage. 5000 Orgs = 1GB | Heute akzeptabel (single-host); bei Multi-Host-Phase auf S3 + CDN umstellen, ist im Code-Pfad schon vorgesehen |
| Logo enthält illegales Material (Hassrede, Markenrechtsverletzung) | Out-of-scope für Sprint 0. Escalation-Path: Admin im /admin sieht alle hochgeladenen Logos, kann manuell löschen. Convention #18 audit-loggt das. |

### Tests

- `tests/test_branding.py`:
  - `test_logo_upload_resizes_oversized_image`
  - `test_logo_upload_rejects_non_image_magic_bytes`
  - `test_logo_upload_rejects_oversized_file`
  - `test_color_patch_validates_hex`
  - `test_branding_snapshot_copied_to_scan_response`
  - `test_branded_response_unchanged_after_org_logo_update` (immutability)
- `tests/test_auth.py::TestTenantIsolation`:
  - `test_cannot_set_other_orgs_branding`
  - `test_cannot_delete_other_orgs_logo`

### Aufwand-Schätzung

| Teilaufgabe | Tage |
|---|---|
| Migration + Branding-Model + Uploader + Routes + Audit-Wiring | 1 |
| PdfReport-Branding-Hooks + Snapshot-Mechanik | 0.5 |
| Frontend Settings-Page + Live-Preview | 0.5 |
| **Gesamt** | **2 Tage** |

---

## Cross-cutting Sprint-0-Themen

### i18n
Drei neue Key-Gruppen, jeweils DE+EN:
- `findings.suppress.*` (Modal-Texte, Reason-Codes, Status-Pins)
- `consent.reject.*` (UI-Section-Titel, Findings-Texte,
  Recommendations)
- `branding.*` (Settings-Page, Upload-Dropzone, Color-Picker)

### Migrations-Reihenfolge
Drei Alembic-Revisions, abhängig in dieser Sequenz:

1. `add_suppressed_finding_table` — neue Tabelle, kein
   Bestandsdaten-Touchpoint.
2. `extend_organization_with_branding` — `Organization`
   bekommt drei nullable Spalten. Bestehende Orgs auf Default
   `NULL` (kein Branding gesetzt). Idempotent.
3. `add_reject_fields_to_scan` — wenn `ScanResponse` als JSONB
   in `scan.payload` lebt: keine Migration nötig (Pydantic-
   Defaults greifen). Wenn als typisierte Spalten: drei nullable
   JSONB-Felder ergänzen.

### CLAUDE.md Convention-Updates (nach Sprint 0)

Neue Convention-Entries, NACH Implementation, NICHT vorab:

- **#34** — Suppression-Mechanik (Fingerprint-Stabilität, Score
  bleibt erhalten, append-only mit revoked_at)
- **#35** — Reject-Pass als drittes Browser-Context, Hard-Cap
  `reject_ignored` über `consent_dark_pattern_high` priorisiert
- **#36** — Branding-Snapshot-Stempel: PDF-Reports sind visuell
  immutable nach Erstellung

### Definition of Done

Sprint 0 ist fertig wenn:

- [ ] Alle drei Features im UI klickbar + im PDF gerendert
- [ ] `pytest` voll grün (heute 465, Erwartung +20-25 neue Tests)
- [ ] `npx tsc --noEmit` grün, `npx next lint` ohne neue Errors
- [ ] Migrations idempotent (auf SQLite + Postgres getestet)
- [ ] Mindestens ein Sales-Call laut Gate-Regel geführt
- [ ] CLAUDE.md Conventions #34-#36 ergänzt
- [ ] Sprint-A-Spec (Säule 1) gestartet mit Sales-Insights als
      Input

---

## Out-of-Scope für Sprint 0

Bewusst nicht enthalten — kommen in den jeweiligen Säulen-Specs:

- **E-Mail-Versand der Reports** — Säule 1 (gleiches SMTP-Setup)
- **Slack/Teams-Webhooks** — Säule 1 (gleicher Webhook-Adapter)
- **Public Share-Links** — eigener Sprint zwischen Säule 1 und 2
- **API-Tokens / CLI / Pre-Deploy-Webhook** — eigenes "DevOps-
  Triplet"-Sprint nach Säule 1
- **Vault-Eintrag erstellen aus suppressed Findings heraus** —
  Säule 3 (Audit-Vault)
- **Bulk-Suppress über CSV-Import** — wartet auf Customer-Demand
- **MedTech-spezifisches Suppression-Reason-Code** ("rechtfertigt
  Art. 9 Verarbeitung weil…") — Säule 2 (MedTech-Edition)

---

## Konvention für die Datei selbst

Diese Spec ist **bindend** für die Sprint-0-Implementation —
Abweichungen erfordern ein Update dieser Datei VOR dem
betreffenden Commit. Teststrategie ist nicht optional: jeder
unten gelistete Test-Case ist Teil von "Definition of Done".

Bei Konflikt zwischen dieser Spec und CLAUDE.md gilt CLAUDE.md
— die Conventions sind das verbindliche Architektur-Dokument,
diese Spec ist eine Anwendung davon.

*Letztes Update: 2026-04-26.*
