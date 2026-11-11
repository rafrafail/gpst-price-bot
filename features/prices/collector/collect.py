"""Collect run: fetch all sources (http-first, browser fallback), save to DB.

Usage:
    python -m features.prices.collector.collect            # all sources
    python -m features.prices.collector.collect --source vi

Lock: a `running` row in collect_runs blocks a second concurrent run.
Report: per-source saved/updated/errors, honest "no answer" marking.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from .db import CollectorDB
from .fetch import BrowserPool, fetch_http
from .parsers import parse_stroylandiya, parse_ufacement, parse_vseinstrumenti
from .sources import SOURCES


def run_collect(db_path: str | Path, only: list[str] | None = None,
                triggered_by: str = "manual") -> dict:
    db = CollectorDB(db_path)
    try:
        if db.running_run():
            return {"status": "locked", "reason": "другой сбор уже выполняется"}
        run_id = db.start_run(triggered_by)
        selected = [s for s in SOURCES if not only or s["key"] in only]
        stats: dict[str, dict] = {}
        # register suppliers
        for source in selected:
            db.upsert_supplier(source["supplier_id"], source["url"],
                               source.get("city", "Уфа"), bool(source.get("browser")))
        selected = [
            {**s, "supplier_pk": db.conn.execute(
                "SELECT id FROM suppliers WHERE name=?", (s["supplier_id"],)
            ).fetchone()["id"]}
            for s in selected
        ]
        browser_needed = [s for s in selected if s.get("browser")]
        pool = BrowserPool() if browser_needed else None
        if pool is not None:
            pool.__enter__()
        try:
            for source in selected:
                key = source["key"]
                stat: dict = {"fetched": 0, "saved": 0, "updated": 0, "error": None}
                try:
                    offers: list[dict] = []
                    pages = source.get("pages") or [(source["key"], source["url"])]
                    last_error = None
                    for page_label, page_url in pages:
                        page = fetch_http(page_url)
                        parsed = []
                        if page.ok and page.html:
                            parsed = source["parse"](page.html)
                        if not parsed and source.get("browser"):
                            time.sleep(2)
                            page = pool.page(page_url, wait_s=source.get("wait_s", 8))
                            if page.ok and page.html:
                                parsed = source["parse"](page.html)
                        for offer in parsed:
                            offer.setdefault("category", page_label)
                        offers.extend(parsed)
                        if not parsed:
                            last_error = page.error or f"no offers on {page_label}"
                        time.sleep(2)  # polite inter-page delay
                    if not offers:
                        stat["error"] = last_error or "site did not answer"
                        db.set_supplier_status(source["supplier_pk"], "no_answer")
                    else:
                        saved, updated = db.save_offers(source["supplier_pk"], offers)
                        stat["fetched"] = len(offers)
                        stat["saved"] = saved
                        stat["updated"] = updated
                        db.set_supplier_status(source["supplier_pk"], "ok")
                except Exception as exc:  # per-source isolation
                    stat["error"] = f"{type(exc).__name__}: {str(exc)[:80]}"
                    db.set_supplier_status(source["supplier_pk"], "error")
                stats[key] = stat
        finally:
            if pool is not None:
                pool.__exit__(None, None, None)
        ok_sources = [k for k, s in stats.items() if not s["error"]]
        status = "ok" if len(ok_sources) == len(stats) else (
            "partial" if ok_sources else "failed")
        db.finish_run(run_id, status, stats)
        summary = db.summary()
        return {"status": status, "stats": stats, "summary": summary}
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect market prices")
    parser.add_argument("--db", default=None, help="SQLite path (default PRICE_DATABASE_PATH)")
    parser.add_argument("--source", action="append", help="limit to source key (repeatable)")
    parser.add_argument("--triggered-by", default="cli")
    args = parser.parse_args()

    db_path = args.db or os.getenv("PRICE_DATABASE_PATH", "data/prices.sqlite3")
    report = run_collect(db_path, args.source, args.triggered_by)
    print(report["status"])
    for key, stat in report.get("stats", {}).items():
        print(f"  {key}: {stat}")
    if report.get("summary"):
        print("summary:", report["summary"])
