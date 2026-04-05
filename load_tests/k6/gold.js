/**
 * Gold Tier — Tsunami Load Test
 * Ramps to 500 concurrent virtual users.
 * Error rate must stay under 5%.
 *
 * Usage (single instance):
 *   k6 run load_tests/k6/gold.js
 *
 * Usage (scaled fleet + Nginx):
 *   docker compose -f docker-compose.1gb.yml up --scale app=2 -d
 *   k6 run --env BASE_URL=http://localhost load_tests/k6/gold.js
 *
 * Alternative constant-arrival-rate mode (100 req/s):
 *   k6 run --env MODE=rps load_tests/k6/gold.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:5000';
const MODE = __ENV.MODE || 'vus';  // 'vus' or 'rps'

// Build options dynamically based on mode
export const options = MODE === 'rps'
  ? {
      // Constant arrival rate: 100 req/s, up to 500 VUs to sustain it
      scenarios: {
        tsunami: {
          executor: 'constant-arrival-rate',
          rate: 100,
          timeUnit: '1s',
          duration: '60s',
          preAllocatedVUs: 200,
          maxVUs: 500,
        },
      },
      thresholds: {
        http_req_duration: ['p(95)<3000'],
        http_req_failed: ['rate<0.05'],
      },
    }
  : {
      // Ramping VU mode: stress test to 500 concurrent users
      stages: [
        { duration: '20s', target: 100 },  // warm up
        { duration: '20s', target: 300 },  // ramp
        { duration: '20s', target: 500 },  // tsunami
        { duration: '60s', target: 500 },  // hold — this is the stress window
        { duration: '20s', target: 0   },  // cool down
      ],
      thresholds: {
        // Gold requirement: p95 under 3 seconds
        http_req_duration: ['p(95)<3000'],
        // Gold requirement: error rate under 5%
        http_req_failed: ['rate<0.05'],
      },
    };

export function setup() {
  const ts = Date.now();
  const headers = { 'Content-Type': 'application/json' };

  const userRes = http.post(
    `${BASE_URL}/api/users`,
    JSON.stringify({ username: `k6_gold_${ts}`, email: `k6_gold_${ts}@example.com` }),
    { headers }
  );

  if (userRes.status !== 201) {
    console.warn(`Setup: user creation returned ${userRes.status}`);
    return { shortCodes: [] };
  }

  const userId = userRes.json('id');

  // Create multiple URLs so redirects spread across different cached entries
  const shortCodes = [];
  for (let i = 0; i < 5; i++) {
    const urlRes = http.post(
      `${BASE_URL}/api/urls`,
      JSON.stringify({
        original_url: `https://example.com/k6-gold-target-${i}`,
        title: `Gold Test URL ${i}`,
        user_id: userId,
      }),
      { headers }
    );
    if (urlRes.status === 201) {
      shortCodes.push(urlRes.json('short_code'));
    }
  }

  console.log(`Setup: created ${shortCodes.length} test URLs`);
  return { shortCodes, userId };
}

export default function (data) {
  const rand = Math.random();
  let res;

  if (rand < 0.20) {
    // 20% — health (very fast, no DB hit)
    res = http.get(`${BASE_URL}/health`);
    check(res, { 'health → 200': (r) => r.status === 200 });

  } else if (rand < 0.45) {
    // 25% — stats (Redis-cached, 30s TTL — the fastest API call under load)
    res = http.get(`${BASE_URL}/api/stats`);
    check(res, {
      'stats → 200': (r) => r.status === 200,
      'stats has total_urls': (r) => r.json('total_urls') !== undefined,
    });

  } else if (rand < 0.70 && data.shortCodes && data.shortCodes.length > 0) {
    // 25% — redirect (Redis-cached, hottest path in production)
    const code = data.shortCodes[Math.floor(Math.random() * data.shortCodes.length)];
    res = http.get(`${BASE_URL}/${code}`, { redirects: 0 });
    check(res, { 'redirect → 302': (r) => r.status === 302 });

  } else if (rand < 0.85) {
    // 15% — list URLs with pagination
    const page = Math.floor(Math.random() * 3) + 1;
    res = http.get(`${BASE_URL}/api/urls?page=${page}&per_page=10`);
    check(res, { 'list URLs → 200': (r) => r.status === 200 });

  } else {
    // 15% — events list (paginated)
    res = http.get(`${BASE_URL}/api/events?per_page=10`);
    check(res, { 'events → 200': (r) => r.status === 200 });
  }

  // Minimal think time to maximize throughput
  sleep(0.05);
}
