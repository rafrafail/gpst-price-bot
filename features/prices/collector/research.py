"""Live research: enumerate candidate sources for construction material prices
in Ufa, verify each (reachable? prices visible? anti-bot?), and write the
report. Uses requests first; CamoFox (via playwright+camoufox) as browser tier.

Run:  python -m features.prices.collector.research
"""
import json
import time
from pathlib import Path

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}

CANDIDATES = [
    # (name, test_url, notes)
    ("vseinstrumenti", "https://www.vseinstrumenti.ru/category/tsement-3432/", "federal, Ufa branch; 403 on curl UA, ok via real browser"),
    ("petrovich", "https://ufa.petrovich.ru/catalog/tsement/", "federal DIY"),
    ("megastroy", "https://ufa.megastroy.com/catalog/tsement/", "Ufa chain"),
    ("saturn_r", "https://saturn-r.ru/catalog/sukhie_smesi/tsement/", "Ufa chain"),
    ("leroy_lemanapro", "https://ufa.lemanapro.ru/catalog/tsement/", "Lemana PRO Ufa"),
    ("maxidom", "https://ufa.maxidom.ru/catalog/tsement/", "federal DIY"),
    ("baucenter", "https://ufa.baucenter.ru/catalog/tsement/", "federal DIY"),
    ("satu", "https://ufa.satu.ru/catalog/stroitelnye-materialy/tsement/", "aggregator Ufa"),
    ("tiu", "https://ufa.tiu.ru/Stroitelnye-materialy", "aggregator Ufa"),
    ("prom", "https://ufa.prom.ua/Tsement", "aggregator Ufa"),
]


def check(name: str, url: str) -> dict:
    result: dict = {"name": name, "url": url}
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        result["http_status"] = resp.status_code
        text = resp.text
        result["len"] = len(text)
        # price markers commonly used by RU e-commerce
        markers = {
            "roble": "руб" in text or "₽" in text,
            "price_class": any(c in text for c in ("price", "product-price", "cost")),
            "product_links": "/product/" in text or "/catalog/" in text,
            "captcha": any(k in text.lower() for k in ("captcha", "роботом", "подтвердите")),
        }
        result["markers"] = markers
        result["verdict"] = (
            "OK-html" if resp.status_code == 200 and markers["roble"]
            else "BLOCKED" if resp.status_code in (403, 401, 429)
            else "NO-PRICES" if resp.status_code == 200
            else f"HTTP-{resp.status_code}"
        )
    except requests.RequestException as exc:
        result["http_status"] = None
        result["error"] = type(exc).__name__
        result["verdict"] = "UNREACHABLE"
    return result


def main() -> None:
    rows = []
    for name, url, note in CANDIDATES:
        row = check(name, url)
        row["note"] = note
        rows.append(row)
        print(f"{name:16} {str(row.get('http_status')):>5}  {row['verdict']}")
        time.sleep(2)  # polite delay
    out = Path("data/research/sources_check.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = [r["name"] for r in rows if r["verdict"] == "OK-html"]
    blocked = [r["name"] for r in rows if r["verdict"] == "BLOCKED"]
    print("\nOK (plain html):", ok)
    print("BLOCKED (need browser):", blocked)


if __name__ == "__main__":
    main()
