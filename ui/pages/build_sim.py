"""
Simulação de build (equipamento + visual).
"""
from __future__ import annotations

import logging
import re
import threading
import uuid
from datetime import datetime

import tkinter as tk
from tkinter import messagebox, ttk

import app_formatters
from adapters import herosaga_api
from app_runtime import api_search_item_names, get_stores_from_item_page
from app_settings import load_settings, save_settings
from build_simulator import (
    BUILD_SLOT_LEFT,
    BUILD_SLOT_RIGHT,
    SLOT_LABELS_PT,
    default_layer_state,
    default_slot_state,
    filter_stores_slot,
    item_meta_is_two_handed,
    load_builds_file,
    min_prices_from_stores,
    save_builds_file,
)
from core.constants import BASE_URL
from item_icon_cache import resolve_item_icon_url
from ui.theme import C
from ui.widgets import DarkButton, DarkCheckbutton, DarkEntry, ScrollableFrame
from ui.widgets.helpers import canvas_round_fill

logger = logging.getLogger(__name__)

_normalize_media_url = herosaga_api.normalize_media_url
fmt_price_stores = app_formatters.fmt_price_stores

_BUILD_SIM_VISUAL_PANEL_TITLE = "Visuais (shadows)"

_BUILD_SIM_LAYER_JSON_KEYS = {
    "equip": ("equip", "equipment", "equipamento"),
    "visual": (
        "visual",
        "shadows",
        "shadow",
        "visuais",
        "cosmetic",
        "cosmeticos",
        "cosméticos",
        "cosmetico",
        "cosmético",
    ),
}

_BUILD_SIM_SLOT_LEGACY_SRC_KEYS = {
    "armor": ("armadura", "body", "chest", "coat"),
}


class BuildSimMixin:
    """Página Simulação de Build."""

    def _build_build_sim(self):
        self.build_sim_frame = tk.Frame(self.main, bg=C["bg"])
        self._build_sim_refresh_gen = 0
        self._build_state = {"equip": default_layer_state(), "visual": default_layer_state()}
        self._build_ui_slot_widgets = {"equip": {}, "visual": {}}
        self._build_price_cache = {}
        self._build_sim_photo_refs = []
        self._build_sim_last_saved_id = None
        self._build_sim_selected_saved_id = None

        scroll = ScrollableFrame(self.build_sim_frame, inner_bg=C["bg"])
        scroll.pack(fill="both", expand=True, padx=10, pady=8)
        root = scroll.inner

        hdr = tk.Frame(root, bg=C["bg"])
        hdr.pack(fill="x", pady=(4, 8))
        hdr_top = tk.Frame(hdr, bg=C["bg"])
        hdr_top.pack(fill="x")
        tk.Label(
            hdr_top,
            text="Simulação de Build",
            bg=C["bg"],
            fg=C["purple3"],
            font=("Segoe UI", 16, "bold"),
        ).pack(side="left", anchor="w")
        hdr_pick = tk.Frame(hdr, bg=C["bg"])
        hdr_pick.pack(fill="x", pady=(8, 0))
        tk.Label(
            hdr_pick,
            text="Build guardada:",
            bg=C["bg"],
            fg=C["text"],
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(0, 8))
        self._build_sim_combo_ignore = False
        self._build_sim_saved_list = []
        self._build_sim_saved_combo = ttk.Combobox(
            hdr_pick,
            state="readonly",
            width=56,
            font=("Segoe UI", 9),
        )
        self._build_sim_saved_combo.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._build_sim_saved_combo.bind("<<ComboboxSelected>>", self._build_sim_on_saved_combo_pick)
        DarkButton(
            hdr_pick,
            text="Principal",
            style="ghost",
            font=("Segoe UI", 8),
            padx=8,
            pady=2,
            command=self._build_sim_mark_selected_as_primary,
        ).pack(side="left")

        totals = tk.Frame(root, bg=C["card"], highlightbackground=C["border"], highlightthickness=1)
        totals.pack(fill="x", pady=6)
        tk.Label(
            totals,
            text="Totais estimados",
            bg=C["card"],
            fg=C["purple3"],
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=12, pady=(10, 4))

        row_hp = tk.Frame(totals, bg=C["card"])
        row_hp.pack(fill="x", padx=12, pady=4)
        tk.Label(row_hp, text="1 RMT =", bg=C["card"], fg=C["text"]).pack(side="left")
        self._build_hp_entry = DarkEntry(row_hp, width=8)
        self._build_hp_entry.pack(side="left", padx=6)
        self._build_hp_entry.insert(0, "30")
        tk.Label(
            row_hp,
            text="Hero Points",
            bg=C["card"],
            fg=C["text3"],
            font=("Segoe UI", 8),
        ).pack(side="left")

        row_t = tk.Frame(totals, bg=C["card"])
        row_t.pack(fill="x", padx=12, pady=(4, 8))
        self._build_lbl_total_rmt = tk.Label(
            row_t, text="RMT: —", bg=C["card"], fg=C["rmt"], font=("Segoe UI", 10, "bold")
        )
        self._build_lbl_total_rmt.pack(side="left", padx=(0, 14))
        self._build_lbl_total_hp = tk.Label(
            row_t,
            text="HP (equiv.): —",
            bg=C["card"],
            fg=C["hero_points"],
            font=("Segoe UI", 10, "bold"),
        )
        self._build_lbl_total_hp.pack(side="left", padx=(0, 14))

        btn_row = tk.Frame(totals, bg=C["card"])
        btn_row.pack(fill="x", padx=12, pady=(0, 12))
        DarkButton(
            btn_row,
            text="Atualizar preços",
            style="primary",
            command=self._build_sim_refresh_prices,
        ).pack(side="left", padx=4)
        DarkButton(btn_row, text="Salvar Build", style="success", command=self._build_sim_save_dialog).pack(
            side="left", padx=4
        )

        boards = tk.Frame(root, bg=C["bg"])
        boards.pack(fill="both", expand=True, pady=8)

        equip_wrap = tk.Frame(boards, bg=C["bg"], highlightthickness=0)
        equip_wrap.pack(side="left", fill="both", expand=True, padx=(4, 36), pady=6)
        self._build_sim_layer_panel(equip_wrap, "equip", "Equipamento (principal)")

        gap_mid = tk.Frame(boards, bg=C["bg"], width=32)
        gap_mid.pack(side="left", fill="y", padx=20, pady=6)
        gap_mid.pack_propagate(False)

        visual_wrap = tk.Frame(boards, bg=C["bg"], highlightthickness=0)
        visual_wrap.pack(side="left", fill="both", expand=True, padx=(36, 4), pady=6)
        self._build_sim_layer_panel(visual_wrap, "visual", _BUILD_SIM_VISUAL_PANEL_TITLE)

        self._build_sim_refresh_saved_combo_list()
        self.after(120, self._build_sim_restore_from_settings)

    def _build_sim_persist_last_saved_id(self):
        """Grava em settings o id da build guardada seleccionada (vazio = nova simulação)."""
        try:
            if not getattr(self, "_build_sim_saved_combo", None):
                return
            sid = getattr(self, "_build_sim_selected_saved_id", None) or ""
            cfg = load_settings()
            cfg["last_build_sim_saved_id"] = str(sid) if sid else ""
            save_settings(cfg)
        except Exception:
            pass

    def _build_sim_mark_selected_as_primary(self):
        """Define a build actualmente seleccionada na lista como principal (aberta ao iniciar)."""
        idx = self._build_sim_saved_combo.current()
        if idx <= 0:
            messagebox.showinfo(
                "Build principal",
                "Escolha uma build salva na lista (não «Nova simulação»).",
                parent=self,
            )
            return
        b = self._build_sim_saved_list[idx - 1]
        bid = str(b.get("id") or "")
        if not bid:
            return
        cfg = load_settings()
        cfg["primary_build_sim_saved_id"] = bid
        save_settings(cfg)
        messagebox.showinfo(
            "Build principal",
            "Esta build será carregada ao abrir a simulação (se ainda existir na lista).",
            parent=self,
        )

    def _build_sim_restore_from_settings(self):
        """Ao iniciar, reabre a build principal (se definida), senão a última seleccionada."""
        try:
            if not getattr(self, "_build_sim_saved_combo", None):
                return
            cfg = load_settings()
            primary = (cfg.get("primary_build_sim_saved_id") or "").strip()
            last = (cfg.get("last_build_sim_saved_id") or "").strip()
            sid_order = []
            if primary:
                sid_order.append(primary)
            if last and last not in sid_order:
                sid_order.append(last)
            found = None
            sid = ""
            for cand in sid_order:
                for s in self._build_sim_saved_list:
                    if isinstance(s, dict) and str(s.get("id")) == cand:
                        found = s
                        sid = cand
                        break
                if found:
                    break
            if not found:
                cfg2 = load_settings()
                changed = False
                if primary and not any(
                    isinstance(s, dict) and str(s.get("id")) == primary for s in self._build_sim_saved_list
                ):
                    cfg2["primary_build_sim_saved_id"] = ""
                    changed = True
                if last and not any(
                    isinstance(s, dict) and str(s.get("id")) == last for s in self._build_sim_saved_list
                ):
                    cfg2["last_build_sim_saved_id"] = ""
                    changed = True
                if changed:
                    save_settings(cfg2)
                return
            self._build_sim_combo_ignore = True
            try:
                for i, s in enumerate(self._build_sim_saved_list):
                    if str(s.get("id")) == sid:
                        self._build_sim_saved_combo.current(i + 1)
                        break
            finally:
                self._build_sim_combo_ignore = False
            self._build_sim_selected_saved_id = found.get("id")
            self._build_sim_apply_saved_build_dict(found)
            self._build_sim_sync_all_slots_ui()
            self._build_sim_clear_slot_price_labels()
            self.after(120, self._build_sim_refresh_prices)
            self.after(140, self._build_sim_fetch_missing_icons)
            self.after(150, self._build_sim_fetch_missing_names)
        except Exception:
            pass

    def _build_sim_refresh_saved_combo_list(self, select_id=None):
        """Preenche o combobox com builds guardadas; ``select_id`` selecciona uma pelo ``id``."""
        data = load_builds_file()
        self._build_sim_saved_list = [x for x in (data.get("saved") or []) if isinstance(x, dict)]
        vals = ["(Nova simulação — não guardada)"] + [
            f"{s.get('name', 'Build')}  [{str(s.get('id', ''))[:8]}]" for s in self._build_sim_saved_list
        ]
        combo = self._build_sim_saved_combo
        combo["values"] = vals
        self._build_sim_combo_ignore = True
        try:
            if select_id:
                sid = str(select_id)
                for i, s in enumerate(self._build_sim_saved_list):
                    if str(s.get("id")) == sid:
                        combo.current(i + 1)
                        self._build_sim_selected_saved_id = s.get("id")
                        break
                else:
                    combo.current(0)
                    self._build_sim_selected_saved_id = None
            else:
                sid = getattr(self, "_build_sim_selected_saved_id", None)
                if sid:
                    found = False
                    for i, s in enumerate(self._build_sim_saved_list):
                        if str(s.get("id")) == str(sid):
                            combo.current(i + 1)
                            found = True
                            break
                    if not found:
                        combo.current(0)
                        self._build_sim_selected_saved_id = None
                else:
                    combo.current(0)
        finally:
            self._build_sim_combo_ignore = False

    def _build_sim_on_saved_combo_pick(self, _event=None):
        if getattr(self, "_build_sim_combo_ignore", False):
            return
        idx = self._build_sim_saved_combo.current()
        if idx < 0:
            return
        if idx == 0:
            self._build_sim_selected_saved_id = None
            self._build_state = {"equip": default_layer_state(), "visual": default_layer_state()}
            try:
                self._build_hp_entry.delete(0, "end")
                self._build_hp_entry.insert(0, "30")
            except tk.TclError:
                pass
        else:
            b = self._build_sim_saved_list[idx - 1]
            self._build_sim_selected_saved_id = b.get("id")
            self._build_sim_apply_saved_build_dict(b)
        self._build_sim_sync_all_slots_ui()
        self._build_sim_clear_slot_price_labels()
        if idx > 0:
            self.after(80, self._build_sim_refresh_prices)
            self.after(90, self._build_sim_fetch_missing_icons)
            self.after(100, self._build_sim_fetch_missing_names)
        self._build_sim_persist_last_saved_id()

    def _build_sim_layer_src_from_build(self, b: dict, layer: str) -> dict:
        """Resolve camada equip/visual em JSON (inclui chaves antigas «shadows», «visuais», etc.)."""
        if not isinstance(b, dict):
            return {}
        for key in _BUILD_SIM_LAYER_JSON_KEYS.get(layer, (layer,)):
            raw = b.get(key)
            if not isinstance(raw, dict):
                continue
            nested = raw.get("slots")
            if isinstance(nested, dict):
                merged = dict(nested)
                for k, v in raw.items():
                    if k != "slots" and k not in merged:
                        merged[k] = v
                return merged
            return raw
        return {}

    def _build_sim_cell_from_saved_raw(self, raw: dict | None) -> dict:
        cell = default_slot_state()
        if not isinstance(raw, dict):
            return cell
        for key, val in raw.items():
            if key == "item_id" and val is not None:
                try:
                    val = int(val)
                except (TypeError, ValueError):
                    val = None
            if key in cell or key == "item_icon_url":
                cell[key] = val
        return cell

    def _build_sim_apply_saved_build_dict(self, b: dict):
        try:
            hpr = int(b.get("hp_per_rmt") or 30)
        except (TypeError, ValueError):
            hpr = 30
        try:
            self._build_hp_entry.delete(0, "end")
            self._build_hp_entry.insert(0, str(hpr))
        except tk.TclError:
            pass
        for layer_key in ("equip", "visual"):
            src = self._build_sim_layer_src_from_build(b, layer_key)
            for sk in self._all_build_slot_keys():
                raw = src.get(sk)
                if not isinstance(raw, dict):
                    for alt in _BUILD_SIM_SLOT_LEGACY_SRC_KEYS.get(sk, ()):
                        raw = src.get(alt)
                        if isinstance(raw, dict):
                            break
                    else:
                        raw = None
                self._build_state[layer_key][sk] = self._build_sim_cell_from_saved_raw(raw)

    def _build_sim_sync_all_slots_ui(self) -> None:
        """Repinta entradas, nomes e ícones de equip + visuais a partir do estado."""
        for layer in ("equip", "visual"):
            for sk in self._all_build_slot_keys():
                widgets = self._build_ui_slot_widgets.get(layer, {})
                if sk not in widgets:
                    continue
                self._build_sim_sync_row_from_state(layer, sk)
                self._build_sim_update_slot_icon(layer, sk)
        self._build_sim_set_left_hand_state("equip", "weapon_left")

    def _build_sim_fetch_missing_names(self) -> None:
        """Preenche ``item_name`` em slots com ID mas sem nome (ex.: build guardada antiga)."""
        tasks: list[tuple[str, str, int]] = []
        for layer in ("equip", "visual"):
            for sk in self._all_build_slot_keys():
                cell = self._build_state[layer][sk]
                try:
                    iid = int(cell.get("item_id") or 0)
                except (TypeError, ValueError):
                    continue
                if iid <= 0:
                    continue
                if (cell.get("item_name") or "").strip():
                    continue
                tasks.append((layer, sk, iid))
        if not tasks:
            return

        def work():
            updates: list[tuple[str, str, str]] = []
            for layer, sk, iid in tasks:
                name = f"Item {iid}"
                try:
                    for r in api_search_item_names(str(iid)) or []:
                        if int(r.get("id", 0) or 0) == iid and r.get("name"):
                            name = str(r.get("name")).strip()
                            break
                except Exception:
                    pass
                updates.append((layer, sk, name))

            def apply_names():
                for layer, sk, name in updates:
                    try:
                        self._build_state[layer][sk]["item_name"] = name
                        self._build_ui_slot_widgets[layer][sk]["lname"].configure(
                            text=name, fg=C["text2"]
                        )
                    except (tk.TclError, KeyError):
                        pass

            self.after(0, apply_names)

        threading.Thread(target=work, daemon=True).start()

    def _build_sim_clear_slot_price_labels(self):
        self._build_price_cache = {}
        for layer in ("equip", "visual"):
            for sk in self._all_build_slot_keys():
                w = self._build_ui_slot_widgets[layer][sk]
                w["lrmt"].configure(text="RMT: —", fg=C["rmt"])
                w["lhp"].configure(text="HP: —", fg=C["hero_points"])
        self._build_sim_recalc_totals()

    def _show_build_sim(self):
        self._clear_main()
        self.build_sim_frame.pack(fill="both", expand=True)
        try:
            self._build_sim_refresh_saved_combo_list()
            self._build_sim_merge_entries_into_state()
            self._build_sim_sync_all_slots_ui()
            self.after(80, self._build_sim_fetch_missing_icons)
            self.after(90, self._build_sim_fetch_missing_names)
        except (tk.TclError, AttributeError):
            pass

    def _all_build_slot_keys(self):
        return list(BUILD_SLOT_LEFT) + list(BUILD_SLOT_RIGHT)

    def _build_sim_layer_panel(self, parent, layer: str, title: str):
        tk.Label(parent, text=title, bg=C["bg"], fg=C["purple3"], font=("Segoe UI", 11, "bold")).pack(
            anchor="w", padx=6, pady=(4, 2)
        )
        row = tk.Frame(parent, bg=C["bg"], highlightthickness=0)
        row.pack(fill="both", expand=True, padx=2, pady=(0, 4))
        lf = tk.Frame(row, bg=C["bg"], highlightthickness=0)
        lf.pack(side="left", fill="both", expand=True, padx=(0, 10))
        rf = tk.Frame(row, bg=C["bg"], highlightthickness=0)
        rf.pack(side="left", fill="both", expand=True, padx=(10, 0))

        for sk in BUILD_SLOT_LEFT:
            self._build_sim_slot_row(lf, layer, sk)
        for sk in BUILD_SLOT_RIGHT:
            self._build_sim_slot_row(rf, layer, sk)

    def _build_sim_slot_row(self, parent, layer: str, slot_key: str):
        sb = C["build_slot_bg"]
        rim = C["build_slot_rim"]
        ebg = C["build_slot_entry_bg"]

        outer = tk.Frame(parent, bg=C["bg"], highlightthickness=0)
        outer.pack(fill="x", pady=5, padx=1)

        cv = tk.Canvas(outer, height=92, bg=C["bg"], highlightthickness=0, borderwidth=0)
        cv.pack(fill="x", expand=True)
        inner = tk.Frame(cv, bg=sb)
        win_id = cv.create_window(2, 2, window=inner, anchor="nw")
        _slot_after = [None]

        def redraw(_e=None):
            if _slot_after[0] is not None:
                try:
                    outer.after_cancel(_slot_after[0])
                except tk.TclError:
                    pass

            def run():
                _slot_after[0] = None
                try:
                    cv.update_idletasks()
                    w = max(int(cv.winfo_width()), 80)
                    inner.update_idletasks()
                    ih = max(int(inner.winfo_reqheight()), 32)
                    ht = ih + 8
                    if w == getattr(cv, "_bslot_rw", -1) and ht == getattr(cv, "_bslot_rh", -1):
                        return
                    cv._bslot_rw, cv._bslot_rh = w, ht
                    cv.configure(height=ht)
                    cv.delete("slotbg")
                    ro, ri = 18, 14
                    canvas_round_fill(cv, 0, 0, w, ht, ro, rim, tag="slotbg", holder=cv)
                    canvas_round_fill(cv, 4, 4, w - 8, ht - 8, ri, sb, tag="slotbg", holder=cv)
                    cv.itemconfigure(win_id, width=max(1, w - 8), height=max(1, ht - 8))
                    cv.coords(win_id, 4, 4)
                except tk.TclError:
                    pass

            _slot_after[0] = outer.after(28, run)

        inner.bind("<Configure>", redraw)
        cv.bind("<Configure>", redraw)

        top = tk.Frame(inner, bg=sb)
        top.pack(fill="x", padx=8, pady=(6, 0))

        icon_slot = tk.Frame(top, bg=sb, width=36, height=28)
        icon_slot.pack(side="left", padx=(0, 6))
        icon_slot.pack_propagate(False)
        icon_lbl = tk.Label(icon_slot, text="·", bg=sb, fg=C["text3"], font=("Segoe UI", 8))
        icon_lbl.place(relx=0.5, rely=0.5, anchor="center")

        col = tk.Frame(top, bg=sb)
        col.pack(side="left", fill="both", expand=True)

        tk.Label(
            col,
            text=SLOT_LABELS_PT.get(slot_key, slot_key),
            bg=sb,
            fg=C["text2"],
            font=("Segoe UI", 7, "bold"),
            anchor="w",
        ).pack(anchor="w")

        r1 = tk.Frame(col, bg=sb)
        r1.pack(fill="x", pady=0)
        ent = tk.Entry(
            r1,
            bg=ebg,
            fg=C["text"],
            insertbackground=C["purple2"],
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=C["build_slot_rim"],
            highlightcolor=C["purple2"],
            font=("Segoe UI", 9),
            width=25,
        )
        ent.pack(side="left", fill="none", expand=False, padx=(0, 8), ipady=1)
        tk.Label(r1, text="Ref.", bg=sb, fg=C["text3"], font=("Segoe UI", 7)).pack(side="left", padx=(0, 1))
        tk.Label(r1, text="+", bg=sb, fg=C["text3"], font=("Segoe UI", 7)).pack(side="left", padx=(0, 1))
        ref_sb = tk.Spinbox(
            r1,
            from_=0,
            to=20,
            width=3,
            bg=ebg,
            fg=C["text"],
            buttonbackground=C["bg3"],
            highlightthickness=0,
            font=("Segoe UI", 8),
        )
        ref_sb.pack(side="left", padx=(0, 6))
        tk.Frame(r1, bg=sb).pack(side="left", fill="x", expand=True)
        DarkButton(
            r1,
            text="Buscar",
            style="success",
            font=("Segoe UI", 8),
            padx=8,
            pady=1,
            command=lambda ly=layer, sk=slot_key: self._build_sim_apply_slot(ly, sk),
        ).pack(side="right")

        name_row = tk.Frame(col, bg=sb)
        name_row.pack(fill="x", pady=(4, 0))
        lname = tk.Label(
            name_row,
            text="—",
            bg=sb,
            fg=C["text3"],
            font=("Segoe UI", 8),
            anchor="w",
            justify="left",
            wraplength=320,
        )
        lname.pack(fill="x", anchor="w")

        prices = tk.Frame(col, bg=sb)
        prices.pack(fill="x", pady=(2, 6))
        fz = ("Segoe UI", 7)
        lrmt = tk.Label(prices, text="RMT: —", bg=sb, fg=C["rmt"], font=fz, anchor="w")
        lrmt.pack(side="left", padx=(0, 6))
        lhp = tk.Label(prices, text="HP: —", bg=sb, fg=C["hero_points"], font=fz, anchor="w")
        lhp.pack(side="left", padx=(0, 6))

        self._build_ui_slot_widgets[layer][slot_key] = {
            "frame": outer,
            "entry": ent,
            "refine_sb": ref_sb,
            "icon_lbl": icon_lbl,
            "lname": lname,
            "lrmt": lrmt,
            "lhp": lhp,
        }
        self._build_sim_sync_row_from_state(layer, slot_key)
        try:
            outer.after_idle(redraw)
        except tk.TclError:
            pass

    def _build_sim_sync_row_from_state(self, layer: str, slot_key: str):
        w = self._build_ui_slot_widgets[layer][slot_key]
        cell = self._build_state[layer][slot_key]
        w["entry"].delete(0, "end")
        iid = cell.get("item_id")
        try:
            if iid is not None and int(iid) > 0:
                w["entry"].insert(0, str(int(iid)))
        except (TypeError, ValueError, tk.TclError):
            pass
        try:
            w["refine_sb"].delete(0, "end")
            w["refine_sb"].insert(0, str(int(cell.get("refine") or 0)))
        except tk.TclError:
            pass
        iid = cell.get("item_id")
        try:
            if iid is not None and int(iid) > 0:
                nm = (cell.get("item_name") or "").strip()
                disp = nm if nm else f"Item {int(iid)}"
                w["lname"].configure(text=disp, fg=C["text2"])
            else:
                w["lname"].configure(text="—", fg=C["text3"])
        except (TypeError, ValueError, tk.TclError, KeyError):
            try:
                w["lname"].configure(text="—", fg=C["text3"])
            except tk.TclError:
                pass
        self._build_sim_set_left_hand_state(layer, slot_key)

    def _build_sim_set_left_hand_state(self, layer: str, slot_key: str):
        if layer != "equip" or slot_key != "weapon_left":
            return
        w = self._build_ui_slot_widgets["equip"]["weapon_left"]
        block = bool(self._build_state["equip"]["weapon_right"].get("is_2h"))
        st = "disabled" if block else "normal"
        try:
            w["entry"].configure(state=st)
            w["refine_sb"].configure(state=st)
        except tk.TclError:
            pass

    def _build_sim_sync_ui_to_state(self):
        for layer in ("equip", "visual"):
            for sk in self._all_build_slot_keys():
                cell = self._build_state[layer][sk]
                if not cell.get("item_id"):
                    continue
                w = self._build_ui_slot_widgets[layer][sk]
                try:
                    cell["refine"] = max(0, min(20, int(w["refine_sb"].get())))
                except (ValueError, TypeError, tk.TclError):
                    cell["refine"] = 0
                cell["cards"] = 0

    def _build_sim_merge_entries_into_state(self):
        """Lê ID e refino das caixas para o estado antes de actualizar preços (sem premir «Buscar»)."""
        for layer in ("equip", "visual"):
            for sk in self._all_build_slot_keys():
                w = self._build_ui_slot_widgets[layer][sk]
                cell = self._build_state[layer][sk]
                try:
                    ref = max(0, min(20, int(w["refine_sb"].get())))
                except (ValueError, TypeError, tk.TclError):
                    try:
                        ref = max(0, min(20, int(cell.get("refine") or 0)))
                    except (TypeError, ValueError):
                        ref = 0
                raw = w["entry"].get().strip()
                pid = None
                if raw:
                    q = raw.strip()
                    low = q.lower()
                    if low.startswith("@ws"):
                        q = q[3:].strip()
                    elif low.startswith("ws") and len(q) > 2 and q[2].isspace():
                        q = q[2:].strip()
                    digits = re.sub(r"\D", "", q)
                    if digits:
                        try:
                            pid = int(digits)
                        except ValueError:
                            pid = None
                try:
                    old_id = int(cell.get("item_id") or 0)
                except (TypeError, ValueError):
                    old_id = 0
                if pid is None:
                    if old_id > 0:
                        cell["refine"] = ref
                    continue
                if old_id != pid:
                    cell["item_name"] = ""
                cell["item_id"] = pid
                cell["refine"] = ref

    def _build_sim_apply_slot(self, layer: str, slot_key: str):
        if layer == "equip" and slot_key == "weapon_left" and self._build_state["equip"]["weapon_right"].get("is_2h"):
            messagebox.showinfo("Arma a duas mãos", "A arma na mão direita ocupa as duas mãos.")
            return
        w = self._build_ui_slot_widgets[layer][slot_key]
        query = w["entry"].get().strip()
        if not query:
            self._build_state[layer][slot_key] = default_slot_state()
            self._build_sim_sync_row_from_state(layer, slot_key)
            self._build_sim_update_slot_icon(layer, slot_key)
            if layer == "equip" and slot_key == "weapon_right":
                self._build_sim_clear_left_if_not_2h()
            return
        try:
            ref_ui = max(0, min(20, int(w["refine_sb"].get())))
        except (ValueError, TypeError, tk.TclError):
            ref_ui = 0

        def work():
            err = None
            try:
                q = query.strip()
                low = q.lower()
                if low.startswith("@ws"):
                    q = q[3:].strip()
                elif low.startswith("ws") and len(q) > 2 and q[2].isspace():
                    q = q[2:].strip()
                digits = re.sub(r"\D", "", q)
                if not digits:
                    raise ValueError("Use só o ID numérico do item (dígitos).")
                iid = int(digits)
                name = f"Item {iid}"
                rows = api_search_item_names(str(iid))
                for r in rows or []:
                    try:
                        if int(r.get("id", 0)) == iid and r.get("name"):
                            name = str(r.get("name")).strip()
                            break
                    except (TypeError, ValueError):
                        continue
                stores, meta = get_stores_from_item_page(iid, "", force_refresh=True)
                ref = ref_ui
                is2 = item_meta_is_two_handed(meta)
                icon_u = meta.get("item_icon_url") if isinstance(meta, dict) else None
            except Exception as e:
                err = str(e)
                iid = name = ref = is2 = icon_u = None
                stores = meta = None

            def done():
                if err:
                    messagebox.showerror("Build", err, parent=self)
                    return
                cell = default_slot_state()
                cell.update(
                    {
                        "item_id": iid,
                        "item_name": name,
                        "refine": ref,
                        "cards": 0,
                        "is_2h": bool(is2),
                        "item_icon_url": _normalize_media_url(icon_u) if icon_u else "",
                    }
                )
                self._build_state[layer][slot_key] = cell
                self._build_sim_sync_row_from_state(layer, slot_key)
                self._build_sim_update_slot_icon(layer, slot_key)
                if layer == "equip" and slot_key == "weapon_right" and cell.get("is_2h"):
                    self._build_state["equip"]["weapon_left"] = default_slot_state()
                    self._build_sim_sync_row_from_state("equip", "weapon_left")
                    self._build_sim_update_slot_icon("equip", "weapon_left")
                elif layer == "equip" and slot_key == "weapon_right":
                    self._build_sim_clear_left_if_not_2h()
                self._build_sim_set_left_hand_state("equip", "weapon_left")
                to_refresh = [(layer, slot_key)]
                if layer == "equip" and slot_key == "weapon_right" and cell.get("is_2h"):
                    to_refresh.append(("equip", "weapon_left"))
                self.after(60, lambda tr=tuple(to_refresh): self._build_sim_refresh_prices_slots(tr))

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _build_sim_fetch_missing_icons(self):
        """Para slots com ``item_id`` mas sem URL de ícone (ex.: build guardada), obtém o ícone pela página do item."""
        tasks = []
        for layer in ("equip", "visual"):
            for sk in self._all_build_slot_keys():
                cell = self._build_state[layer][sk]
                try:
                    iid = int(cell.get("item_id") or 0)
                except (TypeError, ValueError):
                    continue
                if iid <= 0:
                    continue
                if _normalize_media_url(cell.get("item_icon_url") or ""):
                    continue
                tasks.append((layer, sk, iid))

        if not tasks:
            return

        def work():
            updates = []
            for layer, sk, iid in tasks:
                try:
                    _stores, meta = get_stores_from_item_page(iid, "")
                    if not isinstance(meta, dict):
                        continue
                    icon_u = meta.get("item_icon_url")
                    url = _normalize_media_url(icon_u) if icon_u else ""
                    if url:
                        updates.append((layer, sk, url))
                except Exception:
                    pass

            def apply_icons():
                for layer, sk, url in updates:
                    try:
                        cell = self._build_state.get(layer, {}).get(sk)
                        if not isinstance(cell, dict):
                            continue
                        cell["item_icon_url"] = url
                        self._build_sim_update_slot_icon(layer, sk)
                    except (tk.TclError, KeyError):
                        pass

            self.after(0, apply_icons)

        threading.Thread(target=work, daemon=True).start()

    def _build_sim_clear_left_if_not_2h(self):
        if not self._build_state["equip"]["weapon_right"].get("is_2h"):
            self._build_sim_set_left_hand_state("equip", "weapon_left")

    def _build_sim_update_slot_icon(self, layer: str, slot_key: str):
        w = self._build_ui_slot_widgets[layer][slot_key]
        cell = self._build_state[layer][slot_key]
        lbl = w["icon_lbl"]
        try:
            slot_iid = int(cell.get("item_id") or 0)
        except (TypeError, ValueError):
            slot_iid = None
        url = _normalize_media_url(
            resolve_item_icon_url(slot_iid, cell.get("item_icon_url") or "", base_url=BASE_URL)
        )
        if url or slot_iid:
            ph = self._load_item_icon_photo(url, max_size=26, item_id=slot_iid)
            if ph:
                self._build_sim_photo_refs.append(ph)
                lbl.configure(image=ph, text="")
                return
        lbl.configure(image="", text="·")

    def _build_sim_compute_slot_price_cache(self, layer: str, sk: str, *, force_refresh: bool):
        """Calcula entrada de preço para um slot (RMT/HP conforme refino no estado)."""
        cell = self._build_state[layer][sk]
        try:
            iid_int = int(cell.get("item_id") or 0)
        except (TypeError, ValueError):
            return {"empty": True}
        if iid_int <= 0:
            return {"empty": True}
        try:
            stores, _ = get_stores_from_item_page(iid_int, "", force_refresh=force_refresh)
            want_ref = int(cell.get("refine") or 0)
            want_ref = max(0, min(20, want_ref))
            matched = filter_stores_slot(stores, want_ref, 0)
            mp = min_prices_from_stores(matched, only_qty_one=True)
            if not mp and want_ref == 0:
                # +0: se não houver linha exacta, ainda pode haver inconsistência no site — usa o menor global.
                mp = min_prices_from_stores(stores or [], only_qty_one=True)
            elif not mp:
                # Refino > 0: não misturar outras refinagens (evita mostrar preço de +0 quando pediu +10).
                mp = {}
            return {"empty": False, "mins": mp}
        except Exception as e:
            return {"empty": False, "err": str(e)}

    def _build_sim_apply_price_entry_to_slot_widgets(self, layer: str, sk: str, ent: dict):
        w = self._build_ui_slot_widgets[layer][sk]
        if ent.get("empty"):
            w["lrmt"].configure(text="RMT: —", fg=C["rmt"])
            w["lhp"].configure(text="HP: —", fg=C["hero_points"])
            return
        if ent.get("err"):
            w["lrmt"].configure(text=f"Erro: {ent['err'][:24]}", fg=C["rmt"])
            w["lhp"].configure(text="", fg=C["hero_points"])
            return
        mp = ent.get("mins") or {}
        rr = mp.get("rmt")
        hh = mp.get("hero_points")
        w["lrmt"].configure(
            text=f"RMT: {fmt_price_stores(rr) if rr is not None else '—'}",
            fg=C["rmt"],
        )
        w["lhp"].configure(
            text=f"HP: {fmt_price_stores(hh) if hh is not None else '—'}",
            fg=C["hero_points"],
        )

    def _build_sim_refresh_prices_slots(self, slots):
        """Actualiza preços só para os slots indicados (lista de (layer, slot_key))."""
        if not slots:
            return
        self._build_sim_refresh_gen += 1
        gen = self._build_sim_refresh_gen
        targets = list(slots)

        def work():
            updates = {}
            for layer, sk in targets:
                updates[(layer, sk)] = self._build_sim_compute_slot_price_cache(
                    layer, sk, force_refresh=True
                )
            if gen != self._build_sim_refresh_gen:
                return

            def apply_ui():
                if gen != self._build_sim_refresh_gen:
                    return
                for (layer, sk), ent in updates.items():
                    self._build_price_cache[(layer, sk)] = ent
                    self._build_sim_apply_price_entry_to_slot_widgets(layer, sk, ent)
                self._build_sim_recalc_totals()

            self.after(0, apply_ui)

        threading.Thread(target=work, daemon=True).start()

    def _build_sim_refresh_prices(self):
        self._build_sim_merge_entries_into_state()
        self._build_sim_sync_ui_to_state()
        for layer in ("equip", "visual"):
            for sk in self._all_build_slot_keys():
                self._build_sim_sync_row_from_state(layer, sk)
        self._build_sim_clear_slot_price_labels()
        self._build_sim_refresh_gen += 1
        gen = self._build_sim_refresh_gen

        def work():
            cache = {}
            for layer in ("equip", "visual"):
                for sk in self._all_build_slot_keys():
                    cache[(layer, sk)] = self._build_sim_compute_slot_price_cache(
                        layer, sk, force_refresh=True
                    )

            if gen != self._build_sim_refresh_gen:
                return

            def apply_ui():
                if gen != self._build_sim_refresh_gen:
                    return
                self._build_price_cache = cache
                for layer in ("equip", "visual"):
                    for sk in self._all_build_slot_keys():
                        self._build_sim_apply_price_entry_to_slot_widgets(
                            layer, sk, cache.get((layer, sk), {})
                        )
                self._build_sim_recalc_totals()

            self.after(0, apply_ui)

        threading.Thread(target=work, daemon=True).start()

    def _build_sim_recalc_totals(self):
        rmt = hp = 0.0
        for layer in ("equip", "visual"):
            for sk in self._all_build_slot_keys():
                t = self._build_price_cache.get((layer, sk), {})
                if not t or t.get("empty") or t.get("err"):
                    continue
                mp = t.get("mins") or {}
                if "rmt" in mp:
                    rmt += float(mp["rmt"])
                if "hero_points" in mp:
                    hp += float(mp["hero_points"])
        try:
            ratio = float(self._build_hp_entry.get().strip() or "30")
        except (ValueError, TypeError, tk.TclError, AttributeError):
            ratio = 30.0
        hp_equiv = hp + rmt * max(0.0, ratio)
        self._build_lbl_total_rmt.configure(text=f"RMT: {fmt_price_stores(rmt) if rmt else '0'}")
        self._build_lbl_total_hp.configure(text=f"HP (equiv.): {fmt_price_stores(hp_equiv) if hp_equiv else '0'}")

    def _build_sim_save_dialog(self):
        self._build_sim_merge_entries_into_state()
        self._build_sim_sync_ui_to_state()
        d = tk.Toplevel(self)
        d.title("Guardar build")
        d.configure(bg=C["bg"])
        d.transient(self)
        d.geometry("440x248")

        shell = tk.Frame(d, bg=C["bg"])
        shell.pack(fill="both", expand=True, padx=16, pady=16)
        overwrite_id = getattr(self, "_build_sim_selected_saved_id", None)
        if overwrite_id:
            tk.Label(
                shell,
                text="Substitui a build seleccionada na lista (mesmo id). Sem build seleccionada, cria uma nova.",
                bg=C["bg"],
                fg=C["text3"],
                font=("Segoe UI", 8),
                wraplength=400,
                justify="left",
            ).pack(anchor="w", pady=(0, 6))
        tk.Label(shell, text="Nome da build", bg=C["bg"], fg=C["text"]).pack(anchor="w")
        nm = DarkEntry(shell, width=40)
        nm.pack(fill="x", pady=(4, 12))
        found_name = None
        if overwrite_id:
            for s in (load_builds_file().get("saved") or []):
                if isinstance(s, dict) and str(s.get("id")) == str(overwrite_id):
                    found_name = str(s.get("name") or "Build")
                    break
        nm.insert(0, found_name or "Minha build")

        cfg0 = load_settings()
        cur_primary = (cfg0.get("primary_build_sim_saved_id") or "").strip()
        if overwrite_id:
            default_primary_cb = str(overwrite_id) == cur_primary
        else:
            default_primary_cb = not cur_primary
        var_make_primary = tk.BooleanVar(value=default_primary_cb)
        DarkCheckbutton(
            shell,
            text="Definir como build principal (aberta ao iniciar, se existir)",
            variable=var_make_primary,
            bg=C["bg"],
            font=("Segoe UI", 8),
        ).pack(anchor="w", fill="x", pady=(0, 8))

        def ok(oid=overwrite_id):
            self._build_sim_merge_entries_into_state()
            self._build_sim_sync_ui_to_state()
            name = nm.get().strip() or "Build"
            data = load_builds_file()
            saved = data.setdefault("saved", [])
            try:
                hpr = int(self._build_hp_entry.get().strip() or "30")
            except (ValueError, TypeError, tk.TclError, AttributeError):
                hpr = 30
            entry = None
            if oid:
                for i, s in enumerate(saved):
                    if not isinstance(s, dict):
                        continue
                    if str(s.get("id")) != str(oid):
                        continue
                    old = dict(s)
                    entry = {
                        "id": old.get("id"),
                        "name": name,
                        "saved_at": datetime.now().isoformat(),
                        "hp_per_rmt": hpr,
                        "equip": {k: dict(v) for k, v in self._build_state["equip"].items()},
                        "visual": {k: dict(v) for k, v in self._build_state["visual"].items()},
                        "alert_when_total_zeny_below": old.get("alert_when_total_zeny_below"),
                        "alert_when_total_hp_equiv_below": old.get("alert_when_total_hp_equiv_below"),
                        "notify_email": old.get("notify_email") or "",
                        "alert_total_armed": old.get("alert_total_armed", True),
                    }
                    saved[i] = entry
                    break
            if entry is None:
                entry = {
                    "id": str(uuid.uuid4()),
                    "name": name,
                    "saved_at": datetime.now().isoformat(),
                    "hp_per_rmt": hpr,
                    "equip": {k: dict(v) for k, v in self._build_state["equip"].items()},
                    "visual": {k: dict(v) for k, v in self._build_state["visual"].items()},
                    "alert_when_total_zeny_below": None,
                    "alert_when_total_hp_equiv_below": None,
                    "notify_email": "",
                    "alert_total_armed": True,
                }
                saved.append(entry)
            save_builds_file(data)
            cfg = load_settings()
            if var_make_primary.get():
                cfg["primary_build_sim_saved_id"] = str(entry.get("id") or "")
            save_settings(cfg)
            self._build_sim_last_saved_id = entry["id"]
            self._build_sim_selected_saved_id = entry.get("id")
            self._build_sim_refresh_saved_combo_list(select_id=entry["id"])
            self._build_sim_persist_last_saved_id()
            d.destroy()
            messagebox.showinfo("Guardado", f"Build «{name}» guardada.", parent=self)

        bf = tk.Frame(shell, bg=C["bg"])
        bf.pack(fill="x", pady=(12, 0))
        DarkButton(bf, text="Guardar", style="success", command=ok).pack(side="left", padx=4)
        DarkButton(bf, text="Cancelar", style="danger", command=d.destroy).pack(side="left", padx=4)

