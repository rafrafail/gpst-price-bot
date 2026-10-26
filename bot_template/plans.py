"""Plans config loader for tg_bot_template.

Single source of truth: JSON file with mtime caching. Owner edits file
(or sets BOT_PLANS_FILE) — bot and webapp see same data.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

from bot_template.period import Period

logger = logging.getLogger(__name__)

KNOWN_CURRENCIES = ("RUB", "USD")

# Periods engine can auto-renew (billing_interval month/year, 28-31 and 365/366 days)
RECURRING_DAYS = frozenset((*range(28, 32), 365, 366))

_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"path": None, "mtime": None, "plans": None}


def period_of(plan: dict[str, Any] | None) -> Period | None:
    """Period from plan: field `period` ('month:1'), fallback to old `days`."""
    return Period.from_plan(plan)


def _renewable_by_engine(plan: dict[str, Any]) -> bool:
    """Can engine auto-renew this period? Engine only knows month/year."""
    period = period_of(plan)
    if period is None:
        return False
    if period.unit == "month":
        return period.count == 1
    if period.unit == "year":
        return period.count == 1
    return period.nominal_days in RECURRING_DAYS


def load_plans(path: str) -> dict[str, Any]:
    """Load plans config with mtime cache. Broken file = startup error (not silent empty)."""
    try:
        mtime = os.path.getmtime(path)
    except OSError as exc:
        raise RuntimeError(f"plans file not found: {path}") from exc

    with _cache_lock:
        if _cache["path"] == path and _cache["mtime"] == mtime and _cache["plans"] is not None:
            return _cache["plans"]

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    plans = data.get("plans") or []
    codes = [str(p.get("code") or "") for p in plans]
    if not plans or len(set(codes)) != len(codes) or any(not c for c in codes):
        raise RuntimeError(f"plans file {path}: empty or duplicate plan codes")

    for plan in plans:
        if period_of(plan) is None:
            raise RuntimeError(
                f"plans file {path}: plan {plan.get('code')} has no valid "
                f"period (period={plan.get('period')!r}, days={plan.get('days')!r})"
            )
        # Recurring requires recurring_notice (user must see & consent)
        if plan.get("recurring") and not str(plan.get("recurring_notice") or "").strip():
            raise RuntimeError(
                f"plans file {path}: plan {plan.get('code')} is recurring "
                "but has no recurring_notice"
            )
        # Weekly recurring not supported by engine (only month/year)
        if plan.get("recurring") and not _renewable_by_engine(plan):
            raise RuntimeError(
                f"plans file {path}: plan {plan.get('code')} is recurring with "
                f"period={period_of(plan).spec} — billing engine renews only monthly or yearly"
            )

    with _cache_lock:
        _cache.update(path=path, mtime=mtime, plans=data)
    return data


def is_recurring(plan: dict[str, Any] | None) -> bool:
    """Plan sold as subscription with auto-renew. Default NO (one-time purchase)."""
    return bool((plan or {}).get("recurring"))


def get_plan(plans: dict[str, Any], code: str) -> dict[str, Any] | None:
    for plan in plans.get("plans") or []:
        if str(plan.get("code")) == code:
            return plan
    return None


def currency_for(plans: dict[str, Any], language_code: str | None, override: str = "") -> str:
    """Display currency: env override → user language → config default."""
    if override:
        cur = override.upper()
        return cur if cur in KNOWN_CURRENCIES else "RUB"

    mapping = plans.get("language_currency") or {}
    lang = (language_code or "").split("-")[0].lower()
    if lang:
        cur = str(mapping.get(lang) or mapping.get("default") or "").upper()
    else:
        cur = str(plans.get("currency_default") or "").upper()
    if not cur:
        cur = "RUB"
    return cur if cur in KNOWN_CURRENCIES else "RUB"


def plan_public(plan: dict[str, Any], currency: str) -> dict[str, Any] | None:
    """Plan for storefront: only frontend fields, prices in selected currency.
    None = no price in this currency → plan hidden (can't sell for 0).
    """
    prices = plan.get("prices") or {}
    price = prices.get(currency) or {}
    if int(price.get("amount_minor") or 0) <= 0:
        return None

    display = int(price.get("display_amount_minor") or 0)
    period = period_of(plan)

    return {
        "code": str(plan.get("code")),
        "title": str(plan.get("title") or plan.get("code")),
        "tagline": str(plan.get("tagline") or ""),
        "days": period.nominal_days if period else 0,
        "period": period.spec if period else "",
        "period_text": period.label_ru() if period else "",
        "period_is_calendar": bool(period and period.is_calendar),
        "badge": str(plan.get("badge") or "") or None,
        "features": [str(f) for f in (plan.get("features") or [])],
        "recurring": is_recurring(plan),
        "recurring_notice": (str(plan.get("recurring_notice") or "").strip() or None),
        "currency": currency,
        "amount_minor": int(price.get("amount_minor") or 0),
        "display_amount_minor": display or None,
    }


def public_plans(plans: dict[str, Any], currency: str) -> list[dict[str, Any]]:
    """Storefront in currency: plans without price filtered out."""
    out = []
    for plan in plans.get("plans") or []:
        pub = plan_public(plan, currency)
        if pub is not None:
            out.append(pub)
    return out


def deal_view(plans: dict[str, Any]) -> dict:
    """Deal badge on paywall: decorative countdown, price doesn't change at zero."""
    deal = plans.get("deal") or {}
    return {
        "enabled": bool(deal.get("enabled")),
        "seconds": max(30, int(deal.get("seconds") or 300)),
        "label": str(deal.get("label") or "Скидка сгорает"),
    }


def proof_view(plans: dict[str, Any]) -> dict:
    """Social proof on paywall. Disabled by default — numbers must be real."""
    proof = plans.get("proof") or {}
    rows = [
        {"emoji": str(r.get("emoji") or "•"), "label": str(r.get("label") or "")}
        for r in (proof.get("rows") or []) if r.get("label")
    ][:4]
    headline = str(proof.get("headline") or "").strip()
    return {
        "enabled": bool(proof.get("enabled")) and bool(headline),
        "caption": str(proof.get("caption") or ""),
        "headline": headline,
        "rows": rows,
    }


def reviews_view(plans: dict[str, Any]) -> list[dict]:
    """Paywall reviews. Disabled by default — only real reviews."""
    reviews = plans.get("reviews") or {}
    if not reviews.get("enabled"):
        return []
    out = []
    for item in (reviews.get("items") or [])[:8]:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        out.append({
            "name": str(item.get("name") or ""),
            "emoji": str(item.get("emoji") or "🙂"),
            "stars": max(1, min(5, int(item.get("stars") or 5))),
            "text": text,
        })
    return out