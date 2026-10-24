"""Durable v2 state, with short SQLite transactions off the event loop.

Connections are per operation. BEGIN IMMEDIATE serializes read/modify/write even
across Store instances; claims have unguessable fences, not time-based leases.
An expired/abandoned send is uncertain and can only become ``unknown``.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from .models import Campaign, Content, Delivery

T = TypeVar("T")
CAMPAIGN_STATUSES = frozenset({
    "draft", "scheduled", "running", "paused", "stopped", "completed", "partial",
    "failed", "attention",
})
DELIVERY_STATUSES = ("pending", "sending", "sent", "failed", "blocked", "unknown", "skipped")
FINISH_STATUSES = frozenset(DELIVERY_STATUSES) - {"sending"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY CHECK (user_id > 0),
    username TEXT,
    name TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    subscribed INTEGER NOT NULL DEFAULT 1 CHECK (subscribed IN (0, 1)),
    reachable INTEGER NOT NULL DEFAULT 1 CHECK (reachable IN (0, 1))
);
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL CHECK (owner_id > 0),
    content TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'draft', 'scheduled', 'running', 'paused', 'stopped', 'completed',
        'partial', 'failed', 'attention'
    )),
    audience TEXT CHECK (audience IN ('all', 'self')),
    audience_filter TEXT CHECK (audience_filter IN ('new_7d', 'active_7d', 'active_30d')),
    scheduled_at TEXT,
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    created_at TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS campaigns_owner ON campaigns(owner_id, id);
CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'sending', 'sent', 'failed', 'blocked', 'unknown', 'skipped'
    )),
    next_part INTEGER NOT NULL DEFAULT 0 CHECK (next_part >= 0),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    claim_token TEXT UNIQUE,
    retry_at TEXT,
    error TEXT,
    UNIQUE(campaign_id, user_id)
);
CREATE INDEX IF NOT EXISTS deliveries_pending ON deliveries(status, campaign_id, retry_at, id);
CREATE TABLE IF NOT EXISTS media_groups (
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    group_id TEXT NOT NULL,
    PRIMARY KEY(user_id, group_id)
);
CREATE TABLE IF NOT EXISTS ui_state (
    user_id INTEGER PRIMARY KEY CHECK (user_id > 0),
    data TEXT NOT NULL
);
"""


def _positive(value: int, field: str) -> int:
    if type(value) is not int or not 0 < value <= 2**63 - 1:
        raise ValueError(f"{field} must be a positive SQLite integer")
    return value


def _nonnegative(value: int, field: str) -> int:
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError(f"{field} must be a nonnegative SQLite integer")
    return value


def _utc(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("an aware datetime is required")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _schedule(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("scheduled_at must be an aware ISO datetime string")
    try:
        return _utc(datetime.fromisoformat(value))
    except (ValueError, OverflowError) as exc:
        raise ValueError("scheduled_at must be an aware ISO datetime string") from exc


def _json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("state must be JSON serializable") from exc


def _audience(value: str | None) -> str:
    if not isinstance(value, str) or value not in ("all", "self"):
        raise ValueError("audience must be all or self")
    return value


def _audience_filter(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in ("new_7d", "active_7d", "active_30d"):
        raise ValueError("audience_filter must be new_7d, active_7d, or active_30d")
    return value


def _campaign(row: sqlite3.Row) -> Campaign:
    return Campaign(
        id=row["id"], owner_id=row["owner_id"],
        content=Content.from_dict(json.loads(row["content"])), status=row["status"],
        audience=row["audience"], audience_filter=row["audience_filter"] if "audience_filter" in row.keys() else None,
        scheduled_at=row["scheduled_at"], revision=row["revision"],
        created_at=row["created_at"], label=row["label"] if "label" in row.keys() else "",
    )


class Store:
    """A file-backed SQLite store. Call initialize before other operations.

    :memory: (and URI databases) are deliberately rejected: a new connection
    per transaction would otherwise silently discard the database.
    close is a no-op because no connection survives an operation. Recovery is
    explicitly separate and must only run under the runtime's exclusive lock.
    """

    def __init__(self, path: Path | str):
        if str(path) in ("", ":memory:") or str(path).startswith("file:"):
            raise ValueError("Store requires a persistent SQLite file path")
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _transaction(self, operation: Callable[[sqlite3.Connection], T], write: bool) -> T:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            result = operation(connection)
            connection.commit()
            return result
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def _run(self, operation: Callable[[sqlite3.Connection], T], *, write: bool = False) -> T:
        return await asyncio.to_thread(self._transaction, operation, write)

    async def initialize(self) -> None:
        def initialize() -> None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
            connection = self._connect()
            try:
                existing = connection.execute("PRAGMA table_info(users)").fetchall()
                if existing and not {"user_id", "first_seen", "last_seen", "subscribed", "reachable"}.issubset(
                    {row["name"] for row in existing}
                ):
                    raise ValueError("legacy database detected; use a separate v2 database")
                self.path.chmod(0o600)
                # journal_mode can return SQLITE_BUSY immediately during parallel
                # first opens, even with busy_timeout; retry only this safe bootstrap.
                deadline = time.monotonic() + 5.0
                while True:
                    try:
                        connection.execute("PRAGMA journal_mode = WAL")
                        break
                    except sqlite3.OperationalError as exc:
                        code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
                        if code not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} or time.monotonic() >= deadline:
                            raise
                        time.sleep(0.02)
                connection.execute("BEGIN IMMEDIATE")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1):
                    raise ValueError("unsupported storage schema version")
                # executescript implicitly commits, so execute the fixed DDL
                # statements separately to keep initialization transactional.
                for statement in _SCHEMA.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                connection.execute("PRAGMA user_version = 1")
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

        await asyncio.to_thread(initialize)

    async def close(self) -> None:
        """No persistent connection to close; in-flight operations own theirs."""

    @staticmethod
    def _owned(connection: sqlite3.Connection, campaign_id: int, owner_id: int) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM campaigns WHERE id = ? AND owner_id = ?", (campaign_id, owner_id),
        ).fetchone()
        if row is None:
            raise ValueError("campaign not found or not owned")
        return row

    @staticmethod
    def _eligible(connection: sqlite3.Connection, owner_id: int, audience: str, audience_filter: str | None = None) -> list[int]:
        query = "SELECT user_id FROM users WHERE subscribed = 1 AND reachable = 1"
        params: tuple[int, ...] = ()
        if audience == "self":
            query += " AND user_id = ?"
            params = (owner_id,)
        
        # Apply audience filter
        now_dt = datetime.now(timezone.utc)
        if audience_filter == "new_7d":
            cutoff = _utc(now_dt - timedelta(days=7))
            query += " AND first_seen >= ?"
            params += (cutoff,)
        elif audience_filter == "active_7d":
            cutoff = _utc(now_dt - timedelta(days=7))
            query += " AND last_seen >= ?"
            params += (cutoff,)
        elif audience_filter == "active_30d":
            cutoff = _utc(now_dt - timedelta(days=30))
            query += " AND last_seen >= ?"
            params += (cutoff,)
        
        return [row[0] for row in connection.execute(query + " ORDER BY user_id", params)]

    async def register_user(self, user_id: int, username: str | None = None,
                            name: str | None = None) -> None:
        _positive(user_id, "user_id")
        if any(value is not None and not isinstance(value, str) for value in (username, name)):
            raise ValueError("username and name must be strings or None")
        now = _utc(datetime.now(timezone.utc))
        await self._run(lambda connection: connection.execute(
            """INSERT INTO users(user_id, username, name, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET username = excluded.username,
                   name = excluded.name, last_seen = MAX(users.last_seen, excluded.last_seen),
                   reachable = 1""",
            (user_id, username, name, now, now),
        ).rowcount, write=True)

    async def set_subscription(self, user_id: int, subscribed: bool) -> None:
        _positive(user_id, "user_id")
        if type(subscribed) is not bool:
            raise ValueError("subscribed must be boolean")

        def update(connection: sqlite3.Connection) -> None:
            if connection.execute(
                "UPDATE users SET subscribed = ? WHERE user_id = ?", (int(subscribed), user_id),
            ).rowcount != 1:
                raise ValueError("user not registered")

        await self._run(update, write=True)

    async def is_subscribed(self, user_id: int) -> bool:
        _positive(user_id, "user_id")

        def get(connection: sqlite3.Connection) -> bool:
            row = connection.execute(
                "SELECT subscribed FROM users WHERE user_id = ?", (user_id,),
            ).fetchone()
            return bool(row[0]) if row else False

        return await self._run(get)

    async def preview_audience(self, owner_id: int, audience: str, audience_filter: str | None = None) -> list[int]:
        _positive(owner_id, "owner_id")
        _audience(audience)
        if audience_filter is not None:
            _audience_filter(audience_filter)
        return await self._run(lambda connection: self._eligible(connection, owner_id, audience, audience_filter))

    async def create_campaign(self, owner_id: int) -> Campaign:
        _positive(owner_id, "owner_id")
        now = _utc(datetime.now(timezone.utc))

        def create(connection: sqlite3.Connection) -> Campaign:
            cursor = connection.execute(
                "INSERT INTO campaigns(owner_id, content, status, created_at) VALUES (?, ?, 'draft', ?)",
                (owner_id, _json(Content().to_dict()), now),
            )
            assert cursor.lastrowid is not None
            return _campaign(self._owned(connection, cursor.lastrowid, owner_id))

        return await self._run(create, write=True)

    async def get_campaign(self, campaign_id: int, owner_id: int | None = None) -> Campaign | None:
        _positive(campaign_id, "campaign_id")
        if owner_id is not None:
            _positive(owner_id, "owner_id")

        def get(connection: sqlite3.Connection) -> Campaign | None:
            query = "SELECT * FROM campaigns WHERE id = ?"
            params = (campaign_id,) if owner_id is None else (campaign_id, owner_id)
            if owner_id is not None:
                query += " AND owner_id = ?"
            row = connection.execute(query, params).fetchone()
            return _campaign(row) if row else None

        return await self._run(get)

    async def list_campaigns(self, owner_id: int,
                             statuses: list[str] | None = None) -> list[Campaign]:
        _positive(owner_id, "owner_id")
        if statuses is not None:
            if not isinstance(statuses, list) or any(
                not isinstance(s, str) or s not in CAMPAIGN_STATUSES for s in statuses
            ):
                raise ValueError("invalid campaign statuses")
            statuses = list(statuses)

        def get(connection: sqlite3.Connection) -> list[Campaign]:
            query = "SELECT * FROM campaigns WHERE owner_id = ?"
            params: list[Any] = [owner_id]
            if statuses is not None:
                if not statuses:
                    return []
                query += " AND status IN (" + ",".join("?" for _ in statuses) + ")"
                params.extend(statuses)
            return [_campaign(row) for row in connection.execute(query + " ORDER BY id DESC", params)]

        return await self._run(get)

    async def save_campaign(self, campaign_id: int, owner_id: int, *, expected_revision: int,
                            content: Content | None = None, audience: str | None = None,
                            audience_filter: str | None = None,
                            scheduled_at: str | None = None, clear_schedule: bool = False,
                            label: str | None = None) -> Campaign:
        _positive(campaign_id, "campaign_id")
        _positive(owner_id, "owner_id")
        _nonnegative(expected_revision, "expected_revision")
        if content is not None and not isinstance(content, Content):
            raise ValueError("content must be Content")
        content_json = _json(content.to_dict()) if content is not None else None
        if audience is not None:
            _audience(audience)
        if audience_filter is not None:
            _audience_filter(audience_filter)
        if type(clear_schedule) is not bool or (clear_schedule and scheduled_at is not None):
            raise ValueError("conflicting or invalid schedule arguments")
        if label is not None:
            if not isinstance(label, str):
                raise ValueError("label must be a string")
            if len(label) > 80:
                raise ValueError("label не длиннее 80 символов")
        schedule = _schedule(scheduled_at) if scheduled_at is not None else None

        def save(connection: sqlite3.Connection) -> Campaign:
            row = self._owned(connection, campaign_id, owner_id)
            if row["status"] != "draft" or row["revision"] != expected_revision:
                raise ValueError("campaign is not a current draft")
            connection.execute(
                """UPDATE campaigns SET content = ?, audience = ?, audience_filter = ?, scheduled_at = ?,
                   revision = revision + 1, label = ? WHERE id = ?""",
                (content_json if content_json is not None else row["content"],
                 audience if audience is not None else row["audience"],
                 audience_filter if audience_filter is not None else row["audience_filter"],
                 None if clear_schedule else schedule if schedule is not None else row["scheduled_at"],
                 label if label is not None else row["label"],
                 campaign_id),
            )
            return _campaign(self._owned(connection, campaign_id, owner_id))

        return await self._run(save, write=True)

    async def launch_campaign(self, campaign_id: int, owner_id: int, *, expected_revision: int,
                              now: datetime, expected_recipients: list[int] | None = None) -> Campaign:
        _positive(campaign_id, "campaign_id")
        _positive(owner_id, "owner_id")
        _nonnegative(expected_revision, "expected_revision")
        timestamp = _utc(now)
        if expected_recipients is not None:
            if not isinstance(expected_recipients, list):
                raise ValueError("expected_recipients must be a sorted list")
            expected_recipients = [_positive(i, "recipient") for i in expected_recipients]
            if expected_recipients != sorted(set(expected_recipients)):
                raise ValueError("expected_recipients must be sorted and unique")

        def launch(connection: sqlite3.Connection) -> Campaign:
            row = self._owned(connection, campaign_id, owner_id)
            if row["status"] != "draft" or row["revision"] != expected_revision:
                raise ValueError("campaign is not a current draft")
            campaign = _campaign(row)
            # This is the delivery lane's authoritative validator, not a storage
            # approximation. Never import it at module import time.
            from .content import validate_content

            validate_content(campaign.content)
            if not campaign.content.text.strip() and not campaign.content.media:
                raise ValueError("campaign content is empty")
            audience = _audience(campaign.audience)
            if campaign.scheduled_at is not None and campaign.scheduled_at <= timestamp:
                raise ValueError("scheduled_at must be in the future")
            recipients = self._eligible(connection, owner_id, audience, campaign.audience_filter)
            if expected_recipients is not None and recipients != expected_recipients:
                raise ValueError("audience changed; confirmation required")
            if not recipients:
                raise ValueError("campaign audience is empty")
            connection.executemany(
                "INSERT INTO deliveries(campaign_id, user_id) VALUES (?, ?)",
                [(campaign_id, user_id) for user_id in recipients],
            )
            connection.execute(
                "UPDATE campaigns SET status = ?, revision = revision + 1 WHERE id = ?",
                ("scheduled" if campaign.scheduled_at else "running", campaign_id),
            )
            return _campaign(self._owned(connection, campaign_id, owner_id))

        return await self._run(launch, write=True)

    async def duplicate_campaign(self, campaign_id: int, owner_id: int) -> Campaign:
        _positive(campaign_id, "campaign_id")
        _positive(owner_id, "owner_id")
        now = _utc(datetime.now(timezone.utc))

        def duplicate(connection: sqlite3.Connection) -> Campaign:
            row = self._owned(connection, campaign_id, owner_id)
            original_label = row["label"] if "label" in row.keys() else ""
            original_audience_filter = row["audience_filter"] if "audience_filter" in row.keys() else None
            copy_label = f"{original_label} (копия)" if original_label else "Копия"
            cursor = connection.execute(
                """INSERT INTO campaigns(owner_id, content, status, audience, audience_filter, created_at, label)
                   VALUES (?, ?, 'draft', ?, ?, ?, ?)""", (owner_id, row["content"], row["audience"], original_audience_filter, now, copy_label),
            )
            assert cursor.lastrowid is not None
            return _campaign(self._owned(connection, cursor.lastrowid, owner_id))

        return await self._run(duplicate, write=True)

    async def control_campaign(self, campaign_id: int, owner_id: int, action: str) -> Campaign:
        _positive(campaign_id, "campaign_id")
        _positive(owner_id, "owner_id")
        if action not in ("pause", "resume", "stop", "retry"):
            raise ValueError("invalid campaign action")

        def control(connection: sqlite3.Connection) -> Campaign:
            row = self._owned(connection, campaign_id, owner_id)
            status = row["status"]
            if action == "pause" and status in ("running", "scheduled"):
                target = "paused"
            elif action == "resume" and status == "paused":
                target = "scheduled" if row["scheduled_at"] else "running"
            elif action == "stop" and status in ("running", "paused", "scheduled"):
                target = "stopped"
                # No future claim is allowed; already-sending acknowledgements
                # still have to be recorded honestly.
                connection.execute(
                    "UPDATE deliveries SET status = 'skipped' WHERE campaign_id = ? AND status = 'pending'",
                    (campaign_id,),
                )
            elif action == "retry" and status in ("partial", "failed", "completed", "attention"):
                changed = connection.execute(
                    """UPDATE deliveries SET status = 'pending', attempts = 0, claim_token = NULL,
                       retry_at = NULL, error = NULL WHERE campaign_id = ? AND status = 'failed'""",
                    (campaign_id,),
                ).rowcount
                if not changed:
                    raise ValueError("no definitively failed deliveries to retry")
                target = "running"
            else:
                raise ValueError("invalid campaign transition")
            connection.execute(
                "UPDATE campaigns SET status = ?, revision = revision + 1 WHERE id = ?",
                (target, campaign_id),
            )
            return _campaign(self._owned(connection, campaign_id, owner_id))

        return await self._run(control, write=True)

    async def claim_delivery(self, now: datetime) -> Delivery | None:
        timestamp = _utc(now)

        def claim(connection: sqlite3.Connection) -> Delivery | None:
            connection.execute(
                """UPDATE campaigns SET status = 'running', revision = revision + 1
                   WHERE status = 'scheduled' AND scheduled_at <= ?""", (timestamp,),
            )
            connection.execute(
                """UPDATE deliveries SET status = 'skipped', error = 'recipient unavailable'
                   WHERE status = 'pending' AND (retry_at IS NULL OR retry_at <= ?)
                   AND campaign_id IN (SELECT id FROM campaigns WHERE status = 'running')
                   AND user_id IN (SELECT user_id FROM users WHERE subscribed = 0 OR reachable = 0)""",
                (timestamp,),
            )
            row = connection.execute(
                """SELECT d.* FROM deliveries d JOIN campaigns c ON c.id = d.campaign_id
                   WHERE d.status = 'pending' AND c.status = 'running'
                   AND (d.retry_at IS NULL OR d.retry_at <= ?) ORDER BY c.id, d.id LIMIT 1""",
                (timestamp,),
            ).fetchone()
            if row is None:
                return None
            token = uuid4().hex
            connection.execute(
                "UPDATE deliveries SET status = 'sending', attempts = attempts + 1, claim_token = ? WHERE id = ?",
                (token, row["id"]),
            )
            return Delivery(
                id=row["id"], campaign_id=row["campaign_id"], user_id=row["user_id"],
                next_part=row["next_part"], attempts=row["attempts"] + 1, claim_token=token,
            )

        return await self._run(claim, write=True)

    @staticmethod
    def _fence(delivery: Delivery) -> tuple[int, int, int, str, int]:
        if not isinstance(delivery, Delivery):
            raise ValueError("delivery must be Delivery")
        _positive(delivery.id, "delivery.id")
        _positive(delivery.campaign_id, "delivery.campaign_id")
        _positive(delivery.user_id, "delivery.user_id")
        _positive(delivery.attempts, "delivery.attempts")
        if not isinstance(delivery.claim_token, str) or not delivery.claim_token:
            raise ValueError("delivery must have a claim token")
        return (delivery.id, delivery.campaign_id, delivery.user_id,
                delivery.claim_token, delivery.attempts)

    async def advance_delivery(self, delivery: Delivery, next_part: int) -> bool:
        _nonnegative(next_part, "next_part")
        fence = self._fence(delivery)
        return await self._run(lambda connection: connection.execute(
            """UPDATE deliveries SET next_part = ? WHERE id = ? AND campaign_id = ? AND user_id = ?
               AND claim_token = ? AND attempts = ? AND status = 'sending' AND next_part <= ?""",
            (next_part, *fence, next_part),
        ).rowcount == 1, write=True)

    async def finish_delivery(self, delivery: Delivery, status: str, *, error: str | None = None,
                              retry_at: datetime | None = None) -> bool:
        fence = self._fence(delivery)
        if not isinstance(status, str) or status not in FINISH_STATUSES:
            raise ValueError("invalid delivery finish status")
        if error is not None and not isinstance(error, str):
            raise ValueError("error must be a string")
        if retry_at is not None and status != "pending":
            raise ValueError("only a known-safe pending retry can have retry_at")
        timestamp = _utc(retry_at) if retry_at is not None else None

        def finish(connection: sqlite3.Connection) -> bool:
            changed = connection.execute(
                """UPDATE deliveries SET status = ?, error = ?, retry_at = ?, claim_token = NULL,
                   attempts = attempts - ?
                   WHERE id = ? AND campaign_id = ? AND user_id = ? AND claim_token = ?
                   AND attempts = ? AND status = 'sending'""",
                (status, error, timestamp, int(status == "pending" and error is None), *fence),
            ).rowcount == 1
            if changed and status == "blocked":
                connection.execute("UPDATE users SET reachable = 0 WHERE user_id = ?", (delivery.user_id,))
            return changed

        return await self._run(finish, write=True)

    async def recover_inflight(self, now: datetime) -> int:
        _utc(now)
        return await self._run(lambda connection: connection.execute(
            """UPDATE deliveries SET status = 'unknown', claim_token = NULL, retry_at = NULL,
               error = 'interrupted send; outcome unknown' WHERE status = 'sending'""",
        ).rowcount, write=True)

    async def settle_campaigns(self, now: datetime) -> None:
        _utc(now)

        def settle(connection: sqlite3.Connection) -> None:
            rows = connection.execute(
                """SELECT c.id, SUM(d.status = 'unknown') AS uncertain,
                   SUM(d.status = 'sent') AS sent,
                   SUM(d.status IN ('failed', 'blocked')) AS failures
                   FROM campaigns c LEFT JOIN deliveries d ON d.campaign_id = c.id
                   WHERE c.status IN ('running', 'scheduled') GROUP BY c.id
                   HAVING SUM(CASE WHEN d.status IN ('pending', 'sending') THEN 1 ELSE 0 END) = 0""",
            ).fetchall()
            for row in rows:
                if row["uncertain"]:
                    target = "attention"
                elif row["failures"]:
                    target = "partial" if row["sent"] else "failed"
                else:
                    target = "completed"
                connection.execute(
                    "UPDATE campaigns SET status = ?, revision = revision + 1 WHERE id = ?",
                    (target, row["id"]),
                )

        await self._run(settle, write=True)

    async def campaign_counts(self, campaign_id: int) -> dict[str, int]:
        _positive(campaign_id, "campaign_id")

        def count(connection: sqlite3.Connection) -> dict[str, int]:
            counts = dict.fromkeys(DELIVERY_STATUSES, 0)
            for row in connection.execute(
                "SELECT status, COUNT(*) FROM deliveries WHERE campaign_id = ? GROUP BY status",
                (campaign_id,),
            ):
                counts[row[0]] = row[1]
            return {"total": sum(counts.values()), **counts}

        return await self._run(count)

    async def count_users(self) -> int:
        return await self._run(lambda connection: connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    async def count_subscribed_users(self) -> int:
        return await self._run(lambda connection: connection.execute("SELECT COUNT(*) FROM users WHERE subscribed = 1").fetchone()[0])

    async def count_reachable_users(self) -> int:
        return await self._run(lambda connection: connection.execute("SELECT COUNT(*) FROM users WHERE reachable = 1").fetchone()[0])

    async def claim_album(self, user_id: int, group_id: str) -> bool:
        """Durable tombstone: a late/replayed group may never bind to a new input."""
        _positive(user_id, "user_id")
        if not isinstance(group_id, str) or not group_id:
            raise ValueError("media group ID is required")
        return await self._run(lambda connection: connection.execute(
            "INSERT INTO media_groups(user_id, group_id) VALUES(?, ?) ON CONFLICT DO NOTHING",
            (user_id, group_id),
        ).rowcount == 1, write=True)

    async def get_ui(self, user_id: int) -> dict:
        _positive(user_id, "user_id")

        def get(connection: sqlite3.Connection) -> dict:
            data = {"screen": "home", "history": [], "input": None, "panel_id": None}
            row = connection.execute("SELECT data FROM ui_state WHERE user_id = ?", (user_id,)).fetchone()
            if row:
                data.update(json.loads(row[0]))
            return data

        return await self._run(get)

    async def save_ui(self, user_id: int, data: dict) -> None:
        _positive(user_id, "user_id")
        if not isinstance(data, dict):
            raise ValueError("UI state must be a dict")
        serialized = _json(data)
        await self._run(lambda connection: connection.execute(
            "INSERT INTO ui_state(user_id, data) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET data = excluded.data",
            (user_id, serialized),
        ).rowcount, write=True)
