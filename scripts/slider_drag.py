#!/usr/bin/env python3
"""Drag the captcha slider handle (.captcha-control-wrap child) via synthetic
mouse events dispatched on document with bubbles. Then verify.
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

geom = eval_js(r"""(() => {
  const wrap = document.querySelector(".captcha-control-wrap");
  if (!wrap) return "no wrap";
  const r = wrap.getBoundingClientRect();
  const kids = [...wrap.children].map(k => {const kr = k.getBoundingClientRect(); return {tag:k.tagName, cls:String(k.className).slice(0,40), x:kr.x, y:kr.y, w:kr.width, h:kr.height};});
  return {wrap: {x:r.x, y:r.y, w:r.width, h:r.height}, kids};
})()""")
print(json.dumps(geom, ensure_ascii=False)[:600])

res = geom["result"]
if isinstance(res, str):
    raise SystemExit(res)
wrap = res["wrap"]
handle = res["kids"][-1] if res["kids"] else None
hx = (handle["x"] + handle["w"] / 2) if handle else (wrap["x"] + 10)
hy = wrap["y"] + wrap["h"] / 2

expr = r"""((hx, hy, targetX) => {
  const mk = (type, x, y) => new MouseEvent(type, {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, buttons: type === "mousemove" ? 1 : 0});
  const el = document.elementFromPoint(hx, hy) || document.body;
  el.dispatchEvent(mk("mousedown", hx, hy));
  const steps = 30;
  for (let i = 1; i <= steps; i++) {
    const x = hx + (targetX - hx) * i / steps;
    document.dispatchEvent(mk("mousemove", x, hy));
    if (document.elementFromPoint(x, hy)) document.elementFromPoint(x, hy).dispatchEvent(mk("mousemove", x, hy));
  }
  document.dispatchEvent(mk("mouseup", targetX, hy));
  return "dragged " + hx + " -> " + targetX;
})(""" + f"{hx}, {hy}, {hx + 120}" + ")"""
print("drag:", json.dumps(eval_js(expr), ensure_ascii=False)[:250])
time.sleep(5)
after = eval_js("document.body.innerText.includes('ботом') ? 'captcha' : 'passed'")
print("after:", json.dumps(after)[:200])
