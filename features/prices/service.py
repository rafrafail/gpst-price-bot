"""SQLite-backed price catalog and market offer queries."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class PriceService:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS catalog (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL DEFAULT '',
                    region TEXT NOT NULL DEFAULT '', unit TEXT NOT NULL DEFAULT '',
                    internal_price REAL
                );
                CREATE TABLE IF NOT EXISTS supplier_offers (
                    id INTEGER PRIMARY KEY, catalog_id INTEGER NOT NULL REFERENCES catalog(id),
                    supplier_name TEXT NOT NULL, price REAL NOT NULL, unit TEXT NOT NULL DEFAULT '',
                    region TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '', fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS market_prices (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL DEFAULT '',
                    price REAL NOT NULL, unit TEXT NOT NULL DEFAULT '', city TEXT NOT NULL DEFAULT '',
                    supplier TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '',
                    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS catalog_name_idx ON catalog(name);
                CREATE INDEX IF NOT EXISTS market_filter_idx ON market_prices(city, category, name);
            """)

    def summary(self) -> dict[str, int | float]:
        with self.connect() as db:
            catalog = db.execute("SELECT COUNT(*) FROM catalog").fetchone()[0]
            offers = db.execute("SELECT COUNT(*) FROM supplier_offers").fetchone()[0]
            deviation_rows = db.execute("""SELECT c.id, c.internal_price, AVG(s.price) AS market
                FROM catalog c JOIN supplier_offers s ON s.catalog_id=c.id
                WHERE c.internal_price > 0 GROUP BY c.id""").fetchall()
        deviations = [100 * (row['internal_price'] - row['market']) / row['market'] for row in deviation_rows if row['market']]
        outliers = sum(abs(v) > 5 for v in deviations)
        return {"catalog_count": catalog, "supplier_offers_count": offers,
                "items_with_deviation": outliers,
                "avg_deviation_pct": round(sum(deviations) / len(deviations), 1) if deviations else 0}

    def catalog_search(self, query: str, limit: int = 8, offset: int = 0) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT id,name,category,region,unit,internal_price FROM catalog ORDER BY name").fetchall()
        matches = [dict(row) for row in rows if query.casefold() in row["name"].casefold()]
        return matches[offset:offset + limit]

    def catalog_item(self, item_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("""SELECT c.*, AVG(s.price) avg_supplier_price FROM catalog c
                LEFT JOIN supplier_offers s ON c.id=s.catalog_id WHERE c.id=? GROUP BY c.id""", (item_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        average = item['avg_supplier_price']
        internal = item['internal_price']
        deviation = ((internal - average) / average * 100) if average and internal else None
        item['deviation_pct'] = round(deviation, 1) if deviation is not None else None
        item['deviation_label'] = ("выше рынка" if deviation > 5 else "ниже рынка" if deviation < -5 else "в пределах нормы") if deviation is not None else "нет данных"
        return item

    def market_search(self, query: str = "", city: str = "", category: str = "", limit: int = 8, offset: int = 0) -> list[dict[str, Any]]:
        where, args = [], []
        for field, value in (("name", query), ("city", city), ("category", category)):
            if value:
                where.append(f"{field} LIKE ?" if field == "name" else f"{field} = ?")
                args.append(f"%{value}%" if field == "name" else value)
        sql = "SELECT * FROM market_prices" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY fetched_at DESC LIMIT ? OFFSET ?"
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, (*args, limit, offset)).fetchall()]

    def market_options(self, field: str) -> list[str]:
        if field not in {"city", "category"}:
            raise ValueError("invalid market filter")
        with self.connect() as db:
            return [row[0] for row in db.execute(f"SELECT DISTINCT {field} FROM market_prices WHERE {field}<>'' ORDER BY {field}")]
