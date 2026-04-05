# Deploy Guide

## Overview

Deployment is fully automated via GitHub Actions. Pushing to `main` triggers:

```
Test Suite → Build & Push Docker Image → Deploy to DigitalOcean Droplet
```

Manual commands are available via `scripts/manage.sh` for operational tasks (scale, reseed, restart, rollback).

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Docker + Compose plugin | 24+ | Container runtime |
| Git | Any | Source control |
| `uv` | Any | Python dependency management (local dev only) |
| `sshpass` *(optional)* | Any | Password-based SSH from `manage.sh` — `brew install sshpass` |

---

## First Deploy (Bootstrapping a New Server)

### 1. Provision a DigitalOcean Droplet

- **Size**: 1 GB RAM / 1 vCPU / 25 GB SSD (minimum)
- **OS**: CentOS Stream 9 (or Ubuntu 22.04+)
- **Region**: Closest to your users

### 2. Install Docker on the server

```bash
# CentOS Stream 9
./scripts/manage.sh setup

# Or manually on Ubuntu:
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
```

### 3. Add GitHub Secrets

In **GitHub → Settings → Secrets → Actions**, add:

| Secret | Value |
|--------|-------|
| `SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_PASSWORD` | A strong password |
| `DROPLET_HOST` | Droplet public IP |
| `DROPLET_USER` | `root` |
| `DROPLET_PASSWORD` | Droplet SSH password |

### 4. Push to `main`

```bash
git push origin main
```

GitHub Actions runs `test.yml` → on pass, runs `ci-cd.yml`:
1. Builds the Docker image and pushes to GHCR
2. SSHes into the droplet
3. Writes `.env` from secrets
4. Runs `docker compose -f docker-compose.1gb.yml up -d`
5. Polls `GET /health` until 200 (up to 3 minutes)

### 5. Upload seed CSV files (optional)

If you have seed data from the hackathon platform:

```bash
# Copy your CSV files to the repo root, then:
./scripts/manage.sh upload-seeds
./scripts/manage.sh reseed csv
```

---

## Routine Deploy

Every push to `main` is deployed automatically. No manual steps required.

**To deploy a specific branch manually:**

```bash
# Trigger from GitHub Actions UI
# Actions → CI / CD → Run workflow → select branch
```

---

## Rollback

### Option A — Redeploy a previous image (recommended)

Every successful build tags the image with the short Git SHA (e.g., `ghcr.io/owner/repo:abc1234`).

```bash
# 1. Find the last known-good SHA from GitHub Actions history
# 2. SSH into the droplet
ssh root@<DROPLET_HOST>

# 3. Pull and switch to the old image
cd /opt/urlshortener
docker pull ghcr.io/<owner>/<repo>:<old-sha>
APP_IMAGE=ghcr.io/<owner>/<repo>:<old-sha> \
  docker compose -f docker-compose.1gb.yml up -d app
```

### Option B — Revert the code and push

```bash
# On your local machine
git revert HEAD           # creates a new revert commit
git push origin main      # triggers the full CI/CD pipeline
```

This is safer than Option A because it re-runs tests before deploying.

### Database rollback

The application uses Peewee's `create_tables(safe=True)` — tables are only created, never dropped or migrated automatically. To revert a schema change:

1. Stop the app: `./scripts/manage.sh stop app`
2. Connect to the DB: `docker compose exec db psql -U postgres hackathon_db`
3. Apply the reverse migration manually
4. Restart: `./scripts/manage.sh rebuild`

---

## Scaling

```bash
# Scale to 2 app containers (max safe on 1 GB)
./scripts/manage.sh scale 2

# Scale back to 1
./scripts/manage.sh scale 1
```

This runs `docker compose up --scale app=N` and restarts Nginx so it picks up the new containers via Docker DNS.

---

## Monitoring the Deploy

```bash
# Watch container status
./scripts/manage.sh status

# Tail app logs in real time
./scripts/manage.sh logs app

# Check health endpoint
curl https://<your-domain>/health
```

---

## Zero-Downtime Deploys

The CD pipeline uses `docker compose up -d`, which only recreates containers whose image has changed. During the app container restart:

- **Nginx** continues serving. Requests are queued or retried (`proxy_next_upstream error timeout`).
- **In-flight requests** to the dying container may return a `502` briefly (~2 s).
- **Redis** and **PostgreSQL** are unaffected.

For true zero-downtime, scale to 2 app containers before deploying. Nginx will route to the healthy instance while the other restarts.

---

## Post-Deploy Verification Checklist

```bash
# 1. Health
curl https://<domain>/health
# Expect: {"status":"ok","checks":{"db_primary":"ok","cache":"redis"}}

# 2. Redirect
curl -I https://<domain>/<known-short-code>
# Expect: HTTP/1.1 302 Found

# 3. API
curl https://<domain>/api/stats
# Expect: 200 with total_urls, total_users, etc.

# 4. Containers
./scripts/manage.sh status
# Expect: app, db, redis, nginx all "Up"
```
