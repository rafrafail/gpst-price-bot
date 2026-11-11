#!/usr/bin/env python3
"""Try to solve the rotate captcha by dragging the slider horizontally.

The VI captcha shows a rotated image and asks to 'Разверните картинку горизонтально'.
There is a draggable element rendered after JS init. We hunt for it and drag.
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
state = eval_js(r"""(() => {
  const drag = document.querySelector("[class*=drag],[class*=slider],[id*=drag],[id*=slider]");
  return {
    dragFound: !!drag,
    dragInfo: drag ? {tag: drag.tagName, cls: String(drag.className).slice(0,60), rect: drag.getBoundingClientRect()} : null,
    captchaStill: document.body.innerText.includes("ботом"),
  };
})()""")
print(json.dumps(state, ensure_ascii=False)[:800])

if state["result"]["dragFound"]:
    box = state["result"]["dragInfo"]["rect"]
    x = box["x"] + box["width"] / 2
    y = box["y"] + box["height"] / 2
    # drag right in small steps via mouse API if available
    for path in ("/tabs/%s/mouse" % TID,):
        try:
            r = api(path, {"userId": "pricebot", "sessionKey": "night1",
                           "actions": [
                               {"type": "move", "x": x, "y": y},
                               {"type": "down"},
                               {"type": "move", "x": x + 60, "y": y},
                               {"type": "move", "x": x + 120, "y": y},
                               {"type": "move", "x": x + 180, "y": y},
                               {"type": "up"},
                           ]})
            print("mouse:", json.dumps(r)[:200])
            break
        except Exception as e:
            print("mouse api failed:", e)
            break
time.sleep(3)
after = eval_js("document.body.innerText.includes('ботом') ? 'captcha' : 'passed'")
print("after:", json.dumps(after)[:200])
