"""
GDZ Monitor — Aplicativo Desktop
Monitora preços e histórico de vendas do Hero Saga (herosaga.com.br)
"""

import sys

import matplotlib

matplotlib.use("TkAgg")

import tkinter as tk
from tkinter import messagebox, ttk

from app_runtime import get_stores_from_item_page, load_data, load_prices_history, logger
from app_settings import load_settings
from build_simulator import load_builds_file
from loot_manager import LootManager
from mvp_timer import load_mvp_storage
from ui.pages.alerts import AlertsMixin
from ui.pages.build_sim import BuildSimMixin
from ui.pages.busca import BuscaPageMixin
from ui.pages.config import ConfigMixin
from ui.pages.hist import HistPageMixin
from ui.pages.item_detail import ItemDetailMixin
from ui.pages.loot_page import LootPageMixin
from ui.pages.monitor_list import MonitorListMixin
from ui.pages.monitored_home import MonitoredHomeMixin
from ui.pages.mvp_timer import MvpTimerMixin
from ui.shared.item_snapshot import ItemSnapshotMixin
from ui.shell import AppShellMixin
from ui.theme import C
from ui.widgets import HAS_PIL_ROUND, StartupSplash, pil_round_solid

# Reexport API para testes e scripts legados (`from app import api_search`, etc.)
from app_runtime import (  # noqa: E402,F401
    SCRAPER_AVAILABLE,
    _sync_iwork_name_from_sources,
    api_item_history,
    api_search,
    api_vending_search,
    clean_json_response,
    clean_shop_name,
    collect_price,
    fmt_price,
    fmt_price_stores,
    get_herosaga_item_stores,
    group_sales_by_type,
    item_emoji,
    item_matches_search,
    safe_get,
)


# ════════════════════════════════════════════════════════════════════════════
# JANELA PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════


class HeroSagaMonitor(
    AppShellMixin,
    ItemSnapshotMixin,
    BuscaPageMixin,
    MonitoredHomeMixin,
    ItemDetailMixin,
    MonitorListMixin,
    AlertsMixin,
    ConfigMixin,
    BuildSimMixin,
    MvpTimerMixin,
    LootPageMixin,
    HistPageMixin,
    tk.Tk,
):
    def __init__(self):
        super().__init__()
        self._startup_complete = False
        self.title("GDZ Monitor")
        self.geometry("1100x680")
        self.minsize(800, 550)
        self.configure(bg=C["bg"])

        self._search_panel = None
        self.chart_canvas = None
        self._item_detail_photo_ref = None
        self._alert_after_id = None
        self._monitored_home_photo_refs = []
        self._monitor_list_photo_refs = []
        self._alertas_list_photo_refs = []
        self._monitored_home_refresh_gen = 0
        self._alerts_display_refresh_gen = 0
        self._mh_drag = {"active": False}
        self._mh_inners = {}
        self._mh_col_shells = {}
        self._mh_cards_by_id = {}
        self._mh_drag_indicator = None
        self._mh_drag_indicator_category = None
        self._mh_icon_load_gen = 0
        self._mh_prices_refreshing = False
        self._item_icon_photo_ram = {}

        self.protocol("WM_DELETE_WINDOW", self._on_close_request)

        self._style()
        self.withdraw()

        splash = StartupSplash(self)
        splash.update()
        splash.protocol("WM_DELETE_WINDOW", lambda sp=splash: self._cancel_startup_load(sp))

        try:
            splash.grab_set()
        except tk.TclError:
            pass

        try:
            splash.set_progress(5, "A carregar dados locais…")
            self.data = load_data()
            self.loot_manager = LootManager()

            splash.set_progress(28, "A construir janelas e painéis…")
            self._build_ui()

            splash.set_progress(58, "A carregar definições e ficheiros de apoio…")
            self._startup_preload_auxiliary_data()

            splash.set_progress(72, "A carregar catálogo MVP…")
            self._mvp_startup_warm()

            splash.set_progress(84, "A preparar o monitor de alertas…")
            self._update_badge()
            self._schedule_alert_monitor_cycle()
            self._mvp_start_spawn_alert_watch()

            splash.set_progress(93, "A preparar gráficos e fontes…")
            self._startup_warmup()

            splash.set_progress(100, "Concluído.")
            splash.update_idletasks()
        except Exception:
            try:
                splash.grab_release()
            except tk.TclError:
                pass
            try:
                splash.destroy()
            except tk.TclError:
                pass
            try:
                self.deiconify()
            except tk.TclError:
                pass
            raise
        else:
            try:
                splash.grab_release()
            except tk.TclError:
                pass
            try:
                splash.destroy()
            except tk.TclError:
                pass
            self.deiconify()
            self.lift()
            try:
                self.focus_force()
            except tk.TclError:
                pass

        self._startup_complete = True

    def _fetch_item_stores(self, item_id: int, item_name: str = "", *, force_refresh: bool = False):
        """Delegação para ``get_stores_from_item_page`` (uso pelos mixins)."""
        return get_stores_from_item_page(item_id, item_name, force_refresh=force_refresh)

    def _cancel_startup_load(self, splash: tk.Toplevel) -> None:
        try:
            splash.grab_release()
        except tk.TclError:
            pass
        try:
            splash.destroy()
        except tk.TclError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass

    def _startup_preload_auxiliary_data(self) -> None:
        for fn in (
            load_settings,
            load_mvp_storage,
            load_builds_file,
            load_prices_history,
        ):
            try:
                fn()
            except Exception:
                logger.debug(
                    "Falha no pré-load de arranque: %s",
                    getattr(fn, "__name__", repr(fn)),
                    exc_info=True,
                )

    def _on_close_request(self):
        try:
            if hasattr(self, "_build_sim_persist_last_saved_id"):
                self._build_sim_persist_last_saved_id()
        except Exception:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass

    def _startup_warmup(self):
        """Pré-aquece Tk/PIL para o primeiro arrasto e redesenho ficarem mais fluidos."""
        try:
            self.update_idletasks()
            self.tk.call("font", "metrics", "Segoe UI", "-ascent")
        except tk.TclError:
            pass
        if HAS_PIL_ROUND:
            try:
                pil_round_solid(10, 10, 3, C.get("card", "#2a2a2a"))
            except Exception:
                pass

    def _style(self):
        style = ttk.Style()
        style.theme_use("clam")
        sb_trough = C.get("sb_trough", C.get("border", C["bg3"]))
        sb_thumb = C.get("sb_thumb", C.get("bg3", "#1a1a1a"))
        sb_thumb_hover = C.get("sb_thumb_hover", C.get("border2", "#3a3a3a"))
        sb_thumb_pressed = C.get("sb_thumb_active", C.get("purple", "#8b5cf6"))
        style.configure(
            "TScrollbar",
            background=sb_thumb,
            troughcolor=sb_trough,
            bordercolor=sb_trough,
            darkcolor=sb_trough,
            lightcolor=sb_trough,
            arrowcolor=C.get("text3", "#737373"),
            borderwidth=0,
            relief="flat",
            gripcount=0,
            width=12,
        )
        try:
            style.configure("TScrollbar", arrowsize=11)
        except tk.TclError:
            pass
        style.map(
            "TScrollbar",
            background=[
                ("pressed", sb_thumb_pressed),
                ("active", sb_thumb_hover),
                ("!disabled", sb_thumb),
            ],
            arrowcolor=[
                ("pressed", C.get("purple3", C["text2"])),
                ("active", C.get("text2", "#b0b0b0")),
                ("!disabled", C.get("text3", "#737373")),
            ],
        )
        style.configure(
            "Treeview",
            background=C["card"],
            foreground=C["text2"],
            fieldbackground=C["card"],
            rowheight=30,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Treeview.Heading",
            background=C.get("column_hdr", C["bg3"]),
            foreground=C.get("column_hdr_fg", C["text2"]),
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            padding=(4, 6),
        )
        style.map(
            "Treeview.Heading",
            background=[
                ("active", C.get("border2", C["bg3"])),
                ("pressed", C.get("border2", C["bg3"])),
                ("!disabled", C.get("column_hdr", C["bg3"])),
            ],
            foreground=[
                ("active", C.get("column_hdr_fg", C["text2"])),
                ("pressed", C.get("column_hdr_fg", C["text2"])),
                ("!disabled", C.get("column_hdr_fg", C["text2"])),
            ],
        )
        style.map(
            "Treeview",
            background=[("selected", C["border2"])],
            foreground=[("selected", C["purple3"])],
        )


# ════════════════════════════════════════════════════════════════════════════
# APLICAÇÃO PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        logger.info("🚀 Iniciando GDZ Monitor...")
        app = HeroSagaMonitor()
        app.mainloop()
    except KeyboardInterrupt:
        logger.info("⏹️ Aplicação encerrada pelo usuário")
    except Exception as e:
        logger.error("❌ Erro fatal: %s", e)
        import traceback

        logger.error(traceback.format_exc())
        messagebox.showerror("Erro Fatal", f"Erro: {str(e)}")
