import logging
import random

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import LedgerEntry, Payout

logger = logging.getLogger(__name__)

STUCK_THRESHOLD_SECONDS = 30


def _has_refund(payout) -> bool:
    """Check if a credit refund entry already exists for this payout amount and merchant."""
    return LedgerEntry.objects.filter(
        merchant=payout.merchant,
        amount=payout.amount,
        type=LedgerEntry.CREDIT,
    ).exists()


def _refund(payout):
    """
    Issue a credit refund. Guard against double-refund by checking first.
    Must be called inside a transaction with the payout row locked.
    """
    if _has_refund(payout):
        logger.warning(
            "Refund already exists for payout_id=%s — skipping duplicate refund", payout.id
        )
        return
    LedgerEntry.objects.create(
        merchant=payout.merchant,
        amount=payout.amount,
        type=LedgerEntry.CREDIT,
    )
    logger.info(
        "Refund issued: payout_id=%s merchant_id=%s amount=%s paise",
        payout.id, payout.merchant_id, payout.amount,
    )


def _fail_and_refund(payout):
    """Transition payout to failed and issue refund atomically."""
    payout.transition_to(Payout.FAILED)
    payout.save(update_fields=["status", "updated_at"])
    _refund(payout)
    logger.info(
        "Payout failed: payout_id=%s merchant_id=%s amount=%s",
        payout.id, payout.merchant_id, payout.amount,
    )


@shared_task(bind=True, max_retries=3)
def process_payout(self, payout_id):
    logger.info(
        "process_payout started: payout_id=%s attempt=%s",
        payout_id, self.request.retries + 1,
    )

    # ── STEP 1: Transition pending → processing ───────────────────────────────
    with transaction.atomic():
        try:
            payout = Payout.objects.select_for_update().get(id=payout_id)
        except Payout.DoesNotExist:
            logger.error("Payout not found: payout_id=%s — aborting", payout_id)
            return

        if payout.status == Payout.PROCESSING:
            elapsed = (timezone.now() - payout.updated_at).total_seconds()

            # Not yet stuck and this is the first attempt — another worker may be handling it
            if elapsed < STUCK_THRESHOLD_SECONDS and self.request.retries == 0:
                logger.warning(
                    "Payout already processing and not yet stuck: payout_id=%s elapsed=%.1fs — skipping",
                    payout_id, elapsed,
                )
                return

            if payout.retry_count >= 3:
                logger.warning("Payout exceeded max retries: payout_id=%s — marking failed", payout_id)
                _fail_and_refund(payout)
                return

        elif payout.status != Payout.PENDING:
            # Terminal state — task is a duplicate dispatch, safe to discard
            logger.info(
                "Payout already in terminal state: payout_id=%s status=%s — skipping",
                payout_id, payout.status,
            )
            return

        payout.transition_to(Payout.PROCESSING)
        payout.save(update_fields=["status", "updated_at"])
        logger.info("Payout status: payout_id=%s pending → processing", payout_id)

    # ── STEP 2: Simulate bank call — outside transaction, no lock held ────────
    outcome = random.random()
    logger.info("Bank response: payout_id=%s outcome=%.4f", payout_id, outcome)

    # ── STEP 3: Apply result in a fresh transaction ───────────────────────────
    with transaction.atomic():
        payout = Payout.objects.select_for_update().get(id=payout_id)

        # Guard: another worker may have already resolved this payout
        if payout.status != Payout.PROCESSING:
            logger.warning(
                "Payout resolved externally: payout_id=%s status=%s — skipping",
                payout_id, payout.status,
            )
            return

        if outcome < 0.70:      # 70% success
            payout.transition_to(Payout.COMPLETED)
            payout.save(update_fields=["status", "updated_at"])
            logger.info("Payout completed: payout_id=%s merchant_id=%s", payout_id, payout.merchant_id)

        elif outcome < 0.90:    # 20% failure
            _fail_and_refund(payout)

        else:                   # 10% stuck — exponential backoff retry
            payout.retry_count += 1
            payout.save(update_fields=["retry_count", "updated_at"])
            backoff = 60 * (2 ** (payout.retry_count - 1))   # 60s → 120s → 240s
            logger.warning(
                "Payout stuck: payout_id=%s retry=%s backoff=%ss",
                payout_id, payout.retry_count, backoff,
            )
            raise self.retry(countdown=backoff)
