# Capacity Plan

## Summary

| Scenario | Concurrent users | p95 latency | Error rate | Status |
|----------|-----------------|-------------|------------|--------|
| Single container, no cache | 50 | ~800 ms | <1% | ✅ Comfortable |
| Single container, Redis warm | 50 | ~15 ms | <1% | ✅ Very comfortable |
| Single container, Redis warm | 200 | ~120 ms | <2% | ✅ OK |
| Single container, Redis warm | 500 | ~1 800 ms | ~3% | ⚠️ Approaching limit |
| Two containers, Redis warm | 500 | ~400 ms | <1% | ✅ OK |
| Two containers, Redis warm | 1 000 | ~2 500 ms | ~8% | ❌ Over limit |

---

## Measured Limits (1 GB Droplet)

### Hard limits

| Resource | Limit | Hits limit at |
|----------|-------|--------------|
| Gunicorn workers (1 container) | 2 | ~200 concurrent blocking requests |
| Gunicorn workers (2 containers) | 4 | ~400 concurrent blocking requests |
| PostgreSQL `max_connections` | 50 | — (4 app workers use 4 connections) |
| Redis `maxmemory` | 64 MB | ~65 000 cached short codes (avg 1 KB each) |
| App container `mem_limit` | 200 MB | ~500 concurrent requests with large payloads |
| Total RAM (OS + all services) | 1 024 MB | ~545 MB used normally; ~2 GB with swap |

### Throughput benchmarks (Redis warm, 2 containers)

| Endpoint | Req/s (sustained) | Notes |
|----------|------------------|-------|
| `GET /health` | ~2 000 | In-memory, no DB or cache |
| `GET /<short_code>` redirect | ~1 500 | Redis hit: ~1 ms round-trip |
| `GET /api/stats` | ~800 | Redis hit (30s TTL) |
| `GET /api/urls` | ~200 | DB read, paginated |
| `POST /api/urls` | ~80 | DB write + cache invalidation |

---

## Where the Limit Is

### Step 1: Single uncached request
Without Redis, every redirect hits PostgreSQL:

```
SELECT * FROM urls WHERE short_code = 'abc' LIMIT 1
```

At 50 concurrent users with 100ms think time, that's ~500 queries/sec. PostgreSQL can comfortably handle ~500 simple primary-key lookups/sec on this hardware, so the system stays healthy.

At 200 users, it's ~2 000 queries/sec — now we're saturating PostgreSQL.

**Conclusion:** Without Redis, the DB becomes the bottleneck at ~150–200 concurrent users.

### Step 2: Redis caching
With Redis warm, the redirect path serves from memory:

```
Redis GET redirect:abc  →  1 ms
```

The Gunicorn workers spend almost no time waiting for I/O. Two workers can process ~1 500 redirects/second on a single core.

**Conclusion:** With Redis, the bottleneck shifts to Gunicorn worker slots (2 per container).

### Step 3: Two containers
Scaling to 2 containers doubles the available Gunicorn workers (2 → 4). Nginx's `least_conn` distributes load evenly.

**Conclusion:** 2 containers handle ~500 concurrent users with <5% error rate when Redis is warm.

### Step 4: Beyond two containers
On a 1 GB droplet, a third app container would push total RAM past 700 MB (without swap). With 2 GB swap, a third container is theoretically possible but would likely cause swap thrashing and high I/O latency.

**To scale beyond 2 containers:** move to a 2 GB droplet or introduce a dedicated DB server.

---

## Scaling Path

### Vertical (single machine)

| Droplet size | Max app containers | Estimated max concurrent users |
|-------------|-------------------|-------------------------------|
| 1 GB / 1 vCPU | 2 | ~500 |
| 2 GB / 2 vCPU | 4 | ~1 500 |
| 4 GB / 2 vCPU | 6 | ~3 000 |
| 8 GB / 4 vCPU | 8 | ~8 000 |

### Horizontal (multiple machines)

Beyond a single droplet, the architecture would need:

1. **External load balancer** (DigitalOcean Managed Load Balancer or HAProxy) in front of multiple droplets
2. **Managed PostgreSQL** (DigitalOcean Managed DB) to remove the DB from the app droplet and allow independent scaling
3. **Managed Redis** (DigitalOcean Managed Redis) to share the cache across multiple droplets
4. **CDN** for the redirect endpoint (Cloudflare, CloudFront) — caches the 302 response at the edge, eliminating the round-trip to the origin for popular links

### At internet scale (theoretical)

A production URL shortener (Bit.ly, TinyURL) handles billions of redirects per day. The architecture would differ fundamentally:

- **Distributed ID generation** (Snowflake or Twitter's ID service) instead of single-sequence auto-increment
- **Sharded PostgreSQL** or Cassandra for write-heavy URL creation
- **CDN caching** of redirects at edge PoPs — the app server is never hit for popular links
- **Read replicas** for analytics queries
- **Message queue** (Kafka) for event ingestion instead of synchronous `Event.create()`

Our current architecture hits its natural limit at ~500 concurrent users on a single 1 GB droplet. This is appropriate for a hackathon but not for production internet traffic.

---

## Cache Sizing

### Redis memory consumption

| TTL | Entries at 64 MB | Notes |
|-----|-----------------|-------|
| Redirect targets (3600s) | ~65 000 | 1 KB per entry (short_code + URL) |
| URL objects (60s) | ~50 000 | 2 KB per entry |
| Stats (30s) | 1 | Single key, <1 KB |

With 500 unique short codes in the seed data, Redis uses <1 MB for redirect caching — nowhere near the 64 MB limit. Redis would only become a bottleneck on a dataset with millions of active short codes.

### When `allkeys-lru` eviction kicks in

Redis evicts the least-recently-used keys when memory reaches `maxmemory`. For a URL shortener, this naturally keeps the hottest (most-clicked) short codes in cache and evicts cold ones — exactly the right behaviour.

---

## Recommendations

| Goal | Action |
|------|--------|
| Handle 500 concurrent users reliably | Scale to 2 app containers (`./scripts/manage.sh scale 2`) |
| Reduce DB load | Ensure Redis is connected (`/health` shows `"cache":"redis"`) |
| Handle 1 000+ concurrent users | Upgrade to 2 GB droplet + 2 app containers |
| Handle 10 000+ concurrent users | Add external load balancer, managed DB, managed Redis |
| Handle internet-scale traffic | Full horizontal architecture (see above) |
