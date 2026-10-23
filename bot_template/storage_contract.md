# Shared storage API (async, SQLite, owned by storage lane)

Store(path: Path|str); no IO at import. All async methods below. Models from models.py.
Times are aware datetime inputs and ISO UTC strings in records. ValueError for invalid,
unauthorized/stale/non-draft operations. Tests use isolated DB only.

- initialize(), close() (may be no-op if per-call connections).
- register_user(user_id, username=None, name=None): preserve first_seen, update last_seen;
  initial subscribed=True; subsequent interaction MUST NOT override opt-out.
- set_subscription(user_id, subscribed: bool); is_subscribed(user_id)->bool.
- create_campaign(owner_id)->Campaign: status draft, empty content, audience None.
- get_campaign(campaign_id, owner_id=None)->Campaign|None; owner filter enforced if supplied.
- list_campaigns(owner_id, statuses: list[str]|None=None)->list[Campaign].
- save_campaign(campaign_id, owner_id, *, expected_revision:int,
  content:Content|None=None, audience:str|None=None, scheduled_at:str|None=None,
  clear_schedule:bool=False)->Campaign. draft-only CAS, increment revision. Audience all/self.
- preview_audience(owner_id,audience)->list[int]: sorted eligible subscribed/reachable IDs.
- launch_campaign(campaign_id,owner_id,*,expected_revision:int,now:datetime,
  expected_recipients:list[int]|None=None)->Campaign. UI always supplies the previewed roster;
  changed membership requires reconfirmation before any delivery rows are created.
  Atomic draft->running/scheduled + frozen per-recipient rows. Reject empty content,
  invalid buttons/media (use content.validate_content), unset audience, empty audience,
  scheduled_at <= now, stale revision. One campaign launch only. self = owner only;
  all = subscribed reachable private users, recheck preferences before each delivery.
- duplicate_campaign(campaign_id, owner_id)->Campaign: independent draft, no schedule.
- control_campaign(campaign_id,owner_id,action:str)->Campaign: pause/resume/stop/retry.
  Pause running/scheduled; resume paused; stop running/paused/scheduled (terminal stopped).
  Retry ONLY definitively failed deliveries from partial/failed/completed/attention,
  never sent/unknown/blocked/skipped; reset attempts on selected failed rows.
- claim_delivery(now:datetime)->Delivery|None: atomic fenced claim, due scheduled->running,
  pending due row only; increment attempts. Never claim paused/stopped/unknown/sending.
  Skip unsubscribed/unreachable users (except explicit self-test owner? still opt-out honored).
- advance_delivery(delivery:Delivery,next_part:int)->bool: guarded by claim_token + sending.
- finish_delivery(delivery:Delivery,status:str,*,error:str|None=None,
  retry_at:datetime|None=None)->bool: fenced; pending (known safe retry), sent, failed,
  blocked (mark user unreachable), unknown (ambiguous network), skipped.
- recover_inflight(now:datetime)->int: mark sending->unknown; never requeue uncertain rows.
  ONLY runtime startup under exclusive process lock; do not call automatically in Store init.
- settle_campaigns(now:datetime)->None: active campaigns with no pending/sending =>
  attention if unknown; completed if only sent/skipped; partial if sent plus failed/blocked;
  failed if no sent and failed/blocked. Preserve paused/stopped. No false success.
- campaign_counts(campaign_id)->dict[str,int]: total + pending/sending/sent/failed/blocked/unknown/skipped.
- get_ui(user_id)->dict: default {screen:'home',history:[],input:None,panel_id:None}.
- save_ui(user_id,data:dict)->None: durable UI state; draft content itself lives in campaigns.

Core validation is in bot_template/content.py (delivery lane); import lazily in launch to avoid cycles.
No secrets, raw Telegram file URLs, or message bodies in logs. No legacy bot.db migration.
