# Incident Response Runbook

Purpose: when something goes wrong — a suspected compromise, a data
leak, a prolonged outage — this document tells whoever is on call
exactly what to do and in what order. It is not a policy document; it
is an operating manual.

## 0. Severity triage

Declare an incident within 15 minutes of becoming aware of any of:

| Signal | Severity | Example |
|---|---|---|
| Unauthorized data access confirmed | **SEV1** | Audit log shows an attacker's scan on another tenant's org |
| Production outage > 15 min | **SEV1** | `/health` down; customers can't scan |
| Credentials / JWT secret compromise suspected | **SEV1** | Private key appears on GitHub / paste site |
| Non-prod data leak (e.g. backup misplaced) | **SEV2** | Staging DB copied to dev laptop |
| Partial service degradation | **SEV2** | AI provider down, scans work but privacy analysis fails |
| Individual user locked out | **SEV3** | Password reset |

SEV1/SEV2 → notify the designated on-call immediately, open a
chat-channel incident thread, follow the steps below.

## 1. Contain (first 60 minutes)

Priority is stopping the bleeding, NOT understanding root cause yet.

### 1a. Suspected credential compromise

```bash
# SSH to the production host
ssh deploy@scanner.example.com
cd /opt/dsgvo-scanner

# Rotate JWT_SECRET — invalidates every active session immediately.
# Users re-login; any leaked token stops validating.
NEW_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
sed -i "s|^JWT_SECRET=.*|JWT_SECRET=${NEW_SECRET}|" .env

# Rotate database password if the DB account might be touched.
# (Compose uses POSTGRES_PASSWORD from .env; rewrite it + restart postgres.)

# Restart — new secrets take effect; active tokens die.
docker compose -f docker-compose.prod.yml up -d backend worker
```

### 1b. Suspected account takeover

```bash
# On the production host:
docker compose -f docker-compose.prod.yml exec backend python -c "
import asyncio
from sqlalchemy import update
from app.auth import hash_password
from app.db import session_scope
from app.db_models import User
async def lock(email):
    async with session_scope() as s:
        await s.execute(update(User).where(User.email == email).values(
            password_hash=hash_password(__import__('secrets').token_urlsafe(48))
        ))
asyncio.run(lock('suspected@example.com'))
"
```

This sets an unknown password — equivalent to a soft-lock. Don't
delete the row; we need it for the audit trail.

### 1c. Active attack visible

```bash
# Pull the reverse proxy down to cut traffic entirely.
docker compose -f docker-compose.prod.yml stop caddy

# Operator takes over via direct backend access (SSH port-forward).
# Resume caddy only after eradication.
```

## 2. Preserve evidence (parallel to containment)

The audit log, scan history, and container logs are the primary
artefacts for a post-mortem AND for any DSGVO Art. 33 notification.

```bash
# 2a. Full DB snapshot RIGHT NOW — before the attacker (or the fix)
#     mutates anything further.
./deploy/backup.sh
# Label the file clearly so it doesn't get rotated out.
mv /var/backups/scanner/daily/scanner-<TS>.sql.gz \
   /var/backups/scanner/incident-$(date -u +%Y%m%d)-prenose.sql.gz

# 2b. Container logs from the last 24h — stream to a file so they
#     survive a service restart.
docker compose -f docker-compose.prod.yml logs --since 24h --no-color \
  > /var/backups/scanner/incident-$(date -u +%Y%m%d)-logs.txt

# 2c. Audit log dump. Use the admin token from a trusted superuser
#     account to pull the last N entries.
curl -s "https://scanner.example.com/admin/audit?limit=500" \
  -H "Authorization: Bearer <super-admin-token>" \
  > /var/backups/scanner/incident-$(date -u +%Y%m%d)-audit.json
```

Do NOT edit any of these files after collection. Store them on an
encrypted volume; transfer off-host only via encrypted channel (scp
+ GPG, never plain FTP or shared links).

## 3. Assess personal-data exposure (DSGVO Art. 33 clock starts here)

Answer these before anything else:

1. **Was personal data accessed by an unauthorized party?**
   (Scan history contains URLs + contact-channel extracts; user table
   contains emails + bcrypt hashes.)
2. **How many data subjects are affected?**
3. **What categories of data?** (Emails, passwords, scan findings,
   audit logs.)
4. **Is there a likely risk to the rights and freedoms of those
   individuals?** — the threshold for Art. 33 notification.

If the answer to (1) is yes AND (4) is yes (or unclear):

- **The 72-hour notification clock started at the moment you became
  aware.** Not at containment, not at eradication. At awareness.
- Contact your DPO (if external) immediately.
- Draft the notification using the supervisory authority's template
  (in Germany: use the state authority's online form — typical ones
  are LfD or BayLDA).
- Notify the supervisory authority even if you can't yet quantify —
  "initial notification" with follow-up allowed.
- Notify affected data subjects (Art. 34) if the risk is high.

## 4. Eradicate

Only after containment + evidence preservation:

1. **Patch the vulnerability** that enabled the incident. Code change
   goes through normal PR review — incident pressure is a frequent
   source of follow-on bugs.
2. **Regenerate every secret** that touched the affected system:
   `JWT_SECRET`, `POSTGRES_PASSWORD`, `MOLLIE_WEBHOOK_TOKEN`,
   `OPENAI_API_KEY`, any CI deploy keys.
3. **Review all admin users** — anyone promoted recently who shouldn't
   have been, demote via the CLI:
   ```bash
   docker compose exec backend python -m app.cli.promote --revoke suspected@example.com
   ```
4. **Rotate SSH keys** on the production host if the host was touched.

## 5. Recover

1. Bring services back up one at a time:
   ```bash
   docker compose -f docker-compose.prod.yml up -d postgres redis
   # Verify DB integrity from the evidence snapshot if needed:
   #   docker compose exec postgres pg_restore --list /path/to/backup
   docker compose -f docker-compose.prod.yml up -d backend worker
   # Verify /health returns ok
   docker compose -f docker-compose.prod.yml up -d frontend caddy
   ```
2. Watch logs + Sentry for 30 minutes after full restore. Any 5xx
   spike = roll back to the previous image tag (see README's "Rolling
   back" section).

## 6. Communicate

Internal (always):

- Post a summary to the team channel: scope, current status, next
  update time.

External (conditional):

- **Customers**: if service was unavailable > 30 min or any customer
  data was potentially exposed, send a plain-text email with dates,
  scope, and what you're doing about it. Short is better than
  elaborate.
- **Supervisory authority**: within 72h if Art. 33 applies.
- **Affected data subjects**: without undue delay if Art. 34 applies.

## 7. Post-mortem (within 5 business days of resolution)

Writeup template (keep it in this repo at `docs/incidents/<date>.md`):

```markdown
# Incident <date> — <one-line title>

**Severity**: SEV1 / SEV2 / SEV3
**Duration**: detect → resolve
**Impact**: scope in plain English
**Root cause**: one paragraph, not a blame line

## Timeline (UTC)

HH:MM — first signal (what tipped you off)
HH:MM — on-call paged
HH:MM — containment step X
HH:MM — resolution
HH:MM — post-mortem filed

## What went well

## What went wrong

## Action items

- [ ] Concrete fix, owner, deadline
- [ ] Monitoring gap filled, owner, deadline
```

Action items go into the issue tracker with the "incident" label so
the next review catches them if they stall.

## 8. References

- [DSGVO Art. 33 — notification of a personal data breach to the
  supervisory authority](https://gdpr-info.eu/art-33-gdpr/)
- [DSGVO Art. 34 — communication of a personal data breach to the
  data subject](https://gdpr-info.eu/art-34-gdpr/)
- [EDPB Guidelines 9/2022 on personal data breach
  notification](https://edpb.europa.eu/our-work-tools/our-documents/guidelines/guidelines-92022-personal-data-breach-notification-under_en)
- Our security contact: see `/.well-known/security.txt`.
