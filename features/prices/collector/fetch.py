"""Fetch layer: plain http first, browser (Camoufox) on block/JS need.

Parsers are pure functions over page content; this module only brings the
content. Browser runs are batched in one Camoufox launch per collect run.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

POLITE_DELAY_S = 3


@dataclass
class FetchedPage:
    ok: bool
    html: str | None = None
    error: str | None = None
    via: str = "http"  # "http" | "browser"


def fetch_http(url: str, timeout: int = 25) -> FetchedPage:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code == 200 and ("₽" in resp.text or "руб" in resp.text):
            return FetchedPage(ok=True, html=resp.text, via="http")
        return FetchedPage(ok=False, error=f"HTTP {resp.status_code}", via="http")
    except requests.RequestException as exc:
        return FetchedPage(ok=False, error=type(exc).__name__, via="http")


class BrowserPool:
    """One Camoufox instance, reused across pages of a single run."""

    def __init__(self):
        self._ctx = None
        self._browser = None

    def __enter__(self):
        from camoufox.sync_api import Camoufox

        self._ctx = Camoufox(headless=True, humanize=True)
        self._browser = self._ctx.__enter__()
        return self

    def __exit__(self, *exc):
        return self._ctx.__exit__(*exc)  # type: ignore[union-attr]

    def page(self, url: str, wait_s: int = 8) -> FetchedPage:
        page = self._browser.new_page()  # type: ignore[union-attr]
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            time.sleep(wait_s)
            html = page.content()
            return FetchedPage(ok=True, html=html, via="browser")
        except Exception as exc:
            return FetchedPage(ok=False, error=type(exc).__name__, via="browser")
        finally:
            page.close()
