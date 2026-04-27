from django.db import models


class Merchant(models.Model):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name


class LedgerEntry(models.Model):
    CREDIT = "credit"
    DEBIT = "debit"
    TYPE_CHOICES = [(CREDIT, "Credit"), (DEBIT, "Debit")]

    merchant = models.ForeignKey(Merchant, on_delete=models.PROTECT, related_name="ledger_entries")
    amount = models.BigIntegerField()  # paise only, never float
    type = models.CharField(max_length=6, choices=TYPE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["merchant", "type"])]

    def __str__(self):
        return f"{self.type} of {self.amount} paise for {self.merchant}"


class Payout(models.Model):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (PROCESSING, "Processing"),
        (COMPLETED, "Completed"),
        (FAILED, "Failed"),
    ]

    # Valid state transitions — terminal states have no outgoing edges
    VALID_TRANSITIONS = {
        PENDING: {PROCESSING},
        PROCESSING: {COMPLETED, FAILED},
        COMPLETED: set(),
        FAILED: set(),
    }

    merchant = models.ForeignKey(Merchant, on_delete=models.PROTECT, related_name="payouts")
    amount = models.BigIntegerField()  # paise only, never float
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    retry_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)  # used for stuck-payout detection

    class Meta:
        indexes = [models.Index(fields=["merchant", "status"])]

    def transition_to(self, new_status):
        """Enforce valid state transitions. Raises ValueError on invalid move."""
        if new_status not in self.VALID_TRANSITIONS[self.status]:
            raise ValueError(
                f"Invalid transition: {self.status} → {new_status}"
            )
        self.status = new_status

    def __str__(self):
        return f"Payout {self.id} [{self.status}] {self.amount} paise — {self.merchant}"


class IdempotencyKey(models.Model):
    key = models.CharField(max_length=255)
    merchant = models.ForeignKey(Merchant, on_delete=models.PROTECT, related_name="idempotency_keys")
    response = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("key", "merchant")

    def __str__(self):
        return f"{self.key} ({self.merchant})"
