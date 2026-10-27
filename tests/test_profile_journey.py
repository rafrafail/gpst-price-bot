"""Tests for profile-driven menu and example section toggling."""
from tests.helpers import Harness


async def test_profile_menu_order_and_sections(tmp_path):
    """Profile defines menu order, custom sections appear in that order."""
    from bot_template.config import Settings
    from bot_template.profile import BotProfile, ExampleConfig, ProfileSection

    profile = BotProfile(
        title="Тест профиль",
        welcome="Привет из профиля!",
        help="Справка профиля",
        support_url="https://t.me/test_support",
        menu_order=["about", "features", "help", "preferences", "broadcasts"],
        sections=[
            ProfileSection(id="about", label="О нас", text="Описание"),
            ProfileSection(id="features", label="Фичи", text="Возможности"),
        ],
        example=ExampleConfig(enabled=False),
    )

    settings = Settings(
        admins=frozenset({101}),
        database=tmp_path / "profile_test.sqlite3",
        broadcasts=True,
        profile=profile,
    )

    h = await Harness(settings.database, broadcasts=True).start()
    try:
        h.settings = settings
        h.app = h.app.__class__(h.bot, h.store, settings)
        h.dp = h.app.dispatcher()

        await h.send("/start")
        # Check menu shows sections in profile order
        panel = h.session.panel
        buttons = [btn.text for row in panel.reply_markup.inline_keyboard for btn in row]

        # about section first
        assert "О нас" in buttons
        # features section second
        assert "Фичи" in buttons
        # help third
        assert "❔ Помощь" in buttons
        # preferences fourth
        assert "⚙️ Уведомления" in buttons
        # broadcasts fifth (admin)
        assert "📣 Рассылки" in buttons
        # Support URL present
        assert "💬 Поддержка" in buttons

        # Navigate to custom section
        await h.press("Фичи")
        assert "Возможности" in h.session.panel.text
        await h.press("← Назад")
        assert (await h.store.get_ui(h.uid))["screen"] == "home"
    finally:
        await h.close()


async def test_example_section_disabled_by_profile(tmp_path):
    """When example.enabled=false, example section is hidden and inaccessible."""
    from bot_template.config import Settings
    from bot_template.profile import BotProfile, ExampleConfig

    profile = BotProfile(
        title="Без примера",
        example=ExampleConfig(enabled=False),
    )

    settings = Settings(
        admins=frozenset({101}),
        database=tmp_path / "no_example.sqlite3",
        broadcasts=True,
        profile=profile,
    )

    h = await Harness(settings.database, broadcasts=True).start()
    try:
        h.settings = settings
        h.app = h.app.__class__(h.bot, h.store, settings)
        h.dp = h.app.dispatcher()

        await h.send("/start")
        buttons = [btn.text for row in h.session.panel.reply_markup.inline_keyboard for btn in row]
        assert "🧩 Пример раздела" not in buttons

        # Direct navigation to example should redirect to home with notice
        await h.send("/menu")
        await h.click("go:example")
        assert "отключён" in h.session.panel.text
        assert (await h.store.get_ui(h.uid))["screen"] == "home"
    finally:
        await h.close()


async def test_example_section_enabled_by_profile(tmp_path):
    """When example.enabled=true, example section works normally."""
    from bot_template.config import Settings
    from bot_template.profile import BotProfile, ExampleConfig

    profile = BotProfile(
        title="С примером",
        example=ExampleConfig(enabled=True),
    )

    settings = Settings(
        admins=frozenset({101}),
        database=tmp_path / "with_example.sqlite3",
        broadcasts=True,
        profile=profile,
    )

    h = await Harness(settings.database, broadcasts=True).start()
    try:
        h.settings = settings
        h.app = h.app.__class__(h.bot, h.store, settings)
        h.dp = h.app.dispatcher()

        await h.send("/start")
        buttons = [btn.text for row in h.session.panel.reply_markup.inline_keyboard for btn in row]
        assert "🧩 Пример раздела" in buttons

        await h.press("🧩 Пример раздела")
        assert "Пример независимого раздела" in h.session.panel.text

        # Note editing still works
        await h.press("📝 Моя заметка")
        await h.press("✏️ Изменить")
        await h.send("Моя тестовая заметка")
        assert "Моя тестовая заметка" in h.session.panel.text
    finally:
        await h.close()


async def test_example_disabled_preserves_saved_note(tmp_path):
    """Disabling example doesn't delete saved note; it's just hidden."""
    from bot_template.config import Settings
    from bot_template.profile import BotProfile, ExampleConfig

    # First enable, save note
    profile1 = BotProfile(example=ExampleConfig(enabled=True))
    settings1 = Settings(
        admins=frozenset({101}),
        database=tmp_path / "persist_note.sqlite3",
        broadcasts=True,
        profile=profile1,
    )

    h = await Harness(settings1.database, broadcasts=True).start()
    try:
        h.settings = settings1
        h.app = h.app.__class__(h.bot, h.store, settings1)
        h.dp = h.app.dispatcher()

        await h.send("/start")
        await h.press("🧩 Пример раздела")
        await h.press("📝 Моя заметка")
        await h.press("✏️ Изменить")
        await h.send("Сохранённая заметка")
        await h.press("← Назад")
        await h.press("← Назад")  # back to home
    finally:
        await h.close()

    # Now disable example, reopen bot
    profile2 = BotProfile(example=ExampleConfig(enabled=False))
    settings2 = Settings(
        admins=frozenset({101}),
        database=tmp_path / "persist_note.sqlite3",
        broadcasts=True,
        profile=profile2,
    )

    h2 = await Harness(settings2.database, broadcasts=True).start()
    try:
        h2.settings = settings2
        h2.app = h2.app.__class__(h2.bot, h2.store, settings2)
        h2.dp = h2.app.dispatcher()

        await h2.send("/start")
        # Note data still in DB
        ui = await h2.store.get_ui(101)
        assert ui.get("note") == "Сохранённая заметка"
        # But example section not shown
        buttons = [btn.text for row in h2.session.panel.reply_markup.inline_keyboard for btn in row]
        assert "🧩 Пример раздела" not in buttons
    finally:
        await h2.close()


async def test_old_example_callback_after_profile_change(tmp_path):
    """Old go:example callback safely redirects to home with explanation."""
    from bot_template.config import Settings
    from bot_template.profile import BotProfile, ExampleConfig

    profile = BotProfile(example=ExampleConfig(enabled=False))
    settings = Settings(
        admins=frozenset({101}),
        database=tmp_path / "old_callback.sqlite3",
        broadcasts=True,
        profile=profile,
    )

    h = await Harness(settings.database, broadcasts=True).start()
    try:
        h.settings = settings
        h.app = h.app.__class__(h.bot, h.store, settings)
        h.dp = h.app.dispatcher()

        await h.send("/start")
        # Simulate old callback from previously sent message
        await h.click("go:example")
        assert "отключён" in h.session.panel.text
        assert (await h.store.get_ui(h.uid))["screen"] == "home"
    finally:
        await h.close()


async def test_profile_settings_independence(tmp_path):
    """Profile settings independent: example × broadcasts × admin/user."""
    from bot_template.config import Settings
    from bot_template.profile import BotProfile, ExampleConfig

    # User without admin, example enabled, broadcasts disabled
    profile = BotProfile(example=ExampleConfig(enabled=True))
    settings = Settings(
        admins=frozenset({999}),  # different admin
        database=tmp_path / "independence.sqlite3",
        broadcasts=False,  # broadcasts off
        profile=profile,
    )

    h = await Harness(settings.database, broadcasts=False).start()
    try:
        h.settings = settings
        h.app = h.app.__class__(h.bot, h.store, settings)
        h.dp = h.app.dispatcher()

        await h.send("/start")
        buttons = [btn.text for row in h.session.panel.reply_markup.inline_keyboard for btn in row]
        # Example visible
        assert "🧩 Пример раздела" in buttons
        # No broadcasts (not admin and broadcasts disabled)
        assert "📣 Рассылки" not in buttons
        # Preferences visible
        assert "⚙️ Уведомления" in buttons

        await h.press("🧩 Пример раздела")
        assert "Пример независимого раздела" in h.session.panel.text
    finally:
        await h.close()


async def test_profile_priority_over_env(tmp_path, monkeypatch):
    """Explicit BOT_TITLE env overrides profile title."""
    from bot_template.config import Settings

    with open(tmp_path / "profile.toml", "w") as f:
        f.write("""
[bot]
title = "Из профиля"
welcome = "Привет профиля"
help = "Справка профиля"
""")

    monkeypatch.setenv("BOT_PROFILE_PATH", str(tmp_path / "profile.toml"))
    monkeypatch.setenv("ADMIN_IDS", "101")
    monkeypatch.setenv("BOT_TOKEN", "test")
    monkeypatch.setenv("BOT_TITLE", "Из env")

    settings = Settings.from_env()
    assert settings.title == "Из env"
    assert settings.profile.title == "Из профиля"
    assert settings.profile.welcome == "Привет профиля"
    assert settings.profile.help == "Справка профиля"

    monkeypatch.delenv("BOT_TITLE", raising=False)
    monkeypatch.delenv("BOT_PROFILE_PATH", raising=False)
    monkeypatch.delenv("ADMIN_IDS", raising=False)
    monkeypatch.delenv("BOT_TOKEN", raising=False)


async def test_broadcasts_off_admin_sees_no_broadcasts(tmp_path):
    """When broadcasts disabled, admin doesn't see broadcasts in menu."""
    from bot_template.config import Settings
    from bot_template.profile import BotProfile

    profile = BotProfile()
    settings = Settings(
        admins=frozenset({101}),
        database=tmp_path / "no_broadcasts.sqlite3",
        broadcasts=False,
        profile=profile,
    )

    h = await Harness(settings.database, broadcasts=False).start()
    try:
        h.settings = settings
        h.app = h.app.__class__(h.bot, h.store, settings)
        h.dp = h.app.dispatcher()

        await h.send("/start")
        buttons = [btn.text for row in h.session.panel.reply_markup.inline_keyboard for btn in row]
        assert "📣 Рассылки" not in buttons
        # /broadcast command still works for admin but shouldn't show in menu
        await h.send("/broadcast")
        # Should open broadcasts (admin check passes) but menu doesn't show it
        assert "Рассылки" in h.session.panel.text
    finally:
        await h.close()