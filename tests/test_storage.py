"""Storage contract tests; every database is an isolated tmp_path file."""
import asyncio
import importlib
import sqlite3
import sys
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest

from bot_template.models import Button, Content, Media
from bot_template.storage import Store

OWNER = 101
NOW = datetime(2040, 1, 1, 12, tzinfo=timezone.utc)
VALID_CONTENT = Content(text="Storage contract fixture")


@pytest.fixture
async def store(tmp_path):
    instance = Store(tmp_path / "storage.sqlite3")
    await instance.initialize()
    yield instance
    await instance.close()


@pytest.fixture
def validator(monkeypatch):
    """Use the real validator when integrated; standalone lane uses a STRICT seam.

    The sibling content module does not exist on this branch. The temporary
    function accepts exactly one minimal known-valid Content, not arbitrary
    input. This is not proof of content validation: parent MUST rerun this
    suite integrated with the real delivery validator.
    """
    try:
        return importlib.import_module("bot_template.content")
    except ModuleNotFoundError as error:
        if error.name != "bot_template.content":
            raise
    module = ModuleType("bot_template.content")

    def validate_content(content):
        if content != VALID_CONTENT:
            raise ValueError("standalone strict validation seam: only minimal fixture allowed")

    module.validate_content = validate_content
    monkeypatch.setitem(sys.modules, "bot_template.content", module)
    return module


async def make_draft(store, *, owner=OWNER, audience="all", scheduled_at=None):
    campaign = await store.create_campaign(owner)
    return await store.save_campaign(
        campaign.id, owner, expected_revision=campaign.revision,
        content=VALID_CONTENT, audience=audience, scheduled_at=scheduled_at,
    )


@pytest.fixture
async def launch(store, validator):
    async def create(*, users=(OWNER,), audience="all", scheduled_at=None):
        for user in users:
            await store.register_user(user)
        draft = await make_draft(store, audience=audience, scheduled_at=scheduled_at)
        return await store.launch_campaign(
            draft.id, OWNER, expected_revision=draft.revision, now=NOW,
        )
    return create


@pytest.mark.asyncio
async def test_users_ui_and_draft_survive_close_reopen(tmp_path):
    path = tmp_path / "nested" / "storage.sqlite3"
    store = Store(path)
    assert not path.exists()  # Construction/import must not touch the filesystem.
    await store.initialize()
    await store.initialize()
    assert await store.get_ui(101) == {
        "screen": "home", "history": [], "input": None, "panel_id": None,
    }
    await store.register_user(101, "example", "Example")
    assert await store.is_subscribed(101)
    await store.set_subscription(101, False)
    await store.register_user(101, "updated", "Updated")
    assert not await store.is_subscribed(101)
    draft = await store.create_campaign(101)
    assert draft.status == "draft"
    assert draft.content == Content()
    assert draft.audience is None
    assert datetime.fromisoformat(draft.created_at).tzinfo == timezone.utc
    updated = await store.save_campaign(
        draft.id, 101, expected_revision=draft.revision,
        content=Content(text="Durable draft"), audience="self",
    )
    assert updated.revision == draft.revision + 1
    ui = {"screen": "editor", "history": ["home"], "input": "text", "panel_id": 17}
    await store.save_ui(101, ui)
    ui["history"].append("not persisted")
    await store.close()
    reopened = Store(path)
    await reopened.initialize()
    assert not await reopened.is_subscribed(101)
    assert await reopened.get_campaign(draft.id, 101) == updated
    assert (await reopened.get_ui(101))["history"] == ["home"]
    assert await reopened.get_campaign(draft.id, 999) is None
    await reopened.close()


@pytest.mark.parametrize("path", [":memory:", "", "file:memory?mode=memory&cache=shared"])
def test_reject_ephemeral_or_uri_paths(path):
    with pytest.raises(ValueError):
        Store(path)


async def test_user_metadata_preserves_first_seen_and_reactivation_respects_optout(store, launch):
    campaign = await launch()
    with closing(sqlite3.connect(store.path)) as connection, connection:
        first = connection.execute(
            "SELECT first_seen, last_seen FROM users WHERE user_id = ?", (OWNER,),
        ).fetchone()
    delivery = await store.claim_delivery(NOW)
    assert await store.finish_delivery(delivery, "blocked")
    assert await store.preview_audience(OWNER, "all") == []
    await store.set_subscription(OWNER, False)
    await store.register_user(OWNER, "new_username", "New name")
    assert await store.preview_audience(OWNER, "self") == []
    with closing(sqlite3.connect(store.path)) as connection, connection:
        metadata = connection.execute(
            "SELECT first_seen, last_seen, username, name FROM users WHERE user_id = ?", (OWNER,),
        ).fetchone()
    assert metadata[0] == first[0]
    assert metadata[1] >= first[1]
    assert metadata[2:] == ("new_username", "New name")
    await store.set_subscription(OWNER, True)
    assert await store.preview_audience(OWNER, "self") == [OWNER]
    assert (await store.campaign_counts(campaign.id))["blocked"] == 1


async def test_unknown_users_and_invalid_preferences_fail_without_implicit_registration(store):
    assert not await store.is_subscribed(OWNER)
    with pytest.raises(ValueError):
        await store.set_subscription(OWNER, False)
    with pytest.raises(ValueError):
        await store.set_subscription(OWNER, 1)
    assert await store.preview_audience(OWNER, "all") == []


@pytest.mark.parametrize("user_id", [0, -100, True, "101", 2**63])
async def test_private_user_ids_are_positive_integers(store, user_id):
    with pytest.raises(ValueError):
        await store.register_user(user_id)
    with pytest.raises(ValueError):
        await store.create_campaign(user_id)
    with pytest.raises(ValueError):
        await store.save_ui(user_id, {})


async def test_ui_states_are_independent_json_snapshots(store):
    state = await store.get_ui(OWNER)
    state["history"].append("local mutation")
    assert (await store.get_ui(OWNER))["history"] == []
    await store.save_ui(OWNER, {"screen": "confirm", "recipients": [OWNER, 202]})
    loaded = await store.get_ui(OWNER)
    assert loaded["screen"] == "confirm"
    assert loaded["recipients"] == [OWNER, 202]
    loaded["recipients"].append(303)
    assert (await store.get_ui(OWNER))["recipients"] == [OWNER, 202]
    assert (await store.get_ui(202))["screen"] == "home"
    with pytest.raises(ValueError):
        await store.save_ui(OWNER, {"bad": object()})
    with pytest.raises(ValueError):
        await store.save_ui(OWNER, {"bad": float("nan")})
    with pytest.raises(ValueError):
        await store.save_ui(OWNER, [])
    assert (await store.get_ui(OWNER))["screen"] == "confirm"


async def test_content_roundtrip_and_independent_duplicate(store):
    content = Content(
        text="Example", entities=[{"type": "bold", "offset": 0, "length": 7}],
        media=[Media("photo", "synthetic-file-id")],
        buttons=[[Button("Open", url="https://example.com")], [Button("Opt out", action="optout")]],
    )
    draft = await store.create_campaign(OWNER)
    draft = await store.save_campaign(
        draft.id, OWNER, expected_revision=draft.revision, content=content, audience="self",
        scheduled_at=(NOW + timedelta(days=1)).isoformat(),
    )
    content.entities[0]["length"] = 1
    assert (await store.get_campaign(draft.id)).content.entities[0]["length"] == 7
    duplicate = await store.duplicate_campaign(draft.id, OWNER)
    assert duplicate.id != draft.id
    assert duplicate.content == draft.content
    assert duplicate.status == "draft"
    assert duplicate.audience == "self"
    assert duplicate.scheduled_at is None
    assert (await store.campaign_counts(duplicate.id))["total"] == 0
    await store.save_campaign(
        duplicate.id, OWNER, expected_revision=duplicate.revision, content=Content(text="New copy"),
    )
    assert await store.get_campaign(draft.id) == draft
    assert await store.get_campaign(9999) is None
    assert await store.get_campaign(draft.id, 202) is None
    assert [c.id for c in await store.list_campaigns(OWNER)] == [duplicate.id, draft.id]
    assert await store.list_campaigns(202) == []
    assert await store.list_campaigns(OWNER, []) == []
    assert len(await store.list_campaigns(OWNER, ["draft"])) == 2
    with pytest.raises(ValueError):
        await store.list_campaigns(OWNER, ["typo"])


async def test_save_cas_and_schedule_normalization(store):
    draft = await make_draft(store)
    saved = await store.save_campaign(
        draft.id, OWNER, expected_revision=draft.revision,
        scheduled_at="2040-01-02T17:00:00+05:00",
    )
    assert saved.scheduled_at == "2040-01-02T12:00:00.000000+00:00"
    with pytest.raises(ValueError):
        await store.save_campaign(draft.id, OWNER, expected_revision=draft.revision, audience="self")
    assert await store.get_campaign(draft.id) == saved
    cleared = await store.save_campaign(
        draft.id, OWNER, expected_revision=saved.revision, clear_schedule=True,
    )
    assert cleared.scheduled_at is None
    assert cleared.content == saved.content
    assert cleared.audience == saved.audience
    assert cleared.revision == saved.revision + 1


@pytest.mark.parametrize("kwargs", [
    {"audience": "groups"}, {"content": {"text": "wrong type"}},
    {"scheduled_at": "2040-01-02T12:00:00"}, {"scheduled_at": "not a date"},
    {"scheduled_at": "2040-01-02T12:00:00Z", "clear_schedule": True},
    {"clear_schedule": 1}, {"expected_revision": True}, {"expected_revision": -1},
])
async def test_bad_draft_updates_are_atomic(store, kwargs):
    draft = await make_draft(store)
    arguments = {"expected_revision": draft.revision, **kwargs}
    with pytest.raises(ValueError):
        await store.save_campaign(draft.id, OWNER, **arguments)
    assert await store.get_campaign(draft.id) == draft


@pytest.mark.parametrize("operation", ["save", "launch", "duplicate", "pause", "resume", "stop", "retry"])
async def test_mutations_enforce_owner(store, validator, operation):
    draft = await make_draft(store)
    with pytest.raises(ValueError):
        if operation == "save":
            await store.save_campaign(draft.id, 202, expected_revision=draft.revision)
        elif operation == "launch":
            await store.launch_campaign(draft.id, 202, expected_revision=draft.revision, now=NOW)
        elif operation == "duplicate":
            await store.duplicate_campaign(draft.id, 202)
        else:
            await store.control_campaign(draft.id, 202, operation)
    assert await store.get_campaign(draft.id) == draft
    assert (await store.campaign_counts(draft.id))["total"] == 0


async def test_launch_revalidates_with_authoritative_validator_and_rolls_back(store, validator, monkeypatch):
    await store.register_user(OWNER)
    draft = await make_draft(store)
    calls = []

    def reject(content):
        calls.append(content)
        raise ValueError("authoritative content rejection")

    monkeypatch.setattr(validator, "validate_content", reject)
    with pytest.raises(ValueError, match="authoritative content rejection"):
        await store.launch_campaign(draft.id, OWNER, expected_revision=draft.revision, now=NOW)
    assert calls == [VALID_CONTENT]
    assert await store.get_campaign(draft.id) == draft
    assert (await store.campaign_counts(draft.id))["total"] == 0


@pytest.mark.parametrize("scenario", ["empty", "unset", "empty_all", "self_optout", "self_unregistered",
                                       "stale", "past", "equal"])
async def test_invalid_launch_never_freezes_recipients(store, validator, scenario):
    if scenario not in ("empty_all", "self_unregistered"):
        await store.register_user(OWNER)
    audience = "self" if scenario in ("self_optout", "self_unregistered") else "all"
    draft = await store.create_campaign(OWNER)
    draft = await store.save_campaign(
        draft.id, OWNER, expected_revision=draft.revision,
        content=Content() if scenario == "empty" else VALID_CONTENT,
        audience=None if scenario == "unset" else audience,
        scheduled_at=(NOW - timedelta(seconds=1)).isoformat() if scenario == "past"
        else NOW.isoformat() if scenario == "equal" else None,
    )
    if scenario == "self_optout":
        await store.set_subscription(OWNER, False)
    with pytest.raises(ValueError):
        await store.launch_campaign(
            draft.id, OWNER, expected_revision=draft.revision - 1 if scenario == "stale"
            else draft.revision, now=NOW,
        )
    assert await store.get_campaign(draft.id) == draft
    assert (await store.campaign_counts(draft.id))["total"] == 0


async def test_preview_and_launch_require_exact_reconfirmed_sorted_roster(store, validator):
    await store.register_user(303)
    await store.register_user(OWNER)
    preview = await store.preview_audience(OWNER, "all")
    assert preview == [OWNER, 303]
    draft = await make_draft(store)
    await store.register_user(202)
    with pytest.raises(ValueError, match="audience changed"):
        await store.launch_campaign(
            draft.id, OWNER, expected_revision=draft.revision, now=NOW,
            expected_recipients=preview,
        )
    assert await store.get_campaign(draft.id) == draft
    assert (await store.campaign_counts(draft.id))["total"] == 0
    preview = await store.preview_audience(OWNER, "all")
    await store.set_subscription(303, False)
    with pytest.raises(ValueError, match="audience changed"):
        await store.launch_campaign(
            draft.id, OWNER, expected_revision=draft.revision, now=NOW,
            expected_recipients=preview,
        )
    current = await store.preview_audience(OWNER, "all")
    assert current == [OWNER, 202]
    await store.launch_campaign(
        draft.id, OWNER, expected_revision=draft.revision, now=NOW, expected_recipients=current,
    )
    assert (await store.campaign_counts(draft.id))["total"] == 2
    assert (await store.claim_delivery(NOW)).user_id == OWNER
    assert (await store.claim_delivery(NOW)).user_id == 202
    assert await store.claim_delivery(NOW) is None


@pytest.mark.parametrize("recipients", [[202, OWNER], [OWNER, OWNER], [True], (OWNER,), [-1]])
async def test_launch_rejects_malformed_confirmation_rosters(store, validator, recipients):
    await store.register_user(OWNER)
    draft = await make_draft(store)
    with pytest.raises(ValueError):
        await store.launch_campaign(
            draft.id, OWNER, expected_revision=draft.revision, now=NOW,
            expected_recipients=recipients,
        )
    assert await store.get_campaign(draft.id) == draft


async def test_launch_once_immutable_content_and_recipient_snapshot(store, launch):
    campaign = await launch(users=(OWNER, 202))
    await store.register_user(303)  # Never added to an already launched snapshot.
    with pytest.raises(ValueError):
        await store.launch_campaign(campaign.id, OWNER, expected_revision=campaign.revision, now=NOW)
    with pytest.raises(ValueError):
        await store.save_campaign(
            campaign.id, OWNER, expected_revision=campaign.revision, content=Content(text="Edit"),
        )
    duplicate = await store.duplicate_campaign(campaign.id, OWNER)
    assert duplicate.content == campaign.content
    assert duplicate.status == "draft"
    claims = [await store.claim_delivery(NOW), await store.claim_delivery(NOW)]
    assert [d.user_id for d in claims] == [OWNER, 202]
    assert await store.claim_delivery(NOW) is None
    assert (await store.campaign_counts(campaign.id))["total"] == 2


async def test_due_schedule_pause_resume_and_terminal_stop(store, launch):
    due = NOW + timedelta(hours=1)
    campaign = await launch(users=(OWNER, 202), scheduled_at=due.isoformat())
    assert campaign.status == "scheduled"
    assert await store.claim_delivery(due - timedelta(microseconds=1)) is None
    paused = await store.control_campaign(campaign.id, OWNER, "pause")
    assert paused.status == "paused"
    assert await store.claim_delivery(due) is None
    await store.settle_campaigns(due)
    assert (await store.get_campaign(campaign.id)).status == "paused"
    await store.control_campaign(campaign.id, OWNER, "resume")
    delivery = await store.claim_delivery(due)
    assert delivery.user_id == OWNER
    assert (await store.get_campaign(campaign.id)).status == "running"
    stopped = await store.control_campaign(campaign.id, OWNER, "stop")
    assert stopped.status == "stopped"
    assert await store.claim_delivery(due) is None
    assert await store.finish_delivery(delivery, "sent")  # In-flight outcome is still recorded.
    await store.settle_campaigns(due)
    assert (await store.get_campaign(campaign.id)).status == "stopped"
    counts = await store.campaign_counts(campaign.id)
    assert counts["sent"] == 1
    assert counts["skipped"] == 1
    for action in ("resume", "pause", "retry", "stop"):
        with pytest.raises(ValueError):
            await store.control_campaign(campaign.id, OWNER, action)


async def test_checkpoint_safe_retry_and_old_claim_fences_survive_reopen(store, launch):
    campaign = await launch()
    first = await store.claim_delivery(NOW)
    assert first.attempts == 1
    assert first.next_part == 0
    assert await store.advance_delivery(first, 1)
    assert await store.advance_delivery(first, 1)  # Idempotent checkpoint acknowledgement.
    assert not await store.advance_delivery(first, 0)  # Never roll progress backwards.
    await store.close()
    reopened = Store(store.path)
    await reopened.initialize()  # MUST NOT recover uncertain sending rows automatically.
    assert (await reopened.campaign_counts(campaign.id))["sending"] == 1
    assert await reopened.claim_delivery(NOW) is None
    retry = NOW + timedelta(seconds=30)
    assert await reopened.finish_delivery(first, "pending", error="rate limited", retry_at=retry)
    assert not await reopened.advance_delivery(first, 2)
    assert not await reopened.finish_delivery(first, "blocked")
    assert await reopened.preview_audience(OWNER, "self") == [OWNER]
    assert await reopened.claim_delivery(retry - timedelta(microseconds=1)) is None
    second = await reopened.claim_delivery(retry)
    assert second.id == first.id
    assert second.next_part == 1
    assert second.attempts == 2
    assert second.claim_token != first.claim_token
    assert not await reopened.advance_delivery(first, 99)
    assert not await reopened.finish_delivery(first, "sent")
    assert await reopened.advance_delivery(second, 2)
    assert await reopened.finish_delivery(second, "sent")
    assert not await reopened.finish_delivery(second, "failed")
    await reopened.settle_campaigns(retry)
    assert (await reopened.get_campaign(campaign.id)).status == "completed"
    await reopened.close()


@pytest.mark.parametrize("field,value", [
    ("claim_token", "wrong-fence"), ("attempts", 2), ("user_id", 202),
    ("campaign_id", 999), ("id", 999),
])
async def test_forged_fences_cannot_progress_finish_or_mark_user_unreachable(store, launch, field, value):
    campaign = await launch()
    delivery = await store.claim_delivery(NOW)
    forged = replace(delivery, **{field: value})
    assert not await store.advance_delivery(forged, 1)
    assert not await store.finish_delivery(forged, "blocked")
    assert (await store.campaign_counts(campaign.id))["sending"] == 1
    assert await store.preview_audience(OWNER, "all") == [OWNER]
    assert await store.finish_delivery(delivery, "sent")


async def test_invalid_progress_and_finish_arguments_do_not_change_sending(store, launch):
    campaign = await launch()
    delivery = await store.claim_delivery(NOW)
    for checkpoint in (-1, True, 1.5):
        with pytest.raises(ValueError):
            await store.advance_delivery(delivery, checkpoint)
    for status in ("sending", "completed", "draft", "timeout", [], {}):
        with pytest.raises(ValueError):
            await store.finish_delivery(delivery, status)
    with pytest.raises(ValueError):
        await store.finish_delivery(delivery, "sent", retry_at=NOW)
    with pytest.raises(ValueError):
        await store.finish_delivery(delivery, "pending", retry_at=NOW.replace(tzinfo=None))
    assert (await store.campaign_counts(campaign.id))["sending"] == 1


async def test_recovery_is_explicit_unknown_terminal_and_never_automatically_retried(store, launch):
    campaign = await launch()
    delivery = await store.claim_delivery(NOW)
    assert await store.advance_delivery(delivery, 1)
    await store.close()
    reopened = Store(store.path)
    await reopened.initialize()
    assert await reopened.recover_inflight(NOW) == 1
    assert await reopened.recover_inflight(NOW) == 0
    assert not await reopened.finish_delivery(delivery, "pending")
    assert not await reopened.advance_delivery(delivery, 2)
    assert await reopened.claim_delivery(NOW + timedelta(days=100)) is None
    await reopened.settle_campaigns(NOW)
    assert (await reopened.get_campaign(campaign.id)).status == "attention"
    with pytest.raises(ValueError):
        await reopened.control_campaign(campaign.id, OWNER, "retry")
    assert (await reopened.campaign_counts(campaign.id))["unknown"] == 1
    await reopened.close()


@pytest.mark.parametrize("outcomes,target", [
    (["sent"], "completed"), (["skipped"], "completed"), (["failed"], "failed"),
    (["blocked"], "failed"), (["sent", "failed"], "partial"),
    (["sent", "blocked"], "partial"), (["unknown"], "attention"),
    (["sent", "unknown", "failed"], "attention"), (["skipped", "failed"], "failed"),
    (["unknown", "blocked"], "attention"),
])
async def test_settlement_truth_table_and_exact_counts(store, launch, outcomes, target):
    campaign = await launch(users=tuple(OWNER + index for index in range(len(outcomes))))
    for outcome in outcomes:
        delivery = await store.claim_delivery(NOW)
        assert await store.finish_delivery(delivery, outcome)
    assert await store.claim_delivery(NOW) is None
    await store.settle_campaigns(NOW)
    final = await store.get_campaign(campaign.id)
    assert final.status == target
    await store.settle_campaigns(NOW)
    assert await store.get_campaign(campaign.id) == final
    assert await store.campaign_counts(campaign.id) == {
        "total": len(outcomes), "pending": 0, "sending": 0,
        "sent": outcomes.count("sent"), "failed": outcomes.count("failed"),
        "blocked": outcomes.count("blocked"), "unknown": outcomes.count("unknown"),
        "skipped": outcomes.count("skipped"),
    }


async def test_settlement_preserves_active_work_and_paused_campaign(store, launch):
    campaign = await launch(users=(OWNER, 202))
    await store.settle_campaigns(NOW)
    assert (await store.get_campaign(campaign.id)).status == "running"
    first = await store.claim_delivery(NOW)
    second = await store.claim_delivery(NOW)
    await store.finish_delivery(first, "sent")
    await store.settle_campaigns(NOW)
    assert (await store.get_campaign(campaign.id)).status == "running"  # Still sending.
    await store.control_campaign(campaign.id, OWNER, "pause")
    assert await store.finish_delivery(second, "sent")
    await store.settle_campaigns(NOW)
    assert (await store.get_campaign(campaign.id)).status == "paused"
    await store.control_campaign(campaign.id, OWNER, "resume")
    await store.settle_campaigns(NOW)
    assert (await store.get_campaign(campaign.id)).status == "completed"
    with pytest.raises(ValueError):
        await store.control_campaign(campaign.id, OWNER, "retry")


@pytest.mark.parametrize("outcomes,initial", [
    (["failed"], "failed"), (["sent", "failed"], "partial"),
    (["sent", "unknown", "blocked", "skipped", "failed"], "attention"),
])
async def test_manual_retry_only_failed_preserves_checkpoint_and_other_outcomes(store, launch, outcomes, initial):
    campaign = await launch(users=tuple(OWNER + index for index in range(len(outcomes))))
    failed = None
    for outcome in outcomes:
        delivery = await store.claim_delivery(NOW)
        if outcome == "failed":
            failed = delivery
            assert await store.advance_delivery(delivery, 1)
        assert await store.finish_delivery(delivery, outcome)
    await store.settle_campaigns(NOW)
    assert (await store.get_campaign(campaign.id)).status == initial
    retried = await store.control_campaign(campaign.id, OWNER, "retry")
    assert retried.status == "running"
    counts = await store.campaign_counts(campaign.id)
    assert counts["failed"] == 0
    assert counts["pending"] == 1
    for status in ("sent", "unknown", "blocked", "skipped"):
        assert counts[status] == outcomes.count(status)
    retry = await store.claim_delivery(NOW)
    assert retry.id == failed.id
    assert retry.next_part == 1
    assert retry.attempts == 1  # Explicit retry resets the attempt budget only for failed.
    assert retry.claim_token != failed.claim_token
    assert not await store.finish_delivery(failed, "sent")
    assert await store.finish_delivery(retry, "sent")
    assert await store.claim_delivery(NOW) is None
    await store.settle_campaigns(NOW)
    assert (await store.get_campaign(campaign.id)).status == (
        "attention" if "unknown" in outcomes else "completed"
    )


@pytest.mark.parametrize("action", ["pause", "resume", "stop", "retry", "delete", "launch"])
async def test_draft_cannot_be_controlled(store, action):
    draft = await make_draft(store)
    with pytest.raises(ValueError):
        await store.control_campaign(draft.id, OWNER, action)
    assert await store.get_campaign(draft.id) == draft


async def test_preferences_rechecked_after_launch_for_self_and_all(store, launch):
    first = await launch(users=(OWNER, 202))
    # Snapshot both first; marking blocked in one campaign also affects the other.
    second = await launch(users=(), audience="self")
    delivery = await store.claim_delivery(NOW)
    assert delivery.user_id == OWNER
    assert await store.finish_delivery(delivery, "blocked")
    await store.set_subscription(202, False)
    assert await store.claim_delivery(NOW) is None
    await store.settle_campaigns(NOW)
    assert (await store.campaign_counts(first.id))["blocked"] == 1
    assert (await store.campaign_counts(first.id))["skipped"] == 1
    assert (await store.campaign_counts(second.id))["skipped"] == 1
    assert (await store.get_campaign(first.id)).status == "failed"
    assert (await store.get_campaign(second.id)).status == "completed"
    assert await store.preview_audience(OWNER, "all") == []
    await store.set_subscription(202, True)
    assert await store.claim_delivery(NOW) is None  # Skipped rows are never resurrected.


async def test_self_audience_still_honors_optout_after_launch(store, launch):
    campaign = await launch(users=(OWNER, 202), audience="self")
    assert (await store.campaign_counts(campaign.id))["total"] == 1
    await store.set_subscription(OWNER, False)
    assert await store.claim_delivery(NOW) is None
    assert (await store.campaign_counts(campaign.id))["skipped"] == 1
    assert await store.preview_audience(OWNER, "self") == []
    assert await store.preview_audience(OWNER, "all") == [202]


async def test_all_time_inputs_must_be_aware(store, launch):
    campaign = await launch()
    naive = NOW.replace(tzinfo=None)
    for operation in (store.claim_delivery, store.settle_campaigns, store.recover_inflight):
        with pytest.raises(ValueError):
            await operation(naive)
    draft = await make_draft(store)
    with pytest.raises(ValueError):
        await store.launch_campaign(draft.id, OWNER, expected_revision=draft.revision, now=naive)
    assert (await store.campaign_counts(campaign.id))["pending"] == 1


async def test_concurrent_saves_and_launches_have_one_winner_across_stores(store, validator):
    await store.register_user(OWNER)
    draft = await make_draft(store)
    peers = [Store(store.path) for _ in range(8)]
    saves = await asyncio.gather(*(
        peer.save_campaign(draft.id, OWNER, expected_revision=draft.revision, audience="self")
        for peer in peers
    ), return_exceptions=True)
    winners = [result for result in saves if not isinstance(result, BaseException)]
    assert len(winners) == 1
    assert sum(isinstance(result, ValueError) for result in saves) == 7
    current = winners[0]
    launches = await asyncio.gather(*(
        peer.launch_campaign(
            draft.id, OWNER, expected_revision=current.revision, now=NOW,
            expected_recipients=[OWNER],
        ) for peer in peers
    ), return_exceptions=True)
    assert sum(not isinstance(result, BaseException) for result in launches) == 1
    assert sum(isinstance(result, ValueError) for result in launches) == 7
    assert (await store.campaign_counts(draft.id))["total"] == 1


async def test_concurrent_claims_and_finishes_are_fenced_and_never_duplicate(store, launch):
    users = tuple(range(101, 125))
    campaign = await launch(users=users)
    peers = [Store(store.path) for _ in range(48)]
    claims = await asyncio.gather(*(peer.claim_delivery(NOW) for peer in peers))
    deliveries = [claim for claim in claims if claim is not None]
    assert len(deliveries) == len(users)
    assert sorted(d.user_id for d in deliveries) == list(users)
    assert len({d.id for d in deliveries}) == len(users)
    assert len({d.claim_token for d in deliveries}) == len(users)
    assert all(d.attempts == 1 for d in deliveries)
    assert (await store.campaign_counts(campaign.id))["sending"] == len(users)
    for delivery in deliveries:
        results = await asyncio.gather(
            peers[0].finish_delivery(delivery, "sent"),
            peers[1].finish_delivery(delivery, "failed"),
        )
        assert sorted(results) == [False, True]
    await asyncio.gather(*(peer.settle_campaigns(NOW) for peer in peers[:4]))
    counts = await store.campaign_counts(campaign.id)
    assert counts["sent"] + counts["failed"] == len(users)
    assert counts["sending"] == counts["pending"] == 0
    assert await store.claim_delivery(NOW) is None


async def test_concurrent_initialize_same_new_file_is_idempotent(tmp_path):
    path = tmp_path / "concurrent" / "storage.sqlite3"
    peers = [Store(path) for _ in range(8)]
    await asyncio.gather(*(peer.initialize() for peer in peers))
    await peers[0].register_user(OWNER)
    assert await peers[-1].preview_audience(OWNER, "self") == [OWNER]


async def test_snapshot_insert_failure_rolls_back_entire_launch_and_can_retry(store, validator):
    for user in (OWNER, 202):
        await store.register_user(user)
    draft = await make_draft(store)
    with closing(sqlite3.connect(store.path)) as connection, connection:
        connection.execute("""CREATE TRIGGER fail_snapshot BEFORE INSERT ON deliveries
                              WHEN NEW.user_id = 202 BEGIN
                              SELECT RAISE(ABORT, 'injected snapshot failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="injected snapshot failure"):
        await store.launch_campaign(
            draft.id, OWNER, expected_revision=draft.revision, now=NOW,
            expected_recipients=[OWNER, 202],
        )
    assert await store.get_campaign(draft.id) == draft
    assert (await store.campaign_counts(draft.id))["total"] == 0
    with closing(sqlite3.connect(store.path)) as connection, connection:
        connection.execute("DROP TRIGGER fail_snapshot")
    await store.launch_campaign(
        draft.id, OWNER, expected_revision=draft.revision, now=NOW,
        expected_recipients=[OWNER, 202],
    )
    assert (await store.campaign_counts(draft.id))["total"] == 2


async def test_pausing_running_campaign_blocks_new_claims_but_keeps_checkpoint(store, launch):
    campaign = await launch(users=(OWNER, 202))
    delivery = await store.claim_delivery(NOW)
    assert await store.advance_delivery(delivery, 1)
    await store.control_campaign(campaign.id, OWNER, "pause")
    assert await store.finish_delivery(delivery, "pending", retry_at=NOW)
    assert await store.claim_delivery(NOW) is None
    with pytest.raises(ValueError):
        await store.control_campaign(campaign.id, OWNER, "pause")
    await store.control_campaign(campaign.id, OWNER, "resume")
    resumed = await store.claim_delivery(NOW)
    assert resumed.user_id == OWNER
    assert resumed.next_part == 1
    assert resumed.attempts == 2
    assert (await store.claim_delivery(NOW)).user_id == 202


@pytest.mark.parametrize("statuses", [[[]], [{}], [None], "running"])
async def test_invalid_status_filters_raise_value_error(store, statuses):
    with pytest.raises(ValueError):
        await store.list_campaigns(OWNER, statuses)


async def test_invalid_audience_and_metadata_do_not_create_users(store):
    with pytest.raises(ValueError):
        await store.preview_audience(OWNER, "groups")
    with pytest.raises(ValueError):
        await store.register_user(OWNER, username=[])
    with pytest.raises(ValueError):
        await store.register_user(OWNER, name={})
    assert await store.preview_audience(OWNER, "all") == []


async def test_confirmation_detects_replaced_recipient_even_when_count_is_unchanged(store, validator):
    for user in (OWNER, 202):
        await store.register_user(user)
    draft = await make_draft(store)
    confirmed = await store.preview_audience(OWNER, "all")
    assert confirmed == [OWNER, 202]
    await store.set_subscription(202, False)
    await store.register_user(303)
    current = await store.preview_audience(OWNER, "all")
    assert current == [OWNER, 303]
    assert len(current) == len(confirmed)
    with pytest.raises(ValueError, match="audience changed"):
        await store.launch_campaign(
            draft.id, OWNER, expected_revision=draft.revision, now=NOW,
            expected_recipients=confirmed,
        )
    assert (await store.campaign_counts(draft.id))["total"] == 0
    assert await store.get_campaign(draft.id) == draft


async def test_committed_state_survives_a_separate_process_exit(tmp_path):
    path = tmp_path / "process.sqlite3"
    code = """
import asyncio
import sys
from bot_template.models import Content
from bot_template.storage import Store
async def main():
    store = Store(sys.argv[1])
    await store.initialize()
    await store.register_user(101)
    await store.set_subscription(101, False)
    campaign = await store.create_campaign(101)
    await store.save_campaign(
        campaign.id, 101, expected_revision=campaign.revision,
        content=Content(text='Committed by child process'), audience='self',
    )
    await store.save_ui(101, {'screen': 'editor', 'campaign_id': campaign.id})
    # No Store.close call: no connection should outlive an awaited transaction.
asyncio.run(main())
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-B", "-c", code, str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=Path(__file__).resolve().parents[1],
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    assert process.returncode == 0, stderr.decode()
    assert stdout == b""
    reopened = Store(path)
    await reopened.initialize()
    assert not await reopened.is_subscribed(OWNER)
    ui = await reopened.get_ui(OWNER)
    assert ui["screen"] == "editor"
    draft = await reopened.get_campaign(ui["campaign_id"], OWNER)
    assert draft.content == Content(text="Committed by child process")
    assert draft.audience == "self"
    assert draft.status == "draft"
    await reopened.close()
