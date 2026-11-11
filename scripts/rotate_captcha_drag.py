#!/usr/bin/env python3
"""Rotate captcha: drag the captcha image itself horizontally to rotate it upright."""
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
img = eval_js(r"""(() => { const img = document.querySelector("img[src*=captcha]"); const r = img.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; })()""")
r = img["result"]
cx = r["x"] + r["w"] / 2
cy = r["y"] + r["h"] / 2
print("captcha img center:", cx, cy)

actions = [{"type": "move", "x": cx, "y": cy}, {"type": "down"}]
steps = 24
step_px = int(sys.argv[2]) if len(sys.argv) > 2 else 8
for i in range(1, steps + 1):
    actions.append({"type": "move", "x": cx + i * step_px, "y": cy})
actions.append({"type": "up"})
try:
    resp = api(f"/tabs/{TID}/mouse", {"userId": "pricebot", "sessionKey": "night1", "actions": actions})
    print("mouse drag:", json.dumps(resp)[:200])
except Exception as e:
    print("mouse api error:", e)

time.sleep(4)
after = eval_js("document.body.innerText.includes('ботом') ? 'captcha' : 'passed-or-page'")
print("after:", json.dumps(after)[:200])
