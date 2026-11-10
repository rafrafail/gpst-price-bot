"""Presentation helpers for the GPST price-monitoring bot."""
from __future__ import annotations


def money(value) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f}".replace(",", " ").rstrip("0").rstrip(".")


def format_price_item(item: dict) -> str:
    return (
        f"📦 {item['name']}\n"
        f"Категория: {item.get('category') or '—'}\n"
        f"Регион: {item.get('region') or '—'} · Ед.: {item.get('unit') or '—'}\n\n"
        f"Внутренняя цена: {money(item.get('internal_price'))}\n"
        f"Средняя цена поставщиков: {money(item.get('avg_supplier_price'))}\n"
        f"Отклонение: {item.get('deviation_pct') if item.get('deviation_pct') is not None else '—'}%"
        f" · {item.get('deviation_label', 'нет данных')}"
    )
