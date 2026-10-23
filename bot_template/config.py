"""Explicit, side-effect-free configuration; no mandatory AI or external DB."""
import os
from dataclasses import dataclass, field
from pathlib import Path
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

    @classmethod
    def from_env(cls) -> "Settings":
        raw = os.environ.get("ADMIN_IDS", "")
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if any(not p.isdecimal() or int(p) <= 0 for p in parts):
            raise ValueError("ADMIN_IDS: нужны положительные числовые ID через запятую")
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
        ZoneInfo(value.timezone)
        if value.mode not in {"polling", "webhook"}:
            raise ValueError("BOT_MODE: polling или webhook")
        if value.mode == "webhook":
            if not value.webhook_url.startswith("https://") or not value.webhook_secret:
                raise ValueError("Webhook требует WEBHOOK_URL с HTTPS и WEBHOOK_SECRET")
            if not 1 <= value.webhook_port <= 65535:
                raise ValueError("Некорректный WEBHOOK_PORT")
        return value
