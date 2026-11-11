#!/usr/bin/env python3
"""VI captcha solve attempt via slider drag with debug output, saved to /tmp/vi_debug.log."""
import re
import time

from camoufox.sync_api import Camoufox

URL = "https://www.vseinstrumenti.ru/category/tsement-3432/"

with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    page.goto(URL, timeout=60000, wait_until="domcontentloaded")
    time.sleep(10)
    for attempt in range(6):
        body = page.inner_text("body")
        if "ботом" not in body:
            html = page.content()
            open("/tmp/vi_fresh.html", "w").write(html)
            print(f"CLEAN at attempt {attempt}, products={len(re.findall('/product/', html))}")
            break
        info = page.evaluate(
            """(() => {
              const wrap = document.querySelector(".captcha-control-wrap");
              if (!wrap) return {missing: true};
              const kids = [...wrap.querySelectorAll("*")].map(k => {
                const kr = k.getBoundingClientRect();
                return {tag: k.tagName, cls: String(k.className).slice(0, 40), x: kr.x, y: kr.y, w: kr.width, h: kr.height};
              });
              return {kids};
            })()"""
        )
        print(f"attempt {attempt} info: {str(info)[:200]}")
        kids = (info or {}).get("kids") or []
        if not kids:
            time.sleep(6)
            continue
        # handle = the movable knob; likely the child with smallest width near left
        knob = min(kids, key=lambda k: k["w"])
        hx = knob["x"] + knob["w"] / 2
        hy = knob["y"] + knob["h"] / 2
        page.mouse.move(hx, hy)
        page.mouse.down()
        for i in range(1, 31):
            page.mouse.move(hx + i * 7, hy, steps=2)
            time.sleep(0.03)
        page.mouse.up()
        time.sleep(8)
    else:
        print("NEVER CLEAN")
