import threading
import uuid
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase, Client

from .models import Merchant, LedgerEntry, Payout, IdempotencyKey
from .services import get_balance, get_available_balance
from .tasks import process_payout


def _seed_merchant(name, credit_paise):
    merchant = Merchant.objects.create(name=name)
    LedgerEntry.objects.create(merchant=merchant, amount=credit_paise, type=LedgerEntry.CREDIT)
    return merchant


def _post_payout(client, merchant_id, amount_paise, idempotency_key=None):
    return client.post(
        "/api/v1/payouts",
        data={"merchant_id": merchant_id, "amount_paise": amount_paise},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=idempotency_key or str(uuid.uuid4()),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Idempotency Tests
# ─────────────────────────────────────────────────────────────────────────────

class IdempotencyTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.merchant = _seed_merchant("Merchant A", 50_000)

    def test_same_key_returns_same_response(self):
        key = str(uuid.uuid4())
        r1 = _post_payout(self.client, self.merchant.id, 5_000, key)
        r2 = _post_payout(self.client, self.merchant.id, 5_000, key)

        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.json()["payout_id"], r2.json()["payout_id"])

    def test_same_key_does_not_create_duplicate_payout(self):
        key = str(uuid.uuid4())
        _post_payout(self.client, self.merchant.id, 5_000, key)
        _post_payout(self.client, self.merchant.id, 5_000, key)

        self.assertEqual(Payout.objects.filter(merchant=self.merchant).count(), 1)

    def test_different_keys_create_separate_payouts(self):
        _post_payout(self.client, self.merchant.id, 5_000)
        _post_payout(self.client, self.merchant.id, 5_000)

        self.assertEqual(Payout.objects.filter(merchant=self.merchant).count(), 2)

    def test_missing_idempotency_key_returns_400(self):
        r = self.client.post(
            "/api/v1/payouts",
            data={"merchant_id": self.merchant.id, "amount_paise": 5_000},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)


# ─────────────────────────────────────────────────────────────────────────────
# Concurrency Tests — must use TransactionTestCase so select_for_update works
# and threads can see each other's committed data
# ─────────────────────────────────────────────────────────────────────────────

class ConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.merchant = _seed_merchant("Merchant B", 10_000)

    def test_two_simultaneous_payouts_only_one_succeeds(self):
        """
        Merchant has 10,000 paise. Two threads each try to pay out 8,000.
        Only one should succeed — the other must be rejected with 400.
        """
        merchant_id = self.merchant.id
        results = []
        barrier = threading.Barrier(2)

        def fire():
            client = Client()
            barrier.wait()  # release both threads simultaneously
            r = _post_payout(client, merchant_id, 8_000)
            results.append(r.status_code)

        t1 = threading.Thread(target=fire)
        t2 = threading.Thread(target=fire)
        t1.start(); t2.start()
        t1.join();  t2.join()

        results.sort()
        self.assertEqual(results, [400, 201], f"Expected [400, 201], got {results}")
        self.assertEqual(Payout.objects.filter(merchant_id=merchant_id).count(), 1)

    def test_balance_never_goes_negative(self):
        """After any number of payouts, available balance must be >= 0."""
        merchant_id = self.merchant.id
        for _ in range(5):
            _post_payout(Client(), merchant_id, 3_000)

        self.merchant.refresh_from_db()
        available = get_available_balance(self.merchant)
        self.assertGreaterEqual(available, 0)


# ─────────────────────────────────────────────────────────────────────────────
# Balance / Ledger Tests
# ─────────────────────────────────────────────────────────────────────────────

class LedgerTests(TestCase):
    def setUp(self):
        self.merchant = _seed_merchant("Merchant C", 20_000)

    def test_balance_equals_credits_minus_debits(self):
        LedgerEntry.objects.create(merchant=self.merchant, amount=5_000, type=LedgerEntry.DEBIT)
        self.assertEqual(get_balance(self.merchant), 15_000)

    def test_insufficient_balance_rejected(self):
        r = _post_payout(Client(), self.merchant.id, 999_999_999)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Insufficient", r.json()["error"])


# ─────────────────────────────────────────────────────────────────────────────
# State Machine Tests
# ─────────────────────────────────────────────────────────────────────────────

class StateMachineTests(TestCase):
    def setUp(self):
        self.merchant = _seed_merchant("Merchant D", 50_000)

    def test_invalid_transition_raises(self):
        payout = Payout.objects.create(
            merchant=self.merchant, amount=1_000, status=Payout.COMPLETED
        )
        with self.assertRaises(ValueError):
            payout.transition_to(Payout.PROCESSING)

    def test_valid_transition_succeeds(self):
        payout = Payout.objects.create(
            merchant=self.merchant, amount=1_000, status=Payout.PENDING
        )
        payout.transition_to(Payout.PROCESSING)
        self.assertEqual(payout.status, Payout.PROCESSING)


# ─────────────────────────────────────────────────────────────────────────────
# Celery Task Tests
# ─────────────────────────────────────────────────────────────────────────────

class PayoutTaskTests(TestCase):
    def setUp(self):
        self.merchant = _seed_merchant("Merchant E", 50_000)
        self.payout = Payout.objects.create(
            merchant=self.merchant, amount=5_000, status=Payout.PENDING
        )
        LedgerEntry.objects.create(
            merchant=self.merchant, amount=5_000, type=LedgerEntry.DEBIT
        )

    def test_task_success_marks_completed(self):
        with patch("payouts.tasks.random.random", return_value=0.5):  # 70% success path
            process_payout(self.payout.id)
        self.payout.refresh_from_db()
        self.assertEqual(self.payout.status, Payout.COMPLETED)

    def test_task_failure_marks_failed_and_refunds(self):
        with patch("payouts.tasks.random.random", return_value=0.85):  # 20% failure path
            process_payout(self.payout.id)
        self.payout.refresh_from_db()
        self.assertEqual(self.payout.status, Payout.FAILED)
        refund = LedgerEntry.objects.filter(
            merchant=self.merchant, type=LedgerEntry.CREDIT, amount=5_000
        )
        self.assertTrue(refund.exists(), "Refund credit entry must be created on failure")

    def test_task_skips_non_pending_payout(self):
        self.payout.status = Payout.COMPLETED
        self.payout.save()
        with patch("payouts.tasks.random.random", return_value=0.5):
            process_payout(self.payout.id)
        self.payout.refresh_from_db()
        self.assertEqual(self.payout.status, Payout.COMPLETED)
