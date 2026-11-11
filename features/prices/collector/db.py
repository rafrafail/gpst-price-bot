"""SQLite schema for market offers with history and collect-run journal.

Adds to the existing PriceService database:
    suppliers      — source registry (name, base_url, active, last_status)
    market_offers  — normalized offers with collected_at and source url
    collect_runs   — one row per collector run with per-source stats JSON
    price_history  — (offer_key, price, collected_at) for 7-day dynamics

Offer identity for dedup: (supplier_id, name_normalized). History keeps every
run's price so the Excel "changes" sheet can diff against 7 days ago.
"""
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    base_url TEXT NOT NULL,
    city TEXT NOT NULL DEFAULT 'Уфа',
    active INTEGER NOT NULL DEFAULT 1,
    uses_browser INTEGER NOT NULL DEFAULT 0,
    last_status TEXT NOT NULL DEFAULT 'never',
    last_run_at TEXT
);

CREATE TABLE IF NOT EXISTS market_offers (
    id INTEGER PRIMARY KEY,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    name TEXT NOT NULL,
    name_norm TEXT NOT NULL,
    category TEXT NOT NULL,
    price INTEGER NOT NULL,
    unit TEXT NOT NULL DEFAULT 'шт',
    city TEXT NOT NULL,
    url TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(supplier_id, name_norm)
);
CREATE INDEX IF NOT EXISTS idx_offers_norm ON market_offers(name_norm);
CREATE INDEX IF NOT EXISTS idx_offers_city ON market_offers(city);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY,
    offer_id INTEGER NOT NULL REFERENCES market_offers(id),
    price INTEGER NOT NULL,
    collected_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_offer ON price_history(offer_id, collected_at);

CREATE TABLE IF NOT EXISTS collect_runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    triggered_by TEXT NOT NULL DEFAULT 'timer',
    stats_json TEXT NOT NULL DEFAULT '{}'
);
"""


def norm_name(name: str) -> str:
    """Normalize a product name for dedup/search: lowercase, collapse spaces."""
    text = re.sub(r"[\s ]+", " ", name.strip().lower())
    return re.sub(r"[\"«»„“”]", "", text)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CollectorDB:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- suppliers ---------------------------------------------------
    def upsert_supplier(self, name: str, base_url: str, city: str, uses_browser: bool) -> int:
        cur = self.conn.execute(
            """INSERT INTO suppliers(name, base_url, city, uses_browser)
               VALUES(?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET base_url=excluded.base_url,
                   city=excluded.city, uses_browser=excluded.uses_browser""",
            (name, base_url, city, int(uses_browser)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def set_supplier_status(self, supplier_id: int, status: str) -> None:
        self.conn.execute(
            "UPDATE suppliers SET last_status=?, last_run_at=? WHERE id=?",
            (status, utcnow(), supplier_id),
        )
        self.conn.commit()

    # -- collect runs ------------------------------------------------
    def start_run(self, triggered_by: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO collect_runs(started_at, triggered_by) VALUES(?,?)",
            (utcnow(), triggered_by),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, stats: dict) -> None:
        self.conn.execute(
            "UPDATE collect_runs SET finished_at=?, status=?, stats_json=? WHERE id=?",
            (utcnow(), status, json.dumps(stats, ensure_ascii=False), run_id),
        )
        self.conn.commit()

    def running_run(self) -> sqlite3.Row | None:
        row = self.conn.execute(
            "SELECT id FROM collect_runs WHERE status='running' LIMIT 1"
        ).fetchone()
        return row

    # -- offers ------------------------------------------------------
    def save_offers(self, supplier_id: int, offers: list[dict]) -> tuple[int, int]:
        """Insert/update offers; append to price_history. Returns (saved, updated).

        `saved` counts rows whose price changed (new or different), matching
        the natural "how many prices did we record" reading; `updated` counts
        changed prices on already-known offers.
        """
        now = utcnow()
        saved = updated = 0
        for offer in offers:
            name_norm = norm_name(offer["name"])
            existing = self.conn.execute(
                "SELECT id, price FROM market_offers WHERE supplier_id=? AND name_norm=?",
                (supplier_id, name_norm),
            ).fetchone()
            if existing is None:
                cur = self.conn.execute(
                    """INSERT INTO market_offers(supplier_id, name, name_norm, category,
                                                price, unit, city, url, collected_at, updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (supplier_id, offer["name"], name_norm, offer["category"],
                     int(offer["price"]), offer.get("unit", "шт"), offer["city"],
                     offer["url"], now, now),
                )
                offer_id = int(cur.lastrowid)
                saved += 1
            else:
                offer_id = int(existing["id"])
                if int(existing["price"]) != int(offer["price"]):
                    updated += 1
                    self.conn.execute(
                        """UPDATE market_offers SET price=?, url=?, updated_at=? WHERE id=?""",
                        (int(offer["price"]), offer["url"], now, offer_id),
                    )
            self.conn.execute(
                "INSERT INTO price_history(offer_id, price, collected_at) VALUES(?,?,?)",
                (offer_id, int(offer["price"]), now),
            )
        self.conn.commit()
        return saved, updated

    def summary(self) -> dict:
        suppliers = self.conn.execute(
            "SELECT COUNT(*) AS n FROM suppliers WHERE active=1"
        ).fetchone()["n"]
        offers = self.conn.execute("SELECT COUNT(*) AS n FROM market_offers").fetchone()["n"]
        cities = self.conn.execute(
            "SELECT COUNT(DISTINCT city) AS n FROM market_offers"
        ).fetchone()["n"]
        last = self.conn.execute(
            """SELECT started_at, status FROM collect_runs
               WHERE status != 'running' ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        return {
            "suppliers": suppliers,
            "offers": offers,
            "cities": cities,
            "last_run": dict(last) if last else None,
        }
