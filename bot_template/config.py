"""Explicit, side-effect-free configuration; no mandatory AI or external DB."""
import ipaddress
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bot_template.profile import BotProfile, load_profile_from_env

CLOUD_BOT_API_BASE = "https://api.telegram.org"
TRANSPORTS = frozenset({"cloud", "self_hosted"})


def _is_loopback(hostname: str | None) -> bool:
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(hostname or "").is_loopback
    except ValueError:
        return False


def _validate_api_base(value: str, variable: str) -> None:
    endpoint = urlsplit(value)
    try:
        valid_port = endpoint.port is None or 1 <= endpoint.port <= 65535
    except ValueError:
        valid_port = False
    local = _is_loopback(endpoint.hostname)
    if (endpoint.username is not None or endpoint.password is not None
            or endpoint.query or endpoint.fragment or not endpoint.hostname
            or endpoint.scheme not in {"http", "https"} or not valid_port
            or (endpoint.scheme == "http" and not local)):
        raise ValueError(f"{variable}: нужен HTTPS; HTTP разрешён только для loopback-тестов")


@dataclass(frozen=True)
class Settings:
    token: str = field(default="", repr=False)
    admins: frozenset[int] = frozenset()
    title: str = "Мой бот"
    database: Path = Path("data/template-v2.sqlite3")
    timezone: str = "Europe/Moscow"
    broadcasts: bool = True
    # ``api_base`` remains a small testing/backwards-compatible seam. New
    # deployments select a transport instead of encoding that choice in a URL.
    api_base: str | None = None
    transport: str = "cloud"
    local_api_base: str = "http://127.0.0.1:8081"
    mode: str = "polling"
    webhook_url: str = ""
    webhook_secret: str = field(default="", repr=False)
    webhook_host: str = "127.0.0.1"
    webhook_port: int = 8080
    # Public profile (loaded from TOML via BOT_PROFILE_PATH)
    profile: BotProfile = field(default_factory=BotProfile)

    # Billing Engine integration
    billing_api_url: str | None = None
    billing_api_key: str = field(default="", repr=False)
    billing_verify_tls: bool = False
    billing_application_id: str | None = None
    billing_webhook_secret: str = field(default="", repr=False)
    # Map local plan_code -> billing plan_code (may differ)
    billing_plan_map: dict[str, str] = field(default_factory=dict)
    billing_plan_version_map: dict[str, str] = field(default_factory=dict)
    billing_offer_version: str = "1"
    billing_currency: str = "RUB"

    # Telegram Web App initData validation
    initdata_max_age_s: int = 86400  # 24h

    # Mini App paywall gate (if true, run-case returns paywall when not pro)
    miniapp_paywall: bool = False

    @property
    def bot_username(self) -> str | None:
        return self.profile.bot_username

    @property
    def bot_api_base(self) -> str:
        if self.api_base is not None:
            return self.api_base
        if self.transport == "self_hosted":
            return self.local_api_base
        return CLOUD_BOT_API_BASE

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.timezone)
        except (KeyError, ValueError):
            raise ValueError("BOT_TIMEZONE: укажите IANA-зону, например Europe/Moscow") from None
        if not self.title.strip() or len(self.title) > 80:
            raise ValueError("BOT_TITLE: нужно название от 1 до 80 символов")
        if self.mode not in {"polling", "webhook"}:
            raise ValueError("BOT_MODE: polling или webhook")
        if self.transport not in TRANSPORTS:
            raise ValueError("TELEGRAM_TRANSPORT: cloud или self_hosted")
        if self.api_base is not None:
            _validate_api_base(self.api_base, "TELEGRAM_API_BASE")
        if self.transport == "self_hosted":
            if self.api_base is not None:
                raise ValueError(
                    "TELEGRAM_API_BASE нельзя сочетать с TELEGRAM_TRANSPORT=self_hosted; "
                    "используйте LOCAL_BOT_API_URL"
                )
            _validate_api_base(self.local_api_base, "LOCAL_BOT_API_URL")
            if not _is_loopback(urlsplit(self.local_api_base).hostname):
                raise ValueError("LOCAL_BOT_API_URL: self-hosted API должен быть доступен только через loopback")
        if self.mode == "webhook":
            if not self.webhook_url.startswith("https://") or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", self.webhook_secret):
                raise ValueError("Webhook требует HTTPS URL и WEBHOOK_SECRET: 1–256 символов A–Z, a–z, 0–9, _ или -")
            if not 1 <= self.webhook_port <= 65535:
                raise ValueError("Некорректный WEBHOOK_PORT")

    @classmethod
    def from_env(cls) -> "Settings":
        raw = os.environ.get("ADMIN_IDS", "")
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if any(not p.isdecimal() or not 0 < int(p) < 2 ** 63 for p in parts):
            raise ValueError("ADMIN_IDS: нужны положительные числовые ID через запятую")
        if os.environ.get("BROADCAST_ENABLED", "1") not in {"0", "1"}:
            raise ValueError("BROADCAST_ENABLED: 0 или 1")

        # Load profile first (can be overridden by explicit env vars)
        profile = load_profile_from_env()

        # Explicit env vars take priority over profile
        title = os.environ.get("BOT_TITLE", profile.title)
        # Help and welcome only from profile (no env overrides for now)

        # Billing Engine settings
        billing_api_url = os.environ.get("BILLING_API_URL") or None
        billing_api_key = os.environ.get("BILLING_API_KEY", "")
        billing_verify_tls = os.environ.get("BILLING_VERIFY_TLS", "0") == "1"
        billing_application_id = os.environ.get("BILLING_APPLICATION_ID") or None
        billing_webhook_secret = os.environ.get("BILLING_WEBHOOK_SECRET", "")
        billing_currency = os.environ.get("BILLING_CURRENCY", "RUB")
        billing_offer_version = os.environ.get("BILLING_OFFER_VERSION", "1")
        initdata_max_age_s = int(os.environ.get("INITDATA_MAX_AGE_S", "86400"))
        miniapp_paywall = os.environ.get("MINIAPP_PAYWALL", "0") == "1"

        # Parse billing_plan_map: "local1=billing1,local2=billing2"
        billing_plan_map: dict[str, str] = {}
        raw_plan_map = os.environ.get("BILLING_PLAN_MAP", "")
        if raw_plan_map:
            for pair in raw_plan_map.split(","):
                pair = pair.strip()
                if "=" in pair:
                    local, billing = pair.split("=", 1)
                    billing_plan_map[local.strip()] = billing.strip()

        # Parse billing_plan_version_map: "local1=ver1,local2=ver2"
        billing_plan_version_map: dict[str, str] = {}
        raw_version_map = os.environ.get("BILLING_PLAN_VERSION_MAP", "")
        if raw_version_map:
            for pair in raw_version_map.split(","):
                pair = pair.strip()
                if "=" in pair:
                    local, ver = pair.split("=", 1)
                    billing_plan_version_map[local.strip()] = ver.strip()

        value = cls(
            token=os.environ.get("BOT_TOKEN", ""),
            admins=frozenset(map(int, parts)),
            title=title,
            database=Path(os.environ.get("DATABASE_PATH", "data/template-v2.sqlite3")),
            timezone=os.environ.get("BOT_TIMEZONE", "Europe/Moscow"),
            broadcasts=os.environ.get("BROADCAST_ENABLED", "1") == "1",
            api_base=os.environ.get("TELEGRAM_API_BASE") or None,
            transport=os.environ.get("TELEGRAM_TRANSPORT", "cloud"),
            local_api_base=os.environ.get("LOCAL_BOT_API_URL", "http://127.0.0.1:8081"),
            mode=os.environ.get("BOT_MODE", "polling"),
            webhook_url=os.environ.get("WEBHOOK_URL", ""),
            webhook_secret=os.environ.get("WEBHOOK_SECRET", ""),
            webhook_host=os.environ.get("WEBHOOK_HOST", "127.0.0.1"),
            webhook_port=int(os.environ.get("WEBHOOK_PORT", "8080")),
            profile=profile,
            billing_api_url=billing_api_url,
            billing_api_key=billing_api_key,
            billing_verify_tls=billing_verify_tls,
            billing_application_id=billing_application_id,
            billing_webhook_secret=billing_webhook_secret,
            billing_plan_map=billing_plan_map,
            billing_plan_version_map=billing_plan_version_map,
            billing_offer_version=billing_offer_version,
            billing_currency=billing_currency,
            initdata_max_age_s=initdata_max_age_s,
            miniapp_paywall=miniapp_paywall,
        )
        return value
