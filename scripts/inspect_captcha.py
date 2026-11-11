#!/usr/bin/env python3
"""Inspect captcha page structure on the given tab."""
import json
import sys
import urllib.request

TID = sys.argv[1] if len(sys.argv) > 1 else "d371160c-452a-4731-8d29-7e88af48cc3a"
BASE = "http://127.0.0.1:9377"

expr = r"""(() => {
  const html = document.body.innerHTML;
  const rotateHits = (html.match(/rotate[^"'\s<>]*/gi) || []).slice(0, 8);
  const scripts = [...document.querySelectorAll("script[src]")].map(s => s.src.slice(0, 80)).slice(0, 8);
  const hasJquery = typeof window.jQuery;
  const draggables = [...document.querySelectorAll("[class*=drag],[class*=slider],[class*=handle]")].map(e => String(e.className).slice(0, 60));
  return {rotateHits, scripts, hasJquery, draggables};
})()"""

payload = json.dumps({
    "userId": "pricebot",
    "sessionKey": "night1",
    "expression": expr,
}).encode()

req = urllib.request.Request(
    f"{BASE}/tabs/{TID}/evaluate",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=45) as resp:
    print(resp.read().decode()[:1200])
