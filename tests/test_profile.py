"""Tests for bot profile configuration."""
import tempfile
from pathlib import Path

import pytest

from bot_template.config import Settings
from bot_template.profile import BotProfile, load_profile


def test_default_profile() -> None:
    """Default profile has sensible defaults."""
    profile = BotProfile()
    assert profile.title == "Мой бот"
    assert profile.welcome == "Добро пожаловать! Выберите раздел."
    assert "сервисе" in profile.help
    assert profile.support_url is None
    assert profile.example.enabled is True
    assert profile.menu_order == ["about", "example", "preferences", "help", "broadcasts"]


def test_load_nonexistent_profile_returns_defaults() -> None:
    """Loading non-existent path returns defaults."""
    profile = load_profile(Path("/nonexistent/path.toml"))
    assert isinstance(profile, BotProfile)
    assert profile.title == "Мой бот"


def test_load_none_returns_defaults() -> None:
    """Loading None returns defaults."""
    profile = load_profile(None)
    assert isinstance(profile, BotProfile)
    assert profile.title == "Мой бот"


def test_load_valid_profile() -> None:
    """Load a valid profile TOML."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write("""
[bot]
title = "Тестовый бот"
welcome = "Привет!"
help = "Справка"
support_url = "https://t.me/support"

[example]
enabled = false

[menu]
order = ["about", "help"]

[[sections]]
id = "about"
label = "О нас"
text = "Мы крутые"
""")
        path = Path(f.name)

    try:
        profile = load_profile(path)
        assert profile.title == "Тестовый бот"
        assert profile.welcome == "Привет!"
        assert profile.help == "Справка"
        assert profile.support_url == "https://t.me/support"
        assert profile.example.enabled is False
        assert profile.menu_order == ["about", "help"]
        assert len(profile.sections) == 1
        assert profile.sections[0].id == "about"
        assert profile.sections[0].label == "О нас"
        assert profile.sections[0].text == "Мы крутые"
    finally:
        path.unlink()


def test_profile_rejects_invalid_toml() -> None:
    """Invalid TOML raises ValueError."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write("not valid toml [")
        path = Path(f.name)

    try:
        with pytest.raises(ValueError, match="некорректный TOML"):
            load_profile(path)
    finally:
        path.unlink()


def test_profile_rejects_empty_title() -> None:
    """Empty title is rejected."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write('[bot]\ntitle = ""\n')
        path = Path(f.name)

    try:
        with pytest.raises(ValueError, match="bot.title"):
            load_profile(path)
    finally:
        path.unlink()


def test_profile_rejects_long_title() -> None:
    """Title longer than 80 chars is rejected."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write('[bot]\ntitle = "' + "x" * 81 + '"\n')
        path = Path(f.name)

    try:
        with pytest.raises(ValueError, match="bot.title не длиннее 80"):
            load_profile(path)
    finally:
        path.unlink()


def test_profile_rejects_invalid_support_url() -> None:
    """Invalid support URL is rejected."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write('[bot]\nsupport_url = "ftp://example.com"\n')
        path = Path(f.name)

    try:
        with pytest.raises(ValueError, match="support_url должен начинаться"):
            load_profile(path)
    finally:
        path.unlink()


def test_profile_rejects_http_non_loopback() -> None:
    """HTTP URL for non-loopback is rejected."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write('[bot]\nsupport_url = "http://example.com"\n')
        path = Path(f.name)

    try:
        with pytest.raises(ValueError, match="HTTP разрешён только для loopback"):
            load_profile(path)
    finally:
        path.unlink()


def test_profile_rejects_duplicate_section_ids() -> None:
    """Duplicate section IDs are rejected."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write("""
[[sections]]
id = "about"
label = "О нас"
text = "Текст 1"

[[sections]]
id = "about"
label = "О нас 2"
text = "Текст 2"
""")
        path = Path(f.name)

    try:
        with pytest.raises(ValueError, match="дублирующийся section.id"):
            load_profile(path)
    finally:
        path.unlink()


def test_profile_rejects_reserved_section_id() -> None:
    """Reserved section IDs are rejected."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write("""
[[sections]]
id = "home"
label = "Дом"
text = "Текст"
""")
        path = Path(f.name)

    try:
        with pytest.raises(ValueError, match="зарезервирован"):
            load_profile(path)
    finally:
        path.unlink()


def test_profile_rejects_unknown_menu_item() -> None:
    """Unknown menu item is rejected."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write("""
[menu]
order = ["unknown_section"]
""")
        path = Path(f.name)

    try:
        with pytest.raises(ValueError, match="неизвестный пункт меню"):
            load_profile(path)
    finally:
        path.unlink()


def test_profile_accepts_known_menu_items() -> None:
    """Known menu items and sections are accepted."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write("""
[menu]
order = ["about", "features", "help"]

[[sections]]
id = "features"
label = "Фичи"
text = "Крутые фичи"
""")
        path = Path(f.name)

    try:
        profile = load_profile(path)
        assert profile.menu_order == ["about", "features", "help"]
        assert len(profile.sections) == 1
        assert profile.sections[0].id == "features"
    finally:
        path.unlink()


def test_settings_from_env_uses_profile_title() -> None:
    """Settings.from_env uses profile title when BOT_TITLE not set."""
    import os
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write('[bot]\ntitle = "Из профиля"\n')
        path = Path(f.name)

    try:
        os.environ["BOT_PROFILE_PATH"] = str(path)
        os.environ["ADMIN_IDS"] = "123"
        os.environ["BOT_TOKEN"] = "test_token"
        # Don't set BOT_TITLE - should use profile
        settings = Settings.from_env()
        assert settings.title == "Из профиля"
        assert settings.profile.title == "Из профиля"
    finally:
        path.unlink()
        os.environ.pop("BOT_PROFILE_PATH", None)
        os.environ.pop("ADMIN_IDS", None)
        os.environ.pop("BOT_TOKEN", None)


def test_settings_from_env_overrides_profile_title() -> None:
    """Explicit BOT_TITLE overrides profile."""
    import os
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write('[bot]\ntitle = "Из профиля"\n')
        path = Path(f.name)

    try:
        os.environ["BOT_PROFILE_PATH"] = str(path)
        os.environ["ADMIN_IDS"] = "123"
        os.environ["BOT_TOKEN"] = "test_token"
        os.environ["BOT_TITLE"] = "Из env"
        settings = Settings.from_env()
        assert settings.title == "Из env"
        # Profile still has its own title
        assert settings.profile.title == "Из профиля"
    finally:
        path.unlink()
        os.environ.pop("BOT_PROFILE_PATH", None)
        os.environ.pop("ADMIN_IDS", None)
        os.environ.pop("BOT_TOKEN", None)
        os.environ.pop("BOT_TITLE", None)


def test_settings_without_profile_uses_defaults() -> None:
    """Settings without profile uses defaults."""
    import os
    os.environ["ADMIN_IDS"] = "123"
    os.environ["BOT_TOKEN"] = "test_token"
    try:
        settings = Settings.from_env()
        assert settings.title == "Мой бот"
        assert isinstance(settings.profile, BotProfile)
    finally:
        os.environ.pop("ADMIN_IDS", None)
        os.environ.pop("BOT_TOKEN", None)