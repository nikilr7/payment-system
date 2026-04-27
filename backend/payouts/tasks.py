import logging
import random

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import LedgerEntry, Payout

logger = logging.getLogger(__name__)

# Payout is considered stuck if processing for longer than this
STUCK_THRESHOLD_SECONDS = 30


def _refund(payout):
    """Create a credit ledger entry to reverse a failed payout. Must be called inside a transaction."""
    LedgerEntry.objects.create(
        merchant=payout.merchant,
        amount=payout.amount,
        type=LedgerEntry.CREDIT,
    )
    logger.info("Refund issued for payout_id=%s amount=%s paise", payout.id, payout.amount)


def _fail_and_refund(payout):
    """Transition payout to failed and issue refund atomically."""
    payout.transition_to(Payout.FAILED)
    payout.save(update_fields=["status", "updated_at"])
    _refund(payout)


@shared_task(bind=True, max_retries=3)
def process_payout(self, payout_id):
    logger.info("process_payout started for payout_id=%s (attempt=%s)", payout_id, self.request.retries + 1)

    # ── STEP 1: Transition pending → processing ──────────────────────────
    with transaction.atomic():
        try:
            payout = Payout.objects.select_for_update().get(id=payout_id)
        except Payout.DoesNotExist:
            logger.error("Payout %s not found — aborting task", payout_id)
            return

        # On a retry the payout is already in processing — check if it's been
        # stuck too long before allowing another attempt
        if payout.status == Payout.PROCESSING:
            elapsed = (timezone.now() - payout.updated_at).total_seconds()
            if elapsed < STUCK_THRESHOLD_SECONDS and self.request.retries == 0:
                logger.warning("Payout %s already processing and not yet stuck — skipping", payout_id)
                return

            if payout.retry_count >= 3:
                logger.warning("Payout %s exceeded max retries — marking failed", payout_id)
                _fail_and_refund(payout)
                return

        elif payout.status != Payout.PENDING:
            logger.info("Payout %s is in terminal state %s — skipping", payout_id, payout.status)
            return

        payout.transition_to(Payout.PROCESSING)
        payout.save(update_fields=["status", "updated_at"])

    # ── STEP 2: Simulate bank call (outside transaction — no lock held) ───
    outcome = random.random()
    logger.info("Payout %s bank outcome=%.4f", payout_id, outcome)

    # ── STEP 3: Apply result in a fresh transaction ───────────────────────
    with transaction.atomic():
        payout = Payout.objects.select_for_update().get(id=payout_id)

        if payout.status != Payout.PROCESSING:
            # Another process already resolved this payout
            logger.warning("Payout %s status changed to %s externally — skipping", payout_id, payout.status)
            return

        if outcome < 0.70:  # 70% success
            payout.transition_to(Payout.COMPLETED)
            payout.save(update_fields=["status", "updated_at"])
            logger.info("Payout %s completed successfully", payout_id)

        elif outcome < 0.90:  # 20% failure
            _fail_and_refund(payout)
            logger.info("Payout %s failed — refund issued", payout_id)

        else:  # 10% stuck — schedule retry with exponential backoff
            payout.retry_count += 1
            payout.save(update_fields=["retry_count", "updated_at"])
            backoff = 60 * (2 ** (payout.retry_count - 1))  # 60s, 120s, 240s
            logger.warning("Payout %s stuck — retry %s in %ss", payout_id, payout.retry_count, backoff)
            raise self.retry(countdown=backoff)
