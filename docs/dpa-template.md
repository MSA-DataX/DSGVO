# Data Processing Agreement (Template)

> **This is a template, not legal advice.** Before executing with a
> real customer, run it past your lawyer. The placeholders in angle
> brackets `<LIKE_THIS>` need filling in per deal.

---

## Data Processing Agreement
### between the Parties named below, pursuant to Art. 28 GDPR

**Controller** ("Customer"):
- Name: `<CUSTOMER_LEGAL_NAME>`
- Address: `<CUSTOMER_ADDRESS>`
- Represented by: `<CUSTOMER_SIGNATORY>`
- Contact for DPA: `<CUSTOMER_DPO_OR_PRIVACY_EMAIL>`

**Processor** ("Provider"):
- Name: `<PROVIDER_LEGAL_NAME>` ("the Service")
- Address: `<PROVIDER_ADDRESS>`
- Represented by: `<PROVIDER_SIGNATORY>`
- Contact for DPA: `<PROVIDER_DPO_OR_PRIVACY_EMAIL>`

---

### 1. Subject matter and duration

1.1. The Provider processes personal data **on behalf of** the
Customer for the sole purpose of delivering the GDPR compliance
scanner service described in the agreement dated `<MASTER_AGREEMENT_DATE>`
between the Parties ("Main Agreement").

1.2. This DPA applies for the duration of the Main Agreement and
survives termination until all personal data has been returned or
deleted in accordance with Section 10.

### 2. Nature, purpose and scope of processing

2.1. **Nature of processing**: automated scanning of websites nominated
by the Customer; storage of scan results; access via a web dashboard.

2.2. **Purpose**: helping the Customer assess third-party websites'
GDPR compliance posture.

2.3. **Types of personal data processed**:

- Customer user account data (email, display name, hashed password)
- Scan request data (target URL, scan configuration)
- Scan output (cookie names, domains contacted, privacy-policy
  excerpts, form field metadata — value-masked)
- Audit log records (admin actions, with actor email, IP, user-agent)

2.4. **Categories of data subjects**:

- The Customer's own authenticated users ("Users")
- Indirectly: visitors to websites scanned at the Customer's request,
  to the extent their data appears in the scanned site's HTML —
  which the Provider treats as incidental processing and does not
  store verbatim (see Annex 1, PII-masking).

### 3. Obligations of the Provider

The Provider shall:

3.1. Process personal data only on documented instructions from the
Customer, including as set out in the Main Agreement and this DPA.

3.2. Ensure that persons authorised to process personal data have
committed themselves to confidentiality or are under an appropriate
statutory obligation of confidentiality.

3.3. Implement the technical and organisational measures (TOMs) set
out in **Annex 1**.

3.4. Assist the Customer in fulfilling its obligations to respond to
data-subject requests (access, rectification, erasure, restriction,
portability, objection) by providing administrative tooling and, where
applicable, database-level export on reasonable notice.

3.5. Assist the Customer in ensuring compliance with Articles 32–36
GDPR, taking into account the nature of processing and the information
available to the Provider.

3.6. At the Customer's choice, delete or return all personal data to
the Customer after the end of the provision of services, and delete
existing copies unless retention is required by law.

3.7. Make available to the Customer all information necessary to
demonstrate compliance with Art. 28 GDPR, and allow for and contribute
to audits, including inspections, conducted by the Customer or
another auditor mandated by the Customer.

### 4. Sub-processors

4.1. The Customer consents to the engagement of the sub-processors
listed in **Annex 2**.

4.2. Before engaging any new sub-processor or replacing an existing
one, the Provider shall give the Customer `<14 / 30>` calendar days'
notice. The Customer may object on reasonable data-protection
grounds, in which case the Parties will in good faith seek a
resolution; failing one, the Customer may terminate the Main
Agreement for that portion of the service affected.

4.3. The Provider shall impose on each sub-processor, by contract,
the same data-protection obligations as are set out in this DPA.

### 5. International transfers

5.1. Personal data is stored and processed within the European
Economic Area (EEA) by default. Specifically: `<EU_HOSTING_LOCATION>`.

5.2. Any transfer to a third country (i.e. outside the EEA) happens
only:
- (a) on the basis of an adequacy decision under Art. 45 GDPR; or
- (b) subject to appropriate safeguards under Art. 46 GDPR (e.g.
      Standard Contractual Clauses 2021/914).

5.3. The Provider's sub-processors' transfer basis is listed in
Annex 2.

### 6. Data breach notification

6.1. The Provider shall notify the Customer **without undue delay**
after becoming aware of a personal-data breach (Art. 33(2) GDPR), and
in any event **no later than 36 hours** after awareness. This tighter
internal deadline gives the Customer time to meet their own 72-hour
deadline to the supervisory authority.

6.2. The notification shall contain, to the extent known: the nature
of the breach, the categories and approximate numbers of data
subjects and personal-data records concerned, likely consequences,
and measures taken or proposed.

### 7. Data subject rights

7.1. The Customer is responsible for responding to data-subject
requests. The Provider will forward any request it receives directly
from a data subject to the Customer without responding to the request
itself (other than acknowledging receipt).

7.2. For requests routed through the Customer, the Provider will
assist within `<10 / 15>` business days of a written request
describing what is needed.

### 8. Records of processing

8.1. The Provider maintains a record of processing activities (RoPA)
covering the service, available to the Customer on written request.

### 9. Audit rights

9.1. The Provider will respond to the Customer's reasonable
written questions about the service's processing activities within
`<20>` business days.

9.2. The Customer may conduct an on-premises audit not more than
**once per calendar year** at `<30>` business days' notice, at the
Customer's cost, with a scope agreed in advance, and under a
confidentiality undertaking.

9.3. In lieu of 9.2, a then-current SOC 2 Type II or ISO 27001
report provided by the Provider will be accepted by the Customer
as discharging the audit right for the period it covers.

### 10. Termination

Upon termination of the Main Agreement, the Provider shall at the
Customer's written direction either:
- return all personal data to the Customer in a machine-readable
  format within `<30>` calendar days; or
- delete all personal data, including backups, within
  `<30 + backup_retention>` calendar days.

Retention beyond this point is permitted only to the extent required
by applicable law.

### 11. Governing law and venue

This DPA is governed by the laws of `<JURISDICTION>` and subject to
the exclusive venue of the courts of `<CITY>`. Nothing in this
section limits mandatory data-protection jurisdiction under Art. 77,
78, 79 GDPR.

---

### Signatures

| Controller | Processor |
|---|---|
| Name: `<CUSTOMER_SIGNATORY>` | Name: `<PROVIDER_SIGNATORY>` |
| Role: | Role: |
| Date: | Date: |
| Signature: | Signature: |

---

## Annex 1 — Technical and Organisational Measures (TOMs)

Reference document: [docs/tom.md](tom.md) — summarised below.

**Access control**
- Multi-tenant isolation enforced at the application layer: every
  scan read/write is scoped by `organization_id`; cross-tenant access
  returns HTTP 404 to prevent existence leaks.
- Authentication via JWT (HS256), 7-day default TTL. bcrypt password
  hashing, cost factor 12.
- System-wide administrative privilege is a separate flag
  (`is_superuser`) granted only via out-of-band CLI; there is no
  HTTP path to promote the first superuser.

**Audit logging**
- Every privileged (admin) action writes an append-only row to the
  `audit_logs` table: actor, action, target, timestamp, IP,
  user-agent. No UPDATE/DELETE code path exists.

**Encryption**
- In transit: TLS 1.2+ via Caddy + Let's Encrypt; HSTS enforced.
- At rest: Postgres on the host's encrypted volume; backups
  optionally GPG-encrypted for off-site storage.

**SSRF protection**
- URL submission is validated before any network activity — private/
  loopback/link-local/metadata ranges rejected. Playwright + httpx
  re-validate every redirect to block in-browser SSRF.

**Rate limiting**
- Per-organisation limits on scan execution; per-IP limits on
  auth endpoints to block credential stuffing.

**Separation of duties**
- Production deploys require SSH access AND a manual workflow
  trigger in CI. No single-step push-to-prod.

**Incident response**
- Documented runbook at `docs/incident-response.md` with a 72-hour
  notification timeline per Art. 33 GDPR.

**Data minimisation**
- Cookie values + form inputs stored only as masked prefix/suffix
  previews + length. JWT-shaped values replaced with `<jwt>`.
- Country classification computed offline — no third-party geo-IP
  API is queried during scans.

---

## Annex 2 — Approved Sub-processors

| Sub-processor | Purpose | Data | Location | Transfer safeguard |
|---|---|---|---|---|
| `<HOSTING_PROVIDER>` (e.g. Hetzner) | Server hosting | All processed data | `<EU_DATACENTRE>` | N/A — within EEA |
| Mollie B.V. | Payment processing | Customer email, payment details | Netherlands | N/A — within EEA |
| OpenAI Ireland Ltd. **or** Microsoft Ireland Operations Ltd. (Azure OpenAI) | AI policy analysis | Truncated privacy-policy text | Ireland | N/A — within EEA (OpenAI Ireland) or Azure EU |
| Sentry GmbH (optional, if SENTRY_DSN set) | Error telemetry | Error stack traces (scrubbed — no PII) | `<EU_REGION>` | N/A — EU region selected |
| GitHub Inc. | Container registry (images only) | No personal data | US | SCCs (Art. 46) |

Updates to this list are made per Section 4 of this DPA.
