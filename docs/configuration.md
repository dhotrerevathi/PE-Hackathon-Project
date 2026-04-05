# Configuration Reference

All configuration is passed via environment variables. The app reads them at startup via `python-dotenv` (`.env` file) or from the container environment.

---

## Application Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | ✅ Yes | `dev-secret-change-me` | Flask session signing key. **Must be random and secret in production.** Generate with: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `FLASK_DEBUG` | No | `false` | Enable Flask debug mode. **Never set to `true` in production** — exposes an interactive debugger. |
| `PORT` | No | `5000` | Port Gunicorn binds to inside the container. |
| `GUNICORN_WORKERS` | No | `4` | Number of Gunicorn worker processes. Rule of thumb: `2 × CPU_cores + 1`. Set to `2` on the 1 GB droplet. |

---

## Database Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_HOST` | ✅ Yes | `localhost` | PostgreSQL host. Use `db` inside Docker Compose. |
| `DATABASE_PORT` | No | `5432` | PostgreSQL port. |
| `DATABASE_NAME` | ✅ Yes | `hackathon_db` | Database name. Must be created before first run. |
| `DATABASE_USER` | ✅ Yes | `postgres` | PostgreSQL user. |
| `DATABASE_PASSWORD` | ✅ Yes | `postgres` | PostgreSQL password. **Change in production.** |
| `DATABASE_READ_HOST` | No | *(empty)* | Host of a read replica. Leave empty to send all reads to the primary. Not used on the 1 GB single-node setup. |

---

## Cache Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REDIS_URL` | No | `redis://redis:6379/0` | Redis connection URL. If unreachable at startup, Flask-Caching falls back to `SimpleCache` (in-process). Format: `redis://[password@]host:port/db` |

---

## Deployment Variables (CI/CD and `manage.sh`)

These are only needed for the deployment pipeline and `scripts/manage.sh`. They are **never committed** — store them as GitHub Secrets or in `scripts/.env.local`.

| Variable | Where used | Description |
|----------|-----------|-------------|
| `DROPLET_HOST` | `manage.sh`, CI/CD | DigitalOcean droplet public IP |
| `DROPLET_USER` | `manage.sh` | SSH username (default: `root`) |
| `DROPLET_PASS` | `manage.sh` | SSH password. Leave empty to use key auth (recommended). |
| `DEPLOY_DIR` | `manage.sh` | Deployment directory on server (default: `/opt/urlshortener`) |
| `DISCORD_WEBHOOK` | `manage.sh` | Discord webhook URL for status notifications |
| `APP_IMAGE` | `docker-compose.1gb.yml` | Full image reference including tag, set by CD pipeline |

---

## GitHub Secrets (required for CD pipeline)

Set these in **GitHub → Repository → Settings → Secrets and variables → Actions**:

| Secret | Description |
|--------|-------------|
| `SECRET_KEY` | Flask secret key (production) |
| `DATABASE_PASSWORD` | PostgreSQL password (production) |
| `DROPLET_HOST` | Server IP |
| `DROPLET_USER` | SSH username |
| `DROPLET_PASSWORD` | SSH password (or use key-based auth instead) |

`GITHUB_TOKEN` is automatically provided by GitHub Actions — no manual setup needed for pushing to GHCR.

---

## Example `.env` Files

### Local development (`.env`)

```env
FLASK_DEBUG=true
SECRET_KEY=local-dev-only-not-secret
DATABASE_NAME=hackathon_db
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_USER=postgres
DATABASE_PASSWORD=postgres
REDIS_URL=redis://localhost:6379/0
PORT=5000
GUNICORN_WORKERS=2
```

### Production (written by CD pipeline on the server)

```env
SECRET_KEY=<64-char random hex>
DATABASE_PASSWORD=<strong password>
DATABASE_NAME=hackathon_db
DATABASE_HOST=db
DATABASE_PORT=5432
DATABASE_USER=postgres
DATABASE_READ_HOST=
REDIS_URL=redis://redis:6379/0
PORT=5000
GUNICORN_WORKERS=2
APP_IMAGE=ghcr.io/owner/repo:abc1234
```

---

## Validation

The app does **not** crash on missing optional variables — it uses safe defaults. It **will** fail to start if PostgreSQL is unreachable (the `entrypoint.sh` retries for 60 seconds then exits non-zero, causing Docker to restart the container per the `restart: unless-stopped` policy).

To verify all variables are loaded correctly:

```bash
# Check health — shows DB and cache status
curl http://localhost:5000/health
# → {"status":"ok","checks":{"db_primary":"ok","cache":"redis"}}

# If db_primary is an error string, check DATABASE_* variables
# If cache is "simplecache", check REDIS_URL
```
