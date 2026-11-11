#!/usr/bin/env python3
"""Check captcha state after drag: does .captcha-state or captcha-coordinate
update? Maybe check happens server-side on next request, and the slider drag
worked but the answer (angle) is wrong each time. Vision-check the image
rotation and compute precise distance: image 152px, control track ~225px.
"""
import base64
import json
import time

from camoufox.sync_api import Camoufox

URL = "https://www.vseinstrumenti.ru/category/tsement-3432/"

with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    page.goto(URL, timeout=60000, wait_until="domcontentloaded")
    time.sleep(10)
    state = page.evaluate(
        """(() => ({
          stateText: document.querySelector(".captcha-state") ? document.querySelector(".captcha-state").textContent : null,
          coordText: document.querySelector(".captcha-coordinate") ? document.querySelector(".captcha-coordinate").textContent : null,
          knobTransform: document.querySelector(".captcha-control-button") ? document.querySelector(".captcha-control-button").style.cssText : null,
          imgTransform: document.querySelector(".captcha-img img") ? document.querySelector(".captcha-img img").style.cssText : null,
        }))()"""
    )
    print("state after previous runs:", json.dumps(state))
    # read the captcha image bytes
    img_b64 = page.evaluate(
        """(() => { const img = document.querySelector(".captcha-img img");
             return img ? fetch(img.src).then(r => r.blob()).then(b => new Promise(res => {const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(b);})).catch(e => "ERR:" + e) : "no img"; })()"""
    )
    if isinstance(img_b64, str) and img_b64.startswith("data:"):
        open("/tmp/vi_captcha_img.png", "wb").write(base64.b64decode(img_b64.split(",", 1)[1]))
        print("captcha image saved: /tmp/vi_captcha_img.png")
    else:
        print("img fetch:", str(img_b64)[:100])
    page.close()
