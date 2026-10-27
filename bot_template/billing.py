"""Thin Billing Engine client wrapper for tg_bot_template.

Uses only the standard library (urllib.request): the plan forbids mandatory
third-party dependencies, and CI sandboxes run without network access anyway.
If BILLING_API_URL and BILLING_API_KEY are not configured, get_billing_client
returns None (card payments disabled, 501 from webapp endpoints). This matches
the Trix pattern: dead tunnel = BillingUnavailable = 501 card disabled.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# Short connect timeout: dead tunnel must fail fast (~2s), frontend polls every 2.5s
_TIMEOUT_S = 8.0

# Checkout/payment statuses that mean "money arrived" → can activate subscription
_SUCCESS_STATUSES = frozenset({"succeeded", "confirmed", "paid", "captured"})


class BillingError(Exception):
    """Base billing call error."""


class BillingUnavailable(BillingError):
    """Billing unreachable: network, timeout, 5xx → 501 card disabled / pending unchanged."""


class BillingConflict(BillingError):
    """409 idempotency_key_conflict: same key, different body. Do NOT retry with same key."""


class BillingRejected(BillingError):
    """Billing rejected on substance (4xx): bad body, plan, consent."""


def _items_of(data: Any) -> list[dict]:
    """Extract list of objects from list endpoint response.

    Engine format not fixed in contract: bare list, {"items": [...]},
    {"subscriptions": [...]}, etc.
    """
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("items", "subscriptions", "checkouts", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def _field(item: dict, *names: str) -> Any:
    for name in names:
        if name in item and item[name] is not None:
            return item[name]
    return None


class _HTTPError(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


class BillingClient:
    """Synchronous HTTP client for Billing Engine API (stdlib urllib).

    One short-lived request per call (no connection pooling across requests).
    `opener` is the transport injection point for tests (urllib.request.OpenerDirector).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        verify_tls: bool = False,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.verify_tls = verify_tls
        self._opener = opener

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[int, str]:
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(json_body).encode() if json_body is not None else None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        context = None
        if not self.verify_tls:
            import ssl

            context = ssl._create_unverified_context()
        opener = self._opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}),  # never route engine traffic via env proxies
            urllib.request.HTTPSHandler(context=context),
        )
        try:
            with opener.open(request, timeout=_TIMEOUT_S) as response:  # noqa: S310
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise BillingUnavailable(f"billing {method} {path} failed: {exc}") from exc

    @staticmethod
    def _raise_for_status(status: int, body: str) -> None:
        if status < 400:
            return
        if status == 409:
            raise BillingConflict(body[:300])
        if status >= 500:
            raise BillingUnavailable(f"billing 5xx: {status} {body[:200]}")
        raise BillingRejected(f"billing {status}: {body[:300]}")

    def create_checkout_session(self, payload: dict, idempotency_key: str) -> dict:
        """POST /v1/checkout/sessions → engine response dict.

        Idempotency-Key REQUIRED (engine returns 400 without it).
        Caller passes a stable per-payment key so retries don't spawn sessions.
        """
        status, body = self._request(
            "POST", "/v1/checkout/sessions", json_body=payload, idempotency_key=idempotency_key
        )
        self._raise_for_status(status, body)
        try:
            return json.loads(body)
        except ValueError as exc:
            raise BillingUnavailable("billing returned non-JSON checkout response") from exc

    def list_subscriptions(self, external_user_id: str | int) -> list[dict]:
        """GET /v1/subscriptions?external_user_id=... → live subscriptions.

        404 (customer_not_found) = no customer yet → return empty list.
        Network/5xx → BillingUnavailable → payment status stays pending.
        """
        status, body = self._request(
            "GET", "/v1/subscriptions", params={"external_user_id": str(external_user_id)}
        )
        if status == 404:
            return []
        self._raise_for_status(status, body)
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise BillingUnavailable("billing returned non-JSON subscriptions") from exc
        return _items_of(data)

    def checkout_status(self, checkout_id: str, external_user_id: str | int) -> str | None:
        """Auxiliary: checkout status via list endpoint (poll through list).

        Returns status string or None if not found / endpoint unavailable.
        Absence does NOT break polling (main signal = live subscription from
        list_subscriptions).
        """
        try:
            status, body = self._request(
                "GET", "/v1/checkout/sessions", params={"external_user_id": str(external_user_id)}
            )
        except BillingUnavailable as exc:
            logger.info("checkout list unavailable: %s", exc)
            return None
        if status in (404, 405, 501):
            return None
        self._raise_for_status(status, body)
        try:
            data = json.loads(body)
        except ValueError:
            return None
        for item in _items_of(data):
            cid = _field(item, "checkout_id", "id")
            if str(cid) == str(checkout_id):
                value = _field(item, "status", "state")
                return str(value) if value is not None else None
        return None

    @staticmethod
    def is_success_status(status: str | None) -> bool:
        return str(status or "").strip().lower() in _SUCCESS_STATUSES


def get_billing_client(config: Any = None) -> BillingClient | None:
    """Client from config or None → card provider disabled (501).

    No network probe here — liveness checked on actual call.
    """
    from bot_template.config import Settings

    if config is None:
        config = Settings.from_env()

    if not (config.billing_api_url and config.billing_api_key):
        return None

    return BillingClient(
        config.billing_api_url,
        config.billing_api_key,
        verify_tls=config.billing_verify_tls,
    )
