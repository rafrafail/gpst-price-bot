"""Offline content contract checks using real aiogram payload models."""

from copy import deepcopy

import pytest
from aiogram.methods import SendMediaGroup, SendMessage, SendPhoto, SendVideo
from aiogram.types import InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo, MessageEntity

from bot_template.content import prepare_parts, validate_content
from bot_template.models import Button, Content, Media


def units(text):
    return len(text.encode("utf-16-le")) // 2


def test_plain_text_is_not_markdown_and_preserves_native_entities():
    content = Content("😀 <literal> *text*", [{"type": "bold", "offset": 3, "length": 9}])
    before = deepcopy(content.to_dict())
    assert validate_content(content) is None
    (part,) = prepare_parts(content)
    assert part["method"] == "send_message"
    assert part["text"] == content.text
    assert part["parse_mode"] is None
    assert part["entities"] == [MessageEntity(type="bold", offset=3, length=9)]
    assert content.to_dict() == before
    assert "chat_id" not in part
    assert part["allow_paid_broadcast"] is False


def test_utf16_split_clips_formatting_without_losing_text_or_emoji():
    text = "a" * 3999 + "😀" + "б" * 4500
    content = Content(text, [{"type": "bold", "offset": 3990, "length": 2000}])
    parts = prepare_parts(content)
    assert "".join(p["text"] for p in parts) == text
    assert all(0 < units(p["text"]) <= 4000 for p in parts)
    assert parts[0]["entities"][0].length == 9
    assert parts[1]["text"].startswith("😀")
    assert parts[1]["entities"][0].offset == 0
    assert parts[1]["entities"][0].length == 1991


def test_atomic_link_moves_to_next_part_preserving_its_data():
    content = Content(
        "x" * 3990 + "link" * 10,
        [
            {"type": "text_link", "offset": 3990, "length": 40, "url": "https://example.org/path"},
        ],
    )
    first, second = prepare_parts(content)
    assert len(first["text"]) == 3990
    assert first["entities"] == []
    assert second["entities"][0].model_dump(exclude_none=True) == {
        "type": "text_link",
        "offset": 0,
        "length": 40,
        "url": "https://example.org/path",
    }


@pytest.mark.parametrize("kind,method", [("photo", "send_photo"), ("video", "send_video")])
def test_single_media_short_caption_and_keyboard(kind, method):
    content = Content(
        "😀 hi",
        [{"type": "italic", "offset": 3, "length": 2}],
        [Media(kind, "native_file_id")],
        [[Button("Домой", action="home")]],
    )
    (part,) = prepare_parts(content)
    assert part["method"] == method
    assert part[kind] == "native_file_id"
    assert part["caption"] == content.text
    assert part["caption_entities"][0].offset == 3
    assert isinstance(part["reply_markup"], InlineKeyboardMarkup)
    assert part["reply_markup"].inline_keyboard[0][0].callback_data == "go:home"
    assert part["parse_mode"] is None


def test_caption_limit_is_utf16_and_long_caption_becomes_text():
    caption = "😀" * 512
    assert len(prepare_parts(Content(caption, media=[Media("photo", "file")]))) == 1
    content = Content(
        caption + "a",
        [{"type": "bold", "offset": 0, "length": 1025}],
        [Media("photo", "file")],
        [[Button("Открыть", url="https://example.org")]],
    )
    media, text = prepare_parts(content)
    assert media["method"] == "send_photo"
    assert media.get("caption") in (None, "")
    assert "reply_markup" not in media
    assert text["text"] == content.text
    assert text["entities"][0].length == 1025
    assert text["reply_markup"].inline_keyboard[0][0].url == "https://example.org"


def test_album_is_one_group_then_text_and_keyboard():
    content = Content(
        "Album description",
        media=[Media("photo", "a"), Media("video", "b")],
        buttons=[[Button("Help", action="help")]],
    )
    album, text = prepare_parts(content)
    assert album["method"] == "send_media_group"
    assert isinstance(album["media"][0], InputMediaPhoto)
    assert isinstance(album["media"][1], InputMediaVideo)
    assert all(m.caption is None and m.parse_mode is None for m in album["media"])
    assert "reply_markup" not in album
    assert text["text"] == content.text
    assert text["reply_markup"].inline_keyboard[0][0].callback_data == "go:help"


def test_media_only_album_with_buttons_has_meaningful_text():
    content = Content(
        media=[Media("photo", "a"), Media("photo", "b")], buttons=[[Button("Menu", action="home")]]
    )
    album, text = prepare_parts(content)
    assert album["method"] == "send_media_group"
    assert text["text"].strip() and len(text["text"].strip()) > 1
    assert text["reply_markup"]
    assert len(prepare_parts(Content(media=content.media))) == 1


def test_keyboard_on_final_text_only_and_actions_are_whitelisted():
    content = Content(
        "x" * 8001,
        buttons=[
            [
                Button(action.title(), action=action)
                for action in ("home", "help", "example", "preferences")
            ]
        ],
    )
    parts = prepare_parts(content)
    assert all("reply_markup" not in p for p in parts[:-1])
    assert [b.callback_data for b in parts[-1]["reply_markup"].inline_keyboard[0]] == [
        "go:home",
        "go:help",
        "go:example",
        "go:preferences",
    ]


@pytest.mark.parametrize(
    "content",
    [
        Content(),
        Content("  \n"),
        Content(entities=[{"type": "bold", "offset": 0, "length": 1}]),
        Content("bad\ud800"),
        Content("a\x00b"),
        Content(media=[Media("audio", "id")]),
        Content(media=[Media("photo", "")]),
        Content(media=[Media("photo", "id")] * 11),
        Content(media=[Media([], "id")]),
        Content(
            " \n",
            media=[Media("photo", "id"), Media("video", "id")],
            buttons=[[Button("Home", action="home")]],
        ),
        Content("ok", buttons=[[]]),
        Content("ok", buttons=[[Button("\x00", action="home")]]),
        Content("ok", buttons=[[Button("a\nb", action="home")]]),
        Content("ok", buttons=[[Button("  ", action="home")]]),
        Content("ok", buttons=[[Button("😀" * 17, action="home")]]),
        Content("ok", buttons=[[Button("A", action="admin")]]),
        Content("ok", buttons=[[Button("A", action="home", url="https://example.org")]]),
        Content("ok", buttons=[[Button("A")]]),
        Content("ok", [{"type": "not_supported", "offset": 0, "length": 1}]),
        Content("😀x", [{"type": "bold", "offset": 1, "length": 1}]),
        Content("x", [{"type": "bold", "offset": 0, "length": 2}]),
        Content("x", [{"type": "bold", "offset": -1, "length": 1}]),
        Content("x", [{"type": "bold", "offset": True, "length": 1}]),
        Content("x", [{"type": "bold", "offset": 0, "length": 0}]),
        Content("x", [{"type": "text_link", "offset": 0, "length": 1}]),
        Content("x", [{"type": "text_mention", "offset": 0, "length": 1}]),
        Content("x", [{"type": "custom_emoji", "offset": 0, "length": 1}]),
        Content(
            "abcdef",
            [
                {"type": "bold", "offset": 0, "length": 4},
                {"type": "italic", "offset": 2, "length": 4},
            ],
        ),
        Content(
            "x" * 4001,
            [{"type": "text_link", "offset": 0, "length": 4001, "url": "https://example.org"}],
        ),
    ],
)
def test_invalid_content_is_rejected_before_preparing_any_parts(content):
    with pytest.raises(ValueError):
        validate_content(content)
    with pytest.raises(ValueError):
        prepare_parts(content)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.org/file",
        "javascript:alert(1)",
        "https://user:pass@example.org",
        "https://user@example.org",
        "https://",
        "http://example.org:bad",
        "http://example.org:70000",
        "https://exa mple.org",
        "https://example.org/\npath",
        "//example.org/path",
        "https://example.org\\@evil.test",
    ],
)
def test_unsafe_urls_are_rejected_everywhere(url):
    for content in [
        Content("ok", buttons=[[Button("Open", url=url)]]),
        Content("link", [{"type": "text_link", "offset": 0, "length": 4, "url": url}]),
        Content(media=[Media("photo", url)]),
        Content(url, [{"type": "url", "offset": 0, "length": units(url)}]),
    ]:
        with pytest.raises(ValueError):
            validate_content(content)


def test_native_entity_metadata_survives_roundtrip_and_splitting():
    entities = [
        {
            "type": "text_mention",
            "offset": 4000,
            "length": 3,
            "user": {"id": 42, "is_bot": False, "first_name": "Test"},
        },
        {"type": "custom_emoji", "offset": 4004, "length": 2, "custom_emoji_id": "123456"},
        {"type": "pre", "offset": 4007, "length": 4, "language": "python"},
    ]
    parts = prepare_parts(Content("x" * 4000 + "Bob 😀 code", entities))
    assert parts[1]["entities"][0].user.id == 42
    assert parts[1]["entities"][1].custom_emoji_id == "123456"
    assert parts[1]["entities"][1].offset == 4
    assert parts[1]["entities"][2].language == "python"


@pytest.mark.parametrize("count", [2, 10])
def test_album_count_boundaries_and_valid_http_media(count):
    content = Content(media=[Media("photo", "https://example.org/image.jpg")] * count)
    (part,) = prepare_parts(content)
    assert part["method"] == "send_media_group"
    assert len(part["media"]) == count


def test_exactly_64_utf8_bytes_is_a_valid_plain_label():
    label = "😀" * 16
    (part,) = prepare_parts(Content("text", buttons=[[Button(label, action="home")]]))
    assert part["reply_markup"].inline_keyboard[0][0].text == label


def test_nested_formatting_and_multichunk_pre_language_remain_native():
    text = "😀" * 5000
    parts = prepare_parts(
        Content(text, [{"type": "pre", "offset": 0, "length": 10000, "language": "python"}])
    )
    assert "".join(p["text"] for p in parts) == text
    assert [p["entities"][0].length for p in parts] == [4000, 4000, 2000]
    assert all(p["entities"][0].language == "python" for p in parts)
    nested = prepare_parts(
        Content(
            "x" * 8000,
            [
                {"type": "bold", "offset": 0, "length": 8000},
                {"type": "italic", "offset": 3999, "length": 2},
            ],
        )
    )
    assert nested[0]["entities"][1].length == 1
    assert nested[1]["entities"][1].offset == 0
    assert nested[1]["entities"][1].length == 1


def test_small_atomic_custom_emoji_is_never_sliced_at_limit():
    text = "x" * 3999 + "😀" + "end"
    parts = prepare_parts(
        Content(
            text,
            [{"type": "custom_emoji", "offset": 3999, "length": 2, "custom_emoji_id": "12345"}],
        )
    )
    assert parts[0]["text"] == "x" * 3999
    assert parts[0]["entities"] == []
    assert parts[1]["text"] == "😀end"
    assert parts[1]["entities"][0].offset == 0
    assert parts[1]["entities"][0].length == 2


def test_prepared_payloads_validate_with_real_bot_api_models():
    methods = {
        "send_message": SendMessage,
        "send_photo": SendPhoto,
        "send_video": SendVideo,
        "send_media_group": SendMediaGroup,
    }
    for content in [
        Content("plain *literal*", buttons=[[Button("Home", action="home")]]),
        Content("caption", media=[Media("photo", "file")]),
        Content("caption", media=[Media("video", "file")]),
        Content("x" * 5000, media=[Media("photo", "a"), Media("video", "b")]),
    ]:
        for part in prepare_parts(content):
            payload = dict(part)
            method = methods[payload.pop("method")](chat_id=42, **payload)
            assert method.allow_paid_broadcast is False
            assert method.model_dump()["chat_id"] == 42
