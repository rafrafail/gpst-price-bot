"""Targeted tests for review fixes: migrations 1→3, audience bounds, restore safety, DST."""
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from bot_template.maintenance import prepare_restored_for_resume
from bot_template.scheduling import parse_relative_schedule
from bot_template.storage import Store

# ── Migrations: v1 (no label/audience_filter) -> v3 ─────────────────────

def _make_v1_database(path) -> None:
    """Create a synthetic v1-schema database (no label, no audience_filter)."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE users (
            user_id INTEGER PRIMARY KEY CHECK (user_id > 0),
            username TEXT, name TEXT,
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            subscribed INTEGER NOT NULL DEFAULT 1 CHECK (subscribed IN (0, 1)),
            reachable INTEGER NOT NULL DEFAULT 1 CHECK (reachable IN (0, 1))
        );
        CREATE TABLE campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL CHECK (owner_id > 0),
            content TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN (
                'draft', 'scheduled', 'running', 'paused', 'stopped', 'completed',
                'partial', 'failed', 'attention'
            )),
            audience TEXT CHECK (audience IN ('all', 'self')),
            scheduled_at TEXT,
            revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
            created_at TEXT NOT NULL
        );
        CREATE TABLE deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
            user_id INTEGER NOT NULL REFERENCES users(user_id),
            status TEXT NOT NULL DEFAULT 'pending',
            next_part INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            claim_token TEXT UNIQUE,
            retry_at TEXT,
            error TEXT,
            UNIQUE(campaign_id, user_id)
        );
        CREATE TABLE media_groups (
            user_id INTEGER NOT NULL REFERENCES users(user_id),
            group_id TEXT NOT NULL,
            PRIMARY KEY(user_id, group_id)
        );
        CREATE TABLE ui_state (
            user_id INTEGER PRIMARY KEY CHECK (user_id > 0),
            data TEXT NOT NULL
        );
        INSERT INTO users VALUES (42, 'u42', 'User 42', '2026-01-01T00:00:00+00:00',
                                  '2026-01-02T00:00:00+00:00', 1, 1);
        INSERT INTO campaigns(owner_id, content, status, created_at)
            VALUES (42, '{"text":"hi","entities":[],"media":[],"buttons":[]}', 'draft',
                    '2026-01-01T00:00:00+00:00');
        PRAGMA user_version = 1;
    """)
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_migration_v1_to_v3_adds_label_and_filter(tmp_path):
    """Sequential v1→v3 migration: label and audience_filter appear, data survives."""
    path = tmp_path / "v1.sqlite3"
    _make_v1_database(path)
    store = Store(path)
    await store.initialize()

    conn = sqlite3.connect(path)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    cols = {row[1] for row in conn.execute("PRAGMA table_info(campaigns)").fetchall()}
    row = conn.execute("SELECT label, audience_filter FROM campaigns WHERE owner_id = 42").fetchone()
    conn.close()

    assert version == 3
    assert "label" in cols and "audience_filter" in cols
    assert row == ("", None)  # old rows get empty label, no filter


@pytest.mark.asyncio
async def test_migrated_v1_label_save_and_rename_work(tmp_path):
    """Reproduced review failure: renaming on a migrated v1 DB must not fail."""
    path = tmp_path / "v1b.sqlite3"
    _make_v1_database(path)
    store = Store(path)
    await store.initialize()
    campaign = (await store.list_campaigns(42))[0]
    updated = await store.save_campaign(campaign.id, 42, expected_revision=campaign.revision,
                                        label="Моё имя")
    assert updated.label == "Моё имя"


@pytest.mark.asyncio
async def test_reinitialize_is_idempotent(tmp_path):
    path = tmp_path / "idem.sqlite3"
    store = Store(path)
    await store.initialize()
    await store.initialize()  # must not raise
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    conn.close()


# ── Audience filter bounds ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_future_first_seen_is_not_new(tmp_path):
    """Reproduced review failure: a user dated 2099 must not qualify as new."""
    store = Store(tmp_path / "bound.sqlite3")
    await store.initialize()
    now = datetime.now(timezone.utc)
    future = (now + timedelta(days=365 * 70)).isoformat()
    past = (now - timedelta(days=30)).isoformat()
    await store._run(lambda c: (
        c.execute("INSERT INTO users VALUES (1, 'f', 'F', ?, ?, 1, 1)", (future, future)),
        c.execute("INSERT INTO users VALUES (2, 'p', 'P', ?, ?, 1, 1)", (past, past)),
    ), write=True)
    recipients = await store.preview_audience(42, "all", "new_7d")
    assert recipients == []  # both out of window: future beyond now, past beyond cutoff


@pytest.mark.asyncio
async def test_active_7d_includes_recent_excludes_future(tmp_path):
    store = Store(tmp_path / "act.sqlite3")
    await store.initialize()
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=1)).isoformat()
    future = (now + timedelta(days=1)).isoformat()
    await store._run(lambda c: (
        c.execute("INSERT INTO users VALUES (1, 'r', 'R', ?, ?, 1, 1)", (recent, recent)),
        c.execute("INSERT INTO users VALUES (2, 'f', 'F', ?, ?, 1, 1)", (future, future)),
    ), write=True)
    recipients = await store.preview_audience(42, "all", "active_7d")
    assert recipients == [1]


# ── Restore safety ───────────────────────────────────────────────────────

def _seed_restored(path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE users (
            user_id INTEGER PRIMARY KEY, username TEXT, name TEXT,
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            subscribed INTEGER NOT NULL DEFAULT 1, reachable INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE campaigns (
            id INTEGER PRIMARY KEY, owner_id INTEGER, content TEXT NOT NULL,
            status TEXT NOT NULL, audience TEXT, scheduled_at TEXT,
            revision INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE deliveries (
            id INTEGER PRIMARY KEY, campaign_id INTEGER, user_id INTEGER,
            status TEXT NOT NULL DEFAULT 'pending', next_part INTEGER DEFAULT 0,
            attempts INTEGER DEFAULT 0, claim_token TEXT, retry_at TEXT, error TEXT
        );
        CREATE TABLE media_groups (user_id INTEGER, group_id TEXT, PRIMARY KEY(user_id, group_id));
        CREATE TABLE ui_state (user_id INTEGER PRIMARY KEY, data TEXT NOT NULL);
        INSERT INTO users VALUES (7, 'u', 'U', '2026-01-01T00:00:00+00:00',
                                  '2026-01-01T00:00:00+00:00', 1, 1);
        INSERT INTO campaigns VALUES (1, 7, '{}', 'partial', 'all', NULL, 3,
                                      '2026-01-01T00:00:00+00:00');
        INSERT INTO deliveries VALUES (1, 1, 7, 'failed', 0, 1, NULL, NULL, 'boom');
        INSERT INTO ui_state VALUES (7, '{"screen":"campaign:1","confirmation":{"id":1}}');
    """)
    conn.commit()
    conn.close()


def test_prepare_restored_resets_subscriptions_and_terminal_campaign_failures(tmp_path):
    """Reproduced review findings: subscribed=1 and failed rows in terminal campaigns survived."""
    path = tmp_path / "restored.sqlite3"
    _seed_restored(path)
    changes = prepare_restored_for_resume(path)
    conn = sqlite3.connect(path)
    subscribed = conn.execute("SELECT subscribed FROM users WHERE user_id = 7").fetchone()[0]
    delivery = conn.execute("SELECT status FROM deliveries WHERE id = 1").fetchone()[0]
    status = conn.execute("SELECT status FROM campaigns WHERE id = 1").fetchone()[0]
    conn.close()
    assert subscribed == 0                     # opt-in required after restore
    assert delivery == "unknown"               # no retryable rows anywhere
    assert status == "partial"                 # terminal campaign stays terminal (no auto-resume anyway)
    assert changes["subscriptions_reset"] == 1
    assert changes["deliveries_to_unknown"] == 1


def test_prepare_restored_clears_confirmation(tmp_path):
    path = tmp_path / "restored2.sqlite3"
    _seed_restored(path)
    prepare_restored_for_resume(path)
    import json
    conn = sqlite3.connect(path)
    data = json.loads(conn.execute("SELECT data FROM ui_state WHERE user_id = 7").fetchone()[0])
    conn.close()
    assert data.get("confirmation") is None
    assert data.get("panel_id") is None
    assert data.get("input") is None


# ── DST handling in relative schedules ──────────────────────────────────

def test_relative_schedule_rejects_nonexistent_time():
    """Reproduced review failure: Berlin 2026-03-29 02:30 does not exist (spring forward)."""
    # 2026-03-29: Berlin switches 02:00 -> 03:00; 02:30 is a DST gap
    now = datetime(2026, 3, 28, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="местного времени нет|перевод часов"):
        parse_relative_schedule("tomorrow 02:30", "Europe/Berlin", now)


def test_relative_schedule_tomorrow_future_ok():
    now = datetime(2026, 3, 28, 12, 0, tzinfo=timezone.utc)
    result = parse_relative_schedule("tomorrow 10:00", "Europe/Berlin", now)
    dt = datetime.fromisoformat(result)
    assert dt.tzinfo is not None
    assert dt.astimezone(ZoneInfo("Europe/Berlin")).hour == 10
