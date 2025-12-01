"""Logging configuration module."""
import sys
from pathlib import Path
from loguru import logger
from typing import Any

from core.config import Config


def mask_sensitive_data(text: str) -> str:
    """Mask sensitive data in log messages."""
    # Маскируем токены
    if "BOT_TOKEN" in text or "OPENROUTER_API_KEY" in text:
        # Заменяем токены на маскированные версии
        import re
        # Маскируем токены вида sk-or-... или xxx:...
        text = re.sub(r'(sk-or-|xxx:)[^\s\)]+', r'\1***', text)
    
    # Маскируем персональные данные (можно расширить)
    # Например, email, телефоны и т.д.
    
    return text


class SensitiveFilter:
    """Filter to mask sensitive data in logs."""
    
    def __call__(self, record: dict[str, Any]) -> bool:
        """Filter log records and mask sensitive data."""
        if "message" in record:
            record["message"] = mask_sensitive_data(str(record["message"]))
        return True


def setup_logger() -> None:
    """Configure loguru logger."""
    # Удаляем стандартный обработчик
    logger.remove()
    
    # Цвета для разных уровней
    color_map = {
        "INFO": "<blue>",
        "DEBUG": "<white>",
        "SUCCESS": "<green>",
        "WARNING": "<yellow>",
        "ERROR": "<red>",
        "CRITICAL": "<red><bold>",
    }
    
    # Формат для терминала
    terminal_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )
    
    # Формат для файла (без цветов)
    file_format = (
        "{time:YYYY-MM-DD HH:mm:ss} | "
        "{level: <8} | "
        "{name}:{function}:{line} | "
        "{message}"
    )
    
    # Добавляем обработчик для терминала
    if Config.DEBUG_MODE:
        # Подробный вывод в терминал
        logger.add(
            sys.stderr,
            format=terminal_format,
            level="DEBUG",
            colorize=True,
            filter=SensitiveFilter(),
        )
    else:
        # Только ошибки и критические сообщения
        logger.add(
            sys.stderr,
            format=terminal_format,
            level="ERROR",
            colorize=True,
            filter=SensitiveFilter(),
        )
    
    # Добавляем обработчик для файла
    if Config.LOG_TO_FILE:
        log_file = Config.LOGS_DIR / "app.log"
        logger.add(
            log_file,
            format=file_format,
            level="DEBUG",
            rotation="10 MB",
            retention="7 days",
            compression="zip",
            filter=SensitiveFilter(),
        )
    
    logger.info("Логгер настроен", DEBUG_MODE=Config.DEBUG_MODE, LOG_TO_FILE=Config.LOG_TO_FILE)

