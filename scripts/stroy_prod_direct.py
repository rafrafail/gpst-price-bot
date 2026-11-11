#!/usr/bin/env python3
"""TLS/HTTP2 or DNS difference? Compare exactly: fetch via proxy from agent
box — works; from prod — blocked. Only difference is the machine/camoufox
build. Check camoufox build on prod vs agent and try direct from prod with
the 156 build (no proxy, direct .45 IP was 503 on curl, but try in browser)."""
import time

from camoufox.sync_api import Camoufox

URL = "https://ufa.stroylandiya.ru/catalog/sukhie-smesi/"

# direct from prod (no proxy), with the browser — maybe anti-bot only blocks
# proxy/datacenter-IP ranges and plain curl, not real browser on .45
with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    page.goto(URL, timeout=60000, wait_until="domcontentloaded")
    time.sleep(9)
    body = page.inner_text("body")
    cards = page.evaluate("(() => document.querySelectorAll('.fb-product-card').length)()")
    limited = "временно ограничен" in body or "не прошел проверку" in body
    print(f"prod direct browser: cards={cards} limited={limited}")
    page.close()
