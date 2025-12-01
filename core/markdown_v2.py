"""MarkdownV2 utilities for Telegram Bot."""
import re
from typing import Final
from aiogram.types import Message
from aiogram.enums import ParseMode


# Все спецсимволы MarkdownV2 из документации Telegram
_TELEGRAM_MD_V2_SPECIAL_CHARS: Final[str] = r"_*[]()~`>#+-=|{}.!\\"

# Быстрая регулярка, которая ищет любой из этих символов
_MD_V2_ESCAPE_RE = re.compile(rf"([{re.escape(_TELEGRAM_MD_V2_SPECIAL_CHARS)}])")


def sanitize_markdown_v2(text: str) -> str:
    """
    Экранирует все специальные символы MarkdownV2.
    
    Используй для любого текста, который ты НЕ хочешь интерпретировать как разметку.
    Например: текст пользователя, URL, куски кода и т.д.
    
    Args:
        text: Текст для экранирования
        
    Returns:
        Экранированный текст, безопасный для MarkdownV2
    """
    if not text:
        return ""
    return _MD_V2_ESCAPE_RE.sub(r"\\\1", text)


def sanitize_ai_text(text: str) -> str:
    """
    Санитизирует текст от ИИ для MarkdownV2.
    
    Функция:
    1. Удаляет неподдерживаемые элементы (заголовки #, таблицы, HTML и т.д.)
    2. Экранирует незаэкранированные спецсимволы (=, +, - и т.д.) вне поддерживаемых тегов
    3. Сохраняет поддерживаемые теги MarkdownV2:
       - *text* (жирный)
       - _text_ (курсив)
       - __text__ (подчеркнутый)
       - ~text~ (зачеркнутый)
       - ||text|| (спойлер)
       - `code` (inline code)
       - ```code``` (code block)
       - [text](url) (ссылки)
    
    Args:
        text: Текст от ИИ с возможными ошибками форматирования
        
    Returns:
        Санитизированный текст, готовый для отправки с parse_mode="MarkdownV2"
    """
    if not text:
        return ""
    
    # 1. Удаляем HTML теги
    text = re.sub(r'<[^>]+>', '', text)
    
    # 2. Удаляем заголовки Markdown (не поддерживаются в MarkdownV2)
    # Заголовки: # Заголовок, ## Заголовок и т.д.
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    
    # 3. Удаляем таблицы (не поддерживаются в MarkdownV2)
    # Таблицы: | столбец | столбец |
    lines = text.split('\n')
    result_lines = []
    
    for line in lines:
        # Пропускаем строки таблиц (содержат | и выравнивание)
        if '|' in line and re.match(r'^\s*\|.*\|\s*$', line):
            # Проверяем, не является ли это спойлером (||text||)
            if not re.match(r'^\s*\|\|[^|]+\|\|\s*$', line):
                continue  # Пропускаем строку таблицы
        result_lines.append(line)
    
    text = '\n'.join(result_lines)
    
    # 4. Экранируем незаэкранированные спецсимволы вне поддерживаемых тегов
    # Поддерживаемые теги MarkdownV2
    code_block_pattern = r'```[\s\S]*?```'
    inline_code_pattern = r'(?<!\\)`[^`]*`'
    link_pattern = r'\[[^\]]*\]\([^\)]*\)'
    underline_pattern = r'__[^_]*__'
    bold_pattern = r'(?<!\\)\*[^*]*\*'
    italic_pattern = r'(?<!\\)_[^_]*_'
    strike_pattern = r'(?<!\\)~[^~]*~'
    spoiler_pattern = r'\|\|[^|]*\|\|'
    
    all_patterns = [
        code_block_pattern,
        inline_code_pattern,
        link_pattern,
        underline_pattern,
        bold_pattern,
        italic_pattern,
        strike_pattern,
        spoiler_pattern,
    ]
    
    # Находим все поддерживаемые теги
    protected_ranges = []
    for pattern in all_patterns:
        for match in re.finditer(pattern, text):
            protected_ranges.append((match.start(), match.end()))
    
    # Сортируем и объединяем перекрывающиеся диапазоны
    protected_ranges.sort()
    merged_ranges = []
    for start, end in protected_ranges:
        if merged_ranges and start <= merged_ranges[-1][1]:
            merged_ranges[-1] = (merged_ranges[-1][0], max(merged_ranges[-1][1], end))
        else:
            merged_ranges.append((start, end))
    
    # Экранируем спецсимволы только вне поддерживаемых тегов
    result = []
    last_pos = 0
    
    for start, end in merged_ranges:
        # Экранируем часть до тега
        if start > last_pos:
            part = text[last_pos:start]
            escaped_part = _escape_unprotected_chars(part)
            result.append(escaped_part)
        
        # Добавляем тег как есть (он уже правильный)
        result.append(text[start:end])
        last_pos = end
    
    # Экранируем оставшуюся часть
    if last_pos < len(text):
        part = text[last_pos:]
        escaped_part = _escape_unprotected_chars(part)
        result.append(escaped_part)
    
    return ''.join(result)


def _escape_unprotected_chars(text: str) -> str:
    """
    Экранирует незаэкранированные спецсимволы MarkdownV2.
    
    Не экранирует символы, которые уже экранированы (идут после \).
    """
    if not text:
        return ""
    
    result = []
    i = 0
    while i < len(text):
        char = text[i]
        
        # Если это обратный слэш, проверяем следующий символ
        if char == '\\' and i + 1 < len(text):
            # Уже экранированный символ - пропускаем
            result.append(char)
            result.append(text[i + 1])
            i += 2
            continue
        
        # Проверяем, является ли символ спецсимволом
        if char in _TELEGRAM_MD_V2_SPECIAL_CHARS:
            # Экранируем
            result.append('\\')
            result.append(char)
        else:
            result.append(char)
        
        i += 1
    
    return ''.join(result)


# ----- Хелперы для форматирования ----- #

def md_bold(text: str, already_formatted: bool = False) -> str:
    """
    Создает жирный текст: *text*
    
    Args:
        text: Текст для форматирования
        already_formatted: Если True, текст уже содержит MarkdownV2 форматирование
                          и не нужно его экранировать повторно
    """
    if already_formatted:
        return f"*{text}*"
    return f"*{sanitize_markdown_v2(text)}*"


def md_italic(text: str, already_formatted: bool = False) -> str:
    """
    Создает курсив: _text_
    
    Args:
        text: Текст для форматирования
        already_formatted: Если True, текст уже содержит MarkdownV2 форматирование
                          и не нужно его экранировать повторно
    """
    if already_formatted:
        return f"_{text}_"
    return f"_{sanitize_markdown_v2(text)}_"


def md_underline(text: str, already_formatted: bool = False) -> str:
    """
    Создает подчеркнутый текст: __text__
    
    Args:
        text: Текст для форматирования
        already_formatted: Если True, текст уже содержит MarkdownV2 форматирование
                          и не нужно его экранировать повторно
    """
    if already_formatted:
        return f"__{text}__"
    return f"__{sanitize_markdown_v2(text)}__"


def md_strike(text: str) -> str:
    """Создает зачеркнутый текст: ~text~"""
    return f"~{sanitize_markdown_v2(text)}~"


def md_spoiler(text: str) -> str:
    """Создает спойлер: ||text||"""
    return f"||{sanitize_markdown_v2(text)}||"


def md_code_inline(text: str) -> str:
    """
    Создает inline код: `code`
    
    Внутри инлайн-кода Telegram тоже просит экранировать спецсимволы,
    так что используем общую sanitize-функцию.
    """
    return f"`{sanitize_markdown_v2(text)}`"


def md_code_block(text: str, language: str | None = None) -> str:
    """
    Создает многострочный блок кода: ```code```
    
    Args:
        text: Код для форматирования
        language: Опционально: "python", "json" и т.д.
        
    Returns:
        Отформатированный блок кода
    """
    safe = sanitize_markdown_v2(text)
    if language:
        return f"```{language}\n{safe}\n```"
    return f"```\n{safe}\n```"


def md_link(text: str, url: str) -> str:
    """
    Создает безопасную ссылку: [text](url)
    
    Экранирует и текст, и URL.
    """
    safe_text = sanitize_markdown_v2(text)
    safe_url = sanitize_markdown_v2(url)
    return f"[{safe_text}]({safe_url})"


def md_mention_user(name: str, user_id: int | str) -> str:
    """
    Создает инлайн-упоминание пользователя: [name](tg://user?id=user_id)
    
    Args:
        name: Имя пользователя для отображения
        user_id: Telegram ID пользователя
    """
    safe_name = sanitize_markdown_v2(name)
    return f"[{safe_name}](tg://user?id={user_id})"


def md_list_item(text: str) -> str:
    """
    Создает элемент списка с правильным экранированием.
    
    В MarkdownV2 точка после цифры должна быть экранирована: 1\. Текст
    Функция автоматически обрабатывает формат "число. текст".
    
    Args:
        text: Текст списка (например, "1. Первый пункт" или просто "Первый пункт")
    """
    import re
    # Если текст начинается с "число. ", обрабатываем отдельно
    match = re.match(r'^(\d+)\. (.+)$', text)
    if match:
        number = match.group(1)
        rest_text = match.group(2)
        # Экранируем остальной текст
        safe_rest = sanitize_markdown_v2(rest_text)
        # Возвращаем: число + экранированная точка + пробел + экранированный текст
        return f"{number}\\. {safe_rest}"
    else:
        # Обычный текст без номера - просто экранируем
        return sanitize_markdown_v2(text)


# ----- Универсальный рендерер ----- #

async def send_md_v2(message: Message, text: str, **kwargs):
    """
    Универсальный отправщик MarkdownV2.
    
    Args:
        message: Объект Message от aiogram
        text: Уже СФОРМИРОВАННЫЙ md-текст (с помощью хелперов выше)
        **kwargs: Все остальные аргументы message.answer(...)
        
    Returns:
        Отправленное сообщение
    """
    return await message.answer(
        text=text,
        parse_mode=ParseMode.MARKDOWN_V2,
        **kwargs,
    )


async def send_plain_as_md_v2(message: Message, text: str, **kwargs):
    """
    Отправляет обычный текст как MarkdownV2, экранируя все спецсимволы.
    
    Без форматирования, просто безопасная отправка.
    
    Args:
        message: Объект Message от aiogram
        text: Обычный текст (будет автоматически экранирован)
        **kwargs: Все остальные аргументы message.answer(...)
        
    Returns:
        Отправленное сообщение
    """
    safe_text = sanitize_markdown_v2(text)
    return await message.answer(
        text=safe_text,
        parse_mode=ParseMode.MARKDOWN_V2,
        **kwargs,
    )
