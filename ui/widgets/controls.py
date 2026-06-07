"""Widgets Tk customizados (botões, entradas, scroll, cards)."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

from ui.theme import C
from ui.widgets.helpers import (
    canvas_round_fill,
    canvas_round_fill_sb,
    pil_round_solid,
    pill_corner_radius,
    tk_widget_bg,
)

class DarkButton(tk.Canvas):
    """Botão com cantos arredondados (substitui ``tk.Button`` na maior parte da UI)."""

    _radius = 11

    def __init__(
        self,
        parent,
        style="primary",
        command=None,
        text="",
        font=None,
        padx=10,
        pady=4,
        text_anchor="center",
        **kwargs,
    ):
        if "font" in kwargs:
            font = kwargs.pop("font")
        if "padx" in kwargs:
            padx = kwargs.pop("padx")
        if "pady" in kwargs:
            pady = kwargs.pop("pady")
        if "command" in kwargs:
            command = kwargs.pop("command")
        if "text" in kwargs:
            text = kwargs.pop("text")
        if "text_anchor" in kwargs:
            text_anchor = kwargs.pop("text_anchor")
        if "style" in kwargs:
            style = kwargs.pop("style")
        self._command = command
        self._text = text
        self._font = font or ("Segoe UI", 9, "bold")
        self._padx = padx
        self._pady = pady
        self._style_name = style
        self._text_anchor = text_anchor
        self._hover = False
        self._pressed = False
        self._disabled = False
        self._min_width = int(kwargs.pop("width", 0) or 0)
        ckw = {k: v for k, v in kwargs.items() if k in ("cursor", "takefocus", "highlightthickness")}
        for k in ("cursor", "takefocus", "highlightthickness"):
            kwargs.pop(k, None)
        cur = ckw.get("cursor", "hand2")
        super().__init__(
            parent,
            highlightthickness=ckw.get("highlightthickness", 0),
            cursor=cur,
            takefocus=ckw.get("takefocus", 0),
        )
        self.configure(bg=tk_widget_bg(parent))
        self._db_cfg_job = None
        self.bind("<Configure>", self._on_configure_resize)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self._tkfont = tkfont.Font(font=self._font)
        self._last_draw_wh = None
        self._min_h = max(28, int(self._tkfont.metrics("linespace") + 2 * self._pady + 12))
        self._min_w = max(self._min_width, int(self._tkfont.measure(self._text) + 2 * self._padx + 24))
        self.configure(height=self._min_h, width=self._min_w)
        self.after_idle(self._draw)

    def _on_configure_resize(self, _event=None):
        """Redimensionar a janela dispara centenas de Configure/s; agrega redesenhos."""
        if self._db_cfg_job is not None:
            try:
                self.after_cancel(self._db_cfg_job)
            except tk.TclError:
                pass
        self._db_cfg_job = self.after(90, self._draw_after_resize_coalesce)

    def _draw_after_resize_coalesce(self):
        self._db_cfg_job = None
        # Só redesenha se o próprio botão mudou de tamanho — muitos botões têm
        # tamanho fixo e recebem <Configure> só por moverem dentro do pai.
        try:
            wh = (int(self.winfo_width()), int(self.winfo_height()))
        except tk.TclError:
            return
        if wh == self._last_draw_wh:
            return
        self._draw()

    def _colors(self):
        if self._disabled:
            return {
                "bg": C["bg3"],
                "fg": C["text3"],
                "hover": C["bg3"],
            }
        st = self._style_name
        if st == "primary":
            return {"bg": C["purple"], "fg": "#ffffff", "hover": C["accent"]}
        if st == "ghost":
            return {"bg": C["bg3"], "fg": C["text2"], "hover": C["border2"]}
        if st == "danger":
            return {
                "bg": C["btn_danger_bg"],
                "fg": C["btn_danger_fg"],
                "hover": C["btn_danger_hover"],
            }
        if st == "success":
            return {
                "bg": C["btn_success_bg"],
                "fg": C["btn_success_fg"],
                "hover": C["btn_success_hover"],
            }
        if st == "mh_refresh":
            return {"bg": "#2d7a2d", "fg": "#ffffff", "hover": "#3a9e3a"}
        return {"bg": C["bg3"], "fg": C["text2"], "hover": C["border2"]}

    def _face(self):
        c = self._colors()
        bg = c["hover"] if (self._hover or self._pressed) and not self._disabled else c["bg"]
        return bg, c["fg"]

    def _draw(self, event=None):
        w = max(int(self.winfo_width()), 8)
        h = max(int(self.winfo_height()), 8)
        self._last_draw_wh = (w, h)
        self.delete("fill", "txt")
        bg, fg = self._face()
        rr = min(self._radius, h // 2 - 1, w // 2 - 1)
        canvas_round_fill(self, 1, 1, w - 1, h - 1, rr, bg, tag="fill", holder=self)
        if self._text_anchor == "w":
            tx = self._padx + 6
            anc = "w"
        else:
            tx = w // 2
            anc = "center"
        ty = h // 2
        self.create_text(tx, ty, text=self._text, anchor=anc, fill=fg, font=self._font, tags=("txt",))

    def _enter(self, _e=None):
        if self._disabled:
            return
        self._hover = True
        self._draw()

    def _leave(self, _e=None):
        self._hover = False
        self._pressed = False
        self._draw()

    def _press(self, _e=None):
        if self._disabled:
            return
        self._pressed = True
        self._draw()

    def _release(self, event=None):
        if self._disabled:
            return
        was = self._pressed
        self._pressed = False
        self._draw()
        if was and self._command and event is not None:
            try:
                x, y = event.x, event.y
                if 0 <= x < int(self.winfo_width()) and 0 <= y < int(self.winfo_height()):
                    self._command()
            except tk.TclError:
                pass

    def configure(self, cnf=None, **kw):
        if cnf and isinstance(cnf, dict):
            kw = dict(cnf, **kw)
        if "text" in kw:
            self._text = kw.pop("text")
            self._min_w = max(self._min_width, int(self._tkfont.measure(self._text) + 2 * self._padx + 24))
            try:
                super().configure(width=self._min_w)
            except tk.TclError:
                pass
        if "command" in kw:
            self._command = kw.pop("command")
        if kw.get("state") == "disabled":
            self._disabled = True
        elif "state" in kw:
            self._disabled = str(kw.get("state")) == "disabled"
        if "style" in kw:
            self._style_name = kw.pop("style")
        if "bg" in kw:
            kw.pop("bg", None)
            super().configure(bg=tk_widget_bg(self.master))
        if kw:
            super().configure(**kw)
        self.after_idle(self._draw)

    config = configure


class DarkCheckbutton(tk.Frame):
    """Caixa de opção desenhada (contraste claro marcado / desmarcado no Windows)."""

    _BOX = 20

    def __init__(self, parent, text="", variable=None, command=None, font=("Segoe UI", 9), **kw):
        bg = kw.pop("bg", None) or tk_widget_bg(parent)
        super().__init__(parent, bg=bg, cursor="hand2", **kw)
        self._bg = bg
        self._var = variable if variable is not None else tk.BooleanVar(value=False)
        self._command = command
        self._text = text
        self._font = font
        self._disabled = False
        self._c = tk.Canvas(
            self,
            width=self._BOX,
            height=self._BOX,
            highlightthickness=0,
            bg=bg,
            cursor="hand2",
        )
        self._c.pack(side="left", padx=(0, 8))
        self._lbl = tk.Label(
            self,
            text=text,
            bg=bg,
            fg=C["text3"],
            font=font,
            anchor="w",
            justify="left",
            cursor="hand2",
        )
        self._lbl.pack(side="left", fill="x", expand=True)
        for w in (self, self._c, self._lbl):
            w.bind("<Button-1>", self._on_click)
        self._var.trace_add("write", lambda *_a: self.after_idle(self._redraw))
        self._redraw()

    def _on_click(self, _event=None):
        if self._disabled:
            return
        self._var.set(not bool(self._var.get()))
        if self._command:
            self._command()

    def _redraw(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        checked = bool(self._var.get())
        c = self._c
        c.delete("all")
        pad = 2
        x1, y1, x2, y2 = pad, pad, self._BOX - pad, self._BOX - pad
        if self._disabled:
            c.create_rectangle(x1, y1, x2, y2, outline=C["border"], fill=C["bg3"], width=2)
            self._lbl.configure(fg=C["text3"])
            return
        if checked:
            c.create_rectangle(x1, y1, x2, y2, outline=C["purple2"], fill=C["purple"], width=2)
            c.create_line(5, 10, 8, 14, 15, 6, fill="#ffffff", width=2, capstyle="round", joinstyle="round")
            self._lbl.configure(fg=C["text"], font=self._font)
        else:
            c.create_rectangle(x1, y1, x2, y2, outline=C["border2"], fill=C["card"], width=2)
            self._lbl.configure(fg=C["text2"], font=self._font)

    def configure(self, cnf=None, **kw):
        if cnf and isinstance(cnf, dict):
            kw = dict(cnf, **kw)
        if "text" in kw:
            self._text = kw.pop("text")
            self._lbl.configure(text=self._text)
        if "command" in kw:
            self._command = kw.pop("command")
        if "variable" in kw:
            self._var = kw.pop("variable")
            self._var.trace_add("write", lambda *_a: self.after_idle(self._redraw))
        if "font" in kw:
            self._font = kw.pop("font")
            self._lbl.configure(font=self._font)
        if "bg" in kw:
            self._bg = kw.pop("bg")
            super().configure(bg=self._bg)
            self._c.configure(bg=self._bg)
            self._lbl.configure(bg=self._bg)
        st = kw.pop("state", None)
        if st is not None:
            self._disabled = str(st) == "disabled"
            cur = "" if self._disabled else "hand2"
            try:
                super().configure(cursor=cur)
                self._c.configure(cursor=cur)
                self._lbl.configure(cursor=cur)
            except tk.TclError:
                pass
        if kw:
            super().configure(**kw)
        self.after_idle(self._redraw)

    config = configure


class DarkRadiobutton(tk.Frame):
    """Botão de opção desenhado (ponto interior visível quando seleccionado)."""

    _SZ = 20

    def __init__(
        self,
        parent,
        text="",
        variable=None,
        value="",
        command=None,
        font=("Segoe UI", 9),
        **kw,
    ):
        bg = kw.pop("bg", None) or tk_widget_bg(parent)
        super().__init__(parent, bg=bg, cursor="hand2", **kw)
        self._bg = bg
        self._var = variable if variable is not None else tk.StringVar()
        self._value = value
        self._command = command
        self._font = font
        self._disabled = False
        self._c = tk.Canvas(
            self,
            width=self._SZ,
            height=self._SZ,
            highlightthickness=0,
            bg=bg,
            cursor="hand2",
        )
        self._c.pack(side="left", padx=(0, 8))
        self._lbl = tk.Label(
            self,
            text=text,
            bg=bg,
            fg=C["text2"],
            font=font,
            anchor="w",
            cursor="hand2",
        )
        self._lbl.pack(side="left", fill="x", expand=True)
        for w in (self, self._c, self._lbl):
            w.bind("<Button-1>", self._on_click)
        self._var.trace_add("write", lambda *_a: self.after_idle(self._redraw))
        self._redraw()

    def _on_click(self, _event=None):
        if self._disabled:
            return
        self._var.set(self._value)
        if self._command:
            self._command()

    def _redraw(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        selected = str(self._var.get()) == str(self._value)
        c = self._c
        c.delete("all")
        cx, cy = self._SZ // 2, self._SZ // 2
        r_out = 9
        r_in = 5
        if self._disabled:
            c.create_oval(cx - r_out, cy - r_out, cx + r_out, cy + r_out, outline=C["border"], width=2)
            self._lbl.configure(fg=C["text3"])
            return
        if selected:
            c.create_oval(
                cx - r_out,
                cy - r_out,
                cx + r_out,
                cy + r_out,
                outline=C["purple2"],
                fill=C["card"],
                width=2,
            )
            c.create_oval(
                cx - r_in,
                cy - r_in,
                cx + r_in,
                cy + r_in,
                outline=C["purple"],
                fill=C["purple"],
                width=1,
            )
            self._lbl.configure(fg=C["text"], font=self._font)
        else:
            c.create_oval(
                cx - r_out,
                cy - r_out,
                cx + r_out,
                cy + r_out,
                outline=C["border2"],
                fill=C["bg3"],
                width=2,
            )
            self._lbl.configure(fg=C["text2"], font=self._font)

    def configure(self, cnf=None, **kw):
        if cnf and isinstance(cnf, dict):
            kw = dict(cnf, **kw)
        if "text" in kw:
            self._lbl.configure(text=kw.pop("text"))
        if "command" in kw:
            self._command = kw.pop("command")
        if "variable" in kw:
            self._var = kw.pop("variable")
            self._var.trace_add("write", lambda *_a: self.after_idle(self._redraw))
        if "value" in kw:
            self._value = kw.pop("value")
        if "font" in kw:
            self._font = kw.pop("font")
            self._lbl.configure(font=self._font)
        if "bg" in kw:
            self._bg = kw.pop("bg")
            super().configure(bg=self._bg)
            self._c.configure(bg=self._bg)
            self._lbl.configure(bg=self._bg)
        st = kw.pop("state", None)
        if st is not None:
            self._disabled = str(st) == "disabled"
            cur = "" if self._disabled else "hand2"
            try:
                super().configure(cursor=cur)
                self._c.configure(cursor=cur)
                self._lbl.configure(cursor=cur)
            except tk.TclError:
                pass
        if kw:
            super().configure(**kw)
        self.after_idle(self._redraw)

    config = configure


class DarkEntry(tk.Frame):
    """Campo de texto com moldura arredondada.

    O ``Entry`` é filho deste ``Frame`` e fica *por cima* do ``Canvas`` (só decoração).
    Evita ``create_window`` no canvas, que no Windows costuma bloquear clique/teclado.
    """

    _radius = 12
    _FRAME_OPTS = frozenset(
        {
            "bg",
            "width",
            "height",
            "name",
            "cursor",
            "takefocus",
            "highlightthickness",
            "highlightbackground",
            "highlightcolor",
            "bd",
            "borderwidth",
            "relief",
            "padx",
            "pady",
        }
    )

    def __init__(self, parent, **kwargs):
        entry_kw = {}
        for k in ("show", "exportselection", "width", "font", "fg", "insertbackground", "state"):
            if k in kwargs:
                entry_kw[k] = kwargs.pop(k)
        frame_kw = {k: kwargs.pop(k) for k in list(kwargs.keys()) if k in DarkEntry._FRAME_OPTS}
        frame_kw.setdefault("bg", tk_widget_bg(parent))
        super().__init__(parent, **frame_kw)

        self._focus_ring = False
        self._canvas = tk.Canvas(
            self,
            height=40,
            highlightthickness=0,
            bg=self.cget("bg"),
        )
        self._canvas.pack(fill="both", expand=True)
        self._entry = tk.Entry(
            self,
            bg=C["bg3"],
            fg=C["text"],
            insertbackground=C["purple2"],
            relief="flat",
            bd=0,
            highlightthickness=0,
            takefocus=True,
            font=entry_kw.get("font", ("Segoe UI", 11)),
            **{k: v for k, v in entry_kw.items() if k != "font"},
        )

        def _focus_in(_e=None):
            self._set_focus_ring(True)

        def _focus_out(_e=None):
            self._set_focus_ring(False)

        self._entry.bind("<FocusIn>", _focus_in, add="+")
        self._entry.bind("<FocusOut>", _focus_out, add="+")
        self._de_cfg_job = None

        def _on_canvas_resize(_e):
            if self._de_cfg_job is not None:
                try:
                    self.after_cancel(self._de_cfg_job)
                except tk.TclError:
                    pass
            self._de_cfg_job = self.after(28, _layout_run)

        def _layout_run():
            self._de_cfg_job = None
            self._layout()

        self._canvas.bind("<Configure>", _on_canvas_resize)
        self._canvas.bind("<Button-1>", lambda e: self._entry.focus_set())
        self.bind("<Button-1>", lambda e: self._entry.focus_set())

    def _set_focus_ring(self, on):
        self._focus_ring = bool(on)
        self._layout()

    def _layout(self, event=None):
        if getattr(self, "_canvas", None) is None or getattr(self, "_entry", None) is None:
            return
        W = max(int(self._canvas.winfo_width()), 40)
        H = max(int(self._canvas.winfo_height()), 34)
        self._canvas.delete("edge", "face")
        r = self._radius
        edge = C["purple2"] if self._focus_ring else C["border"]
        ri = max(4, r - 2)
        canvas_round_fill(self._canvas, 0, 0, W, H, r, edge, tag="edge", holder=self)
        canvas_round_fill(self._canvas, 2, 2, W - 2, H - 2, ri, C["bg3"], tag="face", holder=self)
        inset_x = 10
        inset_y = max(5, (H - 22) // 2)
        ew = max(12, W - inset_x * 2)
        eh = max(18, H - inset_y * 2)
        try:
            self._entry.place(in_=self, x=inset_x, y=inset_y, width=ew, height=eh)
            self._entry.lift(self._canvas)
        except tk.TclError:
            pass

    def get(self):
        e = getattr(self, "_entry", None)
        return e.get() if e else ""

    def delete(self, first, last=None):
        e = getattr(self, "_entry", None)
        if e:
            return e.delete(first, last)

    def insert(self, index, string):
        e = getattr(self, "_entry", None)
        if e:
            return e.insert(index, string)

    def icursor(self, index):
        e = getattr(self, "_entry", None)
        if e:
            return e.icursor(index)

    def index(self, index):
        e = getattr(self, "_entry", None)
        if e:
            return e.index(index)

    def configure(self, cnf=None, **kw):
        if cnf and isinstance(cnf, dict):
            kw = dict(cnf, **kw)
        frame_kw = {}
        entry_kw = {}
        for k, v in list(kw.items()):
            if k in ("bg", "highlightbackground", "highlightthickness"):
                frame_kw[k] = v
            elif k in (
                "fg",
                "font",
                "show",
                "width",
                "state",
                "insertbackground",
                "exportselection",
            ):
                entry_kw[k] = v
        if frame_kw:
            super().configure(**frame_kw)
            try:
                if getattr(self, "_canvas", None):
                    self._canvas.configure(bg=self.cget("bg"))
            except tk.TclError:
                pass
        e = getattr(self, "_entry", None)
        if entry_kw and e is not None:
            e.configure(**entry_kw)
        if getattr(self, "_canvas", None) is not None:
            self.after_idle(self._layout)

    config = configure

    def bind(self, sequence=None, func=None, add=None):
        e = getattr(self, "_entry", None)
        if e is not None:
            return e.bind(sequence, func, add)
        return super().bind(sequence, func, add)

    def unbind(self, sequence):
        e = getattr(self, "_entry", None)
        if e is not None:
            return e.unbind(sequence)
        return super().unbind(sequence)

    def cget(self, key):
        e = getattr(self, "_entry", None)
        if e is not None and key in ("fg", "bg", "font", "show", "width", "state"):
            try:
                return e.cget(key)
            except tk.TclError:
                pass
        return super().cget(key)

    def focus_set(self):
        e = getattr(self, "_entry", None)
        if e is not None:
            return e.focus_set()
        return super().focus_set()

    def focus_force(self):
        e = getattr(self, "_entry", None)
        if e is not None:
            return e.focus_force()
        return super().focus_force()


class NavPillButton(tk.Canvas):
    """Botão da barra lateral com cantos arredondados."""

    _radius = 12

    def __init__(self, parent, text, command, **kwargs):
        self._text = text
        self._command = command
        self._active = False
        self._hover = False
        self._pressed = False
        kw = {k: v for k, v in kwargs.items() if k in ("cursor", "takefocus")}
        super().__init__(
            parent,
            height=40,
            highlightthickness=0,
            cursor=kw.get("cursor", "hand2"),
            takefocus=kw.get("takefocus", 0),
        )
        self.configure(bg=tk_widget_bg(parent))
        self._np_cfg_job = None
        self._np_last_wh = None
        self.bind("<Configure>", self._on_np_configure_resize)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)

    def _on_np_configure_resize(self, _event=None):
        if self._np_cfg_job is not None:
            try:
                self.after_cancel(self._np_cfg_job)
            except tk.TclError:
                pass
        self._np_cfg_job = self.after(90, self._np_draw_after_resize)

    def _np_draw_after_resize(self):
        self._np_cfg_job = None
        try:
            wh = (int(self.winfo_width()), int(self.winfo_height()))
        except tk.TclError:
            return
        if wh == self._np_last_wh:
            return
        self._draw()

    def set_active(self, active: bool):
        self._active = bool(active)
        self._draw()

    def _enter(self, _e=None):
        self._hover = True
        self._draw()

    def _leave(self, _e=None):
        self._hover = False
        self._pressed = False
        self._draw()

    def _press(self, _e=None):
        self._pressed = True
        self._draw()

    def _release(self, event=None):
        was = self._pressed
        self._pressed = False
        self._draw()
        if was and self._command and event is not None:
            try:
                x, y = event.x, event.y
                if 0 <= x < int(self.winfo_width()) and 0 <= y < int(self.winfo_height()):
                    self._command()
            except tk.TclError:
                pass

    def _draw(self, event=None):
        w = max(int(self.winfo_width()), 20)
        h = max(int(self.winfo_height()), 36)
        self._np_last_wh = (w, h)
        self.delete("fill", "txt", "ring")
        if self._active:
            face = C["bg3"]
            fg = C["purple3"]
            edge = C["purple"]
        elif self._hover:
            face = C["bg3"]
            fg = C["text"]
            edge = C["border2"]
        else:
            face = C["bg2"]
            fg = C["text2"]
            edge = C["bg2"]
        rr = min(self._radius, h // 2 - 1)
        canvas_round_fill(self, 2, 2, w - 2, h - 2, rr, edge, tag="ring", holder=self)
        ri = max(3, rr - 2)
        canvas_round_fill(self, 3, 3, w - 3, h - 3, ri, face, tag="fill", holder=self)
        self.create_text(14, h // 2, text=self._text, anchor="w", fill=fg, font=("Segoe UI", 10), tags=("txt",))


class RoundedCard(tk.Canvas):
    """Painel com cantos arredondados; use ``.inner`` para o conteúdo."""

    def __init__(self, parent, *, radius=18, margin=12, fill_key="card", **kwargs):
        self._r = radius
        self._m = margin
        self._fill_key = fill_key if fill_key in C else "card"
        kw = {k: v for k, v in kwargs.items() if k in ("highlightthickness",)}
        super().__init__(parent, highlightthickness=kw.get("highlightthickness", 0), bg=tk_widget_bg(parent))
        self.inner = tk.Frame(self, bg=C[self._fill_key])
        self._win_id = None
        self._rc_cfg_job = None
        self._rc_last_wh = None
        self.bind("<Configure>", self._on_rc_configure)

    def _on_rc_configure(self, _event=None):
        if self._rc_cfg_job is not None:
            try:
                self.after_cancel(self._rc_cfg_job)
            except tk.TclError:
                pass
        self._rc_cfg_job = self.after(24, self._refit_run)

    def _refit_run(self):
        self._rc_cfg_job = None
        self._refit()

    def _refit(self, event=None):
        W = max(int(self.winfo_width()), self._m * 2 + 40)
        H = max(int(self.winfo_height()), self._m * 2 + 40)
        if self._rc_last_wh == (W, H):
            return
        self._rc_last_wh = (W, H)
        self.delete("edge", "face")
        fill = C[self._fill_key]
        edge = C["border"]
        canvas_round_fill(self, 0, 0, W, H, self._r, edge, tag="edge", holder=self)
        ri = max(4, self._r - 2)
        canvas_round_fill(self, 2, 2, W - 2, H - 2, ri, fill, tag="face", holder=self)
        ix = self._m
        iy = self._m
        iw = max(20, W - 2 * self._m)
        ih = max(20, H - 2 * self._m)
        self.inner.configure(bg=fill)
        if self._win_id is None:
            self._win_id = self.create_window(ix, iy, window=self.inner, anchor="nw", width=iw, height=ih)
        else:
            self.coords(self._win_id, ix, iy)
            self.itemconfigure(self._win_id, width=iw, height=ih)


class ModernScrollbar(tk.Canvas):
    """
    Barra de scroll vertical ou horizontal com trilho e polegar arredondados
    (Pillow quando disponível; caso contrário vectorial).
    Compatível com ``canvas.yview`` / ``xview`` e ``set(frac_lo, frac_hi)``.
    """

    _pad = 5
    _min_thumb = 26
    _side_margin = 2
    _thumb_inset = 1

    def __init__(self, parent, command, orient="vertical", bar_width=12, **kwargs):
        self._command = command
        self._orient = str(orient or "vertical").lower()
        self._bw = max(10, int(bar_width))
        ibg = kwargs.pop("bg", tk_widget_bg(parent))
        kwargs.setdefault("highlightthickness", 0)
        if self._orient == "vertical":
            super().__init__(parent, width=self._bw, bg=ibg, **kwargs)
        else:
            super().__init__(parent, height=self._bw, bg=ibg, **kwargs)
        self._ibg = ibg
        self._frac_lo = 0.0
        self._frac_hi = 1.0
        self._drag = False
        self._hover = False
        self._hover_thumb = False
        self._thumb_hit = None
        self._sb_cfg_job = None
        def _on_sb_configure(_e):
            if self._sb_cfg_job is not None:
                try:
                    self.after_cancel(self._sb_cfg_job)
                except tk.TclError:
                    pass
            self._sb_cfg_job = self.after(28, _sb_configure_draw)

        def _sb_configure_draw():
            self._sb_cfg_job = None
            self._draw()

        self.bind("<Configure>", _on_sb_configure)
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Motion>", self._on_motion_hover)
        self.after_idle(self._draw)
        try:
            cur = "sb_v_double_arrow" if self._orient == "vertical" else "sb_h_double_arrow"
            self.configure(cursor=cur)
        except tk.TclError:
            pass

    def _set_hover(self, on):
        self._hover = bool(on)
        if not on:
            self._hover_thumb = False
        if not self._drag:
            self._draw()

    def _on_motion_hover(self, e):
        if self._drag:
            return
        inside = self._hit_thumb(e.x, e.y)
        if inside != self._hover_thumb:
            self._hover_thumb = inside
            self._draw()

    def set(self, *args):
        """Callback ``yscrollcommand`` / ``xscrollcommand``."""
        try:
            if len(args) == 2:
                lo, hi = float(args[0]), float(args[1])
            elif len(args) == 1 and isinstance(args[0], (tuple, list)) and len(args[0]) >= 2:
                lo, hi = float(args[0][0]), float(args[0][1])
            else:
                return
        except (TypeError, ValueError, IndexError):
            return
        lo = max(0.0, min(1.0, lo))
        hi = max(0.0, min(1.0, hi))
        if hi < lo:
            lo, hi = hi, lo
        self._frac_lo = lo
        self._frac_hi = hi
        self.after_idle(self._draw)

    def _trough_thumb_colors(self):
        trough = C.get("sb_trough", C.get("border", "#2a2a2a"))
        thumb = C.get("sb_thumb", C.get("border2", "#3a3a3a"))
        thumb_hot = C.get("sb_thumb_hover", C.get("border2", "#3a3a3a"))
        thumb_accent = C.get("sb_thumb_active", C.get("purple2", "#a78bfa"))
        return trough, thumb, thumb_hot, thumb_accent

    def _hit_thumb(self, x, y):
        h = self._thumb_hit
        if not h:
            return False
        x0, y0, x1, y1 = h
        return x0 <= x <= x1 and y0 <= y <= y1

    def _track_span(self, total: int) -> Tuple[int, int, int]:
        """Largura/altura do trilho e coordenada inicial, centrados no canvas."""
        margin = self._side_margin
        span = max(4, min(self._bw - margin * 2, total - margin * 2))
        start = int(round((total - span) * 0.5))
        start = max(0, min(start, max(0, total - span)))
        return start, start + span, span

    def _thumb_span(self, track_start: int, track_span: int) -> Tuple[int, int, int]:
        """Polegar centrado no trilho com inset simétrico."""
        inset = self._thumb_inset
        thumb_span = max(4, track_span - inset * 2)
        off = int(round((track_span - thumb_span) * 0.5))
        thumb_start = track_start + off
        return thumb_start, thumb_start + thumb_span, thumb_span

    def _sb_draw_pill(self, x0, y0, x1, y1, fill: str, tag: str) -> None:
        """Cápsula antialiased com bounds inteiros (evita pixels «serrilhados»)."""
        xi0 = int(round(float(x0)))
        yi0 = int(round(float(y0)))
        xi1 = int(round(float(x1)))
        yi1 = int(round(float(y1)))
        if xi1 <= xi0:
            xi1 = xi0 + 1
        if yi1 <= yi0:
            yi1 = yi0 + 1
        w, h = xi1 - xi0, yi1 - yi0
        r = pill_corner_radius(w, h)
        canvas_round_fill_sb(self, xi0, yi0, xi1, yi1, r, fill, tag=tag, holder=self)

    def _vertical_metrics(self, W: int, H: int):
        pad = self._pad
        track_x0, track_x1, track_w = self._track_span(W)
        track_y0, track_y1 = pad, H - pad
        track_h = max(self._min_thumb * 2, track_y1 - track_y0)
        thumb_x0, thumb_x1, thumb_w = self._thumb_span(track_x0, track_w)
        return track_x0, track_y0, track_x1, track_y1, track_w, track_h, thumb_x0, thumb_x1, thumb_w

    def _horizontal_metrics(self, W: int, H: int):
        pad = self._pad
        track_y0, track_y1, track_h = self._track_span(H)
        track_x0, track_x1 = pad, W - pad
        track_w = max(self._min_thumb * 2, track_x1 - track_x0)
        thumb_y0, thumb_y1, thumb_h = self._thumb_span(track_y0, track_h)
        return track_x0, track_y0, track_x1, track_y1, track_w, track_h, thumb_y0, thumb_y1, thumb_h

    def _draw(self):
        self.delete("all")
        try:
            W = int(self.winfo_width())
            H = int(self.winfo_height())
        except tk.TclError:
            return
        if self._orient == "vertical":
            if W < 6 or H < 16:
                return
            self._draw_vertical(W, H)
        else:
            if H < 6 or W < 16:
                return
            self._draw_horizontal(W, H)

    def _draw_vertical(self, W, H):
        (
            track_x0,
            track_y0,
            _track_x1,
            _track_y1,
            track_w,
            track_h,
            thumb_x0,
            thumb_x1,
            thumb_w,
        ) = self._vertical_metrics(W, H)
        trough_c, thumb_c, thumb_hot, thumb_ac = self._trough_thumb_colors()
        self._sb_draw_pill(
            track_x0,
            track_y0,
            track_x0 + track_w,
            track_y0 + track_h,
            trough_c,
            "trough",
        )
        lo, hi = self._frac_lo, self._frac_hi
        delta = max(1e-9, float(hi) - float(lo))
        thumb_h = max(self._min_thumb, int(delta * track_h + 0.5))
        thumb_h = min(thumb_h, track_h)
        if delta >= 1.0 - 1e-6:
            thumb_y = int(track_y0)
            thumb_h = int(track_h)
        else:
            span = max(1, track_h - thumb_h)
            thumb_y = int(round(
                float(track_y0) + (float(lo) / (1.0 - delta)) * float(span)
            ))
            thumb_y = max(int(track_y0), min(int(track_y0 + track_h - thumb_h), thumb_y))
        if self._drag:
            col = thumb_ac
        elif self._hover_thumb:
            col = thumb_hot
        else:
            col = thumb_c
        self._sb_draw_pill(thumb_x0, thumb_y, thumb_x1, thumb_y + thumb_h, col, "thumb")
        self._thumb_hit = (thumb_x0, thumb_y, thumb_x1, thumb_y + thumb_h)

    def _draw_horizontal(self, W, H):
        (
            track_x0,
            track_y0,
            _track_x1,
            _track_y1,
            track_w,
            track_h,
            thumb_y0,
            thumb_y1,
            thumb_h_px,
        ) = self._horizontal_metrics(W, H)
        trough_c, thumb_c, thumb_hot, thumb_ac = self._trough_thumb_colors()
        self._sb_draw_pill(
            track_x0,
            track_y0,
            track_x0 + track_w,
            track_y0 + track_h,
            trough_c,
            "trough",
        )
        lo, hi = self._frac_lo, self._frac_hi
        delta = max(1e-9, float(hi) - float(lo))
        thumb_w = max(self._min_thumb, int(delta * track_w + 0.5))
        thumb_w = min(thumb_w, track_w)
        if delta >= 1.0 - 1e-6:
            thumb_x = int(track_x0)
            thumb_w = int(track_w)
        else:
            span = max(1, track_w - thumb_w)
            thumb_x = int(round(
                float(track_x0) + (float(lo) / (1.0 - delta)) * float(span)
            ))
            thumb_x = max(int(track_x0), min(int(track_x0 + track_w - thumb_w), thumb_x))
        if self._drag:
            col = thumb_ac
        elif self._hover_thumb:
            col = thumb_hot
        else:
            col = thumb_c
        self._sb_draw_pill(thumb_x, thumb_y0, thumb_x + thumb_w, thumb_y1, col, "thumb")
        self._thumb_hit = (thumb_x, thumb_y0, thumb_x + thumb_w, thumb_y1)

    def _on_press(self, event):
        if self._orient == "vertical":
            self._press_vertical(event)
        else:
            self._press_horizontal(event)

    def _press_vertical(self, event):
        if not self._thumb_hit:
            self._draw()
        if not self._thumb_hit:
            return
        x0, y0, x1, y1 = self._thumb_hit
        if y0 <= event.y <= y1 and x0 <= event.x <= x1:
            self._drag = True
            self._draw()
        elif event.y < y0:
            self._command("scroll", -1, "pages")
        else:
            self._command("scroll", 1, "pages")

    def _press_horizontal(self, event):
        if not self._thumb_hit:
            self._draw()
        if not self._thumb_hit:
            return
        x0, y0, x1, y1 = self._thumb_hit
        if x0 <= event.x <= x1 and y0 <= event.y <= y1:
            self._drag = True
            self._draw()
        elif event.x < x0:
            self._command("scroll", -1, "pages")
        else:
            self._command("scroll", 1, "pages")

    def _on_motion(self, event):
        if not self._drag:
            return
        if self._orient == "vertical":
            self._motion_vertical(event)
        else:
            self._motion_horizontal(event)

    def _motion_vertical(self, event):
        try:
            W = int(self.winfo_width())
            H = int(self.winfo_height())
        except tk.TclError:
            return
        _track_x0, track_y0, _tx1, _ty1, _tw, track_h, *_rest = self._vertical_metrics(W, H)
        lo, hi = self._frac_lo, self._frac_hi
        delta = max(1e-9, float(hi) - float(lo))
        thumb_h = max(self._min_thumb, int(delta * track_h + 0.5))
        thumb_h = min(thumb_h, track_h)
        span = max(1, track_h - thumb_h)
        center = float(event.y)
        nlo = (center - float(track_y0) - float(thumb_h) * 0.5) / float(span) * (1.0 - delta)
        nlo = max(0.0, min(1.0 - delta, nlo))
        self._command("moveto", nlo)

    def _motion_horizontal(self, event):
        try:
            W = int(self.winfo_width())
            H = int(self.winfo_height())
        except tk.TclError:
            return
        track_x0, _ty0, track_x1, _ty1, track_w, *_rest = self._horizontal_metrics(W, H)
        lo, hi = self._frac_lo, self._frac_hi
        delta = max(1e-9, float(hi) - float(lo))
        thumb_w = max(self._min_thumb, int(delta * track_w + 0.5))
        thumb_w = min(thumb_w, track_w)
        span = max(1, track_w - thumb_w)
        center = float(event.x)
        nlo = (center - float(track_x0) - float(thumb_w) * 0.5) / float(span) * (1.0 - delta)
        nlo = max(0.0, min(1.0 - delta, nlo))
        self._command("moveto", nlo)

    def _on_release(self, event):
        self._drag = False
        self._draw()


class ScrollableFrame(tk.Frame):
    """Scroll vertical; sincroniza largura do frame interno com o Canvas (evita texto espremido)."""

    def __init__(self, parent, inner_bg=None, **kwargs):
        ibg = inner_bg if inner_bg is not None else C["bg"]
        super().__init__(parent, bg=ibg, **kwargs)
        canvas = tk.Canvas(self, bg=ibg, highlightthickness=0)
        scrollbar = ModernScrollbar(self, canvas.yview, orient="vertical", bar_width=13, bg=ibg)
        self.inner = tk.Frame(canvas, bg=ibg)
        self._canvas = canvas
        inner_win = canvas.create_window((0, 0), window=self.inner, anchor="nw")

        _sr_job = [None]

        def _on_inner_configure(_event=None):
            if _sr_job[0] is not None:
                try:
                    self.after_cancel(_sr_job[0])
                except tk.TclError:
                    pass
            _sr_job[0] = self.after(24, _apply_scrollregion)

        def _apply_scrollregion():
            _sr_job[0] = None
            try:
                canvas.configure(scrollregion=canvas.bbox("all"))
            except tk.TclError:
                pass

        self._last_canvas_inner_w = None

        def _on_canvas_configure(event):
            # Sem isto, inner mantém largura ~1px e labels viram traços/pontos (Windows/Tk).
            try:
                w = int(event.width)
            except (TypeError, ValueError, tk.TclError):
                return
            if w < 2:
                return
            if self._last_canvas_inner_w == w:
                return
            self._last_canvas_inner_w = w
            try:
                canvas.itemconfigure(inner_win, width=w)
            except tk.TclError:
                pass

        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _wheel_win(event):
            try:
                d = int(getattr(event, "delta", 0) or 0)
            except (TypeError, ValueError):
                d = 0
            if d:
                canvas.yview_scroll(int(-1 * (d / 120)), "units")
            return "break"

        def _wheel_linux_up(_event):
            canvas.yview_scroll(-1, "units")
            return "break"

        def _wheel_linux_down(_event):
            canvas.yview_scroll(1, "units")
            return "break"

        def _bind_wheel_recursive(widget):
            """Roda do rato passa nos filhos do inner, não no canvas — ligamos em toda a árvore."""
            try:
                widget.bind("<MouseWheel>", _wheel_win)
                widget.bind("<Button-4>", _wheel_linux_up)
                widget.bind("<Button-5>", _wheel_linux_down)
            except tk.TclError:
                return
            for ch in widget.winfo_children():
                _bind_wheel_recursive(ch)

        _rebind_job = [None]

        def _schedule_rebind_wheel(_event=None):
            if _rebind_job[0] is not None:
                try:
                    self.after_cancel(_rebind_job[0])
                except tk.TclError:
                    pass
            _rebind_job[0] = self.after(220, _run_rebind_wheel)

        def _run_rebind_wheel():
            _rebind_job[0] = None
            _bind_wheel_recursive(self.inner)

        def _on_inner_configure_full(event=None):
            _on_inner_configure(event)
            _schedule_rebind_wheel(event)

        self.inner.bind("<Configure>", _on_inner_configure_full)

        canvas.bind("<MouseWheel>", _wheel_win)
        canvas.bind("<Button-4>", _wheel_linux_up)
        canvas.bind("<Button-5>", _wheel_linux_down)
        scrollbar.bind("<MouseWheel>", _wheel_win)
        scrollbar.bind("<Button-4>", _wheel_linux_up)
        scrollbar.bind("<Button-5>", _wheel_linux_down)
        # Não forçar focus no canvas ao passar o rato: em Toplevel (janela do item) isto no Windows
        # pode empurrar a janela para segundo plano ou baralhar a ordem Z com a janela principal.

        def _sync_inner_width():
            try:
                w = canvas.winfo_width()
                if w > 1:
                    canvas.itemconfigure(inner_win, width=w)
            except tk.TclError:
                pass

        self.after_idle(_sync_inner_width)
        self.after_idle(_run_rebind_wheel)

    def yview_top(self):
        """Repor o scroll no topo (útil ao voltar a abrir Configurações)."""
        try:
            self._canvas.yview_moveto(0.0)
        except tk.TclError:
            pass
