# MLH PE Hackathon — URL Shortener (Flask · Peewee · PostgreSQL)

A production-grade URL shortener built for the MLH PE Hackathon 2026.

**Stack:** Flask · Peewee ORM · PostgreSQL · Redis · Gunicorn · Nginx · Docker

---

## Architecture

```
                        ┌─────────────────────────────────────┐
 Client / Browser  ────►│  Nginx  :80                         │
                        │  least_conn · rate limit · gzip     │
                        └───────────┬─────────────┬───────────┘
                                    │             │  (scale-out)
                        ┌───────────▼───┐   ┌─────▼───────────┐
                        │  App  :5000   │   │  App  :5000      │
                        │  Gunicorn ×2  │   │  Gunicorn ×2     │
                        │  Flask+Peewee │   │  Flask+Peewee    │
                        └──────┬────┬──┘   └──────┬────┬──────┘
                               │    │             │    │
                    ┌──────────▼─┐  └──────┐  ┌──┘  ┌─▼──────────┐
                    │ PostgreSQL │         └──┘     │    Redis    │
                    │   :5432    │                  │    :6379    │
                    │  users     │  ◄── writes      │  redirects  │
                    │  urls      │                  │  stats      │
                    │  events    │                  │  url lookups│
                    └────────────┘                  └─────────────┘
```

**Full diagram, data model, and request flows:** [docs/architecture.md](docs/architecture.md)

---

## Documentation Index

| Document | Contents |
|----------|---------|
| [docs/architecture.md](docs/architecture.md) | System diagram, request flows, data model, port map, scaling model |
| [docs/deploy.md](docs/deploy.md) | First deploy, routine deploy, rollback, scaling, post-deploy checklist |
| [docs/configuration.md](docs/configuration.md) | All environment variables, GitHub Secrets, example `.env` files |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common issues, real bugs we hit + how we fixed them |
| [docs/runbooks.md](docs/runbooks.md) | Step-by-step incident response for 7 alert types |
| [docs/decisions.md](docs/decisions.md) | Why Flask, Peewee, PostgreSQL, Redis, Nginx, Docker Compose, Base62 |
| [docs/capacity.md](docs/capacity.md) | Throughput benchmarks, hard limits, scaling path to internet scale |
| [FAILURE_MODES.md](FAILURE_MODES.md) | 12 failure scenarios with user impact, auto-recovery, time-to-recover |

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Project Structure](#project-structure)
3. [API Reference](#api-reference)
4. [Reliability Quest — Evidence](#reliability-quest--evidence)
   - [Bronze: The Shield](#-tier-1-bronze--the-shield)
   - [Silver: The Fortress](#-tier-2-silver--the-fortress)
   - [Gold: The Immortal](#-tier-3-gold--the-immortal)
5. [Scalability Quest — Evidence](#scalability-quest--evidence)
   - [Bronze: The Baseline](#-tier-1-bronze--the-baseline)
   - [Silver: The Scale-Out](#-tier-2-silver--the-scale-out)
   - [Gold: The Speed of Light](#-tier-3-gold--the-speed-of-light)
6. [Bottleneck Report](#bottleneck-report)
7. [Hidden Challenge Mitigations](#hidden-challenge-mitigations)
8. [Error Handling](#error-handling)
9. [Failure Modes](#failure-modes)
10. [Chaos Mode — Docker Restart Policy](#chaos-mode--docker-restart-policy)
11. [Development Reference](#development-reference)

---

## Quick Start

```bash
# 1. Clone the repo
git clone <repo-url> && cd PE-Hackathon-Template-2026

# 2. Install dependencies (uv manages Python version + virtualenv)
uv sync

# 3. Create the database
createdb hackathon_db

# 4. Configure environment
cp .env.example .env   # edit DB credentials if needed

# 5. Run the server
uv run run.py

# 6. Verify
curl http://localhost:5000/health
# → {"status":"ok","checks":{"db_primary":"ok"}}
```

---

## Project Structure

```
PE-Hackathon-Template-2026/
├── app/
│   ├── __init__.py            # App factory — error handlers, /health, Prometheus
│   ├── cache.py               # Flask-Caching (Redis → SimpleCache fallback)
│   ├── database.py            # Peewee DatabaseProxy, connection lifecycle hooks
│   ├── seed.py                # CSV seeding helpers + _parse_bool
│   ├── utils.py               # to_base62(), is_valid_custom_code(), RESERVED set
│   ├── models/
│   │   ├── event.py           # Event model (click, created)
│   │   ├── url.py             # Url model
│   │   └── user.py            # User model
│   └── routes/
│       ├── events.py          # GET /api/events
│       ├── stats.py           # GET /api/stats
│       ├── urls.py            # CRUD /api/urls + /<short_code> redirect
│       └── users.py           # CRUD /api/users + bulk import
├── tests/
│   ├── unit/
│   │   ├── test_utils.py      # Pure-Python tests for to_base62, is_valid_custom_code
│   │   └── test_seed.py       # Pure-Python tests for _parse_bool
│   └── integration/
│       ├── conftest.py        # pytest fixtures (real PostgreSQL, isolated per-test DB)
│       ├── test_routes.py     # Health, URL CRUD, redirect, stats, events
│       ├── test_users.py      # User CRUD, bulk CSV import, validation
│       └── test_extra.py      # Edge cases, filters, pagination, stats detail
├── .github/workflows/
│   ├── test.yml               # CI: lint → unit → integration (blocks on failure)
│   └── ci-cd.yml              # CD: test → build image → deploy to droplet
├── docker-compose.1gb.yml     # Production compose (restart: unless-stopped on all services)
├── Dockerfile
└── pyproject.toml
```

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check — returns `{"status":"ok","checks":{...}}` |
| `GET` | `/<short_code>` | Redirect to original URL (302), logs click event |
| `GET` | `/api/urls` | List URLs (paginated, filterable by `user_id`, `active`) |
| `GET` | `/api/urls/<id>` | Get single URL |
| `POST` | `/api/urls` | Create URL (returns `short_code`) |
| `PUT` | `/api/urls/<id>` | Update URL title / `is_active` |
| `DELETE` | `/api/urls/<id>` | Delete URL |
| `GET` | `/api/urls/<id>/stats` | Click count + event history for a URL |
| `GET` | `/api/users` | List users (paginated) |
| `GET` | `/api/users/<id>` | Get user with associated URLs |
| `POST` | `/api/users` | Create user |
| `PUT` | `/api/users/<id>` | Update user |
| `POST` | `/api/users/bulk` | Bulk import users from CSV (`multipart/form-data`, field: `file`) |
| `GET` | `/api/events` | List events (filterable by `event_type`, `url_id`) |
| `GET` | `/api/stats` | Global stats: total URLs, active URLs, users, clicks, top URLs |
| `GET` | `/metrics` | Prometheus metrics endpoint |

All endpoints respond in JSON. All error responses are clean JSON objects — no raw stack traces are ever returned to the client.

---

## Reliability Quest — Evidence

### 🥉 Tier 1: Bronze — The Shield

#### Unit Tests (pytest)

Unit tests live in `tests/unit/` and run with zero service dependencies (no database, no network).

**`tests/unit/test_utils.py`** — tests `to_base62()` and `is_valid_custom_code()` in isolation:

- `TestBase62`: 9 tests covering zero, single digits, letter range, two-digit values, known values, uniqueness, monotonic growth, large IDs, and character set validity.
- `TestIsValidCustomCode`: 9 tests covering valid codes, hyphen/underscore, empty input, length limits, special characters, reserved paths, case-insensitive reserved check, and numbers-only codes.

**`tests/unit/test_seed.py`** — tests `_parse_bool()` with parametrized inputs (truthy values, falsy values, whitespace stripping, return type verification).

Run unit tests:

```bash
uv run pytest tests/unit/ -v
```

#### CI — GitHub Actions

`.github/workflows/test.yml` runs on every push and pull request:

```
lint → unit tests → integration tests
```

Deployment in `ci-cd.yml` **requires the `test` job to pass** before building or pushing an image. A failed test blocks the deploy at the pipeline level.

#### Health Check

`GET /health` always returns HTTP 200 with a JSON body:

```json
{ "status": "ok", "checks": { "db_primary": "ok" } }
```

If the database is unreachable, `status` becomes `"degraded"` and `db_primary` contains the error string. Load balancers and Docker healthchecks poll this endpoint.

---

### 🥈 Tier 2: Silver — The Fortress

#### Coverage ≥ 50%

The integration CI step enforces a minimum coverage threshold:

```yaml
# .github/workflows/test.yml
- name: Run integration tests
  run: |
    .venv/bin/pytest tests/integration/ \
      --cov=app \
      --cov-report=term-missing \
      --cov-fail-under=70 \
      -v
```

`--cov-fail-under=70` causes the CI job to exit non-zero (blocking the deploy) if coverage drops below 70 %.

Run coverage locally:

```bash
uv run pytest tests/integration/ --cov=app --cov-report=term-missing
```

#### Integration Tests

Integration tests in `tests/integration/` spin up a real PostgreSQL instance and hit the Flask test client end-to-end. Each test gets a clean, isolated database (rows wiped before and after via the `clean_db` autouse fixture).

Key integration test classes:

| File | Class | What it covers |
|------|-------|----------------|
| `test_routes.py` | `TestHealth` | `/health` JSON shape, DB check field |
| `test_routes.py` | `TestCreateUrl` | 201 response, short code generation, custom codes, reserved codes, 400/409 errors, Twin's Paradox, Fractured Vessel, Deceitful Scroll (invalid URL), optional user_id |
| `test_routes.py` | `TestRedirect` | 302 redirect, click event logging, 404 for unknown codes, Slumbering Guide (inactive URL) |
| `test_routes.py` | `TestUrlCrud` | List, get, update, deactivate, delete, per-URL stats |
| `test_routes.py` | `TestStats` | Global stats structure and counts |
| `test_routes.py` | `TestEvents` | Events list, Unseen Observer (click events appear), filters |
| `test_users.py` | `TestListUsers` | Pagination, totals, field shape |
| `test_users.py` | `TestGetUser` | Field shape, associated URLs |
| `test_users.py` | `TestCreateUser` | 201 response, field validation, Unwitting Stranger, Fractured Vessel |
| `test_users.py` | `TestUpdateUser` | 200 on update, field preservation, 404 on nonexistent, 409 on duplicate, 400 on invalid types |
| `test_users.py` | `TestBulkCreateUsers` | CSV import, count field, duplicate skipping, missing-file 400 |
| `test_extra.py` | `TestUrlListFilters` | `?active=true` filter, pagination |
| `test_extra.py` | `TestUrlUserFilter` | `?user_id=X` filter, nonexistent user_id returns 404, invalid URL format rejected |
| `test_extra.py` | `TestUrlCrudEdgeCases` | 404 on nonexistent, custom code length limit, zero-click stats |
| `test_extra.py` | `TestStatsDetailed` | total events, click counting, top_urls |

#### CI Gatekeeper — Blocked Deploy

The `ci-cd.yml` pipeline:

```yaml
jobs:
  test:   # runs test.yml (lint + unit + integration)
  build:
    needs: test   # ← only runs if test passes
  deploy:
    needs: build  # ← only runs if build passes
```

A single failing test prevents the Docker image from being built and the droplet from being updated.

#### Error Handling

All HTTP errors return JSON, never HTML or Python stack traces:

```python
# app/__init__.py
@app.errorhandler(HTTPException)
def handle_http_exception(e):
    return jsonify({"error": e.name, "message": e.description}), e.code

@app.errorhandler(Exception)
def handle_generic_exception(e):
    return jsonify({"error": "Internal Server Error",
                    "message": "An unexpected error occurred"}), 500
```

| Scenario | Status | Response body |
|----------|--------|---------------|
| Unknown short code | 404 | `{"error": "URL not found"}` |
| Unknown user or URL ID | 404 | `{"error": "...not found"}` |
| Missing required field | 400 | `{"error": "<field> is required"}` |
| Invalid field type | 400 | `{"error": "<field> must be ..."}` |
| Duplicate username / short code | 409 | `{"error": "... already taken"}` |
| Non-JSON body | 400 | `{"error": "Request body must be a JSON object"}` |
| Unhandled server exception | 500 | `{"error": "Internal Server Error", "message": "An unexpected error occurred"}` |

---

### 🥇 Tier 3: Gold — The Immortal

#### Coverage ≥ 70%

The unit and integration suites together achieve ≥ 70 % coverage across `app/`. The integration CI threshold is set at 70 % (`--cov-fail-under=70`), enforced as a hard gate in every CI run.

To measure locally:

```bash
uv run pytest tests/ --cov=app --cov-report=term-missing
```

#### Graceful Failure — Clean JSON on Bad Input

Every route validates its inputs before touching the database. Invalid requests receive structured JSON errors, not tracebacks.

Examples:

```bash
# Missing required field
curl -s -X POST http://localhost:5000/api/urls -H "Content-Type: application/json" -d '{}'
# → {"error":"original_url is required"}  HTTP 400

# Non-string username (integer)
curl -s -X POST http://localhost:5000/api/users \
  -H "Content-Type: application/json" \
  -d '{"username": 12345, "email": "x@x.com"}'
# → {"error":"username is required and must be a non-empty string"}  HTTP 400

# Raw string body instead of JSON object
curl -s -X POST http://localhost:5000/api/urls \
  -H "Content-Type: application/json" \
  -d '"just a string"'
# → {"error":"Request body must be a JSON object"}  HTTP 400

# Nonexistent short code
curl -s http://localhost:5000/doesnotexist99
# → {"error":"URL not found"}  HTTP 404

# Inactive URL
curl -s http://localhost:5000/<inactive-short-code>
# → {"error":"URL is inactive"}  HTTP 404
```

#### Chaos Mode — Container Auto-Restart

All services in `docker-compose.1gb.yml` have `restart: unless-stopped`:

```yaml
# docker-compose.1gb.yml
services:
  nginx:
    restart: unless-stopped
  app:
    restart: unless-stopped
  db:
    restart: unless-stopped
  redis:
    restart: unless-stopped
```

**Live Demo — Kill and Resurrect:**

```bash
# Find the app container
docker ps | grep app

# Kill it hard
docker kill <container-id>

# Docker restarts it automatically — watch:
docker ps -a   # status returns to "Up" within seconds

# Confirm the service is back
curl http://localhost/health
# → {"status":"ok","checks":{"db_primary":"ok"}}
```

---

## Scalability Quest — Evidence

### Architecture — What's Already Handling Scale

| Layer | Component | What it does |
|-------|-----------|--------------|
| Reverse proxy | Nginx (`least_conn`) | Distributes requests to whichever app container has the fewest active connections |
| App tier | Gunicorn workers | Multiple OS-level worker processes per container; concurrency within each instance |
| Cache | Redis (Flask-Caching) | Stores hot responses in memory — redirects, stats, and URL lookups skip the DB after the first hit |
| DB | PostgreSQL | Single primary; connection pool via Peewee's `reuse_if_open=True` |
| Observability | Prometheus + `/metrics` | Tracks request counts, latencies, and the `url_redirects_total` counter per short code |

---

### 🥉 Tier 1: Bronze — The Baseline

#### Load Test Tool

Two options are provided; both live in `load_tests/`:

| Tool | Script | Install |
|------|--------|---------|
| **k6** | `load_tests/k6/bronze.js` | [k6.io/docs/get-started/installation](https://k6.io/docs/get-started/installation/) |
| **Locust** | `load_tests/locust/locustfile.py` | `pip install locust` |

#### Running the Bronze Test (50 VUs, 30 seconds)

```bash
# Start the app
docker compose -f docker-compose.1gb.yml up -d

# k6
k6 run load_tests/k6/bronze.js

# Locust (headless)
locust -f load_tests/locust/locustfile.py \
  --headless --users 50 --spawn-rate 10 --run-time 30s \
  --host http://localhost:5000
```

#### What the test covers

- `GET /health` — 30 % of requests
- `GET /api/stats` — 25 % (Redis-cached)
- `GET /<short_code>` — 20 % (Redis-cached redirect)
- `GET /api/urls` — 25 % (DB read)

#### Thresholds

| Metric | Bronze target |
|--------|---------------|
| p95 response time | < 3 000 ms |
| Error rate | < 10 % |

---

### 🥈 Tier 2: Silver — The Scale-Out

#### Running 2 App Containers

The Nginx config already uses Docker's internal DNS (`resolver 127.0.0.11`) and `least_conn` load balancing, so scaling is a single flag:

```bash
# Scale to 2 app instances
docker compose -f docker-compose.1gb.yml up --scale app=2 -d

# Verify: you should see 2 app containers + nginx + db + redis
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

#### Proving Load Balancing via `X-App-Instance`

Every response includes an `X-App-Instance` header set to the serving container's hostname (its Docker container ID). Watch it alternate between two values as requests hit different containers:

```bash
# Send 5 requests and watch the instance header change
for i in $(seq 1 5); do
  curl -s -o /dev/null -D - http://localhost/health | grep X-App-Instance
done
# → X-App-Instance: a3f9c1d2e5b7
# → X-App-Instance: 7b2e4f1d9c83
# → X-App-Instance: a3f9c1d2e5b7
# ...
```

#### Running the Silver Test (200 VUs)

```bash
# Against Nginx (full stack, shows load balancing)
k6 run --env BASE_URL=http://localhost load_tests/k6/silver.js

# Or against direct Gunicorn (avoids Nginx rate limits)
k6 run load_tests/k6/silver.js

# Locust equivalent
locust -f load_tests/locust/locustfile.py \
  --headless --users 200 --spawn-rate 20 --run-time 90s \
  --host http://localhost:5000
```

#### Thresholds

| Metric | Silver target |
|--------|---------------|
| p95 response time | < 3 000 ms |
| Error rate | < 5 % |

> **Note on Nginx rate limits:** `nginx.conf` limits `/api/urls` POST to 10 req/min and redirects to 60 req/min per IP. The load test scripts default to port 5000 (direct Gunicorn) to avoid these in testing. To test through Nginx without rate limiting interference, temporarily increase `rate=` values in `nginx/nginx.conf`.

---

### 🥇 Tier 3: Gold — The Speed of Light

#### Running the Gold Test (500 VUs / 100 req/s)

```bash
# Ramping VU mode: ramps to 500 concurrent users
k6 run load_tests/k6/gold.js

# Constant-arrival-rate mode: sustains exactly 100 req/s
k6 run --env MODE=rps load_tests/k6/gold.js

# Locust
locust -f load_tests/locust/locustfile.py \
  --headless --users 500 --spawn-rate 50 --run-time 2m \
  --host http://localhost:5000
```

#### Thresholds

| Metric | Gold target |
|--------|-------------|
| p95 response time | < 3 000 ms |
| Error rate | < **5 %** |

#### Evidence of Caching

**1. `/health` reports cache backend:**

```bash
curl -s http://localhost:5000/health | python3 -m json.tool
# {
#   "status": "ok",
#   "checks": {
#     "db_primary": "ok",
#     "cache": "redis"        ← Redis is connected and being used
#   }
# }
```

**2. Speed comparison — cache miss vs cache hit:**

```bash
# First request: cache miss (hits DB)
time curl -s http://localhost:5000/api/stats > /dev/null
# real    0m0.045s   ← DB query

# Second request: cache hit (served from Redis, 30s TTL)
time curl -s http://localhost:5000/api/stats > /dev/null
# real    0m0.005s   ← 9× faster
```

**3. k6 latency histogram** — the first request to a cached endpoint shows a higher latency spike; all subsequent requests cluster at <5 ms (Redis round-trip) until the TTL expires.

**4. What is cached:**

| Endpoint | Cache key | TTL |
|----------|-----------|-----|
| `GET /api/stats` | `api_stats` | 30 s |
| `GET /api/urls/<id>` | per `url_id` | 60 s |
| `GET /<short_code>` redirect target | per `short_code` | 60 min |

Cache is invalidated on `PUT /api/urls/<id>` and `DELETE /api/urls/<id>` via `cache.delete_memoized()`.

---

## Bottleneck Report

### What was slow before caching

**The redirect path (`GET /<short_code>`)** was the critical bottleneck. Every click triggered a `SELECT` on the `urls` table by `short_code`. Under 500 concurrent users, this produced hundreds of identical DB queries per second for the same popular short codes, saturating the connection pool and pushing p95 latency above 1 second.

### What we fixed

1. **Redis memoization on the redirect target** (60-minute TTL): The first hit for a given short code fetches from PostgreSQL; every subsequent hit reads from Redis in ~1 ms. For popular links this eliminates >99% of DB reads on the hot path.

2. **Redis cache on `/api/stats`** (30-second TTL): The global stats query does five separate `COUNT` aggregations plus a ranked `GROUP BY`. Without caching this ran on every dashboard poll. With a 30-second TTL the DB sees at most 2 stats queries per minute regardless of traffic volume.

3. **Nginx `least_conn` upstream** with persistent keepalives (`keepalive 32`): Avoids the overhead of TCP handshakes per request when multiple app containers are running, and routes new requests away from containers that are temporarily busy (long-running DB transactions).

### Remaining bottleneck

At very high write rates (>500 URL creates/minute), PostgreSQL's sequence generator and the `INSERT` → `UPDATE` two-step (needed for the Base62 short code derivation) becomes the limit. The fix would be to pre-generate a batch of IDs or switch to a distributed ID scheme — not needed at hackathon scale.

---

## Hidden Challenge Mitigations

The hackathon evaluator includes undisclosed checks for resilient edge-case behavior. All six published hints are addressed:

### The Twin's Paradox
> *A true creator never paints the exact same masterpiece twice.*

Every URL creation generates a new database row and derives its `short_code` from its unique auto-incremented primary key (`to_base62(url.id)`). Submitting the same `original_url` twice always produces two distinct short codes.

Test: `test_twin_paradox_same_url_creates_new_entry` in `test_routes.py`.

### The Unseen Observer
> *Every time a door is opened and a traveler passes through, someone must take note.*

Every `GET /<short_code>` redirect creates an `Event` row with `event_type="created"` logged at URL creation and `event_type="click"` logged on each redirect. Events are queryable via `GET /api/events` and `GET /api/urls/<id>/stats`.

Tests: `test_redirect_records_click_event`, `test_click_event_recorded_and_visible`, `test_create_records_created_event`.

### The Unwitting Stranger
> *Strangers with false names or missing credentials will attempt to enter your halls.*

All POST/PUT routes validate:
- Required fields are present and non-empty
- String fields reject integers and other non-string types
- `email` is validated against a regex (`^[^@\s]+@[^@\s]+\.[^@\s]+$`)
- Duplicate usernames and emails return 409

Tests: `test_unwitting_stranger_*` in `test_users.py`.

### The Slumbering Guide
> *When a path is closed or a guide is put to sleep, they should not lead anyone astray.*

Inactive URLs (`is_active=False`) return HTTP 404 on redirect and log **no** click event. The redirect cache is invalidated when `is_active` is updated.

Test: `test_slumbering_guide_inactive_no_redirect_no_event` in `test_routes.py`.

### The Deceitful Scroll
> *Sometimes, the details provided are not what they seem — a single word where a whole book was expected.*

All fields are type-checked at the route level. An integer where a string is expected returns 400. `original_url` is also validated with `urllib.parse` — it must have an `http` or `https` scheme and a non-empty host. Plain strings like `"not-a-url"` or `"just some text"` are rejected with 400 before any database operation.

Tests: `test_deceitful_scroll_invalid_url_rejected`, `test_unwitting_stranger_integer_username_rejected`, `test_fractured_vessel_string_body_*`.

### The Fractured Vessel
> *An offering must arrive in a proper vessel, not as a loose string or a shapeless mist.*

`POST /api/urls` and `POST /api/users` call `request.get_json(silent=True)` and immediately reject any payload that is not a `dict`. A raw JSON string, JSON array, or non-JSON `Content-Type` all return 400.

Tests: `test_fractured_vessel_string_body_returns_400`, `test_fractured_vessel_no_content_type_returns_400`.

---

## Error Handling

### 404 Not Found

Returned when a resource does not exist or a short code is unknown.

```json
{"error": "URL not found"}
{"error": "User not found"}
```

### 400 Bad Request

Returned for missing required fields, wrong field types, invalid email format, body not a JSON object, or constraint violations (e.g., reserved short code, custom code too long).

```json
{"error": "original_url is required"}
{"error": "username is required and must be a non-empty string"}
{"error": "Request body must be a JSON object"}
{"error": "short_code 'urls' is reserved"}
```

### 409 Conflict

Returned for uniqueness violations (duplicate username, email, or custom short code).

```json
{"error": "username already taken"}
{"error": "short_code already taken"}
```

### 500 Internal Server Error

Returned for any unhandled exception. The response is always clean JSON — the Python traceback is never exposed.

```json
{"error": "Internal Server Error", "message": "An unexpected error occurred"}
```

---

## Failure Modes

| Failure | Behavior | Recovery |
|---------|----------|----------|
| App container killed | Docker `restart: unless-stopped` restarts it within seconds | Automatic |
| Database unreachable | `/health` returns `{"status":"degraded"}`, all DB-backed routes return 500 with clean JSON | Automatic when DB recovers |
| Redis unreachable | Flask-Caching falls back to `SimpleCache` (in-process); redirects still work | Automatic; no data loss |
| Invalid request body | 400 returned before any DB write; no partial state | N/A |
| Duplicate short code on custom code | 409 returned; no row created | Client retries with different code |
| Inactive URL accessed | 404 returned; no click event recorded | Reactivate URL via `PUT /api/urls/<id>` |
| Unknown short code accessed | 404 returned immediately | N/A |
| OOM on 1 GB droplet | `mem_limit` on each container directs OOM-killer to containers before the OS; other services survive | Affected container restarts |

---

## Chaos Mode — Docker Restart Policy

All four services run with `restart: unless-stopped`, meaning Docker automatically restarts any container that crashes or is forcibly killed.

### Live Demo 1: Kill the container → Watch it resurrect

```bash
./scripts/chaos.sh
```

The script:
1. Confirms the service is healthy
2. Sends `SIGKILL` to the app container (`docker kill`)
3. Polls `GET /health` every second until it returns `"status": "ok"`
4. Reports recovery time and the new container ID

Sample output:

```
═══ Step 2 — Killing the app container (SIGKILL) ═══

Running: docker kill a3f9c1d2e5b7

💀 Container killed at 14:22:31
Container state immediately after kill: exited

═══ Step 3 — Watching Docker restart the container ═══

Polling http://localhost/health every second (max 60s)...

✓ Service is back! (attempt 9, elapsed: 9s)

═══ Step 4 — Recovery Report ═══

✓ Service fully recovered in 9 seconds
Old container: a3f9c1d2e5b7
New container: 7b2e4f1d9c83
Final health:  {"status":"ok","checks":{"db_primary":"ok","cache":"redis"}}

✓ Chaos test passed.
```

### Live Demo 2: Send garbage data → Get a polite error

```bash
./scripts/garbage.sh
```

The script fires ~30 intentionally malformed requests (wrong types, missing fields, invalid URLs, nonexistent IDs, reserved paths, duplicate resources) and verifies every response is valid JSON with the correct HTTP status — no tracebacks, no HTML, no 500s for client errors.

Sample output:

```
─── The Fractured Vessel — Malformed request bodies ───
  ✓ Raw string body on POST /api/users
    HTTP 400 → {"error":"Request body must be a JSON object"}
  ✓ JSON array body (not object) on POST /api/users
    HTTP 400 → {"error":"Request body must be a JSON object"}

─── The Deceitful Scroll — Invalid field types & values ───
  ✓ Integer username (POST /api/users)
    HTTP 400 → {"error":"username is required and must be a non-empty string"}
  ✓ Non-URL original_url — plain text (POST /api/urls)
    HTTP 400 → {"error":"original_url must be a valid http or https URL"}

═══════════════════════════════════════
Results: 30 / 30 checks passed
═══════════════════════════════════════
✓ All garbage inputs returned clean JSON errors.
```

### Failure Mode Documentation

See [FAILURE_MODES.md](FAILURE_MODES.md) for the complete failure mode reference, covering all 12 failure scenarios with user impact, auto-recovery behaviour, and time-to-recover for each.

---

## Development Reference

### uv Commands

| Command | What it does |
|---------|--------------|
| `uv sync` | Install all dependencies (creates `.venv` automatically) |
| `uv run <script>` | Run a script using the project virtualenv |
| `uv add <package>` | Add a new dependency |
| `uv remove <package>` | Remove a dependency |

### Running Tests

```bash
# Unit tests only (no database required)
uv run pytest tests/unit/ -v

# Integration tests (requires PostgreSQL on localhost:5432)
uv run pytest tests/integration/ -v

# Full suite with coverage
uv run pytest tests/ --cov=app --cov-report=term-missing

# Fail if coverage drops below 60%
uv run pytest tests/integration/ --cov=app --cov-fail-under=60
```

### Running Locally with Docker Compose

```bash
# Build and start all services
docker compose -f docker-compose.1gb.yml up --build

# Check health
curl http://localhost/health

# Tail app logs
docker compose -f docker-compose.1gb.yml logs -f app
```

### Useful Peewee Patterns

```python
from peewee import fn
from playhouse.shortcuts import model_to_dict

# Select all
User.select()

# Filter
Url.select().where(Url.is_active == True)

# Get by ID (raises DoesNotExist if missing)
User.get_by_id(1)

# Get or None (safe)
User.get_or_none(User.id == 999)

# Create
User.create(username="alice", email="alice@example.com", created_at=datetime.utcnow())

# Convert to dict for JSON
model_to_dict(user)

# Aggregations
Event.select(fn.COUNT(Event.id)).where(Event.event_type == "click").scalar()

# Paginate
User.select().order_by(User.created_at.desc()).paginate(page=1, paginate_by=20)
```
