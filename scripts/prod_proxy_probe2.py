#!/usr/bin/env python3
"""Proxy probe v2: try https proxy schema for camoufox (socks/http with auth)."""
import time

from camoufox.sync_api import Camoufox

PROXY = "http://user08:GEdhl9l55UlOgJmG@213.176.64.88:42567"

with Camoufox(headless=True, humanize=True,
              proxy={"server": "http://213.176.64.88:42567",
                     "username": "user08",
                     "password": "GEdhl9l55UlOgJmG"}) as browser:
    page = browser.new_page()
    try:
        page.goto("https://ufa.stroylandiya.ru/catalog/sukhie-smesi/", timeout=60000,
                  wait_until="domcontentloaded")
        time.sleep(9)
        body = page.inner_text("body")
        limited = "временно ограничен" in body
        cards = page.evaluate("(() => document.querySelectorAll('.fb-product-card').length)()")
        print(f"via split-proxy: len={len(body)} limited={limited} cards={cards}")
    except Exception as exc:
        print(f"via split-proxy: ERROR {type(exc).__name__}: {str(exc)[:80]}")
    page.close()
