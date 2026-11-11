#!/usr/bin/env python3
"""Retry stroylandiya from agent box (worked 40 min ago): maybe rate-limited, wait and retry."""
import time

from camoufox.sync_api import Camoufox

for attempt in range(3):
    try:
        with Camoufox(headless=True, humanize=True) as browser:
            page = browser.new_page()
            page.goto("https://ufa.stroylandiya.ru/catalog/sukhie-smesi/", timeout=60000,
                      wait_until="domcontentloaded")
            time.sleep(10)
            body = page.inner_text("body")
            limited = "временно ограничен" in body
            cards = page.evaluate("(() => document.querySelectorAll('.fb-product-card').length)()")
            print(f"attempt {attempt}: len={len(body)} limited={limited} cards={cards}")
            if cards:
                print("RECOVERED")
                break
            page.close()
    except Exception as e:
        print(f"attempt {attempt}: {type(e).__name__}")
    time.sleep(30)
