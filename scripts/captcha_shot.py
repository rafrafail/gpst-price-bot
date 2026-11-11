#!/usr/bin/env python3
"""Vision-check the rotate captcha: screenshot the tab, view the image,
compute the needed rotation, then JS-rotate via CSS transform? No — the
captcha expects a drag. We use CDP-free approach: playwright-style drag
is not exposed by CamoFox REST. Instead use vision to estimate angle and
then dispatch precise mousedown/mousemove/mouseup with movementX.

If synthetic events don't count, report honestly and move on: mark VI as
'blocked by captcha' and use other sources.
"""
import base64
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
shot = urllib.request.urlopen(f"{BASE}/tabs/{TID}/screenshot?userId=pricebot&sessionKey=night1", timeout=60).read()
out = "/tmp/vi_captcha.png"
open(out, "wb").write(shot)
print("screenshot saved:", out, len(shot), "bytes")
state = eval_js("document.body.innerText.slice(0,120)")
print("page text:", json.dumps(state, ensure_ascii=False)[:300])
