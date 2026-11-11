#!/usr/bin/env python3
"""Wait — first goto DID load the real page (title 'Сухие смеси')! The 6509-byte
'limited' page must have been served on the FIRST request, then the cookie let
us through. So: stroylandiya needs a retry-on-limited with reload."""
import time

from camoufox.sync_api import Camoufox

PROXY = {"server": "http://213.176.64.88:42567", "username": "user08",
         "password": "GEdhl9l55UlOgJmG"}

with Camoufox(headless=True, humanize=True, proxy=PROXY) as browser:
    page = browser.new_page()
    page.goto("https://ufa.stroylandiya.ru/catalog/sukhie-smesi/", timeout=60000,
              wait_until="domcontentloaded")
    time.sleep(8)
    print("first load title:", page.title()[:50])
    cards = page.evaluate("(() => document.querySelectorAll('.fb-product-card').length)()")
    print("first load cards:", cards)
    if not cards:
        page.reload(timeout=60000, wait_until="domcontentloaded")
        time.sleep(8)
        cards = page.evaluate("(() => document.querySelectorAll('.fb-product-card').length)()")
        print("after reload cards:", cards)
    page.close()
