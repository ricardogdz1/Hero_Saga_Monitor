"""
GDZ Monitor — compatibilidade para scripts legados.

A aplicação corre via PyWebView: ``python web_poc/run.py`` ou ``run.bat``.

Reexporta símbolos de ``app_runtime`` para ``from app import api_search``, etc.
"""

from app_runtime import (  # noqa: F401
    SCRAPER_AVAILABLE,
    _sync_iwork_name_from_sources,
    api_item_history,
    api_search,
    api_vending_search,
    clean_json_response,
    clean_shop_name,
    collect_price,
    fmt_price,
    fmt_price_stores,
    get_herosaga_item_stores,
    get_stores_from_item_page,
    group_sales_by_type,
    item_emoji,
    item_matches_search,
    load_data,
    load_prices_history,
    logger,
    safe_get,
)

if __name__ == "__main__":
    from web_poc.run import main

    main()
