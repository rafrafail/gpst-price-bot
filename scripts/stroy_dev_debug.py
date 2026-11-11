#!/usr/bin/env python3
"""Debug stroylandiya parsing from dev server: fetch one page, dump html length and card count."""
import time

from camoufox.sync_api import Camoufox

with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    page.goto("https://ufa.stroylandiya.ru/catalog/sukhie-smesi/", timeout=60000,
              wait_until="domcontentloaded")
    time.sleep(8)
    body = page.inner_text("body")
    print("body len:", len(body), "| captcha:", "ботом" in body, "| city hint:", "Уфа" in body)
    cards = page.evaluate("(() => document.querySelectorAll('.fb-product-card').length)()")
    print("cards:", cards)
    html = page.content()
    print("html len:", len(html), "| title-inner count:", html.count("fb-product-card__title-inner"))
    open("/tmp/stroy_dev.html", "w").write(html)
    page.close()
