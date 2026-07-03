"""Cliente HTTP (cloudscraper) e cabeçalhos do site."""
from __future__ import annotations

import cloudscraper

from core.constants import BASE_URL

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": f"{BASE_URL}/",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_inner_scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "desktop": True}
)


def _wrap_scraper_get(inner):
    original_get = inner.get

    def get(url, *args, **kwargs):
        from adapters.herosaga_session import (
            apply_session_to_scraper,
            check_response_auth,
            is_herosaga_url,
        )

        if is_herosaga_url(str(url)):
            apply_session_to_scraper(inner)
            kwargs.setdefault("allow_redirects", False)
        response = original_get(url, *args, **kwargs)
        if is_herosaga_url(str(url)):
            check_response_auth(response)
        return response

    inner.get = get
    return inner


scraper = _wrap_scraper_get(_inner_scraper)
