"""Main entry point for Telegram Bot."""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable
from loguru import logger

from core.config import Config, CriticalError
from core.logger import setup_logger
from core.database import db
from core.broadcast import router as broadcast_router
from core.test_markdownv2 import router as test_markdownv2_router
from features.admin.handlers import router as admin_router


async def register_user_handler(message):
    """Register user when they interact with bot."""
    user = message.from_user
    await db.register_user(
        telegram_id=user.id,
        telegram_nickname=user.username,
        telegram_name=user.full_name,
    )


async def setup_bot_commands(bot: Bot):
    """Setup bot commands menu."""
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="admin", description="Панель администратора"),
        BotCommand(command="broadcast", description="Рассылка (только для админов)"),
        BotCommand(command="test_markdownv2", description="Тест форматирования MarkdownV2"),
        BotCommand(command="cancel", description="Отменить текущую операцию"),
    ]
    await bot.set_my_commands(commands)


async def main():
    """Main function."""
    try:
        # Настраиваем логирование
        setup_logger()
        logger.info("Запуск бота...")
        
        # Валидируем конфигурацию
        Config.validate()
        logger.info("Конфигурация валидна")
        
        # Инициализируем базу данных
        await db.init()
        logger.info("База данных инициализирована")
        
        # Создаем бота и диспетчер
        bot = Bot(token=Config.BOT_TOKEN)
        storage = MemoryStorage()
        dp = Dispatcher(storage=storage)
        
        # Middleware для логирования действий пользователей
        class UserActionLoggerMiddleware(BaseMiddleware):
            async def __call__(
                self,
                handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
                event: Any,
                data: Dict[str, Any]
            ) -> Any:
                # Логируем текстовые сообщения
                if isinstance(event, Message):
                    user = event.from_user
                    user_info = f"ID:{user.id}"
                    if user.username:
                        user_info += f" @{user.username}"
                    if user.full_name:
                        user_info += f" ({user.full_name})"
                    
                    # Логируем команды
                    if event.text and event.text.startswith('/'):
                        command = event.text.split()[0] if event.text else None
                        logger.info(f"Пользователь {user_info} выполнил команду: {command}")
                    # Логируем текстовые сообщения
                    elif event.text:
                        text_preview = event.text[:100] + "..." if len(event.text) > 100 else event.text
                        logger.info(f"Пользователь {user_info} отправил текст: {text_preview}")
                    # Логируем другие типы сообщений (фото, документы и т.д.)
                    elif event.photo or event.document or event.video or event.audio or event.voice:
                        media_type = "фото" if event.photo else "документ" if event.document else "видео" if event.video else "аудио" if event.audio else "голосовое"
                        logger.info(f"Пользователь {user_info} отправил {media_type}")
                
                # Логируем нажатия на inline-кнопки
                elif isinstance(event, CallbackQuery):
                    user = event.from_user
                    user_info = f"ID:{user.id}"
                    if user.username:
                        user_info += f" @{user.username}"
                    if user.full_name:
                        user_info += f" ({user.full_name})"
                    
                    button_data = event.data or "неизвестно"
                    logger.info(f"Пользователь {user_info} нажал кнопку: {button_data}")
                
                return await handler(event, data)
        
        # Middleware для регистрации пользователей
        class UserRegistrationMiddleware(BaseMiddleware):
            async def __call__(
                self,
                handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
                event: Message,
                data: Dict[str, Any]
            ) -> Any:
                # Регистрируем пользователя перед обработкой сообщения
                await register_user_handler(event)
                return await handler(event, data)
        
        # Добавляем middleware для логирования (должен быть первым)
        dp.message.middleware(UserActionLoggerMiddleware())
        dp.callback_query.middleware(UserActionLoggerMiddleware())
        
        # Добавляем middleware для регистрации пользователей
        dp.message.middleware(UserRegistrationMiddleware())
        
        # Обработчик команды /start
        @dp.message(Command("start"))
        async def cmd_start(message):
            await message.answer(
                "👋 *Добро пожаловать\\!*\n\n"
                "Это шаблон телеграм\\-бота с интеграцией ИИ через OpenRouter\\.\n\n"
                "Используйте /admin для доступа к панели администратора\\.",
                parse_mode="MarkdownV2"
            )
        
        # Регистрируем роутеры (после обработчика /start)
        dp.include_router(broadcast_router)
        dp.include_router(admin_router)
        dp.include_router(test_markdownv2_router)
        
        # Настраиваем команды бота
        await setup_bot_commands(bot)
        logger.info("Команды бота настроены")
        
        logger.info("Бот запущен и готов к работе")
        
        # Запускаем бота
        await dp.start_polling(bot, skip_updates=True)
    
    except CriticalError as e:
        logger.critical(f"Критическая ошибка: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Остановка бота по запросу пользователя")
    except Exception as e:
        logger.exception(f"Неожиданная ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Используем uvloop на Linux для лучшей производительности
    try:
        import uvloop
        uvloop.install()
        logger.info("uvloop установлен")
    except ImportError:
        logger.debug("uvloop не доступен, используется стандартный event loop")
    
    asyncio.run(main())

