# Server Management Script (`manage.sh`)

The `manage.sh` script is a remote administration tool for the URL Shortener project. It allows you to perform server lifecycle tasks, tail logs, check system health, and manage database seeding directly from your local machine.

## Prerequisites

Depending on your preferred authentication method, you will need:
- **Key-based Auth (Recommended):** Standard `ssh` and `scp`. Ensure your public key is added to the server's `~/.ssh/authorized_keys`.
- **Password-based Auth:** Requires `sshpass`.
  - **Mac:** `brew install sshpass`
  - **CentOS/RHEL:** `dnf install epel-release && dnf install sshpass`
  - **Ubuntu/Debian:** `apt install sshpass`

## Configuration

Create a `.env.local` file in the `scripts/` directory. **This file is gitignored and should never be committed.**

```bash
# scripts/.env.local
DROPLET_HOST=192.168.1.100              # Replace with your server's IP address
DROPLET_USER=root                       # SSH username
DROPLET_PASS=                           # Leave empty to use SSH key authentication (Recommended)
DEPLOY_DIR=/opt/urlshortener            # Deployment directory on the server
DISCORD_WEBHOOK=https://discord.com/... # (Optional) Discord webhook URL for notifications
```

## Usage

Run the script from the root of the project or from within the `scripts/` directory:

```bash
./scripts/manage.sh <command> [options]
```

### Container Lifecycle

| Command | Description |
|---------|-------------|
| `restart [service]` | Restarts container(s) and notifies Discord (e.g. `restart app`). |
| `stop [service]` | Stops container(s) and notifies Discord. Note: Stopped containers do NOT auto-restart. |
| `rebuild` | Force-recreates all containers from the current image and notifies Discord. |
| `scale [N]` | Scales the `app` service to `N` instances (default: 2), restarts Nginx, and notifies Discord. |

### Observability

| Command | Description |
|---------|-------------|
| `status` | Shows running containers, memory, disk usage, load average, and API health check. |
| `logs [service]` | Tails the last 100 log lines for a specific container (default: `app`). |
| `notify` | Posts a server status embed (Memory, Disk, App Health) to the configured Discord webhook. |
| `ping` | Verifies SSH connectivity and returns the running container count. |

### Seeding & Data

| Command | Description |
|---------|-------------|
| `upload-seeds` | Uploads `users.csv`, `urls.csv`, and `events.csv` via SCP to the deployment directory. |
| `reseed [csv|faker]` | Drops the database and reseeds it. Use `csv` to use uploaded files, or `faker` to generate fresh data. |

### Server Bootstrap

| Command | Description |
|---------|-------------|
| `setup` | A one-time command to install Docker CE, `docker-compose-plugin`, and `sshpass` on a fresh CentOS Stream 9 Droplet. |

## Restart Policy Notes

The production `docker-compose.1gb.yml` uses the `unless-stopped` restart policy:
- **Container crashes:** Docker auto-restarts it.
- **Server reboots:** Docker auto-restarts the stack.
- **Using `./manage.sh stop`:** The container stays stopped (this is intentional for maintenance). Use `./manage.sh rebuild` or `restart` to bring it back up.
