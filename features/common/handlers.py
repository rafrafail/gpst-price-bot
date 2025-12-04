"""Common feature handlers - greeting and help commands."""
import json
from pathlib import Path
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from loguru import logger

from core.config import Config
from core.markdown_v2 import sanitize_markdown_v2

router = Router()

# Путь к файлу с сообщениями
MESSAGES_FILE = Config.CONFIG_DIR / "messages.json"


def load_messages() -> dict:
    """Load messages from JSON file."""
    try:
        if not MESSAGES_FILE.exists():
            logger.warning(f"Файл {MESSAGES_FILE} не найден, используются значения по умолчанию")
            return get_default_messages()
        
        with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка при загрузке сообщений: {e}")
        return get_default_messages()


def get_default_messages() -> dict:
    """Get default messages if file is not available."""
    return {
        "start": {
            "greeting": "👋 Привет, {name}!",
            "welcome": "Добро пожаловать!",
            "description": "Это шаблон телеграм-бота с интеграцией ИИ через OpenRouter.",
            "help_hint": "Используйте /help для получения списка доступных команд."
        },
        "help": {
            "title": "📚 Справка по командам",
            "description": "Доступные команды бота:",
            "commands": [
                {
                    "command": "/start",
                    "description": "Запустить бота и получить приветствие"
                },
                {
                    "command": "/help",
                    "description": "Показать эту справку"
                },
                {
                    "command": "/admin",
                    "description": "Панель администратора (только для админов)"
                },
                {
                    "command": "/broadcast",
                    "description": "Рассылка сообщений (только для админов)"
                }
            ],
            "footer": "Если у вас возникли вопросы, обратитесь к администратору."
        }
    }


def get_user_display_name(user) -> str:
    """Get user display name (username or full_name)."""
    if user.username:
        return f"@{user.username}"
    elif user.full_name:
        return user.full_name
    else:
        return "друг"


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Start command handler with personalized greeting."""
    messages = load_messages()
    start_config = messages.get("start", {})
    
    # Получаем имя пользователя
    user = message.from_user
    name = get_user_display_name(user)
    
    # Формируем приветствие
    greeting = start_config.get("greeting", "👋 Привет, {name}!").format(name=name)
    welcome = start_config.get("welcome", "Добро пожаловать!")
    description = start_config.get("description", "")
    help_hint = start_config.get("help_hint", "")
    
    # Формируем сообщение
    text_parts = [
        sanitize_markdown_v2(greeting),
        "",
        f"*{sanitize_markdown_v2(welcome)}*",
        "",
        sanitize_markdown_v2(description),
        "",
        sanitize_markdown_v2(help_hint)
    ]
    
    text = "\n".join(text_parts)
    
    await message.answer(text, parse_mode="MarkdownV2")


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Help command handler."""
    messages = load_messages()
    help_config = messages.get("help", {})
    
    # Получаем данные из конфига
    title = help_config.get("title", "📚 Справка по командам")
    description = help_config.get("description", "Доступные команды бота:")
    commands = help_config.get("commands", [])
    footer = help_config.get("footer", "")
    
    # Формируем список команд
    commands_text = []
    for cmd in commands:
        cmd_name = cmd.get("command", "")
        cmd_desc = cmd.get("description", "")
        commands_text.append(f"• {sanitize_markdown_v2(cmd_name)} — {sanitize_markdown_v2(cmd_desc)}")
    
    # Формируем сообщение
    text_parts = [
        f"*{sanitize_markdown_v2(title)}*",
        "",
        sanitize_markdown_v2(description),
        "",
        *commands_text,
        "",
        sanitize_markdown_v2(footer)
    ]
    
    text = "\n".join(text_parts)
    
    await message.answer(text, parse_mode="MarkdownV2")

