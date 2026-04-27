import logging
from django.db import transaction, IntegrityError
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .models import Merchant, LedgerEntry, Payout, IdempotencyKey
from .services import get_balance, get_held_balance, get_available_balance
from .tasks import process_payout

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Merchant APIs
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET", "POST"])
def merchant_list(request):
    if request.method == "POST":
        name = request.data.get("name", "").strip()
        if not name:
            return Response(
                {"error": "name is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        merchant = Merchant.objects.create(name=name)
        return Response(
            {"merchant_id": merchant.id, "name": merchant.name},
            status=status.HTTP_201_CREATED,
        )

    merchants = Merchant.objects.order_by("id")
    return Response(
        [{"merchant_id": m.id, "name": m.name} for m in merchants],
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
def merchant_detail(request, merchant_id):
    try:
        merchant = Merchant.objects.get(id=merchant_id)
    except Merchant.DoesNotExist:
        return Response(
            {"error": f"Merchant {merchant_id} not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    return Response({
        "merchant_id": merchant.id,
        "name": merchant.name,
        "balance_paise": get_balance(merchant),
        "held_paise": get_held_balance(merchant),
        "available_paise": get_available_balance(merchant),
    })


@api_view(["POST"])
def merchant_topup(request, merchant_id):
    amount_paise = request.data.get("amount_paise")

    try:
        amount_paise = int(amount_paise)
    except (TypeError, ValueError):
        return Response(
            {"error": "amount_paise must be an integer."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if amount_paise <= 0:
        return Response(
            {"error": "amount_paise must be a positive integer."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        with transaction.atomic():
            merchant = Merchant.objects.select_for_update().get(id=merchant_id)
            LedgerEntry.objects.create(
                merchant=merchant,
                amount=amount_paise,
                type=LedgerEntry.CREDIT,
            )
            new_balance = get_balance(merchant)
    except Merchant.DoesNotExist:
        return Response(
            {"error": f"Merchant {merchant_id} not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    return Response({
        "merchant_id": merchant.id,
        "topped_up_paise": amount_paise,
        "new_balance_paise": new_balance,
    }, status=status.HTTP_200_OK)


@api_view(["POST"])
def create_payout(request):
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        return Response(
            {"error": "Idempotency-Key header is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    merchant_id = request.data.get("merchant_id")
    amount_paise = request.data.get("amount_paise")

    if not merchant_id or not amount_paise:
        return Response(
            {"error": "merchant_id and amount_paise are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        amount_paise = int(amount_paise)
    except (TypeError, ValueError):
        return Response(
            {"error": "amount_paise must be an integer."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if amount_paise <= 0:
        return Response(
            {"error": "amount_paise must be a positive integer."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        with transaction.atomic():
            # Lock merchant row — serialises all concurrent requests for this merchant
            merchant = Merchant.objects.select_for_update().get(id=merchant_id)

            # Return cached response for duplicate keys — no new payout created
            existing = IdempotencyKey.objects.filter(
                key=idempotency_key, merchant=merchant
            ).first()
            if existing:
                return Response(existing.response, status=status.HTTP_200_OK)

            # Balance check against live ledger — never trust a cached field
            available = get_available_balance(merchant)
            if available < amount_paise:
                return Response(
                    {
                        "error": "Insufficient balance.",
                        "available_paise": available,
                        "requested_paise": amount_paise,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Create payout and debit ledger atomically
            payout = Payout.objects.create(
                merchant=merchant,
                amount=amount_paise,
                status=Payout.PENDING,
            )
            LedgerEntry.objects.create(
                merchant=merchant,
                amount=amount_paise,
                type=LedgerEntry.DEBIT,
            )

            response_data = {"payout_id": payout.id, "status": payout.status}

            # Only store idempotency key after successful payout creation
            IdempotencyKey.objects.create(
                key=idempotency_key,
                merchant=merchant,
                response=response_data,
            )

        # Trigger Celery AFTER commit — worker is guaranteed to find the row
        logger.info("Dispatching process_payout task for payout_id=%s", payout.id)
        process_payout.delay(payout.id)
        return Response(response_data, status=status.HTTP_201_CREATED)

    except Merchant.DoesNotExist:
        return Response(
            {"error": f"Merchant {merchant_id} not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    except IntegrityError:
        # Race condition: two requests with same idempotency key hit simultaneously
        existing = IdempotencyKey.objects.filter(
            key=idempotency_key, merchant_id=merchant_id
        ).first()
        if existing:
            return Response(existing.response, status=status.HTTP_200_OK)
        return Response(
            {"error": "Duplicate request detected."},
            status=status.HTTP_409_CONFLICT,
        )
    except Exception:
        logger.exception("Unexpected error in create_payout")
        return Response(
            {"error": "An unexpected error occurred."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
