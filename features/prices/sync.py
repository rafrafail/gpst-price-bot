"""Bridge between the collector DB (suppliers/market_offers) and the bot's
PriceService (market_prices view). The bot only READS; the collector writes.

sync_market_prices(price_db_path, collect_db_path):
    refreshes the bot's market_prices table from collector's market_offers so
    existing bot screens (market search, summary) show real data with no
    schema churn in the bot itself.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def sync_market_prices(price_db: str | Path, collect_db: str | Path) -> int:
    """Copy collector offers into the bot's market_prices table. Returns count."""
    src = sqlite3.connect(collect_db)
    src.row_factory = sqlite3.Row
    rows = src.execute("""
        SELECT m.name, m.category, m.price, m.unit, m.city, s.name AS supplier,
               m.url, m.collected_at
        FROM market_offers m JOIN suppliers s ON s.id = m.supplier_id
    """).fetchall()
    src.close()

    dst = sqlite3.connect(price_db)
    try:
        dst.execute("BEGIN")
        dst.execute("DELETE FROM market_prices")
        dst.executemany(
            """INSERT INTO market_prices(name, category, price, unit, city, supplier,
                                         source_url, fetched_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            [(r["name"], r["category"], r["price"], r["unit"], r["city"],
              r["supplier"], r["url"], r["collected_at"]) for r in rows],
        )
        dst.commit()
    except Exception:
        dst.rollback()
        raise
    finally:
        dst.close()
    return len(rows)
