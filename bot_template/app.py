"""Telegram UI: one panel, persistent drafts, and one broadcast workflow."""
import asyncio
import logging
import re
from dataclasses import replace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Message

from bot_template.config import Settings
from bot_template.content import prepare_parts, validate_content
from bot_template.delivery import send_part
from bot_template.models import Button, Content, Media
from bot_template.navigation import Navigator, View
from bot_template.scheduling import (
    get_schedule_options,
    parse_exact_schedule,
    parse_relative_schedule,
)

log = logging.getLogger(__name__)
BACK = [("← Назад", "nav:back"), ("🏠 Главное меню", "nav:home")]
LABELS = {
    "draft": "Черновики", "scheduled": "Запланированные", "running": "Отправляется",
    "paused": "На паузе", "stopped": "Остановлена", "completed": "Завершена",
    "partial": "Частично отправлена", "failed": "Не отправлена", "attention": "Нужна проверка",
}


def message_content(messages: list[Message]) -> Content:
    """Capture native entities/file IDs; never reconstruct secret download URLs."""
    messages = sorted(messages, key=lambda m: m.message_id)
    media = []
    texts = []
    for message in messages:
        if message.photo:
            media.append(Media("photo", message.photo[-1].file_id))
        elif message.video:
            media.append(Media("video", message.video.file_id))
        elif not message.text:
            raise ValueError("Пришлите текст, фото, видео или альбом из фото/видео.")
        text = message.text or message.caption or ""
        entities = message.entities if message.text else message.caption_entities
        if text:
            texts.append((text, [e.model_dump(exclude_none=True) for e in entities or []]))
    if len(texts) > 1:
        raise ValueError("У альбома должна быть одна общая подпись. Пришлите его заново.")
    text, entities = texts[0] if texts else ("", [])
    return Content(text=text, entities=entities, media=media)


def parse_buttons(text: str) -> list[list[Button]]:
    if text.strip() == "0":
        return []
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        row = []
        for item in line.split(";"):
            label, sep, target = item.partition("|")
            if not sep or not label.strip() or not target.strip():
                raise ValueError("Формат кнопки: Название | https://example.com")
            target = target.strip()
            row.append(Button(label.strip(), action=target[1:]) if target.startswith("@")
                       else Button(label.strip(), url=target))
        rows.append(row)
    if not rows or len(rows) > 5 or any(len(r) > 4 for r in rows):
        raise ValueError("Разрешено до 5 рядов по 4 кнопки.")
    return rows


def parse_schedule(text: str, tz: str, now: datetime) -> str:
    """Deprecated alias kept for tests/back-compat; see scheduling.parse_exact_schedule."""
    return parse_exact_schedule(text, tz, now)


class Application:
    def __init__(self, bot: Bot, store, settings: Settings):
        self.bot, self.store, self.settings = bot, store, settings
        self.nav = Navigator(bot, store)
        self.locks: dict[int, asyncio.Lock] = {}
        self.albums: dict[tuple[int, str], dict] = {}
        self.tasks: set[asyncio.Task] = set()

    def lock(self, user_id: int) -> asyncio.Lock:
        return self.locks.setdefault(user_id, asyncio.Lock())

    def dispatcher(self) -> Dispatcher:
        dp = Dispatcher()
        dp.message.register(self.on_message)
        dp.callback_query.register(self.on_callback)
        return dp

    def admin(self, user_id: int) -> None:
        if user_id not in self.settings.admins:
            raise ValueError("Раздел доступен только администраторам.")

    def require_broadcasts(self, user_id: int) -> None:
        """Admin gate + product gate: broadcasts must be enabled for the bot."""
        self.admin(user_id)
        if not self.settings.broadcasts:
            raise ValueError("Рассылки отключены в конфигурации этого бота.")

    async def campaign(self, user_id: int, post_id: int):
        self.admin(user_id)
        post = await self.store.get_campaign(post_id, owner_id=user_id)
        if post is None:
            raise ValueError("Рассылка не найдена или недоступна.")
        return post

    async def render(self, user_id: int, notice: str = "") -> None:
        ui = await self.store.get_ui(user_id)
        screen = ui["screen"]
        rows = []
        profile = self.settings.profile

        if screen == "home":
            # settings.title already resolves env BOT_TITLE > profile > default (plan A1)
            text = f"{self.settings.title}\n\n{profile.welcome}"
            # Build menu from profile.order
            for item in profile.menu_order:
                if item == "about":
                    # Find the 'about' section
                    sec = next((s for s in profile.sections if s.id == "about"), None)
                    if sec:
                        rows.append([(sec.label, f"open:{sec.id}")])
                elif item == "preferences":
                    rows.append([("⚙️ Уведомления", "open:preferences")])
                elif item == "help":
                    rows.append([("❔ Помощь", "open:help")])
                elif item == "broadcasts" and self.settings.broadcasts and user_id in self.settings.admins:
                    rows.append([("📣 Рассылки", "open:broadcasts")])
                elif item == "admin" and user_id in self.settings.admins:
                    rows.append([("🔧 Администрирование", "open:admin")])
                elif item == "example" and profile.example.enabled:
                    rows.append([("🧩 Пример раздела", "open:example")])
                # Custom sections from profile
                elif item not in {"about", "preferences", "help", "broadcasts", "example"}:
                    sec = next((s for s in profile.sections if s.id == item), None)
                    if sec:
                        rows.append([(sec.label, f"open:{sec.id}")])
            # Support URL if configured
            if profile.support_url:
                rows.append([("💬 Поддержка", profile.support_url)])

        elif screen == "help":
            text = profile.help
        elif screen == "preferences":
            subscribed = await self.store.is_subscribed(user_id)
            text = ("⚙️ Уведомления\n\nМассовые рассылки: "
                    + ("включены" if subscribed else "выключены")
                    + ".\nЭто не отключает ответы на ваши действия.")
            rows = [[("Выключить рассылки" if subscribed else "Включить рассылки",
                      "subscribe:0" if subscribed else "subscribe:1")]]
        elif screen.startswith("example"):
            if not profile.example.enabled:
                await self.nav.home(user_id)
                await self.render(user_id, "Пример раздела отключён. Открыто главное меню.")
                return
            note = ui.get("note", "Пока нет заметки.")
            if screen == "example":
                text = "🧩 Пример независимого раздела\n\nЗаметка сохраняется после перезапуска."
                rows = [[("📝 Моя заметка", "open:example:note")],
                        [("📚 Правила интерфейса", "open:example:rules")]]
            elif screen == "example:note":
                text = "📝 Моя заметка\n\n" + note
                rows = [[("✏️ Изменить", "note:edit")]]
            else:
                text = ("📚 Правила интерфейса\n\nОдин экран — одна задача.\n"
                        "Навигация не уничтожает данные.\n"
                        "Результат живёт отдельно от меню.\n"
                        "Для добавления раздела не нужен модуль рассылок или AI.")
        # Custom profile sections
        elif screen in {s.id for s in profile.sections}:
            sec = next(s for s in profile.sections if s.id == screen)
            text = f"{sec.label}\n\n{sec.text}"
            # No extra actions for static sections
        elif screen == "admin" and user_id in self.settings.admins:
            # Admin overview: one consistent read transaction (plan D1)
            ov = await self.store.admin_overview(user_id)
            text = (f"🔧 Администрирование\n\n"
                    f"👥 Пользователи:\n"
                    f"  Всего: {ov['total_users']}\n"
                    f"  Подписаны: {ov['subscribed_users']}\n"
                    f"  Доступны: {ov['reachable_users']}\n\n"
                    f"📣 Ваши рассылки:\n"
                    f"  Запланировано: {ov['scheduled']}\n"
                    f"  В работе: {ov['running']}\n"
                    f"  На паузе: {ov['paused']}\n"
                    f"  Нуждаются в внимании: {ov['attention']}")
            rows = []
            if ov["scheduled"]:
                rows.append([("📋 Запланированные", "open:list:scheduled:0")])
            if ov["running"] or ov["paused"]:
                rows.append([("⚙️ В работе", "open:list:active:0")])
            if ov["attention"]:
                rows.append([("⚠️ Нуждаются в внимании", "open:list:attention:0")])
            rows.append([("📊 История", "open:list:history:0")])
        elif screen == "broadcasts":
            self.require_broadcasts(user_id)
            text = "📣 Рассылки\n\nСоздайте пост или продолжите сохранённый."
            rows = [[("＋ Создать рассылку", "new")],
                    [("Черновики", "open:list:draft:0"), ("Запланированные", "open:list:scheduled:0")],
                    [("В работе", "open:list:active:0"), ("История", "open:list:history:0")]]
        elif screen.startswith("list:"):
            self.require_broadcasts(user_id)
            _, group, page_text = screen.split(":")
            page = max(0, int(page_text))
            states = {"draft": ["draft"], "scheduled": ["scheduled"],
                      "active": ["running", "paused"],
                      "attention": ["attention"],
                      "history": ["completed", "partial", "failed", "stopped", "attention"]}[group]
            posts = await self.store.list_campaigns(user_id, statuses=states)
            text = f"📣 {dict(draft='Черновики', scheduled='Запланированные', active='В работе', attention='Нуждаются в внимании', history='История')[group]}"
            if not posts:
                text += "\n\nЗдесь пока пусто. Можно создать новую рассылку."
                rows = [[("＋ Создать", "new")]]
            else:
                pages = (len(posts) - 1) // 5 + 1
                page = min(page, pages - 1)
                text += f"\n\nСтраница {page + 1} из {pages}"
                for post in posts[page * 5:page * 5 + 5]:
                    if post.label:
                        title = post.label
                    else:
                        title = post.content.text.replace("\n", " ")[:30] or "Пост без текста"
                    rows.append([(f"#{post.id} · {title}", f"open:campaign:{post.id}")])
                pager = []
                if page:
                    pager.append(("‹ Предыдущая", f"page:{group}:{page - 1}"))
                if page + 1 < pages:
                    pager.append(("Следующая ›", f"page:{group}:{page + 1}"))
                if pager:
                    rows.append(pager)
        elif screen.startswith(("audience:", "when:", "stopask:", "retryask:")):
            mode, post_id = screen.split(":")
            post = await self.campaign(user_id, int(post_id))
            key = f"{post.id}:{post.revision}"
            if mode == "audience":
                text = "👥 Кто получит рассылку?"
                rows = [[("Все подписчики", f"choose:all:{key}")],
                        [("Только я (проверка)", f"choose:self:{key}")],
                        [("Новые за 7 дней", f"choose:new_7d:{key}")],
                        [("Активные за 7 дней", f"choose:active_7d:{key}")],
                        [("Активные за 30 дней", f"choose:active_30d:{key}")]]
            elif mode == "when":
                text = f"🕒 Время отправки · {self.settings.timezone}\n\nВыберите вариант или введите свою дату:"
                options = get_schedule_options(self.settings.timezone, datetime.now(timezone.utc))
                rows = []
                for opt in options:
                    if opt["value"] == "custom":
                        rows.append([(opt["label"], f"schedule:custom:{key}")])
                    elif opt["value"] == "now":
                        rows.append([(opt["label"], f"schedule:now:{key}")])
                    else:
                        # For presets, encode the value to avoid colon conflicts
                        encoded_value = opt["value"].replace(" ", "_").replace(":", "-")
                        post_id, revision = key.split(":")
                        rows.append([(opt["label"], f"schedule:preset:{encoded_value}:{post_id}:{revision}")])
            else:
                action = "stop" if mode == "stopask" else "retry"
                text = ("Остановить оставшуюся отправку? Уже отправленные сообщения не отзываются."
                        if action == "stop" else "Повторить только известные ошибки? Неизвестные исходы не повторяются.")
                rows = [[("Подтвердить", f"control:{action}:{post.id}")]]
        elif screen.startswith(("campaign:", "confirm:")):
            post = await self.campaign(user_id, int(screen.split(":")[1]))
            audience = {None: "не выбраны", "all": "все подписчики", "self": "только я"}[post.audience]
            if post.audience_filter:
                filter_labels = {"new_7d": "новые за 7 дней", "active_7d": "активные за 7 дней", "active_30d": "активные за 30 дней"}
                audience += f" · {filter_labels.get(post.audience_filter, post.audience_filter)}"
            when = (datetime.fromisoformat(post.scheduled_at).astimezone(ZoneInfo(self.settings.timezone))
                    .strftime("%d.%m.%Y %H:%M") if post.scheduled_at else "сейчас")
            
            # Show label if set
            label_line = f"Имя: {post.label}\n" if post.label else ""
            
            text = (f"📣 Рассылка #{post.id} · {LABELS[post.status]}\n\n"
                    f"{label_line}"
                    f"Текст: {'добавлен' if post.content.text else 'нет'}\n"
                    f"Медиа: {len(post.content.media)}\n"
                    f"Кнопок: {sum(len(row) for row in post.content.buttons)}\n"
                    f"Получатели: {audience}\nОтправка: {when} ({self.settings.timezone})")
            key = f"{post.id}:{post.revision}"
            if screen.startswith("confirm:") and post.status == "draft":
                confirmation = ui.get("confirmation", {})
                if confirmation.get("revision") != post.revision or confirmation.get("id") != post.id:
                    await self.nav.open(user_id, f"campaign:{post.id}", remember=False)
                    await self.render(user_id, "Пост изменился. Откройте подтверждение заново.")
                    return
                text += (f"\n\nПолучателей: {len(confirmation['recipients'])}.\n"
                         "Подтвердите запуск именно этой версии поста.")
                rows = [[("✅ Подтвердить запуск", f"launch:{key}")]]
            elif post.status == "draft":
                rows = [[("✏️ Текст", f"edit:text:{key}"), ("🖼 Медиа", f"edit:media:{key}")],
                        [("🔗 Кнопки", f"edit:buttons:{key}"), ("🏷 Имя", f"edit:label:{key}")],
                        [("👥 Получатели", f"audience:{key}"), ("🕒 Когда", f"when:{key}")],
                        [("👁 Предпросмотр", f"preview:{key}"), ("🧪 Отправить себе", f"test:{key}")],
                        [("Продолжить к отправке", f"confirm:{key}")]]
            else:
                counts = await self.store.campaign_counts(post.id)
                text += (f"\n\nВсего: {counts['total']} · Подтверждено: {counts['sent']}\n"
                         f"Ожидают: {counts['pending']} · В работе: {counts['sending']}\n"
                         f"Ошибки: {counts['failed']} · Недоступны: {counts['blocked']}\n"
                         f"Пропущены: {counts['skipped']} · Неизвестный исход: {counts['unknown']}")
                if counts["unknown"]:
                    text += "\nНеизвестные исходы не повторяются автоматически: возможна уже состоявшаяся отправка."
                if post.status in {"running", "scheduled"}:
                    rows.append([("⏸ Пауза", f"control:pause:{post.id}")])
                if post.status == "paused":
                    rows.append([("▶ Продолжить", f"control:resume:{post.id}")])
                if post.status in {"running", "scheduled", "paused"}:
                    rows.append([("⏹ Остановить", f"stopask:{post.id}")])
                if post.status in {"partial", "failed", "completed", "attention"} and counts["failed"]:
                    rows.append([("Повторить известные ошибки", f"retryask:{post.id}")])
                rows.append([("📋 Создать копию", f"copy:{post.id}"), ("Обновить", "refresh")])
        else:
            await self.nav.home(user_id)
            await self.render(user_id, "Экран устарел. Открыто главное меню.")
            return
        if ui.get("input"):
            text = ui["input"]["prompt"] + "\n\nЧерновик сохраняется. /cancel — отменить только ввод."
            rows = [[("Отменить ввод", "cancelinput")]]
        if screen != "home":
            rows.append(BACK)
        if notice:
            text = notice[:300] + "\n\n" + text
        await self.nav.show(user_id, View(text, rows))

    async def begin_input(self, user_id: int, kind: str, prompt: str, **data) -> None:
        ui = await self.store.get_ui(user_id)
        ui["input"] = {"kind": kind, "prompt": prompt, **data}
        await self.store.save_ui(user_id, ui)

    async def on_message(self, message: Message) -> None:
        if message.chat.type != "private" or not message.from_user or message.from_user.is_bot:
            return
        uid = message.from_user.id
        async with self.lock(uid):
            await self.store.register_user(uid, message.from_user.username, message.from_user.full_name)
            if message.media_group_id:
                key = (uid, message.media_group_id)
                if key not in self.albums:
                    if not await self.store.claim_album(uid, message.media_group_id):
                        await self.render(uid, "Этот альбом уже обработан; запоздавшая часть не добавлена. При необходимости пришлите альбом заново целиком.")
                        return
                    self.albums[key] = {"messages": [], "input": (await self.store.get_ui(uid)).get("input")}
                    task = asyncio.create_task(self.flush_album(key))
                    self.tasks.add(task)
                    task.add_done_callback(self.tasks.discard)
                self.albums[key]["messages"].append(message)
                return
            await self.accept_messages(uid, [message])

    async def flush_album(self, key) -> None:
        await asyncio.sleep(0.4)
        async with self.lock(key[0]):
            album = self.albums.pop(key)
            try:
                current = await self.store.get_ui(key[0])
                if current.get("input") != album["input"]:
                    await self.render(key[0], "Альбом относится к предыдущему шагу. Пришлите его заново в нужном редакторе.")
                    return
                await self.accept_messages(key[0], album["messages"])
            except Exception as exc:
                log.warning("Album failed: %s", type(exc).__name__)

    async def accept_messages(self, uid: int, messages: list[Message]) -> None:
        try:
            message = messages[0]
            command = (message.text or "").split(maxsplit=1)[0].split("@")[0] if message.text else ""
            if command in {"/start", "/menu"}:
                await self.nav.home(uid)
            elif command == "/help":
                await self.nav.open(uid, "help")
            elif command in {"/admin"}:
                self.admin(uid)
                await self.nav.open(uid, "admin")
            elif command == "/broadcast":
                self.require_broadcasts(uid)
                await self.nav.open(uid, "broadcasts")
            elif command == "/cancel":
                ui = await self.store.get_ui(uid)
                ui["input"] = None
                await self.store.save_ui(uid, ui)
            elif command.startswith("/"):
                raise ValueError("Неизвестная команда. /menu открывает меню.")
            else:
                ui = await self.store.get_ui(uid)
                entry = ui.get("input")
                if not entry:
                    await self.render(uid, "Выберите действие в меню.")
                    return
                text = message.text or ""
                if entry["kind"] == "note":
                    if not text.strip() or len(text) > 1500:
                        raise ValueError("Пришлите заметку текстом, от 1 до 1500 символов.")
                    ui.update(note=text, input=None)
                    await self.store.save_ui(uid, ui)
                else:
                    post = await self.campaign(uid, entry["id"])
                    kind = entry["kind"]
                    changes = {}
                    if kind == "buttons":
                        content = replace(post.content, buttons=parse_buttons(text))
                    elif kind == "schedule":
                        changes["scheduled_at"] = parse_relative_schedule(text, self.settings.timezone, datetime.now(timezone.utc))
                        content = post.content
                    elif kind == "label":
                        if text.strip() == "0":
                            changes["label"] = ""
                        else:
                            if len(text) > 80:
                                raise ValueError("Имя не длиннее 80 символов.")
                            changes["label"] = text.strip()
                        content = post.content
                    elif kind == "media" and text.strip() == "0":
                        content = replace(post.content, media=[])
                    else:
                        incoming = message_content(messages)
                        if kind == "media":
                            if not incoming.media:
                                raise ValueError("Пришлите фото, видео или альбом. 0 — убрать вложения.")
                            content = replace(post.content, media=incoming.media)
                        elif not post.content.text and not post.content.media:
                            content = replace(incoming, buttons=post.content.buttons)
                        else:
                            if incoming.media:
                                raise ValueError("Здесь меняется только текст. Для вложений выберите «Медиа».")
                            content = replace(post.content, text=incoming.text, entities=incoming.entities)
                    # Incomplete drafts are allowed; complete validation happens before preview/launch.
                    if content.text or content.media:
                        validate_content(content)
                    await self.store.save_campaign(post.id, uid, expected_revision=entry["revision"],
                                                   content=content, **changes)
                    ui["input"] = None
                    await self.store.save_ui(uid, ui)
            await self.render(uid)
        except (ValueError, KeyError) as exc:
            await self.render(uid, f"Не удалось выполнить действие: {str(exc)[:200]}")

    async def on_callback(self, callback: CallbackQuery) -> None:
        if not callback.message or callback.message.chat.type != "private":
            await callback.answer("Откройте бота в личном чате.", show_alert=True)
            return
        uid = callback.from_user.id
        if callback.message.chat.id != uid:
            await callback.answer("Эта кнопка не для вашего чата.", show_alert=True)
            return
        async with self.lock(uid):
            await self.store.register_user(uid, callback.from_user.username, callback.from_user.full_name)
            data = callback.data or ""
            ui = await self.store.get_ui(uid)
            if data.startswith("go:"):
                target = data[3:]
                profile = self.settings.profile
                allowed = {"home", "help", "preferences"}
                if profile.example.enabled:
                    allowed.add("example")
                # Allow profile sections
                allowed.update(s.id for s in profile.sections)
                if target not in allowed:
                    if target == "example" and not profile.example.enabled:
                        await callback.answer("Пример раздела отключён.", show_alert=True)
                        await self.nav.home(uid)
                        await self.render(uid, "Пример раздела отключён. Открыто главное меню.")
                        return
                    await callback.answer("Неизвестное действие.", show_alert=True)
                    return
                await callback.answer()
                if target == "home":
                    await self.nav.home(uid)
                else:
                    await self.nav.open(uid, target)
                await self.render(uid)
                return
            if callback.message.message_id != ui.get("panel_id"):
                await callback.answer("Это старое меню. Используйте /menu.", show_alert=True)
                return
            if data not in ui.get("panel_actions", []):
                await callback.answer("Кнопка устарела. Используйте текущее меню или /menu.", show_alert=True)
                return
            await callback.answer()
            try:
                await self.callback_action(uid, data)
                await self.render(uid)
            except (ValueError, KeyError, IndexError) as exc:
                await self.render(uid, f"Не удалось выполнить действие: {str(exc)[:200]}")

    async def callback_action(self, uid: int, data: str) -> None:
        if data == "nav:home":
            await self.nav.home(uid)
        elif data == "nav:back":
            await self.nav.back(uid)
        elif data in {"cancelinput", "refresh"}:
            ui = await self.store.get_ui(uid)
            ui["input"] = None
            await self.store.save_ui(uid, ui)
        elif data.startswith("open:"):
            screen = data[5:]
            profile = self.settings.profile
            if screen == "broadcasts":
                self.require_broadcasts(uid)
            elif re.fullmatch(r"campaign:\d+", screen):
                await self.campaign(uid, int(screen.split(":")[1]))
            elif re.fullmatch(r"list:(draft|scheduled|active|attention|history):\d{1,6}", screen):
                self.require_broadcasts(uid)
            elif screen == "example":
                if not profile.example.enabled:
                    await self.nav.home(uid)
                    await self.render(uid, "Пример раздела отключён. Открыто главное меню.")
                    return
            else:
                allowed = {"home", "help", "preferences", "example", "example:note", "example:rules"}
                if not profile.example.enabled:
                    allowed.discard("example")
                    allowed.discard("example:note")
                    allowed.discard("example:rules")
                # Allow profile sections
                allowed.update(s.id for s in profile.sections)
                if screen not in allowed:
                    raise ValueError("Неизвестный раздел.")
            await self.nav.open(uid, screen)
        elif data.startswith("page:"):
            self.require_broadcasts(uid)
            if not re.fullmatch(r"page:(draft|scheduled|active|history):\d{1,6}", data):
                raise ValueError("Неизвестная страница.")
            await self.nav.open(uid, "list:" + data[5:], remember=False)
        elif data in {"subscribe:0", "subscribe:1"}:
            await self.store.set_subscription(uid, data == "subscribe:1")
        elif data == "note:edit":
            await self.begin_input(uid, "note", "📝 Пришлите новую заметку (до 1500 символов).")
        elif data == "new":
            self.require_broadcasts(uid)
            ui = await self.store.get_ui(uid)
            if ui["screen"] != "broadcasts" and not ui["screen"].startswith("list:"):
                raise ValueError("Откройте список рассылок для создания нового поста.")
            post = await self.store.create_campaign(uid)
            await self.nav.open(uid, f"campaign:{post.id}")
            await self.begin_input(uid, "text", "📣 Пришлите текст или готовый пост с фото/видео.",
                                   id=post.id, revision=post.revision)
        else:
            self.require_broadcasts(uid)
            pieces = data.split(":")
            action = pieces[0]
            if action == "edit":
                kind, post_id, revision = pieces[1], int(pieces[2]), int(pieces[3])
            elif action in {"control", "choose"}:
                kind, post_id = pieces[1], int(pieces[2])
                revision = int(pieces[3]) if len(pieces) > 3 else None
            elif action == "schedule":
                # schedule:now:post_id:revision OR schedule:custom:post_id:revision OR schedule:preset:encoded_value:post_id:revision
                sub_action = pieces[1]
                if sub_action in {"now", "custom"}:
                    kind = sub_action
                    post_id = int(pieces[2])
                    revision = int(pieces[3]) if len(pieces) > 3 else None
                elif sub_action == "preset" and len(pieces) >= 5:
                    encoded_value = pieces[2]
                    decoded_value = encoded_value.replace("_", " ").replace("-", ":")
                    kind = f"preset:{decoded_value}"
                    post_id = int(pieces[3])
                    revision = int(pieces[4])
                else:
                    raise ValueError("Неизвестный под-действие расписания")
            else:
                post_id = int(pieces[1])
                revision = int(pieces[2]) if len(pieces) > 2 else None
                kind = ""
            post = await self.campaign(uid, post_id)
            if revision is not None and revision != post.revision:
                raise ValueError("Пост изменился. Обновите карточку и повторите действие.")
            if action in {"edit", "audience", "when", "choose", "schedule", "confirm", "launch"} and post.status != "draft":
                raise ValueError("Эта рассылка уже запущена. Для изменений создайте копию.")
            if action == "edit":
                prompts = {"text": "✏️ Пришлите новый текст с обычным форматированием Telegram.",
                           "media": "🖼 Пришлите фото, видео или альбом. 0 — убрать вложения.",
                           "buttons": "🔗 Каждая строка: Название | https://example.com\n"
                           "Кнопки в одном ряду разделите ;\nПереходы: @home, @help, @example, @preferences.\n0 — убрать кнопки.",
                           "label": "🏷 Пришлите внутреннее имя рассылки (до 80 символов). 0 — убрать имя."}
                await self.begin_input(uid, kind, prompts[kind], id=post.id, revision=post.revision)
            elif action == "audience":
                await self.nav.open(uid, f"audience:{post.id}")
            elif action == "choose":
                # kind can be audience (all/self) or audience_filter (new_7d/active_7d/active_30d)
                if kind in ("new_7d", "active_7d", "active_30d"):
                    if post.audience != "all":
                        raise ValueError("Фильтр применяется только к группе «Все подписчики».")
                    await self.store.save_campaign(post.id, uid, expected_revision=post.revision, audience_filter=kind)
                else:
                    # all/self resets any stale filter so confirmation matches launch
                    await self.store.save_campaign(post.id, uid, expected_revision=post.revision,
                                                   audience=kind, audience_filter=None)
                await self.nav.back(uid)
            elif action == "when":
                await self.nav.open(uid, f"when:{post.id}")
            elif action == "schedule":
                if kind == "now":
                    await self.store.save_campaign(post.id, uid, expected_revision=post.revision, clear_schedule=True)
                    await self.nav.back(uid)
                elif kind == "custom":
                    await self.nav.back(uid)
                    await self.begin_input(uid, "schedule", f"🕒 Введите дату: ДД.ММ.ГГГГ ЧЧ:ММ\nЧасовой пояс: {self.settings.timezone}.",
                                           id=post.id, revision=post.revision)
                elif kind.startswith("preset:today ") or kind.startswith("preset:tomorrow "):
                    # Preset option: preset:today 14:00 or preset:tomorrow 14:00
                    scheduled_at = parse_relative_schedule(kind[7:], self.settings.timezone, datetime.now(timezone.utc))
                    await self.store.save_campaign(post.id, uid, expected_revision=post.revision, scheduled_at=scheduled_at)
                    await self.nav.back(uid)
                else:
                    raise ValueError("Неизвестный способ отправки.")
            elif action in {"preview", "test"}:
                validate_content(post.content)
                await self.bot.send_message(uid, "🧪 Тестовая отправка себе" if action == "test"
                                            else "👁 Предпросмотр: ниже пост в том виде, в котором его получат.")
                for part in prepare_parts(post.content):
                    await send_part(self.bot, uid, part)
            elif action == "confirm":
                validate_content(post.content)
                if post.audience is None:
                    raise ValueError("Сначала выберите получателей.")
                recipients = await self.store.preview_audience(uid, post.audience, post.audience_filter)
                if not recipients:
                    raise ValueError("Нет доступных подписчиков. Проверьте настройки уведомлений.")
                await self.nav.open(uid, f"confirm:{post.id}")
                ui = await self.store.get_ui(uid)
                ui["confirmation"] = {"id": post.id, "revision": post.revision, "recipients": recipients}
                await self.store.save_ui(uid, ui)
            elif action == "launch":
                ui = await self.store.get_ui(uid)
                confirm = ui.get("confirmation", {})
                if ui["screen"] != f"confirm:{post.id}" or confirm.get("revision") != post.revision or confirm.get("id") != post.id:
                    raise ValueError("Откройте подтверждение заново.")
                await self.store.launch_campaign(post.id, uid, expected_revision=post.revision,
                                                 now=datetime.now(timezone.utc), expected_recipients=confirm["recipients"])
                await self.nav.open(uid, f"campaign:{post.id}", remember=False)
            elif action in {"stopask", "retryask"}:
                await self.nav.open(uid, f"{action}:{post.id}")
            elif action == "control":
                ui = await self.store.get_ui(uid)
                if kind in {"stop", "retry"} and ui["screen"] != f"{kind}ask:{post.id}":
                    raise ValueError("Подтвердите действие в карточке.")
                await self.store.control_campaign(post.id, uid, kind)
                if kind in {"stop", "retry"}:
                    await self.nav.back(uid)
            elif action == "copy":
                copy = await self.store.duplicate_campaign(post.id, uid)
                await self.nav.open(uid, f"campaign:{copy.id}")
            else:
                raise ValueError("Кнопка устарела. Обновите меню.")

    async def status_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            for uid in self.settings.admins:
                try:
                    async with self.lock(uid):
                        ui = await self.store.get_ui(uid)
                        if ui["screen"].startswith("campaign:") and not ui.get("input"):
                            await self.render(uid)
                except Exception as exc:
                    log.warning("Status refresh failed: %s", type(exc).__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=2)
            except TimeoutError:
                pass

    async def close(self) -> None:
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
