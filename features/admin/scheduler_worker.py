"""Scheduler worker for automatic publishing of scheduled broadcasts."""
import asyncio
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InputMediaPhoto, InputMediaVideo, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from loguru import logger

from core.database import db
from core.message_splitter import send_long_markdown

# UTC+3 timezone
UTC_PLUS_3 = timezone(timedelta(hours=3))

# Base directory for scheduled media
BASE_MEDIA_DIR = Path("features/broadcast_media")


async def publish_scheduled_broadcast(bot: Bot, post: Dict) -> bool:
    """
    Publish a scheduled broadcast to all users.
    
    Args:
        bot: Bot instance
        post: Post data from database
    
    Returns:
        True if successful, False otherwise
    """
    post_id = post["id"]
    text = post["text"]
    media = post.get("media", [])
    buttons = post.get("buttons", [])
    
    logger.info(f"[SCHEDULER] Начинаю публикацию поста #{post_id}")
    
    try:
        # Получаем всех пользователей
        users = await db.get_all_users_with_info()
        
        if not users:
            logger.warning(f"[SCHEDULER] Нет пользователей для рассылки поста #{post_id}")
            await db.update_scheduled_broadcast(
                post_id,
                status="failed",
                error_message="Нет пользователей для рассылки"
            )
            return False
        
        # Сортируем медиа по index
        sorted_media = sorted(media, key=lambda x: x.get("index", 0))
        
        # Подготавливаем кнопки
        reply_markup = None
        if buttons:
            inline_buttons = []
            for btn in buttons:
                inline_buttons.append([InlineKeyboardButton(text=btn['text'], url=btn['url'])])
            reply_markup = InlineKeyboardMarkup(inline_keyboard=inline_buttons)
        
        # Отправляем всем пользователям
        success_count = 0
        error_count = 0
        
        for user in users:
            user_id = user["telegram_id"]
            
            try:
                # Отправка медиа
                if len(sorted_media) == 1:
                    # Одно медиа - отправляем с текстом
                    media_item = sorted_media[0]
                    media_value = media_item.get("value")
                    media_type = media_item.get("type")
                    media_kind = media_item.get("kind")
                    
                    if media_type == "local":
                        # Локальный файл
                        file_path = Path(media_value)
                        if not file_path.exists():
                            logger.warning(f"[SCHEDULER] Файл не найден: {file_path} для поста #{post_id}")
                            continue
                        
                        if media_kind == "photo":
                            await bot.send_photo(
                                chat_id=user_id,
                                photo=FSInputFile(file_path),
                                caption=text,
                                parse_mode=ParseMode.MARKDOWN_V2,
                                reply_markup=reply_markup
                            )
                        else:  # video
                            await bot.send_video(
                                chat_id=user_id,
                                video=FSInputFile(file_path),
                                caption=text,
                                parse_mode=ParseMode.MARKDOWN_V2,
                                reply_markup=reply_markup
                            )
                    elif media_type == "url":
                        # URL
                        if media_kind == "photo":
                            await bot.send_photo(
                                chat_id=user_id,
                                photo=media_value,
                                caption=text,
                                parse_mode=ParseMode.MARKDOWN_V2,
                                reply_markup=reply_markup
                            )
                        else:  # video
                            await bot.send_video(
                                chat_id=user_id,
                                video=media_value,
                                caption=text,
                                parse_mode=ParseMode.MARKDOWN_V2,
                                reply_markup=reply_markup
                            )
                    else:  # file_id
                        # File ID
                        if media_kind == "photo":
                            await bot.send_photo(
                                chat_id=user_id,
                                photo=media_value,
                                caption=text,
                                parse_mode=ParseMode.MARKDOWN_V2,
                                reply_markup=reply_markup
                            )
                        else:  # video
                            await bot.send_video(
                                chat_id=user_id,
                                video=media_value,
                                caption=text,
                                parse_mode=ParseMode.MARKDOWN_V2,
                                reply_markup=reply_markup
                            )
                elif len(sorted_media) > 1:
                    # Несколько медиа - отправляем медиагруппой, затем текст
                    media_group = []
                    
                    for media_item in sorted_media:
                        media_value = media_item.get("value")
                        media_type = media_item.get("type")
                        media_kind = media_item.get("kind")
                        
                        if media_type == "local":
                            # Локальный файл
                            file_path = Path(media_value)
                            if not file_path.exists():
                                logger.warning(f"[SCHEDULER] Файл не найден: {file_path} для поста #{post_id}")
                                continue
                            
                            if media_kind == "photo":
                                media_group.append(InputMediaPhoto(media=FSInputFile(file_path)))
                            else:  # video
                                media_group.append(InputMediaVideo(media=FSInputFile(file_path)))
                        elif media_type == "url":
                            # URL
                            if media_kind == "photo":
                                media_group.append(InputMediaPhoto(media=media_value))
                            else:  # video
                                media_group.append(InputMediaVideo(media=media_value))
                        else:  # file_id
                            # File ID
                            if media_kind == "photo":
                                media_group.append(InputMediaPhoto(media=media_value))
                            else:  # video
                                media_group.append(InputMediaVideo(media=media_value))
                    
                    if media_group:
                        await bot.send_media_group(chat_id=user_id, media=media_group)
                    
                    # Текст отправляем отдельно
                    if text:
                        await send_long_markdown(
                            bot=bot,
                            chat_id=user_id,
                            text=text,
                            sanitize=False,
                            reply_markup=reply_markup
                        )
                else:
                    # Только текст
                    await send_long_markdown(
                        bot=bot,
                        chat_id=user_id,
                        text=text,
                        sanitize=False,
                        reply_markup=reply_markup
                    )
                
                success_count += 1
                
                # Небольшая задержка между отправками
                await asyncio.sleep(0.05)
                
            except Exception as e:
                error_count += 1
                logger.error(f"[SCHEDULER] Ошибка при отправке поста #{post_id} пользователю {user_id}: {e}")
        
        # Обновляем статус
        sent_at = datetime.now(UTC_PLUS_3).isoformat()
        broadcast_id = f"scheduled_{post_id}_{datetime.now(UTC_PLUS_3).strftime('%Y-%m-%d_%H-%M-%S')}"
        
        await db.update_scheduled_broadcast(
            post_id,
            status="sent",
            sent_at=sent_at,
            broadcast_id=broadcast_id
        )
        
        # Удаляем папку с медиа
        media_dir = BASE_MEDIA_DIR / str(post_id)
        if media_dir.exists():
            try:
                shutil.rmtree(media_dir)
                logger.info(f"[SCHEDULER] Удалена папка медиа для поста #{post_id}")
            except Exception as e:
                logger.error(f"[SCHEDULER] Ошибка при удалении папки медиа для поста #{post_id}: {e}")
        
        logger.info(f"[SCHEDULER] Пост #{post_id} опубликован. Успешно: {success_count}, Ошибок: {error_count}")
        return True
        
    except Exception as e:
        logger.error(f"[SCHEDULER] Критическая ошибка при публикации поста #{post_id}: {e}")
        await db.update_scheduled_broadcast(
            post_id,
            status="failed",
            error_message=str(e)
        )
        return False


def get_seconds_until_next_hour(now: datetime) -> float:
    """
    Вычисляет количество секунд до начала следующего часа.
    
    Args:
        now: Текущее время в UTC+3
    
    Returns:
        Количество секунд до начала следующего часа
    """
    # Получаем начало следующего часа
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    
    # Вычисляем разницу
    delta = next_hour - now
    
    return delta.total_seconds()


async def scheduler_worker(bot: Bot):
    """
    Background worker that checks and publishes scheduled broadcasts.
    Проверяет посты в начале каждого часа (11:00, 12:00, 13:00 и т.д.).
    """
    logger.info("[SCHEDULER] Scheduler worker запущен")
    
    # Первая проверка сразу при запуске (на случай пропущенных постов)
    logger.info("[SCHEDULER] Выполняю начальную проверку постов")
    try:
        posts = await db.get_scheduled_broadcasts(status="pending")
        now_dt = datetime.now(UTC_PLUS_3)
        
        for post in posts:
            try:
                scheduled_dt_str = post["scheduled_at"]
                if scheduled_dt_str.endswith("Z"):
                    scheduled_dt_str = scheduled_dt_str.replace("Z", "+03:00")
                
                scheduled_dt = datetime.fromisoformat(scheduled_dt_str)
                if scheduled_dt.tzinfo is None:
                    scheduled_dt = scheduled_dt.replace(tzinfo=UTC_PLUS_3)
                
                if scheduled_dt <= now_dt:
                    logger.info(f"[SCHEDULER] Найдено время для публикации поста #{post['id']}")
                    await publish_scheduled_broadcast(bot, post)
                    
            except Exception as e:
                logger.error(f"[SCHEDULER] Ошибка при обработке поста #{post.get('id', 'unknown')}: {e}")
    except Exception as e:
        logger.error(f"[SCHEDULER] Ошибка при начальной проверке: {e}")
    
    while True:
        try:
            # Вычисляем время до начала следующего часа
            now_dt = datetime.now(UTC_PLUS_3)
            seconds_to_wait = get_seconds_until_next_hour(now_dt)
            
            next_hour_time = now_dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            logger.info(f"[SCHEDULER] Следующая проверка в {next_hour_time.strftime('%H:%M:%S')} (через {seconds_to_wait:.1f} сек)")
            
            # Ждем до начала следующего часа
            await asyncio.sleep(seconds_to_wait)
            
            # Проверяем посты в начале часа
            now_dt = datetime.now(UTC_PLUS_3)
            logger.info(f"[SCHEDULER] Проверка постов в {now_dt.strftime('%H:%M:%S')}")
            
            # Получаем посты со статусом pending
            posts = await db.get_scheduled_broadcasts(status="pending")
            
            for post in posts:
                try:
                    # Парсим scheduled_at
                    scheduled_dt_str = post["scheduled_at"]
                    if scheduled_dt_str.endswith("Z"):
                        scheduled_dt_str = scheduled_dt_str.replace("Z", "+03:00")
                    
                    scheduled_dt = datetime.fromisoformat(scheduled_dt_str)
                    if scheduled_dt.tzinfo is None:
                        scheduled_dt = scheduled_dt.replace(tzinfo=UTC_PLUS_3)
                    
                    # Проверяем, пора ли публиковать
                    # Если пост запланирован на этот час (например, 11:00), то он будет опубликован
                    if scheduled_dt <= now_dt:
                        logger.info(f"[SCHEDULER] Найдено время для публикации поста #{post['id']} (запланирован на {scheduled_dt.strftime('%Y-%m-%d %H:%M:%S')})")
                        await publish_scheduled_broadcast(bot, post)
                        
                except Exception as e:
                    logger.error(f"[SCHEDULER] Ошибка при обработке поста #{post.get('id', 'unknown')}: {e}")
            
        except Exception as e:
            logger.error(f"[SCHEDULER] Ошибка в scheduler worker: {e}")
            # При ошибке ждем минуту перед повтором
            await asyncio.sleep(60)

