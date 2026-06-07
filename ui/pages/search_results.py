"""
Janela de resultados da busca de itens (lista + seleção).
A página «Busca» na app principal só dispara a pesquisa; a lista vive aqui.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Dict, List, Optional, Type

import tkinter as tk

from services.item_search import ItemSearchService
from ui.widgets.item_card import ItemCard


class SearchResultsController:
    def __init__(
        self,
        master: tk.Tk,
        *,
        palette: Dict[str, str],
        search_service: ItemSearchService,
        scrollable_frame_cls: Type,
        rounded_card_cls: Type,
        load_icon_photo: Callable,
        on_item_selected: Callable[[dict], None],
        on_search_saved: Callable[[str, int], None],
        set_status: Callable[[str, str], None],
        logger: Optional[logging.Logger] = None,
        item_emoji_fn: Optional[Callable] = None,
        fmt_price_stores_fn: Optional[Callable] = None,
    ):
        self._master = master
        self._palette = palette
        self._search_service = search_service
        self._scrollable_frame_cls = scrollable_frame_cls
        self._rounded_card_cls = rounded_card_cls
        self._load_icon_photo = load_icon_photo
        self._on_item_selected = on_item_selected
        self._on_search_saved = on_search_saved
        self._set_status = set_status
        self.logger = logger or logging.getLogger(__name__)
        self._item_emoji_fn = item_emoji_fn
        self._fmt_price_stores_fn = fmt_price_stores_fn

        self.current_items: List[dict] = []
        self.selected_item: Optional[dict] = None
        self._generation = 0

        self._win: Optional[tk.Toplevel] = None
        self.items_label: Optional[tk.Label] = None
        self.items_scroll = None

    def parse_direct_item_id(self, query: str) -> Optional[int]:
        return self._search_service.parse_direct_item_id(query)

    def hide_window(self) -> None:
        win = self._win
        if win is None:
            return
        try:
            if win.winfo_exists():
                win.withdraw()
        except tk.TclError:
            pass

    def ensure_window(self) -> tk.Toplevel:
        C = self._palette
        win = self._win
        if win is not None:
            try:
                if win.winfo_exists():
                    win.deiconify()
                    win.lift()
                    return win
            except tk.TclError:
                pass

        win = tk.Toplevel(self._master)
        win.title("Resultados da busca — GDZ Monitor")
        win.configure(bg=C["bg"])
        win.minsize(360, 320)
        win.geometry("540x580")

        shell = self._rounded_card_cls(win, radius=20, margin=12, fill_key="card")
        shell.pack(fill="both", expand=True, padx=12, pady=12)
        body = tk.Frame(shell.inner, bg=C["card"])
        body.pack(fill="both", expand=True, padx=10, pady=10)
        self.items_label = tk.Label(body, text="", bg=C["card"], fg=C["text3"], font=("Segoe UI", 8))
        self.items_label.pack(anchor="w", pady=(0, 6))
        self.items_scroll = self._scrollable_frame_cls(body, inner_bg=C["card"])
        self.items_scroll.pack(fill="both", expand=True)
        self._win = win

        def _hide():
            try:
                win.withdraw()
            except tk.TclError:
                pass

        win.protocol("WM_DELETE_WINDOW", _hide)
        return win

    def start_search(self, query: str) -> None:
        """Dispara busca em thread; atualiza a janela de resultados."""
        C = self._palette
        self.ensure_window()
        self._generation += 1
        gen = self._generation

        self._set_status("● buscando...", C["yellow"])
        if self.items_label is not None:
            self.items_label.configure(text="Buscando itens e raspando lojas abertas...")
        if self.items_scroll is not None:
            for w in self.items_scroll.inner.winfo_children():
                w.destroy()
            tk.Label(
                self.items_scroll.inner,
                text="⏳ Aguarde...\nBuscando itens e extraindo dados de lojas...",
                bg=C["bg"],
                fg=C["text3"],
                font=("Segoe UI", 10),
            ).pack(pady=30)

        def run():
            err = None
            try:
                if self.logger:
                    self.logger.info("🔍 Iniciando busca por: '%s' (gen=%s)", query, gen)
                results = self._search_service.search_by_name(query)
                if gen != self._generation:
                    if self.logger:
                        self.logger.debug(
                            "Busca gen=%s ignorada (atual=%s)", gen, self._generation
                        )
                    return
                self.current_items = results
                self._on_search_saved(query, len(results))
                if self.logger:
                    self.logger.info(
                        "✓ Busca concluída: %s itens com informações de lojas", len(results)
                    )
                self._master.after(0, lambda r=results, g=gen: self._finish(r, g, None))
            except Exception as ex:
                err = str(ex)
                if self.logger:
                    self.logger.error("Search error: %s", err)
                self._master.after(0, lambda msg=err, g=gen: self._finish([], g, msg))

        threading.Thread(target=run, daemon=True).start()

    def _finish(self, results: List[dict], gen: int, error_msg: Optional[str]) -> None:
        if gen != self._generation:
            return
        if error_msg:
            self._show_error(error_msg)
            return
        self.render_items(results)

    def _show_error(self, msg: str) -> None:
        C = self._palette
        self._set_status("● erro", C["red"])
        if self.items_label is not None:
            self.items_label.configure(text="Erro na busca")
        if self.items_scroll is None:
            return
        for w in self.items_scroll.inner.winfo_children():
            w.destroy()
        tk.Label(
            self.items_scroll.inner,
            text=f"⚠ Erro:\n{msg}",
            bg=C["bg"],
            fg=C["red"],
            font=("Segoe UI", 9),
            wraplength=420,
            justify="center",
        ).pack(pady=30)

    def render_items(self, items: List[dict]) -> None:
        C = self._palette
        self._set_status("● online", C["green"])
        if self.items_scroll is None or self.items_label is None:
            return
        for w in self.items_scroll.inner.winfo_children():
            w.destroy()

        if not items:
            self.items_label.configure(text="Nenhum item encontrado")
            tk.Label(
                self.items_scroll.inner,
                text="🔍\n\nNenhum resultado.\nTente outro nome.",
                bg=C["bg"],
                fg=C["text3"],
                font=("Segoe UI", 10),
                justify="center",
            ).pack(pady=40)
            return

        self.items_label.configure(text=f"{len(items)} item(s) encontrado(s)")
        for i, item in enumerate(items):
            try:
                card = ItemCard(
                    self.items_scroll.inner,
                    item,
                    on_click=lambda idx=i: self.select_item(idx),
                    palette=self._palette,
                    selected=(
                        self.selected_item is not None
                        and self.selected_item.get("id") == item.get("id")
                    ),
                    thumb_loader=lambda u, iid=None, mx=44: self._load_icon_photo(
                        u, max_size=mx, item_id=iid
                    ),
                    item_emoji_fn=self._item_emoji_fn,
                    fmt_price_stores_fn=self._fmt_price_stores_fn,
                )
                card.pack(fill="x", pady=3)
            except Exception as ex:
                if self.logger:
                    self.logger.debug("ItemCard %s: %s", item.get("id"), ex)

    def select_item(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.current_items):
            return
        item = self.current_items[idx]
        self.selected_item = item
        if self.logger:
            self.logger.info("Selected item: %s", item)
        self.render_items(self.current_items)
        self._on_item_selected(item)
