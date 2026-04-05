"""
Locust load test for the URL shortener — alternative to k6.

Usage:
  # Install locust (one-time)
  pip install locust

  # Headless (CLI) — Bronze: 50 users, 30s
  locust -f load_tests/locust/locustfile.py \
    --headless --users 50 --spawn-rate 10 --run-time 30s \
    --host http://localhost:5000

  # Headless — Silver: 200 users, 90s
  locust -f load_tests/locust/locustfile.py \
    --headless --users 200 --spawn-rate 20 --run-time 90s \
    --host http://localhost:5000

  # Headless — Gold: 500 users, 2 minutes
  locust -f load_tests/locust/locustfile.py \
    --headless --users 500 --spawn-rate 50 --run-time 2m \
    --host http://localhost:5000

  # Web UI (open http://localhost:8089)
  locust -f load_tests/locust/locustfile.py --host http://localhost:5000
"""

import random

from locust import HttpUser, between, task


class URLShortenerUser(HttpUser):
    """Simulates a realistic mix of read traffic against the URL shortener."""

    # Random wait between requests: 50ms–200ms think time
    wait_time = between(0.05, 0.2)

    # Populated in on_start; shared state per virtual user
    short_codes: list[str] = []
    user_id: int | None = None

    def on_start(self):
        """Called once when a virtual user starts — seeds test data."""
        uid = random.randint(10_000, 99_999)
        resp = self.client.post(
            "/api/users",
            json={"username": f"locust_{uid}", "email": f"locust_{uid}@example.com"},
            name="/api/users [setup]",
        )
        if resp.status_code != 201:
            return

        self.user_id = resp.json()["id"]

        # Create 3 short URLs for this virtual user
        for i in range(3):
            url_resp = self.client.post(
                "/api/urls",
                json={
                    "original_url": f"https://example.com/locust-target-{uid}-{i}",
                    "user_id": self.user_id,
                },
                name="/api/urls [setup]",
            )
            if url_resp.status_code == 201:
                self.short_codes.append(url_resp.json()["short_code"])

    # ── Tasks (weights control relative frequency) ────────────────────────────

    @task(3)
    def health_check(self):
        """Health endpoint — no DB, fastest possible response."""
        self.client.get("/health")

    @task(4)
    def global_stats(self):
        """Global stats — Redis-cached, low DB pressure."""
        self.client.get("/api/stats")

    @task(5)
    def redirect(self):
        """Short code redirect — hottest production path, Redis-cached."""
        if not self.short_codes:
            return
        code = random.choice(self.short_codes)
        self.client.get(f"/{code}", allow_redirects=False, name="/[short_code]")

    @task(3)
    def list_urls(self):
        """Paginated URL list."""
        page = random.randint(1, 3)
        self.client.get(f"/api/urls?page={page}&per_page=10")

    @task(2)
    def list_users(self):
        """Paginated user list."""
        self.client.get("/api/users?per_page=10")

    @task(1)
    def list_events(self):
        """Event feed — lower frequency, real-time analytics simulation."""
        self.client.get("/api/events?per_page=10")
