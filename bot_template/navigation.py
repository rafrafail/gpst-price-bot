"""One editable navigation panel, with durable back-stack and no draft deletion."""
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


@dataclass(frozen=True)
class View:
    text: str
    rows: list[list[tuple[str, str]]] = field(default_factory=list)

    def keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=data) for label, data in row]
            for row in self.rows
        ])


class Navigator:
    def __init__(self, bot: Bot, store):
        self.bot = bot
        self.store = store

    async def open(self, user_id: int, screen: str, *, remember: bool = True) -> dict:
        ui = await self.store.get_ui(user_id)
        if remember and ui["screen"] != screen:
            ui["history"] = (ui.get("history", []) + [ui["screen"]])[-20:]
        ui.update(screen=screen, input=None)
        await self.store.save_ui(user_id, ui)
        return ui

    async def back(self, user_id: int) -> dict:
        ui = await self.store.get_ui(user_id)
        history = ui.get("history", [])
        ui.update(screen=history.pop() if history else "home", history=history, input=None)
        await self.store.save_ui(user_id, ui)
        return ui

    async def home(self, user_id: int) -> dict:
        ui = await self.store.get_ui(user_id)
        ui.update(screen="home", history=[], input=None)
        await self.store.save_ui(user_id, ui)
        return ui

    async def show(self, user_id: int, view: View) -> int:
        ui = await self.store.get_ui(user_id)
        # The message ID stays constant while panels are edited. Bind actions to
        # the current screen too, rather than accepting old callbacks by ID alone.
        ui["panel_actions"] = [data for row in view.rows for _, data in row]
        await self.store.save_ui(user_id, ui)
        panel = ui.get("panel_id")
        if panel:
            try:
                await self.bot.edit_message_text(
                    chat_id=user_id, message_id=panel, text=view.text,
                    reply_markup=view.keyboard(), parse_mode=None,
                )
                return panel
            except TelegramBadRequest as exc:
                reason = exc.message.lower()
                if "message is not modified" in reason:
                    return panel
                if not any(x in reason for x in (
                    "message to edit not found", "message can't be edited", "message_id_invalid"
                )):
                    raise
        msg = await self.bot.send_message(
            chat_id=user_id, text=view.text, reply_markup=view.keyboard(), parse_mode=None
        )
        ui["panel_id"] = msg.message_id
        await self.store.save_ui(user_id, ui)
        return msg.message_id
