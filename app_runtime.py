"""
Runtime partilhado: logging, scraping, API Hero Saga e helpers de domínio.
Importado por ``app.py`` e por páginas que precisam de API sem import circular.
"""
from __future__ import annotations

import logging
import os

import urllib3
from bs4 import BeautifulSoup
from price_parse import coerce_price, parse_price_cell

import app_domain
import app_formatters
import app_services
from adapters import herosaga_api, persistence
from adapters.network import HEADERS, scraper
from adapters.persistence import (
    load_data,
    load_prices_history,
    save_data,
    save_prices_history,
)
from core.constants import BASE_URL
from mvp_timer import mvp_catalog_matches_search
from ui.theme import C

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from stores_scraper import (
        HerosagaScraper,
        get_herosaga_item_stores,
        parse_item_card_from_soup,
        search_item_all_stores,
    )

    SCRAPER_AVAILABLE = True
except ImportError as e:
    SCRAPER_AVAILABLE = False
    logging.getLogger(__name__).warning("stores_scraper indisponível: %s", e)

    def parse_item_card_from_soup(soup):
        return {}

    def get_herosaga_item_stores(*_args, **_kwargs):
        return {"error": "scraper indisponível"}

_ITEM_CARD_KEYS = ("item_icon_url", "item_description", "item_weight", "item_card_title")

LOG_FILE = os.path.join(os.path.expanduser("~"), "herosaga_monitor.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)
logger.info("=" * 80)
logger.info("GDZ MONITOR INICIADO")
logger.info("Arquivo de log: %s", LOG_FILE)
logger.info("=" * 80)

DEFAULT_MONITOR_CATEGORIES = persistence.DEFAULT_MONITOR_CATEGORIES
MH_HOME_MIN_VISIBLE_CATEGORY_COLS = 3
MH_HOME_CATEGORY_COL_MIN_WIDTH = 260
_ALERTS_IO_LOCK = persistence._ALERTS_IO_LOCK


def _normalize_media_url(url) -> str:
    return herosaga_api.normalize_media_url(url)


def _item_card_meta_from_details(details: dict) -> dict:
    return app_services.item_card_meta_from_details(details, item_card_keys=_ITEM_CARD_KEYS)


def _ensure_monitor_structure(data: dict) -> dict:
    return persistence.ensure_monitor_structure(data)


def api_search(name: str):
    return app_services.api_search(
        name,
        base_url=BASE_URL,
        scraper=scraper,
        get_stores_from_item_page_fn=get_stores_from_item_page,
        normalize_media_url_fn=_normalize_media_url,
        logger=logger,
    )


def api_search_item_names(query: str):
    return app_services.api_search_item_names(
        query, base_url=BASE_URL, scraper=scraper, logger=logger
    )


def _sync_iwork_name_from_sources(iwork: dict, history_data) -> None:
    app_services.sync_iwork_name_from_sources(
        iwork,
        history_data,
        api_search_item_names_fn=api_search_item_names,
        logger=logger,
    )


def api_item_history(item_id: int):
    return app_services.api_item_history(
        item_id,
        base_url=BASE_URL,
        scraper=scraper,
        clean_json_response_fn=clean_json_response,
        load_prices_history_fn=load_prices_history,
        save_prices_history_fn=save_prices_history,
        get_item_history_fn=get_item_history,
        logger=logger,
    )


def get_stores_from_item_page(
    item_id: int, item_name: str = "", *, force_refresh: bool = False
):
    return app_services.get_stores_from_item_page(
        item_id,
        item_name,
        force_refresh=force_refresh,
        scraper_available=SCRAPER_AVAILABLE,
        get_herosaga_item_stores_fn=get_herosaga_item_stores if SCRAPER_AVAILABLE else None,
        item_card_meta_from_details_fn=_item_card_meta_from_details,
        parse_item_card_from_soup_fn=parse_item_card_from_soup if SCRAPER_AVAILABLE else None,
        clean_shop_name_fn=clean_shop_name,
        parse_price_cell_fn=parse_price_cell,
        base_url=BASE_URL,
        headers=HEADERS,
        scraper=scraper,
        BeautifulSoup_cls=BeautifulSoup,
        logger=logger,
    )


def api_vending_search(name: str):
    return app_services.api_vending_search(
        name,
        base_url=BASE_URL,
        scraper=scraper,
        scraper_available=SCRAPER_AVAILABLE,
        search_item_all_stores_fn=search_item_all_stores if SCRAPER_AVAILABLE else None,
        coerce_price_fn=coerce_price,
        logger=logger,
    )


def _dedupe_monitored_preserve_order(monitored):
    return persistence.dedupe_monitored_preserve_order(monitored)


def load_prices_history():
    return persistence.load_prices_history()


def save_prices_history(history):
    persistence.save_prices_history(history)


def collect_price(item_id: int, item_data: dict):
    app_services.collect_price(
        item_id,
        item_data,
        load_prices_history_fn=load_prices_history,
        save_prices_history_fn=save_prices_history,
        logger=logger,
    )


def get_item_history(item_id: int) -> dict:
    return app_services.get_item_history(
        item_id, load_prices_history_fn=load_prices_history, safe_get_fn=safe_get
    )


def group_sales_by_type(sales: list) -> dict:
    return app_domain.group_sales_by_type(sales)


def calculate_stats(sales: list) -> dict:
    return app_domain.calculate_stats(sales)


def item_emoji(name: str) -> str:
    return app_formatters.item_emoji(name)


def fmt_price(p) -> str:
    return app_formatters.fmt_price(p)


def fmt_price_stores(p) -> str:
    return app_formatters.fmt_price_stores(p)


def _alert_min_refinement(alert: dict):
    return app_domain.alert_min_refinement(alert)


def _sale_min_prices_from_stores(stores: list, *, min_refinement=None) -> dict:
    return app_domain.sale_min_prices_from_stores(stores, min_refinement=min_refinement)


def _format_home_min_prices_for_monitored(m: dict) -> str:
    return app_domain.format_home_min_prices_for_monitored(m, fmt_price_stores=fmt_price_stores)


def _monitored_static_incomplete(m: dict) -> bool:
    return app_domain.monitored_static_incomplete(m)


def _mh_last_prices_update_label(monitored: list) -> str:
    return app_domain.mh_last_prices_update_label(monitored)


_LIST_SEARCH_DEBOUNCE_MS = 300


def item_matches_search(entry: dict, query: str) -> bool:
    return app_domain.item_matches_search(
        entry, query, mvp_catalog_matches_search_fn=mvp_catalog_matches_search
    )


def safe_get(d: dict, key: str, default: str = "N/A") -> str:
    return app_formatters.safe_get(d, key, default)


def clean_shop_name(name: str) -> str:
    return app_formatters.clean_shop_name(name)


def clean_json_response(text: str, content: bytes = None) -> str:
    return app_domain.clean_json_response(text, content, logger=logger)


def sale_type_color(st: str) -> str:
    return app_formatters.sale_type_color(st, C)


def _store_badge_label(sale_type: str) -> tuple:
    return app_formatters.store_badge_label(sale_type, C)


def _format_store_price_display(price: float, sale_type: str) -> tuple:
    return app_formatters.format_store_price_display(price, sale_type, C)
