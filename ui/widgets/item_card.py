"""
Card de item na lista de resultados da busca.
Recebe a paleta de cores (dict mutável, ex. ``C`` da app).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import tkinter as tk

import app_formatters
import app_services
from core.constants import BASE_URL
from item_icon_cache import resolve_item_icon_url


def _normalize_media_url(url: str) -> str:
    return app_services.normalize_media_url(url, base_url=BASE_URL)


class ItemCard(tk.Frame):
    def __init__(
        self,
        parent,
        item: dict,
        on_click: Callable[[], None],
        *,
        palette: Dict[str, str],
        selected: bool = False,
        thumb_loader: Optional[Callable] = None,
        item_emoji_fn: Optional[Callable[[str], str]] = None,
        fmt_price_stores_fn: Optional[Callable] = None,
        **kwargs,
    ):
        C = palette
        emoji = item_emoji_fn or app_formatters.item_emoji
        fmt_prices = fmt_price_stores_fn or app_formatters.fmt_price_stores

        bg = C["card"] if not selected else "#1e0e40"
        super().__init__(parent, bg=bg, cursor="hand2", **kwargs)
        self.configure(pady=8, padx=10)

        border_color = C["purple"] if selected else C["border"]
        self.configure(highlightbackground=border_color, highlightthickness=1)

        thumb_slot = tk.Frame(self, bg=bg, width=44, height=44)
        thumb_slot.pack(side="left", padx=(0, 10))
        thumb_slot.pack_propagate(False)
        self._thumb_ref = None
        try:
            iid_thumb = int(item.get("id"))
        except (TypeError, ValueError):
            iid_thumb = None
        ic_url = _normalize_media_url(
            resolve_item_icon_url(iid_thumb, item.get("item_icon_url") or "", base_url=BASE_URL)
        )
        if ic_url and thumb_loader:
            ph = thumb_loader(ic_url, iid_thumb)
            if ph:
                self._thumb_ref = ph
                tk.Label(thumb_slot, image=ph, bg=bg).place(relx=0.5, rely=0.5, anchor="center")
        if not self._thumb_ref:
            tk.Label(
                thumb_slot,
                text=emoji(item.get("name", "")),
                bg=bg,
                fg=C["text"],
                font=("Segoe UI", 16),
            ).place(relx=0.5, rely=0.5, anchor="center")

        info = tk.Frame(self, bg=bg)
        info.pack(side="left", fill="x", expand=True)

        raw_name = (item.get("item_card_title") or item.get("name") or "").strip()
        name_text = raw_name if raw_name else "Item Desconhecido"
        if item.get("is_costume"):
            name_text += "  [COSTUME]"
        tk.Label(
            info,
            text=name_text,
            bg=bg,
            fg=C["purple3"],
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).pack(fill="x")

        info_row = tk.Frame(info, bg=bg)
        info_row.pack(fill="x")

        tk.Label(
            info_row,
            text=f"ID: {item.get('id', '?')}",
            bg=bg,
            fg=C["text3"],
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(side="left")

        online_stores = item.get("online_stores", 0)
        if online_stores > 0:
            tk.Label(
                info_row,
                text=f"  •  🏪 {online_stores} loja(s) online",
                bg=bg,
                fg=C["yellow"],
                font=("Segoe UI", 8, "bold"),
            ).pack(side="left")

        min_prices = item.get("min_prices", {})
        if min_prices:
            prices_text_parts = []
            for sale_type in ("zeny", "rops", "hero_points", "rmt"):
                if sale_type in min_prices:
                    price = min_prices[sale_type]
                    if sale_type == "zeny":
                        prices_text_parts.append(f"{fmt_prices(price)}Z")
                    elif sale_type == "rops":
                        prices_text_parts.append(f"{fmt_prices(price)}R$ (ROPS)")
                    elif sale_type == "hero_points":
                        prices_text_parts.append(f"{fmt_prices(price)} HP")
                    elif sale_type == "rmt":
                        prices_text_parts.append(f"{fmt_prices(price)}R$ (RMT)")

            if prices_text_parts:
                tk.Label(
                    info,
                    text="  •  ".join(prices_text_parts),
                    bg=bg,
                    fg=C["green"],
                    font=("Segoe UI", 8),
                ).pack(fill="x")

        arrow = tk.Label(self, text="›", bg=bg, fg=C["text3"], font=("Segoe UI", 16))
        arrow.pack(side="right")

        for w in (self, thumb_slot, info, arrow):
            w.bind("<Button-1>", lambda e: on_click())
        for w in info.winfo_children():
            w.bind("<Button-1>", lambda e: on_click())
        for w in thumb_slot.winfo_children():
            w.bind("<Button-1>", lambda e: on_click())
        self.bind("<Enter>", lambda e: self._hover(True, palette))
        self.bind("<Leave>", lambda e: self._hover(False, palette))

    def _hover(self, on: bool, palette: Dict[str, str]):
        color = "#1d1038" if on else palette["card"]
        self._set_bg(color)

    def _set_bg(self, color: str):
        self.configure(bg=color)
        for w in self.winfo_children():
            try:
                w.configure(bg=color)
                for c in w.winfo_children():
                    try:
                        c.configure(bg=color)
                    except tk.TclError:
                        pass
            except tk.TclError:
                pass
