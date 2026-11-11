"""Collect-in-bot flow and Excel sending (added to Application)."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from aiogram.types import FSInputFile

from features.prices.collector.collect import run_collect
from features.prices.export import export_changes, export_current, save_workbook
from features.prices.sync import sync_market_prices

log = logging.getLogger(__name__)


async def _collect_blocking(app):
    """Run the collector in a worker thread so polling stays responsive."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: run_collect(app.collect_db_path, triggered_by="bot_button"),
    )


async def run_collect_and_report(self, uid: int) -> None:
    if self._collect_lock.locked():
        raise ValueError("Сбор уже выполняется — подождите завершения.")
    async with self._collect_lock:
        await self.nav.show(uid, type("V", (), {
            "text": "🔄 Сбор запущен. Это займёт 2–5 минут, не закрывайте бот.",
            "rows": []}))
        try:
            report = await _collect_blocking(self)
        except Exception as exc:
            log.warning("collect failed: %s", type(exc).__name__)
            await self.nav.open(uid, "prices:update")
            await self.render(uid, f"Сбор не выполнен: {str(exc)[:120]}. Прежние данные сохранены.")
            return
        status = report.get("status")
        stats = report.get("stats", {})
        if status == "locked":
            await self.nav.open(uid, "prices:update")
            await self.render(uid, "Другой сбор уже выполняется. Попробуйте позже.")
            return
        try:
            synced = sync_market_prices(self.prices.path, self.collect_db_path)
        except Exception as exc:
            log.warning("sync failed: %s", type(exc).__name__)
            synced = None
        failed = [k for k, s in stats.items() if s.get("error")]
        if status == "failed":
            text = ("❌ Сбор не удался: все источники не ответили. "
                    "Прежние сохранённые данные оставлены без изменений.")
        else:
            total = sum(s.get("fetched", 0) for s in stats.values())
            text = f"✅ Сбор завершён{' с частичными сбоями' if status == 'partial' else ''}."
            text += f"\nСобрано предложений: {total}"
            if synced is not None:
                text += f"\nВ базе рынка: {synced}"
            if failed:
                text += "\n\n⚠️ Часть сайтов не ответила: " + ", ".join(failed)
        await self.nav.open(uid, "prices:update", remember=False)
        await self.render(uid, text)


async def send_price_export(self, uid: int, kind: str) -> None:
    export_dir = self.collect_db_path.parent / "exports"
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    if kind == "current":
        wb = export_current(self.prices.path)
        filename = f"prices_current_{stamp}.xlsx"
    else:
        wb = export_changes(self.prices.path, days=7)
        filename = f"price_changes_7d_{stamp}.xlsx"
    path = save_workbook(wb, export_dir / filename)
    document = FSInputFile(path)
    await self.bot.send_document(uid, document, caption=f"📤 {filename}")
    await self.nav.open(uid, f"prices:export-done:{filename}")
