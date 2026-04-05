# Troubleshooting Guide

## How to Use This Guide

Each entry follows the format:
- **Symptom** — what you observe
- **Likely cause** — why it happens
- **Fix** — exact commands to resolve it

---

## App / API Issues

### `502 Bad Gateway` from Nginx

**Symptom:** All API calls return `502`. Browser shows "Bad Gateway".

**Likely cause:** The app container is restarting or has crashed.

```bash
# Check container state
docker compose -f docker-compose.1gb.yml ps

# If status is "Restarting" or "Exited", check why
docker compose -f docker-compose.1gb.yml logs --tail=50 app
```

**Fix:**
```bash
# Most of the time, restart: unless-stopped recovers it automatically.
# If it's loop-crashing:
docker compose -f docker-compose.1gb.yml restart app

# If the image is bad (syntax error, import error), redeploy the last good image.
# See docs/deploy.md — Rollback section.
```

---

### App container keeps restarting (`Restarting (1)`)

**Symptom:** `docker compose ps` shows app in `Restarting` state. Logs show the same error repeating.

**Likely causes and fixes:**

| Error in logs | Cause | Fix |
|---------------|-------|-----|
| `database not ready after 60 seconds` | PostgreSQL is down or password mismatch | See "Database won't start" below |
| `ModuleNotFoundError` | Python dependency missing in image | Rebuild image: `docker compose -f docker-compose.1gb.yml build --no-cache app` |
| `Address already in use` | Port 5000 taken by another process | `lsof -i :5000` and kill the conflicting process |
| `Permission denied` | entrypoint.sh not executable | `chmod +x entrypoint.sh && git add entrypoint.sh && git commit` |

---

### `GET /health` returns `{"status":"degraded"}`

**Symptom:** Health check reports degraded. `checks.db_primary` contains an error string.

```bash
curl http://localhost/health
# → {"status":"degraded","checks":{"db_primary":"error: connection refused","cache":"simplecache"}}
```

**Fix:** The database is unreachable. See "Database won't start" below.

---

### `404` on every redirect

**Symptom:** Every `GET /<short_code>` returns `{"error":"URL not found"}`.

**Likely causes:**
1. You're testing against an empty database (freshly seeded or test environment)
2. The short code was deleted or is from a different environment

```bash
# Verify there are URLs in the database
curl http://localhost/api/urls
# Check the 'total' field

# If total is 0, seed the database
./scripts/manage.sh reseed csv   # or 'faker'
```

---

### Rate limiting — `429 Too Many Requests`

**Symptom:** Load tests or repeated curl calls return `429`.

**Cause:** Nginx rate limits: 10 req/min on `POST /api/urls`, 60 req/min on redirects (per IP).

**Fix for load testing** (not for production):
```bash
# Run tests against direct Gunicorn (port 5000, no rate limits)
BASE_URL=http://localhost:5000 k6 run load_tests/k6/bronze.js
```

**Fix for production** (if legitimate users are being rate-limited):
Edit `nginx/nginx.conf`, increase `rate=` in the `limit_req_zone` directives, then restart Nginx:
```bash
docker compose -f docker-compose.1gb.yml restart nginx
```

---

## Database Issues

### Database won't start

**Symptom:** `docker compose ps` shows `db` exiting repeatedly.

```bash
docker compose -f docker-compose.1gb.yml logs db
```

**Case 1: Password mismatch** (most common after a `DATABASE_PASSWORD` change)

```
FATAL: password authentication failed for user "postgres"
```

The PostgreSQL data volume was initialized with a different password. The CD pipeline handles this automatically, but locally:

```bash
# WARNING: This deletes all data in the database
docker compose -f docker-compose.1gb.yml stop db
docker compose -f docker-compose.1gb.yml rm -f db
docker volume rm urlshortener_postgres_data
docker compose -f docker-compose.1gb.yml up -d db
```

**Case 2: Disk full**

```bash
df -h /
# If 100%, free space:
docker image prune -f
docker system prune -f   # removes stopped containers, dangling images
```

**Case 3: Port conflict**

```
Error starting userland proxy: listen tcp4 0.0.0.0:5432: bind: address already in use
```

```bash
lsof -i :5432   # find what's using the port
# If it's a local PostgreSQL:
brew services stop postgresql   # macOS
systemctl stop postgresql       # Linux
```

---

### `max_connections` exceeded

**Symptom:** API returns `500`, DB logs show `remaining connection slots are reserved`.

```bash
docker compose -f docker-compose.1gb.yml exec db \
  psql -U postgres -c "SELECT count(*) FROM pg_stat_activity;"
```

**Fix:**
```bash
# Terminate idle connections
docker compose -f docker-compose.1gb.yml exec db \
  psql -U postgres -c "
    SELECT pg_terminate_backend(pid)
    FROM pg_stat_activity
    WHERE datname='hackathon_db'
      AND state='idle'
      AND pid <> pg_backend_pid();"

# Restart the app to reset connection pool
docker compose -f docker-compose.1gb.yml restart app
```

**Prevention:** `max_connections=50` in `docker-compose.1gb.yml`. With 2 app containers × 2 Gunicorn workers = 4 connections max (plus ~5 for administrative use). If you scale up, increase `max_connections` accordingly.

---

## Redis Issues

### Cache is not working (all requests hit the DB)

**Symptom:** `/health` shows `"cache":"simplecache"`. Response times are consistently slow even for `/api/stats`.

```bash
# Check Redis is running
docker compose -f docker-compose.1gb.yml ps redis

# Check Redis is reachable
docker compose -f docker-compose.1gb.yml exec redis redis-cli ping
# Expected: PONG

# Check the REDIS_URL in .env
cat .env | grep REDIS_URL
```

**Fix:**
```bash
docker compose -f docker-compose.1gb.yml restart redis
# Then restart app so it re-probes Redis
docker compose -f docker-compose.1gb.yml restart app
```

---

### Redis out of memory

**Symptom:** Redis logs `OOM command not allowed when used memory > 'maxmemory'`.

**Cause:** 64 MB limit reached and `allkeys-lru` eviction is not keeping up.

**Fix:** This is expected behaviour — Redis will evict old cache entries automatically. If you see errors, the most likely cause is `maxmemory-policy` not set:

```bash
docker compose -f docker-compose.1gb.yml exec redis \
  redis-cli config get maxmemory-policy
# Should return: allkeys-lru
```

---

## CI/CD Issues

### Tests pass locally but fail in CI

**Common cause:** Environment variable mismatch. CI uses `DATABASE_HOST=localhost` with a service container. Check the `env:` block in `.github/workflows/test.yml`.

**Check coverage failure:**
```bash
# Run with the same flags as CI
.venv/bin/pytest tests/integration/ \
  --cov=app --cov-report=term-missing --cov-fail-under=70 -v
```

---

### Deployment fails at "Health check"

**Symptom:** CD pipeline logs show "Attempt N: status=000, retrying..."

**Cause:** The app failed to start within 3 minutes. Usually a database issue on first deploy.

```bash
# SSH into the droplet
ssh root@<DROPLET_HOST>

# Check app logs
cd /opt/urlshortener
docker compose -f docker-compose.1gb.yml logs --tail=50 app
```

**Common fix:** Database credential mismatch on fresh volume. The CD pipeline auto-detects and handles this, but if it fails:

```bash
docker compose -f docker-compose.1gb.yml stop db
docker compose -f docker-compose.1gb.yml rm -f db
docker volume rm urlshortener_postgres_data
docker compose -f docker-compose.1gb.yml up -d
```

---

## Bugs We Hit During Development

These are real issues we encountered and how they were resolved.

### 1. Redirect cache not invalidating on `is_active=False`

**Problem:** After calling `PUT /api/urls/<id>` with `{"is_active": false}`, the URL was still redirecting. The inactive URL was served from Redis cache.

**Root cause:** The `_get_redirect_target()` function was cached with `@cache.memoize`, but `update_url()` was calling `cache.delete_memoized()` with the wrong argument order — passing `url_id` instead of `short_code`.

**Fix:** Corrected to `cache.delete_memoized(_get_redirect_target, url.short_code)` — the memoize key is based on the function arguments, which is the `short_code` string, not the integer ID.

**Test added:** `test_slumbering_guide_inactive_no_redirect_no_event`

---

### 2. Twin's Paradox — same URL submitted twice got the same short code

**Problem:** Submitting `POST /api/urls` twice with the same `original_url` produced the same `short_code` because the short code was derived from a hash of the URL.

**Root cause:** Initial implementation used `hashlib.md5(original_url)` for the short code, which is deterministic.

**Fix:** Switched to `to_base62(url.id)` — the short code is derived from the auto-increment primary key, which is always unique. The `INSERT` uses a placeholder `__pending_<random>` so the row gets its ID first, then the short code is updated in the same transaction.

**Test added:** `test_twin_paradox_same_url_creates_new_entry`

---

### 3. `X-App-Instance` header not passing through Nginx

**Problem:** The `X-App-Instance` header set by Flask was being stripped before reaching the client.

**Root cause:** Nginx strips hop-by-hop headers by default. Our header name was initially `X-Served-By`, which conflicted with an internal Nginx variable.

**Fix:** Renamed to `X-App-Instance` (no conflict). Nginx passes all non-hop-by-hop `X-` headers through transparently.

---

### 4. Integration tests failing with `username already taken`

**Problem:** Tests that created users with hardcoded usernames were failing intermittently when run in parallel or after a previous test left state.

**Root cause:** The `clean_db` autouse fixture wiped the database before each test, but the `app` fixture is session-scoped — the DB connection persisted. Some tests were seeing rows from previous tests when the cleanup happened mid-test.

**Fix:** The `clean_db` fixture explicitly deletes rows in the correct FK order (`Event → Url → User`) and clears the cache, both before and after each test. The order matters because of foreign key constraints.

---

### 5. Prometheus metrics endpoint returning 500 in tests

**Problem:** Running integration tests caused `prometheus-flask-exporter` to raise a `ValueError: Duplicated timeseries` error when the app factory was called more than once in the same process.

**Root cause:** `PrometheusMetrics(app)` registers metrics globally with the Prometheus client. Creating the app multiple times (once per test session in theory, but the exporter re-registered on every call in earlier code).

**Fix:** The `app` fixture is `scope="session"` — the Flask app is created exactly once per test run. This also makes tests faster.
