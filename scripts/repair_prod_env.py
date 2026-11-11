#!/usr/bin/env python3
"""Repair prod .env: ensure single real BOT_TOKEN, PROXY_URL from dev note, PRICE_DATABASE_PATH."""
import re
import subprocess
from pathlib import Path

env_path = Path("/home/user/projects/gpst_price_bot/.env")
proxy = Path("/tmp/price_bot_proxy_value").read_text().strip()

lines = env_path.read_text().splitlines()
out = []
seen_token = False
for line in lines:
    if line.startswith("BOT_TOKEN="):
        if seen_token:
            continue
        seen_token = True
        out.append(line)
        continue
    if line.startswith(("PROXY_URL=", "PRICE_DATABASE_PATH=")):
        continue
    out.append(line)

if not seen_token or not re.fullmatch(r"BOT_TOKEN=[0-9]+:[A-Za-z0-9_-]+", out[[i for i, l in enumerate(out) if l.startswith("BOT_TOKEN=")][0]]):
    raise SystemExit("no valid BOT_TOKEN line found, aborting")

out.append(f"PROXY_URL={proxy}")
out.append("PRICE_DATABASE_PATH=/home/user/projects/gpst_price_bot/data/prices.sqlite3")

env_path.write_text("\n".join(out) + "\n")
env_path.chmod(0o600)

keys = [l.split("=")[0] for l in env_path.read_text().splitlines() if re.match(r"^[A-Z_]+=", l)]
print("keys:", keys)
subprocess.run(["systemctl", "restart", "gpst-price-bot.service"], check=True)
print("restarted")
