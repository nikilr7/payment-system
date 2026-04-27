"""
post_test_verify.py — Deep integrity checks after stress/load testing.

Run with:
    cd backend
    venv\\Scripts\\python.exe manage.py shell < post_test_verify.py
"""

from django.db.models import Sum, Count, Q
from payouts.models import Merchant, LedgerEntry, Payout, IdempotencyKey


def section(title):
    print(f"\n{'=' * 60}\n  {title}\n{'=' * 60}")


PASS = "  [PASS]"
FAIL = "  [FAIL]"


# ── 1. Balance integrity per merchant ─────────────────────────────────────────
section("1. Balance Integrity (credits - debits >= 0)")

for m in Merchant.objects.all():
    credits = (
        LedgerEntry.objects.filter(merchant=m, type=LedgerEntry.CREDIT)
        .aggregate(t=Sum("amount"))["t"] or 0
    )
    debits = (
        LedgerEntry.objects.filter(merchant=m, type=LedgerEntry.DEBIT)
        .aggregate(t=Sum("amount"))["t"] or 0
    )
    held = (
        Payout.objects.filter(merchant=m, status__in=[Payout.PENDING, Payout.PROCESSING])
        .aggregate(t=Sum("amount"))["t"] or 0
    )
    balance   = credits - debits
    available = balance - held
    ok = available >= 0
    print(
        f"  {'OK' if ok else 'FAIL':4}  {m.name:30} "
        f"balance={balance:>10}  held={held:>10}  available={available:>10}"
    )
    if not ok:
        print(f"{FAIL}  {m.name} has NEGATIVE available balance!")


# ── 2. Duplicate payout detection ─────────────────────────────────────────────
section("2. Duplicate Payout Detection")

dupes = (
    Payout.objects
    .values("merchant_id", "amount", "status")
    .annotate(c=Count("id"))
    .filter(c__gt=1, status=Payout.PENDING)
)
if dupes.exists():
    print(f"{FAIL}  Duplicate PENDING payouts found:")
    for d in dupes:
        print(f"        {d}")
else:
    print(f"{PASS}  No duplicate pending payouts")


# ── 3. Failed payouts without refund ──────────────────────────────────────────
section("3. Failed Payouts Without Refund Credit")

missing_refunds = []
for p in Payout.objects.filter(status=Payout.FAILED).select_related("merchant"):
    has_refund = LedgerEntry.objects.filter(
        merchant=p.merchant,
        type=LedgerEntry.CREDIT,
        amount=p.amount,
    ).exists()
    if not has_refund:
        missing_refunds.append(p.id)

if missing_refunds:
    print(f"{FAIL}  Payout IDs missing refund: {missing_refunds}")
else:
    print(f"{PASS}  All failed payouts have a credit refund entry")


# ── 4. Stuck payouts ──────────────────────────────────────────────────────────
section("4. Payouts Stuck in 'processing'")

from django.utils import timezone
from datetime import timedelta

stuck = Payout.objects.filter(
    status=Payout.PROCESSING,
    updated_at__lt=timezone.now() - timedelta(minutes=5),
)
if stuck.exists():
    print(f"{FAIL}  {stuck.count()} payout(s) stuck in processing > 5 min:")
    for p in stuck:
        print(f"        id={p.id}  retry_count={p.retry_count}  updated={p.updated_at}")
else:
    print(f"{PASS}  No payouts stuck in processing")


# ── 5. Idempotency key integrity ──────────────────────────────────────────────
section("5. Idempotency Key Integrity")

total_keys    = IdempotencyKey.objects.count()
total_payouts = Payout.objects.count()
print(f"  Idempotency keys : {total_keys}")
print(f"  Total payouts    : {total_payouts}")
if total_keys >= total_payouts:
    print(f"{PASS}  Key count >= payout count (expected)")
else:
    print(f"{FAIL}  Fewer idempotency keys than payouts — possible duplicate payouts")


# ── 6. Payout status breakdown ────────────────────────────────────────────────
section("6. Payout Status Breakdown")

for row in Payout.objects.values("status").annotate(c=Count("id")).order_by("status"):
    print(f"  {row['status']:12} : {row['c']:>6}")


# ── 7. Ledger entry breakdown ─────────────────────────────────────────────────
section("7. Ledger Entry Breakdown")

for row in (
    LedgerEntry.objects
    .values("merchant__name", "type")
    .annotate(count=Count("id"), total=Sum("amount"))
    .order_by("merchant__name", "type")
):
    print(
        f"  {row['merchant__name']:30} {row['type']:6} "
        f"count={row['count']:>5}  total={row['total']:>12} paise"
    )


# ── Summary ───────────────────────────────────────────────────────────────────
section("Summary")
print("  Run complete. Review any [FAIL] lines above.")
