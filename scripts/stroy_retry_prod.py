#!/usr/bin/env python3
"""Different proxy exit: check if the proxy rotates users (user01/user4415903).
Try the old user01 creds? No - dead per notes. Instead: retry stroylandiya via
proxy several times from prod — the block may be probabilistic per request."""
import time

from camoufox.sync_api import Camoufox

PROXY = {"server": "http://213.176.64.88:42567", "username": "user08",
         "password": "GEdhl9l55UlOgJmG"}
URL = "https://ufa.stroylandiya.ru/catalog/sukhie-smesi/"

results = []
for attempt in range(4):
    with Camoufox(headless=True, humanize=True, proxy=PROXY) as browser:
        page = browser.new_page()
        page.goto(URL, timeout=60000, wait_until="domcontentloaded")
        time.sleep(9)
        body = page.inner_text("body")
        cards = page.evaluate("(() => document.querySelectorAll('.fb-product-card').length)()")
        results.append(cards)
        print(f"attempt {attempt}: cards={cards}")
        page.close()
        time.sleep(10)
print("summary:", results)
