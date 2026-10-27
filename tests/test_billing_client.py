"""Tests for the stdlib BillingClient (no third-party HTTP deps allowed in CI image)."""
import io
import json
import urllib.error
import urllib.request

import pytest

from bot_template.billing import (
    BillingClient,
    BillingRejected,
    BillingUnavailable,
    get_billing_client,
)


class FakeResponse:
    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body.encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener(urllib.request.OpenerDirector):
    """Records the last request and replays a scripted response/error."""

    def __init__(self, status: int = 200, body: str = "{}", error: Exception | None = None):
        super().__init__()
        self.status = status
        self.body = body
        self.error = error
        self.last_request: urllib.request.Request | None = None

    def open(self, fullurl, data=None, timeout=None):  # match urllib signature
        # urllib calls opener.open(request-object); keep whatever arrives.
        self.last_request = fullurl  # type: ignore[assignment]
        if self.error is not None:
            raise self.error
        if self.status >= 400:
            raise urllib.error.HTTPError(
                getattr(fullurl, "full_url", str(fullurl)),
                self.status,
                "err",
                {},
                io.BytesIO(self.body.encode()),
            )
        return FakeResponse(self.status, self.body)


def _client(opener: FakeOpener) -> BillingClient:
    return BillingClient("https://billing.example", "key-test", opener=opener)


def test_checkout_sends_auth_and_idempotency_headers():
    opener = FakeOpener(status=200, body=json.dumps({"checkout_url": "https://pay"}))
    client = _client(opener)
    result = client.create_checkout_session({"plan": "month"}, idempotency_key="pay-42")
    assert result["checkout_url"] == "https://pay"
    request = opener.last_request
    assert request is not None
    assert request.get_header("Authorization") == "Bearer key-test"
    assert request.get_header("Idempotency-key") == "pay-42"
    assert request.get_header("Content-type") == "application/json"


def test_checkout_409_conflict_and_4xx_rejection():
    client = _client(FakeOpener(status=409, body="idempotency_key_conflict"))
    with pytest.raises(Exception) as exc409:
        client.create_checkout_session({}, "k")
    assert "conflict" in str(exc409.value)
    client = _client(FakeOpener(status=422, body="bad plan"))
    with pytest.raises(BillingRejected):
        client.create_checkout_session({}, "k")


def test_network_error_maps_to_unavailable():
    client = _client(FakeOpener(error=urllib.error.URLError("conn refused")))
    with pytest.raises(BillingUnavailable):
        client.create_checkout_session({}, "k")


def test_list_subscriptions_handles_bare_list_and_404():
    body = json.dumps([{"plan_code": "month", "status": "active"}])
    client = _client(FakeOpener(status=200, body=body))
    subs = client.list_subscriptions(7)
    assert subs == [{"plan_code": "month", "status": "active"}]
    client = _client(FakeOpener(status=404, body="customer_not_found"))
    assert client.list_subscriptions(7) == []
    with pytest.raises(BillingUnavailable):
        _client(FakeOpener(status=503, body="down")).list_subscriptions(7)


def test_success_status_normalization():
    assert BillingClient.is_success_status("Succeeded")
    assert BillingClient.is_success_status(" paid ")
    assert not BillingClient.is_success_status("pending")
    assert not BillingClient.is_success_status(None)


def test_get_billing_client_requires_both_url_and_key(monkeypatch):
    monkeypatch.delenv("BILLING_API_URL", raising=False)
    monkeypatch.delenv("BILLING_API_KEY", raising=False)
    assert get_billing_client() is None
