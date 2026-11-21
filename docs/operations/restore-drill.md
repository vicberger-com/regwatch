# Backup and restore drill (M10.2; M10 acceptance 1)

**What a backup holds:** `make backup` writes `backups/<UTC time>/`, readable by its owner only:
- `db.dump`: the database, from `pg_dump -Fc`;
- `objectstore.tar`: the object store volume (PDFs, CSVs, branding, captured documents);
- `MANIFEST`: the migration version, the row counts of the main tables, and the number of object store files;
- `SHA256SUMS`: a SHA-256 sum of each of the three files.

Backups older than 30 days (`BACKUP_KEEP_DAYS`) are removed when a new one is made. Nightly: run `make backup` from cron on the host, for example at 02:00. Copy the directory off the host: an S3-compatible target is BL-79.

**A backup is as sensitive as the database.** It holds every item, users' addresses and password hashes, and the audit log. On the host it is readable by its owner only. Keep backups only where operators alone can write: the sums show a backup is whole, not who made it, and a restore runs what the dump holds. **Encrypt every copy that leaves the host** (for example `age -r <operator key>` or GPG, with the key kept away from the backups), and keep the sums of off-host copies signed or beside the key. The restore refuses an archive holding anything but files and directories, or a path outside the store.

## Restore on a clean host, step by step

1. **Install the release.** Clone or unpack it, copy `deploy/.env`, `deploy/db.env` and `deploy/queue.env` from the secret store, and install Docker with the Compose plugin.
2. **Start the database and queue empty:**
   ```
   docker compose -f deploy/compose.yaml up -d db queue
   ```
   On first start, `db-init` creates the application's database user.
3. **Start the application:**
   ```
   docker compose -f deploy/compose.yaml up -d api worker beat
   ```
4. **Copy the backup directory** to the host, for example to `/srv/restore/20261121T043416Z`.
5. **Restore:**
   ```
   CONFIRM=yes make restore FILE=/srv/restore/20261121T043416Z
   ```
   The script:
   - checks the sums, before anything is changed;
   - stops `api`, `worker` and `beat`;
   - restores the database with `pg_restore --clean --if-exists --single-transaction`;
   - replaces the object store's contents;
   - starts the application again;
   - fails unless every count in the manifest, and the object store's file count, match.
6. **Bring up the rest of the stack** (`up -d`). Then check `GET /api/v1/ready`: it should answer 200 with `ready: true`.
7. **Sign in** and open an item, a report and the Outputs history.

Without `CONFIRM=yes`, the restore stops before any change and says what it would replace.

## Drill record: 2026-11-21

- **Source:** the QA stack (`regwatch-qa`) at `40caa15`, backed up with `make backup`: `20261121T043416Z`.
- **Clean host:** a new Compose project, `regwatch-drill`, with fresh `pgdata` and `objectstore` volumes, its own internal network (10.91.0.0/24) and no published port. Started empty as in steps 2 and 3.
- **The restore** (`CONFIRM=yes`) took 18 s. Run without `CONFIRM`, it stopped with exit 3 and changed nothing.

| Count | Backup | Restored |
| --- | --- | --- |
| alembic_version | 0011 | 0011 |
| item | 4 | 4 |
| item_version | 4 | 4 |
| source | 5 | 5 |
| user | 31 | 31 |
| output_job | 48 | 48 |
| audit_log | 1,057 | 1,057 |
| object store files | 59 | 59 |

**Result: identical counts.**

**Found by the drill:** `/ready` answered 503 on the restored stack, because the queue probe sent PING without AUTH, and the stack's Valkey has a password. The same bug made `/health` report the queue unavailable. It is fixed in `4fc1014`, with a test against a Valkey with a password. After the fix, `/ready` answered `200 {"ready": true, "db": "ok", "queue": "ok", "object_store": "ok"}`.

**Second drill, after the review's fixes (2026-11-21):** the restore checks the archive first and swaps the store in only after a complete extraction. Counts identical; no staging directory left; the project and the backup copy removed. A crafted archive with a symbolic link, and one with a `../` path, were refused before any change (exit 2).
