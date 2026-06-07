"""
Página Home / busca de itens.
"""
from __future__ import annotations

import logging

import tkinter as tk
from tkinter import messagebox

import app_formatters
from adapters import herosaga_api
from adapters.herosaga_client import HerosagaClient
from adapters.network import scraper
from adapters.persistence import save_data
from core.constants import BASE_URL
from services.item_search import ItemSearchService
from services.search_history import append_search as _append_search_history
from ui.pages.search_results import SearchResultsController
from ui.theme import C
from ui.widgets import DarkButton, DarkEntry, RoundedCard, ScrollableFrame

logger = logging.getLogger(__name__)

_normalize_media_url = herosaga_api.normalize_media_url
item_emoji = app_formatters.item_emoji
fmt_price_stores = app_formatters.fmt_price_stores


class BuscaPageMixin:
    """Página inicial com barra de busca e home monitorados."""

    def _build_busca(self):
        self.busca_frame = tk.Frame(self.main, bg=C["bg"])

        # Header
        hdr = tk.Frame(self.busca_frame, bg=C["bg"])
        hdr.pack(fill="x", padx=20, pady=(20, 0))
        tk.Label(hdr, text="Monitoramento GDZ", bg=C["bg"], fg=C["purple3"],
                 font=("Segoe UI", 16, "bold")).pack(anchor="w")

        # Search bar
        search_frame = tk.Frame(self.busca_frame, bg=C["bg"])
        search_frame.pack(fill="x", padx=20, pady=12)

        entry_wrap = tk.Frame(search_frame, bg=C["bg"])
        entry_wrap.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.search_entry = DarkEntry(entry_wrap)
        self.search_entry.pack(fill="x", pady=2)
        self.search_entry.insert(0, "Ex: Mana Sombria, Espada, Poção...")
        self.search_entry.configure(fg=C["text3"])
        # add="+" para não substituir os handlers internos do DarkEntry (foco / redesenho).
        self.search_entry.bind("<FocusIn>", self._entry_focus_in, add="+")
        self.search_entry.bind("<FocusOut>", self._entry_focus_out, add="+")
        self.search_entry.bind("<Return>", lambda e: self._do_search())

        DarkButton(search_frame, text="  Buscar  ", style="primary",
                   command=self._do_search).pack(side="left", padx=(8, 0))

        # ── Home: itens monitorados (atalhos) ───────────────────────────────
        self.monitored_home_outer = tk.Frame(self.busca_frame, bg=C["bg"])
        self.monitored_home_outer.pack(fill="both", expand=True, padx=0, pady=(4, 0))
        mh_hdr = tk.Frame(self.monitored_home_outer, bg=C["bg"])
        mh_hdr.pack(fill="x", padx=20, pady=(4, 2))
        tk.Label(
            mh_hdr,
            text="Itens monitorados",
            bg=C["bg"],
            fg=C["purple3"],
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left", anchor="w")
        mh_search_row = tk.Frame(self.monitored_home_outer, bg=C["bg"])
        mh_search_row.pack(fill="x", padx=20, pady=(4, 0))
        self._pack_list_search_bar(mh_search_row, "mh", "Buscar item (nome ou ID):")
        mh_strip = tk.Frame(self.monitored_home_outer, bg=C["bg"])
        mh_strip.pack(fill="both", expand=True, padx=20, pady=(2, 16))
        self.mh_body = tk.Frame(mh_strip, bg=C["bg"])
        self.mh_body.pack(fill="both", expand=True)

    def _entry_focus_in(self, e):
        if self.search_entry.get() == "Ex: Mana Sombria, Espada, Poção...":
            self.search_entry.delete(0, "end")
            self.search_entry.configure(fg=C["text"])

    def _entry_focus_out(self, e):
        if not self.search_entry.get():
            self.search_entry.insert(0, "Ex: Mana Sombria, Espada, Poção...")
            self.search_entry.configure(fg=C["text3"])

    def _show_busca(self):
        self._clear_main()
        self.busca_frame.pack(fill="both", expand=True)
        self._render_monitored_home()



    def _init_search_panel(self) -> None:
        """Camada ui/pages + services: lista de resultados da busca."""
        client = HerosagaClient(
            base_url=BASE_URL,
            scraper=scraper,
            get_stores_from_item_page_fn=self._fetch_item_stores,
            normalize_media_url_fn=_normalize_media_url,
            logger=logger,
        )
        service = ItemSearchService(client)
        self._search_panel = SearchResultsController(
            self,
            palette=C,
            search_service=service,
            scrollable_frame_cls=ScrollableFrame,
            rounded_card_cls=RoundedCard,
            load_icon_photo=self._load_item_icon_photo,
            on_item_selected=self._on_search_result_item_selected,
            on_search_saved=self._save_search,
            set_status=lambda text, fg: self.status_dot.configure(text=text, fg=fg),
            logger=logger,
            item_emoji_fn=item_emoji,
            fmt_price_stores_fn=fmt_price_stores,
        )

    @property
    def current_items(self):
        return self._search_panel.current_items if self._search_panel else []

    @property
    def selected_item(self):
        return self._search_panel.selected_item if self._search_panel else None

    @property
    def items_scroll(self):
        return self._search_panel.items_scroll if self._search_panel else None

    @property
    def items_label(self):
        return self._search_panel.items_label if self._search_panel else None

    def _do_search(self):
        query = self.search_entry.get().strip()
        if not query or query == "Ex: Mana Sombria, Espada, Poção...":
            messagebox.showwarning("Aviso", "Digite o nome de um item para buscar.")
            return

        direct_id = self._search_panel.parse_direct_item_id(query)
        if direct_id is not None:
            self._search_panel.hide_window()
            self.status_dot.configure(text="● online", fg=C["green"])
            self._open_item_detail_window(item_id=direct_id, item_name_hint=f"Item {direct_id}")
            return

        self._search_panel.start_search(query)

    def _on_search_result_item_selected(self, item: dict) -> None:
        self._destroy_detail_chart_if_any()
        self._open_item_detail_window(item=item)

    def _render_items(self, items):
        if self._search_panel is not None:
            self._search_panel.render_items(items)

    def _quick_search(self, query: str):
        """Repete uma busca do histórico (texto livre: nome ou ID)."""
        self._nav("busca", self._show_busca)
        self.update_idletasks()
        self.search_entry.delete(0, "end")
        self.search_entry.insert(0, query)
        self.search_entry.configure(fg=C["text"])
        self._do_search()

    def _update_badge(self):
        count = len(self.data["monitored"])
        if count > 0:
            text = str(count)
            if count >= 100:
                self.badge_lbl.configure(text=text, font=("Segoe UI", 6, "bold"))
                badge_w = 28
            elif count >= 10:
                self.badge_lbl.configure(text=text, font=("Segoe UI", 7, "bold"))
                badge_w = 24
            else:
                self.badge_lbl.configure(text=text, font=("Segoe UI", 7, "bold"))
                badge_w = 20
            self.badge_fr.configure(width=max(20, badge_w), height=20)
            self.badge_fr.place(relx=1.0, rely=0.5, anchor="e", x=-6)
        else:
            self.badge_fr.place_forget()


