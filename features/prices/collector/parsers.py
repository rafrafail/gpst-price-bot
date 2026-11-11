"""Parsers: one per source, pure functions html -> offer dicts.

Verified live 2026-11-11:
  vseinstrumenti  — category page, .product cards, 40 cards/cement
  stroylandiya    — ufa.stroylandiya.ru, .fb-product-card, 10 cards/cement
  ufacement       — ufacement.ru, li: h2.item_name + span "цена NNN руб/меш"
"""
from __future__ import annotations

import re
from html import unescape

from .db import norm_name

CITY_UFA = "Уфа"


def _strip_tags(fragment: str) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", fragment)).strip()


def _price_int(raw: str) -> int | None:
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


def parse_vseinstrumenti(html: str) -> list[dict]:
    """VI category pages embed JSON-LD with product offers; fallback regex on cards."""
    offers: list[dict] = []
    seen: set[str] = set()
    # JSON-LD "<script type=application/ld+json> ... "offerPrice" ..."
    for match in re.finditer(r'"name"\s*:\s*"([^"]{8,200})".*?"price"\s*:\s*"?(\d+)"?', html, re.S):
        name, price = match.group(1), match.group(2)
        key = norm_name(name)
        if key in seen:
            continue
        seen.add(key)
        offers.append({
            "name": name,
            "category": "Цемент",
            "price": int(price),
            "unit": "шт",
            "city": CITY_UFA,
            "url": "https://www.vseinstrumenti.ru/",
        })
    if offers:
        return offers
    # fallback: link-title followed by ₽ paragraph
    for match in re.finditer(r'title="([^"]{10,200})"[^>]*>.{0,800}?(\d[\d\s]{2,8})\s*(?:₽|руб)', html, re.S):
        name, price = match.group(1), match.group(2)
        key = norm_name(name)
        if key in seen or not re.search(r"(цемент|смес|бетон)", name, re.I):
            continue
        seen.add(key)
        val = _price_int(price)
        if val is None:
            continue
        offers.append({
            "name": name.strip(),
            "category": "Цемент",
            "price": val,
            "unit": "шт",
            "city": CITY_UFA,
            "url": "https://www.vseinstrumenti.ru/",
        })
    return offers


def parse_stroylandiya(html: str) -> list[dict]:
    """fb-product-card blocks: title-inner A + price text in the card div.

    Category is derived from the page URL (parsers see only html, so we accept
    an optional category via closure in collect.py; default 'Стройматериалы').
    """
    offers: list[dict] = []
    seen: set[str] = set()
    pattern = re.compile(
        r'fb-product-card__title-inner[^>]*href="([^"]+)"[^>]*>([^<]{5,150})</a>'
        r'.{0,3000}?(\d[\d\s]{2,8})\s*(?:руб|₽)',
        re.S,
    )
    for match in pattern.finditer(html):
        url, name, price = match.group(1), _strip_tags(match.group(2)), match.group(3)
        key = norm_name(name)
        if key in seen:
            continue
        val = _price_int(price)
        if val is None:
            continue
        seen.add(key)
        if not url.startswith("http"):
            url = "https://ufa.stroylandiya.ru" + (url if url.startswith("/") else "/" + url)
        offers.append({
            "name": name,
            "category": "Стройматериалы",
            "price": val,
            "unit": "шт",
            "city": CITY_UFA,
            "url": url,
        })
    return offers


def parse_ufacement(html: str) -> list[dict]:
    """li blocks: h2.item_name ... цена NNN руб/ед."""
    offers: list[dict] = []
    seen: set[str] = set()
    pattern = re.compile(
        r"item_name\">([^<]{5,150})</h2>.{0,2500}?цена\s*(\d[\d\s]{0,8})\s*руб/([а-яё.]+)",
        re.S,
    )
    for match in pattern.finditer(html):
        name, price, unit = match.group(1).strip(), match.group(2), match.group(3).rstrip(".")
        key = norm_name(name)
        if key in seen:
            continue
        val = _price_int(price)
        if val is None:
            continue
        seen.add(key)
        slug = re.sub(r"[^a-zа-яё0-9]+", "-", name.lower()).strip("-")[:60]
        offers.append({
            "name": name,
            "category": "Цемент",
            "price": val,
            "unit": unit,
            "city": CITY_UFA,
            "url": f"https://ufacement.ru/catalog/cement-v-meshkah/{slug}/",
        })
    return offers
