from django.db.models import Sum

from .models import LedgerEntry, Payout


def get_balance(merchant) -> int:
    entries = LedgerEntry.objects.filter(merchant=merchant)

    credits = entries.filter(type=LedgerEntry.CREDIT).aggregate(total=Sum("amount"))["total"] or 0
    debits  = entries.filter(type=LedgerEntry.DEBIT).aggregate(total=Sum("amount"))["total"] or 0

    return credits - debits


def get_held_balance(merchant) -> int:
    held_statuses = [Payout.PENDING, Payout.PROCESSING]

    return (
        Payout.objects
        .filter(merchant=merchant, status__in=held_statuses)
        .aggregate(total=Sum("amount"))["total"] or 0
    )


def get_available_balance(merchant) -> int:
    return get_balance(merchant) - get_held_balance(merchant)
