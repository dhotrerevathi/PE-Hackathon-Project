# MLH PE Hackathon — URL Shortener (Flask · Peewee · PostgreSQL)

A production-grade URL shortener built for the MLH PE Hackathon 2026 Reliability Engineering quest.

**Stack:** Flask · Peewee ORM · PostgreSQL · Redis · Gunicorn · Nginx · Docker

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Project Structure](#project-structure)
3. [API Reference](#api-reference)
4. [Reliability Quest — Evidence](#reliability-quest--evidence)
   - [Bronze: The Shield](#-tier-1-bronze--the-shield)
   - [Silver: The Fortress](#-tier-2-silver--the-fortress)
   - [Gold: The Immortal](#-tier-3-gold--the-immortal)
5. [Hidden Challenge Mitigations](#hidden-challenge-mitigations)
6. [Error Handling](#error-handling)
7. [Failure Modes](#failure-modes)
8. [Chaos Mode — Docker Restart Policy](#chaos-mode--docker-restart-policy)
9. [Development Reference](#development-reference)

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

```bash
# Kill the app container to simulate a crash
docker kill $(docker ps -qf name=app)

# Watch Docker bring it back (takes ~5-10 seconds)
watch -n1 'docker ps -a --filter name=app --format "table {{.Names}}\t{{.Status}}"'

# Confirm recovery
curl http://localhost/health
```

The Nginx container continues serving incoming requests while the app restarts. Once the app container is healthy, Nginx routes traffic to it again automatically.

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
