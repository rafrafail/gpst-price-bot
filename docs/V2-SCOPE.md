# Template v2 — implementation scope

Authorized: owner “Давай работай!” after the proposal in Telegram. Branch only, PR;
no merge, production restart, real broadcasts, paid calls, history rewrite or deletion.

Outcome: universal aiogram bot, no AI keys needed, private-chat UI conventions from
SlovoX, one durable broadcast editor, same transport for preview/now/schedule,
per-recipient progress, safe unknown outcomes, opt-out, role checks on every action.
Menu edits one panel; results/previews stay separate. Back preserves draft/context;
home does not stop delivery. Example notes feature proves the core is not broadcast-only.

Architecture: bot_template/{config,models,storage,navigation,content,delivery,app,runtime}.
SQLite is the durable authority; dialog state isn't campaign data. One process per DB
(enforced local runtime lock); transactional recipient claims also protect concurrent tasks.
A network ambiguity is unknown, never automatically retried. No read-rate analytics.
Albums obey Telegram's 2–10 items and have a separate text/button message when needed.

Old core/features/prompts/config are retained as legacy reference, NOT loaded by main.py.
Historical CSV are not read, copied, or purged in this wave; history cleanup and token
rotation need separate exposure assessment. Dangerous legacy export is sanitized in place.
No shared-history rewrite. No migration of old bot.db: v2 uses data/template-v2.sqlite3.

Acceptance: full UI handler journeys with real aiogram Update/Message types and isolated
SQLite, exact outgoing Bot API payloads, auth/stale buttons/double click, draft reopen,
next-part resume, known failure vs uncertain timeout, rate-limit/restart, opt-out, scheduler,
real polling + webhook transport entrypoints against isolated HTTP Bot API double.
Mocks prove local protocol/flow, not live Telegram delivery or owner UX approval.
