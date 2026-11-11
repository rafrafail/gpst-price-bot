#!/usr/bin/env python3
"""The 'Доступ ограничен' page: does it set a cookie on first visit, then the
SUBPAGE works? In maindomain.py the SECOND goto (stroylandiya.ru main domain)
returned 40 cards. Here: goto / then the catalog page."""
import time

from camoufox.sync_api import Camoufox

PROXY = {"server": "http://213.176.64.88:42567", "username": "user08",
         "password": "GEdhl9l55UlOgJmG"}

with Camoufox(headless=True, humanize=True, proxy=PROXY) as browser:
    page = browser.new_page()
    page.goto("https://ufa.stroylandiya.ru/", timeout=60000, wait_until="domcontentloaded")
    time.sleep(9)
    body = page.inner_text("body")
    print("home: limited=", "временно ограничен" in body, "len=", len(body))
    page.goto("https://ufa.stroylandiya.ru/catalog/sukhie-smesi/", timeout=60000,
              wait_until="domcontentloaded")
    time.sleep(9)
    body = page.inner_text("body")
    cards = page.evaluate("(() => document.querySelectorAll('.fb-product-card').length)()")
    print("catalog: limited=", "временно ограничен" in body, "len=", len(body), "cards=", cards)
    page.close()
