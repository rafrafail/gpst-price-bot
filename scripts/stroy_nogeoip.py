#!/usr/bin/env python3
"""Puzzle: same proxy, agent-box OK, prod blocked. Fingerprint differences?
Prod runs camoufox fetched with older 156 build first — check which build
prod actually launched, and try geoip=False (GeoIP DB absent on prod?)."""
import time

from camoufox.sync_api import Camoufox

PROXY = {"server": "http://213.176.64.88:42567", "username": "user08",
         "password": "GEdhl9l55UlOgJmG"}

with Camoufox(headless=True, humanize=True, proxy=PROXY, geoip=False) as browser:
    page = browser.new_page()
    page.goto("https://ufa.stroylandiya.ru/catalog/sukhie-smesi/", timeout=60000,
              wait_until="domcontentloaded")
    time.sleep(9)
    body = page.inner_text("body")
    cards = page.evaluate("(() => document.querySelectorAll('.fb-product-card').length)()")
    limited = "временно ограничен" in body or "не прошел проверку" in body
    print(f"prod geoip=False: cards={cards} limited={limited}")
    page.close()
