#!/usr/bin/env python3
"""Prod-vs-agent difference: try humanize=False + i_know_what_im_doing=True,
and also locale 'ru-RU' explicitly. Test 2 configs quickly."""
import time

from camoufox.sync_api import Camoufox

PROXY = {"server": "http://213.176.64.88:42567", "username": "user08",
         "password": "GEdhl9l55UlOgJmG"}
URL = "https://ufa.stroylandiya.ru/catalog/sukhie-smesi/"


def try_cfg(label, **kwargs):
    with Camoufox(headless=True, proxy=PROXY, **kwargs) as browser:
        page = browser.new_page()
        page.goto(URL, timeout=60000, wait_until="domcontentloaded")
        time.sleep(9)
        body = page.inner_text("body")
        cards = page.evaluate("(() => document.querySelectorAll('.fb-product-card').length)()")
        limited = "временно ограничен" in body or "не прошел проверку" in body
        print(f"{label}: cards={cards} limited={limited}")
        page.close()


try_cfg("no-humanize", humanize=False, i_know_what_im_doing=True)
try_cfg("ru-locale", humanize=True, locale="ru-RU")
