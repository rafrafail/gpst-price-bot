"""Tests for wave-2 review fixes: admin overview consistency, list labels, title precedence."""
import json
from datetime import datetime, timezone

import pytest

from bot_template.app import Application
from bot_template.storage import Store

# ── D1: admin overview from one consistent read transaction ─────────────

@pytest.mark.asyncio
async def test_admin_overview_counts_statuses_and_users(tmp_path):
    store = Store(tmp_path / "ov.sqlite3")
    await store.initialize()
    now = datetime.now(timezone.utc).isoformat()
    await store._run(lambda c: (
        c.execute("INSERT INTO users VALUES (1, 'a', 'A', ?, ?, 1, 1)", (now, now)),
        c.execute("INSERT INTO users VALUES (2, 'b', 'B', ?, ?, 1, 0)", (now, now)),
        c.execute("INSERT INTO users VALUES (3, 'c', 'C', ?, ?, 0, 1)", (now, now)),
        c.execute("INSERT INTO campaigns(owner_id, content, status, created_at) "
                  "VALUES (1, '{}', 'scheduled', ?)", (now,)),
        c.execute("INSERT INTO campaigns(owner_id, content, status, created_at) "
                  "VALUES (1, '{}', 'running', ?)", (now,)),
        c.execute("INSERT INTO campaigns(owner_id, content, status, created_at) "
                  "VALUES (1, '{}', 'paused', ?)", (now,)),
        c.execute("INSERT INTO campaigns(owner_id, content, status, created_at) "
                  "VALUES (1, '{}', 'attention', ?)", (now,)),
        c.execute("INSERT INTO campaigns(owner_id, content, status, created_at) "
                  "VALUES (1, '{}', 'partial', ?)", (now,)),
        c.execute("INSERT INTO campaigns(owner_id, content, status, created_at) "
                  "VALUES (1, '{}', 'completed', ?)", (now,)),
        # another admin's campaign must not leak into the overview
        c.execute("INSERT INTO campaigns(owner_id, content, status, created_at) "
                  "VALUES (99, '{}', 'running', ?)", (now,)),
    ), write=True)

    ov = await store.admin_overview(1)
    assert ov["total_users"] == 3
    assert ov["subscribed_users"] == 2
    assert ov["reachable_users"] == 2
    assert ov["scheduled"] == 1
    assert ov["running"] == 1
    assert ov["paused"] == 1
    assert ov["attention"] == 1
    assert ov["history"] == 2  # partial + completed (foreign running excluded)


@pytest.mark.asyncio
async def test_admin_overview_empty_is_truthful_zeroes(tmp_path):
    store = Store(tmp_path / "ov0.sqlite3")
    await store.initialize()
    ov = await store.admin_overview(1)
    assert ov == {"total_users": 0, "subscribed_users": 0, "reachable_users": 0,
                  "scheduled": 0, "running": 0, "paused": 0, "attention": 0, "history": 0}


# ── B3: labels shown in campaign lists ──────────────────────────────────

@pytest.mark.asyncio
async def test_campaign_list_uses_label_when_set(tmp_path):
    store = Store(tmp_path / "lbl.sqlite3")
    await store.initialize()
    now = datetime.now(timezone.utc).isoformat()
    content = json.dumps({"text": "Тело поста", "entities": [], "media": [], "buttons": []})
    await store._run(lambda c: (
        c.execute("INSERT INTO users VALUES (7, 'u', 'U', ?, ?, 1, 1)", (now, now)),
        c.execute("INSERT INTO campaigns(owner_id, content, status, created_at, label) "
                  "VALUES (7, ?, 'draft', ?, 'Пятничный пост')", (content, now)),
        c.execute("INSERT INTO campaigns(owner_id, content, status, created_at) "
                  "VALUES (7, ?, 'draft', ?)", (content, now)),
    ), write=True)

    posts = await store.list_campaigns(7)
    titled = [p for p in posts if p.label]
    untitled = [p for p in posts if not p.label]
    assert len(titled) == 1 and titled[0].label == "Пятничный пост"
    assert len(untitled) == 1  # fallback to text preview happens in UI layer


# ── A1: BOT_TITLE env overrides profile title in home render ────────────

@pytest.mark.asyncio
async def test_home_renders_settings_title_not_raw_profile_title(tmp_path, monkeypatch):
    monkeypatch.setenv("BOT_TITLE", "Бот из ENV")
    monkeypatch.setenv("BROADCAST_ENABLED", "0")
    from bot_template.config import Settings
    settings = Settings.from_env()
    assert settings.title == "Бот из ENV"

    store = Store(tmp_path / "title.sqlite3")
    await store.initialize()
    sent = {}

    class FakeMsg:
        message_id = 555

    class FakeBot:
        async def send_message(self, chat_id, text, reply_markup=None, **kwargs):
            sent["text"] = text
            return FakeMsg()

        async def edit_message_text(self, **kwargs):
            sent["text"] = kwargs["text"]

    from bot_template.navigation import Navigator
    bot = FakeBot()
    app = Application(bot, store, settings)
    app.nav = Navigator(bot, store)
    await app.nav.home(7)
    await app.render(7)
    assert sent["text"].startswith("Бот из ENV")
