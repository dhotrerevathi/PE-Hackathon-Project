#!/usr/bin/env bash
# scripts/garbage.sh — Graceful Failure Demo
#
# Sends intentionally malformed, invalid, and boundary-breaking requests
# to every endpoint. Shows that the API always returns clean JSON errors —
# never Python stack traces, never HTML, never silence.
#
# Usage:
#   ./scripts/garbage.sh                           # defaults to http://localhost:5000
#   BASE_URL=http://localhost ./scripts/garbage.sh  # through Nginx

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

BASE_URL="${BASE_URL:-http://localhost:5000}"

PASS=0
FAIL=0

# ── Helpers ───────────────────────────────────────────────────────────────────
hdr() { printf "\n${BOLD}${CYAN}─── %s ───${RESET}\n" "$*"; }

# check <label> <expected_status> <method> <path> [curl_extra_args...]
check() {
  local label="$1"
  local expected_status="$2"
  local method="$3"
  local path="$4"
  shift 4

  local full_url="${BASE_URL}${path}"
  local response
  local http_code

  http_code=$(curl -s -o /tmp/garbage_body.json -w "%{http_code}" \
    -X "$method" "$full_url" "$@" --max-time 5 2>/dev/null)
  response=$(cat /tmp/garbage_body.json 2>/dev/null || echo "")

  # Validate: is the body valid JSON?
  local is_json=false
  if echo "$response" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
    is_json=true
  fi

  # Check status code matches expectation
  local status_ok=false
  if [ "$http_code" = "$expected_status" ]; then
    status_ok=true
  fi

  # Both must pass: right status AND valid JSON
  if [ "$status_ok" = "true" ] && [ "$is_json" = "true" ]; then
    printf "  ${GREEN}✓${RESET} ${BOLD}%s${RESET}\n" "$label"
    printf "    ${DIM}HTTP %s → %s${RESET}\n" "$http_code" "$response"
    PASS=$((PASS + 1))
  else
    printf "  ${RED}✗${RESET} ${BOLD}%s${RESET}\n" "$label"
    if [ "$status_ok" = "false" ]; then
      printf "    ${RED}Expected HTTP %s, got HTTP %s${RESET}\n" "$expected_status" "$http_code"
    fi
    if [ "$is_json" = "false" ]; then
      printf "    ${RED}Response is NOT valid JSON!${RESET}\n"
    fi
    printf "    ${DIM}Body: %s${RESET}\n" "$response"
    FAIL=$((FAIL + 1))
  fi
}

# ── Connectivity pre-check ────────────────────────────────────────────────────
printf "\n${BOLD}Graceful Failure Demo — Garbage In, Clean JSON Out${RESET}\n"
printf "${DIM}Target: %s${RESET}\n" "$BASE_URL"
echo ""

HEALTH=$(curl -s --max-time 5 "${BASE_URL}/health" 2>/dev/null || echo "")
if ! echo "$HEALTH" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
  printf "${RED}✗ Cannot reach %s — is the app running?${RESET}\n" "$BASE_URL"
  exit 1
fi
printf "${GREEN}✓ App is reachable${RESET}\n"

# Create a real user + URL to use as targets for update/delete tests
REAL_USER=$(curl -s -X POST "${BASE_URL}/api/users" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"garbage_demo_$(date +%s)\",\"email\":\"garbage_$(date +%s)@example.com\"}" \
  2>/dev/null)
REAL_USER_ID=$(echo "$REAL_USER" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || echo "1")

REAL_URL=$(curl -s -X POST "${BASE_URL}/api/urls" \
  -H "Content-Type: application/json" \
  -d "{\"original_url\":\"https://example.com/garbage-demo\",\"user_id\":${REAL_USER_ID}}" \
  2>/dev/null)
REAL_URL_ID=$(echo "$REAL_URL" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || echo "1")
REAL_SHORT_CODE=$(echo "$REAL_URL" | python3 -c "import sys,json; print(json.load(sys.stdin)['short_code'])" 2>/dev/null || echo "")

printf "${DIM}Created test user ID=%s, URL ID=%s${RESET}\n" "$REAL_USER_ID" "$REAL_URL_ID"

# ════════════════════════════════════════════════════════════════════════════ #
hdr "The Fractured Vessel — Malformed request bodies"

check "Raw string body on POST /api/users" "400" POST /api/users \
  -H "Content-Type: application/json" \
  -d '"just a string"'

check "Raw string body on POST /api/urls" "400" POST /api/urls \
  -H "Content-Type: application/json" \
  -d '"just a string"'

check "JSON array body (not object) on POST /api/users" "400" POST /api/users \
  -H "Content-Type: application/json" \
  -d '["username","email"]'

check "No Content-Type header on POST /api/urls" "400" POST /api/urls \
  -d "original_url=https://example.com"

check "Completely empty body on POST /api/users" "400" POST /api/users \
  -H "Content-Type: application/json" \
  -d ""

# ════════════════════════════════════════════════════════════════════════════ #
hdr "The Deceitful Scroll — Invalid field types & values"

check "Integer username (POST /api/users)" "400" POST /api/users \
  -H "Content-Type: application/json" \
  -d '{"username": 99999, "email": "valid@example.com"}'

check "Boolean username (POST /api/users)" "400" POST /api/users \
  -H "Content-Type: application/json" \
  -d '{"username": true, "email": "valid@example.com"}'

check "Null email (POST /api/users)" "400" POST /api/users \
  -H "Content-Type: application/json" \
  -d '{"username": "validname", "email": null}'

check "Invalid email format (POST /api/users)" "400" POST /api/users \
  -H "Content-Type: application/json" \
  -d '{"username": "validname", "email": "notanemail"}'

check "Email without TLD (POST /api/users)" "400" POST /api/users \
  -H "Content-Type: application/json" \
  -d '{"username": "validname", "email": "user@nodomain"}'

check "Non-URL original_url — plain text (POST /api/urls)" "400" POST /api/urls \
  -H "Content-Type: application/json" \
  -d '{"original_url": "not-a-url"}'

check "Non-URL original_url — ftp scheme (POST /api/urls)" "400" POST /api/urls \
  -H "Content-Type: application/json" \
  -d '{"original_url": "ftp://files.example.com"}'

check "Non-URL original_url — bare hostname (POST /api/urls)" "400" POST /api/urls \
  -H "Content-Type: application/json" \
  -d '{"original_url": "example.com"}'

check "Integer is_active field (POST /api/urls)" "400" POST /api/urls \
  -H "Content-Type: application/json" \
  -d '{"original_url": "https://example.com", "is_active": 1}'

# ════════════════════════════════════════════════════════════════════════════ #
hdr "The Unwitting Stranger — Missing required fields"

check "POST /api/users — missing email" "400" POST /api/users \
  -H "Content-Type: application/json" \
  -d '{"username": "missingemail"}'

check "POST /api/users — missing username" "400" POST /api/users \
  -H "Content-Type: application/json" \
  -d '{"email": "valid@example.com"}'

check "POST /api/users — empty object" "400" POST /api/users \
  -H "Content-Type: application/json" \
  -d '{}'

check "POST /api/urls — missing original_url" "400" POST /api/urls \
  -H "Content-Type: application/json" \
  -d '{}'

check "POST /api/urls — empty original_url string" "400" POST /api/urls \
  -H "Content-Type: application/json" \
  -d '{"original_url": "   "}'

# ════════════════════════════════════════════════════════════════════════════ #
hdr "The Slumbering Guide — Inactive & nonexistent resources"

# Deactivate the real URL first
curl -s -X PUT "${BASE_URL}/api/urls/${REAL_URL_ID}" \
  -H "Content-Type: application/json" \
  -d '{"is_active": false}' > /dev/null

if [ -n "$REAL_SHORT_CODE" ]; then
  check "GET inactive short code — 404, no redirect" "404" GET "/${REAL_SHORT_CODE}"
fi

check "GET /api/users/999999 — nonexistent user" "404" GET /api/users/999999

check "GET /api/urls/999999 — nonexistent URL" "404" GET /api/urls/999999

check "GET /api/urls/999999/stats — nonexistent URL stats" "404" GET /api/urls/999999/stats

check "PUT /api/users/999999 — update nonexistent user" "404" PUT /api/users/999999 \
  -H "Content-Type: application/json" \
  -d '{"username": "ghost"}'

check "PUT /api/urls/999999 — update nonexistent URL" "404" PUT /api/urls/999999 \
  -H "Content-Type: application/json" \
  -d '{"title": "ghost"}'

check "DELETE /api/urls/999999 — delete nonexistent URL" "404" DELETE /api/urls/999999

check "GET /doesnotexist99 — unknown short code redirect" "404" GET /doesnotexist99

# ════════════════════════════════════════════════════════════════════════════ #
hdr "Twin's Paradox & Uniqueness Constraints"

# Create a user to use for duplicate tests
DUP_USER=$(curl -s -X POST "${BASE_URL}/api/users" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"duptest_$(date +%s)\",\"email\":\"duptest_$(date +%s)@example.com\"}" 2>/dev/null)
DUP_USER_NAME=$(echo "$DUP_USER" | python3 -c "import sys,json; print(json.load(sys.stdin)['username'])" 2>/dev/null || echo "duptest")
DUP_USER_EMAIL=$(echo "$DUP_USER" | python3 -c "import sys,json; print(json.load(sys.stdin)['email'])" 2>/dev/null || echo "dup@example.com")

check "Duplicate username — 409 Conflict" "409" POST /api/users \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"${DUP_USER_NAME}\",\"email\":\"another_$(date +%s)@example.com\"}"

check "Duplicate email — 409 Conflict" "409" POST /api/users \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"anothername_$(date +%s)\",\"email\":\"${DUP_USER_EMAIL}\"}"

# Create a URL with a custom code, then try to claim it again
TAKEN_CODE="taken_$(date +%s | tail -c 6)"
curl -s -X POST "${BASE_URL}/api/urls" \
  -H "Content-Type: application/json" \
  -d "{\"original_url\":\"https://example.com/first\",\"short_code\":\"${TAKEN_CODE}\"}" > /dev/null

check "Duplicate custom short_code — 409 Conflict" "409" POST /api/urls \
  -H "Content-Type: application/json" \
  -d "{\"original_url\":\"https://example.com/second\",\"short_code\":\"${TAKEN_CODE}\"}"

check "Reserved short code 'api' — 400 Bad Request" "400" POST /api/urls \
  -H "Content-Type: application/json" \
  -d '{"original_url":"https://example.com","short_code":"api"}'

check "Reserved short code 'health' — 400 Bad Request" "400" POST /api/urls \
  -H "Content-Type: application/json" \
  -d '{"original_url":"https://example.com","short_code":"health"}'

check "Custom short code too long (>20 chars) — 400" "400" POST /api/urls \
  -H "Content-Type: application/json" \
  -d '{"original_url":"https://example.com","short_code":"this-code-is-way-too-long-to-be-valid"}'

check "Custom short code with spaces — 400" "400" POST /api/urls \
  -H "Content-Type: application/json" \
  -d '{"original_url":"https://example.com","short_code":"has spaces"}'

# ════════════════════════════════════════════════════════════════════════════ #
hdr "Bulk Import — Bad CSV payloads"

check "POST /api/users/bulk — no file field" "400" POST /api/users/bulk \
  -F "wrong_field=@/dev/null"

# ── Summary ───────────────────────────────────────────────────────────────────
TOTAL=$((PASS + FAIL))
echo ""
printf "${BOLD}════════════════════════════════════════${RESET}\n"
printf "${BOLD}Results: %d / %d checks passed${RESET}\n" "$PASS" "$TOTAL"
printf "${BOLD}════════════════════════════════════════${RESET}\n"

if [ "$FAIL" -eq 0 ]; then
  printf "\n${GREEN}${BOLD}✓ All garbage inputs returned clean JSON errors.${RESET}\n"
  printf "${DIM}No stack traces. No HTML. No crashes. Graceful failure confirmed.${RESET}\n\n"
  exit 0
else
  printf "\n${RED}${BOLD}✗ %d check(s) failed — see above for details.${RESET}\n\n" "$FAIL"
  exit 1
fi
