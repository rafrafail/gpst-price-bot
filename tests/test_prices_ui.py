import pytest

from tests.helpers import Harness


@pytest.mark.asyncio
async def test_catalog_search_and_detail_show_comparison(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICE_DATABASE_PATH", str(tmp_path / "prices.sqlite3"))
    h = await Harness(tmp_path / "bot.sqlite3").start()
    try:
        with h.app.prices.connect() as db:
            catalog_id = db.execute(
                "INSERT INTO catalog(name,category,region,unit,internal_price) VALUES(?,?,?,?,?)",
                ("Цемент М500", "Смеси", "Уфа", "т", 7260),
            ).lastrowid
            db.execute("INSERT INTO supplier_offers(catalog_id,supplier_name,price,unit) VALUES(?,?,?,?)",
                       (catalog_id, "Поставщик А", 6600, "т"))
        await h.send("/start")
        await h.press("📋 Каталог цен поставщиков")
        await h.press("🔎 Новый поиск")
        await h.send("цемент")
        await h.press("Цемент М500")
        text = h.session.panel.text
        assert "Цемент М500" in text
        assert "выше рынка" in text
        assert "10.0%" in text
    finally:
        await h.close()
