#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# purge-secrets.sh
#
# Permanently removes sensitive files from the ENTIRE git history.
# Use this when a secret or data file was accidentally committed.
#
# What this script removes:
#   - .env              (credentials)
#   - *.csv             (seed data files — users.csv, urls.csv, events.csv)
#   - Any custom paths passed as arguments: ./purge-secrets.sh secrets.json
#
# ⚠  WARNING: This rewrites history. Every collaborator must re-clone or
#    run `git pull --rebase` after you force-push.
#
# Prerequisites:
#   pip install git-filter-repo      (fast, modern — preferred)
#   brew install git-filter-repo     (macOS)
#   apt install git-filter-repo      (Debian/Ubuntu 22.04+)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'; NC='\033[0m'

# ── Sanity checks ─────────────────────────────────────────────────────────────
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
  echo -e "${RED}Error: not inside a git repository.${NC}"
  exit 1
fi

if ! command -v git-filter-repo &>/dev/null; then
  echo -e "${RED}Error: git-filter-repo not found.${NC}"
  echo "Install it with:"
  echo "  pip install git-filter-repo"
  echo "  brew install git-filter-repo   (macOS)"
  exit 1
fi

# ── Warn loudly before doing anything destructive ────────────────────────────
echo -e "${YELLOW}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  WARNING: This rewrites ALL git history.                    ║"
echo "║  • Force-push to remote is required after this script.      ║"
echo "║  • All collaborators MUST re-clone or rebase.               ║"
echo "║  • Revoke and rotate any exposed secrets immediately.        ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

read -r -p "Type 'yes' to continue: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "Aborted."
  exit 0
fi

# ── Files to remove (defaults + any extra args) ───────────────────────────────
FILES_TO_PURGE=(
  ".env"
  "users.csv"
  "urls.csv"
  "events.csv"
)

# Append any extra filenames passed as arguments
for extra in "$@"; do
  FILES_TO_PURGE+=("$extra")
done

echo ""
echo "Files to purge from history:"
for f in "${FILES_TO_PURGE[@]}"; do
  echo "  - $f"
done
echo ""

# ── Run git-filter-repo ───────────────────────────────────────────────────────
# Build the --path arguments
PATH_ARGS=()
for f in "${FILES_TO_PURGE[@]}"; do
  PATH_ARGS+=(--path "$f")
done

echo -e "${YELLOW}Running git-filter-repo...${NC}"
git filter-repo "${PATH_ARGS[@]}" --invert-paths --force

echo -e "${GREEN}History rewritten locally.${NC}"

# ── Verify the files are gone ─────────────────────────────────────────────────
echo ""
echo "Verifying purge..."
FOUND=0
for f in "${FILES_TO_PURGE[@]}"; do
  if git log --all --full-history -- "$f" | grep -q "commit"; then
    echo -e "${RED}  ✗ $f still found in history!${NC}"
    FOUND=$((FOUND + 1))
  else
    echo -e "${GREEN}  ✓ $f not found in any commit.${NC}"
  fi
done

if [ "$FOUND" -gt 0 ]; then
  echo -e "${RED}Purge incomplete — check git-filter-repo output above.${NC}"
  exit 1
fi

# ── Re-add remote (git-filter-repo removes it as a safety measure) ───────────
echo ""
echo "git-filter-repo removes the remote origin as a safety measure."
read -r -p "Enter the remote URL to re-add (or press Enter to skip): " REMOTE_URL
if [ -n "$REMOTE_URL" ]; then
  git remote add origin "$REMOTE_URL"
  echo -e "${GREEN}Remote origin re-added.${NC}"
fi

# ── Instructions for next steps ───────────────────────────────────────────────
echo ""
echo -e "${YELLOW}════════════════════════════════════════════════════════════════${NC}"
echo "Next steps:"
echo ""
echo "1. Force-push the rewritten history:"
echo "   git push origin --force --all"
echo "   git push origin --force --tags"
echo ""
echo "2. Rotate ALL exposed credentials immediately:"
echo "   • Generate a new SECRET_KEY:    python3 -c \"import secrets; print(secrets.token_hex(32))\""
echo "   • Change DATABASE_PASSWORD in your hosting provider dashboard"
echo "   • Revoke and re-issue any API keys that appeared in committed files"
echo "   • Update GitHub Secrets (Settings → Secrets → Actions)"
echo ""
echo "3. Notify collaborators to re-clone:"
echo "   git clone <repo-url>   # fresh clone"
echo "   # OR"
echo "   git fetch origin"
echo "   git reset --hard origin/main"
echo ""
echo "4. Add the files to .gitignore to prevent future accidents:"
echo "   The .gitignore in this repo already covers .env and *.csv"
echo -e "${YELLOW}════════════════════════════════════════════════════════════════${NC}"
