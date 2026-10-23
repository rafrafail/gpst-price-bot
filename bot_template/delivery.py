"""Fenced per-recipient delivery with conservative treatment of uncertain sends.

There is no exactly-once Telegram API. If HTTP success cannot be durably
checkpointed, or HTTP's outcome is ambiguous, this worker stops that recipient
as unknown. Only an explicit RetryAfter response is automatically retried.
In-flight recovery belongs to the exclusive runtime startup, never this module.
"""

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramUnauthorizedError,
)

from .content import prepare_parts
from .models import Campaign, Delivery

logger = logging.getLogger(__name__)
_METHODS = frozenset({"send_message", "send_photo", "send_video", "send_media_group"})


class DeliveryStore(Protocol):
    """The async storage_contract.md subset needed by the worker."""

    async def claim_delivery(self, now: datetime) -> Delivery | None: ...
    async def get_campaign(
        self, campaign_id: int, owner_id: int | None = None
    ) -> Campaign | None: ...
    async def is_subscribed(self, user_id: int) -> bool: ...
    async def advance_delivery(self, delivery: Delivery, next_part: int) -> bool: ...
    async def finish_delivery(
        self,
        delivery: Delivery,
        status: str,
        *,
        error: str | None = None,
        retry_at: datetime | None = None,
    ) -> bool: ...
    async def settle_campaigns(self, now: datetime) -> None: ...


async def send_part(bot: Any, user_id: int, part: dict) -> Any:
    """Send a prepared part, shared by UI preview and the delivery worker.

    Dispatch is intentionally not arbitrary getattr: a caller cannot inject
    chat_id, a destructive method, markup parsing, or paid-broadcast behavior.
    The supplied mapping is never mutated.
    """
    if not isinstance(part, dict):
        raise ValueError("A prepared content part is required")
    method = part.get("method")
    if not isinstance(method, str) or method not in _METHODS or "chat_id" in part:
        raise ValueError("Unsupported delivery method or chat override")
    if part.get("allow_paid_broadcast") not in (None, False):
        raise ValueError("Paid broadcasting is disabled")
    if part.get("parse_mode") is not None:
        raise ValueError("Only native Telegram entities are supported")
    kwargs = {key: value for key, value in part.items() if key != "method"}
    kwargs["allow_paid_broadcast"] = False
    if method != "send_media_group":
        kwargs["parse_mode"] = None  # override a Bot-wide HTML/Markdown default
    return await getattr(bot, method)(chat_id=user_id, **kwargs)


def _utc_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("An aware delivery time is required")
    return now.astimezone(timezone.utc)


class DeliveryWorker:
    def __init__(self, bot, store: DeliveryStore, *, pace_seconds=0.06, max_attempts=3):
        if (
            isinstance(pace_seconds, bool)
            or not isinstance(pace_seconds, (int, float))
            or not math.isfinite(pace_seconds)
            or pace_seconds < 0
        ):
            raise ValueError("pace_seconds must be finite and nonnegative")
        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        self.bot = bot
        self.store = store
        self.pace_seconds = float(pace_seconds)
        self.max_attempts = max_attempts
        self._last_send: float | None = None
        self._lock = asyncio.Lock()

    async def _finish(self, delivery, status, *, error=None, retry_at=None):
        # All callers supply constant error codes, never str(exception), method
        # reprs, Telegram URLs, message bodies, or token-bearing tracebacks.
        try:
            return await self.store.finish_delivery(
                delivery,
                status,
                error=error,
                retry_at=retry_at,
            )
        except Exception:
            raise RuntimeError("Delivery checkpoint unavailable") from None

    async def _pace(self):
        loop = asyncio.get_running_loop()
        if self._last_send is not None:
            delay = self.pace_seconds - (loop.time() - self._last_send)
            if delay > 0:
                await asyncio.sleep(delay)

    async def _send_error(self, delivery, error, now):
        if isinstance(error, TelegramRetryAfter):
            if delivery.attempts >= self.max_attempts:
                await self._finish(delivery, "failed", error="rate_limit_attempts_exhausted")
                return
            # Only Telegram's explicit 429 certifies that this part was not sent.
            delay = error.retry_after
            if type(delay) is not int or delay < 0:
                await self._finish(delivery, "failed", error="invalid_retry_after")
                return
            try:
                retry_at = now + timedelta(seconds=max(1, delay))
            except OverflowError:
                await self._finish(delivery, "failed", error="invalid_retry_after")
                return
            await self._finish(delivery, "pending", error="rate_limited", retry_at=retry_at)
        elif isinstance(error, TelegramForbiddenError):
            await self._finish(delivery, "blocked", error="telegram_forbidden")
        elif isinstance(error, TelegramBadRequest):
            await self._finish(delivery, "failed", error="telegram_bad_request")
        elif isinstance(error, TelegramUnauthorizedError):
            await self._finish(delivery, "failed", error="telegram_unauthorized")
        else:
            # Includes server errors, network failures, timeouts, unexpected
            # client exceptions, and response-decoding failures. No blind retry.
            await self._finish(delivery, "unknown", error="send_outcome_unknown")

    async def _deliver(self, delivery: Delivery, now: datetime | None):
        if delivery.attempts > self.max_attempts:
            await self._finish(delivery, "failed", error="attempts_exhausted")
            return
        campaign = await self.store.get_campaign(delivery.campaign_id)
        if campaign is None:
            await self._finish(delivery, "failed", error="campaign_missing")
            return
        try:
            parts = prepare_parts(campaign.content)
        except ValueError:
            await self._finish(delivery, "failed", error="invalid_content")
            return
        if type(delivery.next_part) is not int or not 0 <= delivery.next_part <= len(parts):
            await self._finish(delivery, "failed", error="invalid_progress")
            return
        for index in range(delivery.next_part, len(parts)):
            await self._pace()
            # Re-read after every checkpoint AND after the pacing await. A UI
            # pause cannot cancel HTTP already in flight, but forbids the next.
            campaign = await self.store.get_campaign(delivery.campaign_id)
            if campaign is None or campaign.status == "stopped":
                await self._finish(delivery, "skipped", error="campaign_stopped")
                return
            if campaign.status == "paused":
                await self._finish(delivery, "pending")
                return
            if campaign.status != "running":
                await self._finish(delivery, "unknown", error="campaign_not_running")
                return
            if not await self.store.is_subscribed(delivery.user_id):
                await self._finish(delivery, "skipped", error="recipient_opted_out")
                return
            self._last_send = asyncio.get_running_loop().time()
            try:
                await send_part(self.bot, delivery.user_id, parts[index])
            except Exception as error:
                await self._send_error(delivery, error, _utc_now(now))
                return
            try:
                advanced = await self.store.advance_delivery(delivery, index + 1)
            except Exception:
                advanced = False
            if not advanced:
                await self._finish(delivery, "unknown", error="progress_checkpoint_failed")
                return
        # This also handles a resumed row whose final part was checkpointed
        # immediately before the process stopped, without resending anything.
        await self._finish(delivery, "sent")

    async def run_once(self, now: datetime | None = None) -> bool:
        """Claim at most one recipient; return whether any work was claimed.

        False is idle, not a promise that the campaign is complete. A fenced
        finish/advance returning False never permits another HTTP request.
        """
        claim_time = _utc_now(now)
        async with self._lock:
            try:
                delivery = await self.store.claim_delivery(claim_time)
            except Exception:
                raise RuntimeError("Delivery claim unavailable") from None
            if delivery is None:
                return False
            try:
                await self._deliver(delivery, now)
            except asyncio.CancelledError:
                # Do not requeue a cancelled request whose HTTP outcome cannot
                # be proved. If storage is down, retain sending for startup
                # recover_inflight, which turns it unknown rather than pending.
                await asyncio.shield(self._finish(delivery, "unknown", error="worker_cancelled"))
                raise
            except Exception:
                await self._finish(delivery, "unknown", error="storage_state_unavailable")
            finally:
                try:
                    await self.store.settle_campaigns(_utc_now(now))
                except Exception:
                    raise RuntimeError("Campaign settlement unavailable") from None
            return True

    async def run(self, stop_event: asyncio.Event):
        """Drain due work until stopped; idle waits are interruptible and bounded."""
        while not stop_event.is_set():
            try:
                claimed = await self.run_once()
            except Exception:
                # No exc_info: even a framework exception may contain token URLs
                # and message bodies. Uncertain rows remain fenced, never resent.
                logger.error("Delivery worker storage operation unavailable")
                claimed = False
            if not claimed:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=0.25)
                except TimeoutError:
                    pass
