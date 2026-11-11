#!/usr/bin/env python3
"""Absorb a collected DB shipped to /tmp/gpst_collected.sqlite3 on prod:
merge collector tables into the prod collector DB and re-sync bot market view.
Safe to re-run; never deletes prod-collected rows.
"""
import shutil
import sqlite3
import sys
from pathlib import Path

PROJ = Path("/home/user/projects/gpst_price_bot")
COLLECT_DB = PROJ / "data" / "prices.sqlite3"
INCOMING = Path("/tmp/gpst_collected.sqlite3")

if not INCOMING.exists():
    print("nothing to absorb")
    sys.exit(0)

if not COLLECT_DB.exists():
    COLLECT_DB.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(INCOMING, COLLECT_DB)
    print("first copy: installed as-is")
else:
    src = sqlite3.connect(INCOMING)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(COLLECT_DB)
    # merge suppliers
    for row in src.execute("SELECT * FROM suppliers"):
        dst.execute(
            """INSERT INTO suppliers(name, base_url, city, active, uses_browser,
                                     last_status, last_run_at)
               VALUES(?,?,?,1,?,?,?)
               ON CONFLICT(name) DO UPDATE SET base_url=excluded.base_url,
                   last_status=excluded.last_status, last_run_at=excluded.last_run_at""",
            (row["name"], row["base_url"], row["city"], row["uses_browser"],
             row["last_status"], row["last_run_at"]),
        )
    supplier_map = {}
    for row in src.execute("SELECT id, name FROM suppliers"):
        local = dst.execute("SELECT id FROM suppliers WHERE name=?", (row["name"],)).fetchone()
        supplier_map[row["id"]] = local[0] if local else None
    # merge offers + history
    offers_new = 0
    for row in src.execute("SELECT * FROM market_offers"):
        sid = supplier_map.get(row["supplier_id"])
        if sid is None:
            continue
        cur = dst.execute(
            """INSERT INTO market_offers(supplier_id, name, name_norm, category, price,
                                         unit, city, url, collected_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(supplier_id, name_norm) DO UPDATE SET
                   price=excluded.price, url=excluded.url, updated_at=excluded.updated_at""",
            (sid, row["name"], row["name_norm"], row["category"], row["price"],
             row["unit"], row["city"], row["url"], row["collected_at"], row["updated_at"]),
        )
        if cur.lastrowid is not None:
            offers_new += 1
        offer_id = dst.execute(
            "SELECT id FROM market_offers WHERE supplier_id=? AND name_norm=?",
            (sid, row["name_norm"]),
        ).fetchone()[0]
        dst.execute(
            """INSERT INTO price_history(offer_id, price, collected_at)
               SELECT ?, ?, ?
               WHERE NOT EXISTS (SELECT 1 FROM price_history WHERE offer_id=? AND collected_at=?)""",
            (offer_id, row["price"], row["collected_at"], offer_id, row["collected_at"]),
        )
    # merge collect_runs journal (skip 'running' leftovers)
    for row in src.execute("SELECT * FROM collect_runs WHERE status != 'running'"):
        dst.execute(
            """INSERT INTO collect_runs(started_at, finished_at, status, triggered_by, stats_json)
               SELECT ?,?,?,?,?
               WHERE NOT EXISTS (SELECT 1 FROM collect_runs WHERE started_at=? AND status=?)""",
            (row["started_at"], row["finished_at"], row["status"],
             row["triggered_by"], row["stats_json"], row["started_at"], row["status"]),
        )
    dst.commit()
    dst.close()
    src.close()
    print(f"merged: {offers_new} new offers")

INCOMING.unlink(missing_ok=True)

# refresh the bot's market_prices view from merged collector data
from features.prices.sync import sync_market_prices  # noqa: E402

n = sync_market_prices(COLLECT_DB, COLLECT_DB)  # same file: bot tables live there too
print("market_prices refreshed:", n)
