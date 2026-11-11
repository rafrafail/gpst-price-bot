#!/usr/bin/env python3
"""Try CamoFox's higher-level action API for the slider drag.

Routes seen in the plugin: /tabs/{id}/click {ref|selector}, /tabs/{id}/type,
/tabs/{id}/scroll, /tabs/{id}/navigate. No raw mouse route. So: use click
on the slider track at increasing fractional positions? Click won't drag.

Honest fallback: try Playwright via the python camoufox package directly
(separate browser, fresh session, no server dependency). Install check:
python -c "import playwright" — camoufox venv has playwright? Try.
"""
import importlib.util
import json
import subprocess
import sys

for mod in ("playwright", "camoufox"):
    spec = importlib.util.find_spec(mod)
    print(mod, "->", "OK" if spec else "MISSING")

try:
    from playwright.sync_api import sync_playwright
    print("playwright sync_api import OK")
except Exception as e:
    print("playwright import failed:", e)
