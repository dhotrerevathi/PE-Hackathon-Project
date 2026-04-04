#!/bin/bash
# Configure 2 GB swap on a DigitalOcean (or any Linux) droplet.
#
# Rule of thumb: swap = 2× RAM when RAM ≤ 2 GB
# Run once as root: sudo bash setup-swap.sh
set -e

SWAP_FILE="/swapfile"
SWAP_SIZE="2G"

if swapon --show | grep -q "$SWAP_FILE"; then
  echo "Swap already active on $SWAP_FILE — skipping creation."
else
  echo "Creating ${SWAP_SIZE} swap file at ${SWAP_FILE}..."
  fallocate -l "$SWAP_SIZE" "$SWAP_FILE"
  chmod 600 "$SWAP_FILE"
  mkswap "$SWAP_FILE"
  swapon "$SWAP_FILE"

  # Persist across reboots
  if ! grep -q "$SWAP_FILE" /etc/fstab; then
    echo "$SWAP_FILE none swap sw 0 0" >> /etc/fstab
  fi
  echo "Swap created and enabled."
fi

# ── Kernel memory tuning ──────────────────────────────────────────────────────
# swappiness=10  → only use swap when RAM is nearly full (default=60 is too eager)
# vfs_cache_pressure=50 → retain directory/inode cache longer (good for web servers)
cat >> /etc/sysctl.conf << 'EOF'

# Swap tuning for 1 GB droplet
vm.swappiness=10
vm.vfs_cache_pressure=50
EOF
sysctl -p

echo ""
echo "Done. Current memory layout:"
free -h
echo ""
swapon --show
