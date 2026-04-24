# Data Retention Policy

Every piece of data this system stores has a documented lifetime.
Audit checklist item #1 on any SOC 2 / ISO 27001 review is "where is
your retention policy" — here it is.

## 1. Rules at a glance

| Data class | Where it lives | Default retention | Trigger for early deletion |
|---|---|---|---|
| User account (email, hash, display name) | `users` table | Until user deletes account | Account deletion request |
| Organization | `organizations` table | Until last owner leaves AND no active subscription | Org deletion (Phase 8 work) |
| Scan history (URL, score, full payload) | `scans` table | **12 months** from creation | User-initiated delete via `DELETE /scans/{id}` |
| Cookie / form / scan-output details | Inside `scans.payload` JSON | Same as scan row | Same as scan row |
| Audit log | `audit_logs` table | **3 years** | Never, by design — append-only |
| Subscription | `subscriptions` table | Until org is deleted | Org deletion cascade |
| Mollie customer / subscription IDs | `subscriptions.mollie_*` | Same as subscription | Org deletion cascade |
| DB backups | `/var/backups/scanner/` on host | 30 daily + 12 monthly (~13 months max) | Host filesystem rotation (see `deploy/backup.sh`) |
| Container logs | `docker logs` + Loki / CloudWatch when configured | **30 days** in hot storage, 365 days cold | Log shipper policy |
| Sentry events (when enabled) | Sentry SaaS | Per Sentry's plan default (90 days free tier) | Sentry's own retention controls |

## 2. Rationale per class

### User account

No automatic expiration. Users retain access indefinitely; the
product's value depends on historical continuity. On deletion
request (Art. 17 GDPR / §35 BDSG): the row is removed; dependent
`memberships` cascade-delete; `scans` become orphaned
(`organization_id IS NULL`) — which the scoped queries treat as
"invisible to every tenant". They're purged during the next nightly
sweep (TODO Phase 8).

### Scan history: 12 months

Shorter than you might expect. Reasoning:

- The scanner output contains **URLs + third-party contact channels
  + contact emails** discovered on the scanned site. Even when
  value-masked, long retention of that inventory becomes a
  sensitive derivative dataset.
- Compliance use-cases are "current state" driven; historical scans
  older than ~12 months are rarely referenced in our analytics
  telemetry.
- Customers who need longer history have an explicit
  self-service export (CSV via the dashboard) — Phase 8 feature.

Enforcement (Phase 8 cron job, not yet shipped):

```sql
DELETE FROM scans
WHERE created_at < (NOW() - INTERVAL '12 months');
```

### Audit log: 3 years

Longer than scans for two reasons:

- Auditors ask for historical privileged-action records; a 3-year
  window comfortably covers a typical SOC 2 Type II observation period
  plus an additional annual cycle.
- The rows are small (~500 bytes each) — a year of even heavy admin
  usage is < 10 MB. Cost is negligible.

Explicitly append-only. There is no UPDATE/DELETE code path in the
application. Retention enforcement happens at the database layer —
e.g. a scheduled `DELETE FROM audit_logs WHERE created_at < NOW() -
INTERVAL '3 years'` run monthly by an operator or Phase 8 cron.

### DB backups: 30 daily + 12 monthly

Balances incident-recovery depth against storage cost and against
the legal requirement to delete data on request within reasonable
time. A user whose account was deleted 32+ days ago can no longer
be present in any backup, which closes the "backup forever" loophole
that regulators flag.

Rotation is enforced by `deploy/backup.sh`. See that script for the
retention arithmetic.

### Container logs: 30 days hot, 365 days cold

`docker logs` defaults to keeping everything; we don't override it
but also don't rely on it. In production the log shipper (Loki,
CloudWatch, Datadog) holds 30 days in queryable storage and archives
to object storage for up to 365 days. Request-ID tagging (Phase 7)
means you can trace a user-reported issue a month out without
retaining every line indefinitely.

## 3. User-initiated deletion

Current endpoints:

- `DELETE /scans/{scan_id}` — authenticated user deletes one of
  **their own** scans. Tenant-scoped; cross-tenant IDs return 404.
- `POST /billing/cancel` — cancels subscription; plan stays active
  until period-end; no personal-data deletion (user still signed in).
- **Account deletion** (Art. 17): currently manual via
  `DELETE FROM users WHERE email = ?`. Self-service endpoint is a
  Phase 8 task.

## 4. Operator-initiated deletion (incident / legal hold)

Reference `docs/incident-response.md` — during an incident, evidence
is copied to `/var/backups/scanner/incident-*.sql.gz` with naming
that excludes it from the rotation script. Those files must be
deleted by the operator once the post-mortem is closed and any legal
hold has lifted. Keeping an "incident evidence" dump indefinitely is
not a defensible retention practice.

## 5. Third-party retention (sub-processors)

Out of our direct control — documented in the DPA's Annex 2. In
summary:

- **Hosting provider** (Hetzner / Scaleway): mirrors our policy. VM
  disks wiped on termination.
- **Mollie**: holds payment records for 7 years (Dutch tax law).
  The only personal data we sent them was customer email + payment
  metadata; masked scan content never leaves our infrastructure.
- **OpenAI / Azure OpenAI**: per the DPA we have with them, input
  is not used to train models and is retained for 30 days for abuse
  monitoring. We only send **truncated privacy-policy text** — never
  scan results or user identifiers.
- **Sentry** (if configured): errors retained per the paid plan
  (typically 90 days). No PII leaves the process — the `before_send`
  scrubber redacts tokens, cookies, and bodies.

## 6. Review cycle

This policy is reviewed annually. Changes require a PR + one
maintainer approval; the commit history is the change log. The
in-product audit log (Phase 4) records who approved what and when.
