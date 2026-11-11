#!/usr/bin/env python3
"""Check which egress IP camoufox uses with COLLECT_PROXY on prod."""
from features.prices.collector.fetch import BrowserPool

with BrowserPool() as pool:
    page = pool.page("https://api.ipify.org/", wait_s=5)
    html = page.html or ""
    import re
    m = re.search(r"\d{1,3}(?:\.\d{1,3}){3}", html)
    print("egress IP via proxy:", m.group(0) if m else html[:200])
