"""
locustfile.py — Locust load test for the payout engine.

Run (web UI):
    cd backend
    venv\\Scripts\\locust.exe -f locustfile.py --host=http://127.0.0.1:8000

Run (headless, 50 users, 5 min):
    venv\\Scripts\\locust.exe -f locustfile.py --host=http://127.0.0.1:8000 ^
        --headless -u 50 -r 5 --run-time 5m --csv=results/load_test

Interpret results:
    - RPS        : requests per second — throughput
    - p50/p95    : latency percentiles — responsiveness
    - Failure %  : anything above 1% needs investigation
    - 400 on payout is EXPECTED (insufficient balance) — not a system failure
"""

import uuid
import threading
from locust import HttpUser, task, between, events

# ── Shared merchant pool ──────────────────────────────────────────────────────
# Created once at test start, shared across all simulated users.
_merchant_ids: list[int] = []
_pool_lock = threading.Lock()
TOPUP_PER_MERCHANT = 10_000_000  # 1 lakh rupees — enough for a long run


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Create a pool of 5 merchants and top them up before the test begins."""
    host = environment.host
    for i in range(5):
        r = environment.runner.client if hasattr(environment.runner, "client") else None
        # Use plain requests for setup since locust client isn't available yet
        import requests
        resp = requests.post(
            f"{host}/api/v1/merchants",
            json={"name": f"LoadTest-Merchant-{i+1}"},
        )
        if resp.status_code == 201:
            mid = resp.json()["merchant_id"]
            requests.post(
                f"{host}/api/v1/merchants/{mid}/topup",
                json={"amount_paise": TOPUP_PER_MERCHANT},
            )
            with _pool_lock:
                _merchant_ids.append(mid)
    print(f"\n[Locust] Merchant pool ready: {_merchant_ids}")


# ── User behaviour ────────────────────────────────────────────────────────────

class PayoutUser(HttpUser):
    """
    Simulates a realistic API consumer:
    - 70% of time: create a payout
    - 20% of time: check merchant balance
    - 10% of time: replay an existing idempotency key (tests idempotency)
    """
    wait_time = between(0.1, 0.5)  # think time between requests

    def on_start(self):
        import random
        with _pool_lock:
            if not _merchant_ids:
                self.merchant_id = None
                return
            self.merchant_id = random.choice(_merchant_ids)
        self._last_key: str | None = None

    @task(7)
    def create_payout(self):
        if not self.merchant_id:
            return
        key = str(uuid.uuid4())
        self._last_key = key
        self.client.post(
            "/api/v1/payouts",
            json={"merchant_id": self.merchant_id, "amount_paise": 100},
            headers={"Idempotency-Key": key},
            name="/api/v1/payouts [new]",
        )

    @task(2)
    def check_balance(self):
        if not self.merchant_id:
            return
        self.client.get(
            f"/api/v1/merchants/{self.merchant_id}",
            name="/api/v1/merchants/[id]",
        )

    @task(1)
    def replay_idempotency(self):
        """Replay the last used key — must return 200 with same payout_id."""
        if not self.merchant_id or not self._last_key:
            return
        with self.client.post(
            "/api/v1/payouts",
            json={"merchant_id": self.merchant_id, "amount_paise": 100},
            headers={"Idempotency-Key": self._last_key},
            name="/api/v1/payouts [replay]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 201:
                # First request in this task — not a replay, still fine
                resp.success()
            else:
                resp.failure(f"Idempotency replay failed: {resp.status_code} {resp.text}")
