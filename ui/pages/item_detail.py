"""
Detalhe do item: janela, lojas, histórico, gráficos e diálogo de alerta.
Mixin usado por ``HeroSagaMonitor``.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Optional

import tkinter as tk
from tkinter import messagebox, ttk

import matplotlib.ticker
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import app_domain
import app_formatters
from adapters import herosaga_api
from adapters.network import scraper
from adapters.persistence import load_alerts, save_alerts, save_data
from alert_monitor import (
    filter_stores_by_currency,
    filter_stores_by_refinement,
    listing_fingerprint,
    qualifying_stores_for_alert,
)
from app_settings import load_settings
from core.constants import BASE_URL
from item_icon_cache import read_item_icon_png_bytes, resolve_item_icon_url
from price_parse import parse_price_cell
from services import item_detail as item_detail_service
from services import monitored as monitored_service
from ui.theme import C, ITEM_CARD_UI
from ui.widgets import (
    DarkButton,
    DarkEntry,
    DarkRadiobutton,
    RoundedCard,
    ScrollableFrame,
    pil_knockout_near_white_rgba,
)

logger = logging.getLogger(__name__)

_normalize_media_url = herosaga_api.normalize_media_url
group_sales_by_type = app_domain.group_sales_by_type
calculate_stats = app_domain.calculate_stats
safe_get = app_formatters.safe_get
item_emoji = app_formatters.item_emoji
fmt_price = app_formatters.fmt_price
fmt_price_stores = app_formatters.fmt_price_stores
sale_type_color = lambda st: app_formatters.sale_type_color(st, C)
_store_badge_label = lambda st: app_formatters.store_badge_label(st, C)
_format_store_price_display = lambda p, st: app_formatters.format_store_price_display(p, st, C)

_ITEM_CARD_KEYS = (
    "item_icon_url",
    "item_description",
    "item_weight",
    "item_card_title",
)


class ItemDetailMixin:
    """Janela de detalhe do item (lojas + histórico)."""


    def _detail_error(self, msg):
        error_text = f"⚠ Erro ao buscar detalhes:\n{msg}\n\n(Verifique o arquivo de log)"
        logger.error(f"Detail error displayed to user: {msg}")
        messagebox.showerror("Erro", error_text)

    def _destroy_detail_chart_if_any(self):
        if getattr(self, "chart_canvas", None) is not None:
            try:
                self.chart_canvas.get_tk_widget().destroy()
            except Exception:
                pass
            self.chart_canvas = None

    def _item_id_monitored(self, item_id) -> bool:
        return item_detail_service.is_item_monitored(item_id, self.data.get("monitored") or [])

    def _pack_detail_window_header_actions(self, btn_frame, item: dict, all_sales: list):
        """Botões Monitorar/Remover e alerta no cabeçalho do detalhe (janela ou embebido)."""
        for w in btn_frame.winfo_children():
            w.destroy()
        it = dict(item)
        sl = all_sales if isinstance(all_sales, list) else []

        if item_detail_service.is_item_monitored(it.get("id"), self.data.get("monitored") or []):
            DarkButton(
                btn_frame,
                text="− Remover",
                style="danger",
                command=lambda iit=it, bf=btn_frame, s=sl: self._remove_monitor(
                    iit, detail_btn_frame=bf, detail_all_sales=s
                ),
            ).pack(side="left", padx=2)
        else:
            DarkButton(
                btn_frame,
                text="+ Monitorar",
                style="success",
                command=lambda iit=it, bf=btn_frame, s=sl: self._add_monitor(
                    iit, s, detail_btn_frame=bf
                ),
            ).pack(side="left", padx=2)

        DarkButton(
            btn_frame,
            text="🔔 Alerta",
            style="ghost",
            command=lambda iit=it: self._show_alert_dialog(iit),
        ).pack(side="left", padx=2)

    def _render_detail_into(self, root, item, data, *, chart_setter, preview_photo_holder=None):
        """Monta o painel de lojas + histórico dentro de *root* (janela principal ou Toplevel)."""
        all_sales = data.get("sales", [])

        sales_by_type = group_sales_by_type(all_sales)

        hdr = tk.Frame(root, bg=C["bg2"],
                       highlightbackground=C["border2"], highlightthickness=1)
        hdr.pack(fill="x", pady=(0, 8), padx=2)

        top = tk.Frame(hdr, bg=C["bg2"])
        top.pack(fill="x", padx=14, pady=10)

        hdr._hdr_thumb_refs = []
        icon_slot = tk.Frame(top, bg=C["bg2"], width=42, height=42)
        icon_slot.pack(side="left", padx=(0, 10))
        icon_slot.pack_propagate(False)
        try:
            hdr_iid = int(item.get("id"))
        except (TypeError, ValueError):
            hdr_iid = None
        nu = _normalize_media_url(
            resolve_item_icon_url(hdr_iid, item.get("item_icon_url") or "", base_url=BASE_URL)
        )
        hdr_icon = self._load_item_icon_photo(nu, max_size=40, item_id=hdr_iid) if nu or hdr_iid else None
        if hdr_icon:
            hdr._hdr_thumb_refs.append(hdr_icon)
            tk.Label(icon_slot, image=hdr_icon, bg=C["bg2"]).place(relx=0.5, rely=0.5, anchor="center")
        else:
            tk.Label(
                icon_slot,
                text=item_emoji(item.get("name", "")),
                bg=C["bg2"],
                fg=C["text"],
                font=("Segoe UI", 20),
            ).place(relx=0.5, rely=0.5, anchor="center")

        info = tk.Frame(top, bg=C["bg2"])
        info.pack(side="left", fill="x", expand=True)

        name_row = tk.Frame(info, bg=C["bg2"])
        name_row.pack(fill="x")
        item_name = safe_get(item, "name", "Item Desconhecido")
        tk.Label(name_row, text=item_name,
                 bg=C["bg2"], fg=C["purple3"],
                 font=("Segoe UI", 13, "bold")).pack(side="left")

        meta_parts = []
        if item.get("is_costume"):
            meta_parts.append("COSTUME")

        id_row = tk.Frame(info, bg=C["bg2"])
        id_row.pack(fill="x", anchor="w", pady=(2, 0))
        raw_id = item.get("id")
        id_text = str(raw_id) if raw_id not in (None, "") else "?"

        tk.Label(id_row, text="ID", bg=C["bg2"], fg=C["text3"], font=("Segoe UI", 8)).pack(side="left", padx=(0, 6))
        id_ent = tk.Entry(
            id_row,
            width=14,
            font=("Consolas", 10),
            bg=C["bg2"],
            fg=C["text2"],
            insertbackground=C["purple3"],
            relief="flat",
            bd=0,
            highlightthickness=0,
            selectbackground=C["border2"],
            selectforeground=C["text"],
        )
        id_ent.insert(0, id_text)
        id_ent.pack(side="left")
        try:
            id_ent.configure(state="readonly", readonlybackground=C["bg2"])
        except tk.TclError:
            try:
                id_ent.configure(state="readonly")
            except tk.TclError:
                pass

        def _copy_ws_id():
            try:
                n = int(raw_id)
            except (TypeError, ValueError):
                return
            self._clipboard_copy_ws_item_id(n)

        DarkButton(id_row, text="📋  Copiar @ws", style="ghost", command=_copy_ws_id).pack(side="left", padx=(8, 0))

        if meta_parts:
            tk.Label(
                id_row,
                text="  ·  " + "  ·  ".join(meta_parts),
                bg=C["bg2"],
                fg=C["text3"],
                font=("Segoe UI", 8),
            ).pack(side="left", padx=(10, 0))

        btn_frame = tk.Frame(top, bg=C["bg2"])
        btn_frame.pack(side="right")
        self._pack_detail_window_header_actions(btn_frame, item, all_sales)

        body = tk.Frame(root, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=2)

        left_panel = tk.Frame(body, bg=C["bg"])
        left_panel.pack(side="left", fill="both", expand=True)

        card_holder = tk.Frame(body, bg=C["bg"], width=258)
        card_holder.pack(side="right", fill="y", padx=(12, 4))
        card_holder.pack_propagate(False)
        self._build_item_preview_card(card_holder, item, photo_holder=preview_photo_holder)

        scroll = ScrollableFrame(left_panel)
        scroll.pack(fill="both", expand=True)
        inner = scroll.inner

        stores_holder = tk.Frame(inner, bg=C["bg"])
        stores_holder.pack(fill="x", pady=0)

        stores_list = item.get("stores_list", None)
        self._render_vending_stores(
            stores_holder, item.get("id"), item.get("name", "Item"), None, stores_list, item
        )

        if not all_sales:
            tk.Label(
                inner,
                text="📊  Sem histórico de vendas registrado para este item no site.",
                bg=C["bg"],
                fg=C["text3"],
                font=("Segoe UI", 10),
                justify="center",
            ).pack(pady=(16, 8))
            return

        tabs_frame = tk.Frame(inner, bg=C["bg"])
        tabs_frame.pack(fill="x", padx=0, pady=(12, 0))

        active_tab = tk.StringVar(value="rops")
        tab_buttons = {}

        for sale_type in ["rops", "zeny", "rmt"]:
            sales = sales_by_type.get(sale_type, [])
            if not sales:
                continue

            count = len(sales)
            tab_text = f"{sale_type.upper()} ({count})"
            tab_color = C["rops"] if sale_type == "rops" else (C["zeny"] if sale_type == "zeny" else C["rmt"])

            def make_tab_click(st, cs):
                def click():
                    active_tab.set(st)
                    self._render_history_tabs(
                        inner, sales_by_type, st, item, tabs_frame, stores_holder, chart_setter=cs
                    )
                return click

            btn = tk.Button(tabs_frame, text=tab_text,
                            bg=C["bg3"], fg=tab_color,
                            relief="flat", font=("Segoe UI", 9, "bold"),
                            cursor="hand2", command=make_tab_click(sale_type, chart_setter),
                            padx=12, pady=6)
            btn.pack(side="left", padx=4, pady=4)
            tab_buttons[sale_type] = btn

        first_type = next((t for t in ["rops", "zeny", "rmt"] if sales_by_type.get(t)), "rops")
        active_tab.set(first_type)
        self._render_history_tabs(
            inner, sales_by_type, first_type, item, tabs_frame, stores_holder, chart_setter=chart_setter
        )

    def _render_history_tabs(self, parent, sales_by_type, sale_type, item, tabs_frame, stores_holder, chart_setter=None):
        """Renderiza o conteúdo da aba selecionada com histórico de preços e vendas."""
        # Remove só o bloco de histórico — preserva lojas abertas e botões de moeda
        keep = {tabs_frame, stores_holder}
        for w in list(parent.winfo_children()):
            if w not in keep:
                w.destroy()
        
        sales = sales_by_type.get(sale_type, [])
        if not sales:
            tk.Label(parent, text=f"Sem dados para {sale_type.upper()}",
                     bg=C["bg"], fg=C["text3"], font=("Segoe UI", 9)).pack(pady=20)
            return
        
        # ── SEÇÃO 1: ESTATÍSTICAS ────────────────────────────────────────────
        stats = calculate_stats(sales)
        
        stat_colors = {
            "Último": C["yellow"],
            "Mínimo": C["green"],
            "Máximo": C["red"],
            "Média": C["purple3"],
            "Vendas": C["text2"],
        }
        
        stats_data = [
            ("Último",  fmt_price(stats["último"]),    stat_colors["Último"]),
            ("Mínimo",  fmt_price(stats["mínimo"]),    stat_colors["Mínimo"]),
            ("Máximo",  fmt_price(stats["máximo"]),    stat_colors["Máximo"]),
            ("Média",   fmt_price(stats["média"]),     stat_colors["Média"]),
            ("Vendas",  str(stats["quantidade"]),      stat_colors["Vendas"]),
        ]
        
        stats_row = tk.Frame(parent, bg=C["bg"])
        stats_row.pack(fill="x", pady=(4, 8))
        for label, val, color in stats_data:
            card = tk.Frame(stats_row, bg=C["bg3"],
                            highlightbackground=C["border"], highlightthickness=1)
            card.pack(side="left", padx=3, pady=2, fill="x", expand=True)
            tk.Label(card, text=label, bg=C["bg3"], fg=C["text3"],
                     font=("Segoe UI", 7, "bold")).pack(pady=(6, 0))
            tk.Label(card, text=val, bg=C["bg3"], fg=color,
                     font=("Segoe UI", 11, "bold")).pack(pady=(2, 6))

        # ── SEÇÃO 2: GRÁFICO ─────────────────────────────────────────────────
        chart_wrap = tk.Frame(parent, bg=C["bg3"],
                              highlightbackground=C["border"], highlightthickness=1)
        chart_wrap.pack(fill="x", pady=(0, 8))
        tk.Label(chart_wrap, text=f"HISTÓRICO DE PREÇO - {sale_type.upper()}",
                 bg=C["bg3"], fg=C["text3"],
                 font=("Segoe UI", 7, "bold")).pack(anchor="w", padx=10, pady=(8, 0))

        reversed_sales = list(reversed(sales))
        dates  = [s.get("sale_date", "")[:10] for s in reversed_sales]
        values = [s.get("price", 0) for s in reversed_sales]

        fig = Figure(figsize=(5, 2), dpi=90, facecolor=C["bg3"])
        ax  = fig.add_subplot(111, facecolor=C["bg3"])
        ax.plot(dates, values, color=C["purple2"], linewidth=2, marker="o",
                markersize=4, markerfacecolor=C["purple3"])
        ax.fill_between(range(len(values)), values,
                        alpha=0.15, color=C["purple"])
        ax.set_xticks(range(0, len(dates), max(1, len(dates)//5)))
        ax.set_xticklabels([dates[i] if i < len(dates) else "" 
                            for i in range(0, len(dates), max(1, len(dates)//5))],
                           rotation=40, ha="right", color=C["text3"], fontsize=7)
        ax.tick_params(axis="y", colors=C["text3"], labelsize=7)
        ax.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(
            lambda x, _: f"{int(x):,}".replace(",", ".")))
        for spine in ax.spines.values():
            spine.set_edgecolor(C["border2"])
        ax.grid(axis="y", color=C["border"], linewidth=0.5)
        fig.tight_layout(pad=1.5)

        canvas = FigureCanvasTkAgg(fig, master=chart_wrap)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="x", padx=6, pady=(4, 8))
        if chart_setter is not None:
            chart_setter(canvas)
        else:
            self.chart_canvas = canvas

        # ── SEÇÃO 3: HISTÓRICO DE VENDAS ─────────────────────────────────────
        tk.Label(parent, text=f"📜 HISTÓRICO DE VENDAS - {sale_type.upper()}",
                 bg=C["bg"], fg=C["text3"],
                 font=("Segoe UI", 7, "bold")).pack(anchor="w", pady=(12, 8), padx=4)

        cols = ("Data", "Vendedor", "Comprador", "Preço", "Qtd")
        tree = ttk.Treeview(parent, columns=cols, show="headings",
                            height=min(len(sales), 8))
        widths = [90, 140, 140, 90, 40]
        for col, w in zip(cols, widths):
            tree.heading(col, text=col)
            tree.column(col, width=w, anchor="center" if col in ("Preço","Qtd","Data") else "w")

        # Ordena vendas por data (mais recentes primeiro)
        sorted_sales = sorted(sales, key=lambda x: x.get("sale_date", ""), reverse=True)
        
        for i, s in enumerate(sorted_sales):
            # Calcula diferença em relação à venda anterior (que é mais antiga)
            prev = sorted_sales[i + 1] if i + 1 < len(sorted_sales) else None
            diff = (s.get("price", 0) - prev.get("price", 0)) if prev else 0
            arrow = " ▲" if diff > 0 else (" ▼" if diff < 0 else "")
            price_str = fmt_price(s.get("price", 0)) + arrow
            tree.insert("", "end", values=(
                s.get("sale_date", "N/A")[:16] if s.get("sale_date") else "N/A",
                safe_get(s, "seller_name", "Anônimo"),
                safe_get(s, "buyer_name", "Anônimo"),
                price_str,
                safe_get(s, "quantity", "1"),
            ))

        tree.pack(fill="x", pady=(0, 12))
        tree.tag_configure("oddrow", background=C["bg3"])
    
    def _render_vending_stores(self, parent, item_id, item_name, sale_type, stores_list=None, item=None):
        """Lista lojas abertas no estilo do site (LOJA, refinamento, cartas, valor, qtd, venda por)."""
        for w in parent.winfo_children():
            w.destroy()

        if stores_list is None:
            stores, _ = self._fetch_item_stores(item_id, item_name)
        else:
            stores = list(stores_list) if stores_list else []
            # Lista vazia da busca (ex.: item fora dos 10 primeiros) não deve bloquear nova raspagem.
            if not stores:
                stores, _ = self._fetch_item_stores(item_id, item_name)

        if sale_type is not None:
            sale_type_lower = sale_type.lower()
            if sale_type_lower == "rops":
                stores = [s for s in stores if s.get("sale_type", "").lower() in ["rops", "rp", "r$"]]
            elif sale_type_lower == "zeny":
                stores = [s for s in stores if s.get("sale_type", "").lower() in ["zeny", "z", "z$"]]
            elif sale_type_lower == "hero_points":
                stores = [s for s in stores if "hero" in s.get("sale_type", "").lower()]
            elif sale_type_lower == "rmt":
                stores = [s for s in stores if s.get("sale_type", "").lower() in ["rmt", "rm", "rm$", "m"]]

        stores.sort(key=lambda x: x.get("price", float("inf")))

        # ── Caixa com borda (similar ao site) ───────────────────────────────
        box = tk.Frame(
            parent,
            bg=C["bg2"],
            highlightbackground="#b8860b",
            highlightthickness=2,
        )
        box.pack(fill="x", pady=(4, 10), padx=0)

        head = tk.Frame(box, bg=C["bg2"])
        head.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(
            head,
            text="LOJAS ABERTAS",
            bg=C["bg2"],
            fg=C["yellow"],
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        tk.Label(
            head,
            text="Lojas online com este item à venda (menor → maior preço).",
            bg=C["bg2"],
            fg=C["text3"],
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(2, 0))

        body = tk.Frame(box, bg=C["bg2"])
        body.pack(fill="x", padx=8, pady=(4, 12))

        if not stores:
            tk.Label(
                body,
                text="Nenhuma loja online vendendo este item no momento.",
                bg=C["bg2"],
                fg=C["text3"],
                font=("Segoe UI", 9),
            ).pack(pady=8)
            return

        hdr_bg = C.get("column_hdr", C["border2"])
        hdr_fg = C.get("column_hdr_fg", C["purple3"])
        hdr_h = 32
        header_frame = tk.Frame(body, bg=hdr_bg, height=hdr_h)
        header_frame.pack(fill="x", pady=(0, 4))
        header_frame.pack_propagate(False)

        cols_info = [
            ("Nome da loja", 200, "w"),
            ("Refino", 72, "center"),
            ("Slots", 56, "center"),
            ("Preço", 180, "center"),
            ("Qtd", 56, "center"),
            ("Venda por", 82, "center"),
        ]
        for col_name, width, anchor in cols_info:
            expand = col_name == "Nome da loja"
            # pack_propagate(False) sem height fixa deixa altura ~0 — texto do cabeçalho desaparece (Windows/Tk).
            col_frame = tk.Frame(header_frame, bg=hdr_bg, width=width, height=hdr_h)
            col_frame.pack(side="left", fill="x", expand=expand, padx=1)
            col_frame.pack_propagate(False)
            tk.Label(
                col_frame,
                text=col_name,
                bg=hdr_bg,
                fg=hdr_fg,
                font=("Segoe UI", 8, "bold"),
                anchor=anchor,
            ).pack(fill="both", expand=True, pady=4)

        stores_frame = tk.Frame(body, bg=C["bg2"])
        stores_frame.pack(fill="x")

        for i, store in enumerate(stores):
            char_name = store.get("char_name") or store.get("seller_name") or store.get("owner") or "—"
            refinement = store.get("refinement") or store.get("refine") or store.get("enhancement") or 0
            cards = store.get("cards") or store.get("slots") or 0
            price = store.get("price") or store.get("sell_price") or store.get("valor") or 0
            quantity = store.get("amount") or store.get("quantity") or 1
            store_sale_type = store.get("sale_type") or "zeny"

            price_str, price_color = _format_store_price_display(price, store_sale_type)
            badge_txt, badge_bg = _store_badge_label(store_sale_type)

            row_bg = C["bg3"] if i % 2 == 0 else C["bg2"]

            # Altura livre: linhas com nome longo precisam de mais que ~34px (senão texto virava traços).
            row_frame = tk.Frame(stores_frame, bg=row_bg, height=70)
            row_frame.pack(fill="x", pady=1)
            row_frame.pack_propagate(False)

            loja_frame = tk.Frame(row_frame, bg=row_bg, height=70)
            loja_frame.pack(side="left", fill="both", expand=True, padx=6, pady=0)
            loja_frame.pack_propagate(False)
            tk.Label(
                loja_frame,
                text=char_name,
                bg=row_bg,
                fg=C["text"],
                font=("Segoe UI", 9),
                anchor="w",
                justify="left",
                wraplength=180,
            ).pack(fill="both", expand=True, padx=0, pady=0)

            ref_frame = tk.Frame(row_frame, bg=row_bg, width=72, height=70)
            ref_frame.pack(side="left", padx=2, pady=0)
            ref_frame.pack_propagate(False)
            tk.Label(ref_frame, text=str(refinement), bg=row_bg, fg=C["text2"], font=("Segoe UI", 9), anchor="center").pack(fill="both", expand=True)

            cards_frame = tk.Frame(row_frame, bg=row_bg, width=56, height=70)
            cards_frame.pack(side="left", padx=2, pady=0)
            cards_frame.pack_propagate(False)
            tk.Label(cards_frame, text=str(cards), bg=row_bg, fg=C["text2"], font=("Segoe UI", 9), anchor="center").pack(fill="both", expand=True)

            price_frame = tk.Frame(row_frame, bg=row_bg, width=180, height=70)
            price_frame.pack(side="left", padx=2, pady=0)
            price_frame.pack_propagate(False)
            tk.Label(
                price_frame,
                text=price_str,
                bg=row_bg,
                fg=price_color,
                font=("Segoe UI", 9, "bold"),
                anchor="center",
                wraplength=0,
            ).pack(fill="both", expand=True)

            qty_frame = tk.Frame(row_frame, bg=row_bg, width=56, height=70)
            qty_frame.pack(side="left", padx=2, pady=0)
            qty_frame.pack_propagate(False)
            tk.Label(qty_frame, text=str(quantity), bg=row_bg, fg=C["text2"], font=("Segoe UI", 9), anchor="center").pack(fill="both", expand=True)

            badge_fr = tk.Frame(row_frame, bg=row_bg, width=82, height=70)
            badge_fr.pack(side="left", padx=(4, 8), pady=0)
            badge_fr.pack_propagate(False)
            tk.Label(
                badge_fr,
                text=badge_txt,
                bg=badge_bg,
                fg="#ffffff",
                font=("Segoe UI", 8, "bold"),
                padx=8,
                pady=2,
            ).pack(fill="both", expand=True)

    def _fetch_icon_url_bytes(self, url: str) -> Optional[bytes]:
        url = _normalize_media_url(url or "")
        if not url:
            return None
        try:
            r = scraper.get(url, timeout=18)
            r.raise_for_status()
            return r.content
        except Exception as e:
            logger.debug("Fetch ícone %s: %s", url, e)
            return None

    def _photoimage_from_icon_bytes(self, raw: bytes, max_size: int):
        if not raw:
            return None
        try:
            from io import BytesIO
            from PIL import Image, ImageTk

            im = Image.open(BytesIO(raw))
            if im.mode == "P":
                im = im.convert("RGBA")
            elif im.mode in ("RGBA", "LA"):
                im = im.convert("RGBA")
            else:
                im = im.convert("RGBA")
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:
                resample = Image.LANCZOS
            im.thumbnail((max_size, max_size), resample)
            im = pil_knockout_near_white_rgba(im, thresh=246)
            try:
                return ImageTk.PhotoImage(im, master=self)
            except tk.TclError:
                hx = (C.get("card") or "#151515").strip().lstrip("#")
                if len(hx) >= 6:
                    bg_rgb = (
                        int(hx[0:2], 16),
                        int(hx[2:4], 16),
                        int(hx[4:6], 16),
                    )
                else:
                    bg_rgb = (21, 21, 21)
                flat = Image.new("RGB", im.size, bg_rgb)
                flat.paste(im, mask=im.split()[3])
                return ImageTk.PhotoImage(flat, master=self)
        except ImportError:
            logger.warning("Pillow não instalado — sem ícone do item. pip install Pillow")
            return None
        except Exception as e:
            logger.debug("Ícone bytes→PhotoImage: %s", e)
            return None

    def _load_item_icon_photo(self, url: str, max_size: int = 144, item_id: Optional[int] = None):
        """Ícone: cache disco (se item_id) → rede; RAM na sessão."""
        iid = None
        if item_id is not None:
            try:
                iid = int(item_id)
            except (TypeError, ValueError):
                iid = None
        url = _normalize_media_url(
            resolve_item_icon_url(iid, url or "", base_url=BASE_URL) if iid is not None else (url or "")
        )
        ram_key = None
        if iid is not None:
            ram_key = (iid, int(max_size))
            hit = self._item_icon_photo_ram.get(ram_key)
            if hit is not None:
                return hit
        raw = None
        if iid is not None:
            raw = read_item_icon_png_bytes(
                iid, url, self._fetch_icon_url_bytes, base_url=BASE_URL
            )
        elif url:
            raw = self._fetch_icon_url_bytes(url)
        if not raw:
            return None
        ph = self._photoimage_from_icon_bytes(raw, max_size)
        if ph is not None and ram_key is not None:
            self._item_icon_photo_ram[ram_key] = ph
        return ph

    def _build_item_preview_card(self, parent, item, photo_holder=None):
        """Painel claro à direita (nome, ícone, descrição, peso), como no site.
        photo_holder: se for uma list, a PhotoImage é guardada em photo_holder[0]
        (janela extra); senão usa self._item_detail_photo_ref."""
        U = ITEM_CARD_UI
        wrap = tk.Frame(
            parent,
            bg=U["bg"],
            highlightbackground=U["border"],
            highlightthickness=2,
        )
        wrap.pack(fill="y", anchor="n")

        inner = tk.Frame(wrap, bg=U["bg"])
        inner.pack(fill="x", padx=12, pady=14)

        title = item.get("item_card_title") or item.get("name") or "Item"
        tk.Label(
            inner,
            text=title,
            bg=U["bg"],
            fg=U["title"],
            font=("Segoe UI", 11, "bold"),
            wraplength=232,
            justify="center",
        ).pack(fill="x", pady=(0, 10))

        try:
            card_iid = int(item.get("id"))
        except (TypeError, ValueError):
            card_iid = None
        icon_url = _normalize_media_url(
            resolve_item_icon_url(card_iid, item.get("item_icon_url") or "", base_url=BASE_URL)
        )
        img_holder = tk.Frame(inner, bg=U["bg"], highlightbackground="#e8dfd0", highlightthickness=1)
        img_holder.pack(fill="x", pady=(0, 10))

        photo = self._load_item_icon_photo(icon_url, item_id=card_iid) if icon_url or card_iid else None
        if photo:
            if photo_holder is not None:
                photo_holder.clear()
                photo_holder.append(photo)
            else:
                self._item_detail_photo_ref = photo
            img_lbl = tk.Label(img_holder, image=photo, bg=U["bg"])
            img_lbl._tk_photo_ref = photo
            img_holder._tk_photo_ref = photo
            img_lbl.pack(padx=10, pady=12)
        else:
            tk.Label(
                img_holder,
                text="Sem imagem",
                bg=U["bg"],
                fg=U["muted"],
                font=("Segoe UI", 9),
                pady=28,
            ).pack(fill="x")

        desc = (item.get("item_description") or "").strip()
        
        # Debug: log quando descrição está vazia mas deveria ter
        if not desc and item.get("name"):
            logger.debug(f"⚠️ Item '{item.get('name')}' (ID {item.get('id')}) sem descrição extraída")
        
        desc_fr = tk.Frame(inner, bg=U["desc_bg"], highlightbackground="#ddd", highlightthickness=1)
        desc_fr.pack(fill="x", pady=(0, 10))
        if desc:
            # Usar Text widget para melhor formatação de múltiplas linhas
            desc_text = tk.Text(
                desc_fr,
                bg=U["desc_bg"],
                fg=U["desc_fg"],
                font=("Segoe UI", 9),
                height=25,
                width=28,
                wrap="word",
                relief="flat",
                borderwidth=0,
                padx=10,
                pady=10,
            )
            desc_text.pack(fill="both", expand=True)
            desc_text.insert(tk.END, desc)
            desc_text.config(state="disabled")  # Somente leitura
        else:
            tk.Label(
                desc_fr,
                text="Sem descrição disponível.",
                bg=U["desc_bg"],
                fg=U["muted"],
                font=("Segoe UI", 8),
                wraplength=228,
            ).pack(fill="x", padx=10, pady=10)

        weight = (item.get("item_weight") or "").strip()
        badge = tk.Frame(inner, bg=U["weight_bg"], highlightbackground=U["border"], highlightthickness=1)
        badge.pack(anchor="w")
        tk.Label(
            badge,
            text=f"Peso: {weight}" if weight else "Peso: —",
            bg=U["weight_bg"],
            fg=U["weight_fg"],
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=6,
        ).pack()

        tk.Label(
            inner,
            text=f"ID {item.get('id', '?')}",
            bg=U["bg"],
            fg=U["muted"],
            font=("Segoe UI", 8),
        ).pack(pady=(10, 0))

    def _show_alert_dialog(self, item):
        """Diálogo modal para configurar alertas (Evita travar cliques no Windows)."""
        dialog = tk.Toplevel(self)
        dialog.title(f"Alerta de Preço — {item.get('name', 'Item')}")
        dialog.configure(bg=C["bg"])
        dialog.resizable(False, False)
        dialog.transient(self)
        # Altura suficiente para radiobuttons + botões sempre visíveis
        dialog.geometry("480x680")

        shell = RoundedCard(dialog, radius=22, margin=10, fill_key="card")
        shell.pack(fill="both", expand=True, padx=12, pady=12)
        root = shell.inner

        def dismiss():
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            dialog.destroy()

        # ── Header ───────────────────────────────────────────────────────────
        hdr = tk.Frame(root, bg=C["bg2"])
        hdr.pack(fill="x", padx=0, pady=0)
        tk.Label(hdr, text="📢 Configurar Alerta", bg=C["bg2"], fg=C["purple3"],
                 font=("Segoe UI", 12, "bold")).pack(padx=20, pady=12)

        # Conteúdo sem expand=True para não empurrar botões para fora da área clicável
        content = tk.Frame(root, bg=C["card"])
        content.pack(fill="x", padx=20, pady=16)

        tk.Label(content, text="Alertar quando o preço:", bg=C["card"], fg=C["text"],
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 8))

        alert_type = tk.StringVar(value="below")
        DarkRadiobutton(
            content,
            text="Cair abaixo de:",
            variable=alert_type,
            value="below",
            bg=C["card"],
        ).pack(anchor="w", fill="x")
        DarkRadiobutton(
            content,
            text="Subir acima de:",
            variable=alert_type,
            value="above",
            bg=C["card"],
        ).pack(anchor="w", fill="x")

        entry_frame = tk.Frame(content, bg=C["card"])
        entry_frame.pack(fill="x", pady=(12, 8))
        tk.Label(entry_frame, text="Valor:", bg=C["card"], fg=C["text"]).pack(side="left", padx=(0, 10))
        price_entry = DarkEntry(entry_frame, width=18)
        price_entry.pack(side="left")

        tk.Label(content, text="Moeda:", bg=C["card"], fg=C["text"]).pack(anchor="w", pady=(8, 4))

        sale_type = tk.StringVar(value="zeny")
        currency_opts = [
            ("zeny", "ZENY"),
            ("rmt", "RMT"),
            ("hero_points", "HERO POINTS"),
        ]
        for val, label in currency_opts:
            DarkRadiobutton(
                content,
                text=label,
                variable=sale_type,
                value=val,
                bg=C["card"],
            ).pack(anchor="w", fill="x")

        tk.Label(
            content,
            text="E-mail para notificação (opcional — se vazio, usa o padrão em Configurações):",
            bg=C["card"],
            fg=C["text"],
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(12, 4))
        email_entry = DarkEntry(content, width=42)
        email_entry.pack(anchor="w", fill="x")
        try:
            email_entry.insert(0, (load_settings().get("notify_email") or "").strip())
        except Exception:
            pass

        tk.Label(
            content,
            text="Refino (opcional):",
            bg=C["card"],
            fg=C["text"],
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(14, 2))
        tk.Label(
            content,
            text="Deixe vazio para qualquer refino. Ex.: 10 — só contam ofertas com refino +10 ou superior.",
            bg=C["card"],
            fg=C["text3"],
            font=("Segoe UI", 8),
            wraplength=420,
            justify="left",
        ).pack(anchor="w")
        ref_frame = tk.Frame(content, bg=C["card"])
        ref_frame.pack(fill="x", pady=(4, 0))
        tk.Label(ref_frame, text="+", bg=C["card"], fg=C["text"]).pack(side="left")
        refinement_entry = DarkEntry(ref_frame, width=6)
        refinement_entry.pack(side="left", padx=(2, 0))

        btn_frame = tk.Frame(root, bg=C["card"])
        btn_frame.pack(fill="x", padx=20, pady=(16, 20))

        def save_alert():
            raw_p = price_entry.get().strip()
            try:
                price_value = float(parse_price_cell(raw_p))
            except (ValueError, TypeError):
                messagebox.showerror(
                    "Erro",
                    "Digite um valor válido (ex.: 500000, 350.000, 12,99 ou 225,000).",
                    parent=dialog,
                )
                return
            if price_value <= 0:
                messagebox.showerror("Erro", "O valor deve ser maior que zero.", parent=dialog)
                return

            ref_raw = refinement_entry.get().strip()
            refinement_val = None
            if ref_raw != "":
                try:
                    refinement_val = int(ref_raw)
                except ValueError:
                    messagebox.showerror(
                        "Erro", "Refino inválido: use um número inteiro (ex.: 0, 7, 10) ou deixe vazio.",
                        parent=dialog,
                    )
                    return
                if refinement_val < 0 or refinement_val > 20:
                    messagebox.showerror("Erro", "Refino deve estar entre 0 e 20.", parent=dialog)
                    return

            sl = item.get("stores_list")
            if isinstance(sl, list) and sl:
                mp = monitored_service.sale_min_prices_from_stores(sl, min_refinement=refinement_val)
            elif refinement_val is not None:
                mp = {}
            else:
                mp = dict(item["min_prices"]) if item.get("min_prices") else {}

            alerts = load_alerts()
            key = f"{item['id']}_{sale_type.get()}"
            alerts[key] = {
                "item_id": item["id"],
                "item_name": item.get("name"),
                "price": price_value,
                "type": alert_type.get(),
                "sale_type": sale_type.get(),
                "notify_email": email_entry.get().strip(),
                "condition_met": False,
                "created_at": datetime.now().isoformat(),
                **({"item_icon_url": item["item_icon_url"]} if item.get("item_icon_url") else {}),
                **({"min_prices": mp} if mp else {}),
            }
            if refinement_val is not None:
                alerts[key]["refinement"] = refinement_val
            else:
                alerts[key].pop("refinement", None)
            # Ofertas que já cumprem o critério no momento do save ficam «vistas» — só notifica ofertas novas depois.
            try:
                st_chk, _ = self._fetch_item_stores(int(item["id"]), str(item.get("name") or ""))
            except Exception:
                st_chk = list(item.get("stores_list") or [])
            fx = filter_stores_by_currency(st_chk, alerts[key]["sale_type"])
            fx = filter_stores_by_refinement(fx, alerts[key])
            alerts[key]["notified_listing_keys"] = [
                listing_fingerprint(s) for s in qualifying_stores_for_alert(alerts[key], fx)
            ]
            save_alerts(alerts)
            dismiss()
            messagebox.showinfo(
                "Sucesso",
                f"Alerta salvo para {item.get('name')} ({sale_type.get().replace('_', ' ').upper()}). "
                "O programa verifica as lojas online periodicamente; será notificado por cada nova oferta "
                "que cumprir o critério (e-mail e aviso na app, se o SMTP e o destino estiverem configurados).",
                parent=self,
            )

        DarkButton(btn_frame, text="✓ Salvar", style="success", command=save_alert).pack(side="left", padx=4)
        DarkButton(btn_frame, text="✕ Cancelar", style="danger", command=dismiss).pack(side="left", padx=4)

        dialog.protocol("WM_DELETE_WINDOW", dismiss)
        price_entry.focus_set()

        try:
            x = self.winfo_rootx() + 80
            y = self.winfo_rooty() + 40
            dialog.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

        dialog.update_idletasks()
        dialog.lift(self)
        dialog.focus_force()
        try:
            dialog.grab_set()
        except tk.TclError:
            pass

    def _open_item_detail_window(self, *, item=None, item_id=None, item_name_hint=""):
        """Abre lojas + histórico do item numa nova janela (sempre)."""
        if item is not None:
            iid = int(item["id"])
            iw = dict(item)
            title_name = str(iw.get("name") or item_name_hint or f"Item {iid}")
        elif item_id is not None:
            iid = int(item_id)
            title_name = str(item_name_hint or f"Item {iid}")
            iw = {"id": iid, "name": title_name}
        else:
            return

        win = tk.Toplevel(self)
        win.title(f"{title_name} — lojas e histórico")
        win.geometry("1000x760")
        win.configure(bg=C["bg"])
        win.minsize(720, 520)

        shell = RoundedCard(win, radius=20, margin=8, fill_key="card")
        shell.pack(fill="both", expand=True, padx=10, pady=10)
        container = shell.inner

        def clear_popup_chart():
            c = getattr(win, "_hs_chart_canvas", None)
            if c is not None:
                try:
                    c.get_tk_widget().destroy()
                except Exception:
                    pass
                win._hs_chart_canvas = None

        def set_popup_chart(c):
            clear_popup_chart()
            win._hs_chart_canvas = c

        tk.Label(
            container,
            text="⏳ A carregar lojas online e histórico de vendas…",
            bg=C["card"],
            fg=C["text3"],
            font=("Segoe UI", 11),
        ).pack(expand=True, pady=48)

        preview_ph = []

        def _safe_relift_item_win():
            try:
                if win.winfo_exists():
                    win.lift(self)
            except tk.TclError:
                pass

        def finish(iwork, data):
            if not win.winfo_exists():
                return
            clear_popup_chart()
            for w in container.winfo_children():
                w.destroy()
            try:
                self._render_detail_into(
                    container,
                    iwork,
                    data if isinstance(data, dict) else {"sales": []},
                    chart_setter=set_popup_chart,
                    preview_photo_holder=preview_ph,
                )
            except Exception as ex:
                logger.exception("Render detalhe item %s", iid)
                fail(str(ex))
                return
            disp = (
                str(iwork.get("name") or iwork.get("item_card_title") or "").strip()
                or f"Item {iwork.get('id', '?')}"
            )
            try:
                win.title(f"{disp} — lojas e histórico")
            except tk.TclError:
                pass
            try:
                win.lift(self)
                win.after(150, _safe_relift_item_win)
            except tk.TclError:
                pass

        def fail(msg):
            if not win.winfo_exists():
                return
            clear_popup_chart()
            for w in container.winfo_children():
                w.destroy()
            tk.Label(
                container,
                text=f"⚠ Erro ao carregar:\n{msg}",
                bg=C["bg"],
                fg=C["red"],
                font=("Segoe UI", 10),
                wraplength=480,
                justify="center",
            ).pack(expand=True, pady=40)

        def run():
            import app_runtime as rt

            try:
                data = rt.api_item_history(iid)
                iwork = dict(iw)
                try:
                    stores, meta = self._fetch_item_stores(
                        iid, str(iwork.get("name") or item_name_hint or "")
                    )
                    for _k in _ITEM_CARD_KEYS:
                        v = (meta or {}).get(_k)
                        if v:
                            iwork[_k] = _normalize_media_url(v) if _k == "item_icon_url" else v
                    iwork["stores_list"] = list(stores) if stores else []
                except Exception as ex:
                    logger.warning("Lojas item %s: %s", iid, ex)
                rt._sync_iwork_name_from_sources(iwork, data if isinstance(data, dict) else None)
                iwork_snap = dict(iwork)
                data_snap = dict(data) if isinstance(data, dict) else data
                self.after(0, lambda iw=iwork_snap, dt=data_snap: finish(iw, dt))
            except Exception as ex:
                logger.error("Janela item %s: %s", iid, ex)
                self.after(0, lambda m=str(ex): fail(m))

        def on_close():
            clear_popup_chart()
            try:
                win.destroy()
            except tk.TclError:
                pass

        win.protocol("WM_DELETE_WINDOW", on_close)
        threading.Thread(target=run, daemon=True).start()

    def _open_search_by_item_id(self, item_id: int, item_name: str = ""):
        """Compat: abre detalhe (lojas + histórico) numa nova janela."""
        self._open_item_detail_window(item_id=item_id, item_name_hint=item_name or "")

