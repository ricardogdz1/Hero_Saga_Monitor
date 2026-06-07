"""
Home — itens monitorados (colunas, drag-and-drop, preços).
Mixin usado por ``HeroSagaMonitor``.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Optional

import tkinter as tk
from tkinter import messagebox

import app_formatters
from adapters import herosaga_api
from adapters.persistence import (
    DEFAULT_MONITOR_CATEGORIES,
    save_data,
)

_normalize_media_url = herosaga_api.normalize_media_url
from app_settings import load_settings
from core.constants import BASE_URL
from item_icon_cache import read_item_icon_png_bytes, resolve_item_icon_url
from mvp_timer import mvp_catalog_matches_search
from services import monitored as monitored_service
from ui.theme import C
from ui.widgets import DarkButton, DarkEntry, ModernScrollbar, RoundedCard, ScrollableFrame

logger = logging.getLogger(__name__)

fmt_price_stores = app_formatters.fmt_price_stores


class MonitoredHomeMixin:
    """Itens monitorados na página Home (busca)."""

    def _persist_monitored_data_async(self) -> None:
        """Grava ``herosaga_monitor_data.json`` em thread (não bloqueia UI)."""
        try:
            snapshot = json.loads(json.dumps(self.data, ensure_ascii=False))
        except Exception:
            snapshot = dict(self.data)

        def _run():
            try:
                save_data(snapshot)
            except Exception:
                logger.exception("Falha ao gravar dados monitorados em segundo plano")

        threading.Thread(target=_run, name="SaveMonitoredData", daemon=True).start()

    def _mh_clear_drop_indicator(self) -> None:
        ind = getattr(self, "_mh_drag_indicator", None)
        if ind is not None:
            try:
                ind.destroy()
            except tk.TclError:
                pass
        self._mh_drag_indicator = None
        self._mh_drag_indicator_category = None

    def _mh_drop_line_screen_geometry(self, inner, cards: list, insert_index: int):
        """Rectângulo em coordenadas de ecrã para a barra de inserção (Toplevel)."""
        try:
            inner.update_idletasks()
            ix = int(inner.winfo_rootx())
            iy = int(inner.winfo_rooty())
            iw = int(inner.winfo_width())
            ih = int(inner.winfo_height())
        except tk.TclError:
            return None
        if iw < 8 or ih < 8:
            return None
        pad_x = 10
        bar_h = 6
        x = ix + pad_x
        w = max(48, iw - 2 * pad_x)
        if not cards:
            y = iy + 8
        elif insert_index < len(cards):
            try:
                target = cards[insert_index]
                y = int(target.winfo_rooty()) - bar_h // 2 - 1
            except tk.TclError:
                y = iy + 8
        else:
            try:
                last = cards[-1]
                y = int(last.winfo_rooty()) + int(last.winfo_height()) + 2
            except tk.TclError:
                y = iy + ih - bar_h - 4
        return x, y, w, bar_h

    def _mh_is_drop_indicator_widget(self, widget) -> bool:
        return bool(getattr(widget, "_mh_drop_indicator", False))

    def _mh_category_card_widgets(self, inner) -> list:
        """Cartões monitorados no ``inner`` da categoria (ignora indicador e rótulos vazios)."""
        if inner is None:
            return []
        out = []
        try:
            for ch in inner.winfo_children():
                if self._mh_is_drop_indicator_widget(ch):
                    continue
                if getattr(ch, "_mh_item_id", None) is not None:
                    out.append(ch)
        except tk.TclError:
            pass
        return out

    def _mh_get_insert_index(self, inner, y_root: int, exclude_iid: Optional[int] = None) -> int:
        """Índice de inserção na categoria segundo a posição Y do rato (exclui o card em arrasto)."""
        idx = 0
        for card in self._mh_category_card_widgets(inner):
            try:
                ci = int(getattr(card, "_mh_item_id", None))
            except (TypeError, ValueError):
                continue
            if exclude_iid is not None and ci == int(exclude_iid):
                continue
            try:
                mid_y = card.winfo_rooty() + card.winfo_height() // 2
            except tk.TclError:
                continue
            if y_root < mid_y:
                return idx
            idx += 1
        return idx

    def _mh_find_card(self, iid: int):
        try:
            want = int(iid)
        except (TypeError, ValueError):
            return None
        by_id = getattr(self, "_mh_cards_by_id", None) or {}
        hit = by_id.get(want)
        if hit is not None:
            try:
                if hit.winfo_exists():
                    return hit
            except tk.TclError:
                pass
        for inner in (getattr(self, "_mh_inners", None) or {}).values():
            for ch in self._mh_category_card_widgets(inner):
                try:
                    if int(getattr(ch, "_mh_item_id", None)) == want:
                        return ch
                except (TypeError, ValueError):
                    continue
        return None

    def _mh_card_from_widget(self, widget):
        w = widget
        while w is not None:
            if getattr(w, "_mh_item_id", None) is not None:
                return w
            try:
                w = w.master
            except (tk.TclError, AttributeError):
                break
        return None

    def _mh_create_monitored_card_at_index(
        self,
        inner,
        entry: dict,
        category: str,
        insert_index: int,
        col_min_w: int,
    ):
        """Cria um único cartão na categoria (inserção por índice; outro master)."""
        self._mh_clear_category_empty_placeholder(inner)
        others = self._mh_category_card_widgets(inner)
        insert_index = min(max(0, int(insert_index)), len(others))
        try:
            iid = int(entry["id"])
        except (TypeError, ValueError, KeyError):
            return None, None
        card, _, bind_target = self._pack_item_store_snapshot_row(
            inner,
            entry,
            self._monitored_home_photo_refs,
            wraplength=max(160, col_min_w - 36),
            layout="stack",
            id_subline=f"ID: {entry.get('id', '?')}  ·  nova janela",
            show_ws_copy=True,
            drag_handle_monitored={"iid": iid, "category": category},
            defer_icon_load=True,
            static_incomplete=monitored_service.static_incomplete(entry),
        )
        card._mh_category = str(category)
        try:
            card.pack_forget()
        except tk.TclError:
            pass
        pack_kw = dict(fill="x", pady=4)
        try:
            if insert_index < len(others):
                card.pack(before=others[insert_index], **pack_kw)
            elif others:
                card.pack(after=others[-1], **pack_kw)
            else:
                card.pack(**pack_kw)
        except tk.TclError:
            pass
        try:
            inner.update_idletasks()
        except tk.TclError:
            pass
        return card, bind_target

    def _mh_try_apply_cached_icon_for_card(self, item_id: int, card) -> None:
        if card is None:
            return
        try:
            max_sz = int(getattr(card, "_mh_icon_max", 52) or 52)
        except (TypeError, ValueError):
            max_sz = 52
        ph = self._item_icon_photo_ram.get((int(item_id), max_sz))
        if ph is None:
            url = getattr(card, "_mh_icon_url", None) or ""
            entry_url = ""
            for m in self.data.get("monitored") or []:
                try:
                    if int(m.get("id")) == int(item_id):
                        entry_url = _normalize_media_url(m.get("item_icon_url") or "")
                        break
                except (TypeError, ValueError):
                    continue
            ph = self._load_item_icon_photo(entry_url or url, max_size=max_sz, item_id=int(item_id))
        if ph is None:
            return
        self._monitored_home_photo_refs.append(ph)
        lbl = getattr(card, "_mh_icon_lbl", None)
        if lbl is not None:
            try:
                lbl.configure(image=ph, text="")
                lbl.image = ph
            except tk.TclError:
                pass

    def _mh_repack_card(self, card, inner, insert_index: int) -> None:
        """Reposiciona um cartão existente na mesma categoria (mesmo master)."""
        others = [c for c in self._mh_category_card_widgets(inner) if c is not card]
        try:
            card.pack_forget()
        except tk.TclError:
            pass
        insert_index = min(max(0, int(insert_index)), len(others))
        pack_kw = dict(fill="x", pady=4)
        try:
            if insert_index < len(others):
                card.pack(before=others[insert_index], **pack_kw)
            elif others:
                card.pack(after=others[-1], **pack_kw)
            else:
                card.pack(**pack_kw)
        except tk.TclError:
            pass

    def _mh_clear_category_empty_placeholder(self, inner) -> None:
        for ch in list(inner.winfo_children()):
            if self._mh_is_drop_indicator_widget(ch):
                continue
            if getattr(ch, "_mh_item_id", None) is not None:
                continue
            try:
                ch.destroy()
            except tk.TclError:
                pass

    def _mh_ensure_empty_category_placeholder(self, inner, cat: str) -> None:
        if self._mh_category_card_widgets(inner):
            return
        tk.Label(
            inner,
            text="(sem itens nesta categoria)",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=12)

    def _monitored_splice_category_block(self, monitored: list, category: str, ordered_entries: list) -> list:
        """Substitui o bloco de uma categoria na lista ``monitored`` mantendo o resto."""
        cat = str(category)
        new_monitored = []
        emitted = False
        for m in monitored:
            if str(m.get("category") or "Gerais") != cat:
                new_monitored.append(m)
                continue
            if not emitted:
                new_monitored.extend(ordered_entries)
                emitted = True
        if not emitted:
            new_monitored.extend(ordered_entries)
        return new_monitored

    def _mh_widget_contains_screen(self, widget, x_root: int, y_root: int) -> bool:
        try:
            x1 = int(widget.winfo_rootx())
            y1 = int(widget.winfo_rooty())
            w = int(widget.winfo_width())
            h = int(widget.winfo_height())
        except tk.TclError:
            return False
        if w < 2 or h < 2:
            return False
        return x1 <= int(x_root) < x1 + w and y1 <= int(y_root) < y1 + h

    def _mh_update_drop_indicator(self, cat: str, y_root: int, moving_iid: int) -> None:
        """Barra de inserção flutuante (Toplevel) — visível acima do scroll e do fantasma."""
        inner = (getattr(self, "_mh_inners", None) or {}).get(cat)
        if inner is None:
            self._mh_clear_drop_indicator()
            return

        cards_all = self._mh_category_card_widgets(inner)
        try:
            mid_exclude = int(moving_iid)
        except (TypeError, ValueError):
            mid_exclude = -1
        cards = [
            c
            for c in cards_all
            if int(getattr(c, "_mh_item_id", -1) or -1) != mid_exclude
        ]
        insert_index = self._mh_get_insert_index(inner, int(y_root), exclude_iid=moving_iid)
        geom = self._mh_drop_line_screen_geometry(inner, cards, insert_index)
        if geom is None:
            self._mh_clear_drop_indicator()
            return
        x, y, w, h = geom

        st = getattr(self, "_mh_drag", None) or {}
        st["_drop_cat"] = cat
        st["_drop_insert_index"] = insert_index
        self._mh_drag = st

        ind = getattr(self, "_mh_drag_indicator", None)
        if ind is None:
            try:
                ind = tk.Toplevel(self)
                ind.withdraw()
                ind.overrideredirect(True)
                ind.configure(bg="#7b68ee", cursor="arrow")
                try:
                    ind.attributes("-topmost", True)
                except tk.TclError:
                    pass
                try:
                    ind.attributes("-alpha", 0.95)
                except tk.TclError:
                    pass
                ind._mh_drop_indicator = True
                self._mh_drag_indicator = ind
            except tk.TclError:
                return

        try:
            ind.deiconify()
            ind.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
            ind.lift()
            ind.update_idletasks()
        except tk.TclError:
            self._mh_clear_drop_indicator()
            return
        self._mh_drag_indicator_category = cat

    def _mh_restore_dragged_card_visible(self, st: dict) -> None:
        """Repor cartão na coluna após cancelar arrasto (estava com pack_forget)."""
        if not st.get("_src_card_unpacked"):
            return
        try:
            iid = int(st.get("iid"))
            src = str(st.get("src") or "")
        except (TypeError, ValueError):
            return
        inner = (getattr(self, "_mh_inners", None) or {}).get(src)
        card = self._mh_find_card(iid)
        if inner is None or card is None:
            return
        ids = []
        for m in self.data.get("monitored") or []:
            if str(m.get("category") or "Gerais") == src:
                try:
                    ids.append(int(m["id"]))
                except (TypeError, ValueError):
                    continue
        try:
            idx = ids.index(iid)
        except ValueError:
            idx = len(self._mh_category_card_widgets(inner))
        self._mh_repack_card(card, inner, idx)
        st["_src_card_unpacked"] = False

    def _mh_drag_unbind_all(self) -> None:
        for seq in ("<B1-Motion>", "<ButtonRelease-1>", "<Escape>"):
            try:
                self.unbind_all(seq)
            except tk.TclError:
                pass

    def _mh_drag_cleanup_ghost(self, st: dict) -> None:
        g = st.get("ghost")
        if g is not None:
            try:
                g.destroy()
            except tk.TclError:
                pass
        st["ghost"] = None
        gw = st.get("grab_widget")
        if gw is not None:
            try:
                gw.configure(cursor="hand2")
            except tk.TclError:
                pass
        try:
            self.configure(cursor="")
        except tk.TclError:
            pass

    def _mh_drag_cancel(self, _event=None) -> None:
        st = getattr(self, "_mh_drag", None) or {}
        if not st.get("active"):
            return
        st["active"] = False
        self._mh_drag = st
        self._mh_clear_drop_indicator()
        self._mh_restore_dragged_card_visible(st)
        self._mh_drag_unbind_all()
        self._mh_drag_cleanup_ghost(st)

    def _mh_drag_begin(self, event, iid: int, category: str, display_name: str = "", row_snapshot=None):
        card_src = self._mh_card_from_widget(event.widget)
        if card_src is not None:
            category = getattr(card_src, "_mh_category", None) or category
        prev = getattr(self, "_mh_drag", None) or {}
        old_g = prev.get("ghost")
        if old_g is not None:
            try:
                old_g.destroy()
            except tk.TclError:
                pass
        self._mh_clear_drop_indicator()
        src_card = card_src or self._mh_find_card(iid)
        src_card_unpacked = False
        if src_card is not None:
            try:
                src_card.pack_forget()
                src_card_unpacked = True
            except tk.TclError:
                pass
        try:
            event.widget.configure(cursor="hand1")
        except tk.TclError:
            pass

        ghost = tk.Toplevel(self)
        ghost.overrideredirect(True)
        try:
            ghost.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            ghost.attributes("-alpha", 0.92)
        except tk.TclError:
            pass

        ghost.configure(bg=C["bg"])
        ghost_photo_refs = []
        if isinstance(row_snapshot, dict) and row_snapshot:
            entry = dict(row_snapshot)
        else:
            entry = {"id": iid, "name": (display_name or "").strip() or f"Item {iid}"}
        if entry.get("id") is None:
            entry["id"] = iid
        col_min_w, _ = monitored_service.layout_dims(load_settings())
        wrap = max(160, col_min_w - 36)
        card, _, _ = self._pack_item_store_snapshot_row(
            ghost,
            entry,
            ghost_photo_refs,
            wraplength=wrap,
            layout="stack",
            id_subline=f"ID: {entry.get('id', iid)}  ·  nova janela",
            show_ws_copy=False,
            drag_handle_monitored=None,
            card_pack_fill_x=False,
            title_wraplength=wrap,
            icon_slot_px=50,
            compact_text_column=True,
        )

        ghost.update_idletasks()
        gw = min(max(int(card.winfo_reqwidth()) + 6, 100), 520)
        gh = int(card.winfo_reqheight()) + 6
        ox = -(gw // 2)
        oy = -min(24, max(8, gh // 3))

        self._mh_drag = {
            "active": True,
            "iid": iid,
            "src": category,
            "ghost": ghost,
            "ghost_photo_refs": ghost_photo_refs,
            "grab_widget": event.widget,
            "ox": ox,
            "oy": oy,
            "ghost_w": gw,
            "ghost_h": gh,
            "_last_x_root": event.x_root,
            "_last_y_root": event.y_root,
            "_hover_cat": None,
            "_last_motion_time": 0,
            "_drop_cat": None,
            "_drop_insert_index": None,
            "_src_card_unpacked": src_card_unpacked,
        }
        try:
            self.configure(cursor="hand1")
        except tk.TclError:
            pass
        try:
            ghost.geometry(f"{gw}x{gh}+{event.x_root + ox}+{event.y_root + oy}")
        except tk.TclError:
            pass

        try:
            self._mh_update_drop_indicator(category, event.x_root, event.y_root, int(iid))
        except (TypeError, ValueError):
            pass

        self.bind_all("<B1-Motion>", self._mh_drag_motion)
        self.bind_all("<ButtonRelease-1>", self._mh_drag_release)
        self.bind_all("<Escape>", self._mh_drag_cancel)

    def _mh_drag_motion(self, event):
        st = getattr(self, "_mh_drag", None) or {}
        if not st.get("active"):
            return
        st["_last_x_root"] = event.x_root
        st["_last_y_root"] = event.y_root
        self._mh_drag = st
        try:
            now = int(event.time)
        except (TypeError, ValueError, tk.TclError):
            now = 0
        last = int(st.get("_last_motion_time") or 0)
        if last and (now - last) < 16:
            return
        st["_last_motion_time"] = now
        self._mh_drag = st
        hc = self._mh_drop_category_at_screen(event.x_root, event.y_root)
        st["_hover_cat"] = hc
        self._mh_drag = st
        iid = st.get("iid")
        g = st.get("ghost")
        if g is not None:
            try:
                ox = int(st.get("ox", 0))
                oy = int(st.get("oy", 0))
                gw = st.get("ghost_w")
                gh = st.get("ghost_h")
                if gw and gh:
                    g.geometry(f"{int(gw)}x{int(gh)}+{event.x_root + ox}+{event.y_root + oy}")
                else:
                    g.geometry(f"+{event.x_root + ox}+{event.y_root + oy}")
            except tk.TclError:
                pass
        if hc and iid is not None:
            try:
                self._mh_update_drop_indicator(hc, event.x_root, event.y_root, int(iid))
            except (TypeError, ValueError):
                self._mh_clear_drop_indicator()
        else:
            self._mh_clear_drop_indicator()
        ind = getattr(self, "_mh_drag_indicator", None)
        if ind is not None:
            try:
                ind.lift()
            except tk.TclError:
                pass

    def _mh_drag_release(self, event):
        st = getattr(self, "_mh_drag", None) or {}
        if not st.get("active"):
            return
        st["active"] = False
        self._mh_drag = st
        drop_cat = st.get("_drop_cat")
        drop_index = st.get("_drop_insert_index")
        self._mh_clear_drop_indicator()
        self._mh_drag_unbind_all()
        self._mh_drag_cleanup_ghost(st)

        try:
            lx, ly = st.get("_last_x_root"), st.get("_last_y_root")
            if lx is not None and ly is not None:
                xr, yr = int(lx), int(ly)
            elif event is not None:
                xr, yr = event.x_root, event.y_root
            else:
                xr, yr = 0, 0

            tgt = self._mh_drop_category_at_screen(xr, yr)
            if tgt is None:
                tgt = st.get("_hover_cat")

            iid = st.get("iid")
            src = st.get("src")
            if iid is None or src is None:
                return
            iid = int(iid)
            src = str(src)

            if tgt == src:
                inner = (getattr(self, "_mh_inners", None) or {}).get(src)
                if inner is not None:
                    if drop_cat == src and drop_index is not None:
                        insert_index = int(drop_index)
                    else:
                        insert_index = self._mh_get_insert_index(inner, yr, exclude_iid=iid)
                    self._reorder_monitored_in_category_at_index(iid, src, insert_index)
                return

            if tgt and tgt != src:
                ins = int(drop_index) if drop_cat == tgt and drop_index is not None else None
                self._move_monitored_item_to_category(iid, tgt, y_root=yr, insert_index=ins)
        except Exception:
            logger.exception("Erro ao concluir drag na home monitorados")
            self._mh_clear_drop_indicator()

    def _mh_drop_category_at_screen(self, x_root, y_root):
        """Categoria sob o cursor — por geometria (o fantasma topmost bloqueia winfo_containing)."""
        xr, yr = int(x_root), int(y_root)
        shells = getattr(self, "_mh_col_shells", None) or {}
        for cat, shell in shells.items():
            try:
                if shell.winfo_exists() and self._mh_widget_contains_screen(shell, xr, yr):
                    return cat
            except tk.TclError:
                continue
        inners = getattr(self, "_mh_inners", None) or {}
        for cat, inner in inners.items():
            try:
                if inner.winfo_exists() and self._mh_widget_contains_screen(inner, xr, yr):
                    return cat
            except tk.TclError:
                continue
        return None

    def _move_monitored_item_to_category(
        self,
        iid: int,
        new_cat: str,
        y_root: Optional[int] = None,
        insert_index: Optional[int] = None,
    ):
        cats = monitored_service.categories_list(self.data, default_categories=DEFAULT_MONITOR_CATEGORIES)
        if new_cat not in cats:
            return
        monitored = list(self.data.get("monitored") or [])
        item = None
        old_cat = None
        for m in monitored:
            try:
                if int(m["id"]) == int(iid):
                    item = m
                    old_cat = str(m.get("category") or "Gerais")
                    break
            except (TypeError, ValueError):
                continue
        if item is None:
            return

        inner_tgt = (getattr(self, "_mh_inners", None) or {}).get(new_cat)
        if insert_index is not None:
            insert_index = int(insert_index)
        elif inner_tgt is not None and y_root is not None:
            insert_index = self._mh_get_insert_index(inner_tgt, int(y_root), exclude_iid=iid)
        else:
            insert_index = len(
                [m for m in monitored if str(m.get("category") or "Gerais") == new_cat and int(m["id"]) != int(iid)]
            )

        rest = [m for m in monitored if int(m["id"]) != int(iid)]
        item2 = dict(item)
        item2["category"] = new_cat

        ids = []
        for m in rest:
            if str(m.get("category") or "Gerais") == new_cat:
                try:
                    ids.append(int(m["id"]))
                except (TypeError, ValueError):
                    continue
        insert_index = min(max(0, int(insert_index)), len(ids))
        ids.insert(insert_index, int(iid))

        by_id = {}
        for m in monitored:
            try:
                pid = int(m["id"])
            except (TypeError, ValueError):
                continue
            by_id[pid] = item2 if pid == int(iid) else m
        new_cat_entries = [by_id[x] for x in ids if x in by_id]

        self.data["monitored"] = monitored_service.splice_category_block(rest, new_cat, new_cat_entries)

        if inner_tgt is None:
            self._persist_monitored_data_async()
            return

        old_card = self._mh_find_card(iid)
        if old_card is not None:
            try:
                old_card.destroy()
            except tk.TclError:
                pass
        self._mh_cards_by_id.pop(int(iid), None)

        if old_cat and old_cat != new_cat:
            src_inner = (getattr(self, "_mh_inners", None) or {}).get(old_cat)
            if src_inner is not None and not self._mh_category_card_widgets(src_inner):
                self._mh_ensure_empty_category_placeholder(src_inner, old_cat)

        col_min_w, _ = monitored_service.layout_dims(load_settings())
        new_card, bind_target = self._mh_create_monitored_card_at_index(
            inner_tgt, item2, new_cat, insert_index, col_min_w
        )
        if new_card is None:
            logger.warning("Drag: falha ao recriar cartão %s em «%s»", iid, new_cat)
            self._persist_monitored_data_async()
            return

        self._mh_cards_by_id[int(iid)] = new_card
        self._bind_click_open_item_detail(bind_target, int(iid), str(item2.get("name", "") or ""))
        self._mh_try_apply_cached_icon_for_card(int(iid), new_card)
        self._persist_monitored_data_async()

    def _reorder_monitored_in_category_at_index(self, iid_move: int, category: str, insert_index: int):
        """Reordena um item na mesma categoria (dados + só o cartão movido na UI)."""
        monitored = list(self.data.get("monitored") or [])
        cat = str(category)
        ids = []
        for m in monitored:
            if str(m.get("category") or "Gerais") != cat:
                continue
            try:
                ids.append(int(m["id"]))
            except (TypeError, ValueError):
                continue
        if int(iid_move) not in ids:
            return
        ids_wo = [x for x in ids if x != int(iid_move)]
        insert_index = min(max(0, int(insert_index)), len(ids_wo))
        ids_wo.insert(insert_index, int(iid_move))

        by_id = {}
        for m in monitored:
            if str(m.get("category") or "Gerais") != cat:
                continue
            try:
                pid = int(m["id"])
            except (TypeError, ValueError):
                continue
            if pid not in by_id:
                by_id[pid] = m
        new_cat_entries = [by_id[x] for x in ids_wo if x in by_id]

        self.data["monitored"] = monitored_service.splice_category_block(monitored, cat, new_cat_entries)
        self._persist_monitored_data_async()

        card = self._mh_find_card(iid_move)
        inner = (getattr(self, "_mh_inners", None) or {}).get(cat)
        if card is not None and inner is not None:
            self._mh_repack_card(card, inner, insert_index)
            try:
                inner.update_idletasks()
            except tk.TclError:
                pass
        else:
            logger.warning("Drag: cartão %s não encontrado na UI (sem rebuild)", iid_move)

    def _reorder_monitored_in_category(self, iid_move: int, target_iid: int, category: str, insert_after: bool):
        """Compatibilidade: converte alvo relativo em índice e delega."""
        monitored = list(self.data.get("monitored") or [])
        cat = str(category)
        ids = []
        for m in monitored:
            if str(m.get("category") or "Gerais") != cat:
                continue
            try:
                ids.append(int(m["id"]))
            except (TypeError, ValueError):
                continue
        if int(iid_move) not in ids or int(target_iid) not in ids:
            return
        ids_wo = [x for x in ids if x != int(iid_move)]
        try:
            ti = ids_wo.index(int(target_iid))
        except ValueError:
            return
        ins = ti + (1 if insert_after else 0)
        self._reorder_monitored_in_category_at_index(iid_move, category, ins)

    def _prompt_add_monitor_category(self):
        cats = monitored_service.categories_list(self.data, default_categories=DEFAULT_MONITOR_CATEGORIES)
        d = tk.Toplevel(self)
        d.title("Nova categoria")
        d.configure(bg=C["bg"])
        d.transient(self)
        d.resizable(False, False)
        shell = RoundedCard(d, radius=18, margin=14, fill_key="card")
        shell.pack(fill="both", expand=True, padx=10, pady=10)
        root = shell.inner
        tk.Label(
            root,
            text="Nome da categoria:",
            bg=C["card"],
            fg=C["text"],
            font=("Segoe UI", 10),
        ).pack(padx=18, pady=(16, 6), anchor="w")
        ent = DarkEntry(root, width=32)
        ent.pack(padx=18, fill="x")

        def add():
            name = ent.get().strip()
            if not name:
                messagebox.showwarning("Categoria", "Digite um nome.", parent=d)
                return
            if name in cats:
                messagebox.showwarning("Categoria", "Já existe uma categoria com esse nome.", parent=d)
                return
            self.data.setdefault("monitor_categories", []).append(name)
            save_data(self.data)
            d.destroy()
            self._render_monitored_home()

        bf = tk.Frame(root, bg=C["card"])
        bf.pack(fill="x", padx=18, pady=(8, 16))
        DarkButton(bf, text="Adicionar", style="success", command=add).pack(side="left", padx=(0, 8))
        DarkButton(bf, text="Cancelar", style="ghost", command=d.destroy).pack(side="left")

    def _prompt_remove_monitor_category(self):
        cats = [c for c in monitored_service.categories_list(self.data, default_categories=DEFAULT_MONITOR_CATEGORIES) if c != "Gerais"]
        if not cats:
            messagebox.showinfo(
                "Categorias",
                "Não há categorias removíveis. «Gerais» fica sempre disponível.",
            )
            return
        d = tk.Toplevel(self)
        d.title("Remover categoria")
        d.configure(bg=C["bg"])
        d.transient(self)
        d.resizable(False, False)
        shell = RoundedCard(d, radius=18, margin=14, fill_key="card")
        shell.pack(fill="both", expand=True, padx=10, pady=10)
        root = shell.inner
        tk.Label(
            root,
            text="Escolha a categoria a remover.\nOs itens vão para «Gerais».",
            bg=C["card"],
            fg=C["text3"],
            font=("Segoe UI", 9),
            justify="left",
        ).pack(padx=18, pady=(14, 8), anchor="w")
        lb = tk.Listbox(
            root,
            bg=C["bg3"],
            fg=C["text2"],
            selectbackground=C["border2"],
            height=min(10, len(cats)),
            font=("Segoe UI", 10),
        )
        lb.pack(padx=18, fill="x")
        for c in cats:
            lb.insert("end", c)
        lb.selection_set(0)

        def remove():
            sel = lb.curselection()
            if not sel:
                messagebox.showwarning("Categoria", "Seleccione uma categoria.", parent=d)
                return
            rm = lb.get(sel[0])
            if not messagebox.askyesno(
                "Confirmar",
                f"Remover a categoria «{rm}»?\nOs itens nela passam para «Gerais».",
                parent=d,
            ):
                return
            for m in self.data.get("monitored") or []:
                if str(m.get("category", "")) == rm:
                    m["category"] = "Gerais"
            self.data["monitor_categories"] = [c for c in self.data["monitor_categories"] if c != rm]
            if "Gerais" not in self.data["monitor_categories"]:
                self.data["monitor_categories"].insert(0, "Gerais")
            save_data(self.data)
            d.destroy()
            self._render_monitored_home()

        bf = tk.Frame(root, bg=C["card"])
        bf.pack(fill="x", padx=18, pady=(10, 16))
        DarkButton(bf, text="Remover", style="danger", command=remove).pack(side="left", padx=(0, 8))
        DarkButton(bf, text="Cancelar", style="ghost", command=d.destroy).pack(side="left")

    def _render_monitored_home(self):
        rid = getattr(self, "_mh_reflow_after_id", None)
        if rid is not None:
            try:
                self.after_cancel(rid)
            except tk.TclError:
                pass
        self._mh_reflow_after_id = None
        for w in self.mh_body.winfo_children():
            w.destroy()
        self._monitored_home_photo_refs = []
        self._mh_inners = {}
        self._mh_col_shells = {}
        self._mh_cards_by_id = {}

        monitored_all = self.data.get("monitored") or []
        mh_q = self._list_search_query("mh")
        monitored = monitored_all
        if mh_q:
            monitored = [m for m in monitored_all if monitored_service.item_matches_search(m, mh_q, mvp_catalog_matches_search_fn=mvp_catalog_matches_search)]
        cats = monitored_service.categories_list(self.data, default_categories=DEFAULT_MONITOR_CATEGORIES)
        col_min_w, mh_vis_cols = monitored_service.layout_dims(load_settings())

        tool = tk.Frame(self.mh_body, bg=C["bg"])
        tool.pack(fill="x", pady=(0, 8))
        prices_fr = tk.Frame(tool, bg=C["bg"])
        prices_fr.pack(side="left", anchor="w")
        btn_state = "disabled" if getattr(self, "_mh_prices_refreshing", False) else "normal"
        btn_text = "Atualizando…" if getattr(self, "_mh_prices_refreshing", False) else "🔄 Atualizar Preços"
        self._mh_prices_btn = DarkButton(
            prices_fr,
            text=btn_text,
            style="mh_refresh",
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=6,
            command=self._mh_on_refresh_prices_click,
        )
        self._mh_prices_btn.pack(side="left")
        try:
            self._mh_prices_btn.configure(state=btn_state)
        except tk.TclError:
            pass
        self._mh_prices_status_lbl = tk.Label(
            prices_fr,
            text=monitored_service.last_prices_update_label(monitored),
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 8),
        )
        self._mh_prices_status_lbl.pack(side="left", padx=(10, 0))
        tk.Label(
            tool,
            text="Várias categorias ao mesmo tempo — arraste pelo «⠿» para mudar de coluna "
            "ou para cima/baixo na mesma coluna. Barra inferior se precisar de deslocar horizontalmente.",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 8),
        ).pack(side="left", anchor="w", padx=(16, 0))
        DarkButton(
            tool,
            text="+ Categoria",
            style="ghost",
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=4,
            command=self._prompt_add_monitor_category,
        ).pack(side="right", padx=(4, 0))
        DarkButton(
            tool,
            text="− Categoria",
            style="ghost",
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=4,
            command=self._prompt_remove_monitor_category,
        ).pack(side="right")

        if not monitored:
            if monitored_all and mh_q:
                empty_msg = f"Nenhum item corresponde a «{mh_q}»."
            else:
                empty_msg = "Nenhum item monitorado. Abra um item e toque em « + Monitorar »."
            tk.Label(
                self.mh_body,
                text=empty_msg,
                bg=C["bg"],
                fg=C["text3"],
                font=("Segoe UI", 9),
                justify="left",
            ).pack(anchor="w", pady=12)
            self._mh_inners = {}
            self._mh_col_shells = {}
            self._list_search_update_hint("mh", 0, len(monitored_all))
            return

        pan_wrap = tk.Frame(self.mh_body, bg=C["bg"])
        pan_wrap.pack(fill="both", expand=True)

        canvas = tk.Canvas(pan_wrap, bg=C["bg"], highlightthickness=0)
        hsb = ModernScrollbar(pan_wrap, canvas.xview, orient="horizontal", bar_width=13, bg=C["bg"])
        canvas.configure(xscrollcommand=hsb.set)
        canvas.pack(side="top", fill="both", expand=True)

        col_host = tk.Frame(canvas, bg=C["bg"])
        win_c = canvas.create_window((0, 0), anchor="nw", window=col_host)
        self._mh_reflow_after_id = None
        # Colunas recriadas: força o próximo reflow a aplicar a largura nelas.
        self._mh_last_width_sig = None

        for cat in cats:
            col_rim = tk.Frame(col_host, bg=C["column_rim"])
            col_rim.pack(side="left", fill="y", expand=False, padx=(6, 6), pady=(4, 10))
            col_face = tk.Frame(col_rim, bg=C["column_face"])
            col_face.pack(fill="both", expand=True, padx=2, pady=2)
            col_shell = tk.Frame(
                col_face,
                bg=C["column_face"],
                width=col_min_w,
            )
            col_shell.pack(fill="both", expand=True)
            col_shell.pack_propagate(False)
            col_shell._mh_category = cat
            col_face._mh_category = cat
            col_rim._mh_category = cat
            col_rim._mh_col_shell = col_shell

            hdr_wrap = tk.Frame(col_shell, bg=C["column_hdr"])
            hdr_wrap.pack(fill="x", padx=(10, 10), pady=(10, 6))
            hdr = tk.Label(
                hdr_wrap,
                text=cat,
                bg=C["column_hdr"],
                fg=C["column_hdr_fg"],
                font=("Segoe UI", 10, "bold"),
                anchor="w",
            )
            hdr.pack(fill="x", padx=2, pady=4)
            hdr._mh_category = cat
            hdr_wrap._mh_category = cat

            sf = ScrollableFrame(col_shell)
            sf.pack(fill="both", expand=True)
            sf._mh_category = cat
            sf.inner._mh_category = cat
            inner = sf.inner
            self._mh_inners[cat] = inner
            self._mh_col_shells[cat] = col_shell

            items_here = [m for m in monitored if (m.get("category") or "Gerais") == cat]
            if not items_here:
                tk.Label(
                    inner,
                    text="(sem itens nesta categoria)",
                    bg=C["bg"],
                    fg=C["text3"],
                    font=("Segoe UI", 9),
                ).pack(anchor="w", pady=12)
            else:
                for m in items_here:
                    try:
                        iid = int(m["id"])
                    except (TypeError, ValueError):
                        continue
                    card, _, bind_target = self._pack_item_store_snapshot_row(
                        inner,
                        m,
                        self._monitored_home_photo_refs,
                        wraplength=max(160, col_min_w - 36),
                        layout="stack",
                        id_subline=f"ID: {m.get('id', '?')}  ·  nova janela",
                        show_ws_copy=True,
                        drag_handle_monitored={"iid": iid, "category": cat},
                        defer_icon_load=True,
                        static_incomplete=monitored_service.static_incomplete(m),
                    )
                    self._mh_cards_by_id[iid] = card
                    self._bind_click_open_item_detail(
                        bind_target, iid, str(m.get("name", "") or "")
                    )

        def _reflow_mh_columns_sched(_event=None):
            # Debounce largo: durante um arraste contínuo os eventos chegam a cada
            # poucos ms, então o reflow caro só roda quando o utilizador pausa/solta
            # o rato — evita o «piscar» de remontar os cards várias vezes seguidas.
            if self._mh_reflow_after_id is not None:
                try:
                    self.after_cancel(self._mh_reflow_after_id)
                except tk.TclError:
                    pass
            self._mh_reflow_after_id = self.after(160, _reflow_mh_columns_do)

        def _reflow_mh_columns_do():
            self._mh_reflow_after_id = None
            col_min_w, mh_vis_cols = monitored_service.layout_dims(load_settings())
            try:
                cw_raw = int(canvas.winfo_width())
                ch_raw = int(canvas.winfo_height())
            except tk.TclError:
                return
            if cw_raw < 32 or ch_raw < 64:
                return
            cw = cw_raw
            ch = ch_raw
            try:
                px0 = float(canvas.xview()[0])
            except tk.TclError:
                px0 = 0.0

            n = max(1, len(cats))
            # Largura «natural» da janela: divide pelo maior entre nº de categorias e a
            # meta — assim a largura mínima definida nas Configurações afecta o resultado
            # mesmo com poucas categorias (antes cw//meta sozinha ignorava col_min na
            # maior parte dos casos).
            eff = max(n, mh_vis_cols, 1)
            col_fit = max(1, cw) // eff
            col_w = max(col_min_w, col_fit)
            total_w = n * col_w
            # Reconfigurar a largura de todas as colunas + update_idletasks força um
            # relayout síncrono caro. Só fazemos quando a largura realmente muda
            # (resize horizontal); resize vertical/movimento não dispara este custo.
            width_sig = (col_w, total_w, n)
            if width_sig != getattr(self, "_mh_last_width_sig", None):
                self._mh_last_width_sig = width_sig
                for chf in col_host.winfo_children():
                    try:
                        chf.configure(width=col_w)
                        cs = getattr(chf, "_mh_col_shell", None)
                        if cs is not None:
                            inner_w = max(col_min_w, col_w - 4)
                            cs.configure(width=inner_w)
                    except tk.TclError:
                        pass
            # Sem update_idletasks()/bbox: forçar layout síncrono aqui era o que fazia
            # a grelha «piscar». O Tk aplica as novas larguras numa única repintura no
            # próximo idle. A scrollregion é calculada direto (largura conhecida; altura
            # pela altura pedida do conteúdo).
            canvas.itemconfigure(win_c, width=total_w, height=ch)
            try:
                content_h = max(ch, int(col_host.winfo_reqheight()))
            except tk.TclError:
                content_h = ch
            canvas.configure(scrollregion=(0, 0, total_w, content_h))
            need_scroll = total_w > (cw + 8)
            try:
                hsb_mapped = hsb.winfo_ismapped()
            except tk.TclError:
                hsb_mapped = False
            if need_scroll:
                if not hsb_mapped:
                    hsb.pack(side="bottom", fill="x")
                try:
                    canvas.xview_moveto(max(0.0, min(px0, 1.0)))
                except tk.TclError:
                    pass
            else:
                if hsb_mapped:
                    hsb.pack_forget()
                try:
                    canvas.xview_moveto(0)
                except tk.TclError:
                    pass

        canvas.bind("<Configure>", _reflow_mh_columns_sched)
        pan_wrap.bind("<Configure>", _reflow_mh_columns_sched)
        self.after_idle(_reflow_mh_columns_sched)
        self.after(250, _reflow_mh_columns_sched)

        def _mh_wheel_x(event):
            try:
                d = int(getattr(event, "delta", 0) or 0)
            except (TypeError, ValueError):
                d = 0
            if d and (getattr(event, "state", 0) & 0x0001):
                canvas.xview_scroll(int(-1 * (d / 120)), "units")
                return "break"
            return None

        canvas.bind("<MouseWheel>", _mh_wheel_x)
        hsb.bind("<MouseWheel>", _mh_wheel_x)

        try:
            if self.current_page.get() == "busca":
                self.after_idle(self._mh_start_icon_loader)
        except (tk.TclError, AttributeError):
            pass
        self._list_search_update_hint("mh", len(monitored), len(monitored_all))

    def _mh_on_refresh_prices_click(self) -> None:
        if getattr(self, "_mh_prices_refreshing", False):
            return
        self._mh_prices_refreshing = True
        btn = getattr(self, "_mh_prices_btn", None)
        if btn is not None:
            try:
                btn.configure(state="disabled", text="Atualizando…")
            except tk.TclError:
                pass
        self._monitored_home_refresh_gen += 1
        gen = self._monitored_home_refresh_gen
        threading.Thread(
            target=lambda g=gen: self._refresh_monitored_home_prices_worker(g),
            name="MhRefreshPrices",
            daemon=True,
        ).start()

    def _mh_start_icon_loader(self) -> None:
        self._mh_icon_load_gen += 1
        gen = self._mh_icon_load_gen
        jobs = []
        for m in self.data.get("monitored") or []:
            try:
                iid = int(m["id"])
            except (TypeError, ValueError):
                continue
            url = _normalize_media_url(
                resolve_item_icon_url(iid, m.get("item_icon_url") or "", base_url=BASE_URL)
            )
            jobs.append((iid, url))
        if not jobs:
            return
        threading.Thread(
            target=lambda g=gen, j=jobs: self._mh_icon_loader_worker(g, j),
            name="MhIconLoader",
            daemon=True,
        ).start()

    def _mh_icon_loader_worker(self, gen: int, jobs: list) -> None:
        for iid, url in jobs:
            if gen != getattr(self, "_mh_icon_load_gen", 0):
                return
            raw = read_item_icon_png_bytes(
                iid, url, self._fetch_icon_url_bytes, base_url=BASE_URL
            )
            if gen != getattr(self, "_mh_icon_load_gen", 0):
                return
            self.after(0, lambda mid=iid, data=raw, g=gen: self._mh_apply_card_icon(mid, data, g))

    def _mh_apply_card_icon(self, item_id: int, raw: Optional[bytes], gen: int) -> None:
        if gen != getattr(self, "_mh_icon_load_gen", 0):
            return
        if self.current_page.get() != "busca":
            return
        card = self._mh_find_card(item_id)
        if card is None:
            return
        try:
            max_sz = int(getattr(card, "_mh_icon_max", 52) or 52)
        except (TypeError, ValueError):
            max_sz = 52
        ph = self._photoimage_from_icon_bytes(raw, max_sz) if raw else None
        if ph is None:
            return
        self._monitored_home_photo_refs.append(ph)
        try:
            key = (int(item_id), int(max_sz))
            self._item_icon_photo_ram[key] = ph
        except (TypeError, ValueError):
            pass
        lbl = getattr(card, "_mh_icon_lbl", None)
        if lbl is not None:
            try:
                lbl.configure(image=ph, text="")
                lbl.image = ph
            except tk.TclError:
                pass

    def _mh_update_card_prices_ui(self, item_id: int, gen: int) -> None:
        if gen != self._monitored_home_refresh_gen:
            return
        if self.current_page.get() != "busca":
            return
        card = self._mh_find_card(item_id)
        if card is None:
            return
        lbl = getattr(card, "_mh_price_lbl", None)
        if lbl is None:
            return
        for m in self.data.get("monitored") or []:
            try:
                if int(m["id"]) == int(item_id):
                    try:
                        lbl.configure(text=monitored_service.format_home_min_prices(m, fmt_price_stores_fn=fmt_price_stores))
                    except tk.TclError:
                        pass
                    break
            except (TypeError, ValueError):
                continue

    def _mh_finish_prices_refresh(self, gen: int) -> None:
        if gen != self._monitored_home_refresh_gen:
            return
        self._mh_prices_refreshing = False
        btn = getattr(self, "_mh_prices_btn", None)
        if btn is not None:
            try:
                btn.configure(state="normal", text="🔄 Atualizar Preços")
            except tk.TclError:
                pass
        lbl = getattr(self, "_mh_prices_status_lbl", None)
        if lbl is not None:
            try:
                lbl.configure(text=monitored_service.last_prices_update_label(self.data.get("monitored") or []))
            except tk.TclError:
                pass

    def _refresh_monitored_home_prices_worker(self, gen: int):
        """Actualiza preços (só quando o utilizador pede); cada item actualiza o cartão na UI."""
        try:
            changed = False
            for m in list(self.data.get("monitored") or []):
                if gen != self._monitored_home_refresh_gen:
                    return
                iid = m.get("id")
                name = str(m.get("name") or "")
                if not iid:
                    continue
                try:
                    iid_int = int(iid)
                except (TypeError, ValueError):
                    continue
                try:
                    stores, meta = self._fetch_item_stores(
                        iid_int, name, force_refresh=True
                    )
                except Exception as e:
                    logger.warning("Home monitor refresh %s: %s", iid, e)
                    continue
                patch = {
                    "min_prices": monitored_service.sale_min_prices_from_stores(stores),
                    "home_prices_updated_at": datetime.now().isoformat(),
                }
                if meta.get("item_icon_url") and not m.get("item_icon_url"):
                    patch["item_icon_url"] = _normalize_media_url(meta["item_icon_url"])
                m.update(patch)
                changed = True
                self.after(0, lambda mid=iid_int, g=gen: self._mh_update_card_prices_ui(mid, g))
                if patch.get("item_icon_url"):
                    url = patch["item_icon_url"]
                    self.after(
                        0,
                        lambda mid=iid_int, u=url, g=gen: self._mh_fetch_icon_after_price(mid, u, g),
                    )
            if changed and gen == self._monitored_home_refresh_gen:
                self._persist_monitored_data_async()
            self.after(0, lambda g=gen: self._after_monitored_prices_refresh(g))
        except Exception as e:
            logger.exception("Refresh monitorados home: %s", e)
            self.after(0, lambda g=gen: self._mh_finish_prices_refresh(g))

    def _mh_fetch_icon_after_price(self, item_id: int, url: str, gen: int) -> None:
        if gen != self._monitored_home_refresh_gen:
            return

        def _work():
            raw = read_item_icon_png_bytes(
                item_id, url, self._fetch_icon_url_bytes, base_url=BASE_URL
            )
            self.after(0, lambda: self._mh_apply_card_icon(item_id, raw, getattr(self, "_mh_icon_load_gen", 0)))

        threading.Thread(target=_work, daemon=True).start()

    def _after_monitored_prices_refresh(self, gen: int):
        if gen != self._monitored_home_refresh_gen:
            return
        pg = self.current_page.get()
        if pg == "busca":
            self._mh_finish_prices_refresh(gen)
        elif pg == "monitor":
            self._render_monitor()

