#!/usr/bin/env python3
"""Check BOT_TOKEN shape in prod .env without printing the value."""
import re
from pathlib import Path

from dotenv import dotenv_values

cfg = dotenv_values("/home/user/projects/gpst_price_bot/.env")
tok = cfg.get("BOT_TOKEN", "")
bad = [ch for ch in tok if not re.fullmatch(r"[0-9A-Za-z:_-]", ch)]
print("token shape ok:", bool(re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", tok)))
print("len:", len(tok))
print("invalid chars:", bad)
