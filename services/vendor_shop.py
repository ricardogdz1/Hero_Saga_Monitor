"""
Fetch e parse da loja de um vendedor (viewshop).
URL: /?module=vending&action=viewshop&id={VENDOR_ID}
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

BASE_URL = "https://herosaga.com.br"


def extract_vendor_id(href: str) -> Optional[int]:
    if not href:
        return None
    m = re.search(r"[?&]id=(\d+)", str(href), re.I)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _cell_text(td) -> str:
    if td is None:
        return ""
    return td.get_text(" ", strip=True)


def _col_index(headers: List[str], *needles: str) -> Optional[int]:
    for i, raw in enumerate(headers):
        h = (raw or "").lower()
        for n in needles:
            if n in h:
                return i
    return None


def parse_viewshop_html(html: str, *, base_url: str = BASE_URL) -> dict:
    from bs4 import BeautifulSoup

    if not (html or "").strip():
        return {"ok": False, "error": "Resposta vazia do servidor."}

    soup = BeautifulSoup(html, "html.parser")

    vd = soup.find(class_="vendor-details")
    table = soup.find("table", class_="items-table") or soup.find("table")
    if not vd and not table:
        if soup.find("h2", string=re.compile(r"Acesso Restrito", re.I)):
            return {"ok": False, "error": "Acesso restrito à loja."}
        return {"ok": False, "error": "Não foi possível carregar a loja. Tente novamente."}

    vendor_name = ""
    shop_title = ""
    currency = ""
    autotrade = ""
    avatar_url = ""
    go_cmd = ""
    navi_cmd = ""

    if vd:
        vn = vd.find(class_="vendor-name")
        if vn:
            vendor_name = vn.get_text(strip=True)
        h3 = vd.find("h3")
        if h3:
            shop_title = h3.get_text(" ", strip=True)
            if shop_title.lower().startswith("loja:"):
                shop_title = shop_title[5:].strip()
        cb = vd.find(class_="currency-type-badge")
        if cb:
            currency = cb.get_text(strip=True)
        ab = vd.find(class_="autotrade-badge")
        if ab:
            autotrade = ab.get_text(strip=True)
        card = vd.find(class_="character-card")
        if card:
            img = card.find("img", src=True)
            if img and img.get("src"):
                avatar_url = urljoin(base_url, img["src"])
        for code in vd.find_all("code"):
            t = code.get_text(strip=True)
            if t.startswith("@go"):
                go_cmd = t
        navi_a = vd.find("a", class_="copy-navi-link")
        if navi_a:
            navi_cmd = (navi_a.get("data-navi") or navi_a.get_text(strip=True) or "").strip()

    items: List[Dict[str, Any]] = []

    if table:
        hdr_tr = table.find("tr")
        headers = [th.get_text(strip=True) for th in hdr_tr.find_all("th")] if hdr_tr else []
        idx = {
            "id": _col_index(headers, "id"),
            "name": _col_index(headers, "nome"),
            "refine": _col_index(headers, "refin"),
            "slots": _col_index(headers, "slots"),
            "slot1": _col_index(headers, "slot 1"),
            "slot2": _col_index(headers, "slot 2"),
            "slot3": _col_index(headers, "slot 3"),
            "slot4": _col_index(headers, "slot 4"),
            "random": _col_index(headers, "random"),
            "price": _col_index(headers, "pre"),
            "qty": _col_index(headers, "quant"),
        }

        def col(cols, key: str, fallback: int) -> str:
            j = idx.get(key)
            if j is not None and j < len(cols):
                return _cell_text(cols[j])
            if fallback < len(cols):
                return _cell_text(cols[fallback])
            return ""

        def col_el(cols, key: str, fallback: int):
            j = idx.get(key)
            if j is not None and j < len(cols):
                return cols[j]
            if fallback < len(cols):
                return cols[fallback]
            return None

        for row in table.find_all("tr")[1:]:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            id_td = col_el(cols, "id", 0)
            name_td = col_el(cols, "name", 1)
            item_id = None
            item_name = col(cols, "name", 1)
            if id_td:
                a = id_td.find("a", href=True)
                if a:
                    m = re.search(r"id=(\d+)", a.get("href", ""), re.I)
                    if m:
                        item_id = int(m.group(1))
                if item_id is None:
                    try:
                        item_id = int(re.sub(r"\D", "", id_td.get_text(strip=True)) or 0) or None
                    except (TypeError, ValueError):
                        item_id = None
            if name_td:
                na = name_td.find("a")
                if na:
                    item_name = na.get_text(" ", strip=True) or item_name

            refine_raw = col(cols, "refine", 2)
            refine = 0
            rm = re.search(r"\+?\s*(\d+)", refine_raw or "")
            if rm:
                refine = int(rm.group(1))

            icon_url = ""
            if name_td:
                ic = name_td.find("img", src=True)
                if ic and ic.get("src"):
                    icon_url = urljoin(base_url, ic["src"])
            if not icon_url and item_id:
                icon_url = f"{base_url}/?module=image&action=processicon&id={item_id}"

            price_raw = col(cols, "price", 9 if len(cols) > 9 else len(cols) - 2)
            qty_raw = col(cols, "qty", 10 if len(cols) > 10 else len(cols) - 1)

            items.append({
                "item_id": item_id,
                "item_name": item_name or (f"Item {item_id}" if item_id else "—"),
                "icon_url": icon_url,
                "refinement": refine,
                "slots": col(cols, "slots", 3),
                "slot1": col(cols, "slot1", 4),
                "slot2": col(cols, "slot2", 5),
                "slot3": col(cols, "slot3", 6),
                "slot4": col(cols, "slot4", 7),
                "random_options": col(cols, "random", 8),
                "price_text": price_raw,
                "quantity": max(1, int(re.sub(r"\D", "", qty_raw) or "1") or 1),
            })

    return {
        "ok": True,
        "vendor_name": vendor_name,
        "shop_title": shop_title or vendor_name or "Loja",
        "currency": currency,
        "autotrade": autotrade,
        "avatar_url": avatar_url,
        "go_cmd": go_cmd,
        "navi_cmd": navi_cmd,
        "items": items,
        "item_count": len(items),
    }


def fetch_vendor_shop(vendor_id, *, force_refresh: bool = False) -> dict:
    from stores_scraper import HerosagaScraper

    try:
        vid = int(vendor_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "ID de loja inválido."}
    if vid <= 0:
        return {"ok": False, "error": "ID de loja inválido."}

    url = f"{BASE_URL}/?module=vending&action=viewshop&id={vid}"
    scraper = HerosagaScraper()
    try:
        html = scraper._fetch_url(url, timeout=25, force_refresh=force_refresh)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_vendor_shop %s: %s", vid, exc)
        return {"ok": False, "error": "Não foi possível carregar a loja. Tente novamente."}

    if not html:
        return {"ok": False, "error": "Não foi possível carregar a loja. Tente novamente."}

    parsed = parse_viewshop_html(html, base_url=BASE_URL)
    if not parsed.get("ok"):
        return parsed

    parsed["vendor_id"] = vid
    if not parsed.get("items"):
        parsed["empty"] = True
    return parsed
