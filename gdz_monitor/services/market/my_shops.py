"""
Regras puras da página "Minhas Lojas" (lojas próprias monitoradas).

O usuário registra lojas (vendor_id) dos seus personagens em autotrade.
Guardamos um *baseline* (snapshot do estoque no momento do registro) e, a cada
atualização, um *snapshot atual*. A diferença entre os dois diz o que foi
vendido, o que falta vender e quanto foi arrecadado/lucrado.

Sem rede e sem IO — tudo aqui é testável por pytest.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from gdz_monitor.services.market.price_parse import parse_price_cell


def parse_vendor_ref(text) -> Optional[int]:
    """Extrai o vendor_id de um link viewshop ou de um ID puro."""
    s = str(text or "").strip()
    if not s:
        return None
    if s.isdigit():
        try:
            vid = int(s)
        except (ValueError, OverflowError):
            return None
        return vid if vid > 0 else None
    m = re.search(r"[?&]id=(\d+)", s, re.I)
    if not m:
        return None
    try:
        vid = int(m.group(1))
    except (TypeError, ValueError):
        return None
    return vid if vid > 0 else None


def _clean_slot(val) -> str:
    s = str(val or "").strip()
    if s.lower() in ("", "nenhum", "n/a", "—", "-"):
        return ""
    return s


def item_key(item: dict) -> str:
    """
    Identidade de uma linha da loja: mesmo item com refino/cartas/preço
    diferentes são linhas distintas (em autotrade o preço não muda sem
    fechar a loja, logo preço faz parte da identidade da "leva").
    """
    unit_price = item.get("unit_price")
    if unit_price is None:
        unit_price = parse_price_cell(str(item.get("price_text") or ""))
    parts = [
        str(item.get("item_id") or 0),
        str(int(item.get("refinement") or 0)),
        _clean_slot(item.get("slot1")),
        _clean_slot(item.get("slot2")),
        _clean_slot(item.get("slot3")),
        _clean_slot(item.get("slot4")),
        _clean_slot(item.get("random_options")),
        ("%.4f" % float(unit_price or 0)).rstrip("0").rstrip("."),
    ]
    return "|".join(parts)


def snapshot_from_shop(shop: dict, *, taken_at: str = "") -> dict:
    """
    Converte o resultado de ``fetch_vendor_shop`` num snapshot persistível.
    Linhas com a mesma identidade têm as quantidades somadas.
    """
    items: Dict[str, dict] = {}
    for raw in (shop or {}).get("items") or []:
        if not isinstance(raw, dict):
            continue
        unit_price = parse_price_cell(str(raw.get("price_text") or ""))
        entry = {
            "item_id": raw.get("item_id"),
            "item_name": str(raw.get("item_name") or "—"),
            "icon_url": str(raw.get("icon_url") or ""),
            "refinement": int(raw.get("refinement") or 0),
            "slot1": _clean_slot(raw.get("slot1")),
            "slot2": _clean_slot(raw.get("slot2")),
            "slot3": _clean_slot(raw.get("slot3")),
            "slot4": _clean_slot(raw.get("slot4")),
            "random_options": _clean_slot(raw.get("random_options")),
            "price_text": str(raw.get("price_text") or ""),
            "unit_price": unit_price,
            "quantity": max(0, int(raw.get("quantity") or 0)),
        }
        key = item_key(entry)
        if key in items:
            items[key]["quantity"] += entry["quantity"]
        else:
            items[key] = entry
    return {"taken_at": str(taken_at or ""), "items": items}


def _coerce_cost(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        c = float(value)
    except (TypeError, ValueError):
        return None
    return c if c >= 0 else None


def diff_shop(baseline: dict, current: dict, *, costs: dict | None = None) -> dict:
    """
    Compara baseline × snapshot atual e devolve linhas + totais.

    - ``sold_qty = max(0, qtd_baseline - qtd_atual)`` (nunca negativo);
    - item ausente do snapshot atual = vendeu o restante;
    - quantidade atual MAIOR que o baseline = reposição (``restocked``) —
      não conta como venda até o usuário redefinir o baseline;
    - item que só existe no snapshot atual = ``new_item`` (também reposição).
    """
    base_items = dict((baseline or {}).get("items") or {})
    cur_items = dict((current or {}).get("items") or {})
    costs = costs or {}

    rows: List[Dict[str, Any]] = []
    keys = list(base_items.keys()) + [k for k in cur_items.keys() if k not in base_items]
    for key in keys:
        b = base_items.get(key)
        c = cur_items.get(key)
        ref = b or c or {}
        initial_qty = int((b or {}).get("quantity") or 0)
        current_qty = int((c or {}).get("quantity") or 0)
        sold_qty = max(0, initial_qty - current_qty)
        unit_price = float(ref.get("unit_price") or 0)
        revenue = sold_qty * unit_price
        unit_cost = _coerce_cost(costs.get(key))
        cost_spent = (unit_cost * sold_qty) if unit_cost is not None else None
        rows.append({
            "key": key,
            "item_id": ref.get("item_id"),
            "item_name": str(ref.get("item_name") or "—"),
            "icon_url": str(ref.get("icon_url") or ""),
            "refinement": int(ref.get("refinement") or 0),
            "slot1": str(ref.get("slot1") or ""),
            "slot2": str(ref.get("slot2") or ""),
            "slot3": str(ref.get("slot3") or ""),
            "slot4": str(ref.get("slot4") or ""),
            "random_options": str(ref.get("random_options") or ""),
            "price_text": str(ref.get("price_text") or ""),
            "unit_price": unit_price,
            "initial_qty": initial_qty,
            "current_qty": current_qty,
            "sold_qty": sold_qty,
            "revenue": revenue,
            "unit_cost": unit_cost,
            "cost_spent": cost_spent,
            "profit": (revenue - cost_spent) if cost_spent is not None else None,
            "restocked": current_qty > initial_qty and b is not None,
            "new_item": b is None,
        })

    rows.sort(key=lambda r: (str(r.get("item_name") or "").lower(), -r["unit_price"]))

    initial_total = sum(r["initial_qty"] for r in rows)
    sold_total = sum(r["sold_qty"] for r in rows)
    remaining_total = sum(r["current_qty"] for r in rows)
    revenue_total = sum(r["revenue"] for r in rows)
    cost_total = sum(r["cost_spent"] for r in rows if r["cost_spent"] is not None)
    totals = {
        "initial_qty": initial_total,
        "current_qty": remaining_total,
        "sold_qty": sold_total,
        "revenue": revenue_total,
        "cost_spent": cost_total,
        "profit": revenue_total - cost_total,
        "pct_sold": (sold_total / initial_total) if initial_total > 0 else 0.0,
        "has_costs": any(r["unit_cost"] is not None for r in rows),
        "restocked_any": any(r["restocked"] or r["new_item"] for r in rows),
        "item_count": len(rows),
    }
    return {"rows": rows, "totals": totals}


def shop_summary(entry: dict) -> dict:
    """Resumo de uma loja monitorada (para o card da lista) a partir do que está salvo."""
    diff = diff_shop(
        entry.get("baseline") or {},
        entry.get("last_snapshot") or entry.get("baseline") or {},
        costs=entry.get("costs") or {},
    )
    return {
        "vendor_id": entry.get("vendor_id"),
        "char_name": str(entry.get("char_name") or "—"),
        "shop_title": str(entry.get("shop_title") or "Loja"),
        "currency": str(entry.get("currency") or "zeny"),
        "go_cmd": str(entry.get("go_cmd") or ""),
        "navi_cmd": str(entry.get("navi_cmd") or ""),
        "status": str(entry.get("status") or "open"),
        "status_error": str(entry.get("status_error") or ""),
        "added_at": str(entry.get("added_at") or ""),
        "updated_at": str(entry.get("updated_at") or ""),
        "totals": diff["totals"],
        "items": diff["rows"],
    }
