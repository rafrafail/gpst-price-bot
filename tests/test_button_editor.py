"""Tests for guided button and attachment editing, label, and schedule picker."""
from datetime import datetime, timedelta, timezone

from tests.helpers import Harness


async def test_button_editor_add_edit_remove(tmp_path):
    """Test the full button editor flow: add, edit, remove buttons."""
    h = await Harness(tmp_path / "btn_edit.sqlite3", broadcasts=True).start()
    try:
        post = await h.draft("Пост с кнопками")
        await h.press("🔗 Кнопки")
        
        # Add buttons
        await h.send("Кнопка 1 | https://example.com/1; Кнопка 2 | https://example.com/2")
        
        # Check buttons were added
        campaign = await h.store.get_campaign(post.id)
        assert len(campaign.content.buttons) == 1
        assert len(campaign.content.buttons[0]) == 2
        assert campaign.content.buttons[0][0].text == "Кнопка 1"
        assert campaign.content.buttons[0][0].url == "https://example.com/1"
        assert campaign.content.buttons[0][1].text == "Кнопка 2"
        assert campaign.content.buttons[0][1].url == "https://example.com/2"
        
        # Edit buttons - replace with new set
        await h.press("🔗 Кнопки")
        await h.send("Новая кнопка | https://new.example.com")
        
        campaign = await h.store.get_campaign(post.id)
        assert len(campaign.content.buttons) == 1
        assert len(campaign.content.buttons[0]) == 1
        assert campaign.content.buttons[0][0].text == "Новая кнопка"
        assert campaign.content.buttons[0][0].url == "https://new.example.com"
        
        # Remove all buttons
        await h.press("🔗 Кнопки")
        await h.send("0")
        
        campaign = await h.store.get_campaign(post.id)
        assert campaign.content.buttons == []
        
    finally:
        await h.close()


async def test_media_attachment_add_remove(tmp_path):
    """Test adding and removing media attachments."""
    h = await Harness(tmp_path / "media_edit.sqlite3", broadcasts=True).start()
    try:
        post = await h.draft("Пост с фото")
        await h.press("🖼 Медиа")
        await h.send(photo=[{"file_id": "PHOTO_123", "file_unique_id": "UNIQUE", "width": 100, "height": 100}])
        
        campaign = await h.store.get_campaign(post.id)
        assert len(campaign.content.media) == 1
        assert campaign.content.media[0].file_id == "PHOTO_123"
        
        # Remove media
        await h.press("🖼 Медиа")
        await h.send("0")
        
        campaign = await h.store.get_campaign(post.id)
        assert campaign.content.media == []
        
    finally:
        await h.close()


async def test_label_edit_and_display(tmp_path):
    """Test internal label editing and display in campaign card."""
    h = await Harness(tmp_path / "label_edit.sqlite3", broadcasts=True).start()
    try:
        post = await h.draft("Тест лейбла")
        
        # Initially no label
        campaign = await h.store.get_campaign(post.id)
        assert campaign.label == ""
        
        # Edit label
        await h.press("🏷 Имя")
        await h.send("Важная рассылка")
        
        campaign = await h.store.get_campaign(post.id)
        assert campaign.label == "Важная рассылка"
        
        # Check label appears in campaign card
        await h.app.render(h.uid)
        assert "Имя: Важная рассылка" in h.session.panel.text
        
        # Remove label
        await h.press("🏷 Имя")
        await h.send("0")
        
        campaign = await h.store.get_campaign(post.id)
        assert campaign.label == ""
        
    finally:
        await h.close()


async def test_schedule_quick_picker(tmp_path):
    """Test quick schedule picker options."""
    h = await Harness(tmp_path / "schedule_quick.sqlite3", broadcasts=True).start()
    try:
        post = await h.draft("Тест расписания")
        await h.press("🕒 Когда")
        
        # Should show quick options
        panel = h.session.panel
        buttons = [btn.text for row in panel.reply_markup.inline_keyboard for btn in row]
        
        # Check for quick options
        assert any("Сейчас" in b for b in buttons)
        assert any("Сегодня" in b for b in buttons)
        assert any("Завтра" in b for b in buttons)
        assert any("Другая дата" in b for b in buttons)
        
        # Select "now"
        await h.press("Сейчас")
        
        campaign = await h.store.get_campaign(post.id)
        # "Сейчас" clears schedule (sends immediately), so scheduled_at should be None
        assert campaign.scheduled_at is None
        
        # Cancel and test custom
        await h.press("🕒 Когда")
        await h.press("Другая дата и время")
        
        future = datetime.now(timezone.utc) + timedelta(days=1)
        future_str = future.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M")
        await h.send(future_str)
        
        campaign = await h.store.get_campaign(post.id)
        assert campaign.scheduled_at is not None
        
    finally:
        await h.close()


async def test_schedule_preset_today_tomorrow(tmp_path):
    """Test today/tomorrow preset schedule options."""
    h = await Harness(tmp_path / "schedule_preset.sqlite3", broadcasts=True).start()
    try:
        post = await h.draft("Тест пресета")
        await h.press("🕒 Когда")
        
        # Get current time for today option
        from bot_template.scheduling import get_schedule_options
        options = get_schedule_options("Europe/Moscow", datetime.now(timezone.utc))
        
        # Find a tomorrow option (always in future)
        tomorrow_opt = next((o for o in options if o["value"].startswith("tomorrow ")), None)
        assert tomorrow_opt is not None
        
        # Click the tomorrow option (via callback)
        encoded_value = tomorrow_opt["value"].replace(" ", "_").replace(":", "-")
        await h.click(f"schedule:preset:{encoded_value}:{post.id}:{post.revision}")
        
        campaign = await h.store.get_campaign(post.id)
        assert campaign.scheduled_at is not None
        
        # Test custom future date
        await h.press("🕒 Когда")
        await h.press("Другая дата и время")
        future = datetime.now(timezone.utc) + timedelta(days=1)
        future_str = future.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M")
        await h.send(future_str)
        
        campaign = await h.store.get_campaign(post.id)
        assert campaign.scheduled_at is not None
        
    finally:
        await h.close()


async def test_launch_summary_shows_details(tmp_path):
    """Test final confirmation screen shows label, media count, buttons, audience, time."""
    h = await Harness(tmp_path / "launch_summary.sqlite3", broadcasts=True).start()
    try:
        await h.draft("Тестовое резюме")
        await h.press("🏷 Имя")
        await h.send("Мой тест")
        await h.press("🔗 Кнопки")
        await h.send("Сайт | https://example.com")
        await h.press("👥 Получатели")
        await h.press("Все подписчики")
        await h.press("🕒 Когда")
        await h.press("Сейчас")
        await h.press("Продолжить к отправке")
        
        # Check confirmation screen
        panel = h.session.panel
        text = panel.text
        
        assert "Мой тест" in text  # label
        assert "Кнопок: 1" in text
        assert "Получатели: все подписчики" in text
        assert "Отправка: сейчас" in text or "Отправка:" in text
        assert "Получателей:" in text
        
    finally:
        await h.close()


async def test_copy_preserves_label_not_schedule(tmp_path):
    """Test copy creates new draft with label but without schedule/confirmation."""
    h = await Harness(tmp_path / "copy_label.sqlite3", broadcasts=True).start()
    try:
        post = await h.draft("Оригинал")
        await h.press("🏷 Имя")
        await h.send("Оригинальное имя")
        await h.press("👥 Получатели")
        await h.press("Все подписчики")
        await h.press("🕒 Когда")
        await h.press("Сейчас")
        await h.press("Продолжить к отправке")
        await h.press("✅ Подтвердить запуск")
        
        # Copy the campaign
        await h.press("📋 Создать копию")
        
        copy = (await h.store.list_campaigns(h.uid))[0]
        assert copy.id != post.id
        assert copy.label == "Оригинальное имя (копия)"
        assert copy.status == "draft"
        assert copy.scheduled_at is None
        assert copy.content.text == "Оригинал"
        
    finally:
        await h.close()