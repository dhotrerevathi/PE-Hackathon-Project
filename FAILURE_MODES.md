# Failure Modes — URL Shortener

This document describes every known failure mode for the URL shortener service:
what triggers it, what the user observes, how the system responds, and how to recover.

---

## Table of Contents

1. [App Container Crash](#1-app-container-crash)
2. [Database Unreachable](#2-database-unreachable)
3. [Redis Unreachable](#3-redis-unreachable)
4. [Nginx Crash](#4-nginx-crash)
5. [Out-of-Memory Kill](#5-out-of-memory-kill)
6. [Disk Full](#6-disk-full)
7. [Invalid Request Body](#7-invalid-request-body)
8. [Duplicate Resource (Conflict)](#8-duplicate-resource-conflict)
9. [Nonexistent Resource](#9-nonexistent-resource)
10. [Inactive URL Accessed](#10-inactive-url-accessed)
11. [Server Reboot](#11-server-reboot)
12. [Unhandled Python Exception](#12-unhandled-python-exception)

---

## 1. App Container Crash

| | |
|-|--|
| **Trigger** | Gunicorn worker segfault, `docker kill`, uncaught signal, OOM inside container |
| **User sees** | `502 Bad Gateway` from Nginx (JSON: `{"error":"Bad Gateway","message":"..."}`) for in-flight requests; requests queued during restart are dropped |
| **Detection** | `GET /health` returns `down` or connection refused; Nginx logs `upstream connect error` |
| **Auto-recovery** | Docker `restart: unless-stopped` recreates the container. New container runs entrypoint: waits for DB → seeds if needed → starts Gunicorn |
| **Time to recover** | 5–15 seconds (DB ready check + Gunicorn startup) |
| **Manual steps** | None under normal conditions. If loop-crashing: `docker compose logs app` → fix root cause → `docker compose restart app` |

**Demo:**

```bash
./scripts/chaos.sh
```

---

## 2. Database Unreachable

| | |
|-|--|
| **Trigger** | PostgreSQL container stopped, network partition, password mismatch, max_connections exceeded |
| **User sees** | All DB-backed endpoints (`/api/urls`, `/api/users`, `/api/events`, `/api/stats`) return `HTTP 500` with `{"error":"Internal Server Error","message":"An unexpected error occurred"}`. `/health` returns `{"status":"degraded","checks":{"db_primary":"error: ...","cache":"redis"}}` |
| **Detection** | `GET /health` → `status: "degraded"`. DB error visible in `checks.db_primary` |
| **Auto-recovery** | Automatic when PostgreSQL container restarts (`restart: unless-stopped` on the `db` service). Peewee reconnects on the next request (`reuse_if_open=True`) |
| **Time to recover** | 5–30 seconds (PostgreSQL startup + health check retries) |
| **Manual steps** | `docker compose -f docker-compose.1gb.yml restart db` if not auto-recovering |

**Redis-cached endpoints (`GET /api/stats`, `GET /<short_code>`) continue to work** during a DB outage if the cache is warm, since they serve responses directly from Redis without hitting PostgreSQL.

---

## 3. Redis Unreachable

| | |
|-|--|
| **Trigger** | Redis container stopped, memory exhausted, network issue |
| **User sees** | No visible degradation to end users. All API endpoints continue to function |
| **Detection** | `GET /health` → `checks.cache: "simplecache"` instead of `"redis"`. Cache hit rates drop to 0% (every request hits the DB) |
| **Impact** | Redirect latency increases from ~1 ms to ~10–50 ms (DB lookup). Under high load, DB connection pool may saturate |
| **Auto-recovery** | Flask-Caching automatically falls back to in-process `SimpleCache`. When Redis comes back, `cache.py` probes it on the next app restart and switches back |
| **Time to recover** | Zero downtime for users. Full Redis restoration after container restart: ~5 seconds |
| **Manual steps** | `docker compose -f docker-compose.1gb.yml restart redis`. App restart required to re-probe Redis: `docker compose restart app` |

---

## 4. Nginx Crash

| | |
|-|--|
| **Trigger** | Nginx container crash, bad config reload, OOM |
| **User sees** | Connection refused on port 80 (the public entry point). Port 5000 (direct Gunicorn) remains accessible if exposed |
| **Detection** | `curl http://localhost/health` → `Connection refused` |
| **Auto-recovery** | Docker `restart: unless-stopped` restarts the Nginx container. Nginx configuration is read-only mounted (`nginx.conf:ro`) so there is no config corruption |
| **Time to recover** | 2–5 seconds |
| **Manual steps** | `docker compose -f docker-compose.1gb.yml restart nginx` |

---

## 5. Out-of-Memory Kill

| | |
|-|--|
| **Trigger** | Container exceeds its `mem_limit` (app: 200 MB, db: 128 MB, redis: 80 MB, nginx: 32 MB) |
| **User sees** | Same as the relevant service crash (see above for app/db/redis/nginx) |
| **Detection** | `docker inspect <container> --format='{{.State.OOMKilled}}'` returns `true`. Also visible in `docker events` |
| **Auto-recovery** | `restart: unless-stopped`. Memory limits are set in `docker-compose.1gb.yml` to ensure the OS-level OOM-killer targets containers rather than the host OS processes |
| **Prevention** | Limits are tuned for a 1 GB droplet + 2 GB swap. Redis uses `allkeys-lru` eviction so it never exceeds 64 MB. PostgreSQL shared_buffers is capped at 32 MB |
| **Manual steps** | If the app crashes repeatedly due to OOM, reduce `GUNICORN_WORKERS` from 2 to 1 in the compose file |

---

## 6. Disk Full

| | |
|-|--|
| **Trigger** | PostgreSQL WAL logs fill the volume; Docker image/container layers accumulate |
| **User sees** | Write operations (`POST /api/urls`, `POST /api/users`, etc.) fail with `HTTP 500`. Reads from Redis cache still work |
| **Detection** | `df -h /` shows 100% usage. PostgreSQL logs `could not write to file` |
| **Auto-recovery** | None. Disk space must be freed manually |
| **Manual steps** | `docker image prune -f` (removes dangling images); `docker volume prune` (⚠ removes unused volumes including DB data — confirm first); increase droplet disk size |

---

## 7. Invalid Request Body

| | |
|-|--|
| **Trigger** | Client sends wrong `Content-Type`, a JSON string instead of a JSON object, missing required fields, wrong field types |
| **User sees** | `HTTP 400 Bad Request` with a structured JSON error body — never an HTML error page or Python traceback |
| **Examples** |  |

```json
// Raw string body
POST /api/urls  body: "just a string"
→ 400 {"error": "Request body must be a JSON object"}

// Wrong type
POST /api/users  body: {"username": 99999, "email": "x@x.com"}
→ 400 {"error": "username is required and must be a non-empty string"}

// Not a URL
POST /api/urls  body: {"original_url": "not-a-url"}
→ 400 {"error": "original_url must be a valid http or https URL"}

// Invalid email
POST /api/users  body: {"username": "alice", "email": "notanemail"}
→ 400 {"error": "email is invalid"}

// Missing field
POST /api/users  body: {"username": "bob"}
→ 400 {"error": "email is required and must be a non-empty string"}
```

**Demo:**

```bash
./scripts/garbage.sh
```

---

## 8. Duplicate Resource (Conflict)

| | |
|-|--|
| **Trigger** | Client attempts to create a user with an existing `username` or `email`, or create a URL with an already-taken `short_code` |
| **User sees** | `HTTP 409 Conflict` with a JSON error body |
| **Examples** |  |

```json
// Duplicate username
→ 409 {"error": "username already taken"}

// Duplicate email
→ 409 {"error": "email already registered"}

// Custom short code already in use
→ 409 {"error": "short_code already taken"}
```

**No partial data is written.** The conflict is detected before any `INSERT` commits.

---

## 9. Nonexistent Resource

| | |
|-|--|
| **Trigger** | Client requests a user, URL, or short code that does not exist in the database |
| **User sees** | `HTTP 404 Not Found` with a JSON error body. Never an HTML 404 page |
| **Examples** |  |

```json
GET /api/users/999999  → 404 {"error": "User not found"}
GET /api/urls/999999   → 404 {"error": "URL not found"}
GET /doesnotexist99    → 404 {"error": "URL not found"}
POST /api/urls  body: {"original_url": "...", "user_id": 999999}
               → 404 {"error": "User not found"}
```

---

## 10. Inactive URL Accessed

| | |
|-|--|
| **Trigger** | A URL has been deactivated (`is_active: false`) via `PUT /api/urls/<id>`, and a user visits its short code |
| **User sees** | `HTTP 404 {"error": "URL is inactive"}` — no redirect occurs |
| **Side effects** | **No click event is logged.** The Slumbering Guide rule: dormant routes leave no footprint |
| **Cache behaviour** | The `PUT` that sets `is_active: false` calls `cache.delete_memoized(_get_redirect_target, short_code)`, so the cached redirect target is evicted immediately. The next visit sees the inactive state from the DB |
| **Recovery** | `PUT /api/urls/<id>` with `{"is_active": true}` re-enables the URL. Cache is evicted on the next update |

---

## 11. Server Reboot

| | |
|-|--|
| **Trigger** | Planned reboot, kernel update, power cycle |
| **User sees** | Complete service outage during reboot. Automatic recovery once the OS is back |
| **Auto-recovery** | Docker daemon starts on boot (`systemctl enable docker`). All containers with `restart: unless-stopped` start automatically. Nginx is last to finish but starts within seconds of the app |
| **Time to recover** | OS boot time + ~30 seconds for all services to pass health checks |
| **Data safety** | PostgreSQL data is on a named volume (`postgres_data`). Reboots do not cause data loss |

---

## 12. Unhandled Python Exception

| | |
|-|--|
| **Trigger** | A bug in application code raises an exception that is not caught by route-level validation |
| **User sees** | `HTTP 500 {"error":"Internal Server Error","message":"An unexpected error occurred"}` — never a Python traceback or Werkzeug debugger page |
| **Implementation** | Caught by the `@app.errorhandler(Exception)` handler in `app/__init__.py` |
| **Detection** | Gunicorn stderr logs show the full traceback for debugging. Prometheus `http_request_exceptions_total` counter increments |
| **Recovery** | No restart needed. The Gunicorn worker that handled the request is still alive. Only a bug fix is required |

---

## Summary Table

| Failure | User impact | Auto-recovers | Time |
|---------|-------------|---------------|------|
| App container crash | 502 during restart | ✅ Docker restart | 5–15 s |
| Database down | 500 on writes; cached reads OK | ✅ Docker restart | 5–30 s |
| Redis down | No visible impact (SimpleCache fallback) | ✅ Cache fallback | 0 s |
| Nginx crash | Connection refused on :80 | ✅ Docker restart | 2–5 s |
| OOM kill | Same as service crash | ✅ Docker restart | 5–15 s |
| Disk full | 500 on writes | ❌ Manual | — |
| Bad request body | 400 JSON error | N/A | — |
| Duplicate resource | 409 JSON error | N/A | — |
| Nonexistent resource | 404 JSON error | N/A | — |
| Inactive URL | 404 JSON error, no event logged | N/A | — |
| Server reboot | Full outage during boot | ✅ Docker on-boot | Boot time + 30 s |
| Unhandled exception | 500 JSON error (no crash) | N/A | — |

---

*Last updated: 2026-04-05*
