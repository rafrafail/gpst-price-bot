"""Actual aiohttp wire + polling entrypoint. No live Telegram or real tokens."""
import asyncio

import pytest
from aiohttp import ClientSession, web

from bot_template.app import Application
from bot_template.config import Settings
from bot_template.runtime import logout_from_cloud, make_bot, make_web_app, process_lock, serve
from bot_template.storage import Store


class BotAPIDouble:
    def __init__(self):
        self.calls = []
        self.updates = []
        self.message_id = 100
        self.fail_get_me = False

    async def handle(self, request):
        method = request.match_info["method"]
        data = dict(await request.post())
        self.calls.append((method, data))
        if method == "getMe":
            if self.fail_get_me:
                return web.json_response({"ok": False, "error_code": 500, "description": "synthetic failure"})
            result = {"id": 123456, "is_bot": True, "first_name": "Template TEST", "username": "template_test_bot"}
        elif method == "getUpdates":
            await asyncio.sleep(0.02)
            result, self.updates = self.updates, []
        elif method in {"setMyCommands", "deleteWebhook", "setWebhook", "answerCallbackQuery", "logOut"}:
            result = True
        else:
            self.message_id += 1
            result = {"message_id": int(data.get("message_id", self.message_id)), "date": 1900000000,
                      "chat": {"id": int(data["chat_id"]), "type": "private"}, "text": data.get("text", "")}
        return web.json_response({"ok": True, "result": result})


@pytest.fixture
async def http_api():
    fake = BotAPIDouble()
    app = web.Application()
    app.router.add_post("/bot{token}/{method}", fake.handle)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    yield fake, url
    await runner.cleanup()


def update(update_id, text):
    return {"update_id": update_id, "message": {"message_id": update_id, "date": 1900000000,
            "chat": {"id": 101, "type": "private"}, "from": {"id": 101, "is_bot": False, "first_name": "TEST"},
            "text": text}}


async def until(predicate):
    async with asyncio.timeout(8):
        while not predicate():
            await asyncio.sleep(0.02)


async def until_async(predicate):
    async with asyncio.timeout(8):
        while not await predicate():
            await asyncio.sleep(0.02)


def polling_consumers():
    return [
        task for task in asyncio.all_tasks()
        if not task.done() and getattr(task.get_coro(), "__qualname__", "") == "Dispatcher._polling"
    ]


async def test_actual_polling_entrypoint_twice_same_database(tmp_path, http_api):
    fake, url = http_api
    settings = Settings(token="123456:" + "T" * 35, admins=frozenset({101}),
                        api_base=url, database=tmp_path / "polling.sqlite3")
    for index in range(2):
        fake.updates.append(update(index + 1, "/start"))
        previous = len([m for m, _ in fake.calls if m in {"sendMessage", "editMessageText"}])
        stop = asyncio.Event()
        task = asyncio.create_task(serve(settings, stop))
        try:
            await until(lambda: len([m for m, _ in fake.calls if m in {"sendMessage", "editMessageText"}]) > previous)
            await until_async(lambda: panel_saved(settings.database, 101))
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=8)
        assert polling_consumers() == []
    assert len([m for m, _ in fake.calls if m == "sendMessage"]) == 1
    assert any(m == "editMessageText" for m, _ in fake.calls)
    assert len([m for m, _ in fake.calls if m == "deleteWebhook"]) == 2
    assert all(data.get("drop_pending_updates") == "false" for m, data in fake.calls if m == "deleteWebhook")
    ui = await Store(settings.database).get_ui(101)
    assert ui["panel_id"] is not None
    # No running consumer still owns the database after either stop.
    with process_lock(settings.database):
        pass


async def test_self_hosted_transport_probes_local_api_before_polling(tmp_path, http_api):
    fake, url = http_api
    settings = Settings(
        token="123456:" + "T" * 35,
        admins=frozenset({101}),
        transport="self_hosted",
        local_api_base=url,
        database=tmp_path / "self-hosted.sqlite3",
    )
    stop = asyncio.Event()
    task = asyncio.create_task(serve(settings, stop))
    try:
        await until(lambda: any(method == "getMe" for method, _ in fake.calls))
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=8)

    methods = [method for method, _ in fake.calls]
    assert methods.index("getMe") < methods.index("setMyCommands")
    assert methods.count("deleteWebhook") == 1
    assert polling_consumers() == []


async def test_self_hosted_transport_fails_before_polling_when_local_api_is_unavailable(tmp_path, http_api):
    fake, url = http_api
    fake.fail_get_me = True
    settings = Settings(
        token="123456:" + "T" * 35,
        transport="self_hosted",
        local_api_base=url,
        database=tmp_path / "self-hosted-unavailable.sqlite3",
    )

    with pytest.raises(ValueError, match="Self-hosted Telegram Bot API недоступен"):
        await serve(settings, asyncio.Event())

    assert [method for method, _ in fake.calls] == ["getMe"]
    assert polling_consumers() == []


async def test_cloud_logout_uses_an_explicit_cloud_session(http_api):
    fake, url = http_api

    await logout_from_cloud("123456:" + "T" * 35, api_base=url)

    assert [method for method, _ in fake.calls] == ["logOut"]


async def panel_saved(database, user_id):
    return (await Store(database).get_ui(user_id))["panel_id"] is not None


async def test_pre_stopped_polling_leaves_no_consumer(tmp_path, http_api):
    _, url = http_api
    settings = Settings(
        token="123456:" + "T" * 35,
        api_base=url,
        database=tmp_path / "pre-stopped.sqlite3",
    )
    stop = asyncio.Event()
    stop.set()

    await asyncio.wait_for(serve(settings, stop), timeout=8)

    assert polling_consumers() == []


async def test_cancelled_polling_service_leaves_no_consumer(tmp_path, http_api):
    fake, url = http_api
    settings = Settings(
        token="123456:" + "T" * 35,
        api_base=url,
        database=tmp_path / "cancelled.sqlite3",
    )
    run = asyncio.create_task(serve(settings, asyncio.Event()))
    try:
        await until(lambda: any(method == "getUpdates" for method, _ in fake.calls))
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(run, timeout=8)
    finally:
        if not run.done():
            run.cancel()
        await asyncio.gather(run, return_exceptions=True)

    assert polling_consumers() == []


async def test_webhook_secret_and_real_dispatcher(tmp_path, http_api):
    fake, url = http_api
    settings = Settings(token="123456:" + "T" * 35, api_base=url, database=tmp_path / "web.sqlite3")
    bot = make_bot(settings)
    store = Store(settings.database)
    await store.initialize()
    application = Application(bot, store, settings)
    server = await make_web_app(bot, application.dispatcher(), "test_secret")
    runner = web.AppRunner(server, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    endpoint = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/telegram"
    try:
        async with ClientSession() as client:
            async with client.post(endpoint, json=update(1, "/start")) as response:
                assert response.status == 401
            assert not fake.calls
            async with client.post(endpoint, json=update(2, "/start"),
                    headers={"X-Telegram-Bot-Api-Secret-Token": "test_secret"}) as response:
                assert response.status == 200
                await response.read()
        assert [m for m, _ in fake.calls] == ["sendMessage"]
        assert "Мой бот" in fake.calls[0][1]["text"]
    finally:
        await runner.cleanup()
        await application.close()
        await bot.session.close()


def test_process_lock_exclusive(tmp_path):
    database = tmp_path / "lock.sqlite3"
    with process_lock(database):
        with pytest.raises(ValueError):
            with process_lock(database):
                pytest.fail("Second consumer acquired the lock")


def test_settings_reject_insecure_api_and_repr_hides_credentials():
    with pytest.raises(ValueError):
        Settings(api_base="http://example.com")
    with pytest.raises(ValueError):
        Settings(api_base="https://user:password@example.com")
    value = Settings(token="synthetic_token", webhook_secret="synthetic_secret")
    assert "synthetic_token" not in repr(value)
    assert "synthetic_secret" not in repr(value)
