import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText
from bot_template.delivery import DeliveryWorker

from bot_template.app import Application, parse_schedule
from bot_template.models import Media
from tests.helpers import Harness


@pytest.fixture
async def h(tmp_path):
    value = await Harness(tmp_path / "ui.sqlite3").start()
    yield value
    await value.close()


async def test_one_panel_back_and_persistent_note_without_broadcasts(tmp_path):
    h = await Harness(tmp_path / "independent.sqlite3", broadcasts=False).start()
    try:
        await h.send("/start")
        assert "Рассылки" not in str(h.session.panel.reply_markup)
        panel = (await h.store.get_ui(h.uid))["panel_id"]
        await h.press("🧩 Пример раздела")
        await h.press("📝 Моя заметка")
        await h.press("✏️ Изменить")
        await h.send("Моя сохранённая заметка")
        h.app = Application(h.bot, h.store, h.settings)
        h.dp = h.app.dispatcher()
        await h.press("← Назад")
        assert (await h.store.get_ui(h.uid))["screen"] == "example"
        await h.press("📝 Моя заметка")
        assert "Моя сохранённая заметка" in h.session.panel.text
        await h.send("/menu")
        assert (await h.store.get_ui(h.uid))["panel_id"] == panel
        assert len(h.session.payloads("sendMessage")) == 1
        await h.click("new")
        assert not await h.store.list_campaigns(h.uid)
    finally:
        await h.close()


async def test_draft_editing_preserves_media_buttons_and_back(h):
    post = await h.draft()
    await h.press("🖼 Медиа")
    await h.send(photo=[{"file_id": "PHOTO_ID", "file_unique_id": "UNIQUE", "width": 20, "height": 20}])
    await h.press("🔗 Кнопки")
    await h.send("Сайт | https://example.com ; Помощь | @help")
    await h.press("✏️ Текст")
    await h.send("Жирный текст.", entities=[{"type": "bold", "offset": 0, "length": 6}])
    updated = await h.store.get_campaign(post.id)
    assert updated.content.media == [Media("photo", "PHOTO_ID")]
    assert updated.content.buttons[0][1].action == "help"
    assert updated.content.entities[0]["type"] == "bold"
    await h.press("✏️ Текст")
    await h.press("🏠 Главное меню")
    assert (await h.store.get_campaign(post.id)).content == updated.content
    await h.press("📣 Рассылки")
    await h.press("Черновики")
    label = h.session.panel.reply_markup.inline_keyboard[0][0].text
    await h.press(label)
    await h.press("👥 Получатели")
    assert "Кто получит" in h.session.panel.text
    await h.press("← Назад")
    assert (await h.store.get_ui(h.uid))["screen"] == f"campaign:{post.id}"
    await h.press("← Назад")
    assert (await h.store.get_ui(h.uid))["screen"] == "list:draft:0"


async def test_preview_and_launch_use_same_native_payload_no_double_launch(h):
    post = await h.draft()
    await h.press("👥 Получатели")
    await h.press("Только я (проверка)")
    await h.press("👁 Предпросмотр")
    preview = h.session.payloads("sendMessage")[-1]
    assert preview.text == post.content.text
    assert preview.parse_mode is None
    await h.press("Продолжить к отправке")
    assert "Получателей: 1" in h.session.panel.text
    button = h.session.panel.reply_markup.inline_keyboard[0][0].callback_data
    await asyncio.gather(h.click(button), h.click(button))
    assert (await h.store.campaign_counts(post.id))["total"] == 1
    worker = DeliveryWorker(h.bot, h.store, pace_seconds=0)
    assert await worker.run_once()
    sent = h.session.payloads("sendMessage")[-1]
    assert sent.text == preview.text
    assert sent.entities == preview.entities
    assert (await h.store.get_campaign(post.id)).status == "completed"
    assert not await worker.run_once()


async def test_optout_survives_start_and_audience_change_requires_reconfirmation(h):
    post = await h.draft()
    await h.press("👥 Получатели")
    await h.press("Все подписчики")
    await h.press("Продолжить к отправке")
    await h.store.register_user(202)
    await h.press("✅ Подтвердить запуск")
    assert (await h.store.get_campaign(post.id)).status == "draft"
    await h.send("/menu")
    await h.press("⚙️ Уведомления")
    await h.press("Выключить рассылки")
    await h.send("/start")
    assert not await h.store.is_subscribed(h.uid)


async def test_guest_old_panel_and_foreign_campaign_cannot_mutate(h, tmp_path):
    post = await h.draft()
    revision = post.revision
    await h.click(f"edit:text:{post.id}:{revision}", panel_id=9876)
    assert (await h.store.get_ui(h.uid))["input"] is None
    guest = await Harness(h.settings.database, user_id=202).start()
    try:
        await guest.send("/start")
        await guest.click(f"open:campaign:{post.id}")
        await guest.click("new")
        await guest.click(f"control:stop:{post.id}")
        assert not await guest.store.list_campaigns(202)
        assert (await h.store.get_campaign(post.id)).revision == revision
    finally:
        await guest.close()
    await h.click("open:list:invalid:0")
    assert (await h.store.get_ui(h.uid))["screen"] == f"campaign:{post.id}"


async def test_deleted_panel_recreated_but_unchanged_panel_not_duplicated(h):
    await h.send("/start")
    h.session.error = TelegramBadRequest(EditMessageText(chat_id=h.uid, message_id=101, text="x"),
                                         "Bad Request: message is not modified")
    await h.send("/menu")
    assert len(h.session.payloads("sendMessage")) == 1
    h.session.error = TelegramBadRequest(EditMessageText(chat_id=h.uid, message_id=101, text="x"),
                                         "Bad Request: message to edit not found")
    await h.send("/menu")
    assert len(h.session.payloads("sendMessage")) == 2


async def test_schedule_past_rejected_and_future_uses_same_worker(h):
    post = await h.draft()
    await h.press("🕒 Когда")
    await h.press("Выбрать дату и время")
    await h.send("01.01.2001 12:00")
    assert (await h.store.get_ui(h.uid))["input"]["kind"] == "schedule"
    await h.send("/cancel")
    assert (await h.store.get_campaign(post.id)).scheduled_at is None
    post = await h.store.get_campaign(post.id)
    future = datetime.now(timezone.utc) + timedelta(days=1)
    post = await h.store.save_campaign(post.id, h.uid, expected_revision=post.revision,
                                       audience="self", scheduled_at=future.isoformat())
    await h.click(f"confirm:{post.id}:{post.revision}")
    await h.press("✅ Подтвердить запуск")
    worker = DeliveryWorker(h.bot, h.store, pace_seconds=0)
    assert not await worker.run_once()
    assert await worker.run_once(future + timedelta(seconds=1))
    assert (await h.store.get_campaign(post.id)).status == "completed"


async def test_album_and_pause_resume_stop_confirmation(h):
    post = await h.draft()
    await h.press("🖼 Медиа")
    for index in range(2):
        await h.send(media_group_id="album", photo=[{"file_id": f"PHOTO_{index}",
            "file_unique_id": f"UNIQUE_{index}", "width": 20, "height": 20}])
    await h.app.close()
    post = await h.store.get_campaign(post.id)
    assert len(post.content.media) == 2
    await h.click(f"audience:{post.id}:{post.revision}")
    await h.press("Только я (проверка)")
    await h.press("Продолжить к отправке")
    await h.press("✅ Подтвердить запуск")
    await h.press("⏸ Пауза")
    assert (await h.store.get_campaign(post.id)).status == "paused"
    await h.press("▶ Продолжить")
    await h.press("⏹ Остановить")
    assert (await h.store.get_campaign(post.id)).status == "running"
    await h.press("Подтвердить")
    assert (await h.store.get_campaign(post.id)).status == "stopped"


def test_schedule_timezone_and_dst():
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert parse_schedule("02.01.2025 12:00", "Asia/Yekaterinburg", now) == "2025-01-02T07:00:00+00:00"
    with pytest.raises(ValueError):
        parse_schedule("26.10.2025 02:30", "Europe/Berlin", now)
    with pytest.raises(ValueError):
        parse_schedule("30.03.2025 02:30", "Europe/Berlin", now)
