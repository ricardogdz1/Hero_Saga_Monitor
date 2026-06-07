"""
Shell da aplicação: sidebar, navegação, busca em listas.
"""
from __future__ import annotations

import logging
import os
import tkinter as tk
from tkinter import messagebox

from app_runtime import LOG_FILE
from app_settings import load_settings
from ui.theme import C, apply_palette
from ui.widgets import DarkEntry, NavPillButton

logger = logging.getLogger(__name__)

_LIST_SEARCH_DEBOUNCE_MS = 300


class AppShellMixin:
    """Layout principal e navegação entre páginas."""

    def _build_ui(self):
        # ── Sidebar ─────────────────────────────────────────────────────────
        sidebar = tk.Frame(self, bg=C["bg2"], width=200)
        self.sidebar_frame = sidebar
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        # Logo
        logo_frame = tk.Frame(sidebar, bg=C["bg2"])
        logo_frame.pack(fill="x", padx=14, pady=(16, 12))
        tk.Label(logo_frame, text="⚔", bg=C["bg2"], fg=C["purple3"],
                 font=("Segoe UI", 18)).pack(side="left")
        tk.Label(logo_frame, text=" GDZ", bg=C["bg2"], fg=C["purple3"],
                 font=("Segoe UI", 13, "bold")).pack(side="left")

        tk.Frame(sidebar, bg=C["border"], height=1).pack(fill="x", padx=10, pady=(0, 10))

        # Navegação
        self.nav_frames = {}
        self.current_page = tk.StringVar(value="busca")

        nav_items = [
            ("busca",   "🏠  Home",           self._show_busca),
            ("monitor", "🔔  Monitorados",    self._show_monitor),
            ("build",   "📐  Simulação de Build", self._show_build_sim),
            ("mvp",     "⏱  Timer MVP",     self._show_mvp_timer),
            ("loot",    "🎒  Auto Loot",     self._show_loot),
            ("alertas", "🔊  Alertas",        self._show_alertas),
            ("config",  "⚙  Configurações", self._show_config),
            ("hist",    "📋  Histórico",      self._show_hist),
        ]
        for key, label, cmd in nav_items:
            btn = NavPillButton(sidebar, text=label, command=lambda k=key, c=cmd: self._nav(k, c))
            btn.pack(fill="x", padx=8, pady=3)
            self.nav_frames[key] = btn

        # Badge contador (frame fixo + place para não sair do botão)
        self.badge_fr = tk.Frame(self.nav_frames["monitor"], bg=C["purple"], width=22, height=18)
        self.badge_fr.pack_propagate(False)
        self.badge_lbl = tk.Label(
            self.badge_fr,
            text="",
            bg=C["purple"],
            fg="white",
            font=("Segoe UI", 7, "bold"),
        )
        self.badge_lbl.pack(expand=True)

        # Footer sidebar
        tk.Frame(sidebar, bg=C["border"], height=1).pack(fill="x", padx=10, pady=8, side="bottom")
        tk.Label(sidebar, text="herosaga.com.br", bg=C["bg2"], fg=C["text3"],
                 font=("Segoe UI", 8)).pack(side="bottom", pady=(0, 8))
        self.status_dot = tk.Label(sidebar, text="● online", bg=C["bg2"], fg=C["green"],
                                   font=("Segoe UI", 8))
        self.status_dot.pack(side="bottom")
        
        # Link para abrir logs
        log_link = tk.Label(sidebar, text="📋 Logs", bg=C["bg2"], fg=C["purple2"],
                           font=("Segoe UI", 8, "underline"), cursor="hand2")
        log_link.pack(side="bottom", pady=(2, 0))
        log_link.bind("<Button-1>", lambda e: self._open_logs())

        # ── Área principal ───────────────────────────────────────────────────
        self.main = tk.Frame(self, bg=C["bg"])
        self.main.pack(side="left", fill="both", expand=True)

        self._build_busca()
        self._build_monitor()
        self._build_alertas()
        self._build_config()
        self._build_build_sim()
        self._build_mvp_timer()
        self._build_loot()
        self._build_hist()

        self._init_search_panel()
        self._nav("busca", self._show_busca)

    def _reapply_theme(self, theme: str):
        """Aplica paleta e reconstrói barra lateral e área principal."""
        apply_palette(theme)
        self.configure(bg=C["bg"])
        self._style()
        try:
            self.sidebar_frame.destroy()
        except (tk.TclError, AttributeError):
            pass
        try:
            self.main.destroy()
        except (tk.TclError, AttributeError):
            pass
        self._build_ui()
        self._update_badge()

    def _nav(self, key, cmd):
        self.current_page.set(key)
        for k, btn in self.nav_frames.items():
            if hasattr(btn, "set_active"):
                btn.set_active(k == key)
            elif k == key:
                btn.configure(bg=C["bg3"], fg=C["purple3"])
            else:
                btn.configure(bg=C["bg2"], fg=C["text2"])
        cmd()

    def _open_logs(self):
        """Abre o arquivo de log do Windows"""
        try:
            os.startfile(LOG_FILE)
            logger.info("Log file opened by user")
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível abrir o arquivo de log:\n{e}")
            logger.error(f"Failed to open log file: {e}")

    def _clear_main(self):
        for w in self.main.winfo_children():
            w.pack_forget()

    def _list_search_query(self, prefix: str) -> str:
        try:
            var = getattr(self, f"_{prefix}_search_var")
            return str(var.get() or "").strip()
        except (tk.TclError, AttributeError):
            return ""

    def _list_search_show_busy(self, prefix: str) -> None:
        lbl = getattr(self, f"_{prefix}_search_hint", None)
        if lbl is None:
            return
        try:
            if self._list_search_query(prefix):
                lbl.configure(text="Filtrando…")
            else:
                lbl.configure(text="")
        except tk.TclError:
            pass

    def _list_search_update_hint(self, prefix: str, shown: int, total: int) -> None:
        lbl = getattr(self, f"_{prefix}_search_hint", None)
        if lbl is None:
            return
        q = self._list_search_query(prefix)
        try:
            if not q:
                lbl.configure(text="")
            elif shown == 0:
                lbl.configure(text="Nenhum resultado")
            elif shown < total:
                lbl.configure(text=f"{shown} de {total}")
            else:
                lbl.configure(text=f"{shown} resultado(s)" if shown != 1 else "1 resultado")
        except tk.TclError:
            pass

    def _list_search_scroll_to_top(self, scroll_frame) -> None:
        canvas = getattr(scroll_frame, "_canvas", None)
        if canvas is None:
            return
        try:
            canvas.yview_moveto(0)
        except tk.TclError:
            pass

    def _list_search_on_change(self, prefix: str) -> None:
        aid = getattr(self, f"_{prefix}_search_after_id", None)
        if aid is not None:
            try:
                self.after_cancel(aid)
            except (tk.TclError, ValueError):
                pass
        self.after(0, lambda p=prefix: self._list_search_show_busy(p))
        setattr(
            self,
            f"_{prefix}_search_after_id",
            self.after(_LIST_SEARCH_DEBOUNCE_MS, lambda p=prefix: self._list_search_apply(p)),
        )

    def _list_search_apply(self, prefix: str) -> None:
        setattr(self, f"_{prefix}_search_after_id", None)
        renderers = {
            "mh": self._render_monitored_home,
            "monitor": self._render_monitor,
            "alertas": self._render_alertas,
        }
        cb = renderers.get(prefix)
        if cb is None:
            return
        if prefix == "mh" and self.current_page.get() != "busca":
            return
        if prefix == "monitor" and self.current_page.get() != "monitor":
            return
        if prefix == "alertas" and self.current_page.get() != "alertas":
            return
        try:
            cb()
        except tk.TclError:
            pass

    def _pack_list_search_bar(self, parent, prefix: str, label_text: str) -> None:
        """Campo de busca local com debounce (comportamento do Timer MVP)."""
        if not hasattr(self, f"_{prefix}_search_var"):
            setattr(self, f"_{prefix}_search_var", tk.StringVar(value=""))
            setattr(self, f"_{prefix}_search_after_id", None)
        var = getattr(self, f"_{prefix}_search_var")

        fr = tk.Frame(parent, bg=C["bg"])
        fr.pack(fill="x")
        tk.Label(
            fr,
            text=label_text,
            bg=C["bg"],
            fg=C["text2"],
            font=("Segoe UI", 10),
        ).pack(side="left")
        tk.Entry(
            fr,
            textvariable=var,
            width=42,
            font=("Segoe UI", 10),
            bg=C["bg3"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=C["border"],
            highlightcolor=C["purple"],
        ).pack(side="left", padx=(10, 6), ipady=4)
        hint = tk.Label(
            fr,
            text="",
            bg=C["bg"],
            fg=C["text2"],
            font=("Segoe UI", 9, "italic"),
        )
        hint.pack(side="left", padx=(4, 0))
        setattr(self, f"_{prefix}_search_hint", hint)

        bound = getattr(self, f"_{prefix}_search_trace_bound", False)
        if not bound:
            var.trace_add("write", lambda *_a, p=prefix: self._list_search_on_change(p))
            setattr(self, f"_{prefix}_search_trace_bound", True)

    # ── PÁGINA: BUSCA ────────────────────────────────────────────────────────
