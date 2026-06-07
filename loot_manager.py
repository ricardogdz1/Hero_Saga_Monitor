from __future__ import annotations

import copy
import json
import logging
import os
import threading
import tkinter as tk
from dataclasses import asdict, dataclass, field
from tkinter import messagebox, ttk
from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin

import cloudscraper
import requests
from PIL import Image, ImageTk

from app_settings import load_settings
from divine_pride_api import fetch_item
from item_icon_cache import item_icon_disk_path, read_item_icon_png_bytes

logger = logging.getLogger(__name__)

BASE_URL = "https://herosaga.com.br"
LOOT_FILE = os.path.join(os.path.expanduser("~"), "herosaga_loot_groups.json")
_DEFAULT_GROUP_RANGE = range(1, 6)
_MAX_ITEMS_PER_GROUP = 10
_MAX_GROUP_NUMBER = 9


def _normalize_media_url(url: str) -> str:
    u = str(url or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return urljoin(BASE_URL + "/", u[1:])
    return u


def _default_icon_url(item_id: int) -> str:
    return f"{BASE_URL}/?module=image&action=processicon&id={int(item_id)}"


@dataclass
class LootItem:
    id: int
    name: str
    type: str = ""
    icon_url: str = ""
    npc_sell_price: int = 0


@dataclass
class LootGroup:
    number: int
    name: str
    autoload: bool
    items: List[LootItem] = field(default_factory=list)


class LootManager:
    def __init__(self, file_path: str = LOOT_FILE):
        self.file_path = file_path
        self.groups: Dict[int, LootGroup] = {}
        self.load_from_file()

    def _default_groups(self) -> Dict[int, LootGroup]:
        out: Dict[int, LootGroup] = {}
        for n in _DEFAULT_GROUP_RANGE:
            out[n] = LootGroup(number=n, name=f"Grupo {n}", autoload=False, items=[])
        return out

    def _ensure_consistency(self) -> None:
        if not self.groups:
            self.groups = self._default_groups()
        for n in _DEFAULT_GROUP_RANGE:
            if n not in self.groups:
                self.groups[n] = LootGroup(number=n, name=f"Grupo {n}", autoload=False, items=[])
        for n, grp in list(self.groups.items()):
            if not isinstance(grp, LootGroup):
                continue
            dedup: Dict[int, LootItem] = {}
            for it in grp.items:
                try:
                    iid = int(it.id)
                except (TypeError, ValueError):
                    continue
                if iid not in dedup:
                    dedup[iid] = LootItem(
                        id=iid,
                        name=str(it.name or f"Item {iid}").strip() or f"Item {iid}",
                        type=str(it.type or "").strip(),
                        icon_url=str(getattr(it, "icon_url", "") or "").strip(),
                        npc_sell_price=int(getattr(it, "npc_sell_price", 0) or 0),
                    )
            grp.items = list(dedup.values())[:_MAX_ITEMS_PER_GROUP]
        autoloaded = [g for g in self.groups.values() if g.autoload]
        if len(autoloaded) > 1:
            keep = min(autoloaded, key=lambda g: g.number).number
            for g in autoloaded:
                g.autoload = g.number == keep

    def load_from_file(self) -> None:
        self.groups = self._default_groups()
        if not os.path.isfile(self.file_path):
            return
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as ex:
            logger.warning("LootManager: arquivo inválido %s: %s", self.file_path, ex)
            self.groups = self._default_groups()
            return

        raw_groups = payload.get("groups") if isinstance(payload, dict) else None
        if not isinstance(raw_groups, dict):
            self.groups = self._default_groups()
            return

        parsed: Dict[int, LootGroup] = {}
        for k, data in raw_groups.items():
            try:
                n = int(k)
            except (TypeError, ValueError):
                continue
            if n < 1 or n > _MAX_GROUP_NUMBER or not isinstance(data, dict):
                continue
            items_out: List[LootItem] = []
            for raw in data.get("items") or []:
                if not isinstance(raw, dict):
                    continue
                try:
                    iid = int(raw.get("id"))
                except (TypeError, ValueError):
                    continue
                items_out.append(
                    LootItem(
                        id=iid,
                        name=str(raw.get("name") or f"Item {iid}").strip() or f"Item {iid}",
                        type=str(raw.get("type") or "").strip(),
                        icon_url=str(raw.get("icon_url") or "").strip(),
                        npc_sell_price=int(raw.get("npc_sell_price") or 0),
                    )
                )
            parsed[n] = LootGroup(
                number=n,
                name=str(data.get("name") or f"Grupo {n}").strip() or f"Grupo {n}",
                autoload=bool(data.get("autoload")),
                items=items_out,
            )
        if parsed:
            self.groups = parsed
        self._ensure_consistency()

    def save_to_file(self) -> None:
        self._ensure_consistency()
        payload = {"groups": {}}
        for n in sorted(self.groups):
            g = self.groups[n]
            payload["groups"][str(n)] = {
                "name": g.name,
                "autoload": bool(g.autoload),
                "items": [asdict(i) for i in g.items],
            }
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except OSError as ex:
            logger.warning("LootManager: falha ao gravar %s: %s", self.file_path, ex)

    def get_group(self, group_number: int) -> LootGroup:
        n = int(group_number)
        if n not in self.groups:
            self.groups[n] = LootGroup(number=n, name=f"Grupo {n}", autoload=False, items=[])
        return self.groups[n]

    def add_item(self, group_number: int, item: LootItem) -> bool:
        grp = self.get_group(group_number)
        iid = int(item.id)
        if any(int(it.id) == iid for it in grp.items):
            return False
        if len(grp.items) >= _MAX_ITEMS_PER_GROUP:
            return False
        grp.items.append(item)
        return True

    def remove_item(self, group_number: int, item_id: int) -> None:
        grp = self.get_group(group_number)
        iid = int(item_id)
        grp.items = [x for x in grp.items if int(x.id) != iid]

    def reorder_items(self, group_number: int, new_order: List[int]) -> None:
        grp = self.get_group(group_number)
        by_id = {int(it.id): it for it in grp.items}
        ordered: List[LootItem] = []
        seen = set()
        for iid in new_order:
            key = int(iid)
            if key in seen or key not in by_id:
                continue
            ordered.append(by_id[key])
            seen.add(key)
        for it in grp.items:
            key = int(it.id)
            if key not in seen:
                ordered.append(it)
                seen.add(key)
        grp.items = ordered[:_MAX_ITEMS_PER_GROUP]

    def set_group_name(self, group_number: int, name: str) -> None:
        grp = self.get_group(group_number)
        clean = str(name or "").strip()
        grp.name = clean or f"Grupo {grp.number}"

    def set_autoload(self, group_number: int, active: bool) -> None:
        target = int(group_number)
        if active:
            for n, grp in self.groups.items():
                grp.autoload = n == target
        else:
            self.get_group(target).autoload = False

    def cmd_save(self, group_number: int) -> str:
        grp = self.get_group(group_number)
        ids = " ".join(str(int(it.id)) for it in grp.items)
        return f"@alootid2 save {int(group_number)} {ids}".rstrip()

    def cmd_load(self, group_number: int) -> str:
        return f"@alootid2 load {int(group_number)}"

    def cmd_add(self, group_number: int, item_id: int) -> str:
        return f"@alootid2 add {int(group_number)} {int(item_id)}"

    def cmd_remove(self, group_number: int, item_id: int) -> str:
        return f"@alootid2 remove {int(group_number)} {int(item_id)}"

    def cmd_clear(self, group_number: int) -> str:
        return f"@alootid2 clear {int(group_number)}"

    def cmd_set_name(self, group_number: int) -> str:
        grp = self.get_group(group_number)
        return f"@alootid2 set {int(group_number)} name {grp.name}".rstrip()

    def cmd_set_autoload(self, group_number: int, value: int) -> str:
        return f"@alootid2 set {int(group_number)} autoload {1 if int(value) else 0}"

    def ensure_icon_cached(self, item_id: int, icon_url: str, fetcher: Callable[[str], Optional[bytes]]) -> str:
        try:
            iid = int(item_id)
        except (TypeError, ValueError):
            return ""
        norm_url = _normalize_media_url(icon_url or "") or _default_icon_url(iid)
        read_item_icon_png_bytes(iid, norm_url, fetcher, base_url=BASE_URL)
        path = item_icon_disk_path(iid)
        return path if os.path.isfile(path) else ""


def _item_type_from_dp(data: dict) -> str:
    for key in ("itemType", "type", "Type", "Loc"):
        val = data.get(key)
        if val is None:
            continue
        s = str(val).strip()
        if s:
            return s
    return ""


def _item_name_from_dp(data: dict, fallback_id: int) -> str:
    for key in ("name", "Name", "AegisName", "visibleName"):
        v = data.get(key)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return f"Item {int(fallback_id)}"


def _item_icon_from_dp(data: dict) -> str:
    for key in ("icon", "Icon", "image", "Image", "itemIconUrl", "iconUrl", "item_icon_url"):
        v = data.get(key)
        if not v:
            continue
        return str(v).strip()
    return ""


def _item_npc_sell_from_dp(data: dict) -> int:
    sell_candidates = (
        "sellToNpc",
        "SellToNpc",
        "sell_price",
        "sellPrice",
        "sell",
        "sellZeny",
        "npcSellPrice",
    )
    for key in sell_candidates:
        val = data.get(key)
        try:
            iv = int(float(val))
        except (TypeError, ValueError):
            continue
        if iv >= 0:
            return iv
    # Divine Pride costuma expor ``price`` (preço de compra no NPC);
    # no cliente RO, venda ao NPC normalmente é metade.
    val = data.get("price")
    try:
        iv = int(float(val))
        if iv > 0:
            return max(1, iv // 2)
    except (TypeError, ValueError):
        pass
    return 0


def search_item(query: str) -> List[dict]:
    q = str(query or "").strip()
    if not q:
        return []

    scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "desktop": True})
    cfg = load_settings()
    api_key = (cfg.get("divine_pride_api_key") or "").strip() or None
    dp_server = (cfg.get("divine_pride_server") or "").strip() or None

    out: List[dict] = []
    if q.isdigit():
        item_id = int(q)
        try:
            dp = fetch_item(item_id, api_key=api_key, server=dp_server)
            out.append(
                {
                    "id": item_id,
                    "name": _item_name_from_dp(dp, item_id),
                    "type": _item_type_from_dp(dp),
                    "icon_url": _normalize_media_url(_item_icon_from_dp(dp)) or _default_icon_url(item_id),
                    "npc_sell_price": _item_npc_sell_from_dp(dp),
                }
            )
        except (requests.RequestException, ValueError) as ex:
            logger.warning("Loot search (id=%s): %s", item_id, ex)
            out.append(
                {
                    "id": item_id,
                    "name": f"Item {item_id}",
                    "type": "",
                    "icon_url": _default_icon_url(item_id),
                    "npc_sell_price": 0,
                }
            )
        return out

    url = f"{BASE_URL}/?module=vending&action=search&item_search={requests.utils.quote(q)}"
    try:
        resp = scraper.get(
            url,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE_URL}/",
            },
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json() if resp.text.strip() else {}
        results = payload.get("results") if isinstance(payload, dict) else []
    except requests.RequestException as ex:
        logger.warning("Loot search query=%r: %s", q, ex)
        return []
    except ValueError as ex:
        logger.warning("Loot search resposta inválida query=%r: %s", q, ex)
        return []

    seen = set()
    for item in results or []:
        try:
            iid = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if iid in seen:
            continue
        seen.add(iid)
        out.append(
            {
                "id": iid,
                "name": str(item.get("name") or f"Item {iid}").strip() or f"Item {iid}",
                "type": str(item.get("type") or "").strip(),
                "icon_url": _normalize_media_url(str(item.get("icon_url") or item.get("item_icon_url") or "").strip())
                or _default_icon_url(iid),
                "npc_sell_price": 0,
            }
        )
        if len(out) >= 18:
            break

    if not out:
        return []

    if api_key:
        for row in out:
            try:
                dp = fetch_item(int(row["id"]), api_key=api_key, server=dp_server)
            except Exception:
                continue
            if not row.get("type"):
                row["type"] = _item_type_from_dp(dp)
            if not row.get("icon_url"):
                row["icon_url"] = _normalize_media_url(_item_icon_from_dp(dp))
            if row.get("name", "").lower().startswith("item "):
                row["name"] = _item_name_from_dp(dp, int(row["id"]))
            if not int(row.get("npc_sell_price") or 0):
                row["npc_sell_price"] = _item_npc_sell_from_dp(dp)
            if not row.get("icon_url"):
                row["icon_url"] = _default_icon_url(int(row["id"]))
    else:
        for row in out:
            if not row.get("icon_url"):
                row["icon_url"] = _default_icon_url(int(row["id"]))
    return out


class _ToolTip:
    def __init__(self, widget, text: str = ""):
        self.widget = widget
        self.text = text
        self.tip = None
        self.widget.bind("<Enter>", self._on_enter, add="+")
        self.widget.bind("<Leave>", self._on_leave, add="+")

    def set_text(self, text: str) -> None:
        self.text = str(text or "")

    def _on_enter(self, _event=None):
        if not self.text:
            return
        if self.tip is not None:
            return
        x = self.widget.winfo_rootx() + 14
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        lbl = tk.Label(
            self.tip,
            text=self.text,
            justify="left",
            bg="#111111",
            fg="#f4f4f5",
            padx=8,
            pady=4,
            font=("Segoe UI", 8),
            relief="solid",
            borderwidth=1,
        )
        lbl.pack()

    def _on_leave(self, _event=None):
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


def _draw_round_rect(canvas: tk.Canvas, x0, y0, x1, y1, r, **kwargs):
    rr = max(0, int(min(r, (x1 - x0) // 2, (y1 - y0) // 2)))
    pts = [
        x0 + rr, y0,
        x1 - rr, y0,
        x1, y0,
        x1, y0 + rr,
        x1, y1 - rr,
        x1, y1,
        x1 - rr, y1,
        x0 + rr, y1,
        x0, y1,
        x0, y1 - rr,
        x0, y0 + rr,
        x0, y0,
    ]
    return canvas.create_polygon(pts, smooth=True, splinesteps=36, **kwargs)


class _RoundedButton(tk.Canvas):
    def __init__(
        self,
        parent,
        *,
        text: str,
        command,
        bg: str,
        fg: str,
        hover_bg: str,
        disabled_bg: str,
        disabled_fg: str,
        radius: int = 10,
        height: int = 32,
        min_width: int = 56,
        font=("Segoe UI", 9, "bold"),
        padx: int = 12,
    ):
        super().__init__(parent, highlightthickness=0, bd=0, bg=parent.cget("bg"), height=height, cursor="hand2")
        self._text = text
        self._command = command
        self._bg = bg
        self._fg = fg
        self._hover_bg = hover_bg
        self._disabled_bg = disabled_bg
        self._disabled_fg = disabled_fg
        self._radius = int(radius)
        self._height = int(height)
        self._font = font
        self._padx = int(padx)
        self._hover = False
        self._pressed = False
        self._state = "normal"
        tw = tk.font.Font(font=self._font).measure(self._text) if hasattr(tk, "font") else (len(self._text) * 8)
        self.configure(width=max(min_width, tw + self._padx * 2))
        self.bind("<Configure>", lambda _e: self._draw(), add="+")
        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")
        self.bind("<ButtonPress-1>", self._on_press, add="+")
        self.bind("<ButtonRelease-1>", self._on_release, add="+")
        self._draw()

    def _current_bg(self):
        if self._state != "normal":
            return self._disabled_bg
        if self._pressed:
            return self._hover_bg
        if self._hover:
            return self._hover_bg
        return self._bg

    def _current_fg(self):
        return self._fg if self._state == "normal" else self._disabled_fg

    def _draw(self):
        self.delete("all")
        w = max(4, int(self.winfo_width()))
        h = max(4, int(self.winfo_height()))
        _draw_round_rect(self, 1, 1, w - 1, h - 1, self._radius, fill=self._current_bg(), outline="")
        self.create_text(w // 2, h // 2, text=self._text, fill=self._current_fg(), font=self._font)

    def _on_enter(self, _e=None):
        if self._state != "normal":
            return
        self._hover = True
        self._draw()

    def _on_leave(self, _e=None):
        self._hover = False
        self._pressed = False
        self._draw()

    def _on_press(self, _e=None):
        if self._state != "normal":
            return
        self._pressed = True
        self._draw()

    def _on_release(self, event=None):
        if self._state != "normal":
            return
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if not was_pressed:
            return
        if event is None:
            return
        try:
            if 0 <= event.x < int(self.winfo_width()) and 0 <= event.y < int(self.winfo_height()):
                if callable(self._command):
                    self._command()
        except tk.TclError:
            return

    def configure(self, cnf=None, **kw):
        if "text" in kw:
            self._text = str(kw.pop("text"))
        if "state" in kw:
            self._state = str(kw.pop("state"))
            cur = "hand2" if self._state == "normal" else "arrow"
            try:
                super().configure(cursor=cur)
            except tk.TclError:
                pass
        if "command" in kw:
            self._command = kw.pop("command")
        if "bg" in kw:
            self._bg = str(kw.pop("bg"))
        if "fg" in kw:
            self._fg = str(kw.pop("fg"))
        super().configure(cnf, **kw)
        self._draw()

    config = configure

    def cget(self, key):
        if key == "text":
            return self._text
        if key == "state":
            return self._state
        if key == "bg":
            return self._bg
        if key == "fg":
            return self._fg
        return super().cget(key)


class _RoundedEntry(tk.Canvas):
    def __init__(
        self,
        parent,
        *,
        textvariable=None,
        bg: str,
        fg: str,
        border: str,
        focus_border: str,
        radius: int = 10,
        height: int = 32,
        font=("Segoe UI", 10),
    ):
        super().__init__(parent, highlightthickness=0, bd=0, bg=parent.cget("bg"), height=height)
        self._bg_fill = bg
        self._fg = fg
        self._border = border
        self._focus_border = focus_border
        self._radius = int(radius)
        self._focus = False
        self._entry = tk.Entry(
            self,
            textvariable=textvariable,
            bg=bg,
            fg=fg,
            insertbackground=fg,
            relief="flat",
            bd=0,
            font=font,
        )
        self._win = self.create_window(8, height // 2, window=self._entry, anchor="w")
        self.bind("<Configure>", self._on_cfg, add="+")
        self._entry.bind("<FocusIn>", self._on_focus_in, add="+")
        self._entry.bind("<FocusOut>", self._on_focus_out, add="+")
        self._entry.bind("<<Copy>>", self._safe_copy, add="+")
        self._entry.bind("<Control-c>", self._safe_copy, add="+")
        self._entry.bind("<<Cut>>", self._safe_cut, add="+")
        self._entry.bind("<Control-x>", self._safe_cut, add="+")
        self._entry.bind("<<Paste>>", self._safe_paste, add="+")
        self._entry.bind("<Control-v>", self._safe_paste, add="+")
        self._draw()

    def _on_cfg(self, _e=None):
        try:
            h = int(self.winfo_height())
            w = int(self.winfo_width())
            self.coords(self._win, 10, h // 2)
            self.itemconfigure(self._win, width=max(24, w - 20), height=max(20, h - 10))
        except tk.TclError:
            pass
        self._draw()

    def _draw(self):
        self.delete("skin")
        w = max(4, int(self.winfo_width()))
        h = max(4, int(self.winfo_height()))
        stroke = self._focus_border if self._focus else self._border
        _draw_round_rect(self, 1, 1, w - 1, h - 1, self._radius, fill=self._bg_fill, outline=stroke, width=1, tags="skin")

    def _on_focus_in(self, _e=None):
        self._focus = True
        self._draw()

    def _on_focus_out(self, _e=None):
        self._focus = False
        self._draw()

    def _safe_copy(self, _event=None):
        try:
            if self._entry.selection_present():
                text = self._entry.selection_get()
                self.clipboard_clear()
                self.clipboard_append(text)
        except tk.TclError:
            pass
        return "break"

    def _safe_cut(self, _event=None):
        try:
            if self._entry.selection_present():
                text = self._entry.selection_get()
                self.clipboard_clear()
                self.clipboard_append(text)
                self._entry.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        return "break"

    def _safe_paste(self, _event=None):
        try:
            text = self.clipboard_get()
            if text is None:
                return "break"
            if self._entry.selection_present():
                self._entry.delete("sel.first", "sel.last")
            self._entry.insert("insert", str(text))
        except tk.TclError:
            pass
        return "break"

    def bind(self, sequence=None, func=None, add=None):
        if sequence in (
            "<Return>",
            "<KeyRelease>",
            "<FocusIn>",
            "<FocusOut>",
            "<Key>",
            "<<Paste>>",
            "<<Cut>>",
            "<<Copy>>",
            "<Control-c>",
            "<Control-x>",
            "<Control-v>",
        ):
            return self._entry.bind(sequence, func, add=add)
        return super().bind(sequence, func, add=add)

    def get(self):
        return self._entry.get()

    def insert(self, index, value):
        return self._entry.insert(index, value)

    def delete(self, first, last=None):
        try:
            return self._entry.delete(first, last)
        except tk.TclError as ex:
            msg = str(ex).lower()
            # Alguns bindings do Tk chamam delete("sel.first","sel.last")
            # mesmo quando não há seleção ativa; ignoramos sem derrubar a app.
            if "selection isn't in widget" in msg or "sel.first" in str(first).lower():
                return None
            raise

    def focus_set(self):
        return self._entry.focus_set()

    def focus_force(self):
        return self._entry.focus_force()

    def selection_present(self):
        try:
            return bool(self._entry.selection_present())
        except tk.TclError:
            return False

    def selection_get(self):
        try:
            return self._entry.selection_get()
        except tk.TclError:
            return ""

    def configure(self, cnf=None, **kw):
        if "state" in kw:
            self._entry.configure(state=kw.pop("state"))
        return super().configure(cnf, **kw)

    config = configure


class _SimpleScrollable(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", self._on_inner_configure, add="+")
        self.canvas.bind("<Configure>", self._on_canvas_configure, add="+")
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")

    def _on_inner_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)

    def _on_mousewheel(self, event):
        try:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except tk.TclError:
            pass


class LootTab(ttk.Frame):
    def __init__(
        self,
        parent,
        root: tk.Misc,
        loot_manager: LootManager,
        colors: Optional[dict] = None,
        *,
        rounded_card_cls=None,
        scrollable_cls=None,
    ):
        super().__init__(parent)
        self.root = root
        self.loot_manager = loot_manager
        self.colors = colors or {}
        self.rounded_card_cls = rounded_card_cls
        self.scrollable_cls = scrollable_cls
        self._http = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "desktop": True})
        self._photo_refs: List[ImageTk.PhotoImage] = []
        self._search_results: List[dict] = []
        self._chips_expanded = False
        self._btn_timers: Dict[str, str] = {}
        self._cards_reflow_job = None
        self._npc_hydrate_running = False
        self._group_card_inners: Dict[int, tk.Misc] = {}

        self.search_var = tk.StringVar(value="")
        self.search_status_var = tk.StringVar(value="Digite um nome ou ID para buscar.")
        self.search_target_group_var = tk.StringVar(value="")

        self._setup_progress_styles()
        self._build_ui()
        self.refresh_all()

    def _c(self, key: str, default: str) -> str:
        return str(self.colors.get(key, default))

    def _setup_progress_styles(self) -> None:
        style = ttk.Style()
        trough = self._c("bg3", "#1f1f1f")
        style.configure("LootBlue.Horizontal.TProgressbar", troughcolor=trough, background="#3b82f6")
        style.configure("LootWarn.Horizontal.TProgressbar", troughcolor=trough, background="#f59e0b")
        style.configure("LootDanger.Horizontal.TProgressbar", troughcolor=trough, background="#ef4444")

    def _make_scrollable(self, parent):
        if self.scrollable_cls is not None:
            return self.scrollable_cls(parent, inner_bg=self._c("bg", "#121212"))
        return _SimpleScrollable(parent)

    def _make_card(self, parent, *, radius=14, margin=8):
        if self.rounded_card_cls is not None:
            shell = self.rounded_card_cls(parent, radius=radius, margin=margin, fill_key="card")
            return shell, shell.inner
        fr = tk.Frame(
            parent,
            bg=self._c("card", "#1f1f1f"),
            highlightbackground=self._c("border", "#2f2f2f"),
            highlightthickness=1,
        )
        return fr, fr

    def _build_ui(self):
        bg = self._c("bg", "#121212")
        style = ttk.Style()
        style.configure("LootTab.TFrame", background=bg)
        self.configure(style="LootTab.TFrame")
        card = self._c("card", "#1f1f1f")
        text = self._c("text", "#f4f4f5")
        text2 = self._c("text2", "#d4d4d8")
        text3 = self._c("text3", "#9ca3af")
        border = self._c("border", "#2f2f2f")
        purple = self._c("purple", "#7c3aed")

        # Barra de busca (topo)
        top_shell = tk.Frame(self, bg=bg)
        top_shell.pack(fill="x", padx=20, pady=(4, 6))
        top = tk.Frame(top_shell, bg=bg)
        top.pack(fill="x")
        tk.Label(top, text="Monte seu alootid", bg=bg, fg=self._c("purple3", "#c4b5fd"), font=("Segoe UI", 14, "bold")).pack(
            anchor="w", pady=(2, 0)
        )
        tk.Label(
            top,
            text="Busque por nome, um ID ou varios IDs de uma vez separados por virgula (ex.: 522, 2610, 2613).",
            bg=bg,
            fg=text3,
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(0, 10))
        sr = tk.Frame(top, bg=bg)
        sr.pack(fill="x")
        search_slot = tk.Frame(sr, bg=bg, width=420, height=32)
        search_slot.pack(side="left", fill="y")
        try:
            search_slot.pack_propagate(False)
        except tk.TclError:
            pass
        self.search_entry = _RoundedEntry(
            search_slot,
            textvariable=self.search_var,
            bg=self._c("bg3", "#18181b"),
            fg=text,
            border=border,
            focus_border=purple,
            font=("Segoe UI", 10),
        )
        self.search_entry.pack(fill="both", expand=True)
        self.search_entry.bind("<Return>", lambda _e: self._start_search(), add="+")
        self.search_btn = _RoundedButton(
            sr,
            text="Buscar",
            command=self._start_search,
            bg=purple,
            fg="#ffffff",
            hover_bg=self._c("accent", "#8b5cf6"),
            disabled_bg=self._c("bg3", "#2a2a2a"),
            disabled_fg=self._c("text3", "#8f8f8f"),
            font=("Segoe UI", 9, "bold"),
            height=32,
            min_width=96,
        )
        self.search_btn.pack(side="left", padx=(8, 0))

        def _sync_search_slot_width(_e=None):
            try:
                total_w = int(sr.winfo_width())
                btn_w = int(self.search_btn.winfo_reqwidth())
                target = max(260, int(total_w * 0.5) - btn_w - 8)
                search_slot.configure(width=target)
            except tk.TclError:
                pass

        sr.bind("<Configure>", _sync_search_slot_width, add="+")
        self.after(0, _sync_search_slot_width)
        target_row = tk.Frame(top, bg=bg)
        target_row.pack(fill="x", pady=(8, 0))
        tk.Label(
            target_row,
            text="Adicionar na lista:",
            bg=bg,
            fg=text2,
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")
        self.search_target_combo = ttk.Combobox(
            target_row,
            textvariable=self.search_target_group_var,
            state="readonly",
            width=30,
        )
        self.search_target_combo.pack(side="left", padx=(8, 0))
        self.chips_wrap = tk.Frame(top, bg=bg, height=68)
        self.chips_wrap.pack(fill="x", pady=(10, 2))
        try:
            self.chips_wrap.pack_propagate(False)
        except tk.TclError:
            pass

        # Área de cards (faixa horizontal única)
        cards_wrap = tk.Frame(self, bg=bg)
        cards_wrap.pack(fill="both", expand=True, padx=20, pady=(0, 8))
        self.cards_canvas = tk.Canvas(cards_wrap, bg=bg, bd=0, highlightthickness=0)
        self.cards_hsb = ttk.Scrollbar(cards_wrap, orient="horizontal", command=self.cards_canvas.xview)
        self.cards_canvas.configure(xscrollcommand=self.cards_hsb.set)
        self.cards_canvas.pack(side="top", fill="both", expand=True)
        self.cards_hsb.pack(side="bottom", fill="x")
        self.cards_host = tk.Frame(self.cards_canvas, bg=bg)
        self._cards_host_win = self.cards_canvas.create_window((0, 0), window=self.cards_host, anchor="nw")
        self.cards_host.bind(
            "<Configure>",
            lambda _e: self.cards_canvas.configure(scrollregion=self.cards_canvas.bbox("all")),
            add="+",
        )
        self.cards_canvas.bind("<Configure>", self._schedule_cards_reflow, add="+")

    def _schedule_cards_reflow(self, _event=None):
        if self._cards_reflow_job is not None:
            try:
                self.after_cancel(self._cards_reflow_job)
            except tk.TclError:
                pass
        self._cards_reflow_job = self.after(80, self._render_group_cards)

    def _fetch_url_bytes(self, url: str) -> Optional[bytes]:
        u = str(url or "").strip()
        if not u:
            return None
        try:
            resp = self._http.get(
                u,
                timeout=16,
                headers={
                    "Referer": f"{BASE_URL}/",
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                    "Cache-Control": "no-cache",
                },
            )
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as ex:
            logger.debug("LootTab: download icon (requests err) %s: %s", u, ex)
            return None
        except Exception as ex:
            logger.debug("LootTab: download icon %s: %s", u, ex)
            return None

    def _load_icon_photo(self, item_id: int, icon_url: str, size: int = 24) -> Optional[ImageTk.PhotoImage]:
        path = self.loot_manager.ensure_icon_cached(item_id, icon_url, self._fetch_url_bytes)
        if not path:
            return None
        try:
            im = Image.open(path).convert("RGBA")
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:
                resample = Image.LANCZOS
            im.thumbnail((size, size), resample)
            ph = ImageTk.PhotoImage(im, master=self.root)
            self._photo_refs.append(ph)
            return ph
        except Exception as ex:
            logger.debug("LootTab icon photo %s: %s", path, ex)
            return None

    @staticmethod
    def _parse_multi_id_query(query: str) -> List[int]:
        raw = str(query or "").strip()
        if not raw or "," not in raw:
            return []
        out: List[int] = []
        seen = set()
        for part in [p.strip() for p in raw.split(",")]:
            if not part:
                continue
            if not part.isdigit():
                return []
            iid = int(part)
            if iid <= 0 or iid in seen:
                continue
            out.append(iid)
            seen.add(iid)
        return out

    def _start_search(self):
        q = str(self.search_var.get() or "").strip()
        if not q:
            self.search_status_var.set("Digite um nome ou ID para buscar.")
            self._search_results = []
            self._render_search_chips()
            return
        self.search_status_var.set("Buscando...")
        self.search_btn.configure(state="disabled")
        self._chips_expanded = False
        self._render_search_chips()
        multi_ids = self._parse_multi_id_query(q)

        def worker():
            try:
                if multi_ids:
                    results = []
                    seen = set()
                    for iid in multi_ids:
                        for row in search_item(str(iid)):
                            rid = int(row.get("id") or 0)
                            if rid and rid not in seen:
                                seen.add(rid)
                                results.append(row)
                else:
                    results = search_item(q)
            except Exception as ex:
                logger.warning("Loot search thread: %s", ex)
                results = []
            for row in results:
                try:
                    self.loot_manager.ensure_icon_cached(int(row.get("id") or 0), str(row.get("icon_url") or ""), self._fetch_url_bytes)
                except Exception:
                    pass
            self.root.after(0, lambda r=results: self._finish_search(r))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_search(self, results: List[dict]):
        self.search_btn.configure(state="normal")
        self._search_results = list(results or [])
        if not self._search_results:
            self.search_status_var.set("Nenhum item encontrado.")
        else:
            self.search_status_var.set(f"{len(self._search_results)} resultado(s).")
        self._render_search_chips()

    def _render_search_chips(self):
        for w in self.chips_wrap.winfo_children():
            w.destroy()
        chips_bg = self._c("bg", "#121212")
        text = self._c("text", "#f4f4f5")
        text3 = self._c("text3", "#9ca3af")
        purple = self._c("purple", "#7c3aed")

        status = str(self.search_status_var.get() or "")
        if status == "Buscando...":
            tk.Label(self.chips_wrap, text="Buscando...", bg=chips_bg, fg=text3, font=("Segoe UI", 9, "italic")).pack(anchor="w")
            return
        if not self._search_results:
            tk.Label(self.chips_wrap, text="Nenhum item encontrado.", bg=chips_bg, fg=text3, font=("Segoe UI", 9)).pack(anchor="w")
            return

        items = self._search_results if self._chips_expanded else self._search_results[:5]
        overflow = max(0, len(self._search_results) - len(items))

        for row in items:
            iid = int(row.get("id") or 0)
            chip = tk.Frame(self.chips_wrap, bg=chips_bg, highlightthickness=0, bd=0)
            chip.pack(side="left", padx=(0, 6), pady=(0, 4))
            ph = self._load_icon_photo(iid, str(row.get("icon_url") or ""), size=24)
            if ph:
                tk.Label(chip, image=ph, bg=chips_bg).pack(side="left", padx=(6, 4), pady=4)
            else:
                tk.Label(chip, text="?", bg=chips_bg, fg=text3, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(6, 4), pady=4)
            tk.Label(
                chip,
                text=f"{str(row.get('name') or f'Item {iid}')[:22]} ({iid})",
                bg=chips_bg,
                fg=text,
                font=("Segoe UI", 8),
            ).pack(side="left", padx=(0, 5))
            plus = tk.Label(chip, text="+", bg=purple, fg="#ffffff", font=("Segoe UI", 9, "bold"), width=2, cursor="hand2")
            plus.pack(side="right", padx=(0, 6), pady=4)
            plus.bind("<Button-1>", lambda _e, r=copy.deepcopy(row): self._add_search_result_to_group(r))
            chip.bind("<Button-1>", lambda _e, r=copy.deepcopy(row): self._add_search_result_to_group(r), add="+")

        if overflow > 0:
            more = tk.Label(
                self.chips_wrap,
                text=f"+{overflow} resultados",
                bg=self._c("bg3", "#18181b"),
                fg=self._c("text2", "#d4d4d8"),
                font=("Segoe UI", 8, "bold"),
                padx=10,
                pady=6,
                cursor="hand2",
            )
            more.pack(side="left", pady=(0, 4))
            more.bind("<Button-1>", lambda _e: self._expand_chips())

    def _expand_chips(self):
        self._chips_expanded = True
        self._render_search_chips()

    def _parse_target_group_from_combo(self) -> Optional[int]:
        raw = str(self.search_target_group_var.get() or "").strip()
        if not raw:
            return None
        left = raw.split("—", 1)[0].strip().lower()
        try:
            n = int(left.replace("lista", "").replace("grupo", "").strip())
        except (TypeError, ValueError):
            return None
        return n if n in self.loot_manager.groups else None

    def _add_search_result_to_group(self, row: dict):
        groups = [self.loot_manager.groups[n] for n in sorted(self.loot_manager.groups)]
        if not groups:
            self._add_group()
            groups = [self.loot_manager.groups[n] for n in sorted(self.loot_manager.groups)]
        target = self._parse_target_group_from_combo()
        if target is None:
            target = int(groups[0].number)
        self._add_item_to_group(target, row)

    def _save_and_refresh(self, *, full: bool = False):
        self.loot_manager.save_to_file()
        if full:
            self.refresh_all()
            return
        self._hydrate_missing_npc_prices_async()

    def _refresh_group_card(self, group_number: int):
        gnum = int(group_number)
        inner = self._group_card_inners.get(gnum)
        grp = self.loot_manager.groups.get(gnum)
        if inner is None or grp is None or not inner.winfo_exists():
            self._render_group_cards()
            return
        for w in inner.winfo_children():
            w.destroy()
        self._build_group_card(inner, grp)

    def _add_item_to_group(self, group_number: int, row: dict):
        item = LootItem(
            id=int(row.get("id") or 0),
            name=str(row.get("name") or "").strip() or f"Item {int(row.get('id') or 0)}",
            type=str(row.get("type") or "").strip(),
            icon_url=str(row.get("icon_url") or "").strip(),
            npc_sell_price=int(row.get("npc_sell_price") or 0),
        )
        if not self.loot_manager.add_item(group_number, item):
            messagebox.showinfo("Auto Loot", "Grupo cheio (10) ou item duplicado.", parent=self.root)
            return
        self._save_and_refresh(full=False)
        self._refresh_group_card(group_number)

    def _remove_item_from_group(self, group_number: int, item_id: int):
        self.loot_manager.remove_item(group_number, item_id)
        self._save_and_refresh(full=False)
        self._refresh_group_card(group_number)

    def _add_group(self):
        existing = sorted(int(n) for n in self.loot_manager.groups.keys())
        new_n = None
        for n in range(1, _MAX_GROUP_NUMBER + 1):
            if n not in existing:
                new_n = n
                break
        if new_n is None:
            messagebox.showinfo("Auto Loot", f"Limite de grupos atingido ({_MAX_GROUP_NUMBER}).", parent=self.root)
            return
        self.loot_manager.groups[new_n] = LootGroup(number=new_n, name=f"Lista {new_n}", autoload=False, items=[])
        self._save_and_refresh(full=True)

    def _delete_group(self, group_number: int):
        groups = self.loot_manager.groups
        if int(group_number) not in groups:
            return
        if len(groups) <= 1:
            messagebox.showinfo("Auto Loot", "É necessário manter pelo menos 1 lista.", parent=self.root)
            return
        grp = groups.get(int(group_number))
        label = str(getattr(grp, "name", "") or f"Lista {group_number}")
        item_count = len(getattr(grp, "items", []) or [])
        ok = messagebox.askyesno(
            "Excluir lista",
            f"Excluir a lista '{label}' ({item_count} item(ns))?\n\nEsta ação não pode ser desfeita.",
            parent=self.root,
            icon="warning",
        )
        if not ok:
            return
        groups.pop(int(group_number), None)
        self._save_and_refresh(full=True)

    def _truncate(self, text: str, n: int) -> str:
        s = str(text or "")
        return s if len(s) <= n else s[: max(0, n - 1)] + "…"

    @staticmethod
    def _fmt_zeny(value: int) -> str:
        try:
            n = int(value or 0)
        except (TypeError, ValueError):
            n = 0
        return f"{n:,}".replace(",", ".") + "z"

    def _copy_with_feedback(self, btn, cmd: str, *, duration_ms: int = 1500):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(cmd)
            self.root.update_idletasks()
        except tk.TclError:
            return
        old_text = str(btn.cget("text"))
        btn.configure(text="✓ Copiado!")
        key = str(id(btn))
        prev = self._btn_timers.get(key)
        if prev is not None:
            try:
                self.after_cancel(prev)
            except tk.TclError:
                pass

        def restore():
            self._btn_timers.pop(key, None)
            try:
                btn.configure(text=old_text)
            except tk.TclError:
                pass

        self._btn_timers[key] = self.after(duration_ms, restore)

    def refresh_all(self):
        groups = [self.loot_manager.groups[n] for n in sorted(self.loot_manager.groups)]
        opts = [f"Lista {g.number} — {g.name}" for g in groups]
        if hasattr(self, "search_target_combo"):
            self.search_target_combo["values"] = opts
            cur = str(self.search_target_group_var.get() or "").strip()
            if cur not in opts:
                self.search_target_group_var.set(opts[0] if opts else "")
        self._render_search_chips()
        self._render_group_cards()
        self._hydrate_missing_npc_prices_async()

    def _hydrate_missing_npc_prices_async(self):
        if self._npc_hydrate_running:
            return
        cfg = load_settings()
        api_key = (cfg.get("divine_pride_api_key") or "").strip()
        if not api_key:
            return
        srv = (cfg.get("divine_pride_server") or "").strip() or None
        todo = []
        for n in sorted(self.loot_manager.groups):
            grp = self.loot_manager.groups[n]
            for it in grp.items:
                if int(getattr(it, "npc_sell_price", 0) or 0) <= 0:
                    todo.append((grp.number, int(it.id)))
        if not todo:
            return
        self._npc_hydrate_running = True

        def worker():
            changed = False
            try:
                by_group = {int(g.number): g for g in self.loot_manager.groups.values()}
                for gnum, iid in todo:
                    try:
                        dp = fetch_item(iid, api_key=api_key, server=srv)
                        npc = int(_item_npc_sell_from_dp(dp) or 0)
                    except Exception:
                        npc = 0
                    if npc <= 0:
                        continue
                    grp = by_group.get(int(gnum))
                    if not grp:
                        continue
                    for it in grp.items:
                        if int(it.id) == int(iid) and int(getattr(it, "npc_sell_price", 0) or 0) <= 0:
                            it.npc_sell_price = npc
                            changed = True
                            break
                if changed:
                    self.loot_manager.save_to_file()
            finally:
                self._npc_hydrate_running = False
                if changed:
                    self.root.after(0, self.refresh_all)

        threading.Thread(target=worker, daemon=True).start()

    def _progress_style_for_count(self, count: int) -> str:
        if count >= 9:
            return "LootDanger.Horizontal.TProgressbar"
        if count >= 5:
            return "LootWarn.Horizontal.TProgressbar"
        return "LootBlue.Horizontal.TProgressbar"

    def _start_inline_rename(self, holder, group_number: int, current_name: str):
        for w in holder.winfo_children():
            w.destroy()
        e = tk.Entry(
            holder,
            bg=self._c("bg3", "#18181b"),
            fg=self._c("text", "#f4f4f5"),
            insertbackground=self._c("text", "#f4f4f5"),
            relief="flat",
            font=("Segoe UI", 10, "bold"),
        )
        e.pack(fill="x")
        e.insert(0, current_name)
        e.focus_set()
        e.selection_range(0, "end")

        def save(_ev=None):
            self.loot_manager.set_group_name(group_number, e.get().strip())
            self._save_and_refresh(full=False)
            self._refresh_group_card(group_number)
            return "break"

        e.bind("<Return>", save, add="+")
        e.bind("<FocusOut>", save, add="+")

    def _render_group_cards(self):
        self._cards_reflow_job = None
        self._group_card_inners = {}
        for w in self.cards_host.winfo_children():
            w.destroy()
        groups = [self.loot_manager.groups[n] for n in sorted(self.loot_manager.groups)]
        try:
            vh = int(self.cards_canvas.winfo_height())
            vw = int(self.cards_canvas.winfo_width())
        except tk.TclError:
            vh, vw = 0, 0
        card_h = max(360, vh - 14) if vh > 40 else 520
        card_w = 300 if vw <= 0 else max(260, min(360, int(vw * 0.32)))

        for grp in groups:
            outer, inner = self._make_card(self.cards_host, radius=14, margin=8)
            if isinstance(outer, tk.Canvas):
                outer.configure(width=card_w, height=card_h)
            else:
                try:
                    outer.configure(width=card_w, height=card_h)
                except tk.TclError:
                    pass
            outer.pack(side="left", fill="y", padx=6, pady=6)
            try:
                outer.pack_propagate(False)
            except tk.TclError:
                pass
            self._build_group_card(inner, grp)
            self._group_card_inners[int(grp.number)] = inner

        # Card fantasma: + novo grupo (sempre à direita)
        ghost = tk.Canvas(
            self.cards_host,
            bg=self._c("bg", "#121212"),
            highlightthickness=0,
            bd=0,
            width=card_w,
            height=card_h,
            cursor="hand2",
        )
        ghost.pack(side="left", fill="y", padx=6, pady=6)

        def draw_ghost(_e=None):
            ghost.delete("all")
            w = max(80, int(ghost.winfo_width()))
            h = max(80, int(ghost.winfo_height()))
            ghost.create_rectangle(
                6,
                6,
                w - 6,
                h - 6,
                outline=self._c("border2", "#52525b"),
                width=2,
                dash=(7, 4),
            )
            if len(groups) < _MAX_GROUP_NUMBER:
                ghost.create_text(w // 2, h // 2 - 12, text="+", fill=self._c("text2", "#d4d4d8"), font=("Segoe UI", 26, "bold"))
                ghost.create_text(
                    w // 2,
                    h // 2 + 18,
                    text="Novo grupo",
                    fill=self._c("text2", "#d4d4d8"),
                    font=("Segoe UI", 10, "bold"),
                )
            else:
                ghost.create_text(
                    w // 2,
                    h // 2,
                    text=f"Limite {_MAX_GROUP_NUMBER} grupos",
                    fill=self._c("text3", "#9ca3af"),
                    font=("Segoe UI", 9),
                )

        ghost.bind("<Configure>", draw_ghost, add="+")
        ghost.bind("<Button-1>", lambda _e: self._add_group() if len(groups) < _MAX_GROUP_NUMBER else None, add="+")
        try:
            self.cards_canvas.configure(scrollregion=self.cards_canvas.bbox("all"))
        except tk.TclError:
            pass

    def _build_group_card(self, parent, grp: LootGroup):
        card = self._c("card", "#1f1f1f")
        text = self._c("text", "#f4f4f5")
        text2 = self._c("text2", "#d4d4d8")
        text3 = self._c("text3", "#9ca3af")
        border = self._c("border", "#2f2f2f")

        # Header
        hdr = tk.Frame(parent, bg=card)
        hdr.pack(fill="x", pady=(2, 4))
        name_holder = tk.Frame(hdr, bg=card)
        name_holder.pack(side="left", fill="x", expand=True)
        name_lbl = tk.Label(
            name_holder,
            text=grp.name or f"Lista {grp.number}",
            bg=card,
            fg=text,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )
        name_lbl.pack(side="left")
        name_lbl.bind(
            "<Button-1>",
            lambda _e, h=name_holder, n=grp.number, cur=str(grp.name or f"Lista {grp.number}"): self._start_inline_rename(h, n, cur),
            add="+",
        )
        edit = tk.Label(name_holder, text=" ✎", bg=card, fg=text3, font=("Segoe UI", 9), cursor="hand2")
        edit.pack(side="left")
        edit.bind(
            "<Button-1>",
            lambda _e, h=name_holder, n=grp.number, cur=str(grp.name or f"Lista {grp.number}"): self._start_inline_rename(h, n, cur),
            add="+",
        )
        _ToolTip(edit, "Renomear lista")

        tk.Label(hdr, text=f"{len(grp.items)}/10", bg=card, fg=text2, font=("Segoe UI", 9, "bold")).pack(side="right")

        # Progress
        pb = ttk.Progressbar(
            parent,
            mode="determinate",
            maximum=_MAX_ITEMS_PER_GROUP,
            value=len(grp.items),
            style=self._progress_style_for_count(len(grp.items)),
        )
        pb.pack(fill="x", pady=(0, 8))

        # Footer (fixo no fundo do card)
        footer = tk.Frame(parent, bg=card)
        footer.pack(side="bottom", fill="x")
        cmd_save = self.loot_manager.cmd_save(grp.number)
        tk.Label(
            footer,
            text=cmd_save,
            bg=self._c("bg3", "#18181b"),
            fg=self._c("green", "#22c55e"),
            font=("Consolas", 7),
            anchor="w",
            justify="left",
            padx=6,
            pady=4,
        ).pack(fill="x", pady=(8, 6))
        bfr = tk.Frame(footer, bg=card)
        bfr.pack(fill="x")
        bcenter = tk.Frame(bfr, bg=card)
        bcenter.pack(anchor="center")
        bsave = _RoundedButton(
            bcenter,
            text="Copiar save",
            bg=self._c("purple", "#7c3aed"),
            fg="#ffffff",
            hover_bg=self._c("accent", "#8b5cf6"),
            disabled_bg=self._c("bg3", "#2a2a2a"),
            disabled_fg=self._c("text3", "#8f8f8f"),
            font=("Segoe UI", 8, "bold"),
            height=30,
            min_width=96,
            command=lambda b=None, c=cmd_save: self._copy_with_feedback(bsave, c),
        )
        bsave.pack(side="left")
        bload = _RoundedButton(
            bcenter,
            text="Copiar load",
            bg=self._c("green", "#22c55e"),
            fg="#ffffff",
            hover_bg=self._c("btn_success_hover", "#166534"),
            disabled_bg=self._c("bg3", "#2a2a2a"),
            disabled_fg=self._c("text3", "#8f8f8f"),
            font=("Segoe UI", 8, "bold"),
            height=30,
            min_width=96,
            command=lambda b=None, c=self.loot_manager.cmd_load(grp.number): self._copy_with_feedback(bload, c),
        )
        bload.pack(side="left", padx=(6, 0))
        danger_wrap = tk.Frame(footer, bg=card)
        danger_wrap.pack(fill="x", pady=(6, 0))
        del_btn = tk.Button(
            danger_wrap,
            text="Excluir lista",
            command=lambda n=grp.number: self._delete_group(n),
            bg=card,
            fg=self._c("text3", "#9ca3af"),
            activebackground=card,
            activeforeground=self._c("red", "#ef4444"),
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            font=("Segoe UI", 7, "underline"),
            padx=2,
            pady=1,
        )
        del_btn.pack(side="right")
        _ToolTip(del_btn, "Remove esta lista (com confirmação)")

        # Items (área rolável interna do card, ocupando o restante vertical)
        body_wrap = tk.Frame(parent, bg=card)
        body_wrap.pack(fill="both", expand=True, pady=(0, 0))
        items_canvas = tk.Canvas(body_wrap, bg=card, bd=0, highlightthickness=0)
        items_sb = ttk.Scrollbar(body_wrap, orient="vertical", command=items_canvas.yview)
        items_canvas.configure(yscrollcommand=items_sb.set)
        items_canvas.pack(side="left", fill="both", expand=True)
        items_sb.pack(side="right", fill="y")
        body = tk.Frame(items_canvas, bg=card)
        inner_win = items_canvas.create_window((0, 0), window=body, anchor="nw")

        def _on_body_cfg(_e=None):
            try:
                items_canvas.configure(scrollregion=items_canvas.bbox("all"))
            except tk.TclError:
                pass

        def _on_canvas_cfg(e):
            try:
                items_canvas.itemconfigure(inner_win, width=int(e.width))
            except tk.TclError:
                pass

        def _on_wheel(e):
            try:
                delta = int(getattr(e, "delta", 0) or 0)
            except (TypeError, ValueError):
                delta = 0
            if not delta:
                return "break"
            try:
                first, last = items_canvas.yview()
            except tk.TclError:
                return "break"
            # Em alguns ambientes Windows, o sentido de delta vem invertido.
            # Usamos o mapeamento abaixo e travamos no topo/fundo para evitar "área vazia".
            units = 1 if delta > 0 else -1
            if units < 0 and first <= 0.0:
                return "break"
            if units > 0 and last >= 1.0:
                return "break"
            try:
                items_canvas.yview_scroll(units, "units")
            except tk.TclError:
                pass
            return "break"

        def _on_wheel_up(_e):
            try:
                first, _last = items_canvas.yview()
                if first <= 0.0:
                    return "break"
                items_canvas.yview_scroll(-1, "units")
            except tk.TclError:
                pass
            return "break"

        def _on_wheel_down(_e):
            try:
                _first, last = items_canvas.yview()
                if last >= 1.0:
                    return "break"
                items_canvas.yview_scroll(1, "units")
            except tk.TclError:
                pass
            return "break"

        def _bind_wheel_recursive(widget):
            try:
                # Sem add="+": sobrescreve o bind do ScrollableFrame externo
                # para priorizar o scroll interno do card.
                widget.bind("<MouseWheel>", _on_wheel)
                widget.bind("<Button-4>", _on_wheel_up)
                widget.bind("<Button-5>", _on_wheel_down)
            except tk.TclError:
                return
            for ch in widget.winfo_children():
                _bind_wheel_recursive(ch)

        body.bind("<Configure>", _on_body_cfg, add="+")
        items_canvas.bind("<Configure>", _on_canvas_cfg, add="+")
        _bind_wheel_recursive(body_wrap)
        # O ScrollableFrame externo rebinda roda do rato de forma assíncrona;
        # re-aplicamos depois para manter scroll interno funcional.
        self.after(260, lambda w=body_wrap: _bind_wheel_recursive(w) if w.winfo_exists() else None)
        self.after(620, lambda w=body_wrap: _bind_wheel_recursive(w) if w.winfo_exists() else None)

        for it in grp.items:
            iid = int(it.id)
            row = tk.Frame(body, bg=card, highlightbackground=border, highlightthickness=1)
            row.pack(fill="x", pady=2)
            ph = self._load_icon_photo(iid, str(it.icon_url or ""), size=26)
            icon = tk.Canvas(row, width=26, height=26, bg=card, bd=0, highlightthickness=0)
            icon.pack(side="left", padx=6, pady=4)
            if ph:
                icon.create_image(13, 13, image=ph)
            else:
                icon.create_text(13, 13, text="?", fill=text3, font=("Segoe UI", 9, "bold"))
            tcol = tk.Frame(row, bg=card)
            tcol.pack(side="left", fill="x", expand=True, pady=4)
            tk.Label(tcol, text=self._truncate(it.name, 24), bg=card, fg=text, font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x")
            npc_sell = int(getattr(it, "npc_sell_price", 0) or 0)
            npc_txt = self._fmt_zeny(npc_sell) if npc_sell > 0 else "—"
            tk.Label(
                tcol,
                text=f"ID {iid}  ·  NPC {npc_txt}",
                bg=card,
                fg=text3,
                font=("Segoe UI", 7),
                anchor="w",
            ).pack(fill="x")
            rm = tk.Button(
                row,
                text="✕",
                command=lambda n=grp.number, x=iid: self._remove_item_from_group(n, x),
                bg=self._c("bg3", "#18181b"),
                fg=text2,
                activebackground=self._c("btn_danger_hover", "#991b1b"),
                activeforeground="#ffffff",
                relief="flat",
                bd=0,
                highlightthickness=0,
                cursor="hand2",
                width=2,
                font=("Segoe UI", 8, "bold"),
            )
            rm.pack(side="right", padx=6)
            _bind_wheel_recursive(row)

        vagas = max(0, _MAX_ITEMS_PER_GROUP - len(grp.items))
        if vagas > 0:
            txt = f"···· {vagas} vaga(s) disponível(is) ····"
            tk.Label(body, text=txt, bg=card, fg=text3, font=("Consolas", 8)).pack(fill="x", pady=(4, 2))


