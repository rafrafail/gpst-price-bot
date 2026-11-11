#!/usr/bin/env python3
"""Retry Camoufox direct (no proxy) — dev host reaches VI directly (got 403 on
curl UA but the CamoFox browser earlier loaded the real category page)."""
import json
import sys
import time

URL = "https://www.vseinstrumenti.ru/category/tsement-3432/"


def main():
    from camoufox.sync_api import Camoufox

    with Camoufox(headless=True, humanize=True) as browser:
        page = browser.new_page()
        page.goto(URL, timeout=90000, wait_until="domcontentloaded")
        time.sleep(6)
        for attempt in range(10):
            body = page.inner_text("body")
            if "ботом" not in body:
                print(f"attempt {attempt}: page OK, title: {page.title()}")
                break
            print(f"attempt {attempt}: captcha, dragging slider")
            wrap = page.locator(".captcha-control-wrap")
            wbox = wrap.bounding_box()
            if not wbox:
                time.sleep(6)
                continue
            hx = wbox["x"] + 8
            hy = wbox["y"] + wbox["height"] / 2
            page.mouse.move(hx, hy)
            page.mouse.down()
            for i in range(1, 25):
                page.mouse.move(hx + i * 8, hy, steps=3)
                time.sleep(0.04)
            page.mouse.up()
            time.sleep(7)
        else:
            print("CAPTCHA UNSOLVED")
            return 1
        time.sleep(3)
        cards = page.evaluate(
            """(() => {
              const out = [];
              document.querySelectorAll("a[href*='/product/']").forEach(a => {
                const name = (a.getAttribute("title") || a.textContent || "").trim();
                if (name && !out.some(o => o.name === name)) out.push({name, url: a.href});
              });
              return out.slice(0, 80);
            })()"""
        )
        print("cards:", len(cards))
        for c in cards[:8]:
            print("-", c["name"][:70])
        json.dump(cards, open("/tmp/vi_cards.json", "w"), ensure_ascii=False, indent=1)
        return 0


if __name__ == "__main__":
    sys.exit(main())
