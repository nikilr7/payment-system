from django.db import models
from django.utils import timezone
from datetime import timedelta

IDEMPOTENCY_KEY_TTL_HOURS = 24


def _default_expiry():
    return timezone.now() + timedelta(hours=IDEMPOTENCY_KEY_TTL_HOURS)


class Merchant(models.Model):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name


class LedgerEntry(models.Model):
    CREDIT = "credit"
    DEBIT  = "debit"
    TYPE_CHOICES = [(CREDIT, "Credit"), (DEBIT, "Debit")]

    merchant   = models.ForeignKey(Merchant, on_delete=models.PROTECT, related_name="ledger_entries")
    amount     = models.BigIntegerField()          # paise only — never float
    type       = models.CharField(max_length=6, choices=TYPE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["merchant", "type"])]

    def __str__(self):
        return f"{self.type} of {self.amount} paise for {self.merchant}"


class Payout(models.Model):
    PENDING    = "pending"
    PROCESSING = "processing"
    COMPLETED  = "completed"
    FAILED     = "failed"

    STATUS_CHOICES = [
        (PENDING,    "Pending"),
        (PROCESSING, "Processing"),
        (COMPLETED,  "Completed"),
        (FAILED,     "Failed"),
    ]

    # Terminal states have no outgoing edges — enforced by transition_to()
    VALID_TRANSITIONS = {
        PENDING:    {PROCESSING},
        PROCESSING: {COMPLETED, FAILED},
        COMPLETED:  set(),
        FAILED:     set(),
    }

    merchant    = models.ForeignKey(Merchant, on_delete=models.PROTECT, related_name="payouts")
    amount      = models.BigIntegerField()         # paise only — never float
    status      = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    retry_count = models.PositiveIntegerField(default=0)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)  # heartbeat for stuck-payout detection

    class Meta:
        indexes = [models.Index(fields=["merchant", "status"])]

    def transition_to(self, new_status: str):
        """Enforce valid state transitions. Raises ValueError on invalid move."""
        if new_status not in self.VALID_TRANSITIONS[self.status]:
            raise ValueError(f"Invalid transition: {self.status} → {new_status}")
        self.status = new_status

    def __str__(self):
        return f"Payout {self.id} [{self.status}] {self.amount} paise — {self.merchant}"


class IdempotencyKey(models.Model):
    key          = models.CharField(max_length=255)
    merchant     = models.ForeignKey(Merchant, on_delete=models.PROTECT, related_name="idempotency_keys")
    request_hash = models.CharField(max_length=64)   # SHA-256 of canonical request payload
    response     = models.JSONField()
    created_at   = models.DateTimeField(auto_now_add=True)
    expires_at   = models.DateTimeField(default=_default_expiry)  # set to now + 24h on insert

    class Meta:
        unique_together = ("key", "merchant")
        indexes = [models.Index(fields=["expires_at"])]  # for efficient cleanup queries

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"{self.key} ({self.merchant})"
