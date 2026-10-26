"""Mini App (Telegram Web App) aiohttp handlers for tg_bot_template.

This is the aiohttp version of the webapp API, mounted at /webapp/api.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import urllib.parse
from datetime import datetime, timezone
from uuid import uuid4

from aiohttp import web

from bot_template.billing import BillingClient, BillingUnavailable, get_billing_client
from bot_template.config import Settings
from bot_template.period import Period
from bot_template.plans import (
    currency_for,
    deal_view,
    get_plan,
    is_recurring,
    load_plans,
    plan_public,
    proof_view,
    public_plans,
    reviews_view,
)
from bot_template.storage import Store

logger = logging.getLogger(__name__)

# Plans file path
PLANS_FILE = "bot_template/plans.json"


# ── initData validation (Telegram Web App) ──────────────────────────────

def validate_init_data(init_data: str, bot_token: str, max_age_s: int) -> dict | None:
    """Verify initData HMAC signature and freshness. Returns user dict or None."""
    try:
        pairs = dict(urllib.parse.parse_qsl(init_data or "", keep_blank_values=True))
        received_hash = pairs.pop("hash", "")
        if not received_hash:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            return None
        if max_age_s > 0:
            auth_date = int(pairs.get("auth_date", "0") or 0)
            if auth_date <= 0 or time.time() - auth_date > max_age_s:
                return None
        user = json.loads(pairs.get("user") or "{}")
        if not isinstance(user, dict) or not user.get("id"):
            return None
        return user
    except Exception:
        logger.warning("initData validation failed", exc_info=True)
        return None


# ── View helpers ────────────────────────────────────────────────────────

def _subscription_view(tenant: dict, settings: Settings) -> dict:
    billing_until = tenant.get("billing_until")
    days_left = None
    if billing_until:
        try:
            until_dt = datetime.fromisoformat(billing_until.replace("Z", "+00:00"))
            days_left = (until_dt - datetime.now(timezone.utc)).days
        except Exception:
            pass
    paid = days_left is None or days_left >= 0
    return {
        "status": str(tenant.get("status") or "active"),
        "plan_code": tenant.get("plan_code"),
        "billing_until": tenant.get("billing_until"),
        "days_left": days_left,
        "active": days_left is None or days_left >= 0,
        "pro": paid,
    }


def _quota_view(tenant: dict) -> dict:
    return {"used_5h": tenant.get("used_5h"), "limit_5h": tenant.get("limit_5h"),
            "used_week": tenant.get("used_week"), "limit_week": tenant.get("limit_week")}


def _user_view(user: dict) -> dict:
    return {"id": int(user["id"]), "first_name": str(user.get("first_name") or ""),
            "username": user.get("username") or None, "language_code": user.get("language_code") or None}


def _build_checkout_payload(settings: Settings, payment: dict, plan: dict, user: dict) -> dict:
    customer: dict = {"external_user_id": str(payment["tg_user_id"]), "locale": "ru"}
    if payment.get("email"):
        customer["email"] = payment["email"]

    recurring = is_recurring(plan)
    offer_parts = [plan.get("title"), plan.get("tagline")]
    if recurring:
        offer_parts.append(plan.get("recurring_notice"))
    offer_text = " · ".join(str(x) for x in offer_parts if x)

    return {
        "customer": customer,
        "plan_code": settings.billing_plan_map.get(payment["plan_code"], payment["plan_code"]),
        "save_payment_method": recurring,
        "consent": {
            "kind": "recurring" if recurring else "offer",
            "offer_version": settings.billing_offer_version,
            "offer_text": offer_text,
            "accepted_at": payment["created_at"],
            "evidence": {"source": "miniapp-paywall"},
        },
        "return_url": f"https://t.me/{settings.profile.bot_username}" if settings.profile.bot_username else "https://t.me/",
        "metadata": {"payment_uid": payment["uid"], "plan_code": payment["plan_code"]},
    }


async def get_tenant(db_path: str, tg_user_id: int, username: str | None, first_name: str | None) -> dict:
    """Get or create tenant (local user row). Returns tenant dict."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (tg_user_id,)).fetchone()
        now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        if row is None:
            conn.execute(
                "INSERT INTO users(user_id, username, name, first_seen, last_seen, subscribed, reachable) VALUES(?, ?, ?, ?, ?, 1, 1)",
                (tg_user_id, username, first_name, now, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (tg_user_id,)).fetchone()
        else:
            conn.execute(
                "UPDATE users SET last_seen = ?, username = COALESCE(?, username), name = COALESCE(?, name) WHERE user_id = ?",
                (now, username, first_name, tg_user_id),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (tg_user_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


# ── aiohttp handlers ────────────────────────────────────────────────────

async def plans_public(request: web.Request) -> web.Response:
    """GET /webapp/api/plans — public plans for storefront."""
    settings: Settings = request.app["settings"]
    plans = load_plans(PLANS_FILE)
    currency = currency_for(plans, None, settings.billing_currency)
    return web.json_response({"currency": currency, "deal": deal_view(plans),
                              "proof": proof_view(plans), "reviews": reviews_view(plans),
                              "plans": public_plans(plans, currency)})


async def plans_for_user(request: web.Request) -> web.Response:
    """POST /webapp/api/plans — plans with user's currency."""
    settings: Settings = request.app["settings"]
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="invalid JSON")
    init_data = body.get("initData", "")
    user = None
    if init_data:
        user = validate_init_data(init_data, settings.token, settings.initdata_max_age_s)
    currency = currency_for(load_plans(PLANS_FILE), user.get("language_code") if user else None, settings.billing_currency)
    plans = load_plans(PLANS_FILE)
    return web.json_response({"currency": currency, "deal": deal_view(plans),
                              "proof": proof_view(plans), "reviews": reviews_view(plans),
                              "plans": public_plans(plans, currency)})


async def me(request: web.Request) -> web.Response:
    """POST /webapp/api/me — current user profile."""
    settings: Settings = request.app["settings"]
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="invalid JSON")
    init_data = body.get("initData", "")
    if not settings.token:
        raise web.HTTPServiceUnavailable(text="bot token not configured")
    user = validate_init_data(init_data, settings.token, settings.initdata_max_age_s)
    if user is None:
        raise web.HTTPUnauthorized(text="invalid initData")
    tenant = await get_tenant(str(settings.database), int(user["id"]), user.get("username"), user.get("first_name"))
    sub = _subscription_view(tenant, settings)
    return web.json_response({"user": _user_view(user), "subscription": sub, "quota": _quota_view(tenant)})


async def start_payment(request: web.Request) -> web.Response:
    """POST /webapp/api/start-payment — create checkout session."""
    settings: Settings = request.app["settings"]
    store: Store = request.app["store"]
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="invalid JSON")

    init_data = body.get("initData", "")
    plan_code = body.get("planCode")
    provider = body.get("provider", "card")
    email = body.get("email")

    if not settings.token:
        raise web.HTTPServiceUnavailable(text="bot token not configured")
    user = validate_init_data(init_data, settings.token, settings.initdata_max_age_s)
    if user is None:
        raise web.HTTPUnauthorized(text="invalid initData")

    if not plan_code:
        raise web.HTTPBadRequest(text="planCode required")

    billing = get_billing_client(settings)
    if billing is None:
        raise web.HTTPNotImplemented(text="card payments not configured")

    plans = load_plans(PLANS_FILE)
    plan = get_plan(plans, plan_code)
    if plan is None:
        raise web.HTTPNotFound(text="plan not found")

    pub = plan_public(plan, currency_for(plans, user.get("language_code"), settings.billing_currency))
    if pub is None:
        raise web.HTTPNotFound(text="plan not available in your currency")

    # Create payment record
    uid = f"trix-{uuid4().hex[:16]}"
    period = Period.from_plan(plan)
    await store.create_payment(
        uid=uid,
        tg_user_id=int(user["id"]),
        plan_code=plan_code,
        plan_period=period.spec if period else None,
        plan_days=period.nominal_days if period else None,
        provider=provider,
        email=email,
    )

    # Call Billing Engine
    payment_data = {"uid": uid, "tg_user_id": int(user["id"]),
                    "plan_code": plan_code, "email": email,
                    "created_at": datetime.now(timezone.utc).isoformat()}
    payload = _build_checkout_payload(settings, payment_data, plan, user)
    try:
        session = billing.create_checkout_session(payload, idempotency_key=f"trix-{uid}")
    except BillingUnavailable as exc:
        logger.warning("billing unavailable: %s", exc)
        raise web.HTTPNotImplemented(text="card payments temporarily unavailable")
    except Exception as exc:
        logger.error("billing error: %s", exc)
        raise web.HTTPBadGateway(text="billing error")

    checkout_id = str(session.get("checkout_id") or session.get("id") or "").strip()
    pay_url = session.get("confirmation_url")
    subscription_id = str(session.get("subscription_id") or "").strip() or None
    expires_at = str(session.get("expires_at") or "").strip() or None

    if not checkout_id or not pay_url:
        raise web.HTTPBadGateway(text="billing checkout response invalid")

    await store.set_payment_provider_ref(uid, f"billing:{checkout_id}", pay_url=pay_url,
                                         subscription_id=subscription_id, expires_at=expires_at)

    return web.json_response({"paymentId": uid, "confirmationUrl": pay_url, "checkoutId": checkout_id})


async def payment_status(request: web.Request) -> web.Response:
    """POST /webapp/api/payment-status — reconcile payment."""
    settings: Settings = request.app["settings"]
    store: Store = request.app["store"]
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="invalid JSON")

    init_data = body.get("initData", "")
    payment_id = body.get("paymentId")

    if not settings.token:
        raise web.HTTPServiceUnavailable(text="bot token not configured")
    user = validate_init_data(init_data, settings.token, settings.initdata_max_age_s)
    if user is None:
        raise web.HTTPUnauthorized(text="invalid initData")

    if not payment_id:
        raise web.HTTPBadRequest(text="paymentId required")

    payment = await store.get_payment(payment_id)
    if not payment or payment["tg_user_id"] != int(user["id"]):
        raise web.HTTPNotFound(text="payment not found")

    if payment["status"] == "succeeded":
        tenant = await get_tenant(str(settings.database), int(user["id"]), user.get("username"), user.get("first_name"))
        return web.json_response({"status": "succeeded", "subscription": _subscription_view(tenant, settings)})

    provider_ref = payment.get("provider_ref")
    checkout_id = None
    if provider_ref and provider_ref.startswith("billing:"):
        checkout_id = provider_ref.split(":", 1)[1]

    billing = get_billing_client(settings)
    if billing and checkout_id:
        subs = billing.list_subscriptions(int(user["id"]))
        for sub in subs:
            if sub.get("status") in ("active", "past_due", "pending_cancel"):
                await store.set_payment_status(payment["uid"], "succeeded")
                tenant = await get_tenant(str(settings.database), int(user["id"]), user.get("username"), user.get("first_name"))
                return web.json_response({"status": "succeeded", "subscription": _subscription_view(tenant, settings)})

        checkout_status = billing.checkout_status(checkout_id, int(user["id"]))
        if checkout_status and BillingClient.is_success_status(checkout_status):
            return web.json_response({"status": "pending", "checkout_status": checkout_status})

    return web.json_response({"status": payment["status"]})


async def health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "webapp"})


# ── Route setup ────────────────────────────────────────────────────────

def setup_webapp_routes(app: web.Application, store: Store, settings: Settings) -> None:
    """Mount Mini App API at /webapp/api."""
    app["store"] = store
    app["settings"] = settings

    app.router.add_get("/webapp/api/plans", plans_public)
    app.router.add_post("/webapp/api/plans", plans_for_user)
    app.router.add_post("/webapp/api/me", me)
    app.router.add_post("/webapp/api/start-payment", start_payment)
    app.router.add_post("/webapp/api/payment-status", payment_status)
    app.router.add_get("/webapp/api/health", health)