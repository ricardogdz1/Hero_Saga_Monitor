"""Caso de uso: itens monitorados (categorias, preços, pesquisa local)."""
from __future__ import annotations

from typing import Callable, List

from gdz_monitor.services.market import domain


def categories_from_data(data: dict) -> List[str]:
    return list(data.get("monitor_categories") or [])


def monitored_list(data: dict) -> list:
    return list(data.get("monitored") or [])


def item_matches_search(
    entry: dict,
    query: str,
    *,
    mvp_catalog_matches_search_fn: Callable[[str, str], bool],
) -> bool:
    return domain.item_matches_search(
        entry, query, mvp_catalog_matches_search_fn=mvp_catalog_matches_search_fn
    )


def format_home_min_prices(m: dict, *, fmt_price_stores_fn: Callable) -> str:
    return domain.format_home_min_prices_for_monitored(m, fmt_price_stores=fmt_price_stores_fn)


def static_incomplete(m: dict) -> bool:
    return domain.monitored_static_incomplete(m)


def last_prices_update_label(monitored: list) -> str:
    return domain.mh_last_prices_update_label(monitored)


def sale_min_prices_from_stores(stores: list, *, min_refinement=None) -> dict:
    return domain.sale_min_prices_from_stores(stores, min_refinement=min_refinement)


def splice_category_block(monitored: list, category: str, ordered_entries: list) -> list:
    """Substitui o bloco de uma categoria na lista ``monitored`` mantendo o resto."""
    cat = str(category)
    new_monitored = []
    emitted = False
    for m in monitored:
        if str(m.get("category") or "Gerais") != cat:
            new_monitored.append(m)
            continue
        if not emitted:
            new_monitored.extend(ordered_entries)
            emitted = True
    if not emitted:
        new_monitored.extend(ordered_entries)
    return new_monitored


def categories_list(data: dict, *, default_categories) -> list:
    cats = data.get("monitor_categories")
    if not isinstance(cats, list) or not cats:
        return list(default_categories)
    return list(cats)


def layout_dims(settings: dict) -> tuple:
    """(largura_mínima_coluna_px, meta_categorias_visíveis)."""
    from gdz_monitor.core.constants import MH_CATEGORY_COL_MIN_WIDTH, MH_MIN_VISIBLE_CATEGORY_COLS

    try:
        wmin = int(settings.get("monitor_home_col_min_width") or MH_CATEGORY_COL_MIN_WIDTH)
    except (TypeError, ValueError):
        wmin = MH_CATEGORY_COL_MIN_WIDTH
    wmin = max(160, min(600, wmin))
    try:
        vis = int(settings.get("monitor_home_min_visible_cols") or MH_MIN_VISIBLE_CATEGORY_COLS)
    except (TypeError, ValueError):
        vis = MH_MIN_VISIBLE_CATEGORY_COLS
    vis = max(1, min(8, vis))
    return wmin, vis
