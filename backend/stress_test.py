"""
stress_test.py — Threaded stress test for the payout engine.

Usage:
    cd backend
    venv\\Scripts\\python.exe stress_test.py [--requests N] [--concurrency N] [--amount N]

Defaults: 100 requests, 20 concurrent threads, 500 paise per payout.
"""

import argparse
import os
import sys
import time
import uuid
import statistics
import threading
import django
import requests as http

BASE_URL = "http://127.0.0.1:8000/api/v1"
HEADERS  = {"Content-Type": "application/json"}

# ── Results store ─────────────────────────────────────────────────────────────
results = {
    "success":    [],   # (payout_id, latency_ms)
    "rejected":   [],   # (status_code, latency_ms)
    "errors":     [],   # (exception_str, latency_ms)
    "idempotent": [],   # replayed keys that returned 200
}
lock = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _record(bucket, value):
    with lock:
        results[bucket].append(value)


def create_merchant(name: str) -> int:
    r = http.post(f"{BASE_URL}/merchants", json={"name": name}, headers=HEADERS)
    r.raise_for_status()
    return r.json()["merchant_id"]


def topup(merchant_id: int, amount_paise: int):
    r = http.post(
        f"{BASE_URL}/merchants/{merchant_id}/topup",
        json={"amount_paise": amount_paise},
        headers=HEADERS,
    )
    r.raise_for_status()


def get_merchant(merchant_id: int) -> dict:
    r = http.get(f"{BASE_URL}/merchants/{merchant_id}", headers=HEADERS)
    r.raise_for_status()
    return r.json()


def fire_payout(merchant_id: int, amount_paise: int, idempotency_key: str):
    start = time.monotonic()
    try:
        r = http.post(
            f"{BASE_URL}/payouts",
            json={"merchant_id": merchant_id, "amount_paise": amount_paise},
            headers={**HEADERS, "Idempotency-Key": idempotency_key},
            timeout=10,
        )
        latency = int((time.monotonic() - start) * 1000)

        if r.status_code == 201:
            _record("success", (r.json().get("payout_id"), latency))
        elif r.status_code == 200:
            _record("idempotent", (r.json().get("payout_id"), latency))
        else:
            _record("rejected", (r.status_code, latency))

    except Exception as exc:
        latency = int((time.monotonic() - start) * 1000)
        _record("errors", (str(exc), latency))


# ── Core runner ───────────────────────────────────────────────────────────────

def run_stress(merchant_id: int, total: int, concurrency: int, amount_paise: int):
    keys = [str(uuid.uuid4()) for _ in range(total)]
    semaphore = threading.Semaphore(concurrency)
    threads = []

    def worker(key):
        with semaphore:
            fire_payout(merchant_id, amount_paise, key)

    print(f"\n  Firing {total} requests  |  concurrency={concurrency}  |  amount={amount_paise} paise")
    wall_start = time.monotonic()

    for key in keys:
        t = threading.Thread(target=worker, args=(key,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    return time.monotonic() - wall_start


# ── Idempotency replay test ───────────────────────────────────────────────────

def run_idempotency_replay(merchant_id: int, amount_paise: int, n: int = 10):
    """Fire the same key n times — all after the first must return 200."""
    key = str(uuid.uuid4())
    print(f"\n  Idempotency replay: key={key}  n={n}")
    for _ in range(n):
        fire_payout(merchant_id, amount_paise, key)


# ── Post-run validation ───────────────────────────────────────────────────────

def validate(merchant_id: int):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()

    from django.db.models import Sum, Count
    from payouts.models import Merchant, LedgerEntry, Payout

    print("\n" + "=" * 60)
    print("  POST-RUN VALIDATION")
    print("=" * 60)

    merchant = Merchant.objects.get(id=merchant_id)

    credits = (
        LedgerEntry.objects.filter(merchant=merchant, type=LedgerEntry.CREDIT)
        .aggregate(t=Sum("amount"))["t"] or 0
    )
    debits = (
        LedgerEntry.objects.filter(merchant=merchant, type=LedgerEntry.DEBIT)
        .aggregate(t=Sum("amount"))["t"] or 0
    )
    balance = credits - debits

    status_counts = dict(
        Payout.objects.filter(merchant=merchant)
        .values_list("status")
        .annotate(c=Count("id"))
        .values_list("status", "c")
    )

    held = (
        Payout.objects.filter(merchant=merchant, status__in=[Payout.PENDING, Payout.PROCESSING])
        .aggregate(t=Sum("amount"))["t"] or 0
    )
    available = balance - held

    print(f"  Ledger credits  : {credits:>12} paise")
    print(f"  Ledger debits   : {debits:>12} paise")
    print(f"  Net balance     : {balance:>12} paise")
    print(f"  Held (in-flight): {held:>12} paise")
    print(f"  Available       : {available:>12} paise")
    print(f"  Payout statuses : {status_counts}")

    # ── Assertions ────────────────────────────────────────────────────────────
    failures = []

    if available < 0:
        failures.append(f"FAIL  available balance is negative: {available}")

    dupes = (
        Payout.objects.filter(merchant=merchant)
        .values("amount", "status")
        .annotate(c=Count("id"))
        .filter(c__gt=1, status=Payout.PENDING)
    )
    if dupes.exists():
        failures.append(f"FAIL  duplicate pending payouts detected: {list(dupes)}")

    failed_ids = list(
        Payout.objects.filter(merchant=merchant, status=Payout.FAILED)
        .values_list("id", "amount")
    )
    for payout_id, amount in failed_ids:
        has_refund = LedgerEntry.objects.filter(
            merchant=merchant, type=LedgerEntry.CREDIT, amount=amount
        ).exists()
        if not has_refund:
            failures.append(f"FAIL  payout {payout_id} failed but no refund credit found")

    print()
    if failures:
        for f in failures:
            print(f"  {f}")
    else:
        print("  ALL CHECKS PASSED")
    print("=" * 60)


# ── Report ────────────────────────────────────────────────────────────────────

def print_report(wall_seconds: float, total: int):
    all_latencies = (
        [l for _, l in results["success"]]
        + [l for _, l in results["rejected"]]
        + [l for _, l in results["errors"]]
        + [l for _, l in results["idempotent"]]
    )

    print("\n" + "=" * 60)
    print("  STRESS TEST RESULTS")
    print("=" * 60)
    print(f"  Total requests   : {total}")
    print(f"  Successful (201) : {len(results['success'])}")
    print(f"  Rejected (4xx)   : {len(results['rejected'])}")
    print(f"  Idempotent (200) : {len(results['idempotent'])}")
    print(f"  Errors           : {len(results['errors'])}")
    print(f"  Wall time        : {wall_seconds:.2f}s")
    print(f"  Throughput       : {total / wall_seconds:.1f} req/s")

    if all_latencies:
        print(f"  Latency p50      : {statistics.median(all_latencies):.0f}ms")
        print(f"  Latency p95      : {sorted(all_latencies)[int(len(all_latencies) * 0.95)]:.0f}ms")
        print(f"  Latency max      : {max(all_latencies):.0f}ms")

    if results["errors"]:
        print(f"\n  Sample errors:")
        for err, _ in results["errors"][:3]:
            print(f"    {err}")
    print("=" * 60)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests",    type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--amount",      type=int, default=500)
    args = parser.parse_args()

    total_credit = args.requests * args.amount + 10_000  # buffer

    print("=" * 60)
    print("  PAYOUT ENGINE STRESS TEST")
    print("=" * 60)

    print("\n[1] Creating test merchant...")
    merchant_id = create_merchant(f"StressTest-{uuid.uuid4().hex[:6]}")
    print(f"    merchant_id = {merchant_id}")

    print(f"\n[2] Topping up {total_credit} paise...")
    topup(merchant_id, total_credit)
    print(f"    Balance: {get_merchant(merchant_id)['available_paise']} paise")

    print("\n[3] Running stress test...")
    wall = run_stress(merchant_id, args.requests, args.concurrency, args.amount)

    print("\n[4] Running idempotency replay test...")
    run_idempotency_replay(merchant_id, args.amount)

    print_report(wall, args.requests)

    print("\n[5] Running post-run validation...")
    validate(merchant_id)


if __name__ == "__main__":
    main()
