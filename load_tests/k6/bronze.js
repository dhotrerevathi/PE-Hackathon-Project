/**
 * Bronze Tier — Baseline Load Test
 * 50 concurrent virtual users for 30 seconds.
 * Measures p95 latency and error rate.
 *
 * Usage:
 *   k6 run load_tests/k6/bronze.js
 *   k6 run --env BASE_URL=http://localhost load_tests/k6/bronze.js
 *
 * Note: defaults to port 5000 (direct Gunicorn) to bypass Nginx rate limits.
 * Use BASE_URL=http://localhost to test the full Nginx → app stack.
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:5000';

export const options = {
  vus: 50,
  duration: '30s',

  thresholds: {
    // 95th percentile response time must be under 3 seconds
    http_req_duration: ['p(95)<3000'],
    // Error rate must stay below 10% (Bronze tolerance)
    http_req_failed: ['rate<0.10'],
  },
};

// ── Setup: create one shared user and URL for redirect tests ─────────────────
export function setup() {
  const ts = Date.now();
  const headers = { 'Content-Type': 'application/json' };

  const userRes = http.post(
    `${BASE_URL}/api/users`,
    JSON.stringify({ username: `k6_bronze_${ts}`, email: `k6_bronze_${ts}@example.com` }),
    { headers }
  );

  if (userRes.status !== 201) {
    console.warn(`Setup: user creation returned ${userRes.status} — redirect tests will be skipped`);
    return { shortCode: null };
  }

  const userId = userRes.json('id');
  const urlRes = http.post(
    `${BASE_URL}/api/urls`,
    JSON.stringify({ original_url: 'https://example.com/k6-bronze-target', user_id: userId }),
    { headers }
  );

  const shortCode = urlRes.status === 201 ? urlRes.json('short_code') : null;
  if (!shortCode) {
    console.warn(`Setup: URL creation returned ${urlRes.status}`);
  }
  return { shortCode };
}

// ── Default scenario ──────────────────────────────────────────────────────────
export default function (data) {
  const rand = Math.random();

  if (rand < 0.30) {
    // 30% — health check (no DB, just app process)
    const r = http.get(`${BASE_URL}/health`);
    check(r, { 'health → 200': (res) => res.status === 200 });

  } else if (rand < 0.55) {
    // 25% — global stats (Redis-cached after first request)
    const r = http.get(`${BASE_URL}/api/stats`);
    check(r, { 'stats → 200': (res) => res.status === 200 });

  } else if (rand < 0.75 && data.shortCode) {
    // 20% — short-code redirect (Redis-cached hot path)
    const r = http.get(`${BASE_URL}/${data.shortCode}`, { redirects: 0 });
    check(r, { 'redirect → 302': (res) => res.status === 302 });

  } else {
    // 25% — list URLs (paginated DB read)
    const r = http.get(`${BASE_URL}/api/urls?per_page=10`);
    check(r, { 'list URLs → 200': (res) => res.status === 200 });
  }

  // 100ms think time — simulates a real user pacing
  sleep(0.1);
}
