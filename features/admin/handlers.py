"""Admin feature handlers."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from loguru import logger

from core.config import Config

router = Router()


def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    return Config.is_admin(user_id)


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Admin panel command."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    await message.answer(
        "🔧 *Панель администратора*\n\n"
        "Доступные команды:\n"
        "• /broadcast — рассылка сообщений всем пользователям\n"
        "• /stats — статистика бота (в разработке)\n\n"
        "Используйте команды для управления ботом.",
        parse_mode="MarkdownV2"
    )

