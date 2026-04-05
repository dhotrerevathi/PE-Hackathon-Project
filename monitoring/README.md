# Monitoring & Incident Response

## Overview

| Service | URL | Purpose |
|---------|-----|---------|
| Grafana | http://159.203.3.94/grafana/ | Golden Signals dashboard, alert visualisation |
| Prometheus | http://159.203.3.94:9090 | Metrics storage and alert evaluation |
| Node Exporter | localhost:9100 | Host-level CPU, memory, disk metrics |
| /metrics | http://159.203.3.94/metrics | Flask Prometheus endpoint (scraped by Prometheus) |

---

## Bronze — Structured Logging + Metrics

Every log line is emitted as JSON with these fields:

```json
{
  "timestamp": "2026-01-15T14:23:01",
  "level": "INFO",
  "name": "app",
  "message": "request",
  "method": "GET",
  "path": "/abc123",
  "status": 302,
  "instance": "app_1"
}
```

Error logs include `exc_info` for stack traces:

```json
{
  "timestamp": "2026-01-15T14:23:45",
  "level": "ERROR",
  "name": "app",
  "message": "unhandled_exception",
  "error": "division by zero",
  "path": "/api/urls",
  "exc_info": "Traceback (most recent call last):\n  ..."
}
```

Metrics are exposed at `/metrics` by `prometheus-flask-exporter`.  Key metrics:

| Metric | Type | Description |
|--------|------|-------------|
| `flask_http_request_total` | counter | Requests by method/path/status |
| `flask_http_request_duration_seconds` | histogram | Response time distribution |
| `process_resident_memory_bytes` | gauge | App RSS |
| `process_cpu_seconds_total` | counter | CPU time |
| `app_info` | gauge | App version info |

---

## Silver — Alerting to Discord

### Alert rules (`monitoring/alert_rules.yml`)

| Alert | Condition | Severity | Fire after |
|-------|-----------|----------|-----------|
| InstanceDown | `up{job="flask-app"} == 0` | critical | 1 min |
| HighErrorRate | 5xx rate > 5% | warning | 2 min |
| HighLatency | p95 > 3 s | warning | 3 min |
| HighMemoryUsage | RSS > 180 MB | warning | 5 min |

### Deploy Alertmanager on the server

```bash
# 1. Install Alertmanager
wget https://github.com/prometheus/alertmanager/releases/download/v0.27.0/alertmanager-0.27.0.linux-amd64.tar.gz
tar xzf alertmanager-0.27.0.linux-amd64.tar.gz
sudo mv alertmanager-0.27.0.linux-amd64/alertmanager /usr/local/bin/

# 2. Copy config (set your Discord webhook first)
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN"
envsubst < monitoring/alertmanager.yml | sudo tee /etc/alertmanager/alertmanager.yml

# 3. Run Alertmanager as a systemd service
sudo tee /etc/systemd/system/alertmanager.service <<EOF
[Unit]
Description=Alertmanager
After=network.target

[Service]
ExecStart=/usr/local/bin/alertmanager --config.file=/etc/alertmanager/alertmanager.yml
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now alertmanager

# 4. Copy alert rules + Prometheus config
sudo cp monitoring/alert_rules.yml /etc/prometheus/alert_rules.yml
sudo cp monitoring/prometheus.yml /etc/prometheus/prometheus.yml
sudo systemctl reload prometheus
```

### Discord webhook setup

1. In your Discord server: **Server Settings → Integrations → Webhooks → New Webhook**
2. Select the channel for alerts (#incidents or similar)
3. Copy the webhook URL
4. Set `DISCORD_WEBHOOK_URL` in `/etc/alertmanager/alertmanager.yml`
5. Reload: `sudo systemctl reload alertmanager`

### Test an alert

```bash
# Temporarily stop the app to trigger InstanceDown
docker compose -f docker-compose.1gb.yml stop app
# Wait ~1 minute → Discord receives a 🔴 critical alert
docker compose -f docker-compose.1gb.yml start app
# Alert resolves → Discord receives resolved notification
```

---

## Gold — Golden Signals Dashboard

The dashboard (`monitoring/dashboards/golden_signals.json`) tracks Google's
Four Golden Signals:

| Signal | Panels | Threshold turns red |
|--------|--------|---------------------|
| **Latency** | p50/p95 overall + p95 by endpoint | p95 > 3 s |
| **Traffic** | RPS by status code + by endpoint | — |
| **Errors** | 5xx gauge + 4xx/5xx over time | 5xx > 5% |
| **Saturation** | Memory gauge + CPU + open FDs | RSS > 185 MB |

Plus a Quick Stats row: live App Status, RPS, p95, Error Rate, Memory.

### Load the dashboard

#### Option A — Auto-provisioning (recommended)

```bash
# 1. Copy provisioning config
sudo cp -r monitoring/provisioning/dashboards /etc/grafana/provisioning/
sudo cp -r monitoring/provisioning/datasources /etc/grafana/provisioning/

# 2. Copy the dashboard JSON
sudo mkdir -p /etc/grafana/dashboards
sudo cp monitoring/dashboards/golden_signals.json /etc/grafana/dashboards/

# 3. Restart Grafana
sudo systemctl restart grafana-server

# Dashboard appears at: http://159.203.3.94/grafana/d/golden-signals
```

#### Option B — Manual import

1. Open http://159.203.3.94/grafana/
2. **Dashboards → Import**
3. Upload `monitoring/dashboards/golden_signals.json`
4. Select the **Prometheus** datasource
5. Click **Import**

---

## Sherlock Mode — Incident Diagnosis Walkthrough

When an alert fires, open the dashboard and follow this checklist:

### 🔴 InstanceDown

```
1. Quick Stats row → App Status = DOWN (red)
2. Check: docker compose -f docker-compose.1gb.yml ps app
3. Check: docker compose logs --tail=50 app
4. Follow: docs/runbooks.md → RB-01
```

### 🟡 HighErrorRate

```
1. Errors row → Error Rate Over Time panel → when did it spike?
2. Latency row → check if latency also spiked (DB/Redis slow?)
3. Traffic row → RPS by Endpoint → which path is throwing errors?
4. Check logs: docker compose logs --tail=100 app | grep '"level":"ERROR"'
5. If DB-related: docs/runbooks.md → RB-02
6. If Redis-related: docs/runbooks.md → RB-04
```

### 🟡 HighLatency

```
1. Latency by Endpoint panel → which endpoint is slow?
2. /health check: curl http://localhost/health — is cache "redis" or "simplecache"?
3. If "simplecache": Redis is down → docs/runbooks.md → RB-04
4. If Redis OK: check DB slow queries → docs/runbooks.md → RB-03
5. If CPU saturated: scale app → ./scripts/manage.sh scale 2
```

### 🟡 HighMemoryUsage

```
1. Saturation row → App Memory gauge nearing 200 MB?
2. docker stats --no-stream
3. docs/runbooks.md → RB-05 (OOM)
```
