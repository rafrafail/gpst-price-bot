#!/usr/bin/env python3
"""Solve VI captcha: drag .captcha-control-button (50x50 knob) along the track.

The knob is 50x50, the track 275 wide -> ~225px of travel. The angle maps to
drag distance; try several distances with reload between fails.
"""
import re
import time

from camoufox.sync_api import Camoufox

URL = "https://www.vseinstrumenti.ru/category/tsement-3432/"


def is_captcha(page):
    return "ботом" in page.inner_text("body")


with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    page.goto(URL, timeout=60000, wait_until="domcontentloaded")
    time.sleep(10)
    for distance in (90, 130, 170, 60, 200, 110, 150, 40):
        if not is_captcha(page):
            break
        knob = page.locator(".captcha-control-button")
        box = knob.bounding_box()
        if not box:
            print("no knob box")
            time.sleep(6)
            continue
        hx = box["x"] + box["width"] / 2
        hy = box["y"] + box["height"] / 2
        page.mouse.move(hx, hy)
        page.mouse.down()
        steps = 20
        for i in range(1, steps + 1):
            page.mouse.move(hx + distance * i / steps, hy, steps=1)
            time.sleep(0.05)
        time.sleep(0.5)
        page.mouse.up()
        time.sleep(8)
        print(f"drag {distance}px -> captcha={is_captcha(page)}")
        if is_captcha(page):
            # reload to get a fresh image if still captcha
            page.reload(timeout=60000, wait_until="domcontentloaded")
            time.sleep(8)
    if not is_captcha(page):
        html = page.content()
        open("/tmp/vi_fresh.html", "w").write(html)
        print("CLEAN! products=", len(re.findall("/product/", html)), "len=", len(html))
    else:
        print("STILL CAPTCHA after all distances")
