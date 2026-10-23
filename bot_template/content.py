"""Validate and prepare the *same* native Telegram payloads for preview and delivery.

Offsets are Telegram UTF-16 code units, never Python character indices. Formatting
may cross message boundaries; semantic entities (links, mentions, emoji, etc.) may
not. No HTML/Markdown parser or paid-broadcast defaults are used here.
"""

from bisect import bisect_right
from urllib.parse import urlsplit

from aiogram.enums import MessageEntityType
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    MessageEntity,
)

from .models import Button, Content, Media

TEXT_LIMIT = 4000  # conservative UTF-16 cap below Telegram's 4096
CAPTION_LIMIT = 1024
ACTIONS = frozenset({"home", "help", "example", "preferences"})
_FORMATTING = frozenset(
    {
        "bold",
        "italic",
        "underline",
        "strikethrough",
        "spoiler",
        "code",
        "pre",
        "blockquote",
        "expandable_blockquote",
    }
)
_ENTITY_TYPES = frozenset(e.value for e in MessageEntityType)
_ENTITY_FIELDS = frozenset(MessageEntity.model_fields)


def _boundaries(text: str) -> tuple[list[int], dict[int, int]]:
    offsets = [0]
    for char in text:
        code = ord(char)
        if code == 0 or 0xD800 <= code <= 0xDFFF:
            raise ValueError("Text contains an invalid Unicode character")
        offsets.append(offsets[-1] + (2 if code > 0xFFFF else 1))
    return offsets, {offset: index for index, offset in enumerate(offsets)}


def _validate_url(value: object) -> None:
    if (
        not isinstance(value, str)
        or not value
        or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)
        or any(c in value for c in ("\\", "<", ">", '"'))
    ):
        raise ValueError("A valid HTTP(S) URL is required")
    try:
        url = urlsplit(value)
        if (
            url.scheme.lower() not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or "@" in url.netloc
            or (url.port is not None and not 1 <= url.port <= 65535)
        ):
            raise ValueError
        # Reject malformed Unicode authorities, without changing the supplied URL.
        url.hostname.encode("idna")
    except (ValueError, UnicodeError):
        raise ValueError("A valid HTTP(S) URL without credentials is required") from None


def _validate_media(media: Media) -> None:
    if (
        not isinstance(media, Media)
        or not isinstance(media.kind, str)
        or media.kind not in {"photo", "video"}
    ):
        raise ValueError("Only photo and video media are supported")
    value = media.file_id
    if not isinstance(value, str) or not value:
        raise ValueError("Media requires a file ID or HTTP(S) URL")
    # Telegram file IDs use URL-safe base64. Everything else must be a URL;
    # notably local paths, attach:// and file:// are never accepted.
    if all(c.isascii() and (c.isalnum() or c in "_-=") for c in value):
        return
    _validate_url(value)


def _entities(content: Content, indices: dict[int, int]) -> list[MessageEntity]:
    if not isinstance(content.entities, list):
        raise ValueError("Entities must be a list")
    result = []
    for raw in content.entities:
        if not isinstance(raw, dict) or not set(raw).issubset(_ENTITY_FIELDS):
            raise ValueError("Invalid Telegram entity")
        kind = raw.get("type")
        offset, length = raw.get("offset"), raw.get("length")
        if (
            not isinstance(kind, str)
            or kind not in _ENTITY_TYPES
            or type(offset) is not int
            or type(length) is not int
            or length <= 0
            or offset not in indices
            or offset + length not in indices
        ):
            raise ValueError("Invalid Telegram UTF-16 entity range or type")
        if kind not in _FORMATTING and length > TEXT_LIMIT:
            raise ValueError("An indivisible entity exceeds the text limit")
        if kind == "text_link":
            _validate_url(raw.get("url"))
        elif raw.get("url") is not None:
            _validate_url(raw["url"])
        if kind == "url":
            _validate_url(content.text[indices[offset] : indices[offset + length]])
        if kind == "text_mention" and not raw.get("user"):
            raise ValueError("A text mention requires its native user")
        if kind == "custom_emoji" and not (
            isinstance(raw.get("custom_emoji_id"), str)
            and raw["custom_emoji_id"].isascii()
            and raw["custom_emoji_id"].isdigit()
            and int(raw["custom_emoji_id"]) > 0
        ):
            raise ValueError("A custom emoji requires a native emoji ID")
        try:
            result.append(MessageEntity.model_validate(raw))
        except ValueError:
            raise ValueError("Invalid Telegram entity data") from None

    # Telegram permits nested formatting, not crossing spans or nested links.
    ordered = sorted(result, key=lambda e: (e.offset, -e.length))
    active: list[MessageEntity] = []
    for entity in ordered:
        active = [other for other in active if other.offset + other.length > entity.offset]
        for other in active:
            if entity.offset + entity.length > other.offset + other.length:
                raise ValueError("Telegram entities must not have crossing ranges")
            if (
                {entity.type, other.type} & {"code", "pre"}
                or (entity.type not in _FORMATTING and other.type not in _FORMATTING)
                or (
                    entity.type in {"blockquote", "expandable_blockquote"}
                    and other.type in {"blockquote", "expandable_blockquote"}
                )
            ):
                raise ValueError("Unsupported nested Telegram entities")
        active.append(entity)
    return result


def _keyboard(content: Content) -> InlineKeyboardMarkup | None:
    if not isinstance(content.buttons, list):
        raise ValueError("Buttons must be rows of plain labels")
    if not content.buttons:
        return None
    rows = []
    count = 0
    for row in content.buttons:
        if not isinstance(row, list) or not 1 <= len(row) <= 8:
            raise ValueError("Button rows require one to eight buttons")
        buttons = []
        for button in row:
            if not isinstance(button, Button) or not isinstance(button.text, str):
                raise ValueError("Invalid button")
            label = button.text
            try:
                valid_length = 1 <= len(label.encode("utf-8")) <= 64
            except UnicodeError:
                valid_length = False
            if (
                not valid_length
                or not label.strip()
                or any(ord(c) < 32 or ord(c) == 127 or c in "\u2028\u2029" for c in label)
            ):
                raise ValueError("Button labels must be plain, nonempty and at most 64 bytes")
            if (button.url is None) == (button.action is None):
                raise ValueError("A button requires exactly one URL or action")
            if button.url is not None:
                _validate_url(button.url)
                buttons.append(InlineKeyboardButton(text=label, url=button.url))
            else:
                if not isinstance(button.action, str) or button.action not in ACTIONS:
                    raise ValueError("Unsupported button action")
                buttons.append(
                    InlineKeyboardButton(text=label, callback_data=f"go:{button.action}")
                )
        rows.append(buttons)
        count += len(buttons)
    if count > 100:
        raise ValueError("Too many buttons")
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _validated(content: Content):
    if not isinstance(content, Content) or not isinstance(content.text, str):
        raise ValueError("Content must contain plain text")
    offsets, indices = _boundaries(content.text)
    if content.text and not content.text.strip():
        raise ValueError("Text must not consist only of whitespace")
    if not isinstance(content.media, list) or len(content.media) > 10:
        raise ValueError("Media groups contain two to ten items")
    for media in content.media:
        _validate_media(media)
    if not content.media and not content.text.strip():
        raise ValueError("Content must contain text or media")
    entities = _entities(content, indices)
    keyboard = _keyboard(content)
    return offsets, indices, entities, keyboard


def validate_content(content: Content) -> None:
    """Raise ValueError for content that cannot be delivered safely and natively."""
    _validated(content)


def _text_parts(text, offsets, indices, entities):
    parts = []
    start = 0
    total = offsets[-1]
    atomic = [e for e in entities if e.type not in _FORMATTING]
    while start < total:
        end = offsets[bisect_right(offsets, min(start + TEXT_LIMIT, total)) - 1]
        # Move the boundary before an indivisible entity instead of clipping it.
        while True:
            crossing = [e.offset for e in atomic if e.offset < end < e.offset + e.length]
            if not crossing:
                break
            end = min(crossing)
        if end <= start:
            raise ValueError("An indivisible entity cannot fit a Telegram message")
        local = []
        for entity in entities:
            left = max(start, entity.offset)
            right = min(end, entity.offset + entity.length)
            if left < right:
                local.append(
                    entity.model_copy(update={"offset": left - start, "length": right - left})
                )
        parts.append(
            {
                "method": "send_message",
                "text": text[indices[start] : indices[end]],
                "entities": local,
                "parse_mode": None,
                "allow_paid_broadcast": False,
            }
        )
        start = end
    return parts


def prepare_parts(content: Content) -> list[dict]:
    """Return aiogram kwargs plus a whitelisted method, never including chat_id.

    A single item gets a caption only when the *whole* text fits. Albums always
    precede a separate text/keyboard message, since sendMediaGroup has no keyboard.
    """
    offsets, indices, entities, keyboard = _validated(content)
    parts = []
    if len(content.media) == 1:
        media = content.media[0]
        part = {
            "method": f"send_{media.kind}",
            media.kind: media.file_id,
            "parse_mode": None,
            "allow_paid_broadcast": False,
        }
        if offsets[-1] <= CAPTION_LIMIT:
            part.update(caption=content.text or None, caption_entities=entities)
            if keyboard is not None:
                part["reply_markup"] = keyboard
            return [part]
        parts.append(part)
    elif content.media:
        group = [
            (InputMediaPhoto if item.kind == "photo" else InputMediaVideo)(
                media=item.file_id,
                parse_mode=None,
            )
            for item in content.media
        ]
        parts.append({"method": "send_media_group", "media": group, "allow_paid_broadcast": False})
    parts.extend(_text_parts(content.text, offsets, indices, entities))
    if keyboard is not None:
        if not content.text:
            parts.append(
                {
                    "method": "send_message",
                    "text": "Выберите действие:",
                    "entities": [],
                    "parse_mode": None,
                    "allow_paid_broadcast": False,
                }
            )
        parts[-1]["reply_markup"] = keyboard
    return parts
