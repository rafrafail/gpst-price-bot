"""Markdown sanitization for Telegram MarkdownV2 compatibility."""
import re


def sanitize_markdown(text: str) -> str:
    """
    Очищает текст от элементов, которые не поддерживаются Telegram MarkdownV2.
    
    MarkdownV2 поддерживает:
    - *text* (жирный)
    - _text_ (курсив)
    - __text__ (подчеркнутый)
    - ~text~ (зачеркнутый)
    - ||text|| (спойлер)
    - `code` (inline code)
    - ```code``` (code block)
    - [text](url) (ссылки)
    
    Удаляет только неподдерживаемые элементы (HTML, таблицы и т.д.).
    Экранирует специальные символы вне тегов форматирования.
    """
    if not text:
        return ""
    
    # Удаляем HTML теги
    text = re.sub(r'<[^>]+>', '', text)
    
    # Экранируем специальные символы MarkdownV2 (кроме тех, что в тегах форматирования)
    text = _escape_markdown_v2_safe(text)
    
    return text


def _escape_markdown_v2_safe(text: str) -> str:
    """
    Экранирует специальные символы MarkdownV2, но не внутри тегов форматирования.
    
    Специальные символы: _ * [ ] ( ) ~ ` > # + - = | { } . !
    
    Использует построчную обработку для правильного определения тегов.
    """
    lines = text.split('\n')
    result_lines = []
    in_code_block = False
    
    for line in lines:
        # Отслеживаем code blocks
        if '```' in line:
            in_code_block = not in_code_block
            result_lines.append(line)
            continue
        
        if in_code_block:
            result_lines.append(line)
            continue
        
        # Обрабатываем строку: находим теги форматирования
        # Порядок важен: сначала более длинные паттерны (__), потом короткие (_)
        tag_patterns = [
            (r'`[^`]+`', 'inline_code'),  # inline code
            (r'\|\|[^|]+\|\|', 'spoiler'),  # спойлер
            (r'__[^_]+__', 'underline'),  # подчеркнутый
            (r'\*[^*]+\*', 'bold'),  # жирный (*text*)
            (r'_[^_]+_', 'italic'),  # курсив (_text_)
            (r'~[^~]+~', 'strikethrough'),  # зачеркнутый (~text~)
        ]
        
        # Находим все теги в строке
        tags = []
        for pattern, tag_type in tag_patterns:
            for match in re.finditer(pattern, line):
                tags.append((match.start(), match.end(), match.group(), tag_type))
        
        # Сортируем по позиции
        tags.sort(key=lambda x: x[0])
        
        # Разбиваем строку на части
        parts = []
        last_end = 0
        
        for start, end, tag_text, tag_type in tags:
            # Проверяем, что тег не перекрывается с предыдущим
            if start < last_end:
                continue
            
            # Добавляем текст до тега (экранируем)
            if start > last_end:
                plain_text = line[last_end:start]
                parts.append(('plain', plain_text))
            
            # Добавляем тег (не экранируем)
            parts.append(('tag', tag_text))
            last_end = end
        
        # Добавляем оставшийся текст
        if last_end < len(line):
            plain_text = line[last_end:]
            parts.append(('plain', plain_text))
        
        # Если не нашли тегов, вся строка - обычный текст
        if not parts:
            parts = [('plain', line)]
        
        # Экранируем только обычный текст
        result_line = []
        special_chars = r'_*[]()~`>#+-=|{}.!'
        
        for part_type, part_text in parts:
            if part_type == 'plain':
                # Экранируем специальные символы
                escaped = ""
                for char in part_text:
                    if char in special_chars:
                        escaped += "\\" + char
                    else:
                        escaped += char
                result_line.append(escaped)
            else:
                # Теги форматирования оставляем как есть
                result_line.append(part_text)
        
        result_lines.append(''.join(result_line))
    
    return '\n'.join(result_lines)



