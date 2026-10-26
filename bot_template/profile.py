"""Public bot profile configuration — read from TOML, no secrets, no execution."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


@dataclass(frozen=True)
class ProfileSection:
    id: str
    label: str
    text: str


@dataclass(frozen=True)
class ExampleConfig:
    enabled: bool = True


@dataclass(frozen=True)
class BotProfile:
    title: str = "Мой бот"
    welcome: str = "Добро пожаловать! Выберите раздел."
    help: str = (
        "Здесь можно узнать о сервисе и настроить уведомления.\n"
        "Меню переключается в одном сообщении. «Назад» возвращает на прошлый экран.\n"
        "«Главное меню» не удаляет черновики и не останавливает рассылку.\n"
        "/menu — открыть меню\n/cancel — отменить текущий ввод\n"
        "Готовые результаты и предпросмотры остаются в переписке."
    )
    support_url: str | None = None
    bot_username: str | None = None  # @username бота для ссылок (t.me/username)
    menu_order: list[str] = field(default_factory=lambda: ["about", "example", "preferences", "help", "broadcasts"])
    sections: list[ProfileSection] = field(default_factory=list)
    example: ExampleConfig = field(default_factory=ExampleConfig)


_RESERVED_IDS = frozenset({"home", "help", "preferences", "broadcasts", "example", "example:note", "example:rules"})
_ALLOWED_SECTION_IDS = frozenset({"about"})
_MAX_TEXT_LEN = 4000
_MAX_LABEL_LEN = 40
_MAX_TITLE_LEN = 80
_MAX_SECTIONS = 10
_MAX_MENU_ITEMS = 10
_SUPPORT_URL_MAX_LEN = 200


def _validate_url(url: str | None) -> None:
    if url is None:
        return
    if not isinstance(url, str):
        raise ValueError("support_url must be a string")
    if not url:
        raise ValueError("support_url не может быть пустым")
    if len(url) > _SUPPORT_URL_MAX_LEN:
        raise ValueError(f"support_url не длиннее {_SUPPORT_URL_MAX_LEN} символов")
    if not (url.startswith("https://") or url.startswith("http://")):
        raise ValueError("support_url должен начинаться с https:// или http://")
    # Allow http only for loopback-like hosts
    if url.startswith("http://") and not any(h in url for h in ("localhost", "127.0.0.1", "[::1]")):
        raise ValueError("HTTP разрешён только для loopback-адресов")


def _validate_section(section: dict[str, Any], seen_ids: set[str]) -> ProfileSection:
    if not isinstance(section, dict):
        raise ValueError("section должен быть таблицей")
    section_id = section.get("id")
    if not isinstance(section_id, str) or not section_id:
        raise ValueError("section.id: нужен строковый идентификатор")
    if len(section_id) > 64:
        raise ValueError("section.id не длиннее 64 символов")
    if section_id in _RESERVED_IDS and section_id not in _ALLOWED_SECTION_IDS:
        raise ValueError(f"section.id '{section_id}' зарезервирован")
    if section_id in seen_ids:
        raise ValueError(f"дублирующийся section.id: {section_id}")
    seen_ids.add(section_id)

    label = section.get("label")
    if not isinstance(label, str) or not label.strip():
        raise ValueError(f"section '{section_id}': label не может быть пустым")
    if len(label) > _MAX_LABEL_LEN:
        raise ValueError(f"section '{section_id}': label не длиннее {_MAX_LABEL_LEN} символов")

    text = section.get("text")
    if not isinstance(text, str):
        raise ValueError(f"section '{section_id}': text должен быть строкой")
    if len(text) > _MAX_TEXT_LEN:
        raise ValueError(f"section '{section_id}': text не длиннее {_MAX_TEXT_LEN} символов")

    return ProfileSection(id=section_id, label=label.strip(), text=text)


def _validate_example(example: dict[str, Any] | None) -> ExampleConfig:
    if example is None:
        return ExampleConfig()
    if not isinstance(example, dict):
        raise ValueError("example должен быть таблицей")
    enabled = example.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("example.enabled должно быть true или false")
    return ExampleConfig(enabled=enabled)


def _validate_menu_order(order: list[Any] | None, known_ids: set[str]) -> list[str]:
    if order is None:
        return ["about", "preferences", "help", "broadcasts"]
    if not isinstance(order, list):
        raise ValueError("menu.order должен быть массивом строк")
    if len(order) > _MAX_MENU_ITEMS:
        raise ValueError(f"menu.order не более {_MAX_MENU_ITEMS} пунктов")
    result = []
    # Built-in menu items that don't need sections
    builtin_items = frozenset({"about", "preferences", "help", "broadcasts", "example", "admin"})
    for item in order:
        if not isinstance(item, str):
            raise ValueError("menu.order: элементы должны быть строками")
        if item in result:
            raise ValueError(f"дублирующийся пункт меню: {item}")
        if item in _RESERVED_IDS:
            # Reserved IDs are always allowed in order
            pass
        elif item in builtin_items:
            # Built-in items allowed without sections
            pass
        elif item not in known_ids:
            raise ValueError(f"неизвестный пункт меню: {item} (нет такого section.id)")
        result.append(item)
    return result


def load_profile(path: Path | str | None) -> BotProfile:
    """Load profile from TOML file. Returns defaults if path is None or file doesn't exist."""
    if path is None:
        return BotProfile()

    path = Path(path)
    if not path.exists():
        return BotProfile()

    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"некорректный TOML в профиле: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("профиль должен быть таблицей верхнего уровня")

    # Parse sections first to know valid IDs
    sections_data = data.get("sections", [])
    if not isinstance(sections_data, list):
        raise ValueError("sections должен быть массивом")

    seen_ids: set[str] = set()
    sections = []
    for i, sec in enumerate(sections_data):
        if len(sections) >= _MAX_SECTIONS:
            raise ValueError(f"не более {_MAX_SECTIONS} разделов")
        try:
            sections.append(_validate_section(sec, seen_ids))
        except ValueError as exc:
            raise ValueError(f"section[{i}]: {exc}") from exc

    # Parse menu order against known section IDs
    menu_order = _validate_menu_order(data.get("menu", {}).get("order"), seen_ids)

    # Parse example
    example = _validate_example(data.get("example"))

    # Parse bot fields
    bot_data = data.get("bot", {})
    if not isinstance(bot_data, dict):
        raise ValueError("bot должен быть таблицей")

    title = bot_data.get("title", "Мой бот")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("bot.title: нужно название от 1 до 80 символов")
    if len(title) > _MAX_TITLE_LEN:
        raise ValueError(f"bot.title не длиннее {_MAX_TITLE_LEN} символов")

    welcome = bot_data.get("welcome", "Добро пожаловать! Выберите раздел.")
    if not isinstance(welcome, str):
        raise ValueError("bot.welcome должна быть строкой")
    if len(welcome) > _MAX_TEXT_LEN:
        raise ValueError(f"bot.welcome не длиннее {_MAX_TEXT_LEN} символов")

    help_text = bot_data.get("help")
    if help_text is not None:
        if not isinstance(help_text, str):
            raise ValueError("bot.help должна быть строкой")
        if len(help_text) > _MAX_TEXT_LEN:
            raise ValueError(f"bot.help не длиннее {_MAX_TEXT_LEN} символов")
    else:
        help_text = BotProfile().help

    support_url = bot_data.get("support_url")
    _validate_url(support_url)

    bot_username = bot_data.get("bot_username")
    if bot_username is not None:
        if not isinstance(bot_username, str):
            raise ValueError("bot.bot_username должна быть строкой")
        if bot_username.startswith("@"):
            bot_username = bot_username[1:]
        if not bot_username:
            bot_username = None

    return BotProfile(
        title=title.strip(),
        welcome=welcome,
        help=help_text,
        support_url=support_url,
        bot_username=bot_username,
        menu_order=menu_order,
        sections=sections,
        example=example,
    )


def load_profile_from_env() -> BotProfile:
    """Load profile from BOT_PROFILE_PATH environment variable."""
    path = os.environ.get("BOT_PROFILE_PATH")
    if not path:
        return BotProfile()
    return load_profile(Path(path))