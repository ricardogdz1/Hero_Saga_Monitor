"""
Cliente Hero Saga: busca de itens e metadados de lojas.
Encapsula ``app_services`` para a camada ``services`` não importar scraping diretamente.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional

from gdz_monitor.services.market import site_api
from gdz_monitor.adapters.network import scraper as _scraper


class HerosagaClient:
    """Adaptador HTTP/JSON + raspagem de páginas de item."""

    def __init__(
        self,
        *,
        base_url: str,
        scraper,
        get_stores_from_item_page_fn: Callable,
        normalize_media_url_fn: Callable[[str], str],
        logger: Optional[logging.Logger] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.scraper = scraper or _scraper
        self._get_stores = get_stores_from_item_page_fn
        self._normalize_url = normalize_media_url_fn
        self.logger = logger

    def search_items_by_name(self, name: str) -> List[dict]:
        """Vending search + lojas/card meta nos primeiros resultados."""
        return site_api.api_search(
            name,
            base_url=self.base_url,
            scraper=self.scraper,
            get_stores_from_item_page_fn=self._get_stores,
            normalize_media_url_fn=self._normalize_url,
            logger=self.logger,
        )

    def search_item_names(self, query: str) -> List[dict]:
        """Metadados leves (sem raspar lojas)."""
        return site_api.api_search_item_names(
            query,
            base_url=self.base_url,
            scraper=self.scraper,
            logger=self.logger,
        )
