from django.db import models


class Merchant(models.Model):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name


class LedgerEntry(models.Model):
    CREDIT = "credit"
    DEBIT = "debit"
    TYPE_CHOICES = [(CREDIT, "Credit"), (DEBIT, "Debit")]

    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name="ledger_entries")
    amount = models.BigIntegerField(db_index=True)
    type = models.CharField(max_length=6, choices=TYPE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['merchant', 'type']),
        ]

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

    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name="payouts")
    amount = models.BigIntegerField(db_index=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    retry_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['merchant', 'status']),
        ]

    def __str__(self):
        return f"Payout {self.id} - {self.status} - {self.amount} paise for {self.merchant}"


class IdempotencyKey(models.Model):
    key = models.CharField(max_length=255)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name="idempotency_keys")
    response = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('key', 'merchant')

    def __str__(self):
        return f"{self.key} ({self.merchant})"