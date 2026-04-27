"""
Django shell validation queries.
Run with: venv\Scripts\python.exe manage.py shell < shell_checks.py
"""

from payouts.models import Merchant, LedgerEntry, Payout, IdempotencyKey
from payouts.services import get_balance, get_held_balance, get_available_balance
from django.db.models import Count


def section(title):
    print(f"\n{'='*55}\n  {title}\n{'='*55}")


# ------------------------------------------------------------------ #
# Payout status breakdown
# ------------------------------------------------------------------ #
section("Payout status counts")
for row in Payout.objects.values("status").annotate(count=Count("id")).order_by("status"):
    print(f"  {row['status']:12} → {row['count']}")

# ------------------------------------------------------------------ #
# Ledger entry breakdown per merchant
# ------------------------------------------------------------------ #
section("Ledger entries per merchant/type")
for row in (LedgerEntry.objects
            .values("merchant__name", "type")
            .annotate(count=Count("id"))
            .order_by("merchant__name", "type")):
    print(f"  {row['merchant__name']:20} {row['type']:6} → {row['count']} entries")

# ------------------------------------------------------------------ #
# Balance per merchant
# ------------------------------------------------------------------ #
section("Balance per merchant (paise)")
for m in Merchant.objects.all():
    total     = get_balance(m)
    held      = get_held_balance(m)
    available = get_available_balance(m)
    print(f"  {m.name:20} total={total:>10}  held={held:>10}  available={available:>10}")

# ------------------------------------------------------------------ #
# Duplicate payout detection
# ------------------------------------------------------------------ #
section("Duplicate payout check (same merchant + amount + status=pending)")
dupes = (Payout.objects
         .values("merchant_id", "amount", "status")
         .annotate(count=Count("id"))
         .filter(count__gt=1, status=Payout.PENDING))
if dupes.exists():
    print("  WARNING: Duplicate pending payouts found:")
    for d in dupes:
        print(f"    {d}")
else:
    print("  OK — no duplicate pending payouts")

# ------------------------------------------------------------------ #
# Failed payouts missing refund
# ------------------------------------------------------------------ #
section("Failed payouts without a matching credit refund")
failed_ids = Payout.objects.filter(status=Payout.FAILED).values_list("id", "merchant_id", "amount")
missing = []
for payout_id, merchant_id, amount in failed_ids:
    has_refund = LedgerEntry.objects.filter(
        merchant_id=merchant_id,
        amount=amount,
        type=LedgerEntry.CREDIT,
    ).exists()
    if not has_refund:
        missing.append(payout_id)

if missing:
    print(f"  WARNING: Payout IDs missing refund credit: {missing}")
else:
    print("  OK — all failed payouts have a credit refund entry")

# ------------------------------------------------------------------ #
# Idempotency key count
# ------------------------------------------------------------------ #
section("Idempotency keys")
print(f"  Total stored: {IdempotencyKey.objects.count()}")

# ------------------------------------------------------------------ #
# Payouts stuck in processing
# ------------------------------------------------------------------ #
section("Payouts stuck in 'processing'")
stuck = Payout.objects.filter(status=Payout.PROCESSING)
if stuck.exists():
    for p in stuck:
        print(f"  Payout {p.id} — retry_count={p.retry_count} — {p.amount} paise — {p.merchant}")
else:
    print("  OK — no payouts stuck in processing")
