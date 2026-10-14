# Asas Backend Production Deployment

This is the deployment handoff for the current Asas backend. It is specific to
the repository's Django settings and URL layout. Commands are examples for an
Ubuntu host and must be reviewed against the selected Ubuntu release before
execution. Replace every value enclosed in `<...>`; none are real credentials,
domains, users, or addresses.

## 1. Architecture

Request path:

```text
Internet
  -> production DNS
  -> Nginx (TLS termination and the only trusted reverse proxy)
  -> Gunicorn over a Unix socket
  -> Django (config.wsgi:application)
  -> PostgreSQL on the same host
```

Supporting services:

- Django's shared default cache is `DatabaseCache` stored in the PostgreSQL
  table `asas_cache`. Every Gunicorn worker uses the same table, so login and
  other DRF throttle counters are shared across workers. There is no Redis.
- Media is stored on disk at `/var/www/asas/media` and served by Nginx under
  `/media/`. It is currently public to anyone who knows a file URL.
- Static assets are collected into `staticfiles/` and served by WhiteNoise.
  Nginx does not define a second `/static/` implementation.
- Firebase Admin is optional and sends push notifications when enabled.
  Requests never call Firebase: they store each notification as a pending
  row, and a separate `asas-push-worker` systemd service sends it (section 8).
  If the worker is not running, no push notification is delivered.
- The frontend remains on Vercel under its real production domain.

`NUM_PROXIES=1` is correct only while Nginx is the sole proxy in front of
Django. Adding Cloudflare, a load balancer, or another proxy requires a new
trusted-proxy and forwarded-header review before deployment.

## 2. Server prerequisites

Install the Ubuntu packages appropriate for the selected Ubuntu release:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip postgresql nginx git
```

The repository pins Django `5.2.16` and Gunicorn `26.0.0`. Select the Ubuntu
`python3` package only after confirming that its Python version is supported by
Django 5.2 and every pinned dependency in `requirements.txt`. The repository
does not declare a narrower Python version, so do not invent one in automation.

The pinned packages normally install from wheels. If the target architecture
requires source builds, install build tools only then, for example:

```bash
sudo apt install build-essential libpq-dev python3-dev
```

Do not install Docker, Celery, or Render-specific tooling for this deployment.

## 3. Linux user and directories

Use a dedicated unprivileged account. The examples use `asas`; substitute the
approved service account if different.

```bash
sudo adduser --system --group --home /var/www/asas asas
sudo install -d -o asas -g asas -m 0750 /var/www/asas/backend
sudo install -d -o asas -g asas -m 0750 /var/www/asas/venv
sudo install -d -o asas -g www-data -m 2750 /var/www/asas/media
sudo install -d -o root -g asas -m 0750 /etc/asas
```

Operational rules:

- The application checkout and virtual environment are owned by `asas`.
- Gunicorn owns media files and can create the existing
  `homework/attachments/` and `announcements/attachments/` subdirectories.
- Nginx, through group `www-data`, can read and traverse media directories.
- Use a restrictive service umask; never use mode `777`.
- `media/` is ignored by Git. Never copy it into the checkout or delete it
  during a release or rollback.
- Application logs go to systemd journal; Nginx logs go to `/var/log/nginx/`.
  A project-local writable logs directory is not required by current settings.

Verify effective permissions with the real service users before launch:

```bash
sudo -u asas test -w /var/www/asas/media
sudo -u www-data test -r /var/www/asas/media
```

## 4. Production environment

Create `/etc/asas/backend.env`, owned by `root:asas` with mode `0640`. systemd
loads it for Gunicorn. Do not commit it, print it, attach it to tickets, or log
its contents.

```bash
sudo install -o root -g asas -m 0640 /dev/null /etc/asas/backend.env
sudoedit /etc/asas/backend.env
```

The following values are required by the current production settings:

```dotenv
DJANGO_SETTINGS_MODULE=config.production_settings

SECRET_KEY=<RANDOM_SECRET_AT_LEAST_50_CHARACTERS>
JWT_SIGNING_KEY=<DIFFERENT_RANDOM_SECRET_AT_LEAST_32_CHARACTERS>

ALLOWED_HOSTS=<BACKEND_DOMAIN>
FRONTEND_ORIGINS=https://<FRONTEND_DOMAIN>
BACKEND_ORIGINS=https://<BACKEND_DOMAIN>

DB_NAME=<DATABASE_NAME>
DB_USER=<DATABASE_USER>
DB_PASSWORD=<DATABASE_PASSWORD>
DB_HOST=127.0.0.1
DB_PORT=5432
DB_SSLMODE=<disable_or_prefer_for_reviewed_local_connection>

MEDIA_ROOT=/var/www/asas/media
```

Production rejects `DEBUG=True`; leave `DEBUG` unset or set it to `False`.
Hosts must be plain hostnames. Origins must be exact HTTPS origins without a
path, wildcard, query, fragment, localhost, or a `vercel.app` preview domain.
Use the real Vercel production custom domain for `FRONTEND_ORIGINS`.

Optional settings with current defaults:

```dotenv
LOG_LEVEL=INFO
MOBILE_MAX_ACTIVE_DEVICES_PER_GUARDIAN=2

JWT_COOKIE_SAMESITE=Lax
CSRF_COOKIE_SAMESITE=Lax
# JWT_COOKIE_DOMAIN=<PLAIN_COOKIE_DOMAIN_IF_EXPLICITLY_REQUIRED>

SECURE_HSTS_SECONDS=0
SECURE_HSTS_INCLUDE_SUBDOMAINS=False
SECURE_HSTS_PRELOAD=False

FIREBASE_PUSH_ENABLED=False
# FIREBASE_PROJECT_ID=<FIREBASE_PROJECT_ID>
# GOOGLE_APPLICATION_CREDENTIALS=/etc/asas/firebase-service-account.json

# Push worker (section 8). Every value must be a positive integer.
FIREBASE_HTTP_TIMEOUT_SECONDS=10
PUSH_SEND_CHUNK_SIZE=50
PUSH_MAX_ATTEMPTS=6
PUSH_MAX_AGE_HOURS=24
PUSH_WORKER_BATCH_SIZE=50
PUSH_LEASE_SECONDS=300
PUSH_WORKER_POLL_SECONDS=3
```

Production forces JWT, CSRF, and session cookies to Secure and HttpOnly where
configured. If Firebase is enabled, both Firebase variables become required.
Keep the service-account JSON outside Git, owned by `root:asas`, readable by
the application user, and never include it in an unencrypted general backup.

There are no application email environment variables in the current settings.

## 5. PostgreSQL

Keep PostgreSQL local and do not expose TCP port 5432 publicly. Create a
dedicated login and database from an interactive PostgreSQL administrator
session so the password is not placed in shell history:

```bash
sudo -u postgres psql
```

```sql
CREATE ROLE <DATABASE_USER> LOGIN;
\password <DATABASE_USER>
CREATE DATABASE <DATABASE_NAME> OWNER <DATABASE_USER>;
REVOKE ALL ON DATABASE <DATABASE_NAME> FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE <DATABASE_NAME> TO <DATABASE_USER>;
```

Use the same values in `DB_*`. Review `pg_hba.conf` so the application can
connect locally using password authentication and remote public connections
are not enabled. The database owner has the schema permissions Django needs;
do not grant superuser or server-wide administrative privileges.

Apply migrations only after taking a backup and reviewing the release's
migration plan:

```bash
/var/www/asas/venv/bin/python /var/www/asas/backend/manage.py migrate --settings=config.production_settings
/var/www/asas/venv/bin/python /var/www/asas/backend/manage.py createcachetable --settings=config.production_settings
```

The second command creates the `asas_cache` table; see section 6.

## 6. Cache (PostgreSQL DatabaseCache)

Production uses Django's `DatabaseCache` as the `default` cache. It lives in
the same PostgreSQL database as the application, in the table `asas_cache`.
No separate cache service is installed or required.

```python
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "asas_cache",
        "TIMEOUT": 300,
        "KEY_PREFIX": "asas",
        "OPTIONS": {"MAX_ENTRIES": 300, "CULL_FREQUENCY": 3},
    },
}
```

Create the table after `migrate` and before restarting Gunicorn, on the first
deployment and as a mandatory step of every later deployment:

```bash
/var/www/asas/venv/bin/python /var/www/asas/backend/manage.py createcachetable --settings=config.production_settings
```

- `createcachetable` is not a Django migration. `migrate` does not create the
  table, and it does not appear in `showmigrations`.
- The command is idempotent: if `asas_cache` already exists it does nothing.
  It only creates the table; it never cleans, resets, or resizes it.
- If the table is missing, every endpoint that uses throttling (Web Login,
  Mobile Login, Mobile school requests, Mobile device registration and
  unregistration) fails with HTTP 500 instead of serving or throttling the
  request.
- All Gunicorn workers share this one table, so throttle counters are shared
  across workers. There is intentionally no production fallback to
  per-worker local memory.

Throttle scopes and rates are unchanged: `web_login` `5/minute`,
`mobile_login` `5/minute`, `mobile_school_request_burst` `3/minute`,
`mobile_school_request_hourly` `5/hour`, `mobile_device_registration`
`10/minute`, and `mobile_device_unregistration` `10/minute`. Throttled
requests return HTTP 429 with code `TOO_MANY_REQUESTS`.

Verify that the table exists and that reads and writes work:

```bash
sudo -u postgres psql -d <DATABASE_NAME> -c "SELECT to_regclass('public.asas_cache');"

/var/www/asas/venv/bin/python /var/www/asas/backend/manage.py shell --settings=config.production_settings -c "from django.core.cache import cache; cache.set('deploy-check', 'ok', 30); assert cache.get('deploy-check') == 'ok'; cache.delete('deploy-check'); print('cache ok')"
```

The first command must print `asas_cache`, not an empty value. The second must
print `cache ok`. Run the second command with the production environment
loaded as in the deployment procedure.

Known limitations:

- DRF throttling reads the request history, then writes it back. Concurrent
  requests from the same client can read the same history before either
  writes, so a burst may let slightly more than the configured number of
  requests through. Rate limiting is a best-effort control, not a strict
  guarantee under concurrent requests. This was also true with the previous
  cache backend.
- Expired entries are deleted only opportunistically: Django culls when an
  entry is written and the table holds more than `MAX_ENTRIES` (300) rows,
  removing roughly one third (`CULL_FREQUENCY=3`). Monitor the row count and
  table size of `asas_cache` (see Monitoring). `createcachetable` cannot be
  used to clean it.
- Cache reads and writes add small queries to PostgreSQL. A PostgreSQL outage
  affects the cache and the application together.

## 7. Gunicorn and systemd

The real WSGI target is `config.wsgi:application`. The WSGI module uses
`setdefault`, so the production value from the systemd environment takes
precedence.

Create `/etc/systemd/system/asas-backend.service`:

```ini
[Unit]
Description=Asas Django backend
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=asas
Group=www-data
SupplementaryGroups=asas
WorkingDirectory=/var/www/asas/backend
EnvironmentFile=/etc/asas/backend.env
RuntimeDirectory=asas
RuntimeDirectoryMode=0750
UMask=0007
ExecStart=/var/www/asas/venv/bin/gunicorn \
    --workers 2 \
    --timeout 60 \
    --access-logfile - \
    --error-logfile - \
    --bind unix:/run/asas/gunicorn.sock \
    config.wsgi:application
Restart=on-failure
RestartSec=5
TimeoutStopSec=60
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
```

Two workers are a conservative starting value, not a final capacity decision.
Choose the final count after measuring CPU, RAM, request latency, database
connections, and attachment-processing memory under representative load.

Manage and inspect the service with:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now asas-backend
sudo systemctl restart asas-backend
sudo systemctl status asas-backend
sudo journalctl -u asas-backend -f
```

## 8. Push notification worker

Requests do not send push notifications. Each new notification is stored as a
`pending` row in `notifications_notification` (or `skipped` when
`FIREBASE_PUSH_ENABLED=False` at creation time). The `run_push_worker`
management command claims due rows in batches, sends them through Firebase
outside any database transaction, and records the result:

- `sent`: at least one device received it and nothing is left to retry.
- `pending` again: a temporary Firebase or network error; retried after 30
  seconds, 2 minutes, 10 minutes, 30 minutes, then every 2 hours, up to
  `PUSH_MAX_ATTEMPTS` attempts in total.
- `failed`: every device failed permanently, or the attempts ran out.
- `skipped`: push disabled, recipient inactive or required to change their
  password, or no active device.
- `expired`: still pending `PUSH_MAX_AGE_HOURS` after creation; never sent.

Notifications stay visible in the app whatever their push status.

Create `/etc/systemd/system/asas-push-worker.service`:

```ini
[Unit]
Description=Asas push notification worker
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=asas
Group=asas
WorkingDirectory=/var/www/asas/backend
EnvironmentFile=/etc/asas/backend.env
UMask=0027
ExecStart=/var/www/asas/venv/bin/python /var/www/asas/backend/manage.py run_push_worker --settings=config.production_settings
Restart=always
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
```

It uses the same account and environment file as Gunicorn, so it reads the
same database and Firebase credentials. Run it even while
`FIREBASE_PUSH_ENABLED=False`: it then marks rows left pending from an earlier
enabled period as `skipped`.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now asas-push-worker
sudo systemctl status asas-push-worker
sudo journalctl -u asas-push-worker -f
```

Behaviour to know when operating it:

- On `SIGTERM` (stop, restart, deploy) the worker finishes the current batch
  and exits with status 0. A batch normally takes seconds. If Firebase is
  slow enough that it exceeds `TimeoutStopSec`, systemd kills it; the claimed
  rows are retried by the next worker once their lease
  (`PUSH_LEASE_SECONDS`) expires. A notification may then reach a device
  twice; Android `collapse_key`/`tag` and iOS `apns-collapse-id` make the
  second copy replace the first.
- Database or unexpected errors are logged and retried with a growing pause of
  up to 60 seconds; the process does not exit. `Restart=always` covers crashes.
- One worker is enough. A second instance is safe (rows are leased with
  `SELECT ... FOR UPDATE SKIP LOCKED` and a lease token) but is only useful for
  higher volume.
- The worker holds one PostgreSQL connection; include it when sizing
  `max_connections`.
- Each batch with work logs one line such as
  `Push batch claimed=50 sent=48 retry=2 failed=0 skipped=0 expired=0 lease_lost=0`.
  Logs contain notification and device ids and error type names only, never
  tokens, titles, or bodies.

Lease sizing: with the defaults a batch is at most 50 notifications times two
devices, which is two `send_each` calls of 50 messages sent in parallel. One
Firebase request can take up to 5 attempts of 10 seconds plus 7 seconds of SDK
backoff (57 seconds), or about 101 seconds counting the SDK's extra connect and
read retries, so a batch stays near 114 to 202 seconds in the worst case,
below the 300-second lease. Raising `PUSH_WORKER_BATCH_SIZE` or
`FIREBASE_HTTP_TIMEOUT_SECONDS` requires raising `PUSH_LEASE_SECONDS` to match.

## 9. Nginx

Create a site such as `/etc/nginx/sites-available/asas-backend`, replacing the
domain and certificate placeholders. This configuration intentionally has no
`/static/` location: WhiteNoise is the single static-file serving mechanism.

```nginx
upstream asas_backend {
    server unix:/run/asas/gunicorn.sock fail_timeout=0;
}

server {
    listen 80;
    listen [::]:80;
    server_name <BACKEND_DOMAIN>;

    access_log /var/log/nginx/asas_access.log;
    error_log /var/log/nginx/asas_error.log warn;

    client_max_body_size 7m;

    location ^~ /media/ {
        alias /var/www/asas/media/;
        autoindex off;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Content-Disposition "inline" always;
        add_header Cache-Control "private, max-age=3600" always;
    }

    location / {
        proxy_pass http://asas_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 10s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
}
```

`X-Real-IP` and `X-Forwarded-For` are set to `$remote_addr`, replacing any
value supplied by the client. Do not change them to
`$proxy_add_x_forwarded_for`: with `NUM_PROXIES=1` Django takes the client IP
used for throttling from this header, and an appended client-controlled value
would let clients evade or redirect rate limits.

The `^~ /media/` static alias is never proxied to an interpreter or FastCGI
handler, directory listing is disabled, and `nosniff` prevents browser MIME
guessing. `Content-Disposition: inline` preserves current image/PDF opening in
browsers and mobile clients. If product later chooses forced PDF downloads,
replace it for PDFs with `Content-Disposition: attachment` only after testing
Web and Mobile; do not apply both policies simultaneously.

Media remains public by link. The cache header is deliberately conservative
and private; UUID filenames reduce collisions but are not authorization.

Do not add exceptions for `/api/schema/`, `/api/docs/`, or `/api/redoc/`.
Django does not register them under production settings, so they return 404.
The health endpoint `/health/` is proxied normally.

Enable the site and validate before reload:

```bash
sudo ln -s /etc/nginx/sites-available/asas-backend /etc/nginx/sites-enabled/asas-backend
sudo nginx -t
sudo systemctl reload nginx
```

Ubuntu's packaged logrotate policy normally covers `/var/log/nginx/*.log`.
Confirm that both named log files are matched and rotated; add a dedicated
logrotate rule only if the installed package policy does not cover them.

## 10. HTTPS and domains

1. Point the backend DNS record to the server's public address.
2. Confirm HTTP reaches the intended Nginx virtual host.
3. Install Certbot using the method supported by the selected Ubuntu release,
   then request a certificate for the real backend domain.
4. Enable HTTP-to-HTTPS redirection and test certificate renewal.

Typical commands after DNS is correct:

```bash
sudo certbot --nginx -d <BACKEND_DOMAIN>
sudo certbot renew --dry-run
```

Django already enforces `SECURE_SSL_REDIRECT=True` and trusts only Nginx's
`X-Forwarded-Proto: https` through `SECURE_PROXY_SSL_HEADER`. Nginx must replace
the forwarding header as shown; it must not pass a client-provided value.

Keep `SECURE_HSTS_SECONDS=0` until HTTPS, renewal, and every intended subdomain
are stable. Increase it gradually. Enable subdomains and preload only after a
separate irreversible-impact review. Keep `ALLOWED_HOSTS`, `BACKEND_ORIGINS`,
`FRONTEND_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, and the real Vercel production
origin aligned. Do not use broad wildcards.

## 11. Firewall

Confirm the actual SSH port before enabling UFW, or remote access can be lost.

```bash
sudo ufw allow <SSH_PORT>/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw status verbose
sudo ufw enable
```

Do not allow 5432 or a Gunicorn TCP port publicly. Gunicorn uses a Unix
socket. Also verify provider-level firewall/security-group rules; UFW is not a
substitute for them.

## 12. Deployment procedure

Run release commands as the application user unless a step explicitly needs
root. Never delete or replace `/var/www/asas/media` during deployment.

```bash
cd /var/www/asas/backend

# First deployment only, from the parent directory:
# sudo -u asas git clone <APPROVED_REPOSITORY_URL> /var/www/asas/backend

# Later deployments:
sudo -u asas git fetch --all --prune
sudo -u asas git checkout <REVIEWED_RELEASE_OR_COMMIT>

python3 -m venv /var/www/asas/venv
/var/www/asas/venv/bin/python -m pip install --upgrade pip
/var/www/asas/venv/bin/python -m pip install -r requirements.txt

set -a
. /etc/asas/backend.env
set +a

/var/www/asas/venv/bin/python manage.py check --deploy --settings=config.production_settings
/var/www/asas/venv/bin/python manage.py migrate --settings=config.production_settings
# Mandatory: creates the cache table if missing. Not a migration; see section 6.
/var/www/asas/venv/bin/python /var/www/asas/backend/manage.py createcachetable --settings=config.production_settings
/var/www/asas/venv/bin/python manage.py collectstatic --noinput --settings=config.production_settings
```

Then:

```bash
sudo install -d -o asas -g www-data -m 2750 /var/www/asas/media
sudo systemctl status postgresql
sudo -u postgres psql -d <DATABASE_NAME> -c "SELECT to_regclass('public.asas_cache');"
# Restart both together, after migrate, so they run the same release.
sudo systemctl restart asas-backend asas-push-worker
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl status asas-backend asas-push-worker nginx
```

On the first deployment that includes the push worker, install its unit
(section 8) and run `sudo systemctl enable --now asas-push-worker` instead of
restarting it.

For routine releases, use a reviewed immutable commit or release directory
rather than an unreviewed working tree. Take the database backup before
migrations. Keep the previous commit/release available until smoke tests pass.

## 13. Backup and restore policy

Back up PostgreSQL and media daily. Keep multiple retention tiers appropriate
to school policy, store at least one encrypted copy off-host, monitor backup
completion and capacity, and perform scheduled restore drills.

PostgreSQL example; authentication should come from a protected `.pgpass` or
an interactive prompt, never a password in the command line:

```bash
sudo install -d -o asas -g asas -m 0750 /srv/backups/asas/postgresql
pg_dump -h 127.0.0.1 -U <DATABASE_USER> --format=custom \
  --file=/srv/backups/asas/postgresql/<TIMESTAMP>_<DATABASE_NAME>.dump \
  <DATABASE_NAME>
```

Media example, written outside the source and media trees:

```bash
sudo install -d -o root -g root -m 0700 /srv/backups/asas/media
sudo tar --one-file-system --numeric-owner -czf \
  /srv/backups/asas/media/<TIMESTAMP>_media.tar.gz \
  -C /var/www/asas media
```

Restore into an isolated environment first. Validate the database, media file
counts, ownership, and representative downloads before approving a production
restore. Document the restoration time and responsible operator.

Do not place Firebase credentials or the environment file in a general
unencrypted archive. If configuration recovery is required, back them up with
separate encryption and restricted access.

## 14. Monitoring and logs

Monitor at minimum:

- Free disk space and inode usage, especially the 200 GB allocation intended
  for media and backups.
- Media and backup growth, backup age, and restore-test results.
- RAM, CPU, load, and attachment-processing memory peaks.
- Gunicorn failures, restarts, timeouts, worker saturation, and journal errors.
- Nginx latency, 4xx/5xx rates, upload rejections, and log rotation.
- PostgreSQL availability, connections, locks, storage, and backup status.
- `asas_cache` table existence, row count, and table size (for example
  `SELECT count(*) FROM asas_cache;` and
  `SELECT pg_size_pretty(pg_total_relation_size('asas_cache'));`), and HTTP 500
  responses on login or other throttled endpoints.
- The push worker: `asas-push-worker` must be active, and
  `push_queue_status` must pass every minute (below). **If the worker is
  stopped, no push notification is sent**; notifications still appear in the
  app, and pending ones expire after `PUSH_MAX_AGE_HOURS`. Also alert on
  `ERROR` lines from `notifications.push_services` in its journal:
  `ThirdPartyAuthError`, `PermissionDeniedError`, or `UnauthenticatedError`
  mean the Firebase credentials or project settings are broken.
- HTTP 429 rate and unexpected login-throttle changes.
- TLS expiry and Certbot renewal status.
- `/health/` status and latency.

Useful built-in commands:

`push_queue_status` prints the number of notifications in each push status
and exits non-zero when a due pending push has waited longer than
`--max-age-seconds` (default 300), which means the worker is stopped, stuck,
or cannot reach the database. Run it every minute with a systemd timer.
`/etc/systemd/system/asas-push-queue-check.service`:

```ini
[Unit]
Description=Asas push queue check
OnFailure=<OPERATOR_ALERT_UNIT>

[Service]
Type=oneshot
User=asas
Group=asas
WorkingDirectory=/var/www/asas/backend
EnvironmentFile=/etc/asas/backend.env
ExecStart=/var/www/asas/venv/bin/python /var/www/asas/backend/manage.py push_queue_status --max-age-seconds 300 --settings=config.production_settings
```

`/etc/systemd/system/asas-push-queue-check.timer`:

```ini
[Unit]
Description=Run the Asas push queue check every minute

[Timer]
OnCalendar=minutely
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now asas-push-queue-check.timer
```

Replace `<OPERATOR_ALERT_UNIT>` with the operator's alerting unit, or remove
that line and alert on failed `asas-push-queue-check.service` runs from the
existing monitoring system. The check counts every notification by status,
so it scans the notifications table once a minute.

```bash
sudo journalctl -u asas-backend --since "1 hour ago"
sudo journalctl -u asas-push-worker --since "1 hour ago"
sudo -u asas sh -c 'set -a; . /etc/asas/backend.env; set +a; /var/www/asas/venv/bin/python /var/www/asas/backend/manage.py push_queue_status --settings=config.production_settings'
sudo systemctl status asas-backend asas-push-worker nginx postgresql
sudo tail -f /var/log/nginx/asas_error.log
df -h
df -i
```

No paid monitoring platform is mandatory; integrate these checks with the
operator's existing monitoring system.

## 15. Post-deployment smoke test

Complete this checklist from controlled Web, Mobile, and server clients:

- [ ] `GET https://<BACKEND_DOMAIN>/health/` returns the healthy contract.
- [ ] Web Login works at `/api/v1/auth/web/login/` with CSRF/cookies behaving
      correctly over HTTPS.
- [ ] Mobile Login works at `/api/v1/auth/mobile/login/` and returns the mobile
      token contract.
- [ ] Six controlled invalid login attempts within one minute produce 429 on
      the sixth request for both login scopes, with code `TOO_MANY_REQUESTS`;
      repeat across workers. Counters are shared through `asas_cache`.
- [ ] `/api/schema/`, `/api/docs/`, and `/api/redoc/` each return 404.
- [ ] A valid Homework image uploads, becomes a UUID-named WebP, and downloads.
- [ ] An image over 25,000,000 pixels is rejected without a stored orphan.
- [ ] A valid PDF uploads and opens inline through the public media link.
- [ ] A valid Announcement attachment uploads and downloads.
- [ ] Guardian Mobile can reach a permitted attachment and its normal APIs.
- [ ] An XLSX student import works and the source workbook is not stored under
      `/var/www/asas/media`.
- [ ] PostgreSQL data survives an application and database service restart.
- [ ] `SELECT to_regclass('public.asas_cache');` returns `asas_cache` and the
      cache read/write check from section 6 prints `cache ok`.
- [ ] `asas-push-worker` is active, `push_queue_status` exits 0, and the
      `asas-push-queue-check.timer` is listed by `systemctl list-timers`.
- [ ] When Firebase is enabled, a test notification reaches a device within a
      few seconds and its row becomes `sent`; the worker journal shows a
      `Push batch` line.
- [ ] Media files survive Gunicorn restart and a subsequent deployment.

The application accepts attachments up to 5 MiB. Nginx uses
`client_max_body_size 7m` to leave multipart overhead without replacing the
application's validation.

## 16. Rollback

Before a release, record the current commit/release, back up PostgreSQL, and
retain the previous environment-compatible artifact. If rollback is required:

1. Stop further deployment changes and preserve logs.
2. Review migrations introduced by the failed release. Do not automatically
   run `migrate zero`, drop tables, or reverse data migrations.
3. If a reviewed reverse migration is unsafe, restore the pre-release database
   backup according to the incident plan instead.
4. Restore the previous reviewed code and compatible environment configuration.
5. Do not delete, replace, or roll back `/var/www/asas/media` unless the incident
   explicitly requires a separately reviewed media restore.
6. Re-run `check --deploy` and any migration action approved for the rollback.
7. Restart Gunicorn, validate Nginx, reload it only if its configuration changed,
   and repeat the smoke test.

Rollback is a release-specific decision; code rollback and database rollback
are not automatically equivalent.

### Rolling back to a release without the push worker

1. First, before restoring the previous code, stop the worker and its check:

   ```bash
   sudo systemctl disable --now asas-push-worker
   sudo systemctl disable --now asas-push-queue-check.timer
   ```

   The previous code has no `run_push_worker` command; with `Restart=always`
   the unit would otherwise fail and restart every 5 seconds, and the queue
   check would keep alerting.
2. Restore the previous code and restart `asas-backend` as in the general
   steps above. **No reverse migration is needed.** Migration
   `notifications.0003_notification_push_outbox` only adds columns, and its
   `NOT NULL` columns keep database defaults (`db_default`), so the previous
   code inserts notifications exactly as before. The new columns are ignored
   by it.
3. The previous code sends push inside the request again. Rows it inserts get
   `push_status = 'skipped'` from the database default.
4. Notifications created by the newer release that were still `pending` at
   rollback receive no push after it. They stay visible in the app.
5. When rolling forward again, re-enable both units (section 8 and section 14).
   Rows written by the previous code are `skipped` and are never sent twice.
   Rows still `pending` from before the rollback are sent if they are younger
   than `PUSH_MAX_AGE_HOURS`, otherwise marked `expired`.

## 17. Deferred decisions and accepted risks

- Media is currently public by link. UUID paths reduce guessing but do not
  provide authorization.
- Django Admin upload bypass risk is accepted for now because Admin use is
  restricted to the project owner. Admin forms remain unchanged.
- There are no signed media URLs, protected download endpoint, or
  `X-Accel-Redirect` flow.
- Sensitive or medical documents require a future protected-download design;
  they must not rely on the current public media policy.
- HSTS remains disabled initially and is enabled only after stable HTTPS and
  subdomain review.
- Adding Cloudflare or a load balancer requires revisiting `NUM_PROXIES=1`, the
  Nginx header policy, and the trusted network boundary.
- Final Gunicorn worker count awaits measured CPU/RAM and load-test data.
- Imported XLSX source files are not stored in media, but retention of parsed
  `normalized_data` in the database requires a separate product/data-retention
  decision.
