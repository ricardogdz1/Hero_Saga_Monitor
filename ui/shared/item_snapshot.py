"""
Cartões de item com ícone e preços (partilhado entre páginas).
"""
from __future__ import annotations

import logging

import tkinter as tk

import app_domain
import app_formatters
from adapters import herosaga_api
from core.constants import BASE_URL
from item_icon_cache import resolve_item_icon_url
from ui.theme import C
from ui.widgets import DarkButton

logger = logging.getLogger(__name__)

_normalize_media_url = herosaga_api.normalize_media_url
item_emoji = app_formatters.item_emoji
fmt_price_stores = app_formatters.fmt_price_stores


def _format_home_min_prices_for_monitored(m: dict) -> str:
    return app_domain.format_home_min_prices_for_monitored(m, fmt_price_stores=fmt_price_stores)


class ItemSnapshotMixin:
    """Linha/cartão reutilizável para listas de itens."""

    def _bind_click_open_item_detail(self, widget, item_id: int, item_name: str = ""):
        """Clique abre janela com lojas e histórico do item."""

        def go(_event=None, iid=item_id, nm=item_name):
            self._open_item_detail_window(item_id=iid, item_name_hint=nm or "")

        widget.bind("<Button-1>", go)
        widget.configure(cursor="hand2")
        for c in widget.winfo_children():
            self._bind_click_open_item_detail(c, item_id, item_name)

    def _clipboard_copy_ws_item_id(self, n: int):
        """Copia ``@ws <id>`` para a área de transferência (comando do jogo)."""
        try:
            self.clipboard_clear()
            self.clipboard_append(f"@ws {int(n)}")
            self.update_idletasks()
        except (tk.TclError, TypeError, ValueError):
            logger.warning("Clipboard: falha ao copiar @ws %s", n)

    def _pack_item_store_snapshot_row(
        self,
        parent,
        entry: dict,
        photo_refs: list,
        *,
        wraplength: int = 520,
        layout: str = "stack",
        id_subline=None,
        footer_labels=None,
        show_ws_copy=False,
        drag_handle_monitored=None,
        card_pack_fill_x=True,
        title_wraplength=None,
        icon_slot_px=None,
        compact_text_column=False,
        defer_icon_load=False,
        price_label_holder=None,
        static_incomplete=False,
    ):
        """
        Cartão com ícone, nome, ID, menores por moeda (mesmo formato da home).
        layout: 'stack' — linha única como na home; 'split' — coluna esquerda
          (clique para busca) + espaço à direita para botões (empacote após o return).
        Devolve (card, row, bind_target) para associar clique à busca por ID.
        drag_handle_monitored: {'iid': int, 'category': str} — alça «⠿» para arrastar entre categorias (só stack).
        card_pack_fill_x: na home usa True; no fantasma de arrasto use False para não esticar à largura da janela.
        title_wraplength: se definido, quebra o nome do item (útil no fantasma com largura fixa).
        icon_slot_px: largura/altura da caixa do ícone (omissão: 56).
        compact_text_column: no fantasma de arrasto use True — evita ``fill=y`` extra sob o texto.
        """
        name = entry.get("name") or entry.get("item_name") or "Item"
        eid = entry.get("id")
        if eid is None:
            eid = entry.get("item_id")
        eid_str = str(eid) if eid is not None else "?"

        card = tk.Frame(
            parent,
            bg=C["card"],
            highlightbackground=C["border"],
            highlightthickness=1,
        )
        if card_pack_fill_x:
            card.pack(fill="x", pady=4)
        else:
            card.pack(anchor="nw", pady=4)

        if layout == "split":
            row = tk.Frame(card, bg=C["card"])
            row.pack(fill="x", padx=10, pady=8)
            content = tk.Frame(row, bg=C["card"])
            content.pack(side="left", fill="both", expand=True)
            host = tk.Frame(content, bg=C["card"])
            host.pack(fill="x", anchor="w")
            bind_target = content
        else:
            if drag_handle_monitored:
                strip = tk.Frame(card, bg=C["card"])
                strip.pack(fill="x")
                dh = drag_handle_monitored
                iid_h = int(dh["iid"])
                cat_h = str(dh["category"])
                hlab = tk.Label(
                    strip,
                    text="⠿",
                    bg=C["card"],
                    fg=C["text3"],
                    cursor="hand2",
                    font=("Segoe UI", 12),
                )
                hlab.pack(side="left", padx=(6, 2), pady=8, anchor="n")
                hlab.bind(
                    "<ButtonPress-1>",
                    lambda e, ii=iid_h, cc=cat_h, nm=(name or "").strip(), snap=dict(entry): self._mh_drag_begin(
                        e, ii, cc, nm, snap
                    ),
                )
                row = tk.Frame(strip, bg=C["card"])
                row.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=8)
            else:
                row = tk.Frame(card, bg=C["card"])
                row.pack(fill="x", padx=10, pady=8)
            content = row
            host = row
            bind_target = row

        icon_sz = 56 if icon_slot_px is None else max(40, min(72, int(icon_slot_px)))
        icon_fr = tk.Frame(host, bg=C["card"], width=icon_sz, height=icon_sz)
        icon_fr.pack(side="left", padx=(0, 10))
        icon_fr.pack_propagate(False)
        try:
            iid_icon = int(eid) if eid is not None else None
        except (TypeError, ValueError):
            iid_icon = None
        url = _normalize_media_url(
            resolve_item_icon_url(iid_icon, entry.get("item_icon_url") or "", base_url=BASE_URL)
        )
        icon_lbl = tk.Label(
            icon_fr,
            text=item_emoji(name),
            bg=C["card"],
            fg=C["text2"],
            font=("Segoe UI", 20),
        )
        icon_lbl.place(relx=0.5, rely=0.5, anchor="center")
        if defer_icon_load:
            card._mh_icon_fr = icon_fr
            card._mh_icon_lbl = icon_lbl
            card._mh_icon_item_id = iid_icon
            card._mh_icon_url = url
            card._mh_icon_max = min(52, icon_sz - 4)
        elif url or iid_icon:
            ph = self._load_item_icon_photo(url, max_size=min(52, icon_sz - 4), item_id=iid_icon)
            if ph:
                photo_refs.append(ph)
                icon_lbl.configure(image=ph, text="")
                icon_lbl.image = ph
            else:
                icon_lbl.configure(text=item_emoji(name))
        else:
            icon_lbl.configure(text=item_emoji(name))

        txt = tk.Frame(host, bg=C["card"])
        if compact_text_column:
            txt.pack(side="left", fill="x", expand=True, anchor="n")
        else:
            txt.pack(side="left", fill="both", expand=True)
        name_kw = dict(
            text=name,
            bg=C["card"],
            fg=C["purple3"],
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        )
        if title_wraplength is not None:
            try:
                name_kw["wraplength"] = max(80, int(title_wraplength))
            except (TypeError, ValueError):
                pass
        tk.Label(txt, **name_kw).pack(fill="x")
        sub = id_subline if id_subline is not None else f"ID: {eid_str}  ·  clique para abrir janela"
        if static_incomplete:
            sub = f"{sub}  ·  ⚠ dados incompletos"
        tk.Label(
            txt,
            text=sub,
            bg=C["card"],
            fg=C["text3"],
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(fill="x")
        price_lbl = tk.Label(
            txt,
            text=_format_home_min_prices_for_monitored(entry),
            bg=C["card"],
            fg=C["green"],
            font=("Segoe UI", 8),
            anchor="w",
            wraplength=wraplength,
            justify="left",
        )
        price_lbl.pack(fill="x", pady=(2, 0))
        card._mh_price_lbl = price_lbl
        if price_label_holder is not None:
            price_label_holder.append(price_lbl)

        for foot in footer_labels or ():
            pady = foot.get("pady")
            pack_kw = {"fill": "x", "anchor": "w"}
            if pady is not None:
                pack_kw["pady"] = pady
            tk.Label(
                txt,
                text=foot.get("text", ""),
                bg=C["card"],
                fg=foot.get("fg", C["text2"]),
                font=foot.get("font", ("Segoe UI", 8)),
                anchor="w",
                wraplength=foot.get("wraplength", wraplength),
                justify=foot.get("justify", "left"),
            ).pack(**pack_kw)

        if show_ws_copy and eid is not None:
            try:
                eid_int = int(eid)
            except (TypeError, ValueError):
                eid_int = None
            if eid_int is not None:
                wf = tk.Frame(card, bg=C["card"])
                wf.pack(fill="x", padx=10, pady=(0, 6))
                DarkButton(
                    wf,
                    text="📋  Copiar @ws",
                    style="ghost",
                    font=("Segoe UI", 8, "bold"),
                    padx=8,
                    pady=2,
                    command=lambda rid=eid_int: self._clipboard_copy_ws_item_id(rid),
                ).pack(anchor="w")

        if drag_handle_monitored:
            try:
                card._mh_item_id = int(drag_handle_monitored["iid"])
                card._mh_category = str(drag_handle_monitored["category"])
            except (TypeError, ValueError, KeyError):
                pass

        return card, row, bind_target

