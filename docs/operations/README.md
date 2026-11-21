# Operations runbooks (M10.6)

For the production stack (`deploy/compose.prod.yaml`; setup in `deploy/README.md`). The commands assume:

    P="docker compose -f deploy/compose.prod.yaml"

| Runbook | When |
| --- | --- |
| [release.md](release.md) | Cutting a release; upgrading an installation; rolling back |
| [restore-drill.md](restore-drill.md) | Backups, restoring on a clean host, the drill |
| [monitoring.md](monitoring.md) | The dashboard, and what each alert means |
| Below | Day to day: start and stop, logs, secrets, incidents |

## Start, stop, status
- **Start:** `$P up -d`. Add `--profile monitoring` for Prometheus and Grafana.
- **Stop:** `$P stop` keeps every volume. `$P down` removes the containers but keeps the volumes. Never pass `-v` on a real installation: it deletes the database and the object store.
- **Status:**
  - `$P ps`: every service should be `Up`, and the api `(healthy)`;
  - `curl -s https://<site>/api/v1/ready` should answer `{"ready": true, …}`;
  - a 503 names the dependency that is down.

## Logs
- **Where:** `$P logs --since 1h api worker`. Logs are JSON lines (structlog) with `request_id`, `event` and `level`. A user who reports an error can give the request id from the error message; search for it with `$P logs api | grep '<request id>'`.
- **What is never logged:** passwords, session tokens, email message bodies and captured content. Addresses in the audit log are hashed for email recipients.

## Rotating secrets
Plan rotations in the maintenance window (business hours, weekly; M10 question 3).

**The signing key (`REGWATCH_SECRET_KEY`).** It signs artifact links, sign-in state cookies and the two-factor step, keys query hashes, and encrypts two-factor secrets. Sessions are stored as token hashes, so rotating it signs no one out.
1. Set `REGWATCH_SECRET_KEY_PREVIOUS` to the current key and `REGWATCH_SECRET_KEY` to a new one, 64 hex characters: `openssl rand -hex 32`.
2. Restart: `$P up -d api worker`. Links issued in the last 10 minutes keep working.
3. Re-encrypt the two-factor secrets with the new key: `$P exec api regwatch-admin rotate-mfa-secrets`. It reports how many it re-encrypted. Any it calls unreadable were encrypted with an older key; reset those users' authenticators (Settings, Users). Recovery codes cannot be re-keyed: those made before the rotation stop working when the previous key is removed, so ask users with two-factor sign-in to get new ones (User tab) in the meantime.
4. After 10 minutes, remove `REGWATCH_SECRET_KEY_PREVIOUS` and restart again.

**Database passwords** (`db.env`: the owner and `regwatch_api`):
1. In the database, use psql's `\password`, which sends the password already hashed: `$P exec db psql -U regwatch -d regwatch`, then `\password regwatch_api`. Never type `ALTER ROLE … PASSWORD '…'` with a literal password; it can end up in psql's history and the server log.
2. Update `db.env`, and the database URL in `.env`.
3. Restart api, worker and beat.

**Valkey:** change `VALKEY_PASSWORD` in `queue.env` and the queue URL in `.env`, then restart `queue`, api, worker and beat. The queue holds only tasks waiting to run; scheduled ones are created again on the next tick.

**SMTP and printer credentials** live in `.env` (SMTP) and in the Printers page (certificate fingerprints). Change them there.

## Incidents
| Symptom | First checks |
| --- | --- |
| `/ready` is 503 | The field that says `unavailable`: `$P ps db queue`, their logs, disk space (`df -h`), then `$P restart <service>` |
| Sign-in fails for everyone | `$P logs api`: the database login (BL-61), a wrong `REGWATCH_BASE_URL` (the origin check), or the clock (cookies) |
| A source unhealthy for 24 hours (alert) | Settings, Sources: its last error; the site may have changed or be refusing us (robots.txt, 403). Fix its settings or disable it |
| Outputs failing (alert) | The Outputs history's error class: `smtp-*` (mail relay), `printer-*` (Printers page, printer networks), `pdf-*` (`$P logs pdf`) |
| Queue backlog (alert) | `$P ps worker`, `$P logs worker`; scale with `$P up -d --scale worker=3` |
| Disk filling | The object store (outputs older than the retention are removed every minute), the database, backups older than 30 days (removed by `make backup`), and Docker's images (`docker image prune`) |
| Data lost or damaged | Stop the application (`$P stop api worker beat`) and restore the last good backup (restore-drill.md) |
| An administrator lost their phone and recovery codes | Another administrator resets it (Settings, Users, Reset two-factor). With none: `$P exec api regwatch-admin reset-mfa --email <address>`, audited with who ran it; they then set it up again |
| A suspected compromise | 1. Keep the evidence: `$P logs > incident.log`, and a backup labelled as evidence, kept apart from the normal ones and never restored (it may hold the attacker's changes). 2. Sign everyone out: `$P run --rm --no-deps api regwatch-admin revoke-sessions --all` (rotating secrets alone signs no one out; sessions are stored as token hashes). 3. Reset the passwords of the administrators and of every affected account, and disable accounts you do not recognise (Settings, Users). 4. Rotate every secret (above). 5. In the audit log (Settings, Audit log), review recently created or changed users, roles, groups, printers, sources and settings. 6. Follow `SECURITY.md` |
