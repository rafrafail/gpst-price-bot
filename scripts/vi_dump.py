#!/usr/bin/env python3
"""Check what VI browser html contains: JSON-LD count vs card markup."""
import time

from camoufox.sync_api import Camoufox

with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    page.goto("https://www.vseinstrumenti.ru/category/tsement-3432/", timeout=60000,
              wait_until="domcontentloaded")
    time.sleep(8)
    html = page.content()
    open("/tmp/vi_page.html", "w").write(html)
    import re
    print("len:", len(html))
    print("ld+json blocks:", html.count('application/ld+json'))
    print("product links:", len(re.findall(r'/product/', html)))
    m = re.search(r'"price"\s*:\s*"?(\d+)', html)
    print("json price hits:", len(re.findall(r'"price"\s*:\s*"?(\d+)', html)))
    page.close()
