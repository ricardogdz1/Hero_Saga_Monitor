from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin

import requests

from adapters.network import scraper
from app_settings import load_settings
from core.constants import BASE_URL
from divine_pride_api import fetch_item
from item_icon_cache import item_icon_disk_path, read_item_icon_png_bytes

logger = logging.getLogger(__name__)

LOOT_FILE = os.path.join(os.path.expanduser("~"), "herosaga_loot_groups.json")
_DEFAULT_GROUP_RANGE = range(1, 6)
_MAX_ITEMS_PER_GROUP = 10
_MAX_GROUP_NUMBER = 9
_GENERIC_ITEM_NAME = re.compile(r"^item \d+$", re.IGNORECASE)


def _is_generic_item_name(name: str) -> bool:
    return bool(_GENERIC_ITEM_NAME.match(str(name or "").strip()))


def _normalize_media_url(url: str) -> str:
    u = str(url or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return urljoin(BASE_URL + "/", u[1:])
    return u


def _default_icon_url(item_id: int) -> str:
    return f"{BASE_URL}/?module=image&action=processicon&id={int(item_id)}"


@dataclass
class LootItem:
    id: int
    name: str
    type: str = ""
    icon_url: str = ""
    npc_sell_price: int = 0


@dataclass
class LootGroup:
    number: int
    name: str
    autoload: bool
    items: List[LootItem] = field(default_factory=list)


class LootManager:
    def __init__(self, file_path: str = LOOT_FILE):
        self.file_path = file_path
        self.groups: Dict[int, LootGroup] = {}
        self.load_from_file()

    def _default_groups(self) -> Dict[int, LootGroup]:
        out: Dict[int, LootGroup] = {}
        for n in _DEFAULT_GROUP_RANGE:
            out[n] = LootGroup(number=n, name=f"Grupo {n}", autoload=False, items=[])
        return out

    def _ensure_consistency(self) -> None:
        if not self.groups:
            self.groups = self._default_groups()
        for n in _DEFAULT_GROUP_RANGE:
            if n not in self.groups:
                self.groups[n] = LootGroup(number=n, name=f"Grupo {n}", autoload=False, items=[])
        for n, grp in list(self.groups.items()):
            if not isinstance(grp, LootGroup):
                continue
            dedup: Dict[int, LootItem] = {}
            for it in grp.items:
                try:
                    iid = int(it.id)
                except (TypeError, ValueError):
                    continue
                if iid not in dedup:
                    dedup[iid] = LootItem(
                        id=iid,
                        name=str(it.name or f"Item {iid}").strip() or f"Item {iid}",
                        type=str(it.type or "").strip(),
                        icon_url=str(getattr(it, "icon_url", "") or "").strip(),
                        npc_sell_price=int(getattr(it, "npc_sell_price", 0) or 0),
                    )
            grp.items = list(dedup.values())[:_MAX_ITEMS_PER_GROUP]
        autoloaded = [g for g in self.groups.values() if g.autoload]
        if len(autoloaded) > 1:
            keep = min(autoloaded, key=lambda g: g.number).number
            for g in autoloaded:
                g.autoload = g.number == keep

    def load_from_file(self) -> None:
        self.groups = self._default_groups()
        if not os.path.isfile(self.file_path):
            return
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as ex:
            logger.warning("LootManager: arquivo inválido %s: %s", self.file_path, ex)
            self.groups = self._default_groups()
            return

        raw_groups = payload.get("groups") if isinstance(payload, dict) else None
        if not isinstance(raw_groups, dict):
            self.groups = self._default_groups()
            return

        parsed: Dict[int, LootGroup] = {}
        for k, data in raw_groups.items():
            try:
                n = int(k)
            except (TypeError, ValueError):
                continue
            if n < 1 or n > _MAX_GROUP_NUMBER or not isinstance(data, dict):
                continue
            items_out: List[LootItem] = []
            for raw in data.get("items") or []:
                if not isinstance(raw, dict):
                    continue
                try:
                    iid = int(raw.get("id"))
                except (TypeError, ValueError):
                    continue
                items_out.append(
                    LootItem(
                        id=iid,
                        name=str(raw.get("name") or f"Item {iid}").strip() or f"Item {iid}",
                        type=str(raw.get("type") or "").strip(),
                        icon_url=str(raw.get("icon_url") or "").strip(),
                        npc_sell_price=int(raw.get("npc_sell_price") or 0),
                    )
                )
            parsed[n] = LootGroup(
                number=n,
                name=str(data.get("name") or f"Grupo {n}").strip() or f"Grupo {n}",
                autoload=bool(data.get("autoload")),
                items=items_out,
            )
        if parsed:
            self.groups = parsed
        self._ensure_consistency()

    def save_to_file(self) -> None:
        self._ensure_consistency()
        payload = {"groups": {}}
        for n in sorted(self.groups):
            g = self.groups[n]
            payload["groups"][str(n)] = {
                "name": g.name,
                "autoload": bool(g.autoload),
                "items": [asdict(i) for i in g.items],
            }
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except OSError as ex:
            logger.warning("LootManager: falha ao gravar %s: %s", self.file_path, ex)

    def get_group(self, group_number: int) -> LootGroup:
        n = int(group_number)
        if n not in self.groups:
            self.groups[n] = LootGroup(number=n, name=f"Grupo {n}", autoload=False, items=[])
        return self.groups[n]

    def add_item(self, group_number: int, item: LootItem) -> str:
        """Retorna ``ok``, ``duplicate`` ou ``full``."""
        grp = self.get_group(group_number)
        iid = int(item.id)
        if any(int(it.id) == iid for it in grp.items):
            return "duplicate"
        if len(grp.items) >= _MAX_ITEMS_PER_GROUP:
            return "full"
        grp.items.append(item)
        return "ok"

    def remove_item(self, group_number: int, item_id: int) -> None:
        grp = self.get_group(group_number)
        iid = int(item_id)
        grp.items = [x for x in grp.items if int(x.id) != iid]

    def reorder_items(self, group_number: int, new_order: List[int]) -> None:
        grp = self.get_group(group_number)
        by_id = {int(it.id): it for it in grp.items}
        ordered: List[LootItem] = []
        seen = set()
        for iid in new_order:
            key = int(iid)
            if key in seen or key not in by_id:
                continue
            ordered.append(by_id[key])
            seen.add(key)
        for it in grp.items:
            key = int(it.id)
            if key not in seen:
                ordered.append(it)
                seen.add(key)
        grp.items = ordered[:_MAX_ITEMS_PER_GROUP]

    def set_group_name(self, group_number: int, name: str) -> None:
        grp = self.get_group(group_number)
        clean = str(name or "").strip()
        grp.name = clean or f"Grupo {grp.number}"

    def set_autoload(self, group_number: int, active: bool) -> None:
        target = int(group_number)
        if active:
            for n, grp in self.groups.items():
                grp.autoload = n == target
        else:
            self.get_group(target).autoload = False

    def cmd_save(self, group_number: int) -> str:
        grp = self.get_group(group_number)
        ids = " ".join(str(int(it.id)) for it in grp.items)
        return f"@alootid2 save {int(group_number)} {ids}".rstrip()

    def cmd_load(self, group_number: int) -> str:
        return f"@alootid2 load {int(group_number)}"

    def cmd_add(self, group_number: int, item_id: int) -> str:
        return f"@alootid2 add {int(group_number)} {int(item_id)}"

    def cmd_remove(self, group_number: int, item_id: int) -> str:
        return f"@alootid2 remove {int(group_number)} {int(item_id)}"

    def cmd_clear(self, group_number: int) -> str:
        return f"@alootid2 clear {int(group_number)}"

    def cmd_set_name(self, group_number: int) -> str:
        grp = self.get_group(group_number)
        return f"@alootid2 set {int(group_number)} name {grp.name}".rstrip()

    def cmd_set_autoload(self, group_number: int, value: int) -> str:
        return f"@alootid2 set {int(group_number)} autoload {1 if int(value) else 0}"

    def ensure_icon_cached(self, item_id: int, icon_url: str, fetcher: Callable[[str], Optional[bytes]]) -> str:
        try:
            iid = int(item_id)
        except (TypeError, ValueError):
            return ""
        norm_url = _normalize_media_url(icon_url or "") or _default_icon_url(iid)
        read_item_icon_png_bytes(iid, norm_url, fetcher, base_url=BASE_URL)
        path = item_icon_disk_path(iid)
        return path if os.path.isfile(path) else ""


def _item_type_from_dp(data: dict) -> str:
    for key in ("itemType", "type", "Type", "Loc"):
        val = data.get(key)
        if val is None:
            continue
        s = str(val).strip()
        if s:
            return s
    return ""


def _item_name_from_dp(data: dict, fallback_id: int) -> str:
    for key in ("name", "Name", "AegisName", "visibleName"):
        v = data.get(key)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return f"Item {int(fallback_id)}"


def _item_icon_from_dp(data: dict) -> str:
    for key in ("icon", "Icon", "image", "Image", "itemIconUrl", "iconUrl", "item_icon_url"):
        v = data.get(key)
        if not v:
            continue
        return str(v).strip()
    return ""


_LOOT_DP_LANG_PT = "pt-BR,pt;q=0.9"
_LOOT_DP_SERVER_BR = "bRO"
_LOOT_FINALIZE_WORKERS = 4
_LOOT_META_CACHE_TTL = 300.0

_loot_meta_cache: dict[int, tuple[float, dict]] = {}
_loot_meta_cache_lock = threading.Lock()


def _loot_dp_servers(dp_server: str | None) -> tuple[str, ...]:
    """Servidores DP para Auto Loot (Hero Saga BR → bRO primeiro)."""
    out: list[str] = []
    for s in (_LOOT_DP_SERVER_BR, str(dp_server or "").strip(), "iRO"):
        if s and s not in out:
            out.append(s)
    return tuple(out)


def _dp_fetch_item(
    item_id: int,
    *,
    api_key: str | None,
    server: str | None,
    accept_language: str | None = None,
) -> dict | None:
    key = (api_key or "").strip()
    if not key:
        return None
    try:
        data = fetch_item(
            int(item_id),
            api_key=key,
            server=(server or "").strip() or None,
            accept_language=accept_language,
        )
        return data if isinstance(data, dict) else None
    except Exception as ex:  # noqa: BLE001
        logger.debug("Loot DP item id=%s server=%s: %s", item_id, server, ex)
        return None


def _dp_fetch_cached(
    item_id: int,
    *,
    api_key: str | None,
    server: str | None,
    accept_language: str | None,
    cache: dict,
    cache_lock: threading.Lock,
) -> dict | None:
    lang_key = str(accept_language or "")
    key = (int(item_id), str(server or ""), lang_key)
    with cache_lock:
        if key in cache:
            return cache[key]
    data = _dp_fetch_item(
        item_id,
        api_key=api_key,
        server=server,
        accept_language=accept_language,
    )
    with cache_lock:
        cache[key] = data
    return data


def _hs_item_name(item_id: int) -> str:
    """Nome exibido no site Hero Saga (PT-BR)."""
    try:
        from app_runtime import get_stores_from_item_page

        _stores, meta = get_stores_from_item_page(int(item_id), "", force_refresh=False)
        title = str((meta or {}).get("item_card_title") or "").strip()
        if title and not _is_generic_item_name(title):
            return title
    except Exception as ex:  # noqa: BLE001
        logger.debug("Loot HS name id=%s: %s", item_id, ex)
    return ""


def _loot_pt_name_sources(item_id: int) -> tuple[str, str]:
    """Consulta site Hero Saga e vending em paralelo (nome PT-BR)."""
    iid = int(item_id)
    hs = ""
    vend = ""
    with ThreadPoolExecutor(max_workers=2) as pool:
        hs_f = pool.submit(_hs_item_name, iid)
        vend_f = pool.submit(_vending_name_for_id, iid)
        try:
            hs = str(hs_f.result(timeout=25) or "").strip()
        except Exception as ex:  # noqa: BLE001
            logger.debug("Loot HS parallel id=%s: %s", iid, ex)
        try:
            vend = str(vend_f.result(timeout=20) or "").strip()
        except Exception as ex:  # noqa: BLE001
            logger.debug("Loot vending parallel id=%s: %s", iid, ex)
    return hs, vend


def _apply_dp_fields(
    dp: dict,
    iid: int,
    *,
    name: str,
    item_type: str,
    icon_url: str,
    npc_sell_price: int,
) -> tuple[str, str, str, int]:
    out_name = name
    out_type = item_type
    out_icon = icon_url
    out_price = npc_sell_price
    if not out_name or _is_generic_item_name(out_name):
        dp_name = _item_name_from_dp(dp, iid)
        if dp_name and not _is_generic_item_name(dp_name):
            out_name = dp_name
    if not out_type:
        out_type = _item_type_from_dp(dp)
    if not out_icon:
        out_icon = _normalize_media_url(_item_icon_from_dp(dp))
    if not out_price:
        out_price = _item_npc_sell_from_dp(dp)
    return out_name, out_type, out_icon, out_price


def resolve_loot_item_meta(
    item_id: int,
    *,
    hint_name: str = "",
    hint_type: str = "",
    hint_icon_url: str = "",
    hint_npc_sell_price: int = 0,
    api_key: str | None = None,
    dp_server: str | None = None,
    dp_cache: dict | None = None,
    cache_lock: threading.Lock | None = None,
    use_meta_cache: bool = True,
) -> dict:
    """
    Metadados para Auto Loot: prioriza nome PT (site/vending/DP bRO).
    Sem tradução forçada — se não houver PT, mantém inglês ou hint válido.
    """
    iid = int(item_id)
    if use_meta_cache:
        with _loot_meta_cache_lock:
            hit = _loot_meta_cache.get(iid)
        if hit and (time.time() - hit[0]) < _LOOT_META_CACHE_TTL:
            return dict(hit[1])

    local_cache = dp_cache if dp_cache is not None else {}
    lock = cache_lock if cache_lock is not None else threading.Lock()

    hs_name, vend_name = _loot_pt_name_sources(iid)
    name = hs_name or vend_name or ""
    item_type = str(hint_type or "").strip()
    icon_url = _normalize_media_url(str(hint_icon_url or "").strip())
    npc_sell_price = int(hint_npc_sell_price or 0)

    key = (api_key or "").strip() or None
    if key:
        for srv in _loot_dp_servers(dp_server):
            dp = _dp_fetch_cached(
                iid,
                api_key=key,
                server=srv,
                accept_language=_LOOT_DP_LANG_PT,
                cache=local_cache,
                cache_lock=lock,
            )
            if not dp:
                continue
            name, item_type, icon_url, npc_sell_price = _apply_dp_fields(
                dp, iid, name=name, item_type=item_type, icon_url=icon_url, npc_sell_price=npc_sell_price
            )
            if name and not _is_generic_item_name(name) and npc_sell_price:
                break

        hint = str(hint_name or "").strip()
        if (not name or _is_generic_item_name(name)) and hint and not _is_generic_item_name(hint):
            name = hint

        if (not name or _is_generic_item_name(name)):
            for srv in _loot_dp_servers(dp_server):
                dp = _dp_fetch_cached(
                    iid,
                    api_key=key,
                    server=srv,
                    accept_language=None,
                    cache=local_cache,
                    cache_lock=lock,
                )
                if not dp:
                    continue
                name, item_type, icon_url, npc_sell_price = _apply_dp_fields(
                    dp, iid, name=name, item_type=item_type, icon_url=icon_url, npc_sell_price=npc_sell_price
                )
                if name and not _is_generic_item_name(name):
                    break

        if not npc_sell_price:
            for srv in _loot_dp_servers(dp_server):
                dp = _dp_fetch_cached(
                    iid,
                    api_key=key,
                    server=srv,
                    accept_language=None,
                    cache=local_cache,
                    cache_lock=lock,
                )
                if not dp:
                    continue
                npc_sell_price = _item_npc_sell_from_dp(dp)
                if npc_sell_price:
                    break

    if not name or _is_generic_item_name(name):
        name = f"Item {iid}"
    if not icon_url:
        icon_url = _default_icon_url(iid)

    result = {
        "id": iid,
        "name": name,
        "type": item_type,
        "icon_url": icon_url,
        "npc_sell_price": int(npc_sell_price or 0),
    }
    if use_meta_cache:
        with _loot_meta_cache_lock:
            _loot_meta_cache[iid] = (time.time(), dict(result))
    return result


def _item_npc_sell_from_dp(data: dict) -> int:
    sell_candidates = (
        "sellToNpc",
        "SellToNpc",
        "sell_price",
        "sellPrice",
        "sell",
        "sellZeny",
        "npcSellPrice",
        "npcPrice",
        "sellValue",
    )
    buy_candidates = ("price", "Price", "buyPrice", "BuyPrice", "buy", "value", "Value")
    for key in sell_candidates:
        val = data.get(key)
        try:
            iv = int(float(val))
        except (TypeError, ValueError):
            continue
        if iv >= 0:
            return iv
    for key in buy_candidates:
        val = data.get(key)
        try:
            iv = int(float(val))
        except (TypeError, ValueError):
            continue
        if iv > 0:
            return max(1, iv // 2)
    return 0


def _vending_name_for_id(item_id: int) -> str:
    """Busca nome do item via vending search por ID (fallback leve)."""
    url = f"{BASE_URL}/?module=vending&action=search&item_search={int(item_id)}"
    try:
        resp = scraper.get(
            url,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE_URL}/",
            },
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json() if resp.text.strip() else {}
        for row in (payload.get("results") if isinstance(payload, dict) else []) or []:
            try:
                rid = int(row.get("id"))
            except (TypeError, ValueError):
                continue
            if rid != int(item_id):
                continue
            nm = str(row.get("name") or "").strip()
            if nm and not _is_generic_item_name(nm):
                return nm
    except Exception as ex:  # noqa: BLE001
        logger.debug("Loot vending name id=%s: %s", item_id, ex)
    return ""


def _finalize_loot_row(
    row: dict,
    *,
    api_key: str | None,
    dp_server: str | None,
    dp_cache: dict | None = None,
    cache_lock: threading.Lock | None = None,
) -> dict:
    meta = resolve_loot_item_meta(
        int(row["id"]),
        hint_name=str(row.get("name") or ""),
        hint_type=str(row.get("type") or ""),
        hint_icon_url=str(row.get("icon_url") or ""),
        hint_npc_sell_price=int(row.get("npc_sell_price") or 0),
        api_key=api_key,
        dp_server=dp_server,
        dp_cache=dp_cache,
        cache_lock=cache_lock,
    )
    row.update(meta)
    return row


def _finalize_loot_rows(
    rows: List[dict],
    *,
    api_key: str | None,
    dp_server: str | None,
    max_workers: int = _LOOT_FINALIZE_WORKERS,
) -> List[dict]:
    """Enriquece vários itens em paralelo; preserva a ordem de *rows*."""
    if not rows:
        return []
    dp_cache: dict = {}
    cache_lock = threading.Lock()

    def _one(row: dict) -> dict:
        return _finalize_loot_row(
            row,
            api_key=api_key,
            dp_server=dp_server,
            dp_cache=dp_cache,
            cache_lock=cache_lock,
        )

    if len(rows) == 1:
        return [_one(rows[0])]

    workers = max(1, min(int(max_workers or _LOOT_FINALIZE_WORKERS), 8, len(rows)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_one, rows))


def _loot_search_settings() -> tuple[str | None, str | None]:
    cfg = load_settings()
    api_key = (cfg.get("divine_pride_api_key") or "").strip() or None
    dp_server = (cfg.get("divine_pride_server") or "").strip() or None
    return api_key, dp_server


def search_items_by_ids(item_ids: List[int]) -> List[dict]:
    """Busca metadados de vários IDs em paralelo (ordem preservada)."""
    api_key, dp_server = _loot_search_settings()
    rows = []
    for raw in item_ids:
        try:
            iid = int(raw)
        except (TypeError, ValueError):
            continue
        if iid <= 0:
            continue
        rows.append(
            {
                "id": iid,
                "name": "",
                "type": "",
                "icon_url": _default_icon_url(iid),
                "npc_sell_price": 0,
            }
        )
    return _finalize_loot_rows(rows, api_key=api_key, dp_server=dp_server)


def search_item(query: str) -> List[dict]:
    q = str(query or "").strip()
    if not q:
        return []

    from adapters.network import scraper as hs_scraper

    api_key, dp_server = _loot_search_settings()

    out: List[dict] = []
    if q.isdigit():
        return search_items_by_ids([int(q)])

    url = f"{BASE_URL}/?module=vending&action=search&item_search={requests.utils.quote(q)}"
    try:
        resp = hs_scraper.get(
            url,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE_URL}/",
            },
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json() if resp.text.strip() else {}
        results = payload.get("results") if isinstance(payload, dict) else []
    except requests.RequestException as ex:
        logger.warning("Loot search query=%r: %s", q, ex)
        return []
    except ValueError as ex:
        logger.warning("Loot search resposta inválida query=%r: %s", q, ex)
        return []

    seen = set()
    for item in results or []:
        try:
            iid = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if iid in seen:
            continue
        seen.add(iid)
        out.append(
            {
                "id": iid,
                "name": str(item.get("name") or f"Item {iid}").strip() or f"Item {iid}",
                "type": str(item.get("type") or "").strip(),
                "icon_url": _normalize_media_url(str(item.get("icon_url") or item.get("item_icon_url") or "").strip())
                or _default_icon_url(iid),
                "npc_sell_price": 0,
            }
        )
        if len(out) >= 18:
            break

    if not out:
        return []

    return _finalize_loot_rows(out, api_key=api_key, dp_server=dp_server)
