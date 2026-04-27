# Payout Engine — System Design Explainer

---

## 1. Ledger Design

All money is stored as **paise (integer)** using `BigIntegerField`. There is no balance column on the Merchant model. Balance is always derived on-demand:

```
balance = SUM(credits) - SUM(debits)
```

This is the **double-entry bookkeeping** pattern. Every financial event — a top-up, a payout hold, a refund — creates an immutable `LedgerEntry` row. The ledger is append-only and never updated.

**Why this matters:**
- No risk of a cached balance field going out of sync
- Full audit trail of every rupee movement
- Balance at any point in time can be reconstructed from the ledger alone

**Three balance concepts:**
| Concept | Formula |
|---|---|
| `get_balance` | credits − debits |
| `get_held_balance` | sum of pending + processing payout amounts |
| `get_available_balance` | balance − held_balance |

A payout debit is created at request time (holds the funds). If the payout fails, a credit entry is created to reverse it.

---

## 2. Concurrency Lock

The critical section is: **check balance → create payout → debit ledger**. These three steps must be atomic and exclusive per merchant.

```python
with transaction.atomic():
    merchant = Merchant.objects.select_for_update().get(id=merchant_id)
    available = get_available_balance(merchant)   # reads live ledger
    # ... create payout + debit
```

`SELECT FOR UPDATE` acquires a **row-level exclusive lock** on the merchant row in PostgreSQL. Any concurrent transaction that tries to lock the same merchant row will block until the first transaction commits or rolls back.

**What this prevents:**
- Thread A reads balance = 10,000, Thread B reads balance = 10,000
- Both see sufficient funds and both create payouts for 8,000
- Result without lock: balance goes to −6,000 (double spend)
- Result with lock: Thread B blocks, then reads balance = 2,000 and is rejected

The lock is held only for the duration of the DB writes — the Celery `.delay()` call happens after the `with` block so the lock is never held during network I/O.

---

## 3. Idempotency Design

Every payout request must include an `Idempotency-Key` header. The key is scoped per merchant via a `unique_together` constraint on `(key, merchant)`.

**Flow:**
1. Check if `IdempotencyKey(key, merchant)` exists
2. If yes → return stored response immediately (no new payout)
3. If no → proceed, create payout, store response in `IdempotencyKey.response`

**Key design decisions:**
- The idempotency record is created **inside the same transaction** as the payout and ledger entry — they commit together or not at all
- The stored response is the exact JSON returned to the client, so replays return byte-for-byte identical responses
- If two requests with the same key race simultaneously, the `unique_together` constraint causes one to raise `IntegrityError`, which is caught and resolved by reading the winning record

**Bug fixed:** The original implementation used `get_or_create` with `defaults={"response": {}}` and saved the response in a second `.save()` call. This meant a failed balance check would still commit an empty `IdempotencyKey` record, permanently blocking future valid requests with the same key. The fix: only create the `IdempotencyKey` after the payout is successfully created.

---

## 4. State Machine Enforcement

Valid transitions are declared on the model itself:

```python
VALID_TRANSITIONS = {
    PENDING:    {PROCESSING},
    PROCESSING: {COMPLETED, FAILED},
    COMPLETED:  set(),   # terminal
    FAILED:     set(),   # terminal
}
```

The `transition_to(new_status)` method enforces this at the application layer:

```python
def transition_to(self, new_status):
    if new_status not in self.VALID_TRANSITIONS[self.status]:
        raise ValueError(f"Invalid transition: {self.status} → {new_status}")
    self.status = new_status
```

Every status change in `tasks.py` goes through `transition_to()` — no direct assignment to `payout.status`. This means:
- A completed payout can never be moved back to processing
- A failed payout can never be marked completed
- The Celery task checks the current status before acting, so a payout that was already resolved externally is silently skipped

---

## 5. Real Bug Fixed — Race Condition in Idempotency Key Creation

**The bug:** The original `views.py` used:

```python
idem_obj, created = IdempotencyKey.objects.get_or_create(
    key=idempotency_key,
    merchant=merchant,
    defaults={"response": {}},
)
if not created:
    return Response(idem_obj.response, ...)

# ... balance check, payout creation ...

idem_obj.response = response_data
idem_obj.save()
```

**The problem:** If the balance check failed and returned a 400, the transaction rolled back — but `get_or_create` had already inserted the `IdempotencyKey` row with `response={}`. On rollback, the row disappears. So far so good.

But if the balance check passed and then an exception occurred *after* `idem_obj.save()` but *before* the transaction committed (e.g., a DB error on the payout insert), the idempotency key would be rolled back too — correct.

The real issue was subtler: **a client retrying after a timeout** would get back `{}` (empty response) if the first request's transaction was still in-flight when the retry arrived. The retry would see `created=False` and return the empty stored response as if it were a success.

**The fix:** Use a plain `filter().first()` check instead of `get_or_create`, and only call `IdempotencyKey.objects.create()` as the very last DB write before the transaction commits. This ensures the idempotency record only exists if the payout was fully created.

---

## 6. Retry Logic

Stuck payouts (10% probability) are retried up to 3 times with **exponential backoff**:

| Retry | Countdown |
|---|---|
| 1st | 60s |
| 2nd | 120s |
| 3rd | 240s |

After 3 retries, the payout is marked `failed` and a refund credit entry is created.

A payout is considered "stuck" if it has been in `processing` state for more than 30 seconds (`updated_at` timestamp). This prevents the task from re-processing a payout that another worker is actively handling.

The `updated_at = DateTimeField(auto_now=True)` field on `Payout` is updated on every `.save()`, making it a reliable heartbeat for detecting stuck payouts.
