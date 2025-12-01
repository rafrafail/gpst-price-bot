"""Message splitting for Telegram length limits."""
from typing import List
from loguru import logger
from aiogram.enums import ParseMode

from core.markdown_v2 import sanitize_markdown_v2

# Лимит Telegram для одного сообщения
TELEGRAM_MESSAGE_LIMIT = 4096


def split_markdown_message(text: str, max_length: int = TELEGRAM_MESSAGE_LIMIT) -> List[str]:
    """
    Split long Markdown message into chunks.
    
    Tries to split at:
    1. Double newlines (\n\n)
    2. Single newlines (\n)
    3. Word boundaries
    4. Character boundaries (last resort)
    
    Preserves Markdown block integrity (code blocks, etc.).
    """
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    remaining = text
    
    while len(remaining) > max_length:
        # Пытаемся найти место разрыва
        
        # 1. Ищем двойной перенос строки в пределах лимита
        split_pos = -1
        search_start = max(0, max_length - 1000)  # Ищем в последних 1000 символах
        
        # Ищем последний двойной перенос в допустимом диапазоне
        double_newline_pos = remaining.rfind('\n\n', search_start, max_length)
        if double_newline_pos > 0:
            split_pos = double_newline_pos + 2
        else:
            # 2. Ищем одинарный перенос
            single_newline_pos = remaining.rfind('\n', search_start, max_length)
            if single_newline_pos > 0:
                split_pos = single_newline_pos + 1
            else:
                # 3. Ищем пробел (граница слова)
                space_pos = remaining.rfind(' ', search_start, max_length)
                if space_pos > 0:
                    split_pos = space_pos + 1
                else:
                    # 4. Принудительный разрыв (может сломать слово)
                    split_pos = max_length
        
        # Проверяем, не разрываем ли мы code block
        before_split = remaining[:split_pos]
        after_split = remaining[split_pos:]
        
        # Подсчитываем открывающие и закрывающие code block маркеры
        code_block_open = before_split.count('```')
        if code_block_open % 2 == 1:
            # Code block не закрыт, ищем закрывающий маркер
            closing_pos = after_split.find('```')
            if closing_pos > 0:
                # Продлеваем чанк до закрытия code block
                split_pos = split_pos + closing_pos + 3
        
        # Добавляем чанк
        chunk = remaining[:split_pos].strip()
        if chunk:
            chunks.append(chunk)
        
        remaining = remaining[split_pos:].strip()
    
    # Добавляем остаток
    if remaining:
        chunks.append(remaining)
    
    return chunks


async def send_long_markdown(bot, chat_id: int, text: str, sanitize: bool = False, **kwargs) -> None:
    """
    Send long Markdown message, splitting if necessary.
    
    Args:
        bot: Aiogram Bot instance
        chat_id: Telegram chat ID
        text: Message text (MarkdownV2 formatted)
        sanitize: If True, sanitize all special characters (default: False).
                  Use False if text already contains MarkdownV2 formatting.
        **kwargs: Additional arguments for send_message (parse_mode, reply_markup, etc.)
    """
    logger.debug(f"[SEND_LONG_MD] Отправка сообщения пользователю {chat_id}")
    logger.debug(f"[SEND_LONG_MD] Параметр sanitize: {sanitize}")
    logger.debug(f"[SEND_LONG_MD] Исходный текст (первые 200 символов): {text[:200]}")
    logger.debug(f"[SEND_LONG_MD] Длина текста: {len(text)} символов")
    
    # Санитизируем только если явно указано
    if sanitize:
        logger.debug(f"[SEND_LONG_MD] Санитизирую текст...")
        text = sanitize_markdown_v2(text)
        logger.debug(f"[SEND_LONG_MD] Текст после санитизации (первые 200 символов): {text[:200]}")
    else:
        # Текст передаем как есть (без экранирования) - он уже содержит Markdown-теги
        logger.debug(f"[SEND_LONG_MD] Текст передается как есть (без экранирования)")
    
    # Разбиваем на чанки
    chunks = split_markdown_message(text)
    logger.debug(f"[SEND_LONG_MD] Текст разбит на {len(chunks)} чанков")
    
    # Отправляем по очереди
    parse_mode = kwargs.pop('parse_mode', ParseMode.MARKDOWN_V2)
    logger.debug(f"[SEND_LONG_MD] Используется parse_mode: {parse_mode}")
    
    for i, chunk in enumerate(chunks):
        try:
            logger.debug(f"[SEND_LONG_MD] Отправляю чанк {i+1}/{len(chunks)} (длина: {len(chunk)} символов)")
            logger.debug(f"[SEND_LONG_MD] Содержимое чанка (первые 150 символов): {chunk[:150]}")
            
            # Для последнего чанка передаем все дополнительные параметры (reply_markup и т.д.)
            if i == len(chunks) - 1:
                logger.debug(f"[SEND_LONG_MD] Это последний чанк, передаю дополнительные параметры: {list(kwargs.keys())}")
                await bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode=parse_mode,
                    **kwargs
                )
            else:
                # Для промежуточных чанков не передаем reply_markup
                await bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode=parse_mode
                )
            logger.debug(f"[SEND_LONG_MD] Чанк {i+1}/{len(chunks)} успешно отправлен")
        except Exception as e:
            logger.error(f"[SEND_LONG_MD] Ошибка при отправке сообщения (чанк {i+1}/{len(chunks)}): {e}")
            logger.error(f"[SEND_LONG_MD] Содержимое проблемного чанка: {chunk[:500]}")
            logger.exception(f"[SEND_LONG_MD] Детали ошибки:")
            raise

