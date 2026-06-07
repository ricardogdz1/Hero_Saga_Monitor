"""
Página Auto Loot.
"""
from __future__ import annotations

import logging

import tkinter as tk

from loot_manager import LootTab
from ui.theme import C
from ui.widgets import RoundedCard, ScrollableFrame

logger = logging.getLogger(__name__)


class LootPageMixin:
    """Integração com LootTab."""

    def _build_loot(self):
        self.loot_frame = tk.Frame(self.main, bg=C["bg"])
        hdr = tk.Frame(self.loot_frame, bg=C["bg"])
        hdr.pack(fill="x", padx=20, pady=(20, 4))
        tk.Label(
            hdr,
            text="Auto Loot",
            bg=C["bg"],
            fg=C["purple3"],
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w")
        tk.Label(
            hdr,
            text="Monte grupos @alootid2, mantenha o autoload e copie comandos com 1 clique.",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 9),
            justify="left",
        ).pack(anchor="w")
        self.loot_tab = LootTab(
            self.loot_frame,
            self,
            self.loot_manager,
            colors=C,
            rounded_card_cls=RoundedCard,
            scrollable_cls=ScrollableFrame,
        )
        self.loot_tab.pack(fill="both", expand=True)

    def _show_loot(self):
        self._clear_main()
        self.loot_frame.pack(fill="both", expand=True)
        try:
            self.loot_tab.refresh_all()
        except Exception:
            logger.exception("loot_tab.refresh_all")

