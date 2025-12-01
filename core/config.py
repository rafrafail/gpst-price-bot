"""Configuration management module."""
import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# Загружаем переменные окружения из .env
load_dotenv()

# Корневая директория проекта
BASE_DIR = Path(__file__).parent.parent


class Config:
    """Application configuration."""
    
    # Telegram Bot
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    
    # OpenRouter
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    
    # Admin IDs
    ADMIN_IDS: List[int] = [
        int(admin_id.strip())
        for admin_id in os.getenv("ADMIN_IDS", "").split(",")
        if admin_id.strip().isdigit()
    ]
    
    # Logging
    DEBUG_MODE: bool = os.getenv("DEBUG_MODE", "0") == "1"
    LOG_TO_FILE: bool = os.getenv("LOG_TO_FILE", "0") == "1"
    
    # Database
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", str(BASE_DIR / "bot.db"))
    
    # Paths
    LOGS_DIR: Path = BASE_DIR / "logs"
    PROMPTS_DIR: Path = BASE_DIR / "prompts"
    CONFIG_DIR: Path = BASE_DIR / "config"
    OPENROUTER_MESSAGES_DIR: Path = BASE_DIR / "OpenRouterMessages"
    
    @classmethod
    def validate(cls) -> None:
        """Validate configuration and raise CriticalError if invalid."""
        errors = []
        
        if not cls.BOT_TOKEN:
            errors.append("BOT_TOKEN не установлен в .env")
        
        if not cls.OPENROUTER_API_KEY:
            errors.append("OPENROUTER_API_KEY не установлен в .env")
        
        if errors:
            error_msg = "Критические ошибки конфигурации:\n" + "\n".join(f"  - {e}" for e in errors)
            raise CriticalError(error_msg)
        
        # Создаем необходимые директории
        cls.LOGS_DIR.mkdir(exist_ok=True)
        cls.OPENROUTER_MESSAGES_DIR.mkdir(exist_ok=True)
    
    @classmethod
    def is_admin(cls, user_id: int) -> bool:
        """Check if user is admin."""
        return user_id in cls.ADMIN_IDS


class CriticalError(Exception):
    """Critical configuration or runtime error."""
    pass

