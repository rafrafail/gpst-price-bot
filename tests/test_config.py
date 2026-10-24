import pytest

from bot_template.config import Settings


@pytest.mark.parametrize("endpoint", [
    "http://api.telegram.org", "https://user:password@example.com", "ftp://example.com",
    "https://api.telegram.org?key=bad", "https://api.telegram.org/#fragment", "example.com",
])
def test_unsafe_api_endpoints_rejected(endpoint):
    with pytest.raises(ValueError, match="TELEGRAM_API_BASE"):
        Settings(api_base=endpoint)


@pytest.mark.parametrize("endpoint", ["https://api.telegram.org", "http://127.0.0.1:8081",
                                      "http://[::1]:8081", "http://localhost:8081"])
def test_secure_or_local_test_api_endpoints_allowed(endpoint):
    assert Settings(api_base=endpoint).api_base == endpoint


def test_timezone_and_webhook_validation():
    with pytest.raises(ValueError, match="BOT_TIMEZONE"):
        Settings(timezone="NOT_A_TIMEZONE")
    with pytest.raises(ValueError, match="Webhook"):
        Settings(mode="webhook", webhook_url="http://example.com/telegram", webhook_secret="valid")
    with pytest.raises(ValueError, match="Webhook"):
        Settings(mode="webhook", webhook_url="https://example.com/telegram", webhook_secret="invalid space")
    with pytest.raises(ValueError, match="Webhook"):
        Settings(mode="webhook", webhook_url="https://example.com/telegram", webhook_secret="x" * 257)


def test_keys_not_repr_and_broadcast_flag_strict(monkeypatch):
    token, secret = "NOT_A_REAL_TOKEN", "NOT_A_REAL_SECRET"
    assert token not in repr(Settings(token=token, webhook_secret=secret))
    assert secret not in repr(Settings(token=token, webhook_secret=secret))
    monkeypatch.setenv("BROADCAST_ENABLED", "maybe")
    with pytest.raises(ValueError, match="BROADCAST_ENABLED"):
        Settings.from_env()
