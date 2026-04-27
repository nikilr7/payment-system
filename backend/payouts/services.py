import hashlib
import json

from django.db.models import Sum

from .models import LedgerEntry, Payout


# ── Balance helpers ───────────────────────────────────────────────────────────

def get_balance(merchant) -> int:
    entries = LedgerEntry.objects.filter(merchant=merchant)
    credits = entries.filter(type=LedgerEntry.CREDIT).aggregate(t=Sum("amount"))["t"] or 0
    debits  = entries.filter(type=LedgerEntry.DEBIT).aggregate(t=Sum("amount"))["t"] or 0
    return credits - debits


def get_held_balance(merchant) -> int:
    return (
        Payout.objects
        .filter(merchant=merchant, status__in=[Payout.PENDING, Payout.PROCESSING])
        .aggregate(t=Sum("amount"))["t"] or 0
    )


def get_available_balance(merchant) -> int:
    return get_balance(merchant) - get_held_balance(merchant)


def assert_sufficient_balance(merchant, amount_paise: int):
    """
    Hard invariant check — raises ValueError if the debit would make
    available balance negative. Call this inside a select_for_update transaction
    so the read is consistent with the subsequent write.
    """
    available = get_available_balance(merchant)
    if available < amount_paise:
        raise ValueError(
            f"Insufficient balance: available={available} requested={amount_paise}"
        )
    return available


# ── Idempotency helpers ───────────────────────────────────────────────────────

def hash_request(merchant_id: int, amount_paise: int) -> str:
    """
    Produce a stable SHA-256 fingerprint of the request payload.
    Used to detect key reuse with a different payload — which must be rejected.
    Keys are sorted to ensure dict ordering never affects the hash.
    """
    canonical = json.dumps(
        {"merchant_id": merchant_id, "amount_paise": amount_paise},
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
