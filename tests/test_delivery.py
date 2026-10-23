"""Stateful contract doubles; real aiogram exceptions and Bot API serialization."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
    TelegramUnauthorizedError,
)
from aiogram.methods import SendMessage
from aiogram.types import Message

from bot_template.content import prepare_parts
from bot_template.delivery import DeliveryWorker, send_part
from bot_template.models import Campaign, Content, Delivery, Media

NOW = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
REQUEST = SendMessage(chat_id=42, text="placeholder")
# Synthetic secret-like data is deliberately passed through real exceptions. It
# must never be copied into stored error evidence or logging records.
SENSITIVE = "sensitive-body https://api.telegram.org/bot123456:synthetic_secret/sendMessage"


class StoreDouble:
    """Fenced, stateful implementation of the delivery subset of the contract."""

    def __init__(self, content=None):
        self.campaign = Campaign(
            1, 7, content or Content("hello"), "running", "all", None, 1, NOW.isoformat()
        )
        self.row = Delivery(11, 1, 42, 0, 0, "")
        self.status = "pending"
        self.subscribed = True
        self.retry_at = None
        self.error = None
        self.advances = []
        self.finishes = []
        self.claims = 0
        self.settles = 0
        self.reads = []
        self.fail_advance = None
        self.advance_hook = None

    async def claim_delivery(self, now):
        self.claims += 1
        if (
            self.status != "pending"
            or self.campaign.status != "running"
            or (self.retry_at is not None and now < self.retry_at)
        ):
            return None
        self.status = "sending"
        self.row = replace(
            self.row, attempts=self.row.attempts + 1, claim_token=f"claim-{self.claims}"
        )
        return self.row

    async def get_campaign(self, campaign_id, owner_id=None):
        assert campaign_id == 1
        assert owner_id is None  # the worker is not an owner-scoped UI request
        self.reads.append("campaign")
        return self.campaign

    async def is_subscribed(self, user_id):
        assert user_id == 42
        self.reads.append("subscription")
        return self.subscribed

    async def advance_delivery(self, delivery, next_part):
        self.advances.append(next_part)
        if self.fail_advance == "raise":
            raise RuntimeError(SENSITIVE)
        if self.fail_advance == "false":
            return False
        if self.fail_advance == "after_commit":
            self.row = replace(self.row, next_part=next_part)
            raise RuntimeError(SENSITIVE)
        assert delivery.claim_token == self.row.claim_token
        assert self.status == "sending"
        self.row = replace(self.row, next_part=next_part)
        if self.advance_hook:
            self.advance_hook(next_part)
        return True

    async def finish_delivery(self, delivery, status, *, error=None, retry_at=None):
        assert self.status == "sending"
        assert delivery.claim_token == self.row.claim_token
        self.finishes.append((status, error, retry_at))
        self.status, self.error, self.retry_at = status, error, retry_at
        return True

    async def settle_campaigns(self, now):
        assert now.tzinfo is not None
        self.settles += 1

    async def recover_inflight(self, now):
        raise AssertionError("Recovery belongs only to runtime startup")


class BotDouble:
    def __init__(self, outcomes=(), hook=None):
        self.calls = []
        self.outcomes = list(outcomes)
        self.hook = hook

    async def _send(self, method, kwargs):
        self.calls.append((method, kwargs))
        if self.hook:
            await self.hook()
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
        return object()

    async def send_message(self, **kwargs):
        return await self._send("send_message", kwargs)

    async def send_photo(self, **kwargs):
        return await self._send("send_photo", kwargs)

    async def send_video(self, **kwargs):
        return await self._send("send_video", kwargs)

    async def send_media_group(self, **kwargs):
        return await self._send("send_media_group", kwargs)


async def test_run_once_claims_one_and_checkpoints_each_part_without_duplicates():
    store = StoreDouble(Content("x" * 8001, media=[Media("photo", "file")]))
    bot = BotDouble()
    worker = DeliveryWorker(bot, store, pace_seconds=0)
    assert await worker.run_once(NOW) is True
    assert store.row.next_part == 4
    assert store.advances == [1, 2, 3, 4]
    assert store.status == "sent"
    assert store.settles == 1
    assert all(kwargs["chat_id"] == 42 for _, kwargs in bot.calls)
    assert await worker.run_once(NOW) is False
    assert len(bot.calls) == 4
    assert len(store.reads) >= 8


async def test_worker_resumes_only_next_part():
    store = StoreDouble(Content("x" * 8001))
    store.row = replace(store.row, next_part=1)
    bot = BotDouble()
    assert await DeliveryWorker(bot, store, pace_seconds=0).run_once(NOW)
    assert [len(kwargs["text"]) for _, kwargs in bot.calls] == [4000, 1]
    assert store.advances == [2, 3]
    assert store.status == "sent"


@pytest.mark.parametrize("status,expected", [("paused", "pending"), ("stopped", "skipped")])
async def test_pause_and_stop_during_http_ack_part_but_do_not_send_next(status, expected):
    store = StoreDouble(Content("x" * 8001))

    async def change_status():
        store.campaign = replace(store.campaign, status=status)

    bot = BotDouble(hook=change_status)
    worker = DeliveryWorker(bot, store, pace_seconds=0)
    assert await worker.run_once(NOW)
    assert len(bot.calls) == 1
    assert store.row.next_part == 1
    assert store.status == expected
    assert await worker.run_once(NOW) is False
    if status == "paused":
        store.campaign = replace(store.campaign, status="running")
        bot.hook = None
        assert await worker.run_once(NOW)
        assert store.status == "sent"
        assert [len(k["text"]) for _, k in bot.calls] == [4000, 4000, 1]


async def test_optout_after_completed_part_prevents_the_next_part():
    store = StoreDouble(Content("x" * 8001))
    store.advance_hook = lambda _: setattr(store, "subscribed", False)
    bot = BotDouble()
    assert await DeliveryWorker(bot, store, pace_seconds=0).run_once(NOW)
    assert len(bot.calls) == 1
    assert store.row.next_part == 1
    assert store.status == "skipped"


@pytest.mark.parametrize(
    "paused,optout,expected", [(True, False, "pending"), (False, True, "skipped")]
)
async def test_policy_is_rechecked_immediately_after_pacing(monkeypatch, paused, optout, expected):
    store = StoreDouble(Content("x" * 4001))
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)
        if paused:
            store.campaign = replace(store.campaign, status="paused")
        if optout:
            store.subscribed = False

    monkeypatch.setattr("bot_template.delivery.asyncio.sleep", sleep)
    bot = BotDouble()
    assert await DeliveryWorker(bot, store, pace_seconds=10).run_once(NOW)
    assert sleeps and 0 < sleeps[0] <= 10
    assert len(bot.calls) == 1
    assert store.status == expected


@pytest.mark.parametrize("fail", ["raise", "false", "after_commit"])
async def test_checkpoint_failure_never_sends_another_part(fail, caplog):
    store = StoreDouble(Content("x" * 8001))
    store.fail_advance = fail
    bot = BotDouble()
    assert await DeliveryWorker(bot, store, pace_seconds=0).run_once(NOW)
    assert len(bot.calls) == 1
    assert store.status == "unknown"
    assert store.row.next_part == (1 if fail == "after_commit" else 0)
    assert SENSITIVE not in (store.error or "") + caplog.text
    assert not await DeliveryWorker(bot, store, pace_seconds=0).run_once(NOW)
    # Idle cycles reconcile opted-out/terminal campaigns too, without resending.
    assert store.settles == 2


async def test_same_chat_has_separate_pacing(monkeypatch):
    from unittest.mock import AsyncMock
    store = StoreDouble(Content("x" * 4001))
    bot = BotDouble()
    sleep = AsyncMock()
    monkeypatch.setattr("bot_template.delivery.asyncio.sleep", sleep)
    assert await DeliveryWorker(bot, store).run_once(NOW)
    assert sleep.await_count == 1
    assert sleep.await_args is not None
    assert 0.8 < sleep.await_args.args[0] <= 1.05


async def test_rate_limit_retries_only_the_unsent_part_and_obeys_retry_at():
    store = StoreDouble(Content("x" * 4001))
    bot = BotDouble([None, TelegramRetryAfter(REQUEST, SENSITIVE, retry_after=20)])
    worker = DeliveryWorker(bot, store, pace_seconds=0)
    assert await worker.run_once(NOW)
    assert store.row.next_part == 1
    assert store.status == "pending"
    assert store.retry_at == NOW + timedelta(seconds=20)
    assert not await worker.run_once(NOW + timedelta(seconds=19))
    assert await worker.run_once(NOW + timedelta(seconds=20))
    assert store.status == "sent"
    assert [len(k["text"]) for _, k in bot.calls] == [4000, 1, 1]


async def test_rate_limit_attempt_budget_is_finite():
    store = StoreDouble()
    bot = BotDouble([TelegramRetryAfter(REQUEST, SENSITIVE, retry_after=1)] * 3)
    worker = DeliveryWorker(bot, store, pace_seconds=0, max_attempts=3)
    for second in range(3):
        assert await worker.run_once(NOW + timedelta(seconds=second))
    assert store.status == "failed"
    assert store.row.attempts == 3
    assert len(bot.calls) == 3
    assert not await worker.run_once(NOW + timedelta(seconds=3))


@pytest.mark.parametrize(
    "error,status",
    [
        (TelegramForbiddenError(REQUEST, SENSITIVE), "blocked"),
        (TelegramBadRequest(REQUEST, SENSITIVE), "failed"),
        (TelegramUnauthorizedError(REQUEST, SENSITIVE), "failed"),
        (TelegramNetworkError(REQUEST, SENSITIVE), "unknown"),
        (TelegramServerError(REQUEST, SENSITIVE), "unknown"),
        (TimeoutError(SENSITIVE), "unknown"),
        (ConnectionError(SENSITIVE), "unknown"),
        (RuntimeError(SENSITIVE), "unknown"),
    ],
)
async def test_real_aiogram_error_classification_is_sanitized_and_never_blind_retries(
    error,
    status,
    caplog,
):
    store = StoreDouble(Content("x" * 4001))
    bot = BotDouble([error])
    worker = DeliveryWorker(bot, store, pace_seconds=0)
    assert await worker.run_once(NOW)
    assert store.status == status
    assert store.row.next_part == 0
    assert store.retry_at is None
    assert store.error and SENSITIVE not in store.error + caplog.text
    assert "synthetic_secret" not in store.error + caplog.text
    assert not await worker.run_once(NOW + timedelta(days=1))
    assert len(bot.calls) == 1


async def test_cancellation_in_flight_is_unknown_not_pending():
    store = StoreDouble(Content("x" * 4001))
    bot = BotDouble([asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        await DeliveryWorker(bot, store, pace_seconds=0).run_once(NOW)
    assert store.status == "unknown"
    assert len(bot.calls) == 1
    assert store.settles == 1


async def test_invalid_persisted_content_or_cursor_fails_without_http():
    for content, cursor in [(Content(), 0), (Content("text"), -1), (Content("text"), 2)]:
        store = StoreDouble(content)
        store.row = replace(store.row, next_part=cursor)
        bot = BotDouble()
        assert await DeliveryWorker(bot, store, pace_seconds=0).run_once(NOW)
        assert store.status == "failed"
        assert not bot.calls


async def test_already_checkpointed_final_part_finishes_without_resending():
    store = StoreDouble()
    store.row = replace(store.row, next_part=1)
    bot = BotDouble()
    assert await DeliveryWorker(bot, store, pace_seconds=0).run_once(NOW)
    assert store.status == "sent"
    assert not bot.calls


async def test_attempts_already_exhausted_do_not_call_bot():
    store = StoreDouble()
    store.row = replace(store.row, attempts=3)
    bot = BotDouble()
    assert await DeliveryWorker(bot, store, pace_seconds=0).run_once(NOW)
    assert store.status == "failed"
    assert not bot.calls


@pytest.mark.parametrize(
    "kwargs",
    [
        {"pace_seconds": -1},
        {"pace_seconds": float("nan")},
        {"max_attempts": 0},
        {"max_attempts": True},
    ],
)
def test_invalid_worker_configuration(kwargs):
    with pytest.raises(ValueError):
        DeliveryWorker(BotDouble(), StoreDouble(), **kwargs)


async def test_naive_now_is_rejected_before_claim():
    store = StoreDouble()
    with pytest.raises(ValueError):
        await DeliveryWorker(BotDouble(), store).run_once(datetime(2026, 1, 1))
    assert store.claims == 0


async def test_run_stops_cleanly_and_does_not_recover_inflight():
    store = StoreDouble()
    stop = asyncio.Event()

    async def on_send():
        stop.set()

    bot = BotDouble(hook=on_send)
    await asyncio.wait_for(DeliveryWorker(bot, store, pace_seconds=0).run(stop), timeout=1)
    assert store.status == "sent"
    assert store.settles == 1
    assert len(bot.calls) == 1
    await DeliveryWorker(bot, store).run(stop)
    assert store.claims == 1


async def test_idle_run_can_be_stopped_without_busy_loop():
    store = StoreDouble()
    store.status = "sent"
    stop = asyncio.Event()
    task = asyncio.create_task(DeliveryWorker(BotDouble(), store, pace_seconds=0).run(stop))
    await asyncio.sleep(0)
    stop.set()
    await asyncio.wait_for(task, timeout=1)
    assert store.claims <= 2


async def test_shared_send_part_has_no_mutation_arbitrary_method_chat_override_or_paid_option():
    bot = BotDouble()
    part = prepare_parts(Content("preview"))[0]
    before = dict(part)
    await send_part(bot, 42, part)
    assert part == before
    assert bot.calls[0][1]["chat_id"] == 42
    assert bot.calls[0][1]["allow_paid_broadcast"] is False
    for invalid in [
        dict(part, method="delete_message"),
        dict(part, chat_id=99),
        dict(part, allow_paid_broadcast=True),
        dict(part, parse_mode="HTML"),
    ]:
        with pytest.raises(ValueError):
            await send_part(bot, 42, invalid)
    assert len(bot.calls) == 1


async def test_upstream_success_then_lost_response_is_unknown_without_duplicate():
    store = StoreDouble(Content("x" * 4001))
    effects = []

    async def committed_upstream():
        effects.append("message delivered upstream")

    bot = BotDouble([TimeoutError(SENSITIVE)], hook=committed_upstream)
    worker = DeliveryWorker(bot, store, pace_seconds=0)
    assert await worker.run_once(NOW)
    assert effects == ["message delivered upstream"]
    assert store.status == "unknown" and store.row.next_part == 0
    assert not await worker.run_once(NOW + timedelta(days=1))
    assert len(effects) == 1


async def test_storage_read_failure_fails_closed_without_dispatch(monkeypatch):
    store = StoreDouble()

    async def unavailable(*args):
        raise RuntimeError(SENSITIVE)

    monkeypatch.setattr(store, "is_subscribed", unavailable)
    bot = BotDouble()
    assert await DeliveryWorker(bot, store, pace_seconds=0).run_once(NOW)
    assert not bot.calls
    assert store.status == "unknown"
    assert store.error == "storage_state_unavailable"
    assert store.settles == 1


async def test_finish_failure_leaves_fenced_inflight_not_automatically_requeued(monkeypatch):
    store = StoreDouble(Content("x" * 4001))
    store.fail_advance = "false"

    async def unavailable(*args, **kwargs):
        raise RuntimeError(SENSITIVE)

    monkeypatch.setattr(store, "finish_delivery", unavailable)
    bot = BotDouble()
    worker = DeliveryWorker(bot, store, pace_seconds=0)
    with pytest.raises(RuntimeError, match="^Delivery checkpoint unavailable$"):
        await worker.run_once(NOW)
    assert store.status == "sending"
    assert store.settles == 1
    assert not await worker.run_once(NOW + timedelta(days=1))
    assert len(bot.calls) == 1


async def test_parallel_ticks_on_one_worker_never_duplicate_the_claim():
    store = StoreDouble(Content("x" * 4001))
    bot = BotDouble()
    worker = DeliveryWorker(bot, store, pace_seconds=0)
    assert await asyncio.gather(worker.run_once(NOW), worker.run_once(NOW)) == [True, False]
    assert len(bot.calls) == 2
    assert store.status == "sent"


@pytest.mark.parametrize(
    "transition,expected", [("paused", "pending"), ("stopped", "skipped"), ("optout", "skipped")]
)
async def test_policy_changes_between_claim_and_first_part_prevent_http(transition, expected):
    store = StoreDouble()
    original_claim = store.claim_delivery

    async def claim(now):
        delivery = await original_claim(now)
        if transition == "optout":
            store.subscribed = False
        else:
            store.campaign = replace(store.campaign, status=transition)
        return delivery

    store.claim_delivery = claim
    bot = BotDouble()
    assert await DeliveryWorker(bot, store, pace_seconds=0).run_once(NOW)
    assert store.status == expected
    assert not bot.calls
    assert not store.advances


class RecordingSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.requests = []

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        # Exercise aiogram's actual default/property resolution and JSON handling.
        data = {
            key: self.prepare_value(value, bot=bot, files={})
            for key, value in method.model_dump(warnings=False).items()
        }
        self.requests.append((method.__api_method__, data))
        message = Message.model_validate(
            {"message_id": 1, "date": 1, "chat": {"id": 42, "type": "private"}}
        )
        return [message] if method.__api_method__ == "sendMediaGroup" else message

    async def stream_content(
        self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True
    ):
        if False:
            yield b""


async def test_preview_and_worker_use_identical_real_aiogram_serialized_payloads():
    content = Content(
        "😀 title",
        [{"type": "bold", "offset": 3, "length": 5}],
        [Media("photo", "one"), Media("video", "two")],
    )
    session = RecordingSession()
    # This value only satisfies local Bot token-shape validation. No network IO.
    bot = Bot(
        "123456:synthetic_offline_value",
        session=session,
        default=DefaultBotProperties(parse_mode="MarkdownV2"),
    )
    for part in prepare_parts(content):
        await send_part(bot, 42, part)
    preview = session.requests[:]
    store = StoreDouble(content)
    assert await DeliveryWorker(bot, store, pace_seconds=0).run_once(NOW)
    assert session.requests[2:] == preview
    assert [method for method, _ in preview] == ["sendMediaGroup", "sendMessage"]
    assert all(data["allow_paid_broadcast"] == "false" for _, data in preview)
    assert preview[-1][1]["parse_mode"] is None
    assert '"offset": 3' in preview[-1][1]["entities"]
    assert '"parse_mode": "MarkdownV2"' not in preview[0][1]["media"]
    await bot.session.close()
