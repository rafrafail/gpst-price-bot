#!/usr/bin/env python3
"""Drag captcha image horizontally via Playwright-style dispatch:
synthesize mousedown/mousemove/mouseup on the captcha-img container.

JS-side synthetic events often aren't trusted; but the VI captcha bundle
listens on document-level mousemove after mousedown on .captcha-img —
synthetic MouseEvent with bubbles:true may drive it. Try and check.
"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:9377"


def api(path, payload):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def eval_js(expr):
    return api(f"/tabs/{TID}/evaluate", {"userId": "pricebot", "sessionKey": "night1", "expression": expr})


TID = sys.argv[1]
expr = r"""(() => {
  const img = document.querySelector(".captcha-img img") || document.querySelector("img[src*=get_image]");
  if (!img) return "no img";
  const r = img.getBoundingClientRect();
  const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
  const mk = (type, x) => { const e = new MouseEvent(type, {bubbles: true, cancelable: true, clientX: x, clientY: cy, button: 0}); return e; };
  img.dispatchEvent(mk("mousedown", cx));
  let total = 190;
  for (let i = 1; i <= 19; i++) {
    document.dispatchEvent(mk("mousemove", cx + i * 10));
  }
  document.dispatchEvent(mk("mouseup", cx + total));
  return "dragged to +" + total;
})()"""
print("drag:", json.dumps(eval_js(expr), ensure_ascii=False)[:200])
time.sleep(5)
after = eval_js("document.body.innerText.includes('ботом') ? 'captcha' : 'passed'")
print("after:", json.dumps(after)[:200])
