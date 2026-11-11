#!/usr/bin/env python3
"""VI captcha: drag the exact slider handle (widest child of .captcha-control-wrap)."""
import re
import time

from camoufox.sync_api import Camoufox

with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    page.goto("https://www.vseinstrumenti.ru/category/tsement-3432/", timeout=60000,
              wait_until="domcontentloaded")
    time.sleep(8)
    for attempt in range(10):
        body = page.inner_text("body")
        if "ботом" not in body:
            print(f"clean at {attempt}")
            break
        info = page.evaluate(
            """(() => {
              const wrap = document.querySelector(".captcha-control-wrap");
              if (!wrap) return null;
              const r = wrap.getBoundingClientRect();
              const kids = [...wrap.querySelectorAll("*")].map(k => {
                const kr = k.getBoundingClientRect();
                return {tag: k.tagName, cls: String(k.className).slice(0, 30),
                        x: kr.x + kr.width / 2, y: kr.y + kr.height / 2, w: kr.width};
              });
              return {wrap: {x: r.x, y: r.y, w: r.width, h: r.height}, kids};
            })()"""
        )
        if not info:
            print("no wrap yet")
            time.sleep(6)
            continue
        handle = max(info["kids"], key=lambda k: k["w"]) if info["kids"] else None
        hx = handle["x"] if handle else info["wrap"]["x"] + 8
        hy = handle["y"] if handle else info["wrap"]["y"] + info["wrap"]["h"] / 2
        page.mouse.move(hx, hy)
        page.mouse.down()
        for i in range(1, 31):
            page.mouse.move(hx + i * 7, hy, steps=2)
            time.sleep(0.03)
        page.mouse.up()
        time.sleep(7)
        print(f"attempt {attempt}: dragged from {hx:.0f}")
    html = page.content()
    print("final: products=", len(re.findall("/product/", html)), "len=", len(html))
    page.close()
