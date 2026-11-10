#!/usr/bin/env python3
"""Extract PROXY_URL value from the Obsidian infra note without printing it."""
import re
from pathlib import Path

note = Path("/home/rafail/Documents/Obsidian Vault/coding/tt analytics bot.md")
text = note.read_text(encoding="utf-8")
match = re.search(r"https?://\S*213\.176\.64\.88:42567\S*", text)
if not match:
    raise SystemExit("proxy url not found in note")
value = match.group(0).rstrip(").»,\"'")
target = Path("/tmp/price_bot_proxy_url")
target.write_text(value + "\n", encoding="utf-8")
target.chmod(0o600)
print("saved to /tmp/price_bot_proxy_url, length:", len(value))
