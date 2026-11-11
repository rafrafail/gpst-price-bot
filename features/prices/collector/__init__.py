"""Price collector: source parsers, normalization, storage.

Contract per offer row (dict):
    name: str           — product name as shown on the site
    category: str       — our normalized category (e.g. "Цемент")
    price: int          — rubles, integer
    unit: str           — "шт", "кг", "т", "м2"...
    city: str           — "Уфа" or the site's region
    supplier: str       — source display name
    url: str            — direct product/category page URL
"""
