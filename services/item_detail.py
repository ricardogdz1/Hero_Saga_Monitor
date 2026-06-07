"""Caso de uso: detalhe de item (lojas + histórico)."""
from __future__ import annotations

from typing import Callable, Optional


def fetch_item_history(
    item_id: int,
    *,
    api_item_history_fn: Callable,
) -> dict:
    return api_item_history_fn(item_id)


def fetch_stores_and_meta(
    item_id: int,
    item_name: str,
    *,
    get_stores_from_item_page_fn: Callable,
    force_refresh: bool = False,
) -> tuple:
    """Devolve (lojas, meta_card)."""
    return get_stores_from_item_page_fn(item_id, item_name, force_refresh=force_refresh)


def is_item_monitored(item_id, monitored: list) -> bool:
    try:
        iid = int(item_id)
    except (TypeError, ValueError):
        return False
    for m in monitored:
        if not isinstance(m, dict):
            continue
        try:
            if int(m.get("id")) == iid:
                return True
        except (TypeError, ValueError):
            continue
    return False
