#!/usr/bin/env python3
"""Append COLLECT_PROXY to prod .env (value from PROXY_URL line), no echo of it."""
import re
from pathlib import Path

env_path = Path("/home/user/projects/gpst_price_bot/.env")
lines = env_path.read_text().splitlines()
proxy = next((l.split("=", 1)[1] for l in lines if l.startswith("PROXY_URL=")), None)
if not proxy:
    raise SystemExit("no PROXY_URL in .env to reuse")
if not any(l.startswith("COLLECT_PROXY=") for l in lines):
    lines.append(f"COLLECT_PROXY={proxy}")
env_path.write_text("\n".join(lines) + "\n")
env_path.chmod(0o600)
keys = [l.split("=")[0] for l in lines if re.match(r"^[A-Z_]+=", l)]
print("env keys:", keys)
