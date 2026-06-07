"""Página Histórico de buscas."""
from __future__ import annotations

import tkinter as tk
from typing import Callable, Dict, List, Optional

from adapters.persistence import save_data
from services.search_history import append_search as _append_search_history
from ui.theme import C
from ui.widgets import RoundedCard, ScrollableFrame


class SearchHistoryPage:
    def __init__(
        self,
        parent: tk.Frame,
        *,
        palette: dict,
        on_quick_search: Callable[[str], None],
    ):
        self._palette = palette
        self._on_quick_search = on_quick_search
        self.frame = tk.Frame(parent, bg=palette["bg"])
        self._build()

    def _build(self) -> None:
        C = self._palette
        hdr = tk.Frame(self.frame, bg=C["bg"])
        hdr.pack(fill="x", padx=20, pady=(20, 0))
        tk.Label(
            hdr,
            text="Histórico de Buscas",
            bg=C["bg"],
            fg=C["purple3"],
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")

        shell = RoundedCard(self.frame, radius=20, margin=12, fill_key="card")
        shell.pack(fill="both", expand=True, padx=20, pady=16)
        self._scroll = ScrollableFrame(shell.inner, inner_bg=C["card"])
        self._scroll.pack(fill="both", expand=True, padx=10, pady=10)

    def render(self, searches: List[dict]) -> None:
        C = self._palette
        for w in self._scroll.inner.winfo_children():
            w.destroy()
        if not searches:
            tk.Label(
                self._scroll.inner,
                text="Nenhuma busca registrada ainda.",
                bg=C["card"],
                fg=C["text3"],
                font=("Segoe UI", 10),
            ).pack(pady=40)
            return
        for s in searches:
            row = tk.Frame(self._scroll.inner, bg=C["card"], cursor="hand2")
            row.pack(fill="x", pady=4, padx=4)
            q = s.get("q", "")
            count = s.get("count", 0)
            ts = (s.get("ts") or "")[:16].replace("T", " ")
            tk.Label(
                row,
                text=f"🔍  {q}",
                bg=C["card"],
                fg=C["text"],
                font=("Segoe UI", 10, "bold"),
                anchor="w",
            ).pack(side="left", fill="x", expand=True)
            tk.Label(
                row,
                text=f"{count} resultado(s)  •  {ts}",
                bg=C["card"],
                fg=C["text3"],
                font=("Segoe UI", 8),
            ).pack(side="right")
            row.bind("<Button-1>", lambda e, query=q: self._on_quick_search(query))
            for c in row.winfo_children():
                c.bind("<Button-1>", lambda e, query=q: self._on_quick_search(query))

    def show(self) -> None:
        self.frame.pack(fill="both", expand=True)

    def hide(self) -> None:
        self.frame.pack_forget()

class HistPageMixin:
    """Histórico de buscas (mixin fino sobre SearchHistoryPage)."""

    def _build_hist(self):
        self._hist_page = SearchHistoryPage(
            self.main,
            palette=C,
            on_quick_search=self._quick_search,
        )
        self.hist_frame = self._hist_page.frame

    def _show_hist(self):
        self._clear_main()
        self._render_hist()
        self._hist_page.show()

    def _render_hist(self):
        self._hist_page.render(list(self.data.get("searches") or []))

    def _save_search(self, q, count):
        _append_search_history(self.data, q, count)
        save_data(self.data)
