"""Broadcast module for sending messages to all users."""
from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from loguru import logger

from core.config import Config
from core.database import db
from core.markdown_v2 import send_md_v2, sanitize_markdown_v2
from core.message_splitter import send_long_markdown
from features.admin.states import ADMIN_States

router = Router()


def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    return Config.is_admin(user_id)


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    """Start broadcast process."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    await state.set_state(ADMIN_States.BROADCAST_TEXT)
    await message.answer(
        "📢 Введите текст сообщения для рассылки (поддерживается Markdown):\n\n"
        "Используйте /cancel для отмены."
    )


@router.message(ADMIN_States.BROADCAST_TEXT)
async def process_broadcast_text(message: Message, state: FSMContext):
    """Process broadcast text and show preview."""
    text = message.text or message.caption or ""
    
    logger.info(f"[BROADCAST] Админ {message.from_user.id} ввел текст для рассылки")
    logger.debug(f"[BROADCAST] Исходный текст (первые 200 символов): {text[:200]}")
    logger.debug(f"[BROADCAST] Длина текста: {len(text)} символов")
    
    if not text.strip():
        await message.answer("❌ Текст не может быть пустым. Попробуйте снова или /cancel")
        return
    
    # Сохраняем текст в состоянии
    await state.update_data(broadcast_text=text)
    
    # Создаем inline-кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Отправить", callback_data="broadcast_confirm"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel"),
        ]
    ])
    
    await state.set_state(ADMIN_States.BROADCAST_CONFIRM)
    
    # Показываем предпросмотр с использованием MarkdownV2
    # Служебный текст экранируем, текст админа передаем как есть
    preview_header = sanitize_markdown_v2("📋 Предпросмотр сообщения:")
    preview_footer = sanitize_markdown_v2("Подтвердите отправку:")
    
    # Текст админа передаем как есть (без экранирования) - он уже содержит Markdown-теги
    user_text_preview = text[:500] + ('...' if len(text) > 500 else '')
    
    # Формируем полный текст предпросмотра
    preview_text = f"{preview_header}\n\n{user_text_preview}\n\n{preview_footer}"
    
    logger.info(f"[BROADCAST] Формирую предпросмотр сообщения")
    logger.debug(f"[BROADCAST] Заголовок (экранированный): {preview_header}")
    logger.debug(f"[BROADCAST] Текст админа (без экранирования): {user_text_preview[:200]}")
    logger.debug(f"[BROADCAST] Полный текст предпросмотра (первые 300 символов): {preview_text[:300]}")
    
    try:
        # Используем send_md_v2 для показа текста с Markdown-форматированием
        # Текст админа уже содержит Markdown-теги, поэтому передаем как есть
        logger.debug(f"[BROADCAST] Отправляю предпросмотр с parse_mode=MarkdownV2")
        await send_md_v2(
            message,
            preview_text,
            reply_markup=keyboard
        )
        logger.info(f"[BROADCAST] Предпросмотр успешно отправлен")
    except Exception as e:
        logger.warning(f"[BROADCAST] Ошибка при отправке предпросмотра с Markdown: {e}")
        logger.exception(f"[BROADCAST] Детали ошибки:")
        # Отправляем без Markdown, если парсинг не удался
        await message.answer(
            f"📋 Предпросмотр сообщения:\n\n{user_text_preview}\n\nПодтвердите отправку:",
            reply_markup=keyboard,
            parse_mode=None
        )


@router.callback_query(lambda c: c.data == "broadcast_confirm", ADMIN_States.BROADCAST_CONFIRM)
async def confirm_broadcast(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Confirm and send broadcast."""
    data = await state.get_data()
    text = data.get("broadcast_text", "")
    
    logger.info(f"[BROADCAST] Админ {callback.from_user.id} подтвердил рассылку")
    logger.debug(f"[BROADCAST] Текст для рассылки (первые 200 символов): {text[:200]}")
    logger.debug(f"[BROADCAST] Длина текста: {len(text)} символов")
    
    if not text:
        logger.warning(f"[BROADCAST] Текст не найден в состоянии!")
        await callback.answer("❌ Текст не найден", show_alert=True)
        await state.clear()
        return
    
    await callback.message.edit_text("📤 Начинаю рассылку...")
    
    # Получаем список всех пользователей
    try:
        user_ids = await db.get_all_user_ids()
        logger.info(f"[BROADCAST] Получен список пользователей: {len(user_ids)} пользователей")
    except Exception as e:
        logger.error(f"[BROADCAST] Ошибка при получении списка пользователей: {e}")
        await callback.message.edit_text("❌ Ошибка при получении списка пользователей.")
        await state.clear()
        return
    
    if not user_ids:
        logger.warning(f"[BROADCAST] Нет пользователей для рассылки")
        await callback.message.edit_text("❌ Нет пользователей для рассылки.")
        await state.clear()
        return
    
    # Отправляем сообщения
    success_count = 0
    error_count = 0
    
    logger.info(f"[BROADCAST] Начинаю рассылку {len(user_ids)} пользователям")
    logger.debug(f"[BROADCAST] Текст будет отправлен БЕЗ санитизации (sanitize=False)")
    
    for user_id in user_ids:
        try:
            logger.debug(f"[BROADCAST] Отправляю сообщение пользователю {user_id}")
            await send_long_markdown(
                bot=bot,
                chat_id=user_id,
                text=text,
                sanitize=False,  # Явно указываем, что не нужно санитизировать
            )
            success_count += 1
            if success_count % 10 == 0:
                logger.info(f"[BROADCAST] Отправлено {success_count}/{len(user_ids)} сообщений")
        except Exception as e:
            error_count += 1
            logger.warning(f"[BROADCAST] Ошибка при отправке сообщения пользователю {user_id}: {e}")
            logger.debug(f"[BROADCAST] Детали ошибки для пользователя {user_id}:", exc_info=True)
    
    await callback.message.edit_text(
        f"✅ Рассылка завершена!\n\n"
        f"Успешно: {success_count}\n"
        f"Ошибок: {error_count}\n"
        f"Всего: {len(user_ids)}"
    )
    
    await state.clear()
    await callback.answer()


@router.callback_query(lambda c: c.data == "broadcast_cancel", ADMIN_States.BROADCAST_CONFIRM)
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    """Cancel broadcast."""
    await state.clear()
    await callback.message.edit_text("❌ Рассылка отменена.")
    await callback.answer()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Cancel current FSM state."""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нет активного процесса для отмены.")
        return
    
    await state.clear()
    await message.answer("✅ Операция отменена.")

