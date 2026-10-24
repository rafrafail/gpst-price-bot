"""Polling/webhook shells around the same dispatcher, with owned task cleanup."""
import argparse
import asyncio
import logging
import re
from contextlib import contextmanager
from pathlib import Path

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.types import BotCommand
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiohttp import web
from dotenv import load_dotenv

from bot_template.app import Application
from bot_template.config import Settings
from bot_template.delivery import DeliveryWorker
from bot_template.storage import Store


class SafeFormatter(logging.Formatter):
    def __init__(self, token: str):
        super().__init__("%(levelname)s %(name)s: %(message)s")
        self.token = token

    def format(self, record):
        result = super().format(record)
        if self.token:
            result = result.replace(self.token, "<bot-token>")
        return re.sub(r"(?:file/)?bot\d+:[A-Za-z0-9_-]+", "bot<redacted>", result)


@contextmanager
def process_lock(database: Path):
    # A deployment runs one update consumer/worker per bot DB. Claims additionally
    # protect accidental concurrent tasks, but startup recovery needs exclusivity.
    import fcntl
    database.parent.mkdir(parents=True, exist_ok=True)
    path = database.with_suffix(database.suffix + ".lock")
    with path.open("a") as handle:
        path.chmod(0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Этот файл базы уже используется другим экземпляром бота.") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def make_bot(settings: Settings) -> Bot:
    session = AiohttpSession(api=TelegramAPIServer.from_base(settings.api_base))
    return Bot(settings.token, session=session)


async def make_web_app(bot, dp, secret: str) -> web.Application:
    app = web.Application(client_max_size=2 * 1024 * 1024)
    # Foreground handling is intentional: no background task may outlive a closed store.
    SimpleRequestHandler(dp, bot, secret_token=secret, handle_in_background=False).register(
        app, path="/telegram"
    )
    return app


async def stop_polling(dp, poll: asyncio.Task[None]) -> None:
    """Stop aiogram through its own signal, then wait for its child consumers.

    ``Dispatcher.start_polling`` creates private ``_polling`` tasks.  Cancelling
    only the wrapper task skips aiogram's cancellation/await loop and can leave
    an update consumer alive in this event loop.  That becomes a Telegram 409
    conflict when a caller starts polling again in the same process.
    """
    if poll.done():
        await poll
        return
    # Let a just-created wrapper acquire aiogram's running lock. This matters
    # when the caller supplied an already-set stop event.
    await asyncio.sleep(0)
    if poll.done():
        await poll
        return
    try:
        await dp.stop_polling()
    except RuntimeError:
        # The wrapper can finish before it acquires the dispatcher lock. There
        # are then no child consumers for aiogram to stop; cancel just that
        # never-started wrapper and retain any real startup exception.
        poll.cancel()
        result = (await asyncio.gather(poll, return_exceptions=True))[0]
        if isinstance(result, asyncio.CancelledError):
            return
        if isinstance(result, BaseException):
            raise result
        return
    await poll


async def serve(settings: Settings, stop: asyncio.Event | None = None) -> None:
    if not settings.token:
        raise ValueError("Для запуска задайте BOT_TOKEN. AI-ключи не нужны.")
    with process_lock(settings.database):
        bot = make_bot(settings)
        store = Store(settings.database)
        stop = stop or asyncio.Event()
        app = Application(bot, store, settings)
        tasks = []
        runner = None
        try:
            await store.initialize()
            from datetime import datetime, timezone
            await store.recover_inflight(datetime.now(timezone.utc))
            dp = app.dispatcher()
            await bot.set_my_commands([
                BotCommand(command="start", description="Главное меню"),
                BotCommand(command="menu", description="Открыть меню"),
                BotCommand(command="help", description="Помощь"),
                BotCommand(command="cancel", description="Отменить текущий ввод"),
            ])
            if settings.broadcasts:
                tasks.append(asyncio.create_task(DeliveryWorker(bot, store).run(stop)))
                tasks.append(asyncio.create_task(app.status_loop(stop)))
            if settings.mode == "webhook":
                web_app = await make_web_app(bot, dp, settings.webhook_secret)
                runner = web.AppRunner(web_app, access_log=None)
                await runner.setup()
                await web.TCPSite(runner, settings.webhook_host, settings.webhook_port).start()
                await bot.set_webhook(settings.webhook_url, secret_token=settings.webhook_secret,
                                      drop_pending_updates=False)
                await stop.wait()
            else:
                await bot.delete_webhook(drop_pending_updates=False)
                poll = asyncio.create_task(dp.start_polling(bot, handle_signals=False,
                                                           close_bot_session=False,
                                                           polling_timeout=10,
                                                           handle_as_tasks=False))
                waiter = asyncio.create_task(stop.wait())
                try:
                    done, _ = await asyncio.wait([poll, waiter], return_when=asyncio.FIRST_COMPLETED)
                    if poll in done:
                        await poll
                    else:
                        await stop_polling(dp, poll)
                finally:
                    if not poll.done():
                        poll.cancel()
                    if not waiter.done():
                        waiter.cancel()
                    await asyncio.gather(poll, waiter, return_exceptions=True)
        finally:
            stop.set()
            if runner:
                await runner.cleanup()
            await app.close()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await store.close()
            await bot.session.close()


def cli() -> None:
    parser = argparse.ArgumentParser(description="Универсальный Telegram bot template v2")
    parser.add_argument("--check", action="store_true", help="Проверить конфигурацию без сети")
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    try:
        settings = Settings.from_env()
        if args.check:
            print("Конфигурация корректна. AI, Redis и PostgreSQL не требуются.")
            print("BOT_TOKEN задан." if settings.token else "BOT_TOKEN не задан: живой запуск пока недоступен.")
            return
        handler = logging.StreamHandler()
        handler.setFormatter(SafeFormatter(settings.token))
        logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
        asyncio.run(serve(settings))
    except KeyboardInterrupt:
        pass
    except ValueError as exc:
        parser.exit(2, str(exc) + "\n")
    except Exception as exc:
        # Do not print transport exceptions: their URLs can include the bot token.
        parser.exit(1, "Запуск не завершён: " + type(exc).__name__ + ". Проверьте безопасный журнал.\n")
