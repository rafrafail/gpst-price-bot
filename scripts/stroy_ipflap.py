#!/usr/bin/env python3
"""Check whether stroylandiya block is per-IP: agent box (.61) worked in Camoufox,
dev (.62) blocked. Confirm .61 works right now, twice in a row (anti-flake)."""
import time

from camoufox.sync_api import Camoufox

with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    for run in range(2):
        page.goto("https://ufa.stroylandiya.ru/catalog/sukhie-smesi/", timeout=60000,
                  wait_until="domcontentloaded")
        time.sleep(8)
        cards = page.evaluate("(() => document.querySelectorAll('.fb-product-card').length)()")
        limited = "временно ограничен" in page.inner_text("body")
        print(f"run {run}: cards={cards} limited={limited}")
    page.close()
