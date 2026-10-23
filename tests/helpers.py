"""Real aiogram models/dispatcher, with an explicit recording Bot API double."""
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.types import Message, Update

from bot_template.app import Application
from bot_template.config import Settings
from bot_template.storage import Store


class RecordingSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.counter = 100
        self.error = None

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if self.error and method.__api_method__ in {"sendMessage", "editMessageText"}:
            error, self.error = self.error, None
            raise error
        if method.__api_method__ in {"answerCallbackQuery", "setMyCommands", "deleteWebhook", "setWebhook"}:
            return True
        self.counter += 1
        msg = Message(message_id=getattr(method, "message_id", None) or self.counter,
                      date=datetime.now(timezone.utc), chat={"id": method.chat_id, "type": "private"},
                      text=getattr(method, "text", None) or getattr(method, "caption", None))
        return [msg] if method.__api_method__ == "sendMediaGroup" else msg

    def payloads(self, method):
        return [call for call in self.calls if call.__api_method__ == method]

    @property
    def panel(self):
        return next(c for c in reversed(self.calls)
                    if c.__api_method__ in {"sendMessage", "editMessageText"} and c.reply_markup)


class Harness:
    def __init__(self, path, *, user_id=101, broadcasts=True):
        self.session = RecordingSession()
        self.bot = Bot("123456:" + "T" * 35, session=self.session)
        self.settings = Settings(admins=frozenset({101}), database=path, broadcasts=broadcasts)
        self.store = Store(path)
        self.app = Application(self.bot, self.store, self.settings)
        self.dp = self.app.dispatcher()
        self.uid = user_id
        self.update_id = 0

    async def start(self):
        await self.store.initialize()
        return self

    async def send(self, text=None, **extra):
        self.update_id += 1
        msg = {"message_id": self.update_id, "date": 1900000000,
               "chat": {"id": self.uid, "type": "private"},
               "from": {"id": self.uid, "is_bot": False, "first_name": "Test"}, **extra}
        if text is not None:
            msg["text"] = text
        await self.dp.feed_update(self.bot, Update.model_validate({"update_id": self.update_id, "message": msg}))

    async def click(self, data, *, panel_id=None):
        self.update_id += 1
        ui = await self.store.get_ui(self.uid)
        value = {"update_id": self.update_id, "callback_query": {
            "id": str(self.update_id), "chat_instance": "test",
            "from": {"id": self.uid, "is_bot": False, "first_name": "Test"}, "data": data,
            "message": {"message_id": panel_id or ui["panel_id"], "date": 1900000000,
                        "chat": {"id": self.uid, "type": "private"}},
        }}
        await self.dp.feed_update(self.bot, Update.model_validate(value))

    async def press(self, label):
        for row in self.session.panel.reply_markup.inline_keyboard:
            for button in row:
                if button.text == label:
                    await self.click(button.callback_data)
                    return
        raise AssertionError(f"Button not rendered: {label}")

    async def draft(self, text="Обычный текст. Без Markdown!"):
        await self.send("/start")
        await self.press("📣 Рассылки")
        await self.press("＋ Создать рассылку")
        await self.send(text)
        return (await self.store.list_campaigns(self.uid))[0]

    async def close(self):
        await self.app.close()
        await self.store.close()
        await self.bot.session.close()
