#!/usr/bin/env python3
"""Prod probe v2: stroylandiya body content — what page did we get? Longer wait."""
import time

from camoufox.sync_api import Camoufox

with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    page.goto("https://ufa.stroylandiya.ru/catalog/sukhie-smesi/", timeout=60000,
              wait_until="domcontentloaded")
    for wait_round in range(3):
        time.sleep(8)
        body = page.inner_text("body")
        cards = page.evaluate("(() => document.querySelectorAll('.fb-product-card').length)()")
        print(f"round {wait_round}: len={len(body)} cards={cards} title={page.title()[:60]}")
        if cards:
            break
    print("URL now:", page.url)
    page.close()
