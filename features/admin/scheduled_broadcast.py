"""Scheduled broadcast module for planning and managing scheduled posts."""
import json
import re
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from loguru import logger

from core.config import Config
from core.database import db
from core.markdown_v2 import sanitize_markdown_v2, send_plain_as_md_v2
from aiogram.enums import ParseMode
from features.admin.states import ADMIN_States
from features.admin.scheduler_worker import publish_scheduled_broadcast

router = Router()

# UTC+3 timezone
UTC_PLUS_3 = timezone(timedelta(hours=3))

# Base directory for scheduled media
BASE_MEDIA_DIR = Path("features/broadcast_media")


def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    return Config.is_admin(user_id)


def get_schedule_menu_keyboard() -> InlineKeyboardMarkup:
    """Create main schedule menu keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Добавить пост", callback_data="schedule_menu_add")
        ],
        [
            InlineKeyboardButton(text="📋 Список постов", callback_data="schedule_menu_list")
        ],
        [
            InlineKeyboardButton(text="👁️ Показать пост", callback_data="schedule_menu_show")
        ],
        [
            InlineKeyboardButton(text="❌ Отменить пост", callback_data="schedule_menu_cancel")
        ],
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="schedule_menu_refresh")
        ],
        [
            InlineKeyboardButton(text="🚪 Выйти", callback_data="schedule_menu_exit")
        ]
    ])


def parse_scheduled_at(date_str: str) -> datetime:
    """
    Parse scheduled_at from JSON (UTC+3).
    
    Args:
        date_str: ISO format datetime string (e.g., "2025-12-03T10:00:00")
    
    Returns:
        datetime object in UTC+3
    """
    try:
        # Парсим как UTC+3
        dt = datetime.fromisoformat(date_str.replace("Z", "+03:00"))
        if dt.tzinfo is None:
            # Если нет timezone, считаем что это UTC+3
            dt = dt.replace(tzinfo=UTC_PLUS_3)
        return dt
    except ValueError as e:
        raise ValueError(f"Неверный формат времени: {date_str}. Ожидается ISO формат (например, 2025-12-03T10:00:00)")


def format_scheduled_at(dt: datetime) -> str:
    """
    Format datetime to string (UTC+3).
    
    Args:
        dt: datetime object
    
    Returns:
        ISO format string
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_PLUS_3)
    return dt.isoformat()


def validate_schedule_json(data: Dict, require_text: bool = False) -> Tuple[bool, Optional[str]]:
    """
    Validate schedule JSON structure.
    
    Args:
        data: JSON data to validate
        require_text: If True, text field is required (for backward compatibility)
    
    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
    # Проверка обязательных полей
    if require_text:
        if "text" not in data:
            return False, "Отсутствует поле 'text'"
        
        if not isinstance(data["text"], str) or not data["text"].strip():
            return False, "Поле 'text' должно быть непустой строкой"
    
    if "scheduled_at" not in data:
        return False, "Отсутствует поле 'scheduled_at'"
    
    # Проверка scheduled_at
    try:
        scheduled_dt = parse_scheduled_at(data["scheduled_at"])
    except ValueError as e:
        return False, str(e)
    
    # Проверка media (опционально)
    if "media" in data:
        if not isinstance(data["media"], list):
            return False, "Поле 'media' должно быть массивом"
        
        indices = set()
        for i, item in enumerate(data["media"]):
            if not isinstance(item, dict):
                return False, f"Элемент media[{i}] должен быть объектом"
            
            if "kind" not in item:
                return False, f"Элемент media[{i}] должен содержать поле 'kind'"
            
            if item["kind"] not in ["photo", "video"]:
                return False, f"Элемент media[{i}]: 'kind' должен быть 'photo' или 'video'"
            
            if "type" not in item:
                return False, f"Элемент media[{i}] должен содержать поле 'type'"
            
            if item["type"] not in ["local", "url", "file_id"]:
                return False, f"Элемент media[{i}]: 'type' должен быть 'local', 'url' или 'file_id'"
            
            if "index" not in item:
                return False, f"Элемент media[{i}] должен содержать поле 'index'"
            
            if not isinstance(item["index"], int) or item["index"] < 1:
                return False, f"Элемент media[{i}]: 'index' должен быть положительным числом"
            
            if item["index"] in indices:
                return False, f"Элемент media[{i}]: индекс {item['index']} уже используется"
            indices.add(item["index"])
            
            if item["type"] in ["url", "file_id"]:
                if "value" not in item:
                    return False, f"Элемент media[{i}]: для type='{item['type']}' требуется поле 'value'"
    
    # Проверка buttons (опционально)
    if "buttons" in data:
        if not isinstance(data["buttons"], list):
            return False, "Поле 'buttons' должно быть массивом"
        
        for i, btn in enumerate(data["buttons"]):
            if not isinstance(btn, dict):
                return False, f"Элемент buttons[{i}] должен быть объектом"
            
            if "text" not in btn or "url" not in btn:
                return False, f"Элемент buttons[{i}] должен содержать поля 'text' и 'url'"
    
    return True, None


async def save_local_media(
    bot: Bot,
    message: Message,
    post_id: int,
    index: int,
    kind: str
) -> Optional[str]:
    """
    Save local media file to disk.
    
    Args:
        bot: Bot instance
        message: Message with media
        post_id: Post ID
        index: Media index
        kind: 'photo' or 'video'
    
    Returns:
        Path to saved file or None if error
    """
    media_dir = BASE_MEDIA_DIR / str(post_id) / "files"
    media_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        if kind == "photo" and message.photo:
            file_info = await bot.get_file(message.photo[-1].file_id)
            ext = Path(file_info.file_path).suffix or ".jpg"
            filename = f"{index}_photo{ext}"
        elif kind == "video" and message.video:
            file_info = await bot.get_file(message.video.file_id)
            ext = Path(file_info.file_path).suffix or ".mp4"
            filename = f"{index}_video{ext}"
        else:
            return None
        
        file_path = media_dir / filename
        await bot.download_file(file_info.file_path, destination=file_path)
        
        # Возвращаем относительный путь
        return str(file_path)
    except Exception as e:
        logger.error(f"Ошибка при сохранении медиа для поста #{post_id}: {e}")
        return None


def delete_scheduled_media_folder(post_id: int) -> bool:
    """
    Delete media folder for scheduled post.
    
    Args:
        post_id: Post ID
    
    Returns:
        True if deleted, False if error
    """
    try:
        media_dir = BASE_MEDIA_DIR / str(post_id)
        if media_dir.exists():
            shutil.rmtree(media_dir)
            logger.info(f"Удалена папка медиа для поста #{post_id}")
            return True
        return False
    except Exception as e:
        logger.error(f"Ошибка при удалении папки медиа для поста #{post_id}: {e}")
        return False


async def cancel_schedule_with_cleanup(state: FSMContext) -> None:
    """
    Cancel schedule creation and cleanup: delete post from DB and media folder if exists.
    
    Args:
        state: FSM context
    """
    data = await state.get_data()
    post_id = data.get("post_id")
    
    if post_id:
        # Удаляем пост из БД
        try:
            await db.delete_scheduled_broadcast(post_id)
            logger.info(f"Пост #{post_id} удален из БД при отмене")
        except Exception as e:
            logger.error(f"Ошибка при удалении поста #{post_id} из БД: {e}")
        
        # Удаляем папку с медиа, если она существует
        delete_scheduled_media_folder(post_id)
    
    await state.clear()


@router.message(Command("schedule"))
async def cmd_schedule(message: Message):
    """Main schedule menu command."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    keyboard = get_schedule_menu_keyboard()
    
    # Получаем статистику постов
    all_posts = await db.get_scheduled_broadcasts()
    active_posts = [p for p in all_posts if p["status"] not in ["sent", "cancelled"]]
    
    status_counts = {}
    for post in active_posts:
        status = post["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    
    text = "📅 *Управление расписанием постов*\n\n"
    text += "📊 *Статистика:*\n"
    text += f"• Всего активных: {len(active_posts)}\n"
    
    status_emoji = {
        "pending": "⏳",
        "awaiting_media": "📤",
        "failed": "❌"
    }
    
    for status, count in status_counts.items():
        emoji = status_emoji.get(status, "❓")
        text += f"• {emoji} {status}: {count}\n"
    
    text += "\nВыберите действие:"
    
    await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(lambda c: c.data == "schedule_menu_refresh")
async def schedule_menu_refresh(callback: CallbackQuery):
    """Refresh schedule menu."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав.", show_alert=True)
        return
    
    keyboard = get_schedule_menu_keyboard()
    
    # Получаем статистику постов
    all_posts = await db.get_scheduled_broadcasts()
    active_posts = [p for p in all_posts if p["status"] not in ["sent", "cancelled"]]
    
    status_counts = {}
    for post in active_posts:
        status = post["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    
    text = "📅 *Управление расписанием постов*\n\n"
    text += "📊 *Статистика:*\n"
    text += f"• Всего активных: {len(active_posts)}\n"
    
    status_emoji = {
        "pending": "⏳",
        "awaiting_media": "📤",
        "failed": "❌"
    }
    
    for status, count in status_counts.items():
        emoji = status_emoji.get(status, "❓")
        text += f"• {emoji} {status}: {count}\n"
    
    text += "\nВыберите действие:"
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
    
    await callback.answer()


@router.callback_query(lambda c: c.data == "schedule_menu_add")
async def schedule_menu_add(callback: CallbackQuery, state: FSMContext):
    """Start schedule creation from menu."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав.", show_alert=True)
        return
    
    await state.set_state(ADMIN_States.SCHEDULE_TEXT)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data="schedule_cancel")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад в меню", callback_data="schedule_menu_back")
        ]
    ])
    
    await callback.message.edit_text(
        "📝 Введите текст поста (поддерживается MarkdownV2):\n\n"
        "💡 Вы можете:\n"
        "• Отправить текст напрямую\n"
        "• Отправить файл .txt или .md с текстом (рекомендуется для сохранения разметки)",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "schedule_menu_list")
async def schedule_menu_list(callback: CallbackQuery):
    """Show list of scheduled posts."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав.", show_alert=True)
        return
    
    all_posts = await db.get_scheduled_broadcasts()
    posts = [post for post in all_posts if post["status"] != "sent"]
    
    if not posts:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔙 Назад в меню", callback_data="schedule_menu_back")
            ]
        ])
        try:
            await callback.message.edit_text("📋 Нет запланированных постов.", reply_markup=keyboard)
        except TelegramBadRequest:
            await callback.message.answer("📋 Нет запланированных постов.", reply_markup=keyboard)
        await callback.answer()
        return
    
    status_emoji = {
        "pending": "⏳",
        "awaiting_media": "📤",
        "sent": "✅",
        "failed": "❌",
        "cancelled": "🚫"
    }
    
    text = "📋 *Запланированные посты:*\n\n"
    
    for post in posts[:20]:  # Показываем первые 20
        emoji = status_emoji.get(post["status"], "❓")
        scheduled_dt = parse_scheduled_at(post["scheduled_at"])
        text += f"{emoji} *#{post['id']}* - {scheduled_dt.strftime('%d.%m.%Y %H:%M')} - `{post['status']}`\n"
    
    if len(posts) > 20:
        text += f"\n... и ещё {len(posts) - 20} постов"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 Назад в меню", callback_data="schedule_menu_back")
        ]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
    
    await callback.answer()


@router.callback_query(lambda c: c.data == "schedule_menu_show")
async def schedule_menu_show(callback: CallbackQuery):
    """Show post selection menu for viewing."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав.", show_alert=True)
        return
    
    all_posts = await db.get_scheduled_broadcasts()
    posts = [post for post in all_posts if post["status"] != "sent"]
    
    if not posts:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔙 Назад в меню", callback_data="schedule_menu_back")
            ]
        ])
        try:
            await callback.message.edit_text("📋 Нет запланированных постов для просмотра.", reply_markup=keyboard)
        except TelegramBadRequest:
            await callback.message.answer("📋 Нет запланированных постов для просмотра.", reply_markup=keyboard)
        await callback.answer()
        return
    
    # Создаем кнопки для выбора поста
    buttons = []
    for post in posts[:10]:  # Показываем первые 10
        scheduled_dt = parse_scheduled_at(post["scheduled_at"])
        status_emoji = {
            "pending": "⏳",
            "awaiting_media": "📤",
            "failed": "❌",
            "cancelled": "🚫"
        }
        emoji = status_emoji.get(post["status"], "❓")
        button_text = f"{emoji} #{post['id']} - {scheduled_dt.strftime('%d.%m %H:%M')}"
        buttons.append([
            InlineKeyboardButton(text=button_text, callback_data=f"schedule_show_{post['id']}")
        ])
    
    buttons.append([
        InlineKeyboardButton(text="🔙 Назад в меню", callback_data="schedule_menu_back")
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    text = "👁️ *Выберите пост для просмотра:*\n\n"
    text += f"Показано {min(10, len(posts))} из {len(posts)} постов"
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
    
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("schedule_show_"))
async def schedule_show_post(callback: CallbackQuery):
    """Show specific post by ID."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав.", show_alert=True)
        return
    
    try:
        post_id = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка при получении ID поста.", show_alert=True)
        return
    
    post = await db.get_scheduled_broadcast_by_id(post_id)
    
    if not post:
        await callback.answer(f"❌ Пост #{post_id} не найден.", show_alert=True)
        return
    
    scheduled_dt = parse_scheduled_at(post["scheduled_at"])
    created_dt = datetime.fromisoformat(post["created_at"])
    
    text = f"📄 *Пост #{post_id}*\n\n"
    
    # Показываем текст поста (первые 300 символов)
    post_text = post['text']
    if len(post_text) > 300:
        text += f"📝 *Текст:* {post_text[:300]}...\n\n"
    else:
        text += f"📝 *Текст:* {post_text}\n\n"
    
    status_emoji = {
        "pending": "⏳",
        "awaiting_media": "📤",
        "sent": "✅",
        "failed": "❌",
        "cancelled": "🚫"
    }
    emoji = status_emoji.get(post["status"], "❓")
    
    text += f"📅 *Запланирован:* {scheduled_dt.strftime('%d.%m.%Y %H:%M')}\n"
    text += f"🕐 *Создан:* {created_dt.strftime('%d.%m.%Y %H:%M')}\n"
    text += f"📊 *Статус:* {emoji} `{post['status']}`\n"
    text += f"👤 *Создал:* {post['created_by']}\n\n"
    
    if post.get("media"):
        text += f"🖼️ *Медиа:* {len(post['media'])} элементов\n"
        for media in sorted(post["media"], key=lambda x: x.get("index", 0)):
            text += f"  • {media.get('kind')} (index={media.get('index')}, type={media.get('type')})\n"
    
    if post.get("buttons"):
        text += f"\n🔘 *Кнопки:* {len(post['buttons'])} шт.\n"
        for btn in post["buttons"]:
            text += f"  • {btn.get('text')}: {btn.get('url')}\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 Назад к списку", callback_data="schedule_menu_show")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад в меню", callback_data="schedule_menu_back")
        ]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
    
    await callback.answer()


@router.callback_query(lambda c: c.data == "schedule_menu_cancel")
async def schedule_menu_cancel(callback: CallbackQuery):
    """Show post selection menu for cancellation."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав.", show_alert=True)
        return
    
    all_posts = await db.get_scheduled_broadcasts()
    posts = [post for post in all_posts if post["status"] not in ["sent", "cancelled"]]
    
    if not posts:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔙 Назад в меню", callback_data="schedule_menu_back")
            ]
        ])
        try:
            await callback.message.edit_text("📋 Нет постов для отмены.", reply_markup=keyboard)
        except TelegramBadRequest:
            await callback.message.answer("📋 Нет постов для отмены.", reply_markup=keyboard)
        await callback.answer()
        return
    
    # Создаем кнопки для выбора поста
    buttons = []
    for post in posts[:10]:  # Показываем первые 10
        scheduled_dt = parse_scheduled_at(post["scheduled_at"])
        status_emoji = {
            "pending": "⏳",
            "awaiting_media": "📤",
            "failed": "❌"
        }
        emoji = status_emoji.get(post["status"], "❓")
        button_text = f"{emoji} #{post['id']} - {scheduled_dt.strftime('%d.%m %H:%M')}"
        buttons.append([
            InlineKeyboardButton(text=button_text, callback_data=f"schedule_cancel_{post['id']}")
        ])
    
    buttons.append([
        InlineKeyboardButton(text="🔙 Назад в меню", callback_data="schedule_menu_back")
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    text = "❌ *Выберите пост для отмены:*\n\n"
    text += f"Показано {min(10, len(posts))} из {len(posts)} постов"
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
    
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("schedule_cancel_"))
async def schedule_cancel_post(callback: CallbackQuery):
    """Cancel specific post by ID."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав.", show_alert=True)
        return
    
    try:
        post_id = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка при получении ID поста.", show_alert=True)
        return
    
    post = await db.get_scheduled_broadcast_by_id(post_id)
    
    if not post:
        await callback.answer(f"❌ Пост #{post_id} не найден.", show_alert=True)
        return
    
    if post["status"] in ["sent", "cancelled"]:
        await callback.answer(f"❌ Пост #{post_id} уже {post['status']}.", show_alert=True)
        return
    
    await db.cancel_scheduled_broadcast(post_id)
    
    scheduled_dt = parse_scheduled_at(post["scheduled_at"])
    text = f"✅ *Пост #{post_id} отменен*\n\n"
    text += f"📅 Был запланирован на: {scheduled_dt.strftime('%d.%m.%Y %H:%M')}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 Назад к списку", callback_data="schedule_menu_cancel")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад в меню", callback_data="schedule_menu_back")
        ]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
    
    await callback.answer("✅ Пост отменен")


@router.callback_query(lambda c: c.data == "schedule_menu_back")
async def schedule_menu_back(callback: CallbackQuery, state: FSMContext):
    """Return to main schedule menu."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав.", show_alert=True)
        return
    
    # Проверяем, есть ли активное состояние создания поста
    current_state = await state.get_state()
    if current_state in [ADMIN_States.SCHEDULE_TEXT, ADMIN_States.SCHEDULE_JSON, ADMIN_States.LOAD_LOCAL_MEDIA]:
        # Если есть незавершенное создание поста, очищаем состояние
        await cancel_schedule_with_cleanup(state)
    
    keyboard = get_schedule_menu_keyboard()
    
    # Получаем статистику постов
    all_posts = await db.get_scheduled_broadcasts()
    active_posts = [p for p in all_posts if p["status"] not in ["sent", "cancelled"]]
    
    status_counts = {}
    for post in active_posts:
        status = post["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    
    text = "📅 *Управление расписанием постов*\n\n"
    text += "📊 *Статистика:*\n"
    text += f"• Всего активных: {len(active_posts)}\n"
    
    status_emoji = {
        "pending": "⏳",
        "awaiting_media": "📤",
        "failed": "❌"
    }
    
    for status, count in status_counts.items():
        emoji = status_emoji.get(status, "❓")
        text += f"• {emoji} {status}: {count}\n"
    
    text += "\nВыберите действие:"
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
    
    await callback.answer()


@router.callback_query(lambda c: c.data == "schedule_menu_exit")
async def schedule_menu_exit(callback: CallbackQuery, state: FSMContext):
    """Exit schedule menu and reset state."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав.", show_alert=True)
        return
    
    current_state = await state.get_state()
    if current_state in [ADMIN_States.SCHEDULE_TEXT, ADMIN_States.SCHEDULE_JSON, ADMIN_States.LOAD_LOCAL_MEDIA]:
        await cancel_schedule_with_cleanup(state)
    else:
        await state.clear()
    
    try:
        await callback.message.edit_text("📴 Меню расписания закрыто.")
    except TelegramBadRequest:
        await callback.message.answer("📴 Меню расписания закрыто.")
    
    await callback.answer("Меню закрыто")


@router.message(Command("schedule_add"))
async def cmd_schedule_add(message: Message, state: FSMContext):
    """Start schedule creation process."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    await state.set_state(ADMIN_States.SCHEDULE_TEXT)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data="schedule_cancel")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад в меню", callback_data="schedule_menu_back")
        ]
    ])
    
    await message.answer(
        "📝 Введите текст поста (поддерживается MarkdownV2):\n\n"
        "💡 Вы можете:\n"
        "• Отправить текст напрямую\n"
        "• Отправить файл .txt или .md с текстом (рекомендуется для сохранения разметки)",
        reply_markup=keyboard
    )


@router.callback_query(lambda c: c.data == "schedule_cancel")
async def cancel_schedule(callback: CallbackQuery, state: FSMContext):
    """Cancel schedule creation."""
    await cancel_schedule_with_cleanup(state)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 Назад в меню", callback_data="schedule_menu_back")
        ]
    ])
    
    try:
        await callback.message.edit_text("❌ Создание поста отменено.", reply_markup=keyboard)
    except TelegramBadRequest:
        await callback.message.answer("❌ Создание поста отменено.", reply_markup=keyboard)
    await callback.answer()


@router.message(lambda m: m.text and m.text.startswith("/") and not m.text.startswith("/schedule"), ADMIN_States.SCHEDULE_TEXT)
async def cancel_text_on_command(message: Message, state: FSMContext):
    """Cancel text input if another command is sent."""
    await cancel_schedule_with_cleanup(state)
    await message.answer("❌ Ввод текста отменен из-за вызова другой команды.")


def _parse_markdown_error(error_message: str, text: str) -> dict:
    """
    Парсит ошибку от Telegram API и находит проблемное место в тексте.
    
    Args:
        error_message: Сообщение об ошибке от Telegram
        text: Текст, в котором ищем ошибку
        
    Returns:
        Словарь с информацией об ошибке:
        - description: Описание ошибки
        - position: Позиция проблемного символа (или None)
        - context: Контекст вокруг ошибки
        - suggestion: Совет по исправлению
    """
    result = {
        'description': error_message,
        'position': None,
        'context': '',
        'suggestion': 'Проверьте правильность экранирования спецсимволов.'
    }
    
    # Ищем информацию о проблемном символе
    # Пример: "Character '=' is reserved and must be escaped with the preceding '\'"
    char_match = re.search(r"Character '([^']+)'", error_message)
    if char_match:
        problem_char = char_match.group(1)
        result['description'] = f"Символ '{problem_char}' не экранирован"
        result['suggestion'] = f"Добавьте обратный слэш перед '{problem_char}': \\{problem_char}"
        
        # Ищем незаэкранированный символ в тексте
        # Ищем символ, который не идет после обратного слэша
        pattern = rf'(?<!\\){re.escape(problem_char)}'
        matches = list(re.finditer(pattern, text))
        
        if matches:
            # Берем первое вхождение
            match = matches[0]
            pos = match.start()
            result['position'] = pos
            
            # Формируем контекст (3 строки до и после, или 100 символов)
            lines = text.split('\n')
            line_num = 0
            char_count = 0
            
            # Находим номер строки с ошибкой
            for i, line in enumerate(lines):
                if char_count + len(line) >= pos:
                    line_num = i
                    break
                char_count += len(line) + 1  # +1 для \n
            
            # Берем 2 строки до и после
            start_line = max(0, line_num - 2)
            end_line = min(len(lines), line_num + 3)
            context_lines = lines[start_line:end_line]
            
            # Находим позицию в строке
            line_start_pos = char_count - len(lines[line_num]) if line_num > 0 else 0
            pos_in_line = pos - line_start_pos
            
            # Формируем контекст с указателем
            context_parts = []
            for i, line in enumerate(context_lines):
                actual_line_num = start_line + i
                if actual_line_num == line_num:
                    # Показываем строку с ошибкой и указателем
                    context_parts.append(f"{actual_line_num + 1:3d} | {line}")
                    # Указатель на проблемный символ
                    marker_pos = min(pos_in_line, len(line))
                    marker_line = " " * (5 + marker_pos) + "👉"
                    context_parts.append(f"{marker_line} Здесь символ '{problem_char}' не экранирован")
                else:
                    context_parts.append(f"{actual_line_num + 1:3d} | {line}")
            
            result['context'] = '\n'.join(context_parts)
    else:
        # Если не нашли конкретный символ, проверяем общие ошибки парсинга
        if "can't parse entities" in error_message.lower():
            result['description'] = "Ошибка парсинга Markdown-разметки"
            result['suggestion'] = "Проверьте правильность закрытия всех тегов (*, _, __, ~, ||, `)"
    
    return result


@router.message(ADMIN_States.SCHEDULE_TEXT)
async def process_schedule_text(message: Message, state: FSMContext, bot: Bot):
    """Process text input and request JSON."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        await state.clear()
        return
    
    text = message.text or message.caption or ""
    
    # Проверяем, есть ли документ (txt или md файл)
    if message.document:
        file_name = message.document.file_name or ""
        file_ext = Path(file_name).suffix.lower()
        
        if file_ext in ['.txt', '.md']:
            try:
                # Скачиваем файл
                file_info = await bot.get_file(message.document.file_id)
                # Создаем временный файл для скачивания
                temp_file = Path(f"/tmp/schedule_{message.from_user.id}_{file_info.file_id}.tmp")
                await bot.download_file(file_info.file_path, destination=temp_file)
                
                # Читаем содержимое файла
                with open(temp_file, 'r', encoding='utf-8') as f:
                    text = f.read()
                
                # Удаляем временный файл
                temp_file.unlink()
                
                logger.info(f"[SCHEDULE] Админ {message.from_user.id} отправил файл {file_name}")
            except Exception as e:
                logger.error(f"[SCHEDULE] Ошибка при чтении файла: {e}")
                await message.answer(f"❌ Ошибка при чтении файла: {e}")
                return
    
    if not text.strip():
        await message.answer("❌ Текст не может быть пустым. Попробуйте снова.")
        return
    
    # Текст уже правильный markdownv2, сохраняем как есть
    # Сохраняем оригинальный текст БЕЗ обработки (как в /broadcast)
    # Текст будет отправлен с parse_mode="MarkdownV2" и sanitize=False
    await state.update_data(schedule_text=text)
    
    # Показываем предпросмотр текста в MarkdownV2 (как в /broadcast)
    from core.markdown_v2 import send_md_v2
    
    # Формируем текст предпросмотра (первые 500 символов, как в /broadcast)
    preview_header = sanitize_markdown_v2("📋 Предпросмотр сообщения:")
    user_text_preview = text[:500] + ('...' if len(text) > 500 else '')
    preview_text = f"{preview_header}\n\n{user_text_preview}"
    
    try:
        await send_md_v2(
            message,
            preview_text
        )
    except TelegramBadRequest as e:
        # Ошибка парсинга - показываем ошибку без форматирования (как в /broadcast)
        error_message = str(e)
        logger.warning(f"[SCHEDULE] Ошибка парсинга MarkdownV2: {error_message}")
        error_info = _parse_markdown_error(error_message, text)
        
        # Формируем сообщение об ошибке
        error_text = "❌ Ошибка в Markdown-форматировании!\n\n"
        error_text += f"📝 {error_info['description']}\n\n"
        
        if error_info.get('position') is not None:
            error_text += f"📍 Проблема найдена в тексте:\n"
            error_text += f"```\n{error_info['context']}\n```\n\n"
            error_text += f"💡 Совет: {error_info['suggestion']}"
        else:
            error_text += f"💡 Совет: {error_info['suggestion']}"
        
        await message.answer(error_text, parse_mode=None)
        return
    
    await state.set_state(ADMIN_States.SCHEDULE_JSON)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data="schedule_cancel")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад в меню", callback_data="schedule_menu_back")
        ]
    ])
    
    await message.answer(
        "✅ Текст принят!\n\n"
        "📝 Теперь пришли JSON:\n\n"
        "Пример:\n"
        "```json\n"
        '{\n'
        '  "media": [\n'
        '    {\n'
        '      "kind": "photo",\n'
        '      "type": "local",\n'
        '      "index": 1\n'
        '    },\n'
        '    {\n'
        '      "kind": "photo",\n'
        '      "type": "local",\n'
        '      "index": 2\n'
        '    }\n'
        '  ],\n'
        '  "buttons": [\n'
        '    {\n'
        '      "text": "Перейти",\n'
        '      "url": "https://xdataplus.ru"\n'
        '    }\n'
        '  ],\n'
        '  "scheduled_at": "2025-12-04T17:00:00"\n'
        '}\n'
        "```",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


@router.message(lambda m: m.text and m.text.startswith("/") and not m.text.startswith("/schedule"), ADMIN_States.SCHEDULE_JSON)
async def cancel_json_on_command(message: Message, state: FSMContext):
    """Cancel JSON input if another command is sent."""
    await cancel_schedule_with_cleanup(state)
    await message.answer("❌ Ввод JSON отменен из-за вызова другой команды.")


@router.message(ADMIN_States.SCHEDULE_JSON)
async def process_schedule_json(message: Message, state: FSMContext, bot: Bot):
    """Process JSON and create scheduled post."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        await state.clear()
        return
    
    # Получаем текст из состояния
    state_data = await state.get_data()
    text = state_data.get("schedule_text")
    
    if not text:
        await message.answer("❌ Текст не найден. Начните заново с /schedule_add")
        await state.clear()
        return
    
    # Парсим JSON
    try:
        data = json.loads(message.text)
    except json.JSONDecodeError as e:
        await message.answer(f"❌ Ошибка парсинга JSON: {e}")
        return
    
    # Валидация (без проверки text, так как он уже есть)
    is_valid, error_msg = validate_schedule_json(data, require_text=False)
    if not is_valid:
        await message.answer(f"❌ Ошибка валидации: {error_msg}")
        return
    
    # Проверяем время
    scheduled_dt = parse_scheduled_at(data["scheduled_at"])
    now_dt = datetime.now(UTC_PLUS_3)
    
    # Определяем статус
    media = data.get("media", [])
    local_media = [m for m in media if m.get("type") == "local"]
    status = "awaiting_media" if local_media else "pending"
    
    # Создаем пост в БД
    try:
        post_id = await db.create_scheduled_broadcast(
            text=text,
            media=media,
            buttons=data.get("buttons", []),
            scheduled_at=format_scheduled_at(scheduled_dt),
            created_by=message.from_user.id,
            status=status
        )
    except Exception as e:
        logger.error(f"Ошибка при создании поста: {e}")
        await message.answer(f"❌ Ошибка при создании поста: {e}")
        await state.clear()
        return
    
    # Если есть локальные медиа, начинаем загрузку
    if local_media:
        # Сортируем по index
        local_media.sort(key=lambda x: x["index"])
        
        await state.update_data(
            post_id=post_id,
            local_media=local_media,
            current_media_index=0,
            media_data=media.copy()
        )
        await state.set_state(ADMIN_States.LOAD_LOCAL_MEDIA)
        
        # Запрашиваем первое медиа
        first_media = local_media[0]
        emoji = "📸" if first_media["kind"] == "photo" else "🎥"
        await message.answer(
            f"🆔 Пост **#{post_id}** создан\n"
            f"Запланирован на: `{scheduled_dt.strftime('%d.%m.%Y %H:%M')}`\n\n"
            f"{emoji} Отправь, пожалуйста, **{first_media['kind']} №{first_media['index']}** (index = {first_media['index']}) для поста **#{post_id}**.",
            parse_mode="Markdown"
        )
    else:
        # Нет локальных медиа - пост готов
        await state.clear()
        
        # Если время в прошлом - публикуем сразу
        if scheduled_dt <= now_dt:
            post = await db.get_scheduled_broadcast_by_id(post_id)
            await message.answer(
                f"🆔 Пост **#{post_id}** создан\n"
                f"Время в прошлом - публикую мгновенно...",
                parse_mode="Markdown"
            )
            await publish_scheduled_broadcast(bot, post)
        else:
            await message.answer(
                f"✅ Пост **#{post_id}** создан\n"
                f"Запланирован на: `{scheduled_dt.strftime('%d.%m.%Y %H:%M')}`\n"
                f"Статус: `pending` (ожидает отправки)",
                parse_mode="Markdown"
            )


@router.message(lambda m: m.text and m.text.startswith("/") and not m.text.startswith("/schedule"), ADMIN_States.LOAD_LOCAL_MEDIA)
async def cancel_media_upload_on_command(message: Message, state: FSMContext):
    """Cancel media upload if another command is sent."""
    await cancel_schedule_with_cleanup(state)
    await message.answer("❌ Загрузка медиа отменена из-за вызова другой команды.")


@router.message(ADMIN_States.LOAD_LOCAL_MEDIA)
async def process_local_media(message: Message, state: FSMContext, bot: Bot):
    """Process local media upload."""
    if not is_admin(message.from_user.id):
        await cancel_schedule_with_cleanup(state)
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    data = await state.get_data()
    post_id = data.get("post_id")
    local_media = data.get("local_media", [])
    current_index = data.get("current_media_index", 0)
    media_data = data.get("media_data", [])
    
    if current_index >= len(local_media):
        # Все медиа загружены
        await state.clear()
        
        # Обновляем пост в БД
        await db.update_scheduled_broadcast(post_id, media=media_data, status="pending")
        
        post = await db.get_scheduled_broadcast_by_id(post_id)
        scheduled_dt = parse_scheduled_at(post["scheduled_at"])
        
        await message.answer(
            f"✅ Все медиа для поста **#{post_id}** получены.\n"
            f"Пост запланирован на: `{scheduled_dt.strftime('%d.%m.%Y %H:%M')}`\n"
            f"Статус: `pending` (ожидает отправки).",
            parse_mode="Markdown"
        )
        return
    
    current_media = local_media[current_index]
    expected_kind = current_media["kind"]
    expected_index = current_media["index"]
    
    # Проверяем тип медиа
    if expected_kind == "photo" and not message.photo:
        await message.answer("❌ Здесь нужно фото. Попробуй ещё раз отправить именно фото.")
        return
    
    if expected_kind == "video" and not message.video:
        await message.answer("❌ Здесь нужно видео. Попробуй ещё раз отправить именно видео.")
        return
    
    # Сохраняем медиа
    file_path = await save_local_media(bot, message, post_id, expected_index, expected_kind)
    
    if not file_path:
        await message.answer("❌ Ошибка при сохранении медиа. Попробуй ещё раз.")
        return
    
    # Обновляем media_data
    for i, media_item in enumerate(media_data):
        if media_item.get("index") == expected_index and media_item.get("type") == "local":
            media_data[i]["value"] = file_path
            break
    
    # Переходим к следующему медиа
    current_index += 1
    await state.update_data(
        current_media_index=current_index,
        media_data=media_data
    )
    
    if current_index < len(local_media):
        # Запрашиваем следующее медиа
        next_media = local_media[current_index]
        emoji = "📸" if next_media["kind"] == "photo" else "🎥"
        await message.answer(
            f"{emoji} Теперь отправь **{next_media['kind']} №{next_media['index']}** (index = {next_media['index']}) для поста **#{post_id}**.",
            parse_mode="Markdown"
        )
    else:
        # Все медиа загружены
        await state.clear()
        
        # Обновляем пост в БД
        await db.update_scheduled_broadcast(post_id, media=media_data, status="pending")
        
        post = await db.get_scheduled_broadcast_by_id(post_id)
        scheduled_dt = parse_scheduled_at(post["scheduled_at"])
        now_dt = datetime.now(UTC_PLUS_3)
        
        # Если время в прошлом - публикуем сразу
        if scheduled_dt <= now_dt:
            await message.answer(
                f"✅ Все медиа для поста **#{post_id}** получены.\n"
                f"Время в прошлом - публикую мгновенно...",
                parse_mode="Markdown"
            )
            await publish_scheduled_broadcast(bot, post)
        else:
            await message.answer(
                f"✅ Все медиа для поста **#{post_id}** получены.\n"
                f"Пост запланирован на: `{scheduled_dt.strftime('%d.%m.%Y %H:%M')}`\n"
                f"Статус: `pending` (ожидает отправки).",
                parse_mode="Markdown"
            )


@router.message(Command("scheduled_list"))
async def cmd_scheduled_list(message: Message):
    """List all scheduled broadcasts."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    all_posts = await db.get_scheduled_broadcasts()
    
    # Фильтруем только запланированные посты (исключаем sent)
    posts = [post for post in all_posts if post["status"] != "sent"]
    
    if not posts:
        await message.answer("📋 Нет запланированных постов.")
        return
    
    # Группируем по статусу
    status_emoji = {
        "pending": "⏳",
        "awaiting_media": "📤",
        "sent": "✅",
        "failed": "❌",
        "cancelled": "🚫"
    }
    
    text = "📋 Запланированные посты:\n\n"
    
    for post in posts:
        emoji = status_emoji.get(post["status"], "❓")
        scheduled_dt = parse_scheduled_at(post["scheduled_at"])
        text += f"{emoji} **#{post['id']}** - {scheduled_dt.strftime('%d.%m.%Y %H:%M')} - {post['status']}\n"
    
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("scheduled_cancel"))
async def cmd_scheduled_cancel(message: Message):
    """Cancel scheduled broadcast by ID."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    try:
        post_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.answer("❌ Использование: /scheduled_cancel <id>")
        return
    
    post = await db.get_scheduled_broadcast_by_id(post_id)
    
    if not post:
        await message.answer(f"❌ Пост #{post_id} не найден.")
        return
    
    if post["status"] in ["sent", "cancelled"]:
        await message.answer(f"❌ Пост #{post_id} уже {post['status']}.")
        return
    
    await db.cancel_scheduled_broadcast(post_id)
    await message.answer(f"✅ Пост #{post_id} отменен.")


async def _show_scheduled_post(message: Message, post_id: int):
    """Helper function to show scheduled post by ID."""
    post = await db.get_scheduled_broadcast_by_id(post_id)
    
    if not post:
        await message.answer(f"❌ Пост #{post_id} не найден.")
        return
    
    scheduled_dt = parse_scheduled_at(post["scheduled_at"])
    created_dt = datetime.fromisoformat(post["created_at"])
    
    # Формируем текст без Markdown для безопасности
    text = f"📄 Пост #{post_id}\n\n"
    
    # Показываем текст поста (первые 200 символов)
    post_text = post['text']
    if len(post_text) > 200:
        text += f"📝 Текст: {post_text[:200]}...\n\n"
    else:
        text += f"📝 Текст: {post_text}\n\n"
    
    text += f"📅 Запланирован: {scheduled_dt.strftime('%d.%m.%Y %H:%M')}\n"
    text += f"🕐 Создан: {created_dt.strftime('%d.%m.%Y %H:%M')}\n"
    text += f"📊 Статус: {post['status']}\n"
    text += f"👤 Создал: {post['created_by']}\n\n"
    
    if post.get("media"):
        text += f"🖼️ Медиа: {len(post['media'])} элементов\n"
        for media in sorted(post["media"], key=lambda x: x.get("index", 0)):
            text += f"  - {media.get('kind')} (index={media.get('index')}, type={media.get('type')})\n"
    
    if post.get("buttons"):
        text += f"\n🔘 Кнопки: {len(post['buttons'])} шт.\n"
        for btn in post["buttons"]:
            text += f"  - {btn.get('text')}: {btn.get('url')}\n"
    
    await message.answer(text)


@router.message(Command("scheduled_show"))
async def cmd_scheduled_show(message: Message, state: FSMContext):
    """Show scheduled broadcast preview by ID."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    # Проверяем, есть ли аргумент
    try:
        post_id = int(message.text.split()[1])
        # Если аргумент есть - показываем сразу
        await _show_scheduled_post(message, post_id)
    except (IndexError, ValueError):
        # Если аргумента нет - запрашиваем ID
        await state.set_state(ADMIN_States.SCHEDULE_SHOW_ID)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="❌ Отмена", callback_data="schedule_show_cancel")
            ],
            [
                InlineKeyboardButton(text="🔙 Назад в меню", callback_data="schedule_menu_back")
            ]
        ])
        
        await message.answer(
            "📋 Введите номер поста для просмотра:",
            reply_markup=keyboard
        )


@router.callback_query(lambda c: c.data == "schedule_show_cancel")
async def cancel_schedule_show(callback: CallbackQuery, state: FSMContext):
    """Cancel schedule show."""
    await state.clear()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 Назад в меню", callback_data="schedule_menu_back")
        ]
    ])
    
    try:
        await callback.message.edit_text("❌ Просмотр поста отменен.", reply_markup=keyboard)
    except TelegramBadRequest:
        await callback.message.answer("❌ Просмотр поста отменен.", reply_markup=keyboard)
    await callback.answer()


@router.message(lambda m: m.text and m.text.startswith("/") and not m.text.startswith("/scheduled"), ADMIN_States.SCHEDULE_SHOW_ID)
async def cancel_show_on_command(message: Message, state: FSMContext):
    """Cancel show if another command is sent."""
    await state.clear()
    await message.answer("❌ Просмотр поста отменен из-за вызова другой команды.")


@router.message(ADMIN_States.SCHEDULE_SHOW_ID)
async def process_schedule_show_id(message: Message, state: FSMContext):
    """Process post ID for showing."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        await state.clear()
        return
    
    try:
        post_id = int(message.text.strip())
        await state.clear()
        await _show_scheduled_post(message, post_id)
    except ValueError:
        await message.answer("❌ Пожалуйста, введите числовой ID поста.")

