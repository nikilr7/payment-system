"""
End-to-end test script for the payout engine.
Run with: venv\Scripts\python.exe test_e2e.py
Requires: Django server + Celery worker + Redis all running.
"""

import uuid
import requests

BASE = "http://127.0.0.1:8000/api/v1"
HEADERS = {"Content-Type": "application/json"}


def payout(merchant_id, amount_paise, idempotency_key=None):
    key = idempotency_key or str(uuid.uuid4())
    r = requests.post(
        f"{BASE}/payouts",
        json={"merchant_id": merchant_id, "amount_paise": amount_paise},
        headers={**HEADERS, "Idempotency-Key": key},
    )
    return r, key


def section(title):
    print(f"\n{'='*55}")
    print(f"  {title}")
    print(f"{'='*55}")


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))


# ------------------------------------------------------------------ #
# PART 1: Normal payout
# ------------------------------------------------------------------ #
section("1. Normal Payout (Merchant A = merchant_id 1)")

r, key = payout(merchant_id=1, amount_paise=5000)
check("HTTP 201 created",        r.status_code == 201,        str(r.status_code))
check("payout_id present",       "payout_id" in r.json(),     str(r.json()))
check("status is pending",       r.json().get("status") == "pending")

# ------------------------------------------------------------------ #
# PART 2: Idempotency
# ------------------------------------------------------------------ #
section("2. Idempotency — same key twice")

r1, idem_key = payout(merchant_id=1, amount_paise=3000)
r2, _        = payout(merchant_id=1, amount_paise=3000, idempotency_key=idem_key)

check("First call HTTP 201",     r1.status_code == 201,       str(r1.status_code))
check("Second call HTTP 200",    r2.status_code == 200,       str(r2.status_code))
check("Same payout_id returned", r1.json().get("payout_id") == r2.json().get("payout_id"),
      f"{r1.json()} vs {r2.json()}")

# ------------------------------------------------------------------ #
# PART 3: Missing Idempotency-Key header
# ------------------------------------------------------------------ #
section("3. Missing Idempotency-Key header")

r = requests.post(f"{BASE}/payouts",
                  json={"merchant_id": 1, "amount_paise": 1000},
                  headers=HEADERS)
check("HTTP 400 returned",       r.status_code == 400,        str(r.status_code))
check("Error message present",   "error" in r.json(),         str(r.json()))

# ------------------------------------------------------------------ #
# PART 4: Merchant not found
# ------------------------------------------------------------------ #
section("4. Merchant not found")

r, _ = payout(merchant_id=99999, amount_paise=1000)
check("HTTP 404 returned",       r.status_code == 404,        str(r.status_code))

# ------------------------------------------------------------------ #
# PART 5: Insufficient balance
# ------------------------------------------------------------------ #
section("5. Insufficient balance")

r, _ = payout(merchant_id=1, amount_paise=999_999_999)
check("HTTP 400 returned",       r.status_code == 400,        str(r.status_code))
check("Insufficient balance msg","Insufficient" in r.json().get("error", ""), str(r.json()))

# ------------------------------------------------------------------ #
# PART 6: Invalid amount
# ------------------------------------------------------------------ #
section("6. Invalid amount (zero and negative)")

r, _ = payout(merchant_id=1, amount_paise=0)
check("Zero amount → 400",       r.status_code == 400,        str(r.status_code))

r, _ = payout(merchant_id=1, amount_paise=-500)
check("Negative amount → 400",   r.status_code == 400,        str(r.status_code))

# ------------------------------------------------------------------ #
# PART 7: Concurrency — two simultaneous requests, same merchant
# ------------------------------------------------------------------ #
section("7. Concurrency — two requests draining balance")

import threading

results = []

def fire(amount):
    r, _ = payout(merchant_id=2, amount_paise=amount)
    results.append(r.status_code)

# Merchant B has 20000 paise; fire two requests of 15000 each
t1 = threading.Thread(target=fire, args=(15000,))
t2 = threading.Thread(target=fire, args=(15000,))
t1.start(); t2.start()
t1.join();  t2.join()

results.sort()
check("One 201 and one 400",
      results == [400, 201] or results == [201, 400],
      str(results))

print("\n" + "="*55)
print("  Done. Check Celery worker logs for task outcomes.")
print("="*55 + "\n")
