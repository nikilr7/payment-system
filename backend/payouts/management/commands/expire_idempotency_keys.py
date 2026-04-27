from django.core.management.base import BaseCommand
from django.utils import timezone
from payouts.models import IdempotencyKey


class Command(BaseCommand):
    help = "Delete expired idempotency keys (older than their expires_at timestamp)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print count of keys to be deleted without deleting them.",
        )

    def handle(self, *args, **options):
        expired = IdempotencyKey.objects.filter(expires_at__lt=timezone.now())
        count   = expired.count()

        if options["dry-run"]:
            self.stdout.write(f"[dry-run] {count} expired idempotency key(s) would be deleted.")
            return

        expired.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} expired idempotency key(s)."))
