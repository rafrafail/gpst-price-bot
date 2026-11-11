#!/usr/bin/env python3
"""Expand stroylandiya categories: dry mixes, bricks, rebar, timber, insulation...
Probe which category pages render fb-product-card with prices."""
import time

from camoufox.sync_api import Camoufox

CATALOG = [
    ("sukhie_smesi", "https://ufa.stroylandiya.ru/catalog/sukhie-smesi/"),
    ("pesok_beton", "https://ufa.stroylandiya.ru/catalog/tsement/"),
    ("kirpich", "https://ufa.stroylandiya.ru/catalog/kirpich/"),
    ("armatura", "https://ufa.stroylandiya.ru/catalog/armatura/"),
    ("brus", "https://ufa.stroylandiya.ru/catalog/brus/"),
    ("uteplitel", "https://ufa.stroylandiya.ru/catalog/uteplitel/"),
    ("gipsokarton", "https://ufa.stroylandiya.ru/catalog/gipsokarton/"),
    ("krovelya", "https://ufa.stroylandiya.ru/catalog/krovelnye-materialy/"),
    ("truba", "https://ufa.stroylandiya.ru/catalog/truby/"),
    ("shifer", "https://ufa.stroylandiya.ru/catalog/shifer/"),
]

with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    for name, url in CATALOG:
        try:
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            time.sleep(7)
            cards = page.evaluate(
                "(() => document.querySelectorAll('.fb-product-card').length)()"
            )
            prices = page.evaluate(
                "(() => (document.body.innerText.match(/\\d[\\d\\s]{2,8}\\s*(?:руб|₽)/g) || []).length)()"
            )
            print(f"{name:15} cards={cards:4} prices={prices:4}")
        except Exception as exc:
            print(f"{name:15} ERROR {type(exc).__name__}")
        time.sleep(2)
    page.close()
