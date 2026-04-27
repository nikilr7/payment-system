import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from payouts.models import Merchant, LedgerEntry


def run():
    # Optional reset (for dev only)
    LedgerEntry.objects.all().delete()

    merchant_a, _ = Merchant.objects.get_or_create(name="Merchant A")
    merchant_b, _ = Merchant.objects.get_or_create(name="Merchant B")

    # Merchant A → ₹150
    LedgerEntry.objects.create(merchant=merchant_a, amount=10000, type=LedgerEntry.CREDIT)
    LedgerEntry.objects.create(merchant=merchant_a, amount=5000, type=LedgerEntry.CREDIT)

    # Merchant B → ₹200
    LedgerEntry.objects.create(merchant=merchant_b, amount=20000, type=LedgerEntry.CREDIT)

    print("✅ Seed data created successfully")
    print(f"{merchant_a} balance seeded with 15000 paise")
    print(f"{merchant_b} balance seeded with 20000 paise")


if __name__ == "__main__":
    run()