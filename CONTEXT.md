# Universal Payment Web App — Domain Context

## Core Terms

**Billing Engine** (`rafs_billing_engine`)
: Shared multi-tenant billing service (deployed on 81.222.148.65). Owns money + subscription state. API: checkout sessions, subscriptions list, entitlements, webhooks. YooKassa TEST only; live requires owner command.

**Billing Application**
: One per bot/product. Created via admin CLI: `create-application --slug <slug>`. Has scoped API keys.

**Billing Client** (`hermes_billing_sdk`)
: Python SDK wheel built from engine repo. `BillingClient(base_url, api_key)` — every mutating call requires `idempotency_key`.

**Mini App (Web App)**
: Telegram Web App (opens inside Telegram via "Launch Web App" button). Validates `initData` (HMAC with bot token). Knows `user_id` without external login.

**Plan Config** (`bot_template/plans.json`)
: Single source of truth for tariffs. JSON with mtime caching. Fields: `code`, `title`, `period` (`month:1`, `day:7`), `prices` per currency, `recurring` (bool), `recurring_notice` (required if recurring), `features[]`.

**Subscription State (Authority = Billing Engine)**
: Local DB stores only cache + reconcile metadata. On every cabinet open / "I paid" button: `GET /v1/subscriptions?external_user_id=` → update local cache. No webhook required for MVP (reconcile is more reliable).

**Payment Flow**
1. User taps plan → Mini App calls `POST /webapp/api/start-payment` with `initData` + `planCode`
2. Server validates `initData`, creates payment row (pending), calls Billing `POST /v1/checkout/sessions` with `Idempotency-Key=trix-<payment_uid>`
3. Billing returns `confirmation_url` + `checkout_id` + `subscription_id`
4. Server stores provider ref, returns `confirmation_url` to frontend
5. Frontend opens URL in Telegram Web App (YooKassa checkout)
6. User pays → YooKassa redirects back to bot (`return_url`)
7. Frontend polls `POST /webapp/api/payment-status` → server calls Billing `GET /v1/subscriptions` → if active subscription found → activate locally

**Recurring vs One-time**
: Default = one-time (card NOT saved, no auto-renew). `recurring:true` in plan config enables `save_payment_method=true` + `consent.kind=recurring` + shows `recurring_notice` to user. Engine only renews monthly/yearly periods.

## Integrations

**tg_bot_template** gets:
- `bot_template/billing.py` — thin client wrapper (configured → client, None → card disabled)
- `bot_template/plans.py` — plans loader with mtime cache
- `bot_template/webapp.py` — FastAPI router mounted at `/webapp/api`
- `bot_template/plans.json` — config file
- Storage tables: `payments`, `webapp_tasks` (for case execution from Mini App)
- Settings: `billing_api_url`, `billing_api_key`, `billing_verify_tls`, `billing_application_id`, `billing_webhook_secret`, `billing_plan_map`, `billing_plan_version_map`, `billing_offer_version`, `billing_currency`, `initdata_max_age_s`, `miniapp_paywall`

**Non-goals for MVP**
- Webhook handling (reconcile suffices)
- Promo codes (separate wave)
- One-time top-ups (engine supports subscriptions only)
- Admin manual payment confirmation endpoints (keep for support, but not in template)
- Demo mode gating (separate wave)