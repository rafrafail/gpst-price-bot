#!/usr/bin/env python3
"""Programmatic angle detection of the captcha image via horizon heuristic.

The captcha asks to rotate a circular photo upright ('горизонтально'). Most
photos have a horizon/gravity cue: sky is lighter than ground. We rotate the
image in steps, compute row-wise brightness gradient alignment, and pick the
angle where the top half is brightest (sky up). Then map angle -> slider px.
"""
import base64
import io
import json
import time

from camoufox.sync_api import Camoufox
from PIL import Image

URL = "https://www.vseinstrumenti.ru/category/tsement-3432/"


def estimate_rotation(img: Image.Image) -> int:
    """Return rotation degrees (clockwise) that puts the brightest row at top."""
    img = img.convert("L").resize((64, 64))
    px = img.load()
    best_angle, best_score = 0, -1
    for angle in range(-180, 181, 5):
        rotated = img.rotate(-angle, resample=Image.BILINEAR)
        # score: mean brightness of top half minus bottom half
        top = sum(rotated.getpixel((x, y)) for y in range(0, 20) for x in range(0, 64))
        bottom = sum(rotated.getpixel((x, y)) for y in range(44, 64) for x in range(0, 64))
        score = top - bottom
        if score > best_score:
            best_score, best_angle = score, angle
    return best_angle


with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    page.goto(URL, timeout=60000, wait_until="domcontentloaded")
    time.sleep(10)

    for attempt in range(6):
        if "ботом" not in page.inner_text("body"):
            html = page.content()
            open("/tmp/vi_fresh.html", "w").write(html)
            import re
            print(f"CLEAN at {attempt}; products={len(re.findall('/product/', html))}")
            break
        b64 = page.evaluate(
            """(() => { const img = document.querySelector(".captcha-img img");
                 return img ? fetch(img.src).then(r => r.blob()).then(b => new Promise(res => {
                   const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(b);
                 })) : null; })()"""
        )
        if not b64 or not str(b64).startswith("data:"):
            time.sleep(6)
            continue
        img = Image.open(io.BytesIO(base64.b64decode(str(b64).split(",", 1)[1])))
        angle = estimate_rotation(img)
        # track: 275px wide, knob 50 -> travel 225px for 360deg -> ~0.625 px/deg
        distance = int(abs(angle) * 225 / 360)
        knob = page.locator(".captcha-control-button")
        box = knob.bounding_box()
        if not box:
            time.sleep(6)
            continue
        hx, hy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        direction = 1 if angle >= 0 else -1
        page.mouse.move(hx, hy)
        page.mouse.down()
        steps = 20
        for i in range(1, steps + 1):
            page.mouse.move(hx + direction * distance * i / steps, hy, steps=1)
            time.sleep(0.04)
        time.sleep(0.4)
        page.mouse.up()
        time.sleep(8)
        still = "ботом" in page.inner_text("body")
        print(f"attempt {attempt}: angle={angle} dist={distance}px dir={direction} captcha={still}")
        if still:
            page.reload(timeout=60000, wait_until="domcontentloaded")
            time.sleep(8)
    else:
        print("NEVER CLEAN")
