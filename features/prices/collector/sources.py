"""Source registry: keys, urls, parsers, browser flags.

Live-verified 2026-11-11 (night shift):
  stroylandiya  — ufa.stroylandiya.ru, 9 categories, fb-product-card, ~200 offers
  ufacement     — ufacement.ru, 6 cement offers, li/h2.item_name markup
  vseinstrumenti — blocked by persistent rotate-captcha on this IP since ~01:00;
                   kept active: collector marks it "no_answer" when blocked.
"""
from .parsers import parse_stroylandiya, parse_ufacement, parse_vseinstrumenti

UFA = "Уфа"

SOURCES = [
    {
        "key": "stroylandiya",
        "supplier_id": "ufa.stroylandiya.ru",
        "name": "Стройландия (Уфа)",
        "browser": True,
        "wait_s": 7,
        "pages": [
            ("Цемент и смеси", "https://ufa.stroylandiya.ru/catalog/sukhie-smesi/"),
            ("Кирпич", "https://ufa.stroylandiya.ru/catalog/kirpich/"),
            ("Арматура", "https://ufa.stroylandiya.ru/catalog/armatura/"),
            ("Брус", "https://ufa.stroylandiya.ru/catalog/brus/"),
            ("Утеплитель", "https://ufa.stroylandiya.ru/catalog/uteplitel/"),
            ("Гипсокартон", "https://ufa.stroylandiya.ru/catalog/gipsokarton/"),
            ("Кровля", "https://ufa.stroylandiya.ru/catalog/krovelnye-materialy/"),
            ("Шифер", "https://ufa.stroylandiya.ru/catalog/shifer/"),
        ],
        "parse": parse_stroylandiya,
        "url": "https://ufa.stroylandiya.ru/catalog/sukhie-smesi/",
    },
    {
        "key": "ufacement",
        "supplier_id": "ufacement.ru",
        "name": "УфаЦемент (Уфа)",
        "browser": True,
        "wait_s": 6,
        "pages": [("Цемент в мешках", "https://ufacement.ru/catalog/cement-v-meshkah/")],
        "parse": parse_ufacement,
        "url": "https://ufacement.ru/catalog/cement-v-meshkah/",
    },
    {
        "key": "vseinstrumenti",
        "supplier_id": "vseinstrumenti.ru",
        "name": "ВсеИнструменты.ру",
        "browser": True,
        "wait_s": 10,
        "pages": [("Цемент", "https://www.vseinstrumenti.ru/category/tsement-3432/")],
        "parse": parse_vseinstrumenti,
        "url": "https://www.vseinstrumenti.ru/category/tsement-3432/",
    },
]
