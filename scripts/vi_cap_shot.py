#!/usr/bin/env python3
"""Capture a fresh captcha screenshot for angle estimation (no solving attempt)."""
import time

from camoufox.sync_api import Camoufox

with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    page.goto("https://www.vseinstrumenti.ru/category/tsement-3432/", timeout=60000,
              wait_until="domcontentloaded")
    time.sleep(10)
    box = page.locator(".captcha-main").bounding_box()
    if box:
        page.screenshot(path="/tmp/vi_cap_fresh.png",
                        clip={"x": box["x"] - 10, "y": box["y"] - 10,
                              "width": box["width"] + 20, "height": box["height"] + 20})
        print("cropped screenshot saved")
    else:
        page.screenshot(path="/tmp/vi_cap_fresh.png")
        print("full screenshot saved")
    page.close()
