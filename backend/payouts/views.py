import logging
from django.db import transaction, IntegrityError
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .models import Merchant, LedgerEntry, Payout, IdempotencyKey
from .services import (
    get_balance, get_held_balance, get_available_balance,
    assert_sufficient_balance, hash_request,
)
from .tasks import process_payout

logger = logging.getLogger(__name__)


# ── Merchant APIs ─────────────────────────────────────────────────────────────

@api_view(["GET", "POST"])
def merchant_list(request):
    if request.method == "POST":
        name = request.data.get("name", "").strip()
        if not name:
            return Response({"error": "name is required."}, status=status.HTTP_400_BAD_REQUEST)
        merchant = Merchant.objects.create(name=name)
        logger.info("Merchant created: id=%s name=%s", merchant.id, merchant.name)
        return Response({"merchant_id": merchant.id, "name": merchant.name}, status=status.HTTP_201_CREATED)

    merchants = list(Merchant.objects.order_by("id"))
    return Response([
        {
            "merchant_id":     m.id,
            "name":            m.name,
            "balance_paise":   get_balance(m),
            "held_paise":      get_held_balance(m),
            "available_paise": get_available_balance(m),
        }
        for m in merchants
    ])


@api_view(["GET"])
def merchant_detail(request, merchant_id):
    try:
        merchant = Merchant.objects.get(id=merchant_id)
    except Merchant.DoesNotExist:
        return Response({"error": f"Merchant {merchant_id} not found."}, status=status.HTTP_404_NOT_FOUND)

    return Response({
        "merchant_id":     merchant.id,
        "name":            merchant.name,
        "balance_paise":   get_balance(merchant),
        "held_paise":      get_held_balance(merchant),
        "available_paise": get_available_balance(merchant),
    })


@api_view(["POST"])
def merchant_topup(request, merchant_id):
    amount_paise = request.data.get("amount_paise")
    try:
        amount_paise = int(amount_paise)
    except (TypeError, ValueError):
        return Response({"error": "amount_paise must be an integer."}, status=status.HTTP_400_BAD_REQUEST)

    if amount_paise <= 0:
        return Response({"error": "amount_paise must be a positive integer."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        with transaction.atomic():
            merchant    = Merchant.objects.select_for_update().get(id=merchant_id)
            LedgerEntry.objects.create(merchant=merchant, amount=amount_paise, type=LedgerEntry.CREDIT)
            new_balance = get_balance(merchant)
    except Merchant.DoesNotExist:
        return Response({"error": f"Merchant {merchant_id} not found."}, status=status.HTTP_404_NOT_FOUND)

    logger.info("Topup: merchant_id=%s amount=%s new_balance=%s", merchant_id, amount_paise, new_balance)
    return Response({"merchant_id": merchant.id, "topped_up_paise": amount_paise, "new_balance_paise": new_balance})


# ── Payout API ────────────────────────────────────────────────────────────────

@api_view(["POST"])
def create_payout(request):
    # ── Input validation ──────────────────────────────────────────────────────
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        return Response({"error": "Idempotency-Key header is required."}, status=status.HTTP_400_BAD_REQUEST)

    merchant_id  = request.data.get("merchant_id")
    amount_paise = request.data.get("amount_paise")

    if not merchant_id or not amount_paise:
        return Response({"error": "merchant_id and amount_paise are required."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        amount_paise = int(amount_paise)
    except (TypeError, ValueError):
        return Response({"error": "amount_paise must be an integer."}, status=status.HTTP_400_BAD_REQUEST)

    if amount_paise <= 0:
        return Response({"error": "amount_paise must be a positive integer."}, status=status.HTTP_400_BAD_REQUEST)

    # Compute payload fingerprint before entering the transaction
    payload_hash = hash_request(merchant_id, amount_paise)

    try:
        with transaction.atomic():
            # Lock merchant row — serialises all concurrent payout requests for this merchant
            merchant = Merchant.objects.select_for_update().get(id=merchant_id)

            # ── Idempotency check ─────────────────────────────────────────────
            existing = IdempotencyKey.objects.filter(key=idempotency_key, merchant=merchant).first()

            if existing:
                # Key is expired — treat as a new request
                if existing.is_expired:
                    logger.info(
                        "Idempotency key expired: key=%s merchant_id=%s — processing as new request",
                        idempotency_key, merchant_id,
                    )
                    existing.delete()
                    # Fall through to create a new payout below

                # Key reused with a DIFFERENT payload — hard reject
                elif existing.request_hash != payload_hash:
                    logger.warning(
                        "Idempotency key conflict: key=%s merchant_id=%s "
                        "stored_hash=%s incoming_hash=%s",
                        idempotency_key, merchant_id, existing.request_hash, payload_hash,
                    )
                    return Response(
                        {
                            "error": "Idempotency-Key reused with a different request payload.",
                            "hint":  "Use a new Idempotency-Key for a different request.",
                        },
                        status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    )

                # Valid replay — return cached response immediately
                else:
                    logger.info(
                        "Idempotency replay: key=%s payout_id=%s merchant_id=%s",
                        idempotency_key, existing.response.get("payout_id"), merchant_id,
                    )
                    return Response(existing.response, status=status.HTTP_200_OK)

            # ── Balance invariant check ───────────────────────────────────────
            try:
                assert_sufficient_balance(merchant, amount_paise)
            except ValueError as exc:
                available = get_available_balance(merchant)
                logger.warning(
                    "Insufficient balance: merchant_id=%s available=%s requested=%s",
                    merchant_id, available, amount_paise,
                )
                return Response(
                    {"error": "Insufficient balance.", "available_paise": available, "requested_paise": amount_paise},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # ── Create payout + debit ledger atomically ───────────────────────
            payout = Payout.objects.create(merchant=merchant, amount=amount_paise, status=Payout.PENDING)
            LedgerEntry.objects.create(merchant=merchant, amount=amount_paise, type=LedgerEntry.DEBIT)

            response_data = {"payout_id": payout.id, "status": payout.status}

            # Store idempotency record only after successful payout creation
            IdempotencyKey.objects.create(
                key=idempotency_key,
                merchant=merchant,
                request_hash=payload_hash,
                response=response_data,
            )

            logger.info(
                "Payout created: payout_id=%s merchant_id=%s amount=%s status=%s",
                payout.id, merchant_id, amount_paise, payout.status,
            )

        # Dispatch Celery task AFTER commit — row is guaranteed visible to worker
        process_payout.delay(payout.id)
        return Response(response_data, status=status.HTTP_201_CREATED)

    except Merchant.DoesNotExist:
        return Response({"error": f"Merchant {merchant_id} not found."}, status=status.HTTP_404_NOT_FOUND)

    except IntegrityError:
        # Two concurrent requests with the same key raced — one won, return its response
        existing = IdempotencyKey.objects.filter(key=idempotency_key, merchant_id=merchant_id).first()
        if existing:
            return Response(existing.response, status=status.HTTP_200_OK)
        return Response({"error": "Duplicate request detected."}, status=status.HTTP_409_CONFLICT)

    except Exception:
        logger.exception("Unexpected error in create_payout: merchant_id=%s", merchant_id)
        return Response({"error": "An unexpected error occurred."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
