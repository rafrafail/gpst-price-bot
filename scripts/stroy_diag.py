#!/usr/bin/env python3
"""stroylandiya 503 pattern check: retry from agent box Camoufox again — is it per-session?"""
import time

from camoufox.sync_api import Camoufox

with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    for label, url in [
        ("home", "https://ufa.stroylandiya.ru/"),
        ("catalog", "https://ufa.stroylandiya.ru/catalog/sukhie-smesi/"),
    ]:
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            time.sleep(9)
            body = page.inner_text("body")
            cards = page.evaluate("(() => document.querySelectorAll('.fb-product-card').length)()")
            print(f"{label}: len={len(body)} limited={'временно ограничен' in body} cards={cards}")
        except Exception as e:
            print(f"{label}: {type(e).__name__}")
    page.close()
