#!/usr/bin/env bash
# scripts/chaos.sh — Chaos Engineering Demo
#
# Forcefully kills the app container and watches Docker resurrect it automatically.
# This demonstrates the "restart: unless-stopped" policy in docker-compose.1gb.yml.
#
# Usage:
#   ./scripts/chaos.sh                          # defaults: http://localhost, local compose
#   BASE_URL=http://1.2.3.4 ./scripts/chaos.sh  # remote droplet
#   COMPOSE_FILE=docker-compose.yml ./scripts/chaos.sh

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL="${BASE_URL:-http://localhost}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.1gb.yml}"
HEALTH_ENDPOINT="${BASE_URL}/health"
MAX_WAIT=60   # seconds before giving up on recovery

# ── Helpers ───────────────────────────────────────────────────────────────────
ts()  { date '+%H:%M:%S'; }
log() { printf "${DIM}[$(ts)]${RESET} $*\n"; }
ok()  { printf "${GREEN}✓${RESET} $*\n"; }
err() { printf "${RED}✗${RESET} $*\n"; }
hdr() { printf "\n${BOLD}${CYAN}═══ $* ═══${RESET}\n\n"; }

health_status() {
  curl -s --max-time 3 "$HEALTH_ENDPOINT" 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" \
    2>/dev/null || echo "down"
}

# ── Pre-flight ────────────────────────────────────────────────────────────────
hdr "Chaos Engineering Demo — Kill & Resurrect"

printf "${YELLOW}Target:${RESET}  %s\n" "$HEALTH_ENDPOINT"
printf "${YELLOW}Compose:${RESET} %s\n\n" "$COMPOSE_FILE"

# Check Docker is available
if ! docker info &>/dev/null; then
  err "Docker is not running. Start Docker first."
  exit 1
fi

# Check the compose stack is up
APP_CONTAINER=$(docker compose -f "$COMPOSE_FILE" ps -q app 2>/dev/null | head -1)
if [ -z "$APP_CONTAINER" ]; then
  err "No app container found. Run: docker compose -f $COMPOSE_FILE up -d"
  exit 1
fi

# ── Step 1: Pre-chaos health check ───────────────────────────────────────────
hdr "Step 1 — Confirming service is healthy"

STATUS=$(health_status)
if [ "$STATUS" != "ok" ]; then
  err "Service is not healthy before chaos (status: $STATUS). Aborting."
  exit 1
fi

printf "Container ID:  ${BOLD}%s${RESET}\n" "$APP_CONTAINER"
printf "Health status: ${GREEN}${BOLD}%s${RESET}\n" "$STATUS"
RESPONSE=$(curl -s --max-time 3 "$HEALTH_ENDPOINT" 2>/dev/null || echo '{}')
printf "Response:      %s\n" "$RESPONSE"

# ── Step 2: Kill the container ────────────────────────────────────────────────
hdr "Step 2 — Killing the app container (SIGKILL)"

printf "Running: ${BOLD}docker kill %s${RESET}\n\n" "$APP_CONTAINER"
KILL_TIME=$(ts)
docker kill "$APP_CONTAINER" > /dev/null
printf "${RED}${BOLD}💀 Container killed at %s${RESET}\n" "$KILL_TIME"

# Brief pause to let Docker notice the exit
sleep 1

# Verify it's gone / restarting
CONTAINER_STATUS=$(docker inspect --format='{{.State.Status}}' "$APP_CONTAINER" 2>/dev/null || echo "gone")
printf "Container state immediately after kill: ${YELLOW}%s${RESET}\n" "$CONTAINER_STATUS"

# ── Step 3: Poll for health until it recovers ─────────────────────────────────
hdr "Step 3 — Watching Docker restart the container"

printf "${DIM}Polling %s every second (max %ds)...${RESET}\n\n" "$HEALTH_ENDPOINT" "$MAX_WAIT"

START=$(date +%s)
RECOVERED=false

for i in $(seq 1 "$MAX_WAIT"); do
  CURRENT_STATUS=$(health_status)
  ELAPSED=$(( $(date +%s) - START ))

  if [ "$CURRENT_STATUS" = "ok" ]; then
    RECOVERED=true
    NEW_CONTAINER=$(docker compose -f "$COMPOSE_FILE" ps -q app 2>/dev/null | head -1)
    printf "\r${GREEN}${BOLD}✓ Service is back! (attempt %d, elapsed: %ds)${RESET}           \n" \
      "$i" "$ELAPSED"
    break
  else
    printf "\r${YELLOW}[%ds]${RESET} ${DIM}Attempt %d/%d — status: %s${RESET}" \
      "$ELAPSED" "$i" "$MAX_WAIT" "$CURRENT_STATUS"
    sleep 1
  fi
done

echo ""

# ── Step 4: Post-chaos report ─────────────────────────────────────────────────
hdr "Step 4 — Recovery Report"

if [ "$RECOVERED" = "true" ]; then
  TOTAL_TIME=$(( $(date +%s) - START ))
  ok "Service fully recovered in ${BOLD}${TOTAL_TIME} seconds${RESET}"

  NEW_CONTAINER=$(docker compose -f "$COMPOSE_FILE" ps -q app 2>/dev/null | head -1)
  printf "\nOld container: ${RED}%s${RESET}\n" "$APP_CONTAINER"
  printf "New container: ${GREEN}%s${RESET}\n" "$NEW_CONTAINER"

  FINAL=$(curl -s --max-time 5 "$HEALTH_ENDPOINT" 2>/dev/null || echo '{"status":"?"}')
  printf "Final health:  %s\n" "$FINAL"

  echo ""
  printf "${BOLD}${GREEN}✓ Chaos test passed.${RESET}\n"
  printf "${DIM}The 'restart: unless-stopped' policy in docker-compose.1gb.yml\n"
  printf "automatically recreated the container without any manual intervention.${RESET}\n"
else
  err "Service did NOT recover within ${MAX_WAIT} seconds."
  echo ""
  printf "${DIM}Debug — container status:${RESET}\n"
  docker compose -f "$COMPOSE_FILE" ps
  echo ""
  printf "${DIM}Recent logs:${RESET}\n"
  docker compose -f "$COMPOSE_FILE" logs --tail=20 app
  exit 1
fi
