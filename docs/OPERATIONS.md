# Running Dakbox for other people's businesses

This is the runbook for a hosted install. Everything here is built and tested; what is **not** built is listed at the end.

## 1. Hosted mode

Set `DAKBOX_HOSTED=1`. Then:

- **Strict business selection is on.** A database call with no business selected is an error, never a fallback to the original business. The old single-business web addresses (`/webhooks/meta`, `/pay/<provider>/<kind>`, …) are off; every address names its business.
- **No demo data.** A new hosted server starts with one blank business, not the demo shop.
- **API docs are off** (`/api/docs`, `/api/openapi.json`) and CORS is limited to `DAKBOX_ORIGINS`.
- **The server refuses to start** if a protection is missing:

| Setting | Why it is required |
|---|---|
| `DAKBOX_SECRET_KEY` | The master key. Each business's stored secrets (channel tokens, AI keys, signing secrets) are encrypted with a key derived from it. A key file next to the code is not accepted. Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and keep a copy **somewhere other than the server and its backups**. Losing it makes every stored secret unreadable. |
| `DAKBOX_DATA_DIR` | Where `registry.db` and `businesses/` live. Back this directory up. |
| `DAKBOX_STRICT_BUSINESS` must not be `0` | That would turn the protection off. |
| `DAKBOX_ENV` unset or `production` | |

Optional: `DAKBOX_ORIGINS` (comma-separated allowed browser origins, usually empty because the app is served from the same address), `DAKBOX_API_RATE` and `DAKBOX_DOOR_RATE` (see section 4), `DAKBOX_BACKUP_DIR`, `DAKBOX_BACKUP_EVERY_HOURS`, `DAKBOX_BACKUP_KEEP`.

Run behind HTTPS (a reverse proxy such as Caddy or nginx). Sessions are bearer tokens, so everything must be HTTPS.

## 2. Backups and the restore drill

A hosted server backs itself up **every 24 hours** (`DAKBOX_BACKUP_EVERY_HOURS`, `0` turns it off), checks the new backup, and keeps the newest 14 (`DAKBOX_BACKUP_KEEP`). A backup is a folder in `DAKBOX_BACKUP_DIR` (default `<DAKBOX_DATA_DIR>/backups/<UTC time>/`) with a consistent copy of `registry.db` and of every business's database, made while the server keeps running, and a `manifest.json` with every file's checksum.

**A backup on the same disk is not a backup.** Copy the `backups/` folder off the server regularly (object storage, another machine). That copy step is yours to set up; nothing in Dakbox does it.

The master key is deliberately **not** in a backup. Without it a restore brings back everything except stored secrets, which would have to be entered again.

Commands (run from `backend/`, same environment as the server):

```bash
python -m app.backups create                 # back up now
python -m app.backups list
python -m app.backups verify <name>          # checksums + SQLite integrity check
python -m app.backups drill <name>           # the restore drill: restores into a scratch folder and opens every business from it; live data is never touched
python -m app.backups prune
python -m app.backups restore <name> <slug> --yes     # put ONE business back (its current file is kept as *.before-restore-<time>)
```

The same actions are on the Platform screen, **Health** tab (Back up now, Test restore), and in the API (`/api/platform/backups`).

**Do the drill regularly** (monthly is a sensible start, and after every upgrade). A backup nobody has restored is a hope, not a backup.

**Restoring everything** (a lost server): install Dakbox on the new server with the same `DAKBOX_SECRET_KEY`, stop it, copy `registry.db` and the `businesses/` folder from a verified backup into `DAKBOX_DATA_DIR`, start it, then open Platform > Health and check every business is listed. The default business's file path is stored in the registry; if the data directory moved, run `python -m app.businesses list` and fix the path before starting.

## 3. Monitoring

- `GET /healthz` is public and says only `{"ok": true}` (HTTP 200) or 503 when the registry cannot be read. Point your uptime monitor and load balancer at it.
- Platform > Health (`GET /api/platform/health`, administrators only) shows: up-time, open databases, each business's file size, the last pass of every background job (and which business it failed for), and the backup status. It reports "needs attention" when a database file is missing, a job failed for a business, there is no backup, the last scheduled backup failed, or the newest backup is older than 36 hours.
- Failures of background jobs are printed to the server log with the business's address name, e.g. `[recheck:rina-saree-house] …`.

## 4. Rate limits

Per business, so one noisy business cannot starve the others: signed-in requests `DAKBOX_API_RATE` per minute (default 3000), public addresses (webhooks, payment callbacks, website chat) `DAKBOX_DOOR_RATE` per minute (default 600). Over the limit a request gets `429` with `Retry-After`. `0` switches a limit off. Sign-in attempts are limited per address and email (5 failures in 15 minutes) and per address across all emails (30). The limits are in memory: they reset when the server restarts, and each server process counts separately.

## 5. Deleting data

- **One customer's personal data** (owner only): Customers > the row's menu > Erase personal data. Removes name, phone, area, channel identities, the words of their messages, delivery name/phone/address on their orders and their number in the SMS log. Orders, amounts and stock history stay under an anonymous customer.
- **A whole business**: Platform > Businesses > Delete (type its address). Export its data first if its owner may want it (Export data: one CSV per table; secrets are left out). Backups made earlier still contain it until they are pruned: say so in your terms.
- **A person's account**: `POST /api/platform/accounts/<id>/delete`, only when it belongs to no business.

## 6. The release gate

Before anything goes to a second business, and after every change to routes, authentication or the database layer:

```bash
backend/tools/release_gate.sh
```

It runs the isolation suite first (`python -m pytest -m isolation`), then the whole suite, then the hosted start-up check. The isolation suite walks every route the app has, so a new route fails the test until someone classifies it, and for every route it checks: anonymous callers are refused, a session with no business selected is refused, a person of business A reads and changes nothing of business B (all B's ids are tried on every route that takes one, in both directions), and naming B in a header, query string or body changes nothing. It also covers realtime events, searches, customer matching, order numbers, exports, background jobs with one broken business, and deleting a business.

## 7. Upgrades

Each business's database is upgraded when it is opened. To test an upgrade on copies before it touches live data: install the new code, then (with the server stopped) run `python -m app.backups create` and `python -m app.backups drill <name>`. The drill opens every business from the backup with the new code, running the new upgrade step on the copies. If it passes, start the server; if not, go back to the old code (the live files were not touched).

## 8. What is not built

- Sign-up by the public, email verification and password-reset emails (businesses and their first owners are created by hand on the Platform screen).
- Billing and payment for plans.
- A shared Meta app (each business creates its own Meta app today).
- Subdomain-per-business addresses and wildcard certificates.
- Copying backups off the server, and encryption of backups at rest beyond the per-business encryption of stored secrets.
- Terms of service, a privacy notice and a data-processing agreement (a lawyer's job; the customers' messages pass through your server and an AI provider).
- Limits that hold across several server processes (everything here assumes one server process).
