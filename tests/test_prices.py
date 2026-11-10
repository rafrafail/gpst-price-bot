from bot_template.prices import format_price_item
from features.prices.service import PriceService


def test_catalog_item_format_includes_market_deviation():
    text = format_price_item({
        "name": "Цемент М500", "category": "Сухие смеси", "region": "Уфа",
        "unit": "т", "internal_price": 6000, "avg_supplier_price": 6500,
        "deviation_pct": 8.3, "deviation_label": "выше рынка",
    })
    assert "Цемент М500" in text
    assert "6 000" in text
    assert "6 500" in text
    assert "8.3%" in text
    assert "выше рынка" in text


def test_summary_aggregates_supplier_price_deviations(tmp_path):
    service = PriceService(tmp_path / "prices.sqlite3")
    service.initialize()
    with service.connect() as db:
        item = db.execute(
            "INSERT INTO catalog(name, category, region, unit, internal_price) VALUES (?, ?, ?, ?, ?)",
            ("Цемент", "Смеси", "Уфа", "т", 110),
        ).lastrowid
        db.execute(
            "INSERT INTO supplier_offers(catalog_id, supplier_name, price) VALUES (?, ?, ?)",
            (item, "Поставщик", 100),
        )
    assert service.summary() == {
        "catalog_count": 1, "supplier_offers_count": 1,
        "items_with_deviation": 1, "avg_deviation_pct": 10.0,
    }
