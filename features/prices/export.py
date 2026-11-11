"""Excel exports for the price bot: current snapshot and 7-day changes.

Two sheets modes:
    export_current(db_path)   — all live offers: name, category, price, unit,
                                city, supplier, url, collected_at
    export_changes(db_path, days=7) — per offer: oldest vs newest price in the
                                window, delta and %, source url
Both return openpyxl Workbook; caller writes to file or sends via Telegram.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEAD_FILL = PatternFill("solid", fgColor="D9EAD3")
HEAD_FONT = Font(bold=True)


def _write_sheet(ws, headers: list[str], rows: list[tuple]) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.alignment = Alignment(horizontal="center")
    for row in rows:
        ws.append(row)
    for idx, header in enumerate(headers, start=1):
        width = max(len(header) + 2, *(len(str(r[idx - 1])) + 2 for r in rows[:500] if r[idx - 1] is not None), 10)
        ws.column_dimensions[get_column_letter(idx)].width = min(width, 60)
    ws.freeze_panes = "A2"


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def export_current(db_path: str | Path, city: str | None = None) -> Workbook:
    conn = _connect(db_path)
    query = """
        SELECT m.name, m.category, m.price, m.unit, m.city, s.name AS supplier,
               m.url, m.collected_at
        FROM market_offers m JOIN suppliers s ON s.id = m.supplier_id
    """
    params: tuple = ()
    if city:
        query += " WHERE m.city = ?"
        params = (city,)
    query += " ORDER BY m.category, m.price"
    rows = [tuple(r) for r in conn.execute(query, params)]
    conn.close()
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Рыночные цены"
    _write_sheet(
        ws,
        ["Товар", "Категория", "Цена, руб", "Ед.", "Город", "Поставщик", "Ссылка", "Собрано"],
        rows,
    )
    return wb


def export_changes(db_path: str | Path, days: int = 7) -> Workbook:
    conn = _connect(db_path)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    query = """
        SELECT m.name, m.category, s.name AS supplier,
               MIN(h.price) AS old_price, MAX(h.price) AS new_price,
               COUNT(*) AS n_points, m.url
        FROM price_history h
        JOIN market_offers m ON m.id = h.offer_id
        JOIN suppliers s ON s.id = m.supplier_id
        WHERE h.collected_at >= ?
        GROUP BY h.offer_id
        HAVING COUNT(DISTINCT h.price) > 1
        ORDER BY ABS(MAX(h.price) - MIN(h.price)) DESC
    """
    rows = []
    for r in conn.execute(query, (since,)):
        old, new = int(r["old_price"]), int(r["new_price"])
        delta = new - old
        pct = round(100 * delta / old, 1) if old else None
        direction = "подорожал" if delta > 0 else "подешевел"
        rows.append((r["name"], r["category"], r["supplier"], old, new, delta, pct, direction, r["url"]))
    conn.close()
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = f"Изменения за {days} дней"
    _write_sheet(
        ws,
        ["Товар", "Категория", "Поставщик", "Было", "Стало", "Δ руб", "Δ %", "Динамика", "Ссылка"],
        rows,
    )
    if not rows:
        ws.append([])
        ws.append(["За период изменений цен не зафиксировано."])
    return wb


def save_workbook(wb: Workbook, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
