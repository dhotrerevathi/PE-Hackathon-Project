# Runbooks

Runbooks are step-by-step procedures for responding to specific alerts or incidents. Each runbook includes: trigger condition, severity, impact, diagnostic steps, resolution steps, and escalation path.

---

## RB-01: App Container Crash Loop

**Trigger:** `docker compose ps` shows app container in `Restarting` state for more than 2 minutes.

**Severity:** 🔴 Critical — service is down or severely degraded.

**User impact:** `502 Bad Gateway` on all requests.

**Steps:**

```bash
# 1. Check container status
docker compose -f docker-compose.1gb.yml ps

# 2. Read the last 50 lines of app logs
docker compose -f docker-compose.1gb.yml logs --tail=50 app

# 3. Identify the error class:
```

| Error in logs | Go to |
|---------------|-------|
| `database not ready` | RB-02 (DB down) |
| `ModuleNotFoundError` / `ImportError` | Step 4a |
| `Address already in use` | Step 4b |
| `OOM` / `Killed` | RB-05 (OOM) |
| Unknown Python exception | Step 4c |

```bash
# 4a. Missing Python module — rebuild image
docker compose -f docker-compose.1gb.yml build --no-cache app
docker compose -f docker-compose.1gb.yml up -d app

# 4b. Port conflict — find and kill the occupying process
lsof -i :5000
kill <PID>
docker compose -f docker-compose.1gb.yml up -d app

# 4c. Unknown exception — rollback to last known-good image
# Find the last passing CI run SHA on GitHub Actions
APP_IMAGE=ghcr.io/<owner>/<repo>:<good-sha> \
  docker compose -f docker-compose.1gb.yml up -d app

# 5. Confirm recovery
curl http://localhost/health
# Expected: {"status":"ok",...}
```

**Escalation:** If crash loop persists after rollback, the database or volume may be corrupt. Run `./scripts/manage.sh status` and escalate to RB-02 or RB-06.

---

## RB-02: Database Unreachable

**Trigger:** `GET /health` returns `{"status":"degraded","checks":{"db_primary":"error: ..."}}`.

**Severity:** 🔴 Critical — all write endpoints and uncached reads are failing.

**User impact:** `500` on POST/PUT/DELETE. Cached redirects and stats may still work.

**Steps:**

```bash
# 1. Check if the DB container is running
docker compose -f docker-compose.1gb.yml ps db

# 2. Check DB logs
docker compose -f docker-compose.1gb.yml logs --tail=30 db

# 3a. Container is stopped — restart it
docker compose -f docker-compose.1gb.yml restart db
# Wait for health check: docker compose ps db
# Expected: "healthy" within 30s

# 3b. Password authentication failure
# Error: "FATAL: password authentication failed"
# The DB volume was initialized with a different password.
# WARNING: This will destroy all data if not backed up.
docker compose -f docker-compose.1gb.yml stop db
docker compose -f docker-compose.1gb.yml rm -f db
docker volume rm urlshortener_postgres_data
docker compose -f docker-compose.1gb.yml up -d db
# Wait for db to be healthy, then restart app to trigger reseed
docker compose -f docker-compose.1gb.yml restart app

# 3c. Disk full
df -h /
# If 100%:
docker image prune -f
docker system prune --volumes -f   # WARNING: removes unused volumes
# See RB-06 for disk runbook

# 4. Restart app after DB recovery (resets connection pool)
docker compose -f docker-compose.1gb.yml restart app

# 5. Confirm
curl http://localhost/health
# Expected: {"status":"ok","checks":{"db_primary":"ok",...}}
```

**Escalation:** If the volume is corrupted and no backup exists, the database must be re-seeded from CSV files. See `docs/deploy.md` — Seed section.

---

## RB-03: High Response Latency

**Trigger:** p95 response time exceeds 3 seconds (visible in k6 output or Grafana dashboard).

**Severity:** 🟡 Warning — service is slow but functional.

**User impact:** Redirects and API calls are sluggish. Timeouts possible for long-running queries.

**Steps:**

```bash
# 1. Check if Redis is connected (cached endpoints should be fast)
curl http://localhost/health | python3 -m json.tool
# If cache is "simplecache", Redis is down — see RB-04

# 2. Check active DB connections and slow queries
docker compose -f docker-compose.1gb.yml exec db \
  psql -U postgres hackathon_db -c "
    SELECT pid, state, query_start, left(query, 80) as query
    FROM pg_stat_activity
    WHERE datname='hackathon_db'
    ORDER BY query_start;"

# 3. Terminate long-running queries (older than 30s)
docker compose -f docker-compose.1gb.yml exec db \
  psql -U postgres hackathon_db -c "
    SELECT pg_terminate_backend(pid)
    FROM pg_stat_activity
    WHERE datname='hackathon_db'
      AND state != 'idle'
      AND query_start < NOW() - INTERVAL '30 seconds'
      AND pid <> pg_backend_pid();"

# 4. Check server resource pressure
free -h           # memory
uptime            # load average
df -h /           # disk

# 5. Scale to 2 app containers if CPU is the bottleneck
./scripts/manage.sh scale 2

# 6. Re-run load test to confirm improvement
k6 run load_tests/k6/bronze.js
```

**Root cause history:** The redirect path was the primary bottleneck before Redis caching was added. If Redis is connected and latency is still high, the bottleneck has moved to the DB or network. See `docs/capacity.md` for thresholds.

---

## RB-04: Redis Down / Cache Miss

**Trigger:** `GET /health` shows `"cache":"simplecache"`. Redirect latency increases noticeably.

**Severity:** 🟡 Warning — service functional, but degraded performance under load.

**User impact:** All requests hit PostgreSQL. Under heavy load, DB connection pool may saturate.

**Steps:**

```bash
# 1. Check Redis container
docker compose -f docker-compose.1gb.yml ps redis

# 2. Check Redis logs
docker compose -f docker-compose.1gb.yml logs --tail=20 redis

# 3. Test Redis connectivity
docker compose -f docker-compose.1gb.yml exec redis redis-cli ping
# Expected: PONG

# 4. Restart Redis
docker compose -f docker-compose.1gb.yml restart redis

# 5. Restart app so it re-probes Redis on startup
docker compose -f docker-compose.1gb.yml restart app

# 6. Verify Redis is now active
curl http://localhost/health | python3 -m json.tool
# Expected: "cache": "redis"
```

---

## RB-05: Out-of-Memory Kill

**Trigger:** Container disappears without logs. `docker inspect <id> --format='{{.State.OOMKilled}}'` returns `true`.

**Severity:** 🔴 Critical if app is OOM-killed; 🟡 Warning if redis/db (they auto-restart).

**User impact:** Same as container crash for the affected service.

**Steps:**

```bash
# 1. Identify which container was OOM-killed
docker events --since 30m --filter event=oom

# 2. Check per-container memory usage
docker stats --no-stream

# 3. Check current memory limits (docker-compose.1gb.yml)
grep mem_limit docker-compose.1gb.yml

# 4. If app is OOM-killed: reduce Gunicorn workers
# Edit docker-compose.1gb.yml:
#   GUNICORN_WORKERS: 1   (was 2)
docker compose -f docker-compose.1gb.yml up -d app

# 5. If Redis is OOM-killed: it will auto-restart and begin evicting (allkeys-lru)
# No action needed — Redis self-manages via maxmemory-policy

# 6. Confirm memory headroom
docker stats --no-stream
free -h
```

**Budget reference (1 GB droplet):**

| Service | Limit | Typical RSS |
|---------|-------|------------|
| nginx | 32 MB | ~20 MB |
| app (×1) | 200 MB | ~160 MB |
| db | 128 MB | ~75 MB |
| redis | 80 MB | ~20 MB |
| OS + Docker | — | ~270 MB |
| **Total** | — | **~545 MB** |

---

## RB-06: Disk Space Low

**Trigger:** `df -h /` shows > 85% usage.

**Severity:** 🟡 Warning at 85%; 🔴 Critical at 95% (PostgreSQL will stop writing WAL).

**Steps:**

```bash
# 1. Check disk usage
df -h /
du -sh /var/lib/docker/*   # find largest consumers

# 2. Remove stopped containers and dangling images
docker container prune -f
docker image prune -f

# 3. Remove unused Docker volumes (CAUTION: verify nothing critical)
docker volume ls
# Only prune volumes that are NOT postgres_data or redis_data
docker volume prune -f --filter "label!=keep"

# 4. Clear old logs
docker compose -f docker-compose.1gb.yml logs --no-log-prefix app \
  | wc -c   # check log size

# Truncate logs for a specific container (find container ID first)
truncate -s 0 $(docker inspect --format='{{.LogPath}}' <container_id>)

# 5. If still low: expand the droplet's disk in DigitalOcean console
# → Droplet → Resize → Disk only

# 6. Monitor
watch -n10 'df -h /'
```

---

## RB-07: CI Tests Failing (Blocked Deploy)

**Trigger:** GitHub Actions `Tests` workflow shows red. Deployment is blocked.

**Severity:** 🟡 Warning — production is unaffected, but new code cannot be shipped.

**Steps:**

```bash
# 1. Read the failure message in GitHub Actions UI
#    → Actions → Tests → failed job → expand the failing step

# 2. Reproduce locally
uv sync --group dev

# Unit tests
.venv/bin/pytest tests/unit/ -v

# Integration tests (requires PostgreSQL)
docker run -d -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=hackathon_db \
  -p 5432:5432 postgres:16-alpine
.venv/bin/pytest tests/integration/ -v --cov=app --cov-fail-under=70

# 3. Common failure modes:
```

| Failure message | Cause | Fix |
|-----------------|-------|-----|
| `coverage: X% < 70%` | New code without tests | Add tests for new functions |
| `409 Conflict` | Test isolation issue — DB not cleaned | Check `clean_db` fixture ordering |
| `assert r.status_code == 201` | Route behaviour changed | Review route changes |
| `ModuleNotFoundError` | New dependency not in `pyproject.toml` | `uv add <package>` |
| hadolint warning | Dockerfile lint issue | Fix the flagged line in `Dockerfile` |
