"""Real Store + real worker; only Telegram transport is replaced."""
from datetime import datetime, timedelta, timezone

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import SendMessage

from bot_template.content import prepare_parts
from bot_template.delivery import DeliveryWorker
from bot_template.models import Content
from bot_template.storage import Store
from tests.helpers import RecordingSession


async def campaign(store, content):
    await store.initialize()
    await store.register_user(101)
    post = await store.create_campaign(101)
    post = await store.save_campaign(post.id, 101, expected_revision=post.revision,
                                     content=content, audience="self")
    return await store.launch_campaign(post.id, 101, expected_revision=post.revision,
                                        now=datetime.now(timezone.utc))


async def test_idle_settles_last_optout_and_restart_unknown(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    post = await campaign(store, Content("Отписка"))
    await store.set_subscription(101, False)
    session = RecordingSession()
    bot = Bot("123456:" + "T" * 35, session=session)
    worker = DeliveryWorker(bot, store, pace_seconds=0)
    try:
        assert not await worker.run_once()
        assert (await store.campaign_counts(post.id))["skipped"] == 1
        assert (await store.get_campaign(post.id)).status == "completed"
        assert not session.calls
        await store.set_subscription(101, True)
        post = await campaign(store, Content("Неизвестный исход"))
        claimed = await store.claim_delivery(datetime.now(timezone.utc))
        assert claimed.campaign_id == post.id
        store = Store(store.path)
        await store.initialize()
        assert await store.recover_inflight(datetime.now(timezone.utc)) == 1
        worker = DeliveryWorker(bot, store, pace_seconds=0)
        assert not await worker.run_once()
        assert (await store.get_campaign(post.id)).status == "attention"
        assert (await store.campaign_counts(post.id))["unknown"] == 1
        assert not session.calls
    finally:
        await bot.session.close()


async def test_repeated_pauses_do_not_exhaust_http_retry_budget(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    post = await campaign(store, Content("x" * 17000))

    class PausingSession(RecordingSession):
        async def make_request(self, bot, method, timeout=None):
            result = await super().make_request(bot, method, timeout)
            if len(self.calls) < len(prepare_parts(post.content)):
                await store.control_campaign(post.id, 101, "pause")
            return result

    session = PausingSession()
    bot = Bot("123456:" + "T" * 35, session=session)
    try:
        for _ in prepare_parts(post.content):
            # New worker represents a graceful restart between acknowledged parts.
            worker = DeliveryWorker(bot, Store(store.path), pace_seconds=0)
            assert await worker.run_once()
            current = await store.get_campaign(post.id)
            if current.status == "paused":
                await store.control_campaign(post.id, 101, "resume")
        assert (await store.get_campaign(post.id)).status == "completed"
        assert "".join(call.text for call in session.calls) == post.content.text
    finally:
        await bot.session.close()


async def test_429_resumes_next_part_without_resending_first(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    post = await campaign(store, Content("x" * 5000))

    class LimitedSession(RecordingSession):
        tried = False
        async def make_request(self, bot, method, timeout=None):
            if len(self.calls) == 1 and not self.tried:
                self.tried = True
                raise TelegramRetryAfter(method=method, message="rate limit", retry_after=2)
            return await super().make_request(bot, method, timeout)

    session = LimitedSession()
    bot = Bot("123456:" + "T" * 35, session=session)
    now = datetime.now(timezone.utc)
    try:
        worker = DeliveryWorker(bot, store, pace_seconds=0)
        assert await worker.run_once(now)
        assert len(session.calls) == 1
        assert not await worker.run_once(now + timedelta(seconds=1))
        assert await worker.run_once(now + timedelta(seconds=3))
        assert "".join(call.text for call in session.calls) == post.content.text
        assert (await store.get_campaign(post.id)).status == "completed"
    finally:
        await bot.session.close()


async def test_exhausted_rate_limit_still_delays_other_recipients(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    await store.initialize()
    for uid in (101, 202):
        await store.register_user(uid)
    post = await store.create_campaign(101)
    post = await store.save_campaign(post.id, 101, expected_revision=post.revision,
                                     content=Content("Проверка лимита"), audience="all")
    now = datetime.now(timezone.utc)
    post = await store.launch_campaign(post.id, 101, expected_revision=post.revision, now=now)

    class LimitedSession(RecordingSession):
        attempts = 0
        async def make_request(self, bot, method, timeout=None):
            if method.chat_id == 101:
                self.attempts += 1
                raise TelegramRetryAfter(method=method, message="rate limit",
                                         retry_after=60 if self.attempts == 3 else 1)
            return await super().make_request(bot, method, timeout)

    session = LimitedSession()
    bot = Bot("123456:" + "T" * 35, session=session)
    try:
        worker = DeliveryWorker(bot, store, pace_seconds=0)
        for seconds in range(3):
            assert await worker.run_once(now + timedelta(seconds=seconds))
        assert (await store.campaign_counts(post.id))["failed"] == 1
        assert not await worker.run_once(now + timedelta(seconds=3))
        assert not session.calls
        assert await worker.run_once(now + timedelta(seconds=62))
        assert [call.chat_id for call in session.calls] == [202]
    finally:
        await bot.session.close()


async def test_network_ambiguity_not_retried_against_real_store(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    post = await campaign(store, Content("Один раз"))
    session = RecordingSession()
    session.error = TelegramNetworkError(method=SendMessage(chat_id=101, text="x"), message="timeout")
    bot = Bot("123456:" + "T" * 35, session=session)
    try:
        worker = DeliveryWorker(bot, store, pace_seconds=0)
        assert await worker.run_once()
        assert (await store.get_campaign(post.id)).status == "attention"
        assert not await worker.run_once()
        assert len(session.calls) == 1
        with pytest.raises(ValueError):
            await store.control_campaign(post.id, 101, "retry")
    finally:
        await bot.session.close()
