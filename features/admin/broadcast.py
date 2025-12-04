"""Broadcast module for sending messages to all users."""
import re
import asyncio
import csv
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramRetryAfter,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramAPIError
)
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


def classify_error(exception: Exception) -> Tuple[str, str]:
    """
    Классифицирует ошибку при отправке сообщения.
    
    Returns:
        Tuple[str, str]: (status, error_type)
        status: 'ok', 'not_delivered', 'error'
        error_type: 'blocked', 'deactivated', 'chat_not_found', 'retry_after', 
                   'other_bad_request', 'network_error', 'unknown'
    """
    error_message = str(exception).lower()
    
    # Не дошли (ожидаемо)
    if isinstance(exception, TelegramForbiddenError):
        if "bot was blocked by the user" in error_message:
            return ("not_delivered", "blocked")
        elif "user is deactivated" in error_message:
            return ("not_delivered", "deactivated")
        else:
            return ("not_delivered", "forbidden")
    
    if isinstance(exception, TelegramBadRequest):
        if "chat not found" in error_message:
            return ("not_delivered", "chat_not_found")
        else:
            return ("error", "other_bad_request")
    
    # Технические ошибки
    if isinstance(exception, TelegramRetryAfter):
        return ("error", "retry_after")
    
    if isinstance(exception, TelegramNetworkError):
        return ("error", "network_error")
    
    if isinstance(exception, TelegramAPIError):
        return ("error", "api_error")
    
    # Неизвестная ошибка
    return ("error", "unknown")


async def send_message_to_user(
    bot: Bot,
    user_id: int,
    text: str,
    photos: List[str],
    videos: List[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None
) -> Tuple[bool, Optional[Exception], int]:
    """
    Отправляет сообщение пользователю с обработкой TelegramRetryAfter.
    
    Args:
        bot: Экземпляр бота
        user_id: ID пользователя
        text: Текст сообщения
        photos: Список file_id фотографий
        videos: Список file_id видео
        reply_markup: Клавиатура (опционально)
    
    Returns:
        Tuple[bool, Optional[Exception], int]: (успех, ошибка, количество попыток)
    """
    if videos is None:
        videos = []
    
    attempt = 1
    
    try:
        has_photos = photos and len(photos) > 0
        has_videos = videos and len(videos) > 0
        total_media_count = (len(photos) if has_photos else 0) + (len(videos) if has_videos else 0)
        
        if total_media_count == 1:
            # Одно медиа (фото или видео) - отправляем с текстом
            if has_photos:
                await bot.send_photo(
                    chat_id=user_id,
                    photo=photos[0],
                    caption=text,
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
            else:  # has_videos
                await bot.send_video(
                    chat_id=user_id,
                    video=videos[0],
                    caption=text,
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
        elif total_media_count > 1:
            # Несколько медиа - отправляем все вместе медиагруппой, затем текст
            from aiogram.types import InputMediaPhoto, InputMediaVideo
            media = []
            # Добавляем все фото
            for photo_id in photos:
                media.append(InputMediaPhoto(media=photo_id))
            # Добавляем все видео
            for video_id in videos:
                media.append(InputMediaVideo(media=video_id))
            await bot.send_media_group(chat_id=user_id, media=media)
            # Текст отправляем отдельно
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
        
        return (True, None, attempt)
    
    except TelegramRetryAfter as e:
        # Обрабатываем Flood control - ждем retry_after + 1 сек и повторяем один раз
        retry_after = e.retry_after
        wait_time = retry_after + 1
        logger.warning(
            f"[BROADCAST] Flood control для пользователя {user_id}: "
            f"ждем {wait_time} секунд (retry_after={retry_after})"
        )
        
        await asyncio.sleep(wait_time)
        attempt = 2
        
        try:
            # Повторная попытка
            has_photos = photos and len(photos) > 0
            has_videos = videos and len(videos) > 0
            total_media_count = (len(photos) if has_photos else 0) + (len(videos) if has_videos else 0)
            
            if total_media_count == 1:
                # Одно медиа (фото или видео) - отправляем с текстом
                if has_photos:
                    await bot.send_photo(
                        chat_id=user_id,
                        photo=photos[0],
                        caption=text,
                        parse_mode="MarkdownV2",
                        reply_markup=reply_markup
                    )
                else:  # has_videos
                    await bot.send_video(
                        chat_id=user_id,
                        video=videos[0],
                        caption=text,
                        parse_mode="MarkdownV2",
                        reply_markup=reply_markup
                    )
            elif total_media_count > 1:
                # Несколько медиа - отправляем все вместе медиагруппой, затем текст
                from aiogram.types import InputMediaPhoto, InputMediaVideo
                media = []
                # Добавляем все фото
                for photo_id in photos:
                    media.append(InputMediaPhoto(media=photo_id))
                # Добавляем все видео
                for video_id in videos:
                    media.append(InputMediaVideo(media=video_id))
                await bot.send_media_group(chat_id=user_id, media=media)
                # Текст отправляем отдельно
                await send_long_markdown(
                    bot=bot,
                    chat_id=user_id,
                    text=text,
                    sanitize=False,
                    reply_markup=reply_markup
                )
            else:
                await send_long_markdown(
                    bot=bot,
                    chat_id=user_id,
                    text=text,
                    sanitize=False,
                    reply_markup=reply_markup
                )
            
            logger.info(f"[BROADCAST] Успешный ретрай для пользователя {user_id} после ожидания")
            return (True, None, attempt)
        
        except Exception as retry_exception:
            # Если ретрай тоже не удался - записываем как ошибку
            logger.error(
                f"[BROADCAST] Ретрай не удался для пользователя {user_id}: {retry_exception}"
            )
            return (False, retry_exception, attempt)
    
    except Exception as e:
        # Любая другая ошибка
        return (False, e, attempt)


def _get_broadcast_filename(broadcast_id: str, suffix: str = "") -> str:
    """
    Формирует имя файла для рассылки.
    
    Args:
        broadcast_id: ID рассылки (формат: YYYY-MM-DD_HH-MM-SS)
        suffix: Суффикс для имени файла (например, "_text")
        
    Returns:
        str: Имя файла в формате broadcast_DD-MM-YYYY_HH-MM-SS[suffix].csv
    """
    date_part, time_part = broadcast_id.split('_')
    year, month, day = date_part.split('-')
    formatted_date = f"{day}-{month}-{year}"
    return f"broadcast_{formatted_date}_{time_part}{suffix}.csv"


def create_broadcast_csv(
    broadcast_id: str,
    admin_id: int,
    results: List[Dict],
    broadcasts_dir: Path
) -> Path:
    """
    Создает CSV файл с результатами рассылки.
    
    Args:
        broadcast_id: ID рассылки (формат: YYYY-MM-DD_HH-MM-SS)
        admin_id: ID администратора
        results: Список результатов отправки
        broadcasts_dir: Директория для сохранения CSV
        
    Returns:
        Path: Путь к созданному CSV файлу
    """
    broadcasts_dir.mkdir(parents=True, exist_ok=True)
    
    csv_filename = _get_broadcast_filename(broadcast_id)
    csv_path = broadcasts_dir / csv_filename
    
    # Записываем CSV с разделителем точка с запятой и UTF-8 с BOM
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        fieldnames = [
            'broadcast_id',
            'datetime',
            'admin_id',
            'user_id',
            'username',
            'status',
            'error_type',
            'error_message'
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
        writer.writeheader()
        
        for result in results:
            # Формируем строку с только нужными полями
            row = {
                'broadcast_id': result.get('broadcast_id', ''),
                'datetime': result.get('datetime', ''),
                'admin_id': result.get('admin_id', ''),
                'user_id': result.get('user_id', ''),
                'username': result.get('username', ''),
                'status': result.get('status', ''),
                'error_type': result.get('error_type', ''),
                'error_message': result.get('error_message', '')
            }
            writer.writerow(row)
    
    logger.info(f"[BROADCAST] CSV файл создан: {csv_path}")
    return csv_path


async def create_broadcast_text_file(
    broadcast_id: str,
    text: str,
    photos: List[str],
    videos: List[str] = None,
    buttons: List[dict] = None,
    broadcasts_dir: Path = None,
    bot: Bot = None
) -> Path:
    """
    Создает CSV файл с содержимым рассылки (текст, фото, видео, кнопки).
    
    Args:
        broadcast_id: ID рассылки (формат: YYYY-MM-DD_HH-MM-SS)
        text: Текст рассылки
        photos: Список file_id фотографий
        videos: Список file_id видео
        buttons: Список словарей с кнопками [{"text": "...", "url": "..."}]
        broadcasts_dir: Директория для сохранения CSV
        bot: Экземпляр бота для получения URL медиафайлов
        
    Returns:
        Path: Путь к созданному CSV файлу
    """
    if videos is None:
        videos = []
    if buttons is None:
        buttons = []
    
    broadcasts_dir.mkdir(parents=True, exist_ok=True)
    
    csv_filename = _get_broadcast_filename(broadcast_id, suffix="_text")
    csv_path = broadcasts_dir / csv_filename
    
    # Получаем URL фотографий
    photo_urls = []
    if photos:
        for photo_id in photos:
            try:
                file = await bot.get_file(photo_id)
                photo_url = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"
                photo_urls.append(photo_url)
            except Exception as e:
                logger.warning(f"[BROADCAST] Не удалось получить URL для фото {photo_id}: {e}")
                photo_urls.append(photo_id)  # Используем file_id если не удалось получить URL
    
    # Получаем URL видео
    video_urls = []
    if videos:
        for video_id in videos:
            try:
                file = await bot.get_file(video_id)
                video_url = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"
                video_urls.append(video_url)
            except Exception as e:
                logger.warning(f"[BROADCAST] Не удалось получить URL для видео {video_id}: {e}")
                video_urls.append(video_id)  # Используем file_id если не удалось получить URL
    
    # Формируем строки для кнопок
    button_texts = []
    button_urls = []
    if buttons:
        for btn in buttons:
            button_texts.append(btn.get('text', ''))
            button_urls.append(btn.get('url', ''))
    
    # Записываем CSV с разделителем точка с запятой и UTF-8 с BOM
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        fieldnames = [
            'field',
            'value'
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
        writer.writeheader()
        
        # Текст рассылки
        writer.writerow({'field': 'text', 'value': text})
        
        # Фотографии
        if photo_urls:
            for i, photo_url in enumerate(photo_urls, 1):
                writer.writerow({'field': f'photo_{i}', 'value': photo_url})
        else:
            writer.writerow({'field': 'photo_1', 'value': ''})
        
        # Видео
        if video_urls:
            for i, video_url in enumerate(video_urls, 1):
                writer.writerow({'field': f'video_{i}', 'value': video_url})
        else:
            writer.writerow({'field': 'video_1', 'value': ''})
        
        # Кнопки
        if button_texts and button_urls:
            for i, (btn_text, btn_url) in enumerate(zip(button_texts, button_urls), 1):
                writer.writerow({'field': f'button_{i}_text', 'value': btn_text})
                writer.writerow({'field': f'button_{i}_url', 'value': btn_url})
        else:
            writer.writerow({'field': 'button_1_text', 'value': ''})
            writer.writerow({'field': 'button_1_url', 'value': ''})
    
    logger.info(f"[BROADCAST] Файл с текстом рассылки создан: {csv_path}")
    return csv_path


async def safe_edit_or_send(callback: CallbackQuery, text: str, parse_mode: Optional[str] = None, reply_markup: Optional[InlineKeyboardMarkup] = None) -> None:
    """
    Безопасно редактирует сообщение или отправляет новое, если редактирование невозможно.
    
    Args:
        callback: CallbackQuery объект
        text: Текст для отправки
        parse_mode: Режим парсинга (опционально)
        reply_markup: Клавиатура (опционально)
    """
    try:
        # Пытаемся отредактировать сообщение
        if callback.message.photo:
            # Если это фото, пытаемся отредактировать caption
            # Но если caption нет или это медиагруппа, это может не сработать
            try:
                await callback.message.edit_caption(caption=text, parse_mode=parse_mode, reply_markup=reply_markup)
                return
            except Exception:
                # Если не удалось отредактировать caption, отправляем новое сообщение
                pass
        else:
            # Если это текстовое сообщение, редактируем текст
            try:
                await callback.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
                return
            except Exception:
                # Если не удалось отредактировать, отправляем новое сообщение
                pass
    except Exception as e:
        logger.debug(f"[BROADCAST] Не удалось отредактировать сообщение: {e}, отправляю новое")
    
    # Если редактирование не удалось, отправляем новое сообщение
    await callback.message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)


def _create_preview_keyboard(has_photos: bool = False, has_buttons: bool = False, has_error: bool = False) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для предпросмотра поста.
    
    Args:
        has_photos: Есть ли уже добавленные фото
        has_buttons: Есть ли уже добавленные кнопки
        has_error: Есть ли ошибка в Markdown (показываем только исправление/отмена)
    """
    if has_error:
        # При ошибке показываем только кнопки исправления/отмены
        keyboard = [
            [
                InlineKeyboardButton(text="📝 Отправить исправленный текст", callback_data="broadcast_fix_text"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel"),
            ]
        ]
    elif has_buttons:
        # Если уже есть кнопки, показываем только отправку/отмену
        keyboard = [
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data="broadcast_confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel"),
            ]
        ]
    else:
        # Полное меню конструктора
        keyboard = [
            [
                InlineKeyboardButton(text="📷 Добавить фотографии", callback_data="broadcast_add_photo"),
            ],
            [
                InlineKeyboardButton(text="🔘 Добавить кнопку", callback_data="broadcast_add_button"),
            ],
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data="broadcast_confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel"),
            ]
        ]
        # Если фото уже добавлены, убираем кнопку добавления фото
        if has_photos:
            keyboard = keyboard[1:]  # Убираем первую строку с кнопкой добавления фото
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def _show_preview(
    message: Message,
    text: str,
    photos: Optional[List[str]] = None,
    videos: Optional[List[str]] = None,
    buttons: Optional[List[dict]] = None,
    has_error: bool = False,
    error_info: Optional[dict] = None
) -> None:
    """
    Показывает предпросмотр поста с правильным меню.
    
    Args:
        message: Сообщение для ответа
        text: Текст поста
        photos: Список file_id фотографий (если есть)
        videos: Список file_id видео (если есть)
        buttons: Список словарей с кнопками [{"text": "...", "url": "..."}]
        has_error: Есть ли ошибка в Markdown
        error_info: Информация об ошибке (если есть)
    """
    has_photos = photos is not None and len(photos) > 0
    has_videos = videos is not None and len(videos) > 0
    has_media = has_photos or has_videos
    has_buttons = buttons is not None and len(buttons) > 0
    
    keyboard = _create_preview_keyboard(has_photos=has_media, has_buttons=has_buttons, has_error=has_error)
    
    # Формируем текст предпросмотра
    preview_header = sanitize_markdown_v2("📋 Предпросмотр сообщения:")
    user_text_preview = text[:500] + ('...' if len(text) > 500 else '')
    
    if has_error and error_info:
        # Показываем ошибку
        error_text = "❌ Ошибка в Markdown-форматировании!\n\n"
        error_text += f"📝 {error_info['description']}\n\n"
        
        if error_info.get('position') is not None:
            error_text += f"📍 Проблема найдена в тексте:\n"
            error_text += f"```\n{error_info['context']}\n```\n\n"
            error_text += f"💡 Совет: {error_info['suggestion']}"
        else:
            error_text += f"💡 Совет: {error_info['suggestion']}"
        
        await message.answer(error_text, reply_markup=keyboard, parse_mode=None)
        return
    
    # Формируем полный текст предпросмотра
    preview_text = f"{preview_header}\n\n{user_text_preview}"
    
    # Если есть кнопки, добавляем их к клавиатуре предпросмотра
    preview_keyboard = keyboard
    if has_buttons:
        inline_buttons = []
        for btn in buttons:
            inline_buttons.append([InlineKeyboardButton(text=btn['text'], url=btn['url'])])
        # Объединяем кнопки поста с кнопками управления
        preview_keyboard = InlineKeyboardMarkup(inline_keyboard=inline_buttons + keyboard.inline_keyboard)
    
    try:
        total_media_count = (len(photos) if has_photos else 0) + (len(videos) if has_videos else 0)
        
        if total_media_count == 1:
            # Одно медиа (фото или видео) - отправляем с текстом
            if has_photos:
                await message.answer_photo(
                    photo=photos[0],
                    caption=preview_text,
                    parse_mode="MarkdownV2",
                    reply_markup=preview_keyboard
                )
            else:  # has_videos
                await message.answer_video(
                    video=videos[0],
                    caption=preview_text,
                    parse_mode="MarkdownV2",
                    reply_markup=preview_keyboard
                )
        elif total_media_count > 1:
            # Несколько медиа - отправляем все вместе медиагруппой, затем текст
            from aiogram.types import InputMediaPhoto, InputMediaVideo
            media = []
            # Добавляем все фото
            for photo_id in photos:
                media.append(InputMediaPhoto(media=photo_id))
            # Добавляем все видео
            for video_id in videos:
                media.append(InputMediaVideo(media=video_id))
            await message.answer_media_group(media)
            # Текст отправляем отдельно
            await message.answer(
                preview_text,
                parse_mode="MarkdownV2",
                reply_markup=preview_keyboard
            )
        else:
            # Только текст
            await send_md_v2(
                message,
                preview_text,
                reply_markup=preview_keyboard
            )
    except TelegramBadRequest as e:
        # Ошибка парсинга - показываем ошибку без форматирования
        error_message = str(e)
        logger.warning(f"[BROADCAST] Ошибка парсинга MarkdownV2: {error_message}")
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
        
        # Показываем ошибку с правильным меню (только исправление/отмена)
        error_keyboard = _create_preview_keyboard(has_photos=has_media, has_buttons=has_buttons, has_error=True)
        await message.answer(error_text, reply_markup=error_keyboard, parse_mode=None)


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


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    """Start broadcast process."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    await state.set_state(ADMIN_States.BROADCAST_TEXT)
    
    # Создаем клавиатуру с кнопкой "Отмена"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")
        ]
    ])
    
    await message.answer(
        "📢 Введите текст сообщения для рассылки (поддерживается Markdown):",
        reply_markup=keyboard
    )


@router.message(lambda m: m.text and m.text.startswith("/") and not m.text.startswith("/broadcast"), ADMIN_States.BROADCAST_TEXT)
async def cancel_broadcast_on_command(message: Message, state: FSMContext):
    """Cancel broadcast if user calls another command during text input."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        await state.clear()
        return
    
    # Очищаем состояние broadcast
    await state.clear()
    await message.answer("❌ Создание рассылки отменено из-за вызова другой команды.")


@router.message(ADMIN_States.BROADCAST_TEXT)
async def process_broadcast_text(message: Message, state: FSMContext):
    """Process broadcast text and show preview."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        await state.clear()
        return
    
    text = message.text or message.caption or ""
    
    logger.info(f"[BROADCAST] Админ {message.from_user.id} ввел текст для рассылки")
    logger.debug(f"[BROADCAST] Исходный текст (первые 200 символов): {text[:200]}")
    logger.debug(f"[BROADCAST] Длина текста: {len(text)} символов")
    
    if not text.strip():
        await message.answer("❌ Текст не может быть пустым. Попробуйте снова.")
        return
    
    # Сохраняем текст в состоянии
    await state.update_data(broadcast_text=text, broadcast_photos=None, broadcast_videos=None, broadcast_buttons=None)
    
    await state.set_state(ADMIN_States.BROADCAST_PREVIEW)
    
    # Показываем предпросмотр (ошибки будут обработаны в _show_preview)
    await _show_preview(
        message=message,
        text=text,
        photos=None,
        videos=None,
        buttons=None,
        has_error=False,
        error_info=None
    )


@router.callback_query(lambda c: c.data == "broadcast_add_photo", ADMIN_States.BROADCAST_PREVIEW)
async def add_photo_callback(callback: CallbackQuery, state: FSMContext):
    """Start adding photos to broadcast."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав для выполнения этой команды.", show_alert=True)
        await state.clear()
        return
    
    await state.set_state(ADMIN_States.BROADCAST_ADD_PHOTO)
    
    # Создаем клавиатуру с кнопкой "Назад"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_back_to_preview")
        ]
    ])
    
    await safe_edit_or_send(
        callback,
        "📷 Отправьте фотографию, видео или несколько медиафайлов (можно отправить медиагруппой).",
        reply_markup=keyboard
    )
    await callback.answer()


@router.message(ADMIN_States.BROADCAST_ADD_PHOTO)
async def process_add_photo(message: Message, state: FSMContext):
    """Process photo and video addition."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        await state.clear()
        return
    
    data = await state.get_data()
    text = data.get("broadcast_text", "")
    existing_photos = data.get("broadcast_photos") or []
    existing_videos = data.get("broadcast_videos") or []
    buttons = data.get("broadcast_buttons")
    current_media_group_id = data.get("current_media_group_id")
    media_group_photos = data.get("media_group_photos") or []
    media_group_videos = data.get("media_group_videos") or []
    processed_media_group = data.get("processed_media_group_id")
    
    # Получаем фото или видео из сообщения
    media_id = None
    media_type = None
    
    if message.photo:
        media_id = message.photo[-1].file_id  # Берем фото наибольшего размера
        media_type = "photo"
    elif message.video:
        media_id = message.video.file_id
        media_type = "video"
    else:
        await message.answer("❌ Пожалуйста, отправьте фотографию или видео.")
        return
    
    # Проверяем, это медиагруппа или одиночный файл
    if message.media_group_id:
        # Это медиагруппа
        # Если мы уже обработали эту медиагруппу, игнорируем
        if processed_media_group == message.media_group_id:
            return
        
        if current_media_group_id != message.media_group_id:
            # Новая медиагруппа - начинаем собирать заново
            if media_type == "photo":
                media_group_photos = [media_id]
                media_group_videos = []
            else:  # video
                media_group_photos = []
                media_group_videos = [media_id]
            await state.update_data(
                current_media_group_id=message.media_group_id,
                media_group_photos=media_group_photos,
                media_group_videos=media_group_videos
            )
        else:
            # Продолжаем собирать медиагруппу
            if media_type == "photo":
                media_group_photos.append(media_id)
            else:  # video
                media_group_videos.append(media_id)
            await state.update_data(
                media_group_photos=media_group_photos,
                media_group_videos=media_group_videos
            )
        
        # Ждем немного, чтобы собрать все медиа из группы
        # Затем показываем предпросмотр один раз
        await asyncio.sleep(3.0)  # Задержка 3 секунды для сбора всех медиа из группы
        
        # Проверяем, не изменилось ли состояние (может пришло еще медиа)
        current_data = await state.get_data()
        final_media_group_id = current_data.get("current_media_group_id")
        final_media_group_photos = current_data.get("media_group_photos") or []
        final_media_group_videos = current_data.get("media_group_videos") or []
        already_processed = current_data.get("processed_media_group_id")
        
        # Если это все еще та же медиагруппа и мы еще не обработали её, показываем предпросмотр
        if final_media_group_id == message.media_group_id and already_processed != message.media_group_id:
            existing_photos.extend(final_media_group_photos)
            existing_videos.extend(final_media_group_videos)
            await state.update_data(
                broadcast_photos=existing_photos,
                broadcast_videos=existing_videos,
                current_media_group_id=None,
                media_group_photos=[],
                media_group_videos=[],
                processed_media_group_id=message.media_group_id  # Помечаем как обработанную
            )
            await state.set_state(ADMIN_States.BROADCAST_PREVIEW)
            
            # Показываем предпросмотр один раз для всей медиагруппы
            await _show_preview(
                message=message,
                text=text,
                photos=existing_photos,
                videos=existing_videos,
                buttons=buttons,
                has_error=False
            )
    else:
        # Одиночный файл (не медиагруппа)
        if media_group_photos or media_group_videos:
            # Завершаем обработку предыдущей медиагруппы
            existing_photos.extend(media_group_photos)
            existing_videos.extend(media_group_videos)
            media_group_photos = []
            media_group_videos = []
            current_media_group_id = None
        
        if media_type == "photo":
            existing_photos.append(media_id)
        else:  # video
            existing_videos.append(media_id)
        
        await state.update_data(
            broadcast_photos=existing_photos,
            broadcast_videos=existing_videos,
            current_media_group_id=None,
            media_group_photos=[],
            media_group_videos=[],
            processed_media_group_id=None  # Сбрасываем флаг обработки
        )
        await state.set_state(ADMIN_States.BROADCAST_PREVIEW)
        
        # Показываем предпросмотр для одиночного файла
        await _show_preview(
            message=message,
            text=text,
            photos=existing_photos,
            videos=existing_videos,
            buttons=buttons,
            has_error=False
        )


@router.callback_query(lambda c: c.data == "broadcast_add_button", ADMIN_States.BROADCAST_PREVIEW)
async def add_button_callback(callback: CallbackQuery, state: FSMContext):
    """Start adding button to broadcast."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав для выполнения этой команды.", show_alert=True)
        await state.clear()
        return
    
    await state.set_state(ADMIN_States.BROADCAST_ADD_BUTTON_TEXT)
    
    # Создаем клавиатуру с кнопкой "Назад"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_back_to_preview")
        ]
    ])
    
    await safe_edit_or_send(
        callback,
        "🔘 Введите текст для кнопки:",
        reply_markup=keyboard
    )
    await callback.answer()


@router.message(ADMIN_States.BROADCAST_ADD_BUTTON_TEXT)
async def process_button_text(message: Message, state: FSMContext):
    """Process button text."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        await state.clear()
        return
    
    button_text = message.text or ""
    
    if not button_text.strip():
        await message.answer("❌ Текст кнопки не может быть пустым. Попробуйте снова.")
        return
    
    await state.update_data(button_text=button_text)
    await state.set_state(ADMIN_States.BROADCAST_ADD_BUTTON_URL)
    
    # Создаем клавиатуру с кнопкой "Назад"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_back_to_preview")
        ]
    ])
    
    await message.answer(
        "🔗 Введите URL для кнопки:",
        reply_markup=keyboard
    )


@router.message(ADMIN_States.BROADCAST_ADD_BUTTON_URL)
async def process_button_url(message: Message, state: FSMContext):
    """Process button URL and add button."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        await state.clear()
        return
    
    button_url = message.text or ""
    data = await state.get_data()
    button_text = data.get("button_text", "")
    text = data.get("broadcast_text", "")
    photos = data.get("broadcast_photos")
    videos = data.get("broadcast_videos")
    existing_buttons = data.get("broadcast_buttons") or []
    
    if not button_url.strip():
        await message.answer("❌ URL кнопки не может быть пустым. Попробуйте снова.")
        return
    
    # Проверяем, что это валидный URL
    if not (button_url.startswith("http://") or button_url.startswith("https://")):
        await message.answer("❌ URL должен начинаться с http:// или https://. Попробуйте снова.")
        return
    
    # Добавляем кнопку
    existing_buttons.append({"text": button_text, "url": button_url})
    await state.update_data(broadcast_buttons=existing_buttons)
    await state.set_state(ADMIN_States.BROADCAST_PREVIEW)
    
    # Показываем обновленный предпросмотр
    await _show_preview(
        message=message,
        text=text,
        photos=photos,
        videos=videos,
        buttons=existing_buttons,
        has_error=False
    )


@router.callback_query(lambda c: c.data == "broadcast_fix_text", ADMIN_States.BROADCAST_PREVIEW)
async def fix_text_callback(callback: CallbackQuery, state: FSMContext):
    """Return to text input to fix error."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав для выполнения этой команды.", show_alert=True)
        await state.clear()
        return
    
    await state.set_state(ADMIN_States.BROADCAST_TEXT)
    
    # Создаем клавиатуру с кнопкой "Отмена"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")
        ]
    ])
    
    await safe_edit_or_send(
        callback,
        "📝 Введите исправленный текст сообщения для рассылки (поддерживается Markdown):",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "broadcast_confirm", ADMIN_States.BROADCAST_PREVIEW)
async def confirm_broadcast(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Confirm and send broadcast."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав для выполнения этой команды.", show_alert=True)
        await state.clear()
        return
    
    data = await state.get_data()
    text = data.get("broadcast_text", "")
    photos = data.get("broadcast_photos") or []
    videos = data.get("broadcast_videos") or []
    buttons = data.get("broadcast_buttons") or []
    
    admin_id = callback.from_user.id
    admin_username = callback.from_user.username or ""
    admin_full_name = callback.from_user.full_name or ""
    
    logger.info(f"[BROADCAST] Админ {admin_id} подтвердил рассылку")
    logger.debug(f"[BROADCAST] Текст для рассылки (первые 200 символов): {text[:200]}")
    logger.debug(f"[BROADCAST] Длина текста: {len(text)} символов")
    logger.debug(f"[BROADCAST] Фотографий: {len(photos)}")
    logger.debug(f"[BROADCAST] Видео: {len(videos)}")
    logger.debug(f"[BROADCAST] Кнопок: {len(buttons)}")
    
    if not text:
        logger.warning(f"[BROADCAST] Текст не найден в состоянии!")
        await callback.answer("❌ Текст не найден", show_alert=True)
        await state.clear()
        return
    
    # Для технического сообщения всегда отправляем новое текстовое сообщение
    await callback.message.answer("📤 Начинаю рассылку...")
    
    # Получаем список всех пользователей с полной информацией
    try:
        users = await db.get_all_users_with_info()
        logger.info(f"[BROADCAST] Получен список пользователей: {len(users)} пользователей")
    except Exception as e:
        logger.error(f"[BROADCAST] Ошибка при получении списка пользователей: {e}")
        await callback.message.answer("❌ Ошибка при получении списка пользователей.")
        await state.clear()
        return
    
    if not users:
        logger.warning(f"[BROADCAST] Нет пользователей для рассылки")
        await callback.message.answer("❌ Нет пользователей для рассылки.")
        await state.clear()
        return
    
    # Создаем клавиатуру с кнопками (если есть)
    reply_markup = None
    if buttons:
        inline_buttons = []
        for btn in buttons:
            inline_buttons.append([InlineKeyboardButton(text=btn['text'], url=btn['url'])])
        reply_markup = InlineKeyboardMarkup(inline_keyboard=inline_buttons)
    
    # Подготовка для логирования
    # Формат broadcast_id: YYYY-MM-DD_HH-MM-SS
    now = datetime.utcnow()
    broadcast_id = now.strftime('%Y-%m-%d_%H-%M-%S')
    broadcast_datetime = now.isoformat()
    results = []
    
    # Статистика
    success_count = 0
    not_delivered_count = 0
    error_count = 0
    
    logger.info(f"[BROADCAST] Начинаю рассылку {len(users)} пользователям")
    logger.debug(f"[BROADCAST] Текст будет отправлен БЕЗ санитизации (sanitize=False)")
    
    # Параметры антифлуд логики
    BATCH_SIZE = 10
    BATCH_DELAY = 5  # секунд
    
    # Разбиваем пользователей на батчи
    total_batches = (len(users) + BATCH_SIZE - 1) // BATCH_SIZE
    logger.info(f"[BROADCAST] Рассылка будет выполнена в {total_batches} батчах по {BATCH_SIZE} сообщений")
    
    # Отправляем сообщения батчами
    for batch_num in range(total_batches):
        batch_start = batch_num * BATCH_SIZE
        batch_end = min(batch_start + BATCH_SIZE, len(users))
        batch_users = users[batch_start:batch_end]
        
        logger.info(
            f"[BROADCAST] Обрабатываю батч {batch_num + 1}/{total_batches} "
            f"(пользователи {batch_start + 1}-{batch_end} из {len(users)})"
        )
        
        # Отправляем сообщения в текущем батче
        for user in batch_users:
            user_id = user["telegram_id"]
            username = user.get("telegram_nickname") or ""
            full_name = user.get("telegram_name") or ""
            
            status = "ok"
            error_type = ""
            error_message = ""
            attempt = 1
            
            logger.debug(f"[BROADCAST] Отправляю сообщение пользователю {user_id}")
            
            # Отправляем сообщение с обработкой ретраев
            success, exception, attempt = await send_message_to_user(
                bot=bot,
                user_id=user_id,
                text=text,
                photos=photos,
                videos=videos,
                reply_markup=reply_markup
            )
            
            if success:
                success_count += 1
                status = "ok"
            else:
                # Классифицируем ошибку
                status, error_type = classify_error(exception)
                error_message = str(exception)
                
                if status == "not_delivered":
                    not_delivered_count += 1
                else:
                    error_count += 1
                
                logger.warning(
                    f"[BROADCAST] Ошибка при отправке сообщения пользователю {user_id}: {exception}"
                )
                logger.debug(
                    f"[BROADCAST] Детали ошибки для пользователя {user_id}:", exc_info=True
                )
            
            # Записываем результат
            results.append({
                'broadcast_id': broadcast_id,
                'datetime': broadcast_datetime,
                'admin_id': admin_id,
                'user_id': user_id,
                'username': username,
                'status': status,
                'error_type': error_type,
                'error_message': error_message
            })
        
        # Задержка между батчами (кроме последнего батча)
        if batch_num < total_batches - 1:
            logger.debug(f"[BROADCAST] Ожидание {BATCH_DELAY} секунд перед следующим батчем...")
            await asyncio.sleep(BATCH_DELAY)
    
    # Создаем CSV файлы
    broadcasts_dir = Path("features/admin/broadcast_logs")
    
    # Создаем основной CSV файл с результатами
    try:
        csv_path = create_broadcast_csv(
            broadcast_id=broadcast_id,
            admin_id=admin_id,
            results=results,
            broadcasts_dir=broadcasts_dir
        )
    except Exception as e:
        logger.error(f"[BROADCAST] Ошибка при создании CSV файла: {e}")
        csv_path = None
    
    # Создаем файл с содержимым рассылки (текст, фото, кнопки)
    try:
        text_csv_path = await create_broadcast_text_file(
            broadcast_id=broadcast_id,
            text=text,
            photos=photos,
            videos=videos,
            buttons=buttons,
            broadcasts_dir=broadcasts_dir,
            bot=bot
        )
    except Exception as e:
        logger.error(f"[BROADCAST] Ошибка при создании файла с текстом рассылки: {e}")
        text_csv_path = None
    
    # Формируем сводку для админа
    summary = (
        f"✅ Рассылка завершена!\n\n"
        f"Успешно: {success_count}\n"
        f"Не дошли (заблокировали / удалены / чат не найден): {not_delivered_count}\n"
        f"Технические ошибки: {error_count}\n"
        f"Всего адресатов: {len(users)}\n"
        f"ID рассылки: `{broadcast_id}`"
    )
    
    # Отправляем сводку админу
    await callback.message.answer(summary)
    
    # Отправляем CSV файл админу, если он был создан
    if csv_path and csv_path.exists():
        try:
            document = FSInputFile(csv_path)
            await callback.message.answer_document(
                document=document,
                caption="Лог рассылки"
            )
        except Exception as e:
            logger.error(f"[BROADCAST] Ошибка при отправке CSV файла админу: {e}")
            await callback.message.answer(
                f"⚠️ CSV файл создан, но не удалось отправить: {csv_path}"
            )
    
    await state.clear()
    await callback.answer()


@router.callback_query(lambda c: c.data == "broadcast_back_to_preview")
async def back_to_preview(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Return to preview from button input or photo selection."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав для выполнения этой команды.", show_alert=True)
        return
    
    # Сохраняем ссылку на сообщение и chat перед удалением
    message_to_delete = callback.message
    chat = callback.message.chat
    
    # Удаляем старое сообщение, если возможно
    try:
        if message_to_delete:
            await message_to_delete.delete()
    except Exception as e:
        logger.debug(f"[BROADCAST] Не удалось удалить сообщение: {e}")
    
    # Получаем данные из состояния
    data = await state.get_data()
    text = data.get("broadcast_text", "")
    photos = data.get("broadcast_photos")
    videos = data.get("broadcast_videos")
    buttons = data.get("broadcast_buttons") or []
    
    # Возвращаемся в состояние превью
    await state.set_state(ADMIN_States.BROADCAST_PREVIEW)
    
    # Создаем временный объект Message для _show_preview
    # Используем методы bot напрямую через обёртку
    from aiogram.types import Message as MessageType
    
    class MessageWrapper:
        """Обёртка для Message, которая использует bot для отправки."""
        def __init__(self, chat, from_user, bot):
            self.chat = chat
            self.from_user = from_user
            self._bot = bot
        
        async def answer(self, text, **kwargs):
            return await self._bot.send_message(self.chat.id, text, **kwargs)
        
        async def answer_photo(self, photo, **kwargs):
            return await self._bot.send_photo(self.chat.id, photo, **kwargs)
        
        async def answer_video(self, video, **kwargs):
            return await self._bot.send_video(self.chat.id, video, **kwargs)
        
        async def answer_media_group(self, media, **kwargs):
            return await self._bot.send_media_group(self.chat.id, media, **kwargs)
    
    temp_message = MessageWrapper(chat, callback.from_user, bot)
    
    # Показываем превью
    await _show_preview(
        message=temp_message,
        text=text,
        photos=photos,
        videos=videos,
        buttons=buttons,
        has_error=False
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "broadcast_cancel")
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    """Cancel broadcast."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав для выполнения этой команды.", show_alert=True)
        return
    
    await state.clear()
    await safe_edit_or_send(callback, "❌ Рассылка отменена.")
    await callback.answer()



