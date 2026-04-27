# Playto Payout Engine

A production-grade payout system handling international payments for Indian agencies and freelancers. Built with Django + DRF backend, React frontend, and PostgreSQL.

## Architecture Overview

**Stack:**
- **Backend:** Django 5.0 + Django REST Framework
- **Frontend:** React 18 + TypeScript + Tailwind CSS + Vite
- **Database:** PostgreSQL (strongly preferred; SQLite for dev only)
- **Background Jobs:** Celery + Redis
- **Testing:** Django TestCase + pytest

## Key Features

✅ **Double-Entry Ledger** — All balance calculations are append-only, auditable, and timestamped  
✅ **Concurrency Safe** — Row-level locking prevents race conditions on balance checks  
✅ **Idempotent API** — Duplicate requests return identical responses; safe retries  
✅ **State Machine** — Strict enforcement of valid payout status transitions  
✅ **Automatic Retries** — Exponential backoff for stuck payouts (60s → 120s → 240s)  
✅ **Comprehensive Tests** — Unit tests + concurrency tests + idempotency tests  

## Quick Start

### Backend Setup

```bash
# Navigate to backend directory
cd backend

# Create Python virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create database (PostgreSQL recommended)
# Set DATABASE_URL in .env or config/settings.py
# Example: DATABASE_URL=postgres://user:password@localhost/payout_db

# Run migrations
python manage.py migrate

# Seed test data
python seed.py

# Start Redis (required for Celery)
redis-server

# Start Celery worker (in another terminal)
celery -A config worker -l info

# Run development server (in another terminal)
python manage.py runserver
```

The backend API is now available at `http://localhost:8000/api/v1/`

### Frontend Setup

```bash
# Navigate to frontend directory
cd frontend/frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

The frontend is available at `http://localhost:5173/`

## API Endpoints

### Merchant Management

**List/Create Merchants:**
```bash
GET  /api/v1/merchants
POST /api/v1/merchants
```

**Get Merchant Details:**
```bash
GET /api/v1/merchants/{merchant_id}
```

**Top-up Merchant Balance:**
```bash
POST /api/v1/merchants/{merchant_id}/topup
Body: { "amount_paise": 50000 }
```

### Payouts

**Create Payout Request:**
```bash
POST /api/v1/payouts
Headers:
  - Idempotency-Key: <uuid>
  - Content-Type: application/json
Body: {
  "merchant_id": 1,
  "amount_paise": 10000
}

Response (201 Created):
{
  "payout_id": 42,
  "status": "pending"
}
```

**Key Rules:**
- `Idempotency-Key` header is **required** — each unique key creates one payout max
- Amount must be in **paise** (100 paise = 1 rupee)
- Merchant must have sufficient available balance
- Payout status progresses: `pending` → `processing` → `completed` or `failed`

## Testing

```bash
cd backend

# Run all tests
python manage.py test

# Run with coverage
coverage run --source='.' manage.py test
coverage report

# Run specific test class
python manage.py test payouts.tests.ConcurrencyTests

# Run stress test (Locust)
locust -f locustfile.py --host=http://localhost:8000
```

## Project Structure

```
backend/
├── config/              # Django settings & ASGI/WSGI
│   ├── settings.py
│   ├── celery.py
│   └── urls.py
├── payouts/
│   ├── models.py       # Merchant, Payout, LedgerEntry, IdempotencyKey
│   ├── services.py     # Balance helpers, hash functions
│   ├── views.py        # API endpoints
│   ├── tasks.py        # Celery background tasks
│   ├── tests.py        # Unit + concurrency + idempotency tests
│   ├── seed.py         # Seed data script
│   └── management/
│       └── commands/
│           └── expire_idempotency_keys.py
├── manage.py
└── requirements.txt

frontend/
└── frontend/           # Vite + React app
    ├── src/
    │   ├── App.tsx
    │   ├── main.tsx
    │   └── components/
    ├── public/
    ├── vite.config.ts
    └── package.json

EXPLAINER.md           # Detailed design walkthrough (5 key concepts + AI audit)
```

## System Design Highlights

See **[EXPLAINER.md](./EXPLAINER.md)** for deep dives into:

1. **The Ledger** — Double-entry bookkeeping prevents balance inconsistency
2. **The Lock** — `SELECT FOR UPDATE` eliminates race conditions
3. **The Idempotency** — Cryptographic request deduplication
4. **The State Machine** — Strict transition validation
5. **Real Bug We Fixed** — A race condition in idempotency key creation
6. **🤖 AI Audit** — Example of a subtle payment bug AI suggested (and we caught)

## Deployment

### Docker

```bash
# Build and run with docker-compose
docker-compose up --build

# Services:
# - Django API: http://localhost:8000
# - React Frontend: http://localhost:3000
# - PostgreSQL: localhost:5432
# - Redis: localhost:6379
# - Celery worker: background job processing
```

### Railway / Render / Fly.io

1. Set environment variables:
   ```
   DEBUG=False
   SECRET_KEY=<random-secure-key>
   DATABASE_URL=postgresql://...
   REDIS_URL=redis://...
   ALLOWED_HOSTS=yourdomain.com
   ```

2. Run migrations on deploy:
   ```
   python manage.py migrate
   ```

3. Collect static files:
   ```
   python manage.py collectstatic --noinput
   ```

4. Start Celery worker as a background service

## Development Workflow

### Adding a New Feature

1. Write tests first (TDD)
2. Implement feature in `models.py` / `services.py` / `views.py`
3. Run tests locally: `python manage.py test`
4. Update EXPLAINER.md if architectural
5. Commit with clear message

### Debugging Payouts

```python
# Django shell
python manage.py shell

from payouts.models import Merchant, Payout, LedgerEntry
from payouts.services import get_balance, get_available_balance

merchant = Merchant.objects.get(id=1)
get_balance(merchant)           # Available + held
get_available_balance(merchant) # Available only
Payout.objects.filter(merchant=merchant).values_list('status').distinct()
```

## Performance Considerations

- **Balance queries:** Indexed on `(merchant, type)` for O(1) lookups
- **Payout filtering:** Indexed on `(merchant, status)` for fast stuck-payout detection
- **Idempotency expiry:** Indexed on `expires_at` for efficient cleanup
- **Database:** Use PostgreSQL + connection pooling (pgBouncer) in production
- **Celery:** Scale workers horizontally; monitor task queue depth

## Monitoring & Alerting

Key metrics to track:

- **Payout success rate** — Should be ~70% (by design)
- **Average payout latency** — Typically < 5 minutes (end-to-end)
- **Stuck payout count** — Should be near zero after retries
- **Database lock contention** — Monitor `SELECT FOR UPDATE` wait times
- **Idempotency cache hit rate** — Indicates client retry patterns

## Troubleshooting

**"Insufficient balance" errors are too frequent:**
- Check that `held_balance` calculation is not double-counting pending payouts
- Verify ledger entries aren't duplicated

**Payouts stuck in "processing":**
- Check Celery worker is running: `celery -A config inspect active`
- Review logs for task exceptions
- Manually inspect payout row: `SELECT * FROM payouts_payout WHERE id=<id>;`

**IntegrityError on IdempotencyKey creation:**
- This is expected and handled — two concurrent requests with same key
- Check logs for warning: "Duplicate request detected" and idempotency replay

**Database locked errors:**
- PostgreSQL lock timeout (default 30s)
- Increase `DEFAULT_AUTO_FIELD` transaction timeout if many concurrent payouts
- Scale read replicas for balance queries (read-only)

