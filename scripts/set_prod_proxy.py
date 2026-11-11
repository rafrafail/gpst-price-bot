#!/usr/bin/env python3
"""Set PROXY_URL in prod .env to the cleaned value from /tmp/price_bot_proxy_value, restart bot."""
import subprocess
from pathlib import Path

proxy = Path("/tmp/price_bot_proxy_value").read_text().strip().replace("`", "").strip()
assert proxy.startswith("http://") and ":" in proxy.split("@")[-1], "bad proxy shape"

env_path = Path("/home/user/projects/gpst_price_bot/.env")
lines = [l for l in env_path.read_text().splitlines() if not l.startswith("PROXY_URL=")]
lines.append(f"PROXY_URL={proxy}")
env_path.write_text("\n".join(lines) + "\n")
env_path.chmod(0o600)

subprocess.run(["systemctl", "restart", "gpst-price-bot.service"], check=True)
print("proxy set, length:", len(proxy), "- restarted")
