#!/usr/bin/env python3
"""VI captcha solver: fresh Camoufox session via python playwright, navigate to
the cement category, wait for captcha (if any), drag the slider handle with a
real mouse, verify access, then extract product cards.

Real Playwright mouse = trusted events, unlike synthetic JS ones.
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

URL = "https://www.vseinstrumenti.ru/category/tsement-3432/"
PROXY = os.environ.get("COLLECT_PROXY") or "http://user08:GEdhl9l55UlOgJmG@213.176.64.88:42567"


def main():
    from camoufox.sync_api import Camoufox

    with Camoufox(headless=True, geoip=True, humanize=True, proxy={"server": PROXY}) as browser:
        page = browser.new_page()
        page.goto(URL, timeout=90000, wait_until="domcontentloaded")
        time.sleep(5)
        for attempt in range(12):
            body = page.inner_text("body")
            if "ботом" not in body:
                print(f"attempt {attempt}: no captcha, page OK")
                break
            print(f"attempt {attempt}: captcha present, trying slider drag")
            handle = page.locator(".captcha-control-wrap span, .captcha-control-wrap div").last
            try:
                box = handle.bounding_box()
            except Exception:
                box = None
            if not box:
                wrap = page.locator(".captcha-control-wrap")
                wbox = wrap.bounding_box()
                if not wbox:
                    time.sleep(5)
                    continue
                box = {"x": wbox["x"] + 5, "y": wbox["y"] + wbox["height"] / 2 - 5, "width": 10, "height": 10}
            hx = box["x"] + box["width"] / 2
            hy = box["y"] + box["height"] / 2
            page.mouse.move(hx, hy)
            page.mouse.down()
            for i in range(1, 21):
                page.mouse.move(hx + i * 12, hy, steps=2)
                time.sleep(0.05)
            page.mouse.up()
            time.sleep(6)
        else:
            print("CAPTCHA UNSOLVED after retries")
            return 1

        time.sleep(3)
        title = page.title()
        print("title:", title)
        cards = page.evaluate(
            """(() => {
              const out = [];
              document.querySelectorAll("a[href*='/product/']").forEach(a => {
                const name = (a.getAttribute("title") || a.textContent || "").trim();
                if (name && !out.some(o => o.name === name)) out.push({name, url: a.href});
              });
              return out.slice(0, 60);
            })()"""
        )
        print("cards:", len(cards))
        for c in cards[:10]:
            print("-", c["name"][:70])
        json.dump(cards, open("/tmp/vi_cards.json", "w"), ensure_ascii=False, indent=1)
        return 0


if __name__ == "__main__":
    sys.exit(main())
