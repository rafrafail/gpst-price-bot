# Telegram bot template v2

- Active runtime: main.py -> bot_template/runtime.py. The root core/, features/,
  config/, prompts/ and old docs are retained legacy reference, not a second active bot.
- Work only on hermes/* branches; no merge/deploy/live broadcasts without owner approval.
- Never open .env, tokens, old broadcast CSV, or private credentials. Do not embed bot
  tokens in exports or log exceptions containing Telegram request URLs.
- User interface contract: docs/UI-CONVENTIONS.md. One navigation panel; back restores
  context, home preserves drafts/jobs; input cancel != draft delete != delivery stop.
- Do not duplicate sender logic: preview/test/worker use content.prepare_parts + delivery.send_part.
- Native Telegram entities and file IDs are content authority. No MarkdownV2 for admin content.
- Storage is durable SQLite; versioned draft changes, atomic launch and claims. Unknown
  network outcomes are not retried automatically. No claims of exactly-once external delivery.
- Add features inside bot_template/ without making broadcasts/AI mandatory. Example notes
  in app.py must work with BROADCAST_ENABLED=0. Avoid a framework/plugin ecosystem.
- Acceptance CI: native X-CICD MCP, project tg-bot-template, full 40-hex SHA.
  Read back run number, SHA, terminal status and all stages. GitHub-hosted checks
  and local tests are supplementary, never substitutes for the external gate.
- Tests: _work/venv/bin/python -m pytest; lint: _work/venv/bin/python -m ruff check .;
  syntax: _work/venv/bin/python -m compileall -q bot_template tests main.py.
- Recursive tools must exclude _work/ and legacy code. Test paths use isolated tmp DBs;
  never use data/template-v2.sqlite3 or old bot.db for tests.
