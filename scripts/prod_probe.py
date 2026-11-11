#!/usr/bin/env python3
"""Probe stroylandiya/ufacement accessibility from prod via Camoufox."""
import time

from camoufox.sync_api import Camoufox

with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    for label, url in [
        ("stroylandiya", "https://ufa.stroylandiya.ru/catalog/sukhie-smesi/"),
        ("ufacement", "https://ufacement.ru/catalog/cement-v-meshkah/"),
    ]:
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            time.sleep(8)
            body = page.inner_text("body")
            limited = "временно ограничен" in body
            cards = page.evaluate("(() => document.querySelectorAll('.fb-product-card').length)()")
            rub = body.count("руб") + body.count("₽")
            print(f"{label}: len={len(body)} limited={limited} cards={cards} rubmarks={rub}")
        except Exception as exc:
            print(f"{label}: ERROR {type(exc).__name__}")
    page.close()
