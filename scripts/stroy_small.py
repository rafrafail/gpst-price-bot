#!/usr/bin/env python3
"""251-byte page = JS challenge? Dump the small page content."""
import time

from camoufox.sync_api import Camoufox

PROXY = {"server": "http://213.176.64.88:42567", "username": "user08",
         "password": "GEdhl9l55UlOgJmG"}

with Camoufox(headless=True, humanize=True, proxy=PROXY) as browser:
    page = browser.new_page()
    page.goto("https://ufa.stroylandiya.ru/", timeout=60000, wait_until="domcontentloaded")
    time.sleep(12)
    print("title:", page.title()[:70])
    print("body repr:", repr(page.inner_text("body"))[:300])
    print("final url:", page.url)
    page.close()
