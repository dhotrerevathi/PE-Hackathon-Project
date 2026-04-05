# Decision Log

This document records the technical choices made during the hackathon and the reasoning behind each one. The goal is to make trade-offs explicit and help future contributors understand _why_ the system is built the way it is.

---

## DEC-01: Flask over FastAPI or Django

**Decision:** Use Flask as the web framework.

**Alternatives considered:**
- FastAPI — async, built-in OpenAPI docs, Pydantic validation
- Django — batteries-included, admin panel, mature ORM

**Reasoning:**

Flask was chosen for three reasons:

1. **Simplicity at hackathon scale.** The app has ~10 endpoints and no complex business logic. Flask's minimal surface area means less framework boilerplate and faster iteration.

2. **Compatibility with Peewee.** Peewee is a synchronous ORM. Mixing it with FastAPI's async request handling requires care (running sync code in a thread pool). Flask is synchronous throughout, making the integration straightforward.

3. **Team familiarity.** The team had existing Flask experience. Using an unfamiliar framework under time pressure adds risk.

**Trade-offs accepted:**
- No automatic request/response schema validation (handled manually in routes)
- No built-in async support (not needed at this scale)
- No auto-generated OpenAPI docs (documented manually in `README.md`)

---

## DEC-02: Peewee over SQLAlchemy

**Decision:** Use Peewee as the ORM.

**Alternatives considered:**
- SQLAlchemy (Core or ORM)
- Raw `psycopg2` with hand-written SQL

**Reasoning:**

1. **Lower cognitive overhead.** Peewee's API is smaller and more direct than SQLAlchemy's. `Model.create()`, `Model.select().where()`, `Model.get_or_none()` are self-explanatory.

2. **Explicit connection management.** Peewee's `DatabaseProxy` and `reuse_if_open=True` make it straightforward to manage one connection per Gunicorn worker without a connection pool library.

3. **Sufficient for the data model.** The schema is simple (3 tables, straightforward joins). SQLAlchemy's power is wasted here.

**Trade-offs accepted:**
- Peewee has less community tooling for migrations (no Alembic equivalent). Schema changes require manual SQL.
- `model_to_dict` from `playhouse.shortcuts` can be slow on deeply nested models with backrefs. Mitigated by writing custom `_to_dict()` functions for each model.

---

## DEC-03: PostgreSQL over SQLite or MySQL

**Decision:** Use PostgreSQL as the primary database.

**Alternatives considered:**
- SQLite — zero-config, file-based
- MySQL / MariaDB

**Reasoning:**

1. **Correctness under concurrency.** PostgreSQL's MVCC (multi-version concurrency control) handles simultaneous reads and writes correctly without explicit locking. SQLite has write contention issues under concurrent load.

2. **Sequence reset after CSV seeding.** The seeding logic imports rows with explicit IDs, then resets the sequence with `SELECT setval(...)`. This is a PostgreSQL-specific operation. It ensures new rows get IDs higher than the seeded ones.

3. **Production standard.** PostgreSQL is the de facto standard for relational workloads. Using SQLite in production would be a risk for data integrity.

**Trade-offs accepted:**
- Requires a running PostgreSQL instance for local development (Docker handles this)
- More complex initial setup than SQLite

---

## DEC-04: Redis for Caching

**Decision:** Use Redis as the cache backend via Flask-Caching.

**Alternatives considered:**
- No cache (every request hits PostgreSQL)
- Memcached
- In-process `SimpleCache`

**Reasoning:**

1. **Shared across Gunicorn workers.** In-process caching (`SimpleCache`) is local to each worker process. With 2 workers (or 2 containers), each worker builds its own cache independently, doubling DB load. Redis is shared — one cache miss populates it for all workers.

2. **Persistence across app restarts.** Redis with AOF (`appendonly yes`) survives app container restarts. The cache is warm immediately after restart.

3. **The redirect path is the hottest.** A URL shortener's core value is fast redirects. Caching `_get_redirect_target(short_code)` for 60 minutes eliminates >99% of DB reads on popular links.

4. **Graceful degradation.** `cache.py` probes Redis at startup. If unreachable, it falls back to `SimpleCache` automatically — the app keeps running, just without cross-worker cache sharing.

**Cache TTL decisions:**

| Endpoint | TTL | Reasoning |
|----------|-----|-----------|
| `/<short_code>` redirect target | 3600s (1h) | Hot path; original URLs rarely change |
| `GET /api/urls/<id>` | 60s | Balance freshness vs DB load |
| `GET /api/stats` | 30s | Aggregation query is expensive; slight staleness is acceptable |

---

## DEC-05: Nginx over Traefik or Caddy

**Decision:** Use Nginx as the reverse proxy and load balancer.

**Alternatives considered:**
- Traefik — dynamic service discovery, automatic TLS, Docker-native
- Caddy — automatic HTTPS, simple config syntax

**Reasoning:**

1. **Explicit control.** The Nginx config is explicit about every behaviour: rate limits, upstream selection (`least_conn`), retry policy, header forwarding. Traefik's dynamic config via labels is more implicit and harder to audit.

2. **Rate limiting is a requirement.** Nginx has battle-tested `limit_req_zone` support built-in. Traefik requires a plugin or middleware chain for equivalent functionality.

3. **Horizontal scaling via Docker DNS.** Nginx's `resolver 127.0.0.11` combined with a DNS-based upstream (`server app:5000`) means `--scale app=2` works without touching the Nginx config. Docker DNS automatically load-balances across all `app` containers.

4. **Team familiarity.** Nginx configuration syntax is widely documented and understood.

**Trade-offs accepted:**
- No automatic TLS (would need Certbot or Caddy). SSL termination handled at the load balancer (DigitalOcean) level in production.
- Nginx config requires a reload if the rate limit zones need to change.

---

## DEC-06: Docker Compose over Kubernetes

**Decision:** Use Docker Compose for container orchestration.

**Alternatives considered:**
- Kubernetes (k3s or managed K8s)
- Nomad

**Reasoning:**

1. **Single-node deployment.** A 1 GB DigitalOcean droplet is a single machine. Kubernetes is designed for multi-node clusters. Running k3s on a 1 GB node would consume ~300–400 MB of RAM just for control plane overhead, leaving insufficient room for the application.

2. **Operational simplicity.** Docker Compose's `up -d`, `--scale`, `logs`, `restart` cover all operational needs. Kubernetes adds significant complexity (YAML manifests, kubeconfig, namespaces, RBAC) that provides no benefit at this scale.

3. **Restart policy.** `restart: unless-stopped` in Compose provides the same auto-recovery behaviour as Kubernetes' default pod restart policy — without the overhead.

**Trade-offs accepted:**
- No automatic rolling deployments (Compose `up -d` has a brief restart gap). Mitigated by scaling to 2 before deploying.
- No horizontal pod autoscaling. Manual `--scale` required.
- If the single droplet fails, there is no automatic failover to another host.

---

## DEC-07: Base62 Short Code Derivation

**Decision:** Derive `short_code` from `to_base62(url.id)` rather than a random hash.

**Alternatives considered:**
- MD5/SHA hash of the original URL, truncated
- Random string (e.g., `secrets.token_urlsafe(6)`)
- Nanoid or UUID

**Reasoning:**

1. **Collision-free by design.** Auto-increment primary keys are unique by definition. `to_base62(id)` produces a unique code for every row without any collision check.

2. **The Twin's Paradox requirement.** Two identical URLs submitted twice must produce different short codes. A hash of the URL would produce the same code both times. A random string requires a uniqueness retry loop. Base62-from-ID is unique without retries.

3. **Monotonic growth.** Codes grow longer as the dataset grows (same as base conversion). A 6-character code handles up to 62⁶ ≈ 56 billion URLs.

4. **Simple and auditable.** `to_base62` is 8 lines of pure Python, fully unit-tested.

**Trade-offs accepted:**
- Sequential IDs make the short code slightly guessable (users can infer URL count and creation order). A random component or hash would prevent this. For a hackathon URL shortener, this is acceptable.
- The two-step `INSERT` (placeholder `__pending_<random>`) then `UPDATE` is slightly less efficient than a single `INSERT`. Wrapped in `db.atomic()` so it's a single transaction.

---

## DEC-08: Gunicorn as WSGI Server

**Decision:** Use Gunicorn to run Flask in production.

**Alternatives considered:**
- Flask's built-in development server (`flask run`)
- uWSGI
- Waitress

**Reasoning:**

1. **Flask's built-in server is single-threaded and not production-safe.** The documentation explicitly warns against using it in production.

2. **Gunicorn is the standard.** It's well-documented, widely deployed, and integrates cleanly with Flask via `app:create_app()`.

3. **Worker count tuned for the hardware.** `GUNICORN_WORKERS=2` on a 1 vCPU droplet follows the `2 × CPU + 1` rule. Each worker is an independent OS process that handles requests concurrently via preforking.

**Trade-offs accepted:**
- Gunicorn uses the `sync` worker by default (one request per worker at a time). For I/O-bound workloads (which ours is), `gevent` or `eventlet` workers would allow higher concurrency per worker. We chose `sync` workers to keep the configuration simple and avoid compatibility issues with Peewee's synchronous ORM.
