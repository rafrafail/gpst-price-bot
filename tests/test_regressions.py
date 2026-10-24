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


async def test_stale_editor_callback_cannot_redirect_input_to_another_draft(tmp_path):
    h = await Harness(tmp_path / "ui.sqlite3").start()
    try:
        first = await h.draft("Первый")
        stale = f"edit:text:{first.id}:{first.revision}"
        await h.press("🏠 Главное меню")
        await h.press("📣 Рассылки")
        await h.press("＋ Создать рассылку")
        await h.send("Второй")
        second = (await h.store.list_campaigns(h.uid))[0]
        await h.click(stale)
        ui = await h.store.get_ui(h.uid)
        assert ui["screen"] == f"campaign:{second.id}"
        assert ui["input"] is None
        await h.press("✏️ Текст")
        await h.send("Второй изменён")
        assert (await h.store.get_campaign(first.id)).content.text == "Первый"
        assert (await h.store.get_campaign(second.id)).content.text == "Второй изменён"
    finally:
        await h.close()


@pytest.mark.parametrize("restart", [False, True])
async def test_late_album_fragment_cannot_land_in_another_draft_after_flush(tmp_path, restart):
    from bot_template.app import Application
    h = await Harness(tmp_path / "ui.sqlite3").start()
    def photo(identifier):
        return [{"file_id": identifier, "file_unique_id": identifier,
                 "width": 20, "height": 20}]
    try:
        first = await h.draft("Первый")
        await h.press("🖼 Медиа")
        await h.send(media_group_id="delayed", photo=photo("FIRST"))
        await h.app.close()  # first group is already flushed and no longer buffered
        if restart:
            h.app = Application(h.bot, Store(h.settings.database), h.settings)
            h.dp = h.app.dispatcher()
        await h.press("🏠 Главное меню")
        await h.press("📣 Рассылки")
        await h.press("＋ Создать рассылку")
        await h.send("Второй")
        second = (await h.store.list_campaigns(h.uid))[0]
        await h.press("🖼 Медиа")
        await h.send(media_group_id="delayed", photo=photo("LATE"))
        await h.app.close()
        assert not (await h.store.get_campaign(second.id)).content.media
        assert [m.file_id for m in (await h.store.get_campaign(first.id)).content.media] == ["FIRST"]
        assert (await h.store.get_ui(h.uid))["input"]["id"] == second.id
    finally:
        await h.close()


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
