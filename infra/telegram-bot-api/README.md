# Optional self-hosted Telegram Bot API

This directory is an **optional local transport** for one copy of the template.
It does not create a second bot and it never exposes the Bot API publicly: Docker
binds it only to `127.0.0.1:8081`.

## What is needed

- a Linux host with Docker Compose and outbound access to Telegram;
- the existing private application `.env` with `BOT_TOKEN` and the usual settings;
- `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` from
  [my.telegram.org](https://my.telegram.org), placed only in this directory's
  private `.env`.

The Bot API credentials are separate from the bot token. Do not commit either
`.env` file and do not put the token in a shell command or URL.

## Prepare the local server configuration

```bash
cd infra/telegram-bot-api
cp .env.example .env
# Fill TELEGRAM_API_ID and TELEGRAM_API_HASH in the private .env.
docker compose config -q
```

`docker compose config -q` validates without printing the resolved configuration,
which would otherwise contain `TELEGRAM_API_HASH`. It must complete before the
cloud migration. **Do not start the local container yet.** A persistent volume can
contain a previous webhook, which the Bot API server restores on startup. The
compose file uses the tested `aiogram/telegram-bot-api:10.3` image and `--local`
mode via `TELEGRAM_LOCAL=true`. Its data volume is private to the container; the
template does not currently download user media to disk, so it does not require a
host file-volume adapter.

## Switch safely from cloud mode

Only one `getUpdates` consumer may use a bot token. Never run cloud and local
processes together and do not use an automatic health-check fallback.

1. Stop the currently running bot process.
2. From the application root, execute once:

   ```bash
   .venv/bin/python main.py --logout-cloud
   ```

   The command reads `BOT_TOKEN` only from the private `.env`, takes the normal
   database lock, and calls the official cloud `logOut` method. It does not start
   the bot or print the token. Telegram permits an immediate local login only
   after this call succeeds.
3. Start the local Bot API container only now:

   ```bash
   cd infra/telegram-bot-api
   docker compose up -d
   ```

4. In the application's private `.env`, set:

   ```dotenv
   TELEGRAM_TRANSPORT=self_hosted
   LOCAL_BOT_API_URL=http://127.0.0.1:8081
   ```

5. Start exactly one application process. On self-hosted mode it first calls local
   `getMe`; if that fails it stops before polling or delivery begins.

To return to cloud mode, stop the self-hosted bot process **and** stop the local
Bot API server before changing application settings:

```bash
cd infra/telegram-bot-api
docker compose down  # Do not add -v: it would delete the local server data.
```

After `--logout-cloud`, Telegram blocks cloud login only until 10 minutes have
elapsed from that successful call. If that interval has not yet passed, wait for
it, set `TELEGRAM_TRANSPORT=cloud`, then start exactly one bot process. Do not
run `--logout-cloud` for this direction.

## Boundaries

- The local API is intentionally loopback-only. A remote `LOCAL_BOT_API_URL` is
  rejected by configuration validation.
- This minimal compose configuration does not configure a proxy, TLS, systemd or
  automatic failover. Those are deployment-specific concerns and must not be
  copied from another bot without their own review.
- Switching transport is an operational action, not a deploy. Test it first with
  a separate bot token and an isolated database.
