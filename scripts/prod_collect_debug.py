#!/usr/bin/env python3
"""Debug: run the actual collector for stroylandiya only on prod, verbose."""
import json
import time

from camoufox.sync_api import Camoufox

from features.prices.collector.fetch import BrowserPool
from features.prices.collector.parsers import parse_stroylandiya
from features.prices.collector.sources import SOURCES

src = next(s for s in SOURCES if s["key"] == "stroylandiya")

with BrowserPool() as pool:
    page = pool.page(src["pages"][0][1], wait_s=src.get("wait_s", 7))
    print("ok:", page.ok, "via:", page.via, "err:", page.error, "html_len:", len(page.html or ""))
    if page.ok and page.html:
        offers = parse_stroylandiya(page.html)
        print("parsed:", len(offers))
        for o in offers[:4]:
            print(" ", o["price"], "|", o["name"][:60])
