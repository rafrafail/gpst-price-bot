"""Collector tests: parsers on saved HTML fixtures, DB dedup, run lock."""
import sqlite3

import pytest

from features.prices.collector.collect import run_collect
from features.prices.collector.db import CollectorDB, norm_name
from features.prices.collector.parsers import (
    parse_stroylandiya,
    parse_ufacement,
    parse_vseinstrumenti,
)

VI_HTML = """
<div class="product-card"><a title="Цемент ЦЕМ II М-500 Movatex 5 кг" href="/product/x/">x</a>
<span class="price">435 ₽</span></div>
<div class="product-card"><a title="Портландцемент AKKERMAN ЦЕМ I 25 кг" href="/product/y/">y</a>
<span class="price">414 ₽</span></div>
"""

STROY_HTML = """
<a class="fb-product-card__title-inner" href="/catalog/sukhie-smesi/tsement-m500/">
Цемент AKKERMANN М500 50 кг</a><div class="fb-product-card__price">670 руб.</div>
<a class="fb-product-card__title-inner" href="/catalog/sukhie-smesi/pc-150/">
Смесь песчано цементная (ПЦС) М150 25 кг</a><div>193 руб.</div>
"""

UFACEMENT_HTML = """
<li><div class="infoPart"><h2 class="item_name">Цемент М400 по 50 кг (Катавский)</h2></div>
<div class="basketPart"><span>цена 550 руб/меш.</span></div></li>
<li><div class="infoPart"><h2 class="item_name">Цемент М500 по 50 кг</h2></div>
<div class="basketPart"><span>цена 580 руб/меш.</span></div></li>
"""


def test_norm_name_collapses():
    assert norm_name('Цемент  "М-500"  50 кг') == norm_name("цемент м-500 50 кг")


def test_parse_vseinstrumenti_offline():
    offers = parse_vseinstrumenti(VI_HTML)
    assert len(offers) == 2
    assert offers[0]["price"] == 435
    assert offers[0]["city"] == "Уфа"


def test_parse_stroylandiya_offline():
    offers = parse_stroylandiya(STROY_HTML)
    names = [o["name"] for o in offers]
    assert any("AKKERMANN" in n for n in names)
    assert all(o["price"] > 0 for o in offers)


def test_parse_ufacement_offline():
    offers = parse_ufacement(UFACEMENT_HTML)
    assert len(offers) == 2
    assert offers[0]["price"] == 550
    assert offers[0]["unit"] == "меш"


def test_db_dedup_and_history(tmp_path):
    db = CollectorDB(tmp_path / "c.sqlite3")
    sid = db.upsert_supplier("test.ru", "https://test.ru", "Уфа", False)
    offers = [{"name": "Цемент М500", "category": "Цемент", "price": 500,
               "unit": "меш", "city": "Уфа", "url": "https://test.ru/1"}]
    saved, updated = db.save_offers(sid, offers)
    assert saved >= 1 and updated == 0
    saved2, updated2 = db.save_offers(sid, [{**offers[0], "price": 560}])
    assert updated2 == 1
    with sqlite3.connect(tmp_path / "c.sqlite3") as conn:
        history = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
        assert history == 2
    db.close()


def test_run_lock_blocks_second(tmp_path, monkeypatch):
    db = CollectorDB(tmp_path / "lock.sqlite3")
    run_id = db.start_run("test")
    assert db.running_run() is not None
    report = run_collect(tmp_path / "lock.sqlite3")
    assert report["status"] == "locked"
    db.finish_run(run_id, "ok", {})
    db.close()
