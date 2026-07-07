"""
Funções de API do Hero Saga (delegam em app_services).
Mantidas aqui para serviços e ``app_runtime`` não repetirem parâmetros de scraper.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from bs4 import BeautifulSoup

from gdz_monitor.services.market import site_api
from gdz_monitor.adapters.network import HEADERS, scraper
from gdz_monitor.core.constants import BASE_URL

logger = logging.getLogger(__name__)


def normalize_media_url(url) -> str:
    return site_api.normalize_media_url(url, base_url=BASE_URL)


def item_card_meta_from_details(details: dict, *, item_card_keys: tuple) -> dict:
    return site_api.item_card_meta_from_details(details, item_card_keys=item_card_keys)


def api_search(
    name: str,
    *,
    get_stores_from_item_page_fn: Callable,
    logger_instance: Optional[logging.Logger] = None,
):
    return site_api.api_search(
        name,
        base_url=BASE_URL,
        scraper=scraper,
        get_stores_from_item_page_fn=get_stores_from_item_page_fn,
        normalize_media_url_fn=normalize_media_url,
        logger=logger_instance or logger,
    )


def api_search_item_names(query: str, *, logger_instance: Optional[logging.Logger] = None):
    return site_api.api_search_item_names(
        query, base_url=BASE_URL, scraper=scraper, logger=logger_instance or logger
    )


def api_item_history(
    item_id: int,
    *,
    clean_json_response_fn: Callable,
    load_prices_history_fn: Callable,
    save_prices_history_fn: Callable,
    get_item_history_fn: Callable,
    persist: bool = False,
    logger_instance: Optional[logging.Logger] = None,
):
    return site_api.api_item_history(
        item_id,
        base_url=BASE_URL,
        scraper=scraper,
        clean_json_response_fn=clean_json_response_fn,
        load_prices_history_fn=load_prices_history_fn,
        save_prices_history_fn=save_prices_history_fn,
        get_item_history_fn=get_item_history_fn,
        persist=persist,
        logger=logger_instance or logger,
    )


def get_stores_from_item_page(
    item_id: int,
    item_name: str = "",
    *,
    force_refresh: bool = False,
    scraper_available: bool,
    get_herosaga_item_stores_fn,
    item_card_meta_from_details_fn: Callable,
    parse_item_card_from_soup_fn,
    clean_shop_name_fn: Callable,
    parse_price_cell_fn: Callable,
    logger_instance: Optional[logging.Logger] = None,
):
    return site_api.get_stores_from_item_page(
        item_id,
        item_name,
        force_refresh=force_refresh,
        scraper_available=scraper_available,
        get_herosaga_item_stores_fn=get_herosaga_item_stores_fn,
        item_card_meta_from_details_fn=item_card_meta_from_details_fn,
        parse_item_card_from_soup_fn=parse_item_card_from_soup_fn,
        clean_shop_name_fn=clean_shop_name_fn,
        parse_price_cell_fn=parse_price_cell_fn,
        base_url=BASE_URL,
        headers=HEADERS,
        scraper=scraper,
        BeautifulSoup_cls=BeautifulSoup,
        logger=logger_instance or logger,
    )


def api_vending_search(
    name: str,
    *,
    scraper_available: bool,
    search_item_all_stores_fn,
    coerce_price_fn: Callable,
    logger_instance: Optional[logging.Logger] = None,
):
    return site_api.api_vending_search(
        name,
        base_url=BASE_URL,
        scraper=scraper,
        scraper_available=scraper_available,
        search_item_all_stores_fn=search_item_all_stores_fn,
        coerce_price_fn=coerce_price_fn,
        logger=logger_instance or logger,
    )


def collect_price(
    item_id: int,
    item_data: dict,
    *,
    load_prices_history_fn: Callable,
    save_prices_history_fn: Callable,
    logger_instance: Optional[logging.Logger] = None,
):
    return site_api.collect_price(
        item_id,
        item_data,
        load_prices_history_fn=load_prices_history_fn,
        save_prices_history_fn=save_prices_history_fn,
        logger=logger_instance or logger,
    )


def get_item_history(item_id: int, *, load_prices_history_fn: Callable, safe_get_fn: Callable) -> dict:
    return site_api.get_item_history(
        item_id, load_prices_history_fn=load_prices_history_fn, safe_get_fn=safe_get_fn
    )


def sync_iwork_name_from_sources(
    iwork: dict,
    history_data,
    *,
    api_search_item_names_fn: Callable,
    logger_instance: Optional[logging.Logger] = None,
):
    return site_api.sync_iwork_name_from_sources(
        iwork,
        history_data,
        api_search_item_names_fn=api_search_item_names_fn,
        logger=logger_instance or logger,
    )
