#!/usr/bin/env python3
"""Full DOM dump of the standalone captcha page — find the real slider markup."""
import time

from camoufox.sync_api import Camoufox

with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    page.goto("https://www.vseinstrumenti.ru/category/tsement-3432/", timeout=60000,
              wait_until="domcontentloaded")
    time.sleep(12)
    html = page.content()
    open("/tmp/vi_captcha_page.html", "w").write(html)
    dump = page.evaluate(
        """(() => [...document.querySelectorAll("div,span,button,canvas")].slice(0, 60).map(el => ({
             tag: el.tagName, id: el.id || "", cls: String(el.className).slice(0, 50),
             w: Math.round(el.getBoundingClientRect().width),
             h: Math.round(el.getBoundingClientRect().height)
           })))()"""
    )
    import json
    for row in dump:
        print(row)
    page.close()
