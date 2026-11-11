#!/usr/bin/env python3
"""Nord: proxy stroylandiya through the Telegram proxy (user08) from prod."""
import time

from camoufox.sync_api import Camoufox

PROXY = "http://user08:GEdhl9l55UlOgJmG@213.176.64.88:42567"

with Camoufox(headless=True, humanize=True, proxy={"server": PROXY}) as browser:
    page = browser.new_page()
    for label, url in [
        ("stroylandiya", "https://ufa.stroylandiya.ru/catalog/sukhie-smesi/"),
    ]:
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            time.sleep(9)
            body = page.inner_text("body")
            limited = "временно ограничен" in body
            cards = page.evaluate("(() => document.querySelectorAll('.fb-product-card').length)()")
            print(f"{label} via proxy: len={len(body)} limited={limited} cards={cards}")
        except Exception as exc:
            print(f"{label} via proxy: ERROR {type(exc).__name__}: {str(exc)[:80]}")
    page.close()
