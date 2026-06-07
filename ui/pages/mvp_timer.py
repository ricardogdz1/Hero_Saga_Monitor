"""
Timer MVP (catálogo, grelha, alertas de spawn).
"""
from __future__ import annotations

import logging
import os
import threading
import time

import requests
from collections import OrderedDict
from datetime import datetime
from typing import Optional, Tuple

import tkinter as tk
from tkinter import messagebox, ttk

from app_settings import load_settings, save_settings
from divine_pride_api import fetch_monster
from image_loader import MvpImageLoader
from mvp_alert_sound import play_mvp_spawn_alert_sound
from mvp_timer import (
    DIVINE_PRIDE_LIST_HEADERS,
    MVP_CATALOG_PORTABLE_FILE,
    MVP_DATA_FILE,
    MVP_MAPS_DIR,
    MVP_SPRITES_DIR,
    build_mvp_map_click_mask_from_image,
    fetch_mvp_catalog_from_divine_pride,
    format_countdown_clock,
    game_to_pixel_coords,
    is_mvp_map_coord_clickable,
    load_mvp_catalog_cache,
    load_mvp_storage,
    monster_api_display_name,
    mvp_catalog_entry_skipped,
    mvp_catalog_matches_search,
    mvp_catalog_names_are_english_marked,
    mvp_dashboard_status_text,
    mvp_map_display_layout,
    new_timer_entry,
    parse_user_datetime,
    pixel_to_game_coords,
    resolve_map_image,
    save_mvp_catalog_cache,
    save_mvp_storage,
    seconds_until_spawn,
    spawn_maps_from_monster,
    summarize_monster_for_timer,
)
from ui.theme import C
from ui.widgets import DarkButton, DarkEntry, ScrollableFrame
from ui.widgets.helpers import canvas_round_fill

logger = logging.getLogger(__name__)

_MVP_MAP_DISPLAY_BOX_W = 420
_MVP_MAP_DISPLAY_BOX_H = 420
_MVP_EDIT_DIALOG_MIN_W = 600
# Largura/altura alvo: minimapa + formulário + rodapé (independente do scroll colapsado).
_MVP_EDIT_DIALOG_PREF_W = _MVP_MAP_DISPLAY_BOX_W + 200
_MVP_EDIT_DIALOG_PREF_H = (
    _MVP_MAP_DISPLAY_BOX_H
    + 320
)  # instruções, 4 linhas, status, legenda do mapa, botão Salvar, margens


def _mvp_fit_edit_dialog_geometry(
    top: tk.Toplevel,
    anchor: tk.Misc,
    *,
    inner: tk.Misc | None = None,
    footer_frm: tk.Misc | None = None,
) -> None:
    """Abre grande o suficiente para mostrar todo o formulário; só encolhe se o ecrã for baixo."""
    try:
        top.update_idletasks()
        sw = int(top.winfo_screenwidth())
        sh = int(top.winfo_screenheight())
    except (TypeError, ValueError, tk.TclError):
        return

    w = _MVP_EDIT_DIALOG_PREF_W
    h = _MVP_EDIT_DIALOG_PREF_H
    if inner is not None:
        try:
            w = max(w, int(inner.winfo_reqwidth()) + 56)
            inner_h = int(inner.winfo_reqheight())
            foot_h = 0
            if footer_frm is not None:
                foot_h = int(footer_frm.winfo_reqheight())
            h = max(h, inner_h + foot_h + 52)
        except (TypeError, ValueError, tk.TclError):
            pass

    w = min(w, sw - 48)
    h = min(h, sh - 72)

    try:
        ax = anchor.winfo_rootx() + max(int(anchor.winfo_width()), 1) // 2
        ay = anchor.winfo_rooty() + max(int(anchor.winfo_height()), 1) // 2
    except tk.TclError:
        ax, ay = sw // 2, sh // 2
    x = max(0, min(ax - w // 2, sw - w - 16))
    y = max(0, min(ay - h // 2, sh - h - 32))
    try:
        top.minsize(min(_MVP_EDIT_DIALOG_MIN_W, w), min(480, h))
        top.geometry(f"{w}x{h}+{x}+{y}")
    except tk.TclError:
        pass


class MvpTimerMixin:
    """Página Timer MVP."""

    def _build_mvp_timer(self):
        self.mvp_timer_frame = tk.Frame(self.main, bg=C["bg"])
        self._mvp_timer_tick_job = None
        self._mvp_photo_refs = []
        self._mvp_card_labels = {}
        self._mvp_catalog_items = []
        self._mvp_catalog_fetching = False
        self._mvp_spawn_enriching = False
        self._mvp_search_after_id = None
        topbar = tk.Frame(self.mvp_timer_frame, bg=C["bg"])
        topbar.pack(fill="x", padx=12, pady=(12, 4))
        topbar.columnconfigure(1, weight=1)

        tk.Label(
            topbar,
            text="⚔ MVP Timer",
            bg=C["bg"],
            fg=C["purple3"],
            font=("Segoe UI", 15, "bold"),
        ).grid(row=0, column=0, sticky="w")

        center = tk.Frame(topbar, bg=C["bg"])
        center.grid(row=0, column=1)
        self._mvp_filter_mode = tk.StringVar(value="todos")
        self._mvp_filter_btns = {}
        filt_specs = [
            ("Todos os MVPs", "todos"),
            ("Timers Ativos", "ativos"),
            ("Respawn pendente", "pendente"),
            ("MVPs disponíveis", "disponiveis"),
        ]
        for i, (label, val) in enumerate(filt_specs):

            def make_cmd(v=val):
                return lambda: self._mvp_set_filter(v)

            b = tk.Button(
                center,
                text=label,
                command=make_cmd(),
                relief="flat",
                cursor="hand2",
                font=("Segoe UI", 9, "bold"),
                padx=12,
                pady=6,
            )
            b.grid(row=0, column=i, padx=4)
            self._mvp_filter_btns[val] = b

        add_fr = tk.Frame(topbar, bg=C["bg"])
        add_fr.grid(row=0, column=2, sticky="e")
        self._mvp_catalog_hdr_status = tk.Label(add_fr, text="", bg=C["bg"], fg=C["text3"], font=("Segoe UI", 8))
        self._mvp_catalog_hdr_status.pack(side="right", padx=(8, 0))
        DarkButton(add_fr, text="Resetar todos os timers", style="ghost", command=self._mvp_reset_all_timers, padx=6).pack(
            side="left", padx=2
        )
        self._mvp_sync_filter_styles()

        tk.Label(
            self.mvp_timer_frame,
            text="Catálogo de MVPs com sprites quando disponíveis. Use «Registrar» para marcar a morte; o timer começa após «Salvar».",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=16, pady=(2, 6))

        search_fr = tk.Frame(self.mvp_timer_frame, bg=C["bg"])
        search_fr.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(
            search_fr,
            text="Buscar MVP (nome ou ID):",
            bg=C["bg"],
            fg=C["text2"],
            font=("Segoe UI", 10),
        ).pack(side="left")
        self._mvp_search_var = tk.StringVar(value="")
        self._mvp_search_var.trace_add("write", lambda *_a: self._mvp_on_search_change())
        tk.Entry(
            search_fr,
            textvariable=self._mvp_search_var,
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
        # Texto «Filtrando…» imediato na busca/filtros (ocultado ao terminar o render da grelha).
        self._mvp_search_filter_hint = tk.Label(
            search_fr,
            text="",
            bg=C["bg"],
            fg=C["text2"],
            font=("Segoe UI", 9, "italic"),
        )
        self._mvp_search_filter_hint.pack(side="left", padx=(4, 0))

        self._mvp_grid_progress_label = tk.Label(
            self.mvp_timer_frame,
            text="",
            bg=C["bg"],
            fg=C["text2"],
            font=("Segoe UI", 9),
        )

        self._mvp_scroll_outer = tk.Frame(self.mvp_timer_frame, bg=C["bg"])
        self._mvp_scroll_outer.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        scroll = ScrollableFrame(self._mvp_scroll_outer, inner_bg=C["bg"])
        scroll.pack(fill="both", expand=True)
        self._mvp_cards_scroll = scroll
        self.mvp_cards_host = scroll.inner

        self.mvp_catalog_host = None
        self._mvp_catalog_win = None
        self._MVP_GRID_COLS = 5
        self._mvp_cards_generation = 0
        self._mvp_grid_render_gen_done = None
        self._mvp_chunk_after_id = None
        self._mvp_grid_refresh_after_id = None
        self._mvp_last_render_sig = None
        # Contador lógico dos dados de timers (gravar/invalidar), mais estável que mtime em disco na assinatura de skip.
        self._mvp_timer_storage_rev = 0
        self._mvp_storage_tick_cache = None
        self._mvp_storage_tick_mtime = None
        self._mvp_filter_cache_key = None
        self._mvp_filter_cache_items = None
        self._mvp_catalog_cache_mtime = None
        self._mvp_sprite_bytes_lru = OrderedDict()
        self._mvp_image_loader = MvpImageLoader()
        self._mvp_sprite_poll_after = None
        self._mvp_card_refresh_job = None
        # Vigia global de spawn (som + pop-up) — corre sempre, em qualquer página.
        self._mvp_spawn_watch_job = None
    def _mvp_file_mtime(self, path: str):
        try:
            return os.path.getmtime(path)
        except OSError:
            return None

    def _mvp_render_signature(self):
        try:
            sq = str(self._mvp_search_var.get() or "").strip()
        except (tk.TclError, AttributeError):
            sq = ""
        try:
            mode = self._mvp_filter_mode.get()
        except tk.TclError:
            mode = "todos"
        try:
            st_m = os.path.getmtime(MVP_DATA_FILE) if os.path.isfile(MVP_DATA_FILE) else None
        except OSError:
            st_m = None
        return (
            self._mvp_file_mtime(MVP_CATALOG_PORTABLE_FILE),
            getattr(self, "_mvp_timer_storage_rev", 0),
            st_m,
            mode,
            sq,
            len(self._mvp_catalog_items or []),
            bool(self._mvp_catalog_fetching),
        )

    def _mvp_should_skip_grid_redraw(self) -> bool:
        if self._mvp_catalog_fetching:
            return False
        if not (self._mvp_catalog_items or []):
            return False
        if getattr(self, "_mvp_grid_render_gen_done", None) != getattr(self, "_mvp_cards_generation", -1):
            return False
        sig = self._mvp_render_signature()
        if sig != getattr(self, "_mvp_last_render_sig", None):
            return False
        host = self.mvp_cards_host
        try:
            if not host.winfo_children():
                return False
        except tk.TclError:
            return False
        return True

    def _mvp_cancel_chunked_render(self):
        aid = getattr(self, "_mvp_chunk_after_id", None)
        if aid is not None:
            try:
                self.after_cancel(aid)
            except (tk.TclError, ValueError):
                pass
            self._mvp_chunk_after_id = None

    def _mvp_cancel_deferred_grid_refresh(self):
        aid = getattr(self, "_mvp_grid_refresh_after_id", None)
        if aid is not None:
            try:
                self.after_cancel(aid)
            except (tk.TclError, ValueError):
                pass
            self._mvp_grid_refresh_after_id = None

    def _mvp_queue_mvp_grid_refresh(self, delay_ms: int = 320):
        """Um único redesenho após enriquecimento API — evita múltiplos «flashes» seguidos."""

        def run():
            self._mvp_grid_refresh_after_id = None
            if self.current_page.get() != "mvp":
                return
            self._mvp_render_mvp_cards()

        self._mvp_cancel_deferred_grid_refresh()
        self._mvp_grid_refresh_after_id = self.after(delay_ms, run)

    def _mvp_storage_for_tick(self):
        """Evita reler JSON em disco a cada segundo se o ficheiro não mudou."""
        try:
            mtime = os.path.getmtime(MVP_DATA_FILE) if os.path.isfile(MVP_DATA_FILE) else None
        except OSError:
            mtime = None
        if mtime == self._mvp_storage_tick_mtime and self._mvp_storage_tick_cache is not None:
            return self._mvp_storage_tick_cache
        self._mvp_storage_tick_cache = load_mvp_storage()
        self._mvp_storage_tick_mtime = mtime
        return self._mvp_storage_tick_cache

    def _mvp_timers_data(self):
        """Snapshot dos timers MVP (mesmo cache que o tick — invalida após gravar)."""
        return self._mvp_storage_for_tick()

    def _mvp_invalidate_filter_cache(self) -> None:
        """Invalida o cache da lista filtrada (busca + modo); chamado quando timers ou catálogo mudam."""
        self._mvp_filter_cache_key = None
        self._mvp_filter_cache_items = None

    def _mvp_invalidate_timer_storage_cache(self):
        self._mvp_storage_tick_cache = None
        self._mvp_storage_tick_mtime = None
        try:
            self._mvp_timer_storage_rev = int(getattr(self, "_mvp_timer_storage_rev", 0)) + 1
        except (TypeError, ValueError):
            self._mvp_timer_storage_rev = 1
        self._mvp_invalidate_filter_cache()

    def _mvp_filter_cache_key_tuple(self) -> tuple:
        """Chave do cache de filtro: UI + revisão de storage + meta do catálogo em disco."""
        try:
            sq = str(self._mvp_search_var.get() or "").strip()
        except (tk.TclError, AttributeError):
            sq = ""
        try:
            mode = self._mvp_filter_mode.get()
        except tk.TclError:
            mode = "todos"
        rev = getattr(self, "_mvp_timer_storage_rev", 0)
        try:
            st_m = os.path.getmtime(MVP_DATA_FILE) if os.path.isfile(MVP_DATA_FILE) else None
        except OSError:
            st_m = None
        cat_m = self._mvp_file_mtime(MVP_CATALOG_PORTABLE_FILE)
        n = len(self._mvp_catalog_items or [])
        fetching = bool(getattr(self, "_mvp_catalog_fetching", False))
        return (sq, mode, rev, st_m, cat_m, n, fetching)

    def _mvp_cancel_card_refresh_chunk(self):
        jid = getattr(self, "_mvp_card_refresh_job", None)
        if jid is not None:
            try:
                self.after_cancel(jid)
            except (tk.TclError, ValueError):
                pass
            self._mvp_card_refresh_job = None

    def _mvp_display_name_for_mid(self, mid: int, fallback: str = "") -> str:
        for it in self._mvp_catalog_items or []:
            try:
                if int(it.get("id") or 0) == int(mid):
                    n = str(it.get("name") or "").strip()
                    if n:
                        return n
            except (TypeError, ValueError):
                continue
        return (fallback or "").strip() or "MVP"

    def _mvp_startup_warm(self):
        """Carrega o catálogo MVP em memória a partir do cache (sem sprites em rede)."""
        try:
            cached = load_mvp_catalog_cache()
            if cached:
                self._mvp_catalog_items = list(cached)
            self._mvp_catalog_cache_mtime = self._mvp_file_mtime(MVP_CATALOG_PORTABLE_FILE)
        except Exception as ex:
            logger.debug("MVP warm-up catálogo: %s", ex)
        try:
            self._mvp_storage_for_tick()
        except Exception as ex:
            logger.debug("MVP warm-up timers: %s", ex)

    def _mvp_show_filter_busy(self) -> None:
        """Feedback imediato antes do debounce / render (Tk pinta o botão primeiro)."""
        lbl = getattr(self, "_mvp_search_filter_hint", None)
        if lbl is not None:
            try:
                lbl.configure(text="Filtrando…")
            except tk.TclError:
                pass

    def _mvp_clear_filter_busy(self) -> None:
        lbl = getattr(self, "_mvp_search_filter_hint", None)
        if lbl is not None:
            try:
                lbl.configure(text="")
            except tk.TclError:
                pass

    def _mvp_scroll_grid_to_top(self) -> None:
        """Grelha MVP: scroll ao topo (filtros, reset, fim do render)."""
        sf = getattr(self, "_mvp_cards_scroll", None)
        if sf is None:
            return
        canvas = getattr(sf, "_canvas", None)
        if canvas is None:
            return
        try:
            canvas.yview_moveto(0)
        except tk.TclError:
            pass

    def _mvp_set_filter(self, value: str):
        self._mvp_filter_mode.set(value)
        self._mvp_sync_filter_styles()
        self._mvp_scroll_grid_to_top()
        self.after(0, self._mvp_show_filter_busy)
        # Deixa o estilo dos botões atualizar antes do trabalho pesado da grelha.
        self.after(0, lambda: self._mvp_render_mvp_cards())

    def _mvp_sync_filter_styles(self):
        cur = self._mvp_filter_mode.get()
        for val, b in getattr(self, "_mvp_filter_btns", {}).items():
            try:
                if val == cur:
                    b.configure(
                        bg=C["purple"],
                        fg="#ffffff",
                        activebackground=C["accent"],
                        activeforeground="#ffffff",
                    )
                else:
                    b.configure(
                        bg=C["bg3"],
                        fg=C["text"],
                        activebackground=C["border"],
                        activeforeground=C["text"],
                    )
            except tk.TclError:
                pass

    def _mvp_on_search_change(self):
        """Debounce do filtro: menos renders durante a digitação (300 ms)."""
        aid = getattr(self, "_mvp_search_after_id", None)
        if aid is not None:
            try:
                self.after_cancel(aid)
            except (tk.TclError, ValueError):
                pass
        self.after(0, self._mvp_show_filter_busy)
        self._mvp_search_after_id = self.after(300, self._mvp_apply_search_filter)

    def _mvp_apply_search_filter(self):
        self._mvp_search_after_id = None
        try:
            self._mvp_render_mvp_cards()
        except tk.TclError:
            pass

    def _mvp_catalog_base_count(self) -> int:
        """MVPs no catálogo em disco (exclui nomes de instância)."""
        n = 0
        for it in self._mvp_catalog_items or []:
            if not isinstance(it, dict):
                continue
            if mvp_catalog_entry_skipped(it):
                continue
            try:
                if int(it.get("id") or 0):
                    n += 1
            except (TypeError, ValueError):
                pass
        return n

    def _mvp_filtered_catalog_items(self, data=None) -> list:
        use_cache = data is None
        cache_key = None
        if use_cache:
            cache_key = self._mvp_filter_cache_key_tuple()
            if cache_key == getattr(self, "_mvp_filter_cache_key", None) and getattr(
                self, "_mvp_filter_cache_items", None
            ) is not None:
                return list(self._mvp_filter_cache_items)

        cat = list(self._mvp_catalog_items or [])
        if data is None:
            data = self._mvp_timers_data()
        by_mid: dict = {}
        for e in data.get("entries") or []:
            mid = int(e.get("monster_id") or 0)
            if mid and mid not in by_mid:
                by_mid[mid] = e
        cat_base = []
        for it in cat:
            if not isinstance(it, dict):
                continue
            try:
                mid = int(it.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if not mid:
                continue
            if mvp_catalog_entry_skipped(it):
                continue
            cat_base.append(it)
        cat = cat_base

        try:
            q = str(self._mvp_search_var.get() or "") if getattr(self, "_mvp_search_var", None) else ""
        except (tk.TclError, AttributeError):
            q = ""
        if q.strip():
            cat = [it for it in cat if mvp_catalog_matches_search(it, q)]

        mode = self._mvp_filter_mode.get()
        if mode == "todos":
            result = cat
        else:
            out = []
            for it in cat:
                mid = int(it["id"])
                ent = by_mid.get(mid)
                if mode == "ativos" and ent:
                    su = seconds_until_spawn(ent)
                    if su is not None:
                        out.append(it)
                elif mode == "pendente" and ent:
                    su = seconds_until_spawn(ent)
                    if su is not None and su > 0:
                        out.append(it)
                elif mode == "disponiveis":
                    if ent:
                        su = seconds_until_spawn(ent)
                        if su is not None and su < 0:
                            out.append(it)
            result = out

        if use_cache and cache_key is not None:
            self._mvp_filter_cache_key = cache_key
            self._mvp_filter_cache_items = result
        return result

    def _mvp_filtered_ordered_ids(self, data=None) -> list:
        return [int(x["id"]) for x in self._mvp_filtered_catalog_items(data)]

    def _mvp_clock_label_fg(self, ent, su) -> str:
        """Verde: ainda falta para o respawn; vermelho: tempo esgotado (contagem negativa). Neutro: sem dados."""
        if su is None:
            return C["text3"]
        if su > 0:
            return C["green"]
        return C["red"]

    def _mvp_sprite_lru_get(self, mid: int) -> Optional[bytes]:
        """LRU só na main thread: devolve bytes PNG em cache ou None."""
        od = self._mvp_sprite_bytes_lru
        mid = int(mid)
        if mid not in od:
            return None
        od.move_to_end(mid)
        return od[mid]

    def _mvp_sprite_lru_set(self, mid: int, blob: bytes) -> None:
        """Grava miniatura no LRU (máx. 150 entradas)."""
        od = self._mvp_sprite_bytes_lru
        mid = int(mid)
        if mid in od:
            del od[mid]
        od[mid] = blob
        od.move_to_end(mid)
        while len(od) > 150:
            od.popitem(last=False)

    def _mvp_cancel_sprite_poll(self) -> None:
        aid = getattr(self, "_mvp_sprite_poll_after", None)
        if aid is not None:
            try:
                self.after_cancel(aid)
            except (tk.TclError, ValueError):
                pass
            self._mvp_sprite_poll_after = None

    def _mvp_schedule_sprite_poll(self) -> None:
        """Garante um loop de polling de resultados do worker (main thread)."""
        if getattr(self, "_mvp_sprite_poll_after", None) is not None:
            return
        self._mvp_sprite_poll_after = self.after(0, self._mvp_poll_sprite_loop)

    def _mvp_poll_sprite_loop(self) -> None:
        self._mvp_sprite_poll_after = None
        if self.current_page.get() != "mvp":
            return
        drained = 0
        while True:
            r = self._mvp_image_loader.try_get_result()
            if r is None:
                break
            drained += 1
            self._mvp_apply_sprite_from_worker(*r)
        if drained > 0 or self._mvp_image_loader.has_backlog():
            self._mvp_sprite_poll_after = self.after(16, self._mvp_poll_sprite_loop)

    def _mvp_apply_sprite_from_worker(self, gen: int, mid: int, blob: Optional[bytes]) -> None:
        """Aplica PNG recebido do worker; ignora gerações antigas da grelha."""
        if gen != self._mvp_cards_generation:
            return
        if blob:
            self._mvp_sprite_lru_set(mid, blob)
        w = self._mvp_card_labels.get(str(int(mid)))
        if not w:
            return
        host = w.get("sprite_host")
        if not host:
            return
        card_bg = C["card"]
        try:
            for ch in host.winfo_children():
                ch.destroy()
        except tk.TclError:
            return
        if blob:
            try:
                from io import BytesIO

                from PIL import Image, ImageTk

                im = Image.open(BytesIO(blob)).convert("RGBA")
                ph = ImageTk.PhotoImage(im, master=self)
                self._mvp_photo_refs.append(ph)
                tk.Label(host, image=ph, bg=card_bg, bd=0, highlightthickness=0).place(
                    relx=0.5, rely=0.5, anchor="center"
                )
            except Exception:
                tk.Label(host, text="—", fg=C["text3"], bg=card_bg, font=("Segoe UI", 11)).place(
                    relx=0.5, rely=0.5, anchor="center"
                )
        else:
            tk.Label(host, text="—", fg=C["text3"], bg=card_bg, font=("Segoe UI", 11)).place(
                relx=0.5, rely=0.5, anchor="center"
            )

    def _mvp_fill_card_inner(self, inner, cit: dict, ent, mid: int) -> None:
        """Conteúdo visual de um card (sprite, textos, timer, botão)."""
        card_bg = C["card"]
        card_bd = C["border"]
        title_fg = C["purple3"]
        st_fg = C["purple2"]
        box_bg = C["bg3"]
        mid = int(mid)
        name = str(cit.get("name") or "—")

        cv_sz = 76
        sprite_host = tk.Frame(
            inner,
            width=cv_sz,
            height=cv_sz,
            bg=card_bg,
            highlightbackground=card_bd,
            highlightthickness=1,
        )
        sprite_host.pack_propagate(False)
        sprite_host.pack(pady=(0, 4))
        gen = int(getattr(self, "_mvp_cards_generation", 0))
        ph = None
        cached_blob = self._mvp_sprite_lru_get(mid)
        if cached_blob:
            try:
                from io import BytesIO

                from PIL import Image, ImageTk

                im = Image.open(BytesIO(cached_blob)).convert("RGBA")
                ph = ImageTk.PhotoImage(im, master=self)
                self._mvp_photo_refs.append(ph)
            except Exception:
                ph = None
        if ph is not None:
            tk.Label(sprite_host, image=ph, bg=card_bg, bd=0, highlightthickness=0).place(
                relx=0.5, rely=0.5, anchor="center"
            )
        else:
            tk.Label(
                sprite_host,
                text="…",
                fg=C["text3"],
                bg=card_bg,
                font=("Segoe UI", 16),
            ).place(relx=0.5, rely=0.5, anchor="center")
            self._mvp_image_loader.enqueue(gen, mid, name)
            self._mvp_schedule_sprite_poll()

        name_fr = tk.Frame(inner, bg=card_bg)
        name_fr.pack(fill=tk.X)
        name_w = tk.Text(
            name_fr,
            wrap=tk.WORD,
            width=24,
            height=1,
            font=("Segoe UI", 10, "bold"),
            bg=card_bg,
            fg=title_fg,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=0,
            pady=0,
            cursor="ibeam",
            insertofftime=0,
            insertontime=0,
            takefocus=1,
            undo=False,
        )
        name_w.tag_configure("center", justify="center")
        name_w.insert("1.0", name)
        name_w.tag_add("center", "1.0", "end")
        lc = int(str(name_w.index("end-1c")).split(".")[0])
        name_w.configure(height=max(1, lc))

        def _mvp_copyable_text_key(e):
            if e.keysym in (
                "Left",
                "Right",
                "Up",
                "Down",
                "Home",
                "End",
                "Next",
                "Prior",
                "Tab",
                "Shift_L",
                "Shift_R",
                "Control_L",
                "Control_R",
                "Alt_L",
                "Alt_R",
            ):
                return
            if (e.state & 4) and e.keysym.lower() in ("c", "a", "insert"):
                return
            return "break"

        name_w.bind("<Key>", _mvp_copyable_text_key)
        name_w.bind("<<Paste>>", lambda _e: "break")
        name_w.bind("<<Cut>>", lambda _e: "break")
        name_w.pack(anchor=tk.CENTER)

        id_fr = tk.Frame(inner, bg=card_bg)
        id_fr.pack(fill=tk.X)
        id_row = tk.Entry(
            id_fr,
            font=("Segoe UI", 8),
            fg=C["text3"],
            bg=card_bg,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            justify="center",
            insertbackground=card_bg,
            insertofftime=0,
            insertontime=0,
            cursor="ibeam",
            takefocus=1,
        )
        try:
            id_row.configure(readonlybackground=card_bg)
        except tk.TclError:
            pass
        id_row.insert(0, f"ID {mid}")
        id_row.configure(state="readonly")
        id_row.pack(anchor=tk.CENTER)

        if ent:
            dm = str(ent.get("death_map") or "").strip()
            maps_txt = dm if dm else "—"
        else:
            maps_txt = "—"
        tk.Label(
            inner,
            text=maps_txt,
            bg=card_bg,
            fg=C["text2"],
            font=("Segoe UI", 8),
            wraplength=178,
            justify="center",
        ).pack(pady=(6, 2))

        if ent and ent.get("death_x") is not None and ent.get("death_y") is not None:
            loc = f"{ent['death_x']}, {ent['death_y']}"
        else:
            loc = "—"
        tk.Label(
            inner,
            text=f"Coords  {loc}",
            bg=card_bg,
            fg=C["text3"],
            font=("Segoe UI", 8),
        ).pack()

        box = tk.Frame(inner, bg=box_bg, highlightbackground=card_bd, highlightthickness=1)
        box.pack(fill="x", pady=(10, 0), ipady=6, ipadx=4)

        st_txt = mvp_dashboard_status_text(ent)
        lbl_st = tk.Label(
            box,
            text=st_txt,
            bg=box_bg,
            fg=st_fg,
            font=("Segoe UI", 9, "bold"),
        )
        lbl_st.pack()

        su = seconds_until_spawn(ent) if ent else None
        clk_fg = self._mvp_clock_label_fg(ent, su)
        lbl_ck = tk.Label(
            box,
            text=format_countdown_clock(su),
            bg=box_bg,
            fg=clk_fg,
            font=("Consolas", 15, "bold"),
        )
        lbl_ck.pack()

        self._mvp_card_labels[str(mid)] = {
            "lbl_clock": lbl_ck,
            "lbl_status": lbl_st,
            "entry": ent,
            "inner": inner,
            "sprite_host": sprite_host,
        }

        def reg_btn():
            return tk.Button(
                inner,
                relief="flat",
                bg=C["purple"],
                fg="#ffffff",
                activebackground=C["accent"],
                activeforeground="#ffffff",
                font=("Segoe UI", 9, "bold"),
                cursor="hand2",
                padx=4,
                pady=8,
            )

        if ent:
            b = reg_btn()
            b.configure(text="⏱  Editar timer", command=lambda eid=ent["entry_id"]: self._mvp_open_edit_dialog(eid))
        else:
            b = reg_btn()
            b.configure(text="⏱  Registrar", command=lambda m=mid: self._mvp_add_monster_by_catalog_id(m))
        b.pack(fill="x", pady=(12, 0))

    def _mvp_refresh_card_for_monster(self, mid: int) -> None:
        mid = int(mid)
        w = self._mvp_card_labels.get(str(mid))
        inner = w.get("inner") if w else None
        try:
            if inner is None or not inner.winfo_exists():
                self._mvp_render_mvp_cards()
                return
        except tk.TclError:
            self._mvp_render_mvp_cards()
            return
        cit = next((x for x in (self._mvp_catalog_items or []) if int(x.get("id") or 0) == mid), None)
        if cit is None:
            self._mvp_render_mvp_cards()
            return
        data = self._mvp_timers_data()
        by_mid = {}
        for e in data.get("entries") or []:
            m = int(e.get("monster_id") or 0)
            if m and m not in by_mid:
                by_mid[m] = e
        ent = by_mid.get(mid)
        for ch in inner.winfo_children():
            ch.destroy()
        self._mvp_fill_card_inner(inner, cit, ent, mid)

    def _mvp_storage_change_refresh(self, affected_mid: int, before_ids: list) -> None:
        """Actualiza só o card se a lista filtrada (ordem e tamanho) não mudou; senão redesenha a grelha."""
        am = int(affected_mid)
        after_ids = self._mvp_filtered_ordered_ids()
        if before_ids == after_ids and str(am) in self._mvp_card_labels:
            self._mvp_refresh_card_for_monster(am)
        else:
            self._mvp_render_mvp_cards()

    def _mvp_set_catalog_status(self, text: str):
        lbl = getattr(self, "_mvp_catalog_hdr_status", None)
        if lbl is not None:
            try:
                lbl.configure(text=text)
            except tk.TclError:
                pass

    def _mvp_refresh_catalog_header_counts(self):
        """Canto superior direito: quantos MVPs estão visíveis com filtro + busca."""
        if self._mvp_catalog_fetching:
            return
        shown = len(self._mvp_filtered_catalog_items())
        total = self._mvp_catalog_base_count()
        self._mvp_set_catalog_status(f"Mostrando {shown} de {total} MVPs")

    def _show_mvp_timer(self):
        self._clear_main()
        self.mvp_timer_frame.pack(fill="both", expand=True)
        self.after_idle(self._mvp_show_mvp_timer_finish)

    def _mvp_show_mvp_timer_finish(self):
        if self.current_page.get() != "mvp":
            return
        self._mvp_ensure_catalog()
        self._mvp_schedule_tick()

    def _mvp_ensure_catalog(self):
        cm = self._mvp_file_mtime(MVP_CATALOG_PORTABLE_FILE)
        if cm != getattr(self, "_mvp_catalog_cache_mtime", None) or not (self._mvp_catalog_items or []):
            cached = load_mvp_catalog_cache()
            self._mvp_catalog_items = list(cached) if cached else []
            self._mvp_catalog_cache_mtime = cm
            # Catálogo novo: lista filtrada em cache já não corresponde à memória.
            self._mvp_invalidate_filter_cache()
        if self._mvp_catalog_items:
            if self._mvp_should_skip_grid_redraw():
                self._mvp_refresh_catalog_header_counts()
            else:
                self._mvp_render_mvp_cards()
            names_en = mvp_catalog_names_are_english_marked()
            need_sync = not names_en
            if need_sync and not (load_settings().get("divine_pride_api_key") or "").strip():
                self._mvp_set_catalog_status(
                    "Catálogo carregado. Configure a chave Divine Pride (Configurações) para obter nomes dos MVPs em inglês via API."
                )
            self._mvp_start_spawn_enrich(sync_all_names=need_sync)
            return
        self._mvp_render_mvp_cards()
        self._mvp_start_catalog_fetch(force=False)

    def _mvp_refresh_catalog(self):
        self._mvp_start_catalog_fetch(force=True)

    def _mvp_start_catalog_fetch(self, *, force: bool):
        if self._mvp_catalog_fetching:
            return
        self._mvp_set_catalog_status("A sincronizar lista MVP (Divine Pride)…")
        self._mvp_catalog_fetching = True
        self._mvp_render_mvp_cards()

        def work():
            err = None
            items = None
            try:
                cfg = load_settings()
                srv = (cfg.get("divine_pride_server") or "").strip() or None
                sess = requests.Session()
                sess.headers.update(DIVINE_PRIDE_LIST_HEADERS)
                items = fetch_mvp_catalog_from_divine_pride(sess, list_server=srv)
                old_by = {int(x["id"]): x for x in (self._mvp_catalog_items or [])}
                for it in items:
                    mid = int(it["id"])
                    if mid in old_by and old_by[mid].get("spawn_maps"):
                        it["spawn_maps"] = list(old_by[mid]["spawn_maps"])
                save_mvp_catalog_cache(items, name_display_locale="pending")
            except Exception as ex:
                err = str(ex)
            self.after(0, lambda e=err, it=items: self._mvp_catalog_fetch_done(e, it))

        threading.Thread(target=work, daemon=True).start()

    def _mvp_catalog_fetch_done(self, err, items):
        self._mvp_catalog_fetching = False
        if err or not items:
            msg = err or "Lista vazia"
            logger.warning("Catálogo MVP: %s", msg)
            self._mvp_set_catalog_status(f"Erro: {msg[:80]}")
            self._mvp_render_mvp_cards(update_hdr_counts=False)
            return
        self._mvp_catalog_items = list(items)
        self._mvp_catalog_cache_mtime = self._mvp_file_mtime(MVP_CATALOG_PORTABLE_FILE)
        self._mvp_invalidate_filter_cache()
        self._mvp_render_mvp_cards()
        self._mvp_start_spawn_enrich(sync_all_names=True)

    def _mvp_start_spawn_enrich(self, *, sync_all_names: bool = False):
        """Enriquece via API (nomes em inglês, Accept-Language na API). *sync_all_names*: todos os MVPs."""
        if getattr(self, "_mvp_spawn_enriching", False):
            return
        if not self._mvp_catalog_items:
            return
        cfg = load_settings()
        key = (cfg.get("divine_pride_api_key") or "").strip()
        dp_srv = (cfg.get("divine_pride_server") or "").strip() or None
        if not key:
            return

        def _has_sm(it: dict) -> bool:
            sm = it.get("spawn_maps") if isinstance(it.get("spawn_maps"), list) else []
            return any(str(x).strip() for x in sm)

        if not sync_all_names:
            if not any(not _has_sm(it) for it in self._mvp_catalog_items):
                return
        self._mvp_spawn_enriching = True

        def work():
            api_hits = 0
            catalog_changed = False
            st_changed = False
            try:
                for it in list(self._mvp_catalog_items or []):
                    if not isinstance(it, dict):
                        continue
                    if mvp_catalog_entry_skipped(it):
                        continue
                    try:
                        mid = int(it.get("id") or 0)
                    except (TypeError, ValueError):
                        continue
                    if not mid:
                        continue
                    has_maps = _has_sm(it)
                    if not sync_all_names and has_maps:
                        continue
                    try:
                        mobj = fetch_monster(mid, api_key=key, server=dp_srv)
                        api_hits += 1
                        nn = monster_api_display_name(mobj)
                        if nn:
                            old_n = str(it.get("name") or "").strip()
                            if old_n != nn:
                                it["name"] = nn
                                catalog_changed = True
                        if not has_maps:
                            new_maps = spawn_maps_from_monster(mobj)
                            # Só persiste/redesenha quando a API devolve mapas reais;
                            # MVPs sem mapa (ex. Beelzebub, Em Angeling/Deviling) não
                            # devem regravar o cache nem disparar refresh a cada abertura.
                            if new_maps:
                                it["spawn_maps"] = new_maps
                                catalog_changed = True
                    except Exception as ex:
                        logger.debug("enrich MVP %s: %s", mid, ex)
                    time.sleep(0.12)
                try:
                    st_data = load_mvp_storage()
                    by_mid_e = {
                        int(e.get("monster_id") or 0): e
                        for e in st_data.get("entries") or []
                        if int(e.get("monster_id") or 0)
                    }
                    for cit in self._mvp_catalog_items or []:
                        if not isinstance(cit, dict):
                            continue
                        try:
                            mid_k = int(cit.get("id") or 0)
                        except (TypeError, ValueError):
                            continue
                        if not mid_k or mid_k not in by_mid_e:
                            continue
                        cn = str(cit.get("name") or "").strip()
                        if cn and by_mid_e[mid_k].get("name") != cn:
                            by_mid_e[mid_k]["name"] = cn
                            st_changed = True
                    if st_changed:
                        save_mvp_storage(st_data)
                        self._mvp_invalidate_timer_storage_cache()
                except Exception as ex:
                    logger.debug("sync timer entry names from catalog: %s", ex)
                try:
                    if catalog_changed or st_changed or sync_all_names:
                        loc = None
                        if sync_all_names:
                            loc = "en" if api_hits > 0 else "pending"
                        save_mvp_catalog_cache(self._mvp_catalog_items, name_display_locale=loc)
                except Exception as ex:
                    logger.warning("save_mvp_catalog_cache after enrich: %s", ex)
            finally:
                self._mvp_spawn_enriching = False
                # Só agenda redesenho se dados visíveis mudaram — evita grelha completa ao reabrir a aba sem alterações.
                if catalog_changed or st_changed:
                    if catalog_changed:
                        self._mvp_invalidate_filter_cache()
                    self.after(0, lambda: self._mvp_queue_mvp_grid_refresh())

        threading.Thread(target=work, daemon=True).start()

    def _mvp_add_monster_by_catalog_id(self, mid: int):
        cfg = load_settings()
        dp_srv = (cfg.get("divine_pride_server") or "").strip() or None
        if not (cfg.get("divine_pride_api_key") or "").strip():
            messagebox.showerror(
                "MVP",
                "Configure a chave Divine Pride em Configurações (ou variável DIVINE_PRIDE_API_KEY).",
                parent=self,
            )
            return
        data = self._mvp_timers_data()
        if any(int(e.get("monster_id") or 0) == int(mid) for e in data.get("entries") or []):
            messagebox.showinfo("MVP", "Este MVP já está na lista de timers.", parent=self)
            return

        def work():
            err = None
            mobj = None
            try:
                mobj = fetch_monster(
                    mid,
                    api_key=cfg.get("divine_pride_api_key"),
                    server=dp_srv,
                )
            except Exception as ex:
                err = str(ex)
            self.after(0, lambda: self._mvp_add_monster_done(err, mobj))

        threading.Thread(target=work, daemon=True).start()

    def _mvp_schedule_tick(self):
        if self._mvp_timer_tick_job is not None:
            try:
                self.after_cancel(self._mvp_timer_tick_job)
            except tk.TclError:
                pass
            self._mvp_timer_tick_job = None
        self._mvp_timer_tick()

    def _mvp_timer_tick(self):
        """Atualiza os relógios dos cards — só enquanto a aba MVP está visível."""
        self._mvp_timer_tick_job = None
        try:
            if self.current_page.get() != "mvp":
                return
            self._mvp_update_countdown_labels()
        except Exception:
            logger.exception("mvp_timer_tick")
        self._mvp_timer_tick_job = self.after(1000, self._mvp_timer_tick)

    def _mvp_start_spawn_alert_watch(self):
        """Inicia (uma vez) a vigia global de spawn: som + pop-up em qualquer página."""
        if getattr(self, "_mvp_spawn_watch_job", None) is not None:
            return
        self._mvp_spawn_alert_watch_tick()

    def _mvp_spawn_alert_watch_tick(self):
        """Verifica spawns a cada segundo enquanto o programa estiver aberto."""
        self._mvp_spawn_watch_job = None
        try:
            self._mvp_check_spawn_alerts()
        except Exception:
            logger.exception("mvp_spawn_alert_watch_tick")
        try:
            self._mvp_spawn_watch_job = self.after(1000, self._mvp_spawn_alert_watch_tick)
        except tk.TclError:
            self._mvp_spawn_watch_job = None

    def _mvp_update_countdown_labels(self):
        data = self._mvp_storage_for_tick()
        by_mid = {}
        for e in data.get("entries") or []:
            mid = int(e.get("monster_id") or 0)
            if mid and mid not in by_mid:
                by_mid[mid] = e
        for mid_str, w in list(self._mvp_card_labels.items()):
            try:
                mid = int(mid_str)
            except (TypeError, ValueError):
                continue
            ent = by_mid.get(mid)
            try:
                if "lbl_clock" in w:
                    su = seconds_until_spawn(ent) if ent else None
                    w["lbl_clock"].configure(
                        text=format_countdown_clock(su), fg=self._mvp_clock_label_fg(ent, su)
                    )
                if "lbl_status" in w:
                    w["lbl_status"].configure(text=mvp_dashboard_status_text(ent))
            except tk.TclError:
                pass

    def _mvp_check_spawn_alerts(self):
        data = self._mvp_timers_data()
        changed = False
        for e in data.get("entries") or []:
            if e.get("alert_fired"):
                continue
            su = seconds_until_spawn(e)
            if su is None:
                continue
            if su > 0:
                continue
            e["alert_fired"] = True
            changed = True
            name = e.get("name") or "MVP"
            # Som primeiro; o pop-up é não-modal e não bloqueia a aplicação.
            try:
                snd = str(load_settings().get("mvp_alert_sound_path") or "").strip()
                play_mvp_spawn_alert_sound(snd or None)
            except Exception:
                logger.debug("mvp spawn alert sound", exc_info=True)
            self._mvp_show_spawn_popup(name, e)
        if changed:
            save_mvp_storage(data)
            self._mvp_invalidate_timer_storage_cache()

    def _mvp_show_spawn_popup(self, name, entry):
        """Pop-up de spawn não-modal (não congela a app; vários alertas em cascata)."""
        try:
            top = tk.Toplevel(self)
        except tk.TclError:
            return
        top.title("MVP — respawn")
        top.configure(bg=C["bg"])
        top.resizable(False, False)
        try:
            top.transient(self)
        except tk.TclError:
            pass

        maps = entry.get("spawn_maps") if isinstance(entry, dict) else None
        death_map = (entry.get("death_map") if isinstance(entry, dict) else "") or ""
        map_txt = death_map or (", ".join(m for m in (maps or []) if m) if maps else "")

        outer = tk.Frame(top, bg=C["border"], padx=1, pady=1)
        outer.pack(fill="both", expand=True)
        card = tk.Frame(outer, bg=C["card"], padx=16, pady=14)
        card.pack(fill="both", expand=True)

        tk.Label(
            card,
            text="MVP — RESPAWN",
            bg=C["card"],
            fg=C["text3"],
            font=("Segoe UI", 8, "bold"),
        ).pack(anchor="w")

        tk.Label(
            card,
            text=name or "MVP",
            bg=C["card"],
            fg=C["purple3"],
            font=("Segoe UI", 14, "bold"),
            anchor="w",
            justify="left",
            wraplength=320,
        ).pack(anchor="w", pady=(6, 0))

        if map_txt:
            tk.Label(
                card,
                text=f"Mapa: {map_txt}",
                bg=C["card"],
                fg=C["text2"],
                font=("Segoe UI", 10),
                anchor="w",
                justify="left",
                wraplength=320,
            ).pack(anchor="w", pady=(2, 0))

        spawn_wrap = tk.Frame(card, bg=C["bg3"], padx=12, pady=8)
        spawn_wrap.pack(fill="x", pady=(12, 0))
        tk.Label(
            spawn_wrap,
            text="NASCEU!",
            bg=C["bg3"],
            fg=C["green"],
            font=("Segoe UI", 18, "bold"),
            anchor="w",
        ).pack(anchor="w")

        tk.Label(
            card,
            text="O tempo de contagem terminou. Verifique in-game e, após matar o MVP, "
            "registe a morte no card «Editar».",
            bg=C["card"],
            fg=C["text2"],
            font=("Segoe UI", 10),
            anchor="w",
            justify="left",
            wraplength=340,
        ).pack(anchor="w", pady=(10, 0))

        DarkButton(card, text="Fechar", command=top.destroy, style="ghost").pack(
            anchor="e", pady=(14, 0)
        )

        top.bind("<Escape>", lambda _e: top.destroy())
        top.bind("<Return>", lambda _e: top.destroy())

        place = getattr(self, "_place_alert_popup", None)
        if callable(place):
            place(top)
        try:
            top.attributes("-topmost", True)
        except tk.TclError:
            pass

    def _mvp_add_monster_done(self, err, mobj):
        if err:
            messagebox.showerror("MVP", f"Erro ao carregar monstro:\n{err}", parent=self)
            return
        summ = summarize_monster_for_timer(mobj)
        data = self._mvp_timers_data()
        if any(int(e.get("monster_id") or 0) == int(summ["monster_id"]) for e in data.get("entries") or []):
            messagebox.showinfo("MVP", "Este MVP já está na lista de timers.", parent=self)
            return
        if not summ["is_mvp"]:
            if not messagebox.askyesno(
                "MVP",
                "Na Divine Pride este monstro não está marcado como MVP. Adicionar à mesma?",
                parent=self,
            ):
                return
        before_ids = self._mvp_filtered_ordered_ids(data)
        maps = summ["spawn_maps"]
        dm = maps[0] if maps else ""
        entry = new_timer_entry(
            summ["monster_id"],
            summ["name"],
            maps,
            summ["respawn_seconds"],
            death_map=dm,
            death_at_iso="",
        )
        data.setdefault("entries", []).append(entry)
        eid_new = entry["entry_id"]
        save_mvp_storage(data)
        self._mvp_invalidate_timer_storage_cache()
        for it in self._mvp_catalog_items or []:
            if int(it.get("id") or 0) == int(summ["monster_id"]):
                if summ.get("spawn_maps"):
                    it["spawn_maps"] = list(summ["spawn_maps"])
                break
        if self._mvp_catalog_items:
            try:
                save_mvp_catalog_cache(self._mvp_catalog_items)
                self._mvp_catalog_cache_mtime = self._mvp_file_mtime(MVP_CATALOG_PORTABLE_FILE)
            except Exception:
                pass
        self._mvp_storage_change_refresh(int(summ["monster_id"]), before_ids)
        self.after(100, lambda eid=eid_new: self._mvp_open_edit_dialog(eid))

    def _mvp_refresh_visible_cards_batched(self, mids: list, idx: int = 0, batch: int = 14) -> None:
        """Reconstrói cartões visíveis em fatias — UI não bloqueia em resets grandes."""
        self._mvp_card_refresh_job = None
        if self.current_page.get() != "mvp":
            return
        n = len(mids)
        end = min(idx + max(1, int(batch)), n)
        for i in range(idx, end):
            try:
                self._mvp_refresh_card_for_monster(int(mids[i]))
            except Exception:
                logger.debug("mvp_refresh_visible_cards_batched", exc_info=True)
        if end < n:
            self._mvp_card_refresh_job = self.after(
                1, lambda: self._mvp_refresh_visible_cards_batched(mids, end, batch)
            )
        else:
            self._mvp_refresh_catalog_header_counts()

    def _mvp_refresh_all_visible_cards_batched(self, batch: int = 14) -> None:
        self._mvp_cancel_card_refresh_chunk()
        mids = []
        for mid_str in list(self._mvp_card_labels.keys()):
            try:
                mids.append(int(mid_str))
            except (TypeError, ValueError):
                continue
        if not mids:
            self._mvp_refresh_catalog_header_counts()
            return
        self._mvp_refresh_visible_cards_batched(mids, 0, batch)

    def _mvp_reset_all_timers(self):
        data = self._mvp_timers_data()
        entries = data.get("entries") or []
        if not entries:
            messagebox.showinfo("MVP", "Não há MVPs registados.", parent=self)
            return
        if not messagebox.askyesno(
            "MVP",
            "Resetar todos os timers?\n\n"
            "Isto remove a hora de morte e as coordenadas de cada MVP registado. "
            "A contagem só volta a correr depois de abrir «Editar timer», definir a morte e «Salvar».",
            parent=self,
        ):
            return
        for e in entries:
            e["death_at"] = ""
            e["death_x"] = None
            e["death_y"] = None
            e["alert_fired"] = False
        save_mvp_storage(data)
        self._mvp_invalidate_timer_storage_cache()
        self._mvp_scroll_grid_to_top()
        self._mvp_refresh_all_visible_cards_batched()

    def _mvp_open_edit_dialog(self, entry_id):
        st = self._mvp_timers_data()
        ent = None
        for e in st.get("entries") or []:
            if e.get("entry_id") == entry_id:
                ent = e
                break
        if not ent:
            return

        mid_edit = int(ent.get("monster_id") or 0)

        top = tk.Toplevel(self)
        title_name = self._mvp_display_name_for_mid(mid_edit, str(ent.get("name") or "MVP"))
        top.title(f"Editar MVP — {title_name}")
        top.configure(bg=C["bg"])
        top.transient(self)
        top.resizable(True, True)

        footer = tk.Frame(top, bg=C["bg"])
        footer.pack(side="bottom", fill="x", padx=12, pady=(8, 12))
        btn_salvar = DarkButton(footer, text="Salvar", style="success", padx=8)
        btn_salvar.pack(side="left", padx=4)

        content_host = tk.Frame(top, bg=C["bg"])
        content_host.pack(side="top", fill="both", expand=True, padx=12, pady=(12, 0))
        scroll = ScrollableFrame(content_host, inner_bg=C["bg"])
        scroll.pack(fill="both", expand=True)
        fr = scroll.inner

        def _schedule_fit_geometry() -> None:
            if not top.winfo_exists():
                return
            _mvp_fit_edit_dialog_geometry(top, self, inner=fr, footer_frm=footer)

        def persist(patch: dict) -> None:
            d = load_mvp_storage()
            for x in d.get("entries") or []:
                if x.get("entry_id") == entry_id:
                    x.update(patch)
                    break
            save_mvp_storage(d)
            self._mvp_invalidate_timer_storage_cache()

        def load_ent():
            d = load_mvp_storage()
            for x in d.get("entries") or []:
                if x.get("entry_id") == entry_id:
                    return x
            return None

        lbl_help = tk.Label(
            fr,
            text="Clique na área colorida do mapa para marcar onde o MVP morreu. "
            "A origem (0,0) fica no canto inferior esquerdo.",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 9),
            wraplength=_MVP_EDIT_DIALOG_PREF_W - 48,
            justify="left",
        )
        lbl_help.pack(anchor="w", pady=(0, 10))

        maps = list(ent.get("spawn_maps") or [])
        if not maps:
            try:
                mid_ent = int(ent.get("monster_id") or 0)
            except (TypeError, ValueError):
                mid_ent = 0
            if mid_ent:
                for it in self._mvp_catalog_items or []:
                    try:
                        if int(it.get("id") or 0) == mid_ent:
                            maps = [
                                str(x).strip()
                                for x in (it.get("spawn_maps") or [])
                                if str(x).strip()
                            ]
                            break
                    except (TypeError, ValueError):
                        continue
        row_map = tk.Frame(fr, bg=C["bg"])
        row_map.pack(fill="x", pady=4)
        row_map.columnconfigure(1, weight=1)
        tk.Label(row_map, text="Mapa da morte:", bg=C["bg"], fg=C["text"], font=("Segoe UI", 9)).grid(
            row=0, column=0, sticky="w"
        )
        map_cb = ttk.Combobox(row_map, values=maps or [""], width=32, font=("Segoe UI", 9), state="readonly")
        cur_dm = (ent.get("death_map") or "").strip() or (maps[0] if maps else "")
        if cur_dm in maps or not maps:
            map_cb.set(cur_dm or "")
        elif maps:
            map_cb.set(maps[0])
        map_cb.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        row_d = tk.Frame(fr, bg=C["bg"])
        row_d.pack(fill="x", pady=4)
        row_d.columnconfigure(1, weight=1)
        tk.Label(row_d, text="Morte (AAAA-MM-DD HH:MM):", bg=C["bg"], fg=C["text"], font=("Segoe UI", 9)).grid(
            row=0, column=0, sticky="w"
        )
        raw_death = str(ent.get("death_at") or "").strip()
        if raw_death:
            death_s = raw_death[:16].replace("T", " ")
        else:
            death_s = datetime.now().strftime("%Y-%m-%d %H:%M")
        de = DarkEntry(row_d, width=18)
        de.grid(row=0, column=1, sticky="w", padx=(8, 0))
        de.insert(0, death_s)

        row_r = tk.Frame(fr, bg=C["bg"])
        row_r.pack(fill="x", pady=4)
        row_r.columnconfigure(1, weight=1)
        tk.Label(row_r, text="Respawn (min):", bg=C["bg"], fg=C["text"], font=("Segoe UI", 9)).grid(
            row=0, column=0, sticky="w"
        )
        rm = max(1, int(ent.get("respawn_seconds") or 3600) // 60)
        sp = tk.Spinbox(
            row_r,
            from_=1,
            to=10080,
            width=8,
            bg=C.get("bg3", "#2a2a2a"),
            fg=C["text"],
            insertbackground=C["purple2"],
            font=("Segoe UI", 9),
        )
        sp.delete(0, "end")
        sp.insert(0, str(rm))
        sp.grid(row=0, column=1, sticky="w", padx=(8, 0))

        row_xy = tk.Frame(fr, bg=C["bg"])
        row_xy.pack(fill="x", pady=4)
        tk.Label(row_xy, text="Coords (jogo):", bg=C["bg"], fg=C["text"], font=("Segoe UI", 9)).grid(
            row=0, column=0, sticky="w"
        )
        xy_inputs = tk.Frame(row_xy, bg=C["bg"])
        xy_inputs.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ex_x = DarkEntry(xy_inputs, width=8)
        ex_x.pack(side="left")
        ex_x.insert(0, str(ent["death_x"]) if ent.get("death_x") is not None else "")
        ex_y = DarkEntry(xy_inputs, width=8)
        ex_y.pack(side="left", padx=(6, 0))
        ex_y.insert(0, str(ent["death_y"]) if ent.get("death_y") is not None else "")

        map_host = tk.Frame(fr, bg=C["bg"])
        map_host.pack(fill="x", pady=8)

        lbl_xy_status = tk.Label(fr, text="", bg=C["bg"], fg=C["hero_points"], font=("Segoe UI", 9))
        lbl_xy_status.pack(anchor="w")

        cv_ref = [None]
        map_photo_ref: list = []
        map_native_wh = [0, 0]
        map_display_wh = [0, 0]
        map_display_off = [0, 0]
        map_click_mask = [b""]

        def flush_dialog() -> None:
            raw_death = de.get().strip()
            dt = parse_user_datetime(raw_death) if raw_death else None
            if dt:
                persist({"death_at": dt.strftime("%Y-%m-%d %H:%M:%S"), "alert_fired": False})
            elif not raw_death:
                persist({"death_at": "", "alert_fired": False})
            try:
                mn = int(sp.get())
                persist({"respawn_seconds": max(60, mn * 60)})
            except (ValueError, tk.TclError):
                pass
            dm = map_cb.get().strip()
            persist({"death_map": dm})
            xs, ys = ex_x.get().strip(), ex_y.get().strip()
            patch: dict = {}
            if not xs:
                patch["death_x"] = None
            elif xs.isdigit() or (xs.startswith("-") and xs[1:].isdigit()):
                patch["death_x"] = int(xs)
            if not ys:
                patch["death_y"] = None
            elif ys.isdigit() or (ys.startswith("-") and ys[1:].isdigit()):
                patch["death_y"] = int(ys)
            if patch:
                persist(patch)

        def redraw_minimap() -> None:
            for w in map_host.winfo_children():
                w.destroy()
            cv_ref[0] = None
            map_native_wh[:] = [0, 0]
            map_display_wh[:] = [0, 0]
            map_display_off[:] = [0, 0]
            map_click_mask[:] = [b""]
            lbl_xy_status.configure(text="")
            dm = map_cb.get().strip()
            if not dm:
                tk.Label(
                    map_host,
                    text="Escolha o mapa da morte para marcar as coordenadas.",
                    bg=C["bg"],
                    fg=C["text3"],
                    font=("Segoe UI", 9),
                    wraplength=480,
                ).pack(pady=12)
                return
            try:
                from io import BytesIO

                from PIL import Image, ImageTk

                map_blob, _map_url = resolve_map_image(dm)
                if not map_blob:
                    tk.Label(
                        map_host,
                        text=f"Sem mapa de «{dm}». Importe com tools/import_mvp_map_folder.py.",
                        bg=C["bg"],
                        fg=C["text3"],
                        font=("Segoe UI", 9),
                        wraplength=480,
                    ).pack(pady=12)
                    return

                im = Image.open(BytesIO(map_blob)).convert("RGBA")
                nw, nh = im.size
                if nw <= 0 or nh <= 0:
                    return
                mw, mh, mask_bytes = build_mvp_map_click_mask_from_image(im)
                box_w, box_h = _MVP_MAP_DISPLAY_BOX_W, _MVP_MAP_DISPLAY_BOX_H
                dw, dh, off_x, off_y = mvp_map_display_layout(nw, nh, box_w, box_h)
                map_native_wh[:] = [nw, nh]
                map_display_wh[:] = [dw, dh]
                map_display_off[:] = [off_x, off_y]
                map_click_mask[:] = [mask_bytes]
                map_photo_ref.clear()

                if dw != nw or dh != nh:
                    im_show = im.resize((dw, dh), Image.Resampling.NEAREST)
                else:
                    im_show = im

                shell = tk.Frame(map_host, bg=C["bg"])
                shell.pack(anchor="center")

                cv = tk.Canvas(
                    shell,
                    width=box_w,
                    height=box_h,
                    bg="#0a0a12",
                    highlightthickness=1,
                    highlightbackground=C["border"],
                    cursor="arrow",
                )
                cv.pack()
                cv_ref[0] = cv

                ph = ImageTk.PhotoImage(im_show, master=top)
                map_photo_ref.append(ph)
                cv.create_image(off_x, off_y, anchor="nw", image=ph, tags="map_bg")

                tk.Label(
                    map_host,
                    text=(
                        f"Mapa {dm}: {nw}×{nh} células (1:1) — vista {box_w}×{box_h} px, "
                        "centrada. Origem inferior esquerda."
                    ),
                    bg=C["bg"],
                    fg=C["text3"],
                    font=("Segoe UI", 8),
                ).pack(anchor="center", pady=(4, 0))

                def _canvas_xy(ev) -> Tuple[float, float]:
                    return float(ev.x), float(ev.y)

                def _local_on_map(cx: float, cy: float) -> Optional[Tuple[float, float]]:
                    lx, ly = cx - off_x, cy - off_y
                    if lx < 0 or ly < 0 or lx >= dw or ly >= dh:
                        return None
                    return lx, ly

                def draw_mob_at_game(gx: int, gy: int) -> None:
                    canvas = cv_ref[0]
                    if not canvas:
                        return
                    canvas.delete("mvp_icon")
                    px, py = game_to_pixel_coords(
                        gx, gy, nw, nh, display_w=dw, display_h=dh
                    )
                    px += off_x
                    py += off_y
                    r = 8
                    canvas.create_line(
                        px - r, py, px + r, py, fill=C["purple2"], width=2, tags="mvp_icon"
                    )
                    canvas.create_line(
                        px, py - r, px, py + r, fill=C["purple2"], width=2, tags="mvp_icon"
                    )

                def on_motion(ev):
                    cx, cy = _canvas_xy(ev)
                    local = _local_on_map(cx, cy)
                    if local is None:
                        cv.configure(cursor="arrow")
                        lbl_xy_status.configure(text="")
                        return
                    lx, ly = local
                    gx, gy = pixel_to_game_coords(
                        lx, ly, nw, nh, display_w=dw, display_h=dh
                    )
                    if is_mvp_map_coord_clickable(gx, gy, mw, mh, mask_bytes):
                        cv.configure(cursor="crosshair")
                        lbl_xy_status.configure(
                            text=f"X={gx}  Y={gy}  ({nw}×{nh}) — clique para marcar"
                        )
                    else:
                        cv.configure(cursor="no")
                        lbl_xy_status.configure(
                            text="Fora do mapa jogável — clique nas áreas coloridas"
                        )

                def on_click(ev):
                    cx, cy = _canvas_xy(ev)
                    local = _local_on_map(cx, cy)
                    if local is None:
                        return
                    lx, ly = local
                    gx, gy = pixel_to_game_coords(
                        lx, ly, nw, nh, display_w=dw, display_h=dh
                    )
                    if not is_mvp_map_coord_clickable(gx, gy, mw, mh, mask_bytes):
                        lbl_xy_status.configure(
                            text="Clique fora do mapa: toque na área colorida."
                        )
                        return
                    ex_x.delete(0, "end")
                    ex_x.insert(0, str(gx))
                    ex_y.delete(0, "end")
                    ex_y.insert(0, str(gy))
                    draw_mob_at_game(gx, gy)
                    persist({"death_map": dm, "death_x": gx, "death_y": gy})
                    lbl_xy_status.configure(text=f"Posição: X={gx}  Y={gy}  (mapa {dm})")

                cv.bind("<Motion>", on_motion)
                cv.bind("<Leave>", lambda _e: cv.configure(cursor="arrow"))
                cv.bind("<Button-1>", on_click)

                xe = load_ent()
                if xe and (xe.get("death_map") or "").strip() == dm:
                    xn, yn = xe.get("death_x"), xe.get("death_y")
                    if xn is not None and yn is not None:
                        try:
                            draw_mob_at_game(int(xn), int(yn))
                            lbl_xy_status.configure(text=f"Marcador — X={xn} Y={yn}")
                        except (TypeError, ValueError):
                            pass
            except Exception as ex:
                logger.exception("Minimapa MVP «%s»", dm)
                tk.Label(map_host, text=str(ex), bg=C["bg"], fg=C["red"], wraplength=480).pack()

        def on_map_change(_e=None):
            dm_sel = map_cb.get().strip()
            persist({"death_map": dm_sel})
            redraw_minimap()

        map_cb.bind("<<ComboboxSelected>>", on_map_change)

        def redraw_then_fit() -> None:
            redraw_minimap()
            _schedule_fit_geometry()

        top.after(60, redraw_then_fit)
        top.after(200, _schedule_fit_geometry)

        def close_dialog():
            before_ids = self._mvp_filtered_ordered_ids()
            flush_dialog()
            try:
                top.destroy()
            except tk.TclError:
                pass
            self._mvp_storage_change_refresh(mid_edit, before_ids)

        def dismiss_without_save():
            """Fechar pela X: não gravar o formulário (timer e dados só com «Salvar»)."""
            before_ids = self._mvp_filtered_ordered_ids()
            try:
                top.destroy()
            except tk.TclError:
                pass
            self._mvp_storage_change_refresh(mid_edit, before_ids)

        top.protocol("WM_DELETE_WINDOW", dismiss_without_save)
        btn_salvar.configure(command=close_dialog)
        top.update_idletasks()
        _schedule_fit_geometry()

    def _mvp_grid_place_card(self, host, idx: int, cit: dict, ent, cols: int, card_bg: str, card_bd: str) -> None:
        mid = int(cit["id"])
        r, col = divmod(idx, cols)
        card = tk.Frame(
            host,
            bg=card_bg,
            highlightbackground=card_bd,
            highlightthickness=1,
        )
        card.grid(row=r, column=col, padx=6, pady=6, sticky="nsew")
        inner = tk.Frame(card, bg=card_bg)
        inner.pack(fill="both", expand=True, padx=10, pady=10)
        self._mvp_fill_card_inner(inner, cit, ent, mid)

    def _mvp_render_mvp_cards(self, *, update_hdr_counts: bool = True):
        self._mvp_cancel_card_refresh_chunk()
        self._mvp_cancel_sprite_poll()
        self._mvp_cancel_deferred_grid_refresh()
        self._mvp_cancel_chunked_render()
        self._mvp_cards_generation += 1
        gen = self._mvp_cards_generation
        self._mvp_card_labels.clear()
        self._mvp_photo_refs = []
        host = self.mvp_cards_host

        def _finish_render():
            self._mvp_grid_render_gen_done = gen
            self._mvp_last_render_sig = self._mvp_render_signature()
            self._mvp_catalog_cache_mtime = self._mvp_file_mtime(MVP_CATALOG_PORTABLE_FILE)
            try:
                self._mvp_grid_progress_label.pack_forget()
            except tk.TclError:
                pass
            self._mvp_clear_filter_busy()
            self._mvp_scroll_grid_to_top()

        for w in host.winfo_children():
            w.destroy()

        if self._mvp_catalog_fetching and not self._mvp_catalog_items:
            tk.Label(
                host,
                text="A sincronizar todos os MVPs com divine-pride.net…",
                bg=C["bg"],
                fg=C["text3"],
                font=("Segoe UI", 12),
                justify="center",
            ).pack(pady=80)
            _finish_render()
            return

        data = self._mvp_timers_data()
        items = self._mvp_filtered_catalog_items()
        if not self._mvp_catalog_items:
            tk.Label(
                host,
                text="Catálogo de MVPs não carregado.\nVerifique a pasta data/ e reinicie.",
                bg=C["bg"],
                fg=C["text3"],
                font=("Segoe UI", 11),
                justify="center",
            ).pack(pady=60)
            if update_hdr_counts:
                self._mvp_refresh_catalog_header_counts()
            _finish_render()
            return

        if not items:
            mode = self._mvp_filter_mode.get()
            try:
                sq = str(self._mvp_search_var.get() or "").strip()
            except (tk.TclError, AttributeError):
                sq = ""
            if sq:
                tk.Label(
                    host,
                    text=f"Nenhum MVP encontrado para «{sq[:50]}{'…' if len(sq) > 50 else ''}».\n"
                    "Tente outro nome, o ID ou remova os acentos.",
                    bg=C["bg"],
                    fg=C["text3"],
                    font=("Segoe UI", 11),
                    justify="center",
                ).pack(pady=60)
            elif mode == "todos":
                tk.Label(
                    host,
                    text="Catálogo vazio.\nAtualize a lista (precisa de internet).",
                    bg=C["bg"],
                    fg=C["text3"],
                    font=("Segoe UI", 11),
                    justify="center",
                ).pack(pady=60)
            else:
                tk.Label(
                    host,
                    text="Nenhum MVP neste filtro.\nUse «Todos os MVPs» ou ajuste a busca.",
                    bg=C["bg"],
                    fg=C["text3"],
                    font=("Segoe UI", 11),
                    justify="center",
                ).pack(pady=60)
            if update_hdr_counts:
                self._mvp_refresh_catalog_header_counts()
            _finish_render()
            return

        by_mid = {}
        for e in data.get("entries") or []:
            mid = int(e.get("monster_id") or 0)
            if mid and mid not in by_mid:
                by_mid[mid] = e

        cols = max(1, int(getattr(self, "_MVP_GRID_COLS", 5)))
        for c in range(cols):
            host.columnconfigure(c, weight=1, uniform="mvp_tile")
        rows = (len(items) + cols - 1) // cols
        for rr in range(rows):
            host.rowconfigure(rr, weight=1)

        card_bd = C["border"]
        card_bg = C["card"]

        n = len(items)
        chunk_sz = 20
        self._mvp_grid_progress_label.configure(text=f"Carregando… 0/{n}")
        self._mvp_grid_progress_label.pack(fill="x", padx=16, pady=(0, 4))
        self._mvp_schedule_sprite_poll()

        state = {"i": 0}

        def pump():
            if gen != self._mvp_cards_generation:
                return
            if self.current_page.get() != "mvp":
                return
            end = min(state["i"] + chunk_sz, n)
            for idx in range(state["i"], end):
                cit = items[idx]
                mid = int(cit["id"])
                ent = by_mid.get(mid)
                self._mvp_grid_place_card(host, idx, cit, ent, cols, card_bg, card_bd)
            try:
                self._mvp_grid_progress_label.configure(text=f"Carregando… {end}/{n}")
            except tk.TclError:
                pass
            state["i"] = end
            if end < n:
                self._mvp_chunk_after_id = self.after(10, pump)
            else:
                self._mvp_chunk_after_id = None
                if update_hdr_counts:
                    self._mvp_refresh_catalog_header_counts()
                _finish_render()

        self._mvp_chunk_after_id = self.after(0, pump)

