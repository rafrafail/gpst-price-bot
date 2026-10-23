"""Regression/security checks that do not touch existing user data or credentials."""
import ast
import csv
import logging
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import List
from unittest.mock import AsyncMock

import pytest

from bot_template.content import prepare_parts
from bot_template.models import Content
from bot_template.runtime import SafeFormatter
from bot_template.storage import Store
from tests.helpers import Harness


async def test_double_optout_is_idempotent(tmp_path):
    h = await Harness(tmp_path / "ui.sqlite3").start()
    try:
        await h.send("/start")
        await h.press("⚙️ Уведомления")
        await h.click("subscribe:0")
        await h.click("subscribe:0")
        await h.send("/start")
        assert not await h.store.is_subscribed(h.uid)
    finally:
        await h.close()


async def test_album_cannot_land_in_a_different_draft(tmp_path):
    h = await Harness(tmp_path / "ui.sqlite3").start()
    try:
        first = await h.draft("Первый")
        await h.press("🖼 Медиа")
        await h.send(media_group_id="late", photo=[{"file_id": "PHOTO_ID", "file_unique_id": "UNIQUE",
                                                   "width": 20, "height": 20}])
        await h.press("🏠 Главное меню")
        await h.press("📣 Рассылки")
        await h.press("＋ Создать рассылку")
        await h.app.close()
        posts = await h.store.list_campaigns(h.uid)
        assert all(not post.content.media for post in posts)
        saved = await h.store.get_campaign(first.id)
        assert saved is not None and saved.content.text == "Первый"
        assert "предыдущему шагу" in h.session.panel.text
    finally:
        await h.close()


async def test_database_private_and_legacy_database_is_not_migrated(tmp_path):
    path = tmp_path / "v2.sqlite3"
    await Store(path).initialize()
    assert path.stat().st_mode & 0o777 == 0o600
    legacy = tmp_path / "old.sqlite3"
    with sqlite3.connect(legacy) as connection:
        connection.execute("CREATE TABLE users(telegram_id INTEGER PRIMARY KEY, created_at TEXT)")
        connection.execute("INSERT INTO users VALUES(101,'original')")
        connection.commit()
    before = legacy.read_bytes()
    with pytest.raises(ValueError, match="legacy database"):
        await Store(legacy).initialize()
    assert legacy.read_bytes() == before


def test_native_bare_domain_preserved_without_rewriting():
    text = "example.com/path"
    content = Content(text, [{"type": "url", "offset": 0, "length": len(text)}])
    part, = prepare_parts(content)
    assert part["text"] == text
    assert part["entities"][0].type == "url"


def test_logging_formatter_redacts_token_in_message_and_exception():
    token = "123456:" + "T" * 35
    formatter = SafeFormatter(token)
    record = logging.LogRecord("test", logging.ERROR, "test", 1,
                               "Failed https://api.telegram.org/bot%s/sendMessage", (token,), None)
    assert token not in formatter.format(record)
    try:
        raise RuntimeError("https://api.telegram.org/file/bot" + token + "/file")
    except RuntimeError:
        import sys
        record.exc_info = sys.exc_info()
        assert token not in formatter.format(record)


async def test_legacy_export_uses_file_ids_and_never_requests_secret_urls(tmp_path):
    # Compile ONLY this pure export function, not the obsolete v1 runtime or its globals.
    # Only newly generated synthetic CSV is read; existing broadcast_logs are untouched.
    source = Path(__file__).resolve().parents[1] / "features/admin/broadcast.py"
    tree = ast.parse(source.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                and n.name == "create_broadcast_text_file")
    namespace = {"Path": Path, "List": List, "Bot": object, "csv": csv,
                 "logger": SimpleNamespace(info=lambda *_: None),
                 "_get_broadcast_filename": lambda *_, **__: "synthetic.csv"}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)
    token = "123456:" + "T" * 35
    bot = SimpleNamespace(token=token, get_file=AsyncMock(side_effect=AssertionError("No network")))
    output = await namespace["create_broadcast_text_file"](
        "synthetic", "TEST", ["photo_id"], ["video_id"], [], tmp_path, bot)
    text = output.read_text(encoding="utf-8-sig")
    assert "photo_id" in text and "video_id" in text
    assert token not in text and "api.telegram.org" not in text
    bot.get_file.assert_not_awaited()
