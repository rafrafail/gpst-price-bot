#!/usr/bin/env python3
"""Inspect captcha DOM: does .captcha-control-wrap exist? What's inside #captcha_root?"""
import time

from camoufox.sync_api import Camoufox

with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    page.goto("https://www.vseinstrumenti.ru/category/tsement-3432/", timeout=60000,
              wait_until="domcontentloaded")
    time.sleep(10)
    dump = page.evaluate(
        """(() => {
          const root = document.querySelector("#captcha_root");
          return {
            hasRoot: !!root,
            rootChildren: root ? [...root.querySelectorAll("div,span,button")].slice(0, 30).map(el => ({
              tag: el.tagName, cls: String(el.className).slice(0, 50),
              w: el.getBoundingClientRect().width, h: el.getBoundingClientRect().height
            })) : [],
            controlWrapCount: document.querySelectorAll(".captcha-control-wrap").length,
          };
        })()"""
    )
    import json
    print(json.dumps(dump, ensure_ascii=False, indent=1)[:2000])
    page.close()
