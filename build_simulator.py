"""
Build Simulator — lógica de slots, preços por refino/cartas e alertas por custo total.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BUILDS_FILE = os.path.join(os.path.expanduser("~"), "herosaga_builds.json")

# Ordem visual: coluna esquerda (top→bottom), coluna direita (top→bottom)
BUILD_SLOT_LEFT = (
    "head_top",
    "head_low",
    "weapon_right",
    "robe",
    "accessory_left",
)
BUILD_SLOT_RIGHT = (
    "head_mid",
    "armor",
    "weapon_left",
    "shoes",
    "accessory_right",
)

SLOT_LABELS_PT: Dict[str, str] = {
    "head_top": "Topo (head)",
    "head_mid": "Meio (head)",
    "head_low": "Baixo (head)",
    "armor": "Armadura",
    "weapon_right": "Mão direita",
    "weapon_left": "Mão esq. / escudo",
    "robe": "Capa",
    "shoes": "Botas",
    "accessory_right": "Acessório dir.",
    "accessory_left": "Acessório esq.",
}

_TWO_HAND_RE = re.compile(
    r"duas?\s*m[aã]os|two[\s-]?hand(?:ed)?|2[\s-]?hand|duas\s*mãos|ambas\s*as\s*mãos",
    re.IGNORECASE,
)


def default_slot_state() -> Dict[str, Any]:
    return {
        "item_id": None,
        "item_name": "",
        "refine": 0,
        "cards": 0,
        "is_2h": False,
        "item_icon_url": "",
    }


def default_layer_state() -> Dict[str, Dict[str, Any]]:
    return {k: default_slot_state() for k in BUILD_SLOT_LEFT + BUILD_SLOT_RIGHT}


def load_builds_file() -> dict:
    if not os.path.exists(BUILDS_FILE):
        return {"version": 1, "saved": []}
    try:
        with open(BUILDS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return {"version": 1, "saved": []}
        raw.setdefault("version", 1)
        if not isinstance(raw.get("saved"), list):
            raw["saved"] = []
        return raw
    except Exception as e:
        logger.debug("load_builds_file: %s", e)
        return {"version": 1, "saved": []}


def save_builds_file(data: dict) -> None:
    merged = {"version": 1, "saved": []}
    if isinstance(data, dict):
        merged.update(data)
    if not isinstance(merged.get("saved"), list):
        merged["saved"] = []
    with open(BUILDS_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)


def _refinement(s: dict) -> int:
    for k in ("refinement", "refine", "enhancement"):
        v = s.get(k)
        if v is None or v == "":
            continue
        try:
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                return max(0, min(20, int(v)))
            t = str(v).strip().replace("+", " ")
            digits = "".join(filter(str.isdigit, t))
            if digits:
                return max(0, min(20, int(digits)))
        except (TypeError, ValueError):
            continue
    return 0


def _cards(s: dict) -> int:
    try:
        return int(s.get("cards") or s.get("slots") or 0)
    except (TypeError, ValueError):
        return 0


def filter_stores_slot(stores: List[dict], want_refine: int, want_cards: int) -> List[dict]:
    """Refino exacto; cartas 0 = qualquer contagem de slots na listagem."""
    out: List[dict] = []
    for s in stores or []:
        if _refinement(s) != int(want_refine):
            continue
        if int(want_cards) > 0 and _cards(s) != int(want_cards):
            continue
        out.append(s)
    return out


def _store_listing_qty(store: dict) -> int:
    for k in ("amount", "quantity", "qtd"):
        try:
            v = int(store.get(k) or 0)
            if v > 0:
                return v
        except (TypeError, ValueError):
            continue
    return 1


def min_prices_from_stores(stores: List[dict], *, only_qty_one: bool = False) -> Dict[str, float]:
    """Menor preço por moeda (zeny, rops, rmt, hero_points).

    Se *only_qty_one* for True, só entram listagens com quantidade 1 (coluna Qtd da
    página do item). No Herosaga o preço em «Valor» é sempre o da listagem; linhas
    com Qtd>1 não representam o mesmo tipo de oferta e distorcem o mínimo.
    """
    best: Dict[str, float] = {}
    for store in stores or []:
        if only_qty_one and _store_listing_qty(store) != 1:
            continue
        st = (store.get("sale_type") or "zeny").lower()
        if "hero" in st and "point" in st:
            key = "hero_points"
        elif "hero" in st:
            continue
        elif st in ("rmt", "rm", "rm$", "m") or "rmt" in st:
            key = "rmt"
        elif "rops" in st or st in ("rp", "r$"):
            key = "rops"
        elif st in ("zeny", "z", "z$"):
            key = "zeny"
        else:
            key = "zeny"
        try:
            price = float(store.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        if key not in best or price < best[key]:
            best[key] = price
    return best


REF_HP_BUNDLE = 100_000
HP_REFERENCE_ITEM_ID = 40111  # moeda de 100.000 Hero Points (referência RMT↔HP)
DEFAULT_HP_PER_RMT = 30.0

FetchStoresFn = Callable[[int, str], Tuple[List[dict], dict]]


def hp_per_rmt_from_pair(rmt: float, hp: float):
    try:
        r = float(rmt)
        h = float(hp)
    except (TypeError, ValueError):
        return None
    if r <= 0 or h <= 0:
        return None
    return h / r


def rmt_for_ref_hp(rmt: float, hp: float, ref_hp: float = REF_HP_BUNDLE):
    try:
        r = float(rmt)
        h = float(hp)
        ref = float(ref_hp)
    except (TypeError, ValueError):
        return None
    if r <= 0 or h <= 0 or ref <= 0:
        return None
    return r * (ref / h)


def derive_hp_per_rmt_from_reference_item(min_prices: dict) -> dict:
    """Taxa RMT↔HP a partir do menor preço RMT do item de referência (100.000 HP)."""
    try:
        min_rmt = float((min_prices or {}).get("rmt"))
    except (TypeError, ValueError):
        min_rmt = None
    if min_rmt is None or min_rmt <= 0:
        return {
            "hp_per_rmt": None,
            "rmt_per_100k_hp": None,
            "samples": 0,
            "source": "none",
            "reference_item_id": HP_REFERENCE_ITEM_ID,
        }
    hp_per_rmt = REF_HP_BUNDLE / min_rmt
    return {
        "hp_per_rmt": hp_per_rmt,
        "rmt_per_100k_hp": min_rmt,
        "samples": 1,
        "source": "reference_item",
        "reference_item_id": HP_REFERENCE_ITEM_ID,
    }


def fetch_hp_conversion_from_market(fetch_stores: FetchStoresFn) -> dict:
    """Consulta lojas do item ``HP_REFERENCE_ITEM_ID`` e devolve a taxa de conversão."""
    try:
        stores, _ = fetch_stores(HP_REFERENCE_ITEM_ID, "")
        matched = filter_stores_slot(stores or [], 0, 0)
        mp = min_prices_from_stores(matched, only_qty_one=True)
        if not mp:
            mp = min_prices_from_stores(stores or [], only_qty_one=True)
        return derive_hp_per_rmt_from_reference_item(mp)
    except Exception as e:
        logger.debug("fetch_hp_conversion_from_market(%s): %s", HP_REFERENCE_ITEM_ID, e)
        return derive_hp_per_rmt_from_reference_item({})


def resolve_build_hp_per_rmt(fetch_stores: FetchStoresFn, saved_rate=None) -> float:
    """Taxa efectiva: mercado (item 40111) → valor guardado → padrão."""
    conv = fetch_hp_conversion_from_market(fetch_stores)
    rate = conv.get("hp_per_rmt")
    if rate is not None and rate > 0:
        return float(rate)
    try:
        fallback = float(saved_rate if saved_rate is not None else DEFAULT_HP_PER_RMT)
    except (TypeError, ValueError):
        fallback = DEFAULT_HP_PER_RMT
    return fallback if fallback > 0 else DEFAULT_HP_PER_RMT


def derive_hp_per_rmt_from_pairs(pairs) -> dict:
    """Estima taxa de mercado a partir de pares (min RMT, min HP) do mesmo item/refino.

    Prioriza listagens cujo preço em HP está mais perto de ``REF_HP_BUNDLE`` (100.000 HP).
    """
    import math

    candidates = []
    for pair in pairs or []:
        if not isinstance(pair, (tuple, list)) or len(pair) < 2:
            continue
        rate = hp_per_rmt_from_pair(pair[0], pair[1])
        if rate is None:
            continue
        try:
            hp = float(pair[1])
        except (TypeError, ValueError):
            continue
        weight = 1.0 / (1.0 + abs(math.log10(max(hp, 1.0) / REF_HP_BUNDLE)))
        r100 = rmt_for_ref_hp(pair[0], pair[1])
        candidates.append({"rate": rate, "weight": weight, "rmt_per_100k": r100, "hp": hp, "rmt": float(pair[0])})

    if not candidates:
        return {
            "hp_per_rmt": None,
            "rmt_per_100k_hp": None,
            "samples": 0,
            "source": "none",
        }

    total_w = sum(c["weight"] for c in candidates)
    avg_rate = sum(c["rate"] * c["weight"] for c in candidates) / total_w
    avg_r100 = REF_HP_BUNDLE / avg_rate if avg_rate > 0 else None
    return {
        "hp_per_rmt": avg_rate,
        "rmt_per_100k_hp": avg_r100,
        "samples": len(candidates),
        "source": "market",
    }


def accumulate_build_currency_totals(entries, hp_per_rmt) -> dict:
    """Soma custos em RMT e HP, convertendo quando só existe uma moeda."""
    try:
        rate = float(hp_per_rmt or DEFAULT_HP_PER_RMT)
    except (TypeError, ValueError):
        rate = DEFAULT_HP_PER_RMT
    if rate <= 0:
        rate = DEFAULT_HP_PER_RMT

    total_rmt = 0.0
    total_hp = 0.0
    slots = 0

    for ent in entries or []:
        if not isinstance(ent, dict):
            continue
        r = ent.get("rmt")
        h = ent.get("hp")
        try:
            rv = float(r) if r is not None and r != "" else None
        except (TypeError, ValueError):
            rv = None
        try:
            hv = float(h) if h is not None and h != "" else None
        except (TypeError, ValueError):
            hv = None
        if rv is not None and rv <= 0:
            rv = None
        if hv is not None and hv <= 0:
            hv = None
        if rv is None and hv is None:
            continue
        slots += 1
        if rv is not None and hv is not None:
            total_rmt += min(rv, hv / rate)
            total_hp += min(hv, rv * rate)
        elif rv is not None:
            total_rmt += rv
            total_hp += rv * rate
        else:
            total_hp += hv
            total_rmt += hv / rate

    return {"total_rmt": total_rmt, "total_hp": total_hp, "slots": slots}


def item_meta_is_two_handed(meta: Optional[dict]) -> bool:
    if not meta:
        return False
    desc = (meta.get("item_description") or "") + " " + (meta.get("item_card_title") or "")
    return bool(_TWO_HAND_RE.search(desc))


def _parse_ts(s: str) -> Optional[datetime]:
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    try:
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00")[:19])
    except Exception:
        pass
    return None


def _sale_type_bucket(st: str) -> str:
    x = (st or "").lower()
    if "hero" in x and "point" in x:
        return "hero_points"
    if "rmt" in x or x in ("rm", "rm$", "m"):
        return "rmt"
    if "rops" in x or x in ("rp", "r$"):
        return "rops"
    return "zeny"


def price_variation_vs_7d_mean(
    sales: List[dict],
    *,
    currency: str = "zeny",
    current_price: Optional[float] = None,
) -> Tuple[Optional[float], Optional[float], int]:
    """
    Devolve (percentual vs média 7d, média 7d, n_amostras).
    *currency*: zeny | rmt | rops | hero_points
    """
    if not sales:
        return None, None, 0
    cutoff = datetime.now() - timedelta(days=7)
    want = (currency or "zeny").lower()
    prices: List[float] = []
    for s in sales:
        st = _sale_type_bucket(str(s.get("sale_type") or ""))
        if want == "zeny" and st != "zeny":
            continue
        if want == "rmt" and st != "rmt":
            continue
        if want == "rops" and st != "rops":
            continue
        if want == "hero_points" and st != "hero_points":
            continue
        dt = _parse_ts(str(s.get("sale_date") or s.get("timestamp") or ""))
        if dt is not None and dt < cutoff:
            continue
        try:
            p = float(s.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if p > 0:
            prices.append(p)
    if not prices:
        return None, None, 0
    avg = sum(prices) / float(len(prices))
    if current_price is None or current_price <= 0 or avg <= 0:
        return None, avg, len(prices)
    pct = (current_price - avg) / avg * 100.0
    return pct, avg, len(prices)


def sum_layer_totals(
    layer: Dict[str, Dict[str, Any]],
    fetch_stores: FetchStoresFn,
) -> Tuple[float, float, float, float, List[str]]:
    """
    Soma menores preços por moeda em todos os slots preenchidos de uma camada (equip ou visual).
    Devolve (zeny, rmt, rops, hero_points, erros_debug).
    """
    tot_z = tot_rmt = tot_rops = tot_hp = 0.0
    errs: List[str] = []
    keys = set(BUILD_SLOT_LEFT + BUILD_SLOT_RIGHT)
    for key in keys:
        cell = layer.get(key) or {}
        try:
            iid = int(cell.get("item_id") or 0)
        except (TypeError, ValueError):
            iid = 0
        if iid <= 0:
            continue
        name = str(cell.get("item_name") or "")
        try:
            ref = int(cell.get("refine") or 0)
        except (TypeError, ValueError):
            ref = 0
        try:
            stores, _ = fetch_stores(iid, name)
            matched = filter_stores_slot(stores, ref, 0)
            mp = min_prices_from_stores(matched, only_qty_one=True)
        except Exception as e:
            errs.append(f"{key}:{e}")
            continue
        if "zeny" in mp:
            tot_z += mp["zeny"]
        if "rmt" in mp:
            tot_rmt += mp["rmt"]
        if "rops" in mp:
            tot_rops += mp["rops"]
        if "hero_points" in mp:
            tot_hp += mp["hero_points"]
    return tot_z, tot_rmt, tot_rops, tot_hp, errs


def total_saved_build_zeny(
    build: dict,
    fetch_stores: FetchStoresFn,
) -> float:
    """Soma Zeny mínima (equip + visual) — usado só para alertas antigos (``alert_when_total_zeny_below``)."""
    eq = build.get("equip") if isinstance(build.get("equip"), dict) else {}
    vis = build.get("visual") if isinstance(build.get("visual"), dict) else {}
    z1, _, _, _, _ = sum_layer_totals(eq, fetch_stores)
    z2, _, _, _, _ = sum_layer_totals(vis, fetch_stores)
    return float(z1 + z2)


def total_saved_build_hp_equiv(
    build: dict,
    fetch_stores: FetchStoresFn,
    *,
    hp_per_rmt: Optional[float] = None,
) -> float:
    """Soma HP (Hero Points nas lojas) + RMT convertido com taxa de mercado ou da build."""
    if hp_per_rmt is not None:
        ratio = max(0.0, float(hp_per_rmt))
    else:
        ratio = resolve_build_hp_per_rmt(fetch_stores, build.get("hp_per_rmt"))
    eq = build.get("equip") if isinstance(build.get("equip"), dict) else {}
    vis = build.get("visual") if isinstance(build.get("visual"), dict) else {}
    _z1, r1, _o1, h1, _ = sum_layer_totals(eq, fetch_stores)
    _z2, r2, _o2, h2, _ = sum_layer_totals(vis, fetch_stores)
    tot_rmt = float(r1 + r2)
    tot_hp = float(h1 + h2)
    return tot_hp + tot_rmt * ratio


def saved_build_has_any_item(build: dict) -> bool:
    for layer_key in ("equip", "visual"):
        layer = build.get(layer_key)
        if not isinstance(layer, dict):
            continue
        for cell in layer.values():
            if not isinstance(cell, dict):
                continue
            try:
                if int(cell.get("item_id") or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def run_build_total_alerts(
    fetch_stores: FetchStoresFn,
) -> List[dict]:
    """
    Avalia builds guardados com limiar numérico:
    ``alert_when_total_hp_equiv_below`` (total RMT+HP equivalente) ou,
    em builds antigos, ``alert_when_total_zeny_below`` (total Zeny).

    Usa ``alert_total_armed``: quando o total volta acima do limiar, rearma.

    Devolve eventos com ``alert_kind`` ``"hp_equiv"`` | ``"zeny"``, ``total``, ``threshold``.
    """
    data = load_builds_file()
    saved = [b for b in (data.get("saved") or []) if isinstance(b, dict)]
    events: List[dict] = []
    changed = False
    market_hp_per_rmt = resolve_build_hp_per_rmt(fetch_stores, None)
    for b in saved:
        th_hp = b.get("alert_when_total_hp_equiv_below")
        th_z = b.get("alert_when_total_zeny_below")
        threshold = None
        alert_kind: Optional[str] = None
        if th_hp is not None and th_hp != "":
            try:
                threshold = float(th_hp)
            except (TypeError, ValueError):
                threshold = None
            if threshold is not None and threshold > 0:
                alert_kind = "hp_equiv"
        elif th_z is not None and th_z != "":
            try:
                threshold = float(th_z)
            except (TypeError, ValueError):
                threshold = None
            if threshold is not None and threshold > 0:
                alert_kind = "zeny"
        if threshold is None or threshold <= 0 or not alert_kind:
            continue
        bid = str(b.get("id") or "")
        if not bid:
            b["id"] = str(uuid.uuid4())
            bid = b["id"]
            changed = True
        if not saved_build_has_any_item(b):
            continue
        try:
            if alert_kind == "hp_equiv":
                total = total_saved_build_hp_equiv(
                    b,
                    fetch_stores,
                    hp_per_rmt=market_hp_per_rmt,
                )
            else:
                total = total_saved_build_zeny(b, fetch_stores)
        except Exception as e:
            logger.debug("build alert %s: %s", bid, e)
            continue
        if total <= 0:
            continue
        armed = b.get("alert_total_armed", True)
        if total < threshold:
            if armed:
                events.append(
                    {
                        "build_id": bid,
                        "build_name": str(b.get("name") or "Build"),
                        "total": total,
                        "total_zeny": total,
                        "threshold": threshold,
                        "notify_email": (b.get("notify_email") or "").strip(),
                        "alert_kind": alert_kind,
                    }
                )
                b["alert_total_armed"] = False
                changed = True
        else:
            if not armed:
                b["alert_total_armed"] = True
                changed = True
    if changed:
        save_builds_file(data)
    return events


def build_email_body_build_total(ev: dict) -> str:
    nm = ev.get("build_name") or "Build"
    tot = ev.get("total")
    if tot is None:
        tot = ev.get("total_zeny") or 0
    th = ev.get("threshold") or 0
    a = f"{int(round(tot)):,}".replace(",", ".")
    b = f"{int(round(th)):,}".replace(",", ".")
    kind = ev.get("alert_kind") or "zeny"
    if kind == "hp_equiv":
        return (
            "Alerta — GDZ Monitor (Simulação de Build)\n\n"
            f"Build: {nm}\n"
            f"Custo total estimado (HP equivalente: Hero Points nas lojas + RMT convertido): {a}\n"
            f"Limiar definido: {b}\n\n"
            "O custo total caiu abaixo do valor que configurou ao guardar a build."
        )
    return (
        "Alerta — GDZ Monitor (Simulação de Build)\n\n"
        f"Build: {nm}\n"
        f"Custo total estimado (Zeny, equip + visual, menores preços ao refino do slot): {a} Z\n"
        f"Limiar definido: {b} Z\n\n"
        "O custo total caiu abaixo do valor que configurou ao guardar a build."
    )
