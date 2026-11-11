#!/usr/bin/env python3
"""Both routes blocked from prod .45. Sources' decisions:
- stroylandiya: NO_ANSWER from prod (both direct and proxy IP blocked)
- ufacement: OK direct from prod (200 verified earlier)
- vseinstrumenti: captcha loop

Agent box .61 works fine for stroylandiya (111 offers). Plan: run the nightly
collect on the agent box via systemd timer (cron there), keep the bot on prod
reading the synced DB. But bot DB is on prod... Simplest honest architecture:
collector runs where sources are reachable; DB file lives on prod; sync the
SQLite over rsync after each collect on .61, bot reads it.

Set up: timer on agent box -> collect -> rsync data/prices.sqlite3 to prod.
"""
print("plan only")
