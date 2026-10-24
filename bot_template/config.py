"""Explicit, side-effect-free configuration; no mandatory AI or external DB."""
import ipaddress
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Settings:
    token: str = field(default="", repr=False)
    admins: frozenset[int] = frozenset()
    title: str = "Мой бот"
    database: Path = Path("data/template-v2.sqlite3")
    timezone: str = "Europe/Moscow"
    broadcasts: bool = True
    api_base: str = "https://api.telegram.org"
    mode: str = "polling"
    webhook_url: str = ""
    webhook_secret: str = field(default="", repr=False)
    webhook_host: str = "127.0.0.1"
    webhook_port: int = 8080

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.timezone)
        except (KeyError, ValueError):
            raise ValueError("BOT_TIMEZONE: укажите IANA-зону, например Europe/Moscow") from None
        if not self.title.strip() or len(self.title) > 80:
            raise ValueError("BOT_TITLE: нужно название от 1 до 80 символов")
        if self.mode not in {"polling", "webhook"}:
            raise ValueError("BOT_MODE: polling или webhook")
        endpoint = urlsplit(self.api_base)
        local = endpoint.hostname in {"localhost", "127.0.0.1", "::1"}
        if not local:
            try:
                local = ipaddress.ip_address(endpoint.hostname or "").is_loopback
            except ValueError:
                pass
        if (endpoint.username is not None or endpoint.password is not None
                or endpoint.query or endpoint.fragment or not endpoint.hostname
                or endpoint.scheme not in {"http", "https"}
                or (endpoint.scheme == "http" and not local)):
            raise ValueError("TELEGRAM_API_BASE: нужен HTTPS; HTTP разрешён только для loopback-тестов")
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
        value = cls(
            token=os.environ.get("BOT_TOKEN", ""),
            admins=frozenset(map(int, parts)),
            title=os.environ.get("BOT_TITLE", "Мой бот"),
            database=Path(os.environ.get("DATABASE_PATH", "data/template-v2.sqlite3")),
            timezone=os.environ.get("BOT_TIMEZONE", "Europe/Moscow"),
            broadcasts=os.environ.get("BROADCAST_ENABLED", "1") == "1",
            api_base=os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org"),
            mode=os.environ.get("BOT_MODE", "polling"),
            webhook_url=os.environ.get("WEBHOOK_URL", ""),
            webhook_secret=os.environ.get("WEBHOOK_SECRET", ""),
            webhook_host=os.environ.get("WEBHOOK_HOST", "127.0.0.1"),
            webhook_port=int(os.environ.get("WEBHOOK_PORT", "8080")),
        )
        return value
