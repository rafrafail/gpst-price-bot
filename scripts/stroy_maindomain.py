#!/usr/bin/env python3
"""With proxy egress confirmed (176.124.198.1), why does stroylandiya show
'access limited'? The proxy IP itself is probably blocked by stroylandiya
(same proxy used before). Try: proxy for stroylandiya + retry;
ufacement direct (worked earlier direct 200)."""
import time

from camoufox.sync_api import Camoufox

PROXY = {"server": "http://213.176.64.88:42567", "username": "user08",
         "password": "GEdhl9l55UlOgJmG"}

with Camoufox(headless=True, humanize=True, proxy=PROXY) as browser:
    page = browser.new_page()
    # confirm the limited page content
    page.goto("https://ufa.stroylandiya.ru/catalog/sukhie-smesi/", timeout=60000,
              wait_until="domcontentloaded")
    time.sleep(8)
    print("title:", page.title()[:60])
    # try the main domain (different vhost?)
    page.goto("https://stroylandiya.ru/catalog/sukhie-smesi/", timeout=60000,
              wait_until="domcontentloaded")
    time.sleep(8)
    body = page.inner_text("body")
    cards = page.evaluate("(() => document.querySelectorAll('.fb-product-card').length)()")
    print("main domain: len=", len(body), "limited=", "временно ограничен" in body, "cards=", cards)
    page.close()
