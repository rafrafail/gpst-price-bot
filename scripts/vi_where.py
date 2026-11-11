#!/usr/bin/env python3
"""What page are we actually on? Dump body text + check for the standalone captcha page."""
import time

from camoufox.sync_api import Camoufox

with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    page.goto("https://www.vseinstrumenti.ru/category/tsement-3432/", timeout=60000,
              wait_until="domcontentloaded")
    time.sleep(12)
    print("URL:", page.url)
    print("TITLE:", page.title())
    body = page.inner_text("body")
    print("BODY len:", len(body))
    print("BODY head:", body[:500].replace("\n", " | ")[:500])
    page.close()
