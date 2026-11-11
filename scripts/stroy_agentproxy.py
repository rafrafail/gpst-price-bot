#!/usr/bin/env python3
"""Confirm: is the proxy IP itself blocked? Test the same proxy from the
agent box (.61) where DIRECT worked — if proxy fails there too, the proxy IP
176.124.198.1 is blocked by stroylandiya, and prod has no working route."""
import time

from camoufox.sync_api import Camoufox

PROXY = {"server": "http://213.176.64.88:42567", "username": "user08",
         "password": "GEdhl9l55UlOgJmG"}

with Camoufox(headless=True, humanize=True, proxy=PROXY) as browser:
    page = browser.new_page()
    page.goto("https://ufa.stroylandiya.ru/catalog/sukhie-smesi/", timeout=60000,
              wait_until="domcontentloaded")
    time.sleep(9)
    body = page.inner_text("body")
    cards = page.evaluate("(() => document.querySelectorAll('.fb-product-card').length)()")
    limited = "временно ограничен" in body or "не прошел проверку" in body
    print(f"agent-box via proxy: cards={cards} limited={limited}")
    page.close()
