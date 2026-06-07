"""
Página «Monitorados» (lista completa).
Mixin usado por ``HeroSagaMonitor``.
"""
from __future__ import annotations

from datetime import datetime
import threading
import tkinter as tk
from tkinter import messagebox

from adapters.persistence import save_data
from mvp_timer import mvp_catalog_matches_search
from services import monitored as monitored_service
from ui.theme import C
from ui.widgets import DarkButton, ScrollableFrame

item_matches_search = lambda entry, q: monitored_service.item_matches_search(
    entry, q, mvp_catalog_matches_search_fn=mvp_catalog_matches_search
)


class MonitorListMixin:
    """Lista de itens monitorados (página dedicada)."""


    # ── MONITORADOS ──────────────────────────────────────────────────────────
    def _add_monitor(self, item, sales=None, detail_btn_frame=None):
        try:
            iid = int(item["id"])
        except (TypeError, ValueError):
            return
        if any(int(m["id"]) == iid for m in self.data["monitored"]):
            messagebox.showinfo("Info", "Este item já está sendo monitorado.")
            return
        last_price = sales[0]["price"] if sales else 0
        self.data["monitored"].append({
            "id": iid,
            "name": item.get("name", "Item"),
            "is_costume": item.get("is_costume", False),
            "last_price": last_price,
            "added_at": datetime.now().isoformat(),
            "category": "Gerais",
            **({"item_icon_url": item["item_icon_url"]} if item.get("item_icon_url") else {}),
            **({"min_prices": dict(item["min_prices"])} if item.get("min_prices") else {}),
        })
        save_data(self.data)
        self._update_badge()
        pg = getattr(self, "current_page", None) and self.current_page.get()
        if pg == "busca":
            self._render_monitored_home()
        elif pg == "monitor":
            self._render_monitor()
        if pg == "monitor":
            self._monitored_home_refresh_gen += 1
            g = self._monitored_home_refresh_gen
            threading.Thread(
                target=lambda gen=g: self._refresh_monitored_home_prices_worker(gen),
                daemon=True,
            ).start()
        if detail_btn_frame is not None:
            try:
                if detail_btn_frame.winfo_exists():
                    self._pack_detail_window_header_actions(
                        detail_btn_frame, dict(item), sales if isinstance(sales, list) else []
                    )
            except tk.TclError:
                pass
        else:
            try:
                idx = next(i for i, it in enumerate(self.current_items) if int(it.get("id", -1)) == iid)
            except (StopIteration, TypeError, ValueError):
                idx = None
            if idx is not None and getattr(self, "items_scroll", None) is not None:
                self._render_items(self.current_items)

    def _remove_monitor(self, item, detail_btn_frame=None, detail_all_sales=None):
        try:
            iid = int(item["id"])
        except (TypeError, ValueError):
            return
        self.data["monitored"] = [m for m in self.data["monitored"] if int(m["id"]) != iid]
        save_data(self.data)
        self._update_badge()
        if getattr(self, "current_page", None) and self.current_page.get() == "busca":
            self._render_monitored_home()
        elif getattr(self, "current_page", None) and self.current_page.get() == "monitor":
            self._render_monitor()
        if detail_btn_frame is not None:
            try:
                if detail_btn_frame.winfo_exists():
                    sl = detail_all_sales if isinstance(detail_all_sales, list) else []
                    self._pack_detail_window_header_actions(detail_btn_frame, dict(item), sl)
            except tk.TclError:
                pass
        else:
            try:
                idx = next(i for i, it in enumerate(self.current_items) if int(it.get("id", -1)) == iid)
            except (StopIteration, TypeError, ValueError):
                idx = None
            if idx is not None and getattr(self, "items_scroll", None) is not None:
                self._render_items(self.current_items)

    def _build_monitor(self):
        self.monitor_frame = tk.Frame(self.main, bg=C["bg"])

        hdr = tk.Frame(self.monitor_frame, bg=C["bg"])
        hdr.pack(fill="x", padx=20, pady=(20, 4))
        tk.Label(hdr, text="Itens Monitorados", bg=C["bg"], fg=C["purple3"],
                 font=("Segoe UI", 16, "bold")).pack(anchor="w")
        tk.Label(
            hdr,
            text="Menores preços por moeda nas lojas. Atualiza ao abrir a página.",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 9),
            wraplength=520,
            justify="left",
        ).pack(anchor="w")

        mon_search_row = tk.Frame(self.monitor_frame, bg=C["bg"])
        mon_search_row.pack(fill="x", padx=20, pady=(8, 0))
        self._pack_list_search_bar(mon_search_row, "monitor", "Buscar item (nome ou ID):")

        self.monitor_list_frame = ScrollableFrame(self.monitor_frame)
        self.monitor_list_frame.pack(fill="both", expand=True, padx=20, pady=10)

    def _show_monitor(self):
        self._clear_main()
        self.monitor_frame.pack(fill="both", expand=True)
        self._render_monitor()
        self._monitored_home_refresh_gen += 1
        gen = self._monitored_home_refresh_gen
        threading.Thread(
            target=lambda g=gen: self._refresh_monitored_home_prices_worker(g),
            daemon=True,
        ).start()

    def _render_monitor(self):
        for w in self.monitor_list_frame.inner.winfo_children():
            w.destroy()
        self._monitor_list_photo_refs = []

        monitored_all = self.data.get("monitored") or []
        mon_q = self._list_search_query("monitor")
        monitored = monitored_all
        if mon_q:
            monitored = [m for m in monitored_all if item_matches_search(m, mon_q)]

        if not monitored:
            if monitored_all and mon_q:
                empty_msg = f"🔍\n\nNenhum item corresponde a «{mon_q}»."
            else:
                empty_msg = (
                    "🔔\n\nNenhum item monitorado.\n\nAbra um item e toque em « + Monitorar »."
                )
            tk.Label(
                self.monitor_list_frame.inner,
                text=empty_msg,
                bg=C["bg"],
                fg=C["text3"],
                font=("Segoe UI", 11),
                justify="center",
            ).pack(pady=60)
            self._list_search_update_hint("monitor", 0, len(monitored_all))
            return

        for m in monitored:
            added = m.get("added_at", "")[:10]
            _, row, bind_target = self._pack_item_store_snapshot_row(
                self.monitor_list_frame.inner,
                m,
                self._monitor_list_photo_refs,
                wraplength=520,
                layout="split",
                id_subline=f"ID: {m['id']}  ·  Adicionado: {added}",
            )
            btns = tk.Frame(row, bg=C["card"])
            btns.pack(side="right")
            DarkButton(
                btns,
                text="Ver preços",
                style="ghost",
                command=lambda iid=m["id"], nm=str(m.get("name", "") or ""): self._open_search_by_item_id(iid, nm),
            ).pack(side="left", padx=3)
            DarkButton(
                btns,
                text="Remover",
                style="danger",
                command=lambda mid=m["id"]: self._remove_by_id(mid),
            ).pack(side="left")
            self._bind_click_open_item_detail(bind_target, int(m["id"]), str(m.get("name", "") or ""))

        self._list_search_scroll_to_top(self.monitor_list_frame)
        self._list_search_update_hint("monitor", len(monitored), len(monitored_all))

    def _remove_by_id(self, item_id):
        try:
            rid = int(item_id)
        except (TypeError, ValueError):
            return
        self.data["monitored"] = [m for m in self.data["monitored"] if int(m["id"]) != rid]
        save_data(self.data)
        self._update_badge()
        self._render_monitor()
        if getattr(self, "current_page", None) and self.current_page.get() == "busca":
            self._render_monitored_home()

