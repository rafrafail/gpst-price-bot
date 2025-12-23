"""Test handler for MarkdownV2 formatting."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from core.config import Config

from core.markdown_v2 import (
    md_bold,
    md_italic,
    md_underline,
    md_strike,
    md_spoiler,
    md_code_inline,
    md_code_block,
    md_link,
    md_mention_user,
    md_list_item,
    sanitize_markdown_v2,
    send_md_v2,
)

router = Router()


def is_admin(user_id: int) -> bool:
    """Проверка, что пользователь — админ."""
    return Config.is_admin(user_id)

@router.message(Command("test_markdownv2"))
async def cmd_test_markdownv2(message: Message):
    """Тестовая команда для проверки всех типов форматирования MarkdownV2."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    # Собираем тестовый текст с разными фичами MarkdownV2
    parts: list[str] = []

    parts.append(md_bold("🧪 Тест MarkdownV2 форматирования"))
    parts.append("")  # пустая строка

    parts.append(md_italic("Курсив"))
    parts.append(md_bold("Жирный"))
    parts.append(md_underline("Подчеркнутый"))
    parts.append(md_strike("Зачеркнутый"))
    # Вложенное форматирование: сначала внутреннее, потом внешнее с already_formatted=True
    parts.append(md_bold(md_italic("Жирный + курсив (вложенный формат)", already_formatted=False), already_formatted=True))

    parts.append("")
    parts.append(md_spoiler("Скрытый текст (спойлер)"))

    parts.append("")
    parts.append(md_code_inline("inline code: 1 + 2 = 3"))

    parts.append(
        md_code_block(
            "for i in range(3):\n    print(i)",
            language="python",
        )
    )

    parts.append("")
    parts.append(
        md_link(
            "Ссылка на Telegram",
            "https://telegram.org",
        )
    )

    parts.append(
        md_mention_user(
            "Пример упоминания пользователя",
            user_id=message.from_user.id,
        )
    )

    parts.append("")
    parts.append(md_bold("Списки:"))
    # Список — просто текст, экранировать вручную не надо, он и так обычный
    # (но если будут спецсимволы — через sanitize)
    parts.append(sanitize_markdown_v2("• Буллет 1"))
    parts.append(sanitize_markdown_v2("• Буллет 2"))
    parts.append(sanitize_markdown_v2("   • Вложенный буллет"))

    parts.append("")
    parts.append(md_bold("Нумерованный список:"))
    # Используем специальную функцию для списков
    parts.append(md_list_item("1. Первый пункт"))
    parts.append(md_list_item("2. Второй пункт"))
    parts.append(md_list_item("3. Третий пункт"))

    parts.append("")
    parts.append(md_bold("Спецсимволы (все экранированы sanitize_markdown_v2):"))
    parts.append(
        sanitize_markdown_v2("_ * [ ] ( ) ~ ` > # + - = | { } . ! \\")
    )

    # Собираем в один текст
    test_text = "\n".join(parts)

    await send_md_v2(message, test_text)


@router.message(Command("test_raw"))
async def cmd_test_raw(message: Message):
    """Тестовая команда для проверки сырого текста с MarkdownV2."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    # Текст передается как есть, без обработки
    test_text = """*📝 Тест MarkdownV2 формата*



_Курсив_



*Жирный*



__Подчёркнутый__



~Зачёркнутый~



*__Комбо стиль: жирный \+ подчёркнутый__* 



*Жирный _курсив_ ~зачеркнутый~ __и подчёркнутый курсив__*



||Скрытый текст \(спойлер\)||



`inline code: a \+ b \= c`"""

    await send_md_v2(message, test_text)

