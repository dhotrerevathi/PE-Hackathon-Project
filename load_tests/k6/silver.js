/**
 * Silver Tier — Scale-Out Load Test
 * Ramps to 200 concurrent virtual users.
 * Tests horizontal scaling: run with 2+ app containers behind Nginx.
 *
 * Usage (single instance, direct):
 *   k6 run load_tests/k6/silver.js
 *
 * Usage (2 app containers, through Nginx):
 *   docker compose -f docker-compose.1gb.yml up --scale app=2 -d
 *   k6 run --env BASE_URL=http://localhost load_tests/k6/silver.js
 *
 * Evidence of load balancing: watch the X-App-Instance response header change
 * between requests — each value is a different container ID.
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:5000';

// Track how many distinct app instances handle requests
const instancesSeen = new Counter('distinct_app_instances');
const seenInstances = new Set();

export const options = {
  stages: [
    { duration: '20s', target: 50  },  // warm up
    { duration: '30s', target: 200 },  // ramp to 200 VUs
    { duration: '60s', target: 200 },  // hold at 200 VUs
    { duration: '10s', target: 0   },  // ramp down
  ],

  thresholds: {
    // Silver requirement: p95 under 3 seconds
    http_req_duration: ['p(95)<3000'],
    // Silver tolerance: <5% errors
    http_req_failed: ['rate<0.05'],
  },
};

export function setup() {
  const ts = Date.now();
  const headers = { 'Content-Type': 'application/json' };

  const userRes = http.post(
    `${BASE_URL}/api/users`,
    JSON.stringify({ username: `k6_silver_${ts}`, email: `k6_silver_${ts}@example.com` }),
    { headers }
  );

  if (userRes.status !== 201) {
    console.warn(`Setup: user creation returned ${userRes.status}`);
    return { shortCode: null };
  }

  const userId = userRes.json('id');
  const urlRes = http.post(
    `${BASE_URL}/api/urls`,
    JSON.stringify({ original_url: 'https://example.com/k6-silver-target', user_id: userId }),
    { headers }
  );

  return { shortCode: urlRes.status === 201 ? urlRes.json('short_code') : null };
}

export default function (data) {
  const rand = Math.random();
  let res;

  if (rand < 0.25) {
    res = http.get(`${BASE_URL}/health`);
    check(res, { 'health → 200': (r) => r.status === 200 });

  } else if (rand < 0.50) {
    res = http.get(`${BASE_URL}/api/stats`);
    check(res, { 'stats → 200': (r) => r.status === 200 });

  } else if (rand < 0.70 && data.shortCode) {
    res = http.get(`${BASE_URL}/${data.shortCode}`, { redirects: 0 });
    check(res, { 'redirect → 302': (r) => r.status === 302 });

  } else if (rand < 0.85) {
    res = http.get(`${BASE_URL}/api/urls?per_page=10`);
    check(res, { 'list URLs → 200': (r) => r.status === 200 });

  } else {
    res = http.get(`${BASE_URL}/api/users?per_page=10`);
    check(res, { 'list users → 200': (r) => r.status === 200 });
  }

  // Record which app instance served this request (proves load balancing)
  if (res) {
    const instance = res.headers['X-App-Instance'];
    if (instance && !seenInstances.has(instance)) {
      seenInstances.add(instance);
      instancesSeen.add(1);
    }
  }

  sleep(0.1);
}
