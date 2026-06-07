"""
Ponte Python ↔ JS para a prova de conceito da Home em pywebview.

Reaproveita a lógica existente do app (carregamento de dados, ícones em cache)
sem nenhuma dependência de Tkinter. Os métodos públicos desta classe ficam
acessíveis no front-end via ``window.pywebview.api.<metodo>()``.
"""
from __future__ import annotations

import base64
import os
import re
import sys
from datetime import datetime

# Permite importar os módulos do projeto quando executado de dentro de web_poc/.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from adapters.herosaga_client import HerosagaClient  # noqa: E402
from adapters.network import scraper  # noqa: E402
from adapters.persistence import (  # noqa: E402
    _ALERTS_IO_LOCK,
    load_alerts,
    load_data,
    save_alerts,
    save_data,
)
from app_domain import (  # noqa: E402
    alert_min_refinement,
    sale_min_prices_from_stores,
)
from app_settings import (  # noqa: E402
    load_settings,
    save_settings,
    set_windows_autostart,
)
from app_runtime import (  # noqa: E402
    _normalize_media_url,
    api_item_history,
    calculate_stats,
    get_stores_from_item_page,
    logger,
)
from core.constants import BASE_URL  # noqa: E402
from item_icon_cache import (  # noqa: E402
    item_icon_disk_path,
    read_item_icon_png_bytes,
    resolve_item_icon_url,
)
from services.item_search import ItemSearchService  # noqa: E402
from services.monitored import splice_category_block  # noqa: E402
from services.search_history import append_search as _append_search  # noqa: E402
from web_poc.alert_worker import get_alert_worker  # noqa: E402

DEFAULT_CATEGORIES = ("Gerais", "Equipamentos", "Cartas", "Utilitários", "Consumíveis")

_PRICE_KEYS = ("zeny", "rmt", "hero_points")
_GENERIC_ITEM_NAME = re.compile(r"^Item \d+$")


def _is_generic_item_name(name) -> bool:
    return bool(_GENERIC_ITEM_NAME.match(str(name or "").strip()))


def _icon_data_uri(item_id, url: str) -> str:
    """Ícone do item: cache em disco (base64) → URL remota como fallback."""
    try:
        iid = int(item_id)
    except (TypeError, ValueError):
        iid = None
    if iid is not None:
        try:
            path = item_icon_disk_path(iid)
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    raw = f.read()
                return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        except OSError:
            pass
    return resolve_item_icon_url(iid, url or "", base_url=BASE_URL)


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _optional_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fetch_url_bytes(url: str):
    try:
        r = scraper.get(url, timeout=15)
        if getattr(r, "status_code", 0) == 200:
            return r.content
    except Exception:  # noqa: BLE001
        return None
    return None


def _norm_currency(sale_type: str) -> str:
    # No jogo só existem ZENY, RMT e HP (Hero Points). A API de histórico expõe
    # exatamente 3 moedas: "zeny", "rmt" e "rops" — sendo que "rops" é, na
    # prática, o balde de Hero Points (HP). Por isso mapeamos rops/hero → HP.
    st = (sale_type or "zeny").lower()
    if "rmt" in st:
        return "rmt"
    if "rops" in st or ("hero" in st and "point" in st) or st == "hp":
        return "hero_points"
    return "zeny"


def _norm_prices(mp: dict) -> dict:
    """Normaliza um dict de menores preços (chaves de moeda variadas) para zeny/rmt/rops/hp."""
    out: dict = {}
    for k, v in (mp or {}).items():
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv <= 0:
            continue
        key = _norm_currency(k)
        if key not in out or fv < out[key]:
            out[key] = fv
    return out


def _icon_fetched(item_id, url: str) -> str:
    """Ícone com rede: disco → download (grava em cache) → base64; '' se falhar."""
    iid = _as_int(item_id)
    if iid is None:
        return ""
    try:
        raw = read_item_icon_png_bytes(iid, url or "", _fetch_url_bytes, base_url=BASE_URL)
        if raw:
            return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    except Exception:  # noqa: BLE001
        pass
    return ""


def _sale_date(s: dict) -> str:
    return str(s.get("sale_date") or s.get("timestamp") or "")


def _currency_block(items: list) -> dict:
    """Série (asc), estatísticas e vendas recentes (desc) para uma moeda."""
    points = []
    for s in sorted(items, key=_sale_date):
        try:
            p = float(s.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if p <= 0:
            continue
        points.append({"t": _sale_date(s), "price": p})

    raw = calculate_stats(items)
    stats = {
        "last": raw.get("último", 0),
        "min": raw.get("mínimo", 0),
        "max": raw.get("máximo", 0),
        "avg": raw.get("média", 0),
        "count": raw.get("quantidade", len(items)),
    }

    recent = []
    for s in sorted(items, key=_sale_date, reverse=True)[:25]:
        try:
            price = float(s.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        recent.append({
            "date": _sale_date(s),
            "price": price,
            "qty": int(s.get("quantity") or 1),
            "seller": str(s.get("seller_name") or ""),
            "buyer": str(s.get("buyer_name") or ""),
        })

    return {"points": points, "stats": stats, "sales": recent, "count": len(items)}


def _history_payload(item_id) -> dict:
    """Histórico de vendas separado por moeda (zeny/rmt/hero_points)."""
    iid = _as_int(item_id)
    if iid is None:
        return {"ok": False, "error": "id inválido"}
    try:
        hist = api_item_history(iid)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}

    sales = (hist or {}).get("sales") or []
    groups = {"zeny": [], "rmt": [], "hero_points": []}
    for s in sales:
        groups[_norm_currency(s.get("sale_type"))].append(s)

    currencies = {k: _currency_block(v) for k, v in groups.items()}
    default = max(currencies, key=lambda k: currencies[k]["count"])
    if currencies[default]["count"] == 0:
        default = "zeny"
    return {"ok": True, "currencies": currencies, "default": default}


def _store_payload(s: dict) -> dict:
    try:
        price = float(s.get("price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    out = {
        "shop": str(s.get("char_name") or s.get("store") or "—"),
        "price": price,
        "currency": _norm_currency(s.get("sale_type")),
        "refinement": int(s.get("refinement") or 0),
        "cards": int(s.get("cards") or 0),
        "quantity": int(s.get("quantity") or s.get("amount") or 1),
    }
    try:
        vid = int(s.get("vendor_id") or 0)
        if vid > 0:
            out["vendor_id"] = vid
    except (TypeError, ValueError):
        pass
    return out


def _item_payload(m: dict) -> dict:
    iid = m.get("id")
    prices = {}
    mp = m.get("min_prices") or {}
    if isinstance(mp, dict):
        for k in _PRICE_KEYS:
            v = mp.get(k)
            try:
                if v is not None and float(v) > 0:
                    prices[k] = float(v)
            except (TypeError, ValueError):
                continue
    return {
        "id": iid,
        "name": str(m.get("name") or "Item"),
        "icon": _icon_data_uri(iid, m.get("item_icon_url") or ""),
        "prices": prices,
        "updated": str(m.get("updated_at") or m.get("home_prices_updated_at") or ""),
    }


def _build_slot_price(iid: int, refine: int, stores=None) -> dict:
    """Menor preço (RMT/HP) de um item num refino exacto (regra do simulador de build)."""
    from build_simulator import filter_stores_slot, min_prices_from_stores

    try:
        iid_int = int(iid)
    except (TypeError, ValueError):
        return {"rmt": None, "hp": None}
    if iid_int <= 0:
        return {"rmt": None, "hp": None}
    try:
        if stores is None:
            stores, _ = get_stores_from_item_page(iid_int, "", force_refresh=True)
        want_ref = max(0, min(20, int(refine or 0)))
        matched = filter_stores_slot(stores or [], want_ref, 0)
        mp = min_prices_from_stores(matched, only_qty_one=True)
        if not mp and want_ref == 0:
            mp = min_prices_from_stores(stores or [], only_qty_one=True)
        elif not mp:
            mp = {}
        return {
            "rmt": mp.get("rmt"),
            "hp": mp.get("hero_points"),
        }
    except Exception:  # noqa: BLE001
        return {"rmt": None, "hp": None}


def _alert_view(key: str, a: dict) -> dict:
    """Representação de um alerta para o front-end (página Alertas)."""
    iid = _as_int(a.get("item_id"))
    ref = a.get("refinement")
    try:
        ref = int(ref) if ref is not None and str(ref).strip() != "" else None
    except (TypeError, ValueError):
        ref = None
    return {
        "key": key,
        "id": iid,
        "name": str(a.get("item_name") or "Item"),
        "icon": _icon_data_uri(iid, a.get("item_icon_url") or ""),
        "prices": _norm_prices(a.get("min_prices")),
        "currency": _norm_currency(a.get("sale_type")),
        "type": "above" if str(a.get("type")) == "above" else "below",
        "threshold": float(a.get("price") or 0),
        "refinement": ref,
        "notify_email": str(a.get("notify_email") or "").strip(),
        "condition_met": bool(a.get("condition_met")),
        "last_fired_at": str(a.get("last_fired_at") or "").strip(),
    }


class Api:
    """Métodos expostos ao front-end."""

    def __init__(self) -> None:
        self._search_service = None
        self._alert_worker = get_alert_worker(
            lambda iid, name: get_stores_from_item_page(iid, name, force_refresh=True)
        )
        self._alert_worker.start(initial_delay=8.0)

    def _search(self) -> ItemSearchService:
        if self._search_service is None:
            client = HerosagaClient(
                base_url=BASE_URL,
                scraper=scraper,
                get_stores_from_item_page_fn=get_stores_from_item_page,
                normalize_media_url_fn=_normalize_media_url,
                logger=logger,
            )
            self._search_service = ItemSearchService(client)
        return self._search_service

    def get_home(self) -> dict:
        """Estrutura completa da Home: categorias (na ordem do utilizador) + itens."""
        data = load_data()
        monitored = list(data.get("monitored") or [])
        cats = data.get("monitor_categories")
        if not isinstance(cats, list) or not cats:
            cats = list(DEFAULT_CATEGORIES)

        by_cat: dict = {c: [] for c in cats}
        for m in monitored:
            c = str(m.get("category") or "Gerais")
            by_cat.setdefault(c, [])
            if c not in cats:
                cats.append(c)
            by_cat[c].append(_item_payload(m))

        categories = [{"name": c, "items": by_cat.get(c, [])} for c in cats]
        total = len(monitored)
        return {
            "categories": categories,
            "total": total,
            "app": "GDZ Monitor",
        }

    def get_item_detail(self, item_id) -> dict:
        """Lojas ao vivo + menores preços de um item monitorado (para o painel de detalhe)."""
        data = load_data()
        monitored = list(data.get("monitored") or [])
        entry = next((m for m in monitored if str(m.get("id")) == str(item_id)), None)
        name = str((entry or {}).get("name") or "")
        if _is_generic_item_name(name):
            name = ""
        try:
            iid = int(item_id)
        except (TypeError, ValueError):
            return {"ok": False, "error": "ID inválido", "id": item_id}

        try:
            stores, meta = get_stores_from_item_page(iid, name, force_refresh=True)
        except Exception as exc:  # noqa: BLE001 — POC: superfície de erro vai para a UI
            return {"ok": False, "error": str(exc), "id": iid, "name": name}

        stores = stores or []
        meta = meta or {}
        icon_url = resolve_item_icon_url(
            iid,
            (entry or {}).get("item_icon_url") or meta.get("item_icon_url") or "",
            base_url=BASE_URL,
        )
        payload_stores = sorted(
            (_store_payload(s) for s in stores), key=lambda x: x["price"] or float("inf")
        )
        return {
            "ok": True,
            "id": iid,
            "name": name or str(meta.get("item_card_title") or meta.get("name") or "Item"),
            "icon": _icon_data_uri(iid, icon_url),
            "item_icon_url": icon_url,
            "stores": payload_stores,
            "min_prices": sale_min_prices_from_stores(stores),
            "store_count": len(payload_stores),
            "description": str(meta.get("item_description") or "").strip(),
            "weight": str(meta.get("item_weight") or "").strip(),
            "monitored": iid in {_as_int(m.get("id")) for m in monitored},
        }

    def get_vendor_shop(self, vendor_id) -> dict:
        """Carrega inventário completo de uma loja (viewshop)."""
        from services.vendor_shop import fetch_vendor_shop

        try:
            vid = int(vendor_id)
        except (TypeError, ValueError):
            return {"ok": False, "error": "ID de loja inválido."}
        if vid <= 0:
            return {"ok": False, "error": "ID de loja inválido."}

        try:
            data = fetch_vendor_shop(vid)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

        if not data.get("ok"):
            return data

        items = []
        for raw in data.get("items") or []:
            if not isinstance(raw, dict):
                continue
            iid = _as_int(raw.get("item_id"))
            items.append({
                "item_id": iid,
                "item_name": str(raw.get("item_name") or (f"Item {iid}" if iid else "—")),
                "icon": _icon_data_uri(iid, raw.get("icon_url") or "") if iid else "",
                "refinement": int(raw.get("refinement") or 0),
                "slots": str(raw.get("slots") or ""),
                "slot1": str(raw.get("slot1") or ""),
                "slot2": str(raw.get("slot2") or ""),
                "slot3": str(raw.get("slot3") or ""),
                "slot4": str(raw.get("slot4") or ""),
                "random_options": str(raw.get("random_options") or ""),
                "price_text": str(raw.get("price_text") or ""),
                "quantity": int(raw.get("quantity") or 1),
            })
        data["items"] = items
        return data

    def get_price_history(self, item_id) -> dict:
        """Histórico de preços/vendas de um item (para o gráfico no detalhe)."""
        return _history_payload(item_id)

    def refresh_prices(self) -> dict:
        """Atualiza os menores preços de todos os itens monitorados e devolve a Home nova."""
        data = load_data()
        monitored = list(data.get("monitored") or [])
        updated = 0
        for m in monitored:
            iid = m.get("id")
            if iid is None:
                continue
            try:
                iid_int = int(iid)
            except (TypeError, ValueError):
                continue
            try:
                stores, meta = get_stores_from_item_page(
                    iid_int, str(m.get("name") or ""), force_refresh=True
                )
            except Exception:  # noqa: BLE001 — falha de rede num item não trava o lote
                continue
            m["min_prices"] = sale_min_prices_from_stores(stores or [])
            m["home_prices_updated_at"] = datetime.now().isoformat()
            if (meta or {}).get("item_icon_url") and not m.get("item_icon_url"):
                m["item_icon_url"] = meta["item_icon_url"]
            updated += 1
        data["monitored"] = monitored
        try:
            save_data(data)
        except Exception:  # noqa: BLE001
            pass
        result = self.get_home()
        result["refreshed"] = updated
        return result

    # ── Ações de edição (persistem em disco e devolvem a Home nova) ──────

    def remove_item(self, item_id) -> dict:
        iid = _as_int(item_id)
        data = load_data()
        data["monitored"] = [
            m for m in (data.get("monitored") or []) if _as_int(m.get("id")) != iid
        ]
        save_data(data)
        return self.get_home()

    def place_item(self, item_id, category, insert_index) -> dict:
        """Move/reordena um item: coloca-o em ``category`` na posição ``insert_index``.

        Cobre tanto mover entre categorias como reordenar dentro da mesma.
        """
        iid = _as_int(item_id)
        cat = str(category)
        data = load_data()
        monitored = list(data.get("monitored") or [])
        cats = data.get("monitor_categories") or list(DEFAULT_CATEGORIES)
        if cat not in cats:
            return {"ok": False, "error": "categoria inexistente", **self.get_home()}

        item = next((m for m in monitored if _as_int(m.get("id")) == iid), None)
        if item is None:
            return {"ok": False, "error": "item não encontrado", **self.get_home()}

        item = dict(item)
        item["category"] = cat
        rest = [m for m in monitored if _as_int(m.get("id")) != iid]

        ids = [_as_int(m.get("id")) for m in rest if str(m.get("category") or "Gerais") == cat]
        ids = [x for x in ids if x is not None]
        try:
            idx = int(insert_index)
        except (TypeError, ValueError):
            idx = len(ids)
        idx = min(max(0, idx), len(ids))
        ids.insert(idx, iid)

        by_id = {_as_int(m.get("id")): m for m in rest}
        by_id[iid] = item
        new_entries = [by_id[x] for x in ids if x in by_id]

        data["monitored"] = splice_category_block(rest, cat, new_entries)
        save_data(data)
        return self.get_home()

    def add_category(self, name) -> dict:
        nm = str(name or "").strip()
        if not nm:
            return {"ok": False, "error": "nome vazio", **self.get_home()}
        data = load_data()
        cats = list(data.get("monitor_categories") or list(DEFAULT_CATEGORIES))
        if nm in cats:
            return {"ok": False, "error": "categoria já existe", **self.get_home()}
        cats.append(nm)
        data["monitor_categories"] = cats
        save_data(data)
        return self.get_home()

    def remove_category(self, name) -> dict:
        nm = str(name or "").strip()
        if nm == "Gerais" or not nm:
            return {"ok": False, "error": "categoria protegida", **self.get_home()}
        data = load_data()
        for m in data.get("monitored") or []:
            if str(m.get("category") or "") == nm:
                m["category"] = "Gerais"
        cats = [c for c in (data.get("monitor_categories") or []) if c != nm]
        if "Gerais" not in cats:
            cats.insert(0, "Gerais")
        data["monitor_categories"] = cats
        save_data(data)
        return self.get_home()

    # ── Busca no catálogo + adicionar ao monitor ────────────────────────

    def search_items(self, query) -> dict:
        q = str(query or "").strip()
        if not q:
            return {"ok": True, "query": q, "items": []}
        monitored_ids = {_as_int(m.get("id")) for m in (load_data().get("monitored") or [])}
        try:
            results = self._search().search_by_name(q)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "query": q, "items": []}

        items = []
        for r in results or []:
            iid = _as_int(r.get("id"))
            if iid is None:
                continue
            items.append({
                "id": iid,
                "name": str(r.get("name") or "Item"),
                "icon": _icon_fetched(iid, r.get("item_icon_url") or ""),
                "item_icon_url": resolve_item_icon_url(iid, r.get("item_icon_url") or "", base_url=BASE_URL),
                "prices": _norm_prices(r.get("min_prices")),
                "online_stores": int(r.get("online_stores") or 0),
                "is_costume": bool(r.get("is_costume", False)),
                "monitored": iid in monitored_ids,
            })

        # Fallback: pesquisa só por ID (ex.: «1234» ou «@ws 1234»).
        if not items:
            direct = ItemSearchService.parse_direct_item_id(q)
            if direct is not None:
                try:
                    stores, meta = get_stores_from_item_page(direct, "", force_refresh=True)
                    items.append({
                        "id": direct,
                        "name": str((meta or {}).get("name") or f"Item {direct}"),
                        "icon": _icon_fetched(direct, (meta or {}).get("item_icon_url") or ""),
                        "item_icon_url": resolve_item_icon_url(direct, (meta or {}).get("item_icon_url") or "", base_url=BASE_URL),
                        "prices": sale_min_prices_from_stores(stores or []),
                        "online_stores": len(stores or []),
                        "is_costume": False,
                        "monitored": direct in monitored_ids,
                    })
                except Exception:  # noqa: BLE001
                    pass

        try:
            data = load_data()
            _append_search(data, q, len(items))
            save_data(data)
        except Exception:  # noqa: BLE001
            pass

        return {"ok": True, "query": q, "items": items}

    def add_item(self, item) -> dict:
        item = item or {}
        iid = _as_int(item.get("id"))
        if iid is None:
            return {"ok": False, "error": "id inválido", **self.get_home()}
        data = load_data()
        monitored = list(data.get("monitored") or [])
        if any(_as_int(m.get("id")) == iid for m in monitored):
            return {"ok": False, "error": "já monitorado", **self.get_home()}

        cats = data.get("monitor_categories") or list(DEFAULT_CATEGORIES)
        category = str(item.get("category") or "Gerais")
        if category not in cats:
            category = "Gerais"

        name = str(item.get("name") or "Item").strip() or "Item"
        icon_url = str(item.get("item_icon_url") or "").strip()
        prices = item.get("prices") if isinstance(item.get("prices"), dict) else {}

        if _is_generic_item_name(name) or not icon_url:
            try:
                stores, meta = get_stores_from_item_page(iid, "", force_refresh=True)
                meta = meta or {}
                real_name = str(meta.get("name") or meta.get("item_card_title") or "").strip()
                if real_name and not _is_generic_item_name(real_name):
                    name = real_name
                if not icon_url:
                    icon_url = resolve_item_icon_url(
                        iid, meta.get("item_icon_url") or "", base_url=BASE_URL
                    )
                if not prices and stores:
                    prices = sale_min_prices_from_stores(stores or [])
            except Exception:  # noqa: BLE001
                pass

        entry = {
            "id": iid,
            "name": name,
            "is_costume": bool(item.get("is_costume", False)),
            "last_price": 0,
            "added_at": datetime.now().isoformat(),
            "category": category,
        }
        if icon_url:
            entry["item_icon_url"] = icon_url
            _icon_fetched(iid, icon_url)
        if prices:
            entry["min_prices"] = dict(prices)

        monitored.append(entry)
        data["monitored"] = monitored
        save_data(data)
        result = self.get_home()
        result["added"] = iid
        return result

    def repair_monitored_generic_names(self) -> dict:
        """Corrige monitorados salvos como «Item {id}» (nome + ícone em cache)."""
        data = load_data()
        monitored = list(data.get("monitored") or [])
        changed = 0
        for m in monitored:
            if not _is_generic_item_name(m.get("name")):
                continue
            iid = _as_int(m.get("id"))
            if iid is None:
                continue
            item_dirty = False
            try:
                stores, meta = get_stores_from_item_page(iid, "", force_refresh=True)
                meta = meta or {}
                real_name = str(meta.get("name") or meta.get("item_card_title") or "").strip()
                if real_name and not _is_generic_item_name(real_name):
                    m["name"] = real_name
                    item_dirty = True
                icon_url = resolve_item_icon_url(
                    iid,
                    m.get("item_icon_url") or meta.get("item_icon_url") or "",
                    base_url=BASE_URL,
                )
                if icon_url:
                    m["item_icon_url"] = icon_url
                    _icon_fetched(iid, icon_url)
                    item_dirty = True
                if stores:
                    mp = sale_min_prices_from_stores(stores or [])
                    if mp:
                        m["min_prices"] = mp
                        item_dirty = True
            except Exception:  # noqa: BLE001
                continue
            if item_dirty:
                changed += 1
        if changed:
            data["monitored"] = monitored
            save_data(data)
        result = self.get_home()
        result["repaired"] = changed
        return result

    # ── Monitorados (lista detalhada) ───────────────────────────────────

    def get_monitored_list(self) -> dict:
        """Lista plana de monitorados (ordem do utilizador) com preços e data."""
        data = load_data()
        monitored = list(data.get("monitored") or [])
        items = []
        for m in monitored:
            p = _item_payload(m)
            p["added"] = str(m.get("added_at") or "")[:10]
            p["category"] = str(m.get("category") or "Gerais")
            items.append(p)
        return {"ok": True, "items": items, "total": len(items)}

    def refresh_monitored_prices(self) -> dict:
        """Igual a refresh_prices mas devolve a lista plana (página Monitorados)."""
        self.refresh_prices()
        return self.get_monitored_list()

    # ── Alertas ─────────────────────────────────────────────────────────

    def get_alerts(self) -> dict:
        alerts = load_alerts()
        items = [_alert_view(k, a) for k, a in alerts.items()]
        return {"ok": True, "items": items, "total": len(items)}

    def refresh_alerts_prices(self) -> dict:
        """Atualiza os menores preços (por moeda) de cada alerta e grava."""
        alerts = load_alerts()
        if not alerts:
            return self.get_alerts()
        updates = {}
        for key, a in list(alerts.items()):
            iid = _as_int(a.get("item_id"))
            if iid is None:
                continue
            try:
                stores, meta = get_stores_from_item_page(iid, str(a.get("item_name") or ""), force_refresh=True)
            except Exception:  # noqa: BLE001
                continue
            upd = {
                "min_prices": sale_min_prices_from_stores(stores or [], min_refinement=alert_min_refinement(a)),
                "home_prices_updated_at": datetime.now().isoformat(),
            }
            if (meta or {}).get("item_icon_url"):
                upd["item_icon_url"] = _normalize_media_url(meta["item_icon_url"])
            updates[key] = upd
        if updates:
            with _ALERTS_IO_LOCK:
                cur = load_alerts()
                for k, u in updates.items():
                    if k in cur:
                        cur[k].update(u)
                save_alerts(cur)
        return self.get_alerts()

    def remove_alert(self, alert_key) -> dict:
        key = str(alert_key)
        alerts = load_alerts()
        if key in alerts:
            del alerts[key]
            save_alerts(alerts)
        return self.get_alerts()

    def add_alert(self, payload) -> dict:
        """Cria/atualiza um alerta (mesma chave/estrutura da app original)."""
        p = payload or {}
        iid = _as_int(p.get("item_id"))
        if iid is None:
            return {"ok": False, "error": "id inválido"}
        try:
            price_value = float(p.get("price") or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "valor inválido"}
        if price_value <= 0:
            return {"ok": False, "error": "o valor deve ser maior que zero"}

        sale_type = _norm_currency(p.get("sale_type"))
        atype = "above" if str(p.get("type")) == "above" else "below"

        ref_raw = str(p.get("refinement") or "").strip()
        refinement_val = None
        if ref_raw != "":
            try:
                refinement_val = int(ref_raw)
            except ValueError:
                return {"ok": False, "error": "refino inválido"}
            if refinement_val < 0 or refinement_val > 20:
                return {"ok": False, "error": "refino deve estar entre 0 e 20"}

        try:
            stores, meta = get_stores_from_item_page(iid, str(p.get("name") or ""), force_refresh=True)
        except Exception:  # noqa: BLE001
            stores, meta = [], {}
        mp = sale_min_prices_from_stores(stores or [], min_refinement=refinement_val)

        alerts = load_alerts()
        key = f"{iid}_{sale_type}"
        icon_url = p.get("item_icon_url") or (meta or {}).get("item_icon_url") or ""
        entry = {
            "item_id": iid,
            "item_name": str(p.get("name") or f"Item {iid}"),
            "price": price_value,
            "type": atype,
            "sale_type": sale_type,
            "notify_email": str(p.get("notify_email") or "").strip(),
            "condition_met": False,
            "created_at": datetime.now().isoformat(),
        }
        if icon_url:
            entry["item_icon_url"] = _normalize_media_url(icon_url)
        if mp:
            entry["min_prices"] = mp
        if refinement_val is not None:
            entry["refinement"] = refinement_val

        qual: list = []
        fx: list = []
        # Ofertas que já cumprem o critério ficam «vistas» — só notifica novas depois.
        try:
            from alert_monitor import (
                filter_stores_by_currency,
                filter_stores_by_refinement,
                listing_fingerprint,
                qualifying_stores_for_alert,
            )

            fx = filter_stores_by_currency(stores or [], entry["sale_type"])
            fx = filter_stores_by_refinement(fx, entry)
            qual = qualifying_stores_for_alert(entry, fx)
            entry["condition_met"] = len(qual) > 0
            entry["notified_listing_keys"] = [listing_fingerprint(s) for s in qual]
        except Exception:  # noqa: BLE001
            entry["notified_listing_keys"] = []
            entry["condition_met"] = False

        alerts[key] = entry
        save_alerts(alerts)

        if qual:
            try:
                self._alert_worker.notify_if_already_met(key, entry, fx)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Alerta criado — notificação imediata falhou: %s", exc)

        return {"ok": True, "key": key, **self.get_alerts()}

    def get_alert_notifications(self, unread_only=False, limit=200) -> dict:
        only = bool(unread_only)
        try:
            lim = max(1, min(int(limit or 200), 200))
        except (TypeError, ValueError):
            lim = 200
        result = self._alert_worker.get_notifications(unread_only=only, limit=lim)
        alerts = load_alerts()
        for n in result.get("items") or []:
            iid = _as_int(n.get("item_id"))
            url = str(n.get("item_icon_url") or "")
            if not url and iid is not None:
                key = str(n.get("alert_key") or "")
                a = alerts.get(key) or {}
                url = str(a.get("item_icon_url") or "")
            n["icon"] = _icon_data_uri(iid, url) if iid is not None else ""
        return result

    def mark_alert_notifications_read(self, ids=None) -> dict:
        return self._alert_worker.mark_read(ids)

    def remove_alert_notification(self, notif_id) -> dict:
        return self._alert_worker.remove_notification(str(notif_id or ""))

    def clear_alert_notifications(self) -> dict:
        return self._alert_worker.clear_all()

    def run_alert_check_now(self) -> dict:
        """Força uma verificação imediata (útil para testes)."""
        events = self._alert_worker.run_pass()
        note = self._alert_worker.get_notifications(unread_only=False)
        return {"ok": True, "fired": len(events), "unread": note.get("unread") or 0}

    # ── Histórico de buscas ─────────────────────────────────────────────

    def get_searches(self) -> dict:
        data = load_data()
        return {"ok": True, "items": list(data.get("searches") or [])}

    # ── Configurações ───────────────────────────────────────────────────

    _CFG_KEYS = (
        "notify_email", "smtp_host", "smtp_port", "smtp_user", "smtp_password",
        "smtp_use_tls", "alert_interval_seconds", "start_with_windows", "ui_theme",
        "divine_pride_api_key", "divine_pride_server", "mvp_alert_sound_path",
    )

    def get_settings(self) -> dict:
        s = load_settings()
        return {"ok": True, "settings": {k: s.get(k) for k in self._CFG_KEYS}}

    def save_settings_web(self, payload) -> dict:
        p = payload or {}
        data = load_settings()

        def _int(key, default, lo, hi):
            try:
                v = int(str(p.get(key, data.get(key, default))).strip() or default)
            except (TypeError, ValueError):
                return None
            return max(lo, min(hi, v))

        port = _int("smtp_port", 587, 1, 65535)
        if port is None:
            return {"ok": False, "error": "Porta SMTP inválida."}
        interval = _int("alert_interval_seconds", 300, 60, 86400)
        if interval is None:
            return {"ok": False, "error": "Intervalo inválido."}

        data["notify_email"] = str(p.get("notify_email") or "").strip()
        data["smtp_host"] = str(p.get("smtp_host") or "").strip()
        data["smtp_port"] = port
        data["smtp_user"] = str(p.get("smtp_user") or "").strip()
        data["smtp_password"] = str(p.get("smtp_password") or "")
        data["smtp_use_tls"] = bool(p.get("smtp_use_tls"))
        data["alert_interval_seconds"] = interval
        data["start_with_windows"] = bool(p.get("start_with_windows"))
        data["ui_theme"] = "light" if str(p.get("ui_theme")) == "light" else "dark"
        data["divine_pride_api_key"] = str(p.get("divine_pride_api_key") or "").strip()
        data["divine_pride_server"] = str(p.get("divine_pride_server") or "").strip() or "iRO"
        data["mvp_alert_sound_path"] = str(p.get("mvp_alert_sound_path") or "").strip()
        save_settings(data)

        msg = "Configurações guardadas."
        ok_auto, auto_msg = set_windows_autostart(data["start_with_windows"])
        if auto_msg:
            msg += f" {auto_msg}"
        return {"ok": True, "message": msg, "settings": {k: data.get(k) for k in self._CFG_KEYS}}

    def test_email(self, payload) -> dict:
        p = payload or {}
        to_addr = str(p.get("notify_email") or "").strip()
        if not to_addr:
            return {"ok": False, "error": "Indique o e-mail destino."}
        from alert_monitor import send_alert_email

        st = load_settings()
        try:
            port = int(str(p.get("smtp_port") or st.get("smtp_port") or 587).strip() or "587")
        except (TypeError, ValueError):
            port = 587
        cfg = {
            **st,
            "smtp_host": str(p.get("smtp_host") or "").strip(),
            "smtp_port": port,
            "smtp_user": str(p.get("smtp_user") or "").strip(),
            "smtp_password": str(p.get("smtp_password") or ""),
            "smtp_use_tls": bool(p.get("smtp_use_tls")),
        }
        ok, err = send_alert_email(
            cfg, to_addr, "[GDZ] Teste de e-mail",
            "Se recebeu esta mensagem, o SMTP está configurado correctamente.",
        )
        return {"ok": bool(ok), "error": "" if ok else str(err)}

    def test_divine_pride(self, payload) -> dict:
        p = payload or {}
        key = str(p.get("divine_pride_api_key") or "").strip()
        srv = str(p.get("divine_pride_server") or "").strip() or None
        if not key:
            return {"ok": False, "error": "Indique a chave API Divine Pride."}
        try:
            from divine_pride_api import fetch_item

            d = fetch_item(5017, api_key=key, server=srv)
            return {"ok": True, "message": f"Ligação OK. Item 5017: {d.get('name') or '?'}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    # ── Auto Loot ───────────────────────────────────────────────────────

    def _loot(self):
        if getattr(self, "_loot_mgr", None) is None:
            from loot_manager import LootManager

            self._loot_mgr = LootManager()
        return self._loot_mgr

    def _loot_state(self) -> dict:
        mgr = self._loot()
        groups = []
        for n in sorted(mgr.groups):
            g = mgr.groups[n]
            items = []
            for it in g.items:
                iid = int(it.id)
                items.append({
                    "id": iid,
                    "name": str(it.name or f"Item {iid}"),
                    "type": str(getattr(it, "type", "") or ""),
                    "npc_sell_price": int(getattr(it, "npc_sell_price", 0) or 0),
                    "icon": _icon_data_uri(iid, getattr(it, "icon_url", "") or ""),
                })
            groups.append({
                "number": g.number,
                "name": str(g.name or f"Lista {g.number}"),
                "autoload": bool(g.autoload),
                "items": items,
                "count": len(items),
                "save_cmd": mgr.cmd_save(g.number),
                "load_cmd": mgr.cmd_load(g.number),
            })
        return {"ok": True, "groups": groups, "max_items": 10, "max_groups": 9}

    def loot_get(self) -> dict:
        return self._loot_state()

    def loot_search(self, query) -> dict:
        from loot_manager import search_item

        q = str(query or "").strip()
        if not q:
            return {"ok": True, "items": []}
        # Vários IDs separados por vírgula (ex.: "522, 2610").
        multi = [p.strip() for p in q.split(",")] if "," in q else []
        rows = []
        try:
            if multi and all(p.isdigit() for p in multi if p):
                seen = set()
                for p in multi:
                    if not p:
                        continue
                    for r in search_item(p):
                        rid = int(r.get("id") or 0)
                        if rid and rid not in seen:
                            seen.add(rid)
                            rows.append(r)
            else:
                rows = search_item(q)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "items": []}

        items = []
        for r in rows or []:
            iid = int(r.get("id") or 0)
            if not iid:
                continue
            items.append({
                "id": iid,
                "name": str(r.get("name") or f"Item {iid}"),
                "type": str(r.get("type") or ""),
                "npc_sell_price": int(r.get("npc_sell_price") or 0),
                "icon": _icon_data_uri(iid, r.get("icon_url") or ""),
                "icon_url": str(r.get("icon_url") or ""),
            })
        return {"ok": True, "items": items}

    def loot_add(self, group_number, item) -> dict:
        from loot_manager import LootItem

        it = item or {}
        iid = _as_int(it.get("id"))
        if iid is None:
            return {"ok": False, "error": "id inválido", **self._loot_state()}
        mgr = self._loot()
        added = mgr.add_item(
            int(group_number),
            LootItem(
                id=iid,
                name=str(it.get("name") or f"Item {iid}"),
                type=str(it.get("type") or ""),
                icon_url=str(it.get("icon_url") or ""),
                npc_sell_price=int(it.get("npc_sell_price") or 0),
            ),
        )
        if not added:
            return {"ok": False, "error": "Grupo cheio (10) ou item duplicado.", **self._loot_state()}
        mgr.save_to_file()
        return {"ok": True, **self._loot_state()}

    def loot_remove(self, group_number, item_id) -> dict:
        mgr = self._loot()
        mgr.remove_item(int(group_number), int(item_id))
        mgr.save_to_file()
        return {"ok": True, **self._loot_state()}

    def loot_add_group(self) -> dict:
        from loot_manager import LootGroup

        mgr = self._loot()
        existing = sorted(int(n) for n in mgr.groups.keys())
        new_n = next((n for n in range(1, 10) if n not in existing), None)
        if new_n is None:
            return {"ok": False, "error": "Limite de 9 grupos atingido.", **self._loot_state()}
        mgr.groups[new_n] = LootGroup(number=new_n, name=f"Lista {new_n}", autoload=False, items=[])
        mgr.save_to_file()
        return {"ok": True, **self._loot_state()}

    def loot_delete_group(self, group_number) -> dict:
        mgr = self._loot()
        if len(mgr.groups) <= 1:
            return {"ok": False, "error": "É necessário manter pelo menos 1 lista.", **self._loot_state()}
        mgr.groups.pop(int(group_number), None)
        mgr.save_to_file()
        return {"ok": True, **self._loot_state()}

    def loot_rename(self, group_number, name) -> dict:
        mgr = self._loot()
        mgr.set_group_name(int(group_number), str(name or ""))
        mgr.save_to_file()
        return {"ok": True, **self._loot_state()}

    # ── Simulação de Build ──────────────────────────────────────────────

    def build_meta(self) -> dict:
        from build_simulator import BUILD_SLOT_LEFT, BUILD_SLOT_RIGHT, SLOT_LABELS_PT
        from build_classes import SERVER_LIMITS, class_catalog, default_character
        from build_stats import stat_schema

        return {
            "ok": True,
            "left": list(BUILD_SLOT_LEFT),
            "right": list(BUILD_SLOT_RIGHT),
            "labels": {k: SLOT_LABELS_PT.get(k, k) for k in (BUILD_SLOT_LEFT + BUILD_SLOT_RIGHT)},
            "stats": stat_schema(),
            "server": dict(SERVER_LIMITS),
            "classes": class_catalog(),
            "default_character": default_character(),
        }

    def build_list(self) -> dict:
        from build_simulator import load_builds_file

        data = load_builds_file()
        saved = [x for x in (data.get("saved") or []) if isinstance(x, dict)]
        primary = (load_settings().get("primary_build_sim_saved_id") or "").strip()
        return {
            "ok": True,
            "builds": [{"id": str(s.get("id") or ""), "name": str(s.get("name") or "Build")} for s in saved],
            "primary_id": primary,
        }

    def build_load(self, build_id) -> dict:
        from build_simulator import (
            BUILD_SLOT_LEFT, BUILD_SLOT_RIGHT, default_slot_state, load_builds_file,
        )

        from build_stats import normalize_base_stats, parse_weapon_base
        from build_classes import normalize_character

        bid = str(build_id or "")
        data = load_builds_file()
        b = next((s for s in (data.get("saved") or []) if isinstance(s, dict) and str(s.get("id")) == bid), None)
        if not b:
            return {"ok": False, "error": "build não encontrada"}
        try:
            hpr = int(b.get("hp_per_rmt") or 30)
        except (TypeError, ValueError):
            hpr = 30
        cells = {"equip": {}, "visual": {}}
        for layer in ("equip", "visual"):
            src = b.get(layer) if isinstance(b.get(layer), dict) else {}
            for sk in (BUILD_SLOT_LEFT + BUILD_SLOT_RIGHT):
                raw = src.get(sk) if isinstance(src.get(sk), dict) else {}
                cell = default_slot_state()
                for k, v in (raw or {}).items():
                    if k == "item_id" and v is not None:
                        try:
                            v = int(v)
                        except (TypeError, ValueError):
                            v = None
                    if k in cell or k in ("item_icon_url", "item_stats", "item_description", "weapon_base", "manual_price", "price_rmt", "price_hp"):
                        cell[k] = v
                iid = _as_int(cell.get("item_id"))
                desc = str(cell.get("item_description") or "")
                ref = int(cell.get("refine") or 0)
                wb = cell.get("weapon_base") if isinstance(cell.get("weapon_base"), dict) else None
                if wb is None and iid and desc and sk in ("weapon_right", "weapon_left"):
                    wb = parse_weapon_base(desc, refine=ref)
                cells[layer][sk] = {
                    "item_id": iid,
                    "item_name": str(cell.get("item_name") or ""),
                    "refine": int(cell.get("refine") or 0),
                    "is_2h": bool(cell.get("is_2h")),
                    "icon": _icon_data_uri(iid, cell.get("item_icon_url") or "") if iid else "",
                    "item_icon_url": str(cell.get("item_icon_url") or ""),
                    "manual_price": bool(cell.get("manual_price")),
                    "price_rmt": _optional_float(cell.get("price_rmt")),
                    "price_hp": _optional_float(cell.get("price_hp")),
                    "item_stats": cell.get("item_stats") if isinstance(cell.get("item_stats"), dict) else None,
                    "item_description": desc,
                    "weapon_base": wb,
                }
        base_stats = normalize_base_stats(b.get("base_stats"))
        character = normalize_character(b.get("character"))
        return {
            "ok": True, "id": bid, "name": str(b.get("name") or "Build"),
            "hp_per_rmt": hpr, "cells": cells, "base_stats": base_stats,
            "character": character,
        }

    def build_resolve(self, query, refine) -> dict:
        """Resolve um item por ID para um slot: nome, ícone, 2-mãos e preço (RMT/HP)."""
        import re as _re

        from app_runtime import api_search_item_names
        from build_simulator import item_meta_is_two_handed
        from build_stats import parse_item_stats, parse_weapon_base

        q = str(query or "").strip()
        low = q.lower()
        if low.startswith("@ws"):
            q = q[3:].strip()
        elif low.startswith("ws") and len(q) > 2 and q[2].isspace():
            q = q[2:].strip()
        digits = _re.sub(r"\D", "", q)
        if not digits:
            return {"ok": False, "error": "Use só o ID numérico do item."}
        iid = int(digits)
        try:
            ref = max(0, min(20, int(refine)))
        except (TypeError, ValueError):
            ref = 0

        name = f"Item {iid}"
        try:
            for r in api_search_item_names(str(iid)) or []:
                if int(r.get("id", 0) or 0) == iid and r.get("name"):
                    name = str(r.get("name")).strip()
                    break
        except Exception:  # noqa: BLE001
            pass
        try:
            stores, meta = get_stores_from_item_page(iid, "", force_refresh=True)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        is2 = item_meta_is_two_handed(meta)
        icon_u = (meta or {}).get("item_icon_url") or ""
        desc = str((meta or {}).get("item_description") or "").strip()
        item_stats = parse_item_stats(desc, refine=ref)
        weapon_base = parse_weapon_base(desc, refine=ref)
        prices = _build_slot_price(iid, ref, stores)
        return {
            "ok": True,
            "id": iid, "item_name": name, "refine": ref, "is_2h": bool(is2),
            "icon": _icon_data_uri(iid, icon_u),
            "item_icon_url": _normalize_media_url(icon_u) if icon_u else "",
            "description": desc,
            "item_stats": item_stats,
            "weapon_base": weapon_base,
            "prices": prices,
        }

    def build_prices(self, cells, hp_per_rmt) -> dict:
        """Recalcula preços de todos os slots, taxa RMT/HP de mercado e totais."""
        from build_simulator import (
            DEFAULT_HP_PER_RMT,
            HP_REFERENCE_ITEM_ID,
            accumulate_build_currency_totals,
            fetch_hp_conversion_from_market,
        )

        cells = cells or {}
        slots = {"equip": {}, "visual": {}}
        market_entries = []
        manual_entries = []

        for layer in ("equip", "visual"):
            layer_cells = cells.get(layer) or {}
            for sk, cell in layer_cells.items():
                iid = _as_int((cell or {}).get("item_id"))
                if iid is None:
                    slots[layer][sk] = {"rmt": None, "hp": None}
                    continue

                if (cell or {}).get("manual_price"):
                    pr = {
                        "rmt": _optional_float((cell or {}).get("price_rmt")),
                        "hp": _optional_float((cell or {}).get("price_hp")),
                    }
                    slots[layer][sk] = pr
                    manual_entries.append(pr)
                    continue

                try:
                    ref = max(0, min(20, int((cell or {}).get("refine") or 0)))
                except (TypeError, ValueError):
                    ref = 0
                pr = _build_slot_price(iid, ref)
                slots[layer][sk] = pr
                market_entries.append(pr)

        conv = fetch_hp_conversion_from_market(
            lambda iid, name: get_stores_from_item_page(iid, name, force_refresh=True)
        )
        rate = conv.get("hp_per_rmt")
        if rate is None or rate <= 0:
            try:
                rate = float(hp_per_rmt or DEFAULT_HP_PER_RMT)
            except (TypeError, ValueError):
                rate = DEFAULT_HP_PER_RMT
            conv_source = "fallback"
        else:
            conv_source = conv.get("source") or "reference_item"
        if rate <= 0:
            rate = DEFAULT_HP_PER_RMT

        market_totals = accumulate_build_currency_totals(market_entries, rate)
        manual_totals = accumulate_build_currency_totals(manual_entries, rate)

        return {
            "ok": True,
            "slots": slots,
            "hp_per_rmt": rate,
            "rmt_per_100k_hp": conv.get("rmt_per_100k_hp") or (100_000.0 / rate if rate > 0 else None),
            "conversion_samples": conv.get("samples") or 0,
            "conversion_source": conv_source,
            "reference_item_id": conv.get("reference_item_id") or HP_REFERENCE_ITEM_ID,
            "market_totals": market_totals,
            "manual_totals": manual_totals,
            "total_rmt": market_totals.get("total_rmt") or 0.0,
            "total_hp_equiv": market_totals.get("total_hp") or 0.0,
        }

    def build_save(self, payload) -> dict:
        import uuid as _uuid
        from datetime import datetime as _dt

        from build_simulator import (
            BUILD_SLOT_LEFT, BUILD_SLOT_RIGHT, default_slot_state,
            load_builds_file, save_builds_file,
        )
        from build_stats import normalize_base_stats
        from build_classes import normalize_character

        p = payload or {}
        name = str(p.get("name") or "Build").strip() or "Build"
        try:
            hpr = int(p.get("hp_per_rmt") or 30)
        except (TypeError, ValueError):
            hpr = 30
        cells_in = p.get("cells") or {}

        def layer_dict(layer):
            out = {}
            src = cells_in.get(layer) or {}
            for sk in (BUILD_SLOT_LEFT + BUILD_SLOT_RIGHT):
                c = src.get(sk) or {}
                cell = default_slot_state()
                cell["item_id"] = _as_int(c.get("item_id"))
                cell["item_name"] = str(c.get("item_name") or "")
                try:
                    cell["refine"] = max(0, min(20, int(c.get("refine") or 0)))
                except (TypeError, ValueError):
                    cell["refine"] = 0
                cell["is_2h"] = bool(c.get("is_2h"))
                cell["item_icon_url"] = str(c.get("item_icon_url") or "")
                cell["manual_price"] = bool(c.get("manual_price"))
                cell["price_rmt"] = _optional_float(c.get("price_rmt"))
                cell["price_hp"] = _optional_float(c.get("price_hp"))
                if isinstance(c.get("item_stats"), dict):
                    cell["item_stats"] = c.get("item_stats")
                if c.get("item_description"):
                    cell["item_description"] = str(c.get("item_description") or "")
                if isinstance(c.get("weapon_base"), dict):
                    cell["weapon_base"] = c.get("weapon_base")
                out[sk] = cell
            return out

        base_stats = normalize_base_stats(p.get("base_stats"))
        character = normalize_character(p.get("character"))
        data = load_builds_file()
        saved = data.setdefault("saved", [])
        oid = str(p.get("id") or "").strip()
        entry = None
        if oid:
            for i, s in enumerate(saved):
                if isinstance(s, dict) and str(s.get("id")) == oid:
                    entry = {
                        "id": s.get("id"), "name": name, "saved_at": _dt.now().isoformat(),
                        "hp_per_rmt": hpr, "equip": layer_dict("equip"), "visual": layer_dict("visual"),
                        "base_stats": base_stats,
                        "character": character,
                        "alert_when_total_zeny_below": s.get("alert_when_total_zeny_below"),
                        "alert_when_total_hp_equiv_below": s.get("alert_when_total_hp_equiv_below"),
                        "notify_email": s.get("notify_email") or "",
                        "alert_total_armed": s.get("alert_total_armed", True),
                    }
                    saved[i] = entry
                    break
        if entry is None:
            entry = {
                "id": str(_uuid.uuid4()), "name": name, "saved_at": _dt.now().isoformat(),
                "hp_per_rmt": hpr, "equip": layer_dict("equip"), "visual": layer_dict("visual"),
                "base_stats": base_stats,
                "character": character,
                "alert_when_total_zeny_below": None, "alert_when_total_hp_equiv_below": None,
                "notify_email": "", "alert_total_armed": True,
            }
            saved.append(entry)
        save_builds_file(data)
        if p.get("make_primary"):
            cfg = load_settings()
            cfg["primary_build_sim_saved_id"] = str(entry.get("id") or "")
            save_settings(cfg)
        return {"ok": True, "id": entry["id"], **self.build_list()}

    def build_set_primary(self, build_id) -> dict:
        cfg = load_settings()
        cfg["primary_build_sim_saved_id"] = str(build_id or "")
        save_settings(cfg)
        return {"ok": True, **self.build_list()}

    def build_delete(self, build_id) -> dict:
        bid = str(build_id or "").strip()
        if not bid:
            return {"ok": False, "error": "ID inválido", **self.build_list()}
        from build_simulator import load_builds_file, save_builds_file

        data = load_builds_file()
        saved = [s for s in (data.get("saved") or []) if isinstance(s, dict)]
        if len(saved) <= 1:
            return {"ok": False, "error": "Não é possível excluir a única build", **self.build_list()}
        if not any(str(s.get("id")) == bid for s in saved):
            return {"ok": False, "error": "Build não encontrada", **self.build_list()}

        data["saved"] = [s for s in saved if str(s.get("id")) != bid]
        save_builds_file(data)
        cfg = load_settings()
        if str(cfg.get("primary_build_sim_saved_id") or "") == bid:
            cfg["primary_build_sim_saved_id"] = ""
            save_settings(cfg)
        return {"ok": True, **self.build_list()}

    # ── Timer MVP ───────────────────────────────────────────────────────

    def mvp_cards(self, filter_mode="todos", query="") -> dict:
        from mvp_timer import (
            load_mvp_catalog_cache, load_mvp_storage,
            mvp_catalog_entry_skipped, mvp_catalog_matches_search,
            next_spawn_at, seconds_until_spawn,
        )

        catalog = load_mvp_catalog_cache() or []
        data = load_mvp_storage()
        by_mid = {}
        for e in data.get("entries") or []:
            mid = _as_int(e.get("monster_id"))
            if mid is not None and mid not in by_mid:
                by_mid[mid] = e

        base = []
        for it in catalog:
            if not isinstance(it, dict) or mvp_catalog_entry_skipped(it):
                continue
            mid = _as_int(it.get("id"))
            if not mid:
                continue
            base.append(it)
        total = len(base)

        q = str(query or "").strip()
        if q:
            base = [it for it in base if mvp_catalog_matches_search(it, q)]

        mode = str(filter_mode or "todos")
        cards = []
        for it in base:
            mid = int(it["id"])
            ent = by_mid.get(mid)
            su = seconds_until_spawn(ent) if ent else None
            if mode == "ativos" and (not ent or su is None):
                continue
            if mode == "pendente" and (su is None or su <= 0):
                continue
            if mode == "disponiveis" and (su is None or su >= 0):
                continue
            nxt = next_spawn_at(ent) if ent else None
            dm = str((ent or {}).get("death_map") or "").strip()
            dx, dy = (ent or {}).get("death_x"), (ent or {}).get("death_y")
            cards.append({
                "id": mid,
                "name": str(it.get("name") or f"MVP {mid}"),
                "death_map": dm,
                "coords": (f"{dx}, {dy}" if dx is not None and dy is not None else ""),
                "next_ms": int(nxt.timestamp() * 1000) if nxt else None,
                "respawn_min": max(1, int((ent or {}).get("respawn_seconds") or 3600) // 60) if ent else None,
                "registered": ent is not None,
                "entry_id": (ent or {}).get("entry_id") if ent else None,
            })
        return {"ok": True, "cards": cards, "shown": len(cards), "total": total}

    def mvp_sprite(self, monster_id, name="") -> dict:
        from mvp_timer import resolve_mob_image

        mid = _as_int(monster_id)
        if mid is None:
            return {"ok": False, "icon": ""}
        try:
            raw, _src = resolve_mob_image(mid, display_name=str(name or ""))
            if not raw:
                return {"ok": False, "icon": ""}
            return {"ok": True, "icon": "data:image/png;base64," + base64.b64encode(raw).decode("ascii")}
        except Exception:  # noqa: BLE001
            return {"ok": False, "icon": ""}

    def mvp_register(self, monster_id) -> dict:
        from divine_pride_api import fetch_monster
        from mvp_timer import (
            load_mvp_storage, new_timer_entry, save_mvp_storage,
            summarize_monster_for_timer,
        )

        mid = _as_int(monster_id)
        if mid is None:
            return {"ok": False, "error": "id inválido"}
        cfg = load_settings()
        key = (cfg.get("divine_pride_api_key") or "").strip()
        if not key:
            return {"ok": False, "error": "Configure a chave Divine Pride em Configurações para registar MVPs."}
        srv = (cfg.get("divine_pride_server") or "").strip() or None
        data = load_mvp_storage()
        if any(_as_int(e.get("monster_id")) == mid for e in data.get("entries") or []):
            return {"ok": False, "error": "Este MVP já está na lista de timers."}
        try:
            mobj = fetch_monster(mid, api_key=key, server=srv)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        summ = summarize_monster_for_timer(mobj)
        maps = summ["spawn_maps"]
        entry = new_timer_entry(
            summ["monster_id"], summ["name"], maps, summ["respawn_seconds"],
            death_map=(maps[0] if maps else ""), death_at_iso="",
        )
        data.setdefault("entries", []).append(entry)
        save_mvp_storage(data)
        return {"ok": True, "entry_id": entry["entry_id"], "is_mvp": summ["is_mvp"]}

    def mvp_get_entry(self, entry_id) -> dict:
        from mvp_timer import load_mvp_catalog_cache, load_mvp_storage

        eid = str(entry_id)
        data = load_mvp_storage()
        ent = next((e for e in data.get("entries") or [] if e.get("entry_id") == eid), None)
        if not ent:
            return {"ok": False, "error": "timer não encontrado"}
        maps = [str(x).strip() for x in (ent.get("spawn_maps") or []) if str(x).strip()]
        if not maps:
            mid = _as_int(ent.get("monster_id"))
            for it in load_mvp_catalog_cache() or []:
                if _as_int(it.get("id")) == mid:
                    maps = [str(x).strip() for x in (it.get("spawn_maps") or []) if str(x).strip()]
                    break
        raw_death = str(ent.get("death_at") or "").strip()
        death_s = raw_death[:16].replace("T", " ") if raw_death else ""
        return {
            "ok": True,
            "entry_id": eid,
            "name": str(ent.get("name") or "MVP"),
            "maps": maps,
            "death_map": str(ent.get("death_map") or "").strip(),
            "death_at": death_s,
            "respawn_min": max(1, int(ent.get("respawn_seconds") or 3600) // 60),
            "death_x": ent.get("death_x"),
            "death_y": ent.get("death_y"),
        }

    def mvp_save_entry(self, entry_id, patch) -> dict:
        from mvp_timer import load_mvp_storage, next_spawn_at, parse_user_datetime, save_mvp_storage

        eid = str(entry_id)
        p = patch or {}
        data = load_mvp_storage()
        ent = next((e for e in data.get("entries") or [] if e.get("entry_id") == eid), None)
        if not ent:
            return {"ok": False, "error": "timer não encontrado"}
        raw_death = str(p.get("death_at") or "").strip()
        if raw_death:
            dt = parse_user_datetime(raw_death)
            if not dt:
                return {"ok": False, "error": "Data/hora de morte inválida (use AAAA-MM-DD HH:MM)."}
            ent["death_at"] = dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            ent["death_at"] = ""
        # Cada gravação reinicia o ciclo de alerta e a contagem.
        ent["alert_fired"] = False
        try:
            ent["respawn_seconds"] = max(60, int(p.get("respawn_min") or 60) * 60)
        except (TypeError, ValueError):
            pass
        ent["death_map"] = str(p.get("death_map") or "").strip()
        for axis in ("death_x", "death_y"):
            v = p.get(axis)
            if v is None or str(v).strip() == "":
                ent[axis] = None
            else:
                try:
                    ent[axis] = int(v)
                except (TypeError, ValueError):
                    ent[axis] = None
        save_mvp_storage(data)
        nxt = next_spawn_at(ent)
        return {
            "ok": True,
            "next_ms": int(nxt.timestamp() * 1000) if nxt else None,
            "respawn_min": max(1, int(ent.get("respawn_seconds") or 3600) // 60),
        }

    def mvp_reset_all(self) -> dict:
        from mvp_timer import load_mvp_storage, save_mvp_storage

        data = load_mvp_storage()
        entries = data.get("entries") or []
        for e in entries:
            e["death_at"] = ""
            e["death_x"] = None
            e["death_y"] = None
            e["alert_fired"] = False
        save_mvp_storage(data)
        return {"ok": True, "count": len(entries)}

    def mvp_map(self, map_name) -> dict:
        from mvp_timer import build_mvp_map_click_mask_from_image, resolve_map_image

        dm = str(map_name or "").strip()
        if not dm:
            return {"ok": False, "error": "sem mapa"}
        try:
            blob, _url = resolve_map_image(dm)
            if not blob:
                return {"ok": False, "error": f"Sem imagem do mapa «{dm}»."}
            from io import BytesIO

            from PIL import Image

            im = Image.open(BytesIO(blob)).convert("RGBA")
            nw, nh = im.size
            mw, mh, mask = build_mvp_map_click_mask_from_image(im)
            return {
                "ok": True,
                "image": "data:image/png;base64," + base64.b64encode(blob).decode("ascii"),
                "nw": nw, "nh": nh,
                "mask": base64.b64encode(bytes(mask)).decode("ascii"),
                "mw": mw, "mh": mh,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def mvp_check_spawns(self) -> dict:
        """Marca como avisados os MVPs que acabaram de nascer; devolve os novos (som/pop-up)."""
        from mvp_timer import load_mvp_storage, save_mvp_storage, seconds_until_spawn

        data = load_mvp_storage()
        fired = []
        changed = False
        for e in data.get("entries") or []:
            if e.get("alert_fired"):
                continue
            su = seconds_until_spawn(e)
            if su is None or su > 0:
                continue
            e["alert_fired"] = True
            changed = True
            maps = e.get("spawn_maps") or []
            fired.append({
                "name": str(e.get("name") or "MVP"),
                "map": str(e.get("death_map") or "") or (", ".join(m for m in maps if m) if maps else ""),
            })
        if changed:
            save_mvp_storage(data)
        return {"ok": True, "fired": fired}

    def ping(self) -> str:
        return "ok"
