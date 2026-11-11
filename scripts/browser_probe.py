#!/usr/bin/env python3
"""Probe candidate sources through Camoufox browser tier.

For each candidate: load page, wait, extract (name, price) pairs with a
generic heuristic, print verdict. No DB writes — research only.
"""
import json
import sys
import time

from camoufox.sync_api import Camoufox

CANDIDATES = [
    ("megastroy", "https://ufa.megastroy.com/catalog/tsement-240/"),
    ("megastroy_alt", "https://ufa.megastroy.com/"),
    ("saturn_r", "https://saturn-r.ru/catalog/sukhie_smesi/tsement/"),
    ("saturn_r_alt", "https://saturn-r.ru/"),
]


def probe(browser, name: str, url: str) -> dict:
    page = browser.new_page()
    result: dict = {"name": name, "url": url}
    try:
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        time.sleep(4)
        result["title"] = page.title()[:100]
        body = page.inner_text("body")
        result["len"] = len(body)
        result["captcha"] = "ботом" in body or "captcha" in body.lower()
        result["has_rub"] = "₽" in body or "руб" in body
        result["price_count"] = body.count("₽") + body.count("руб")
        # try generic card extraction
        cards = page.evaluate(
            """(() => {
              const out = [];
              document.querySelectorAll("a[href]").forEach(a => {
                const t = (a.getAttribute("title") || a.textContent || "").trim();
                if (t.length > 15 && /цемент/i.test(t) && out.length < 5) out.push(t.slice(0, 80));
              });
              return out;
            })()"""
        )
        result["cement_links"] = cards
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:100]}"
    finally:
        page.close()
    return result


def main() -> int:
    with Camoufox(headless=True, humanize=True) as browser:
        rows = []
        for name, url in CANDIDATES:
            row = probe(browser, name, url)
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False)[:300])
            time.sleep(3)
        json.dump(rows, open("/tmp/browser_probe.json", "w"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
