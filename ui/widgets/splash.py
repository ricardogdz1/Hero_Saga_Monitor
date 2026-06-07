"""Ecrã de arranque com barra de progresso."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ui.theme import C


class StartupSplash(tk.Toplevel):
    """Janela modal com progresso enquanto a interface principal fica oculta."""

    def __init__(self, master: tk.Tk):
        super().__init__(master)
        self.title("GDZ Monitor")
        self.configure(bg=C["bg"])
        self.resizable(False, False)
        self.transient(master)
        fr = tk.Frame(self, bg=C["bg"], padx=36, pady=28)
        fr.pack(fill="both", expand=True)
        tk.Label(
            fr,
            text="⚔ GDZ MONITOR",
            bg=C["bg"],
            fg=C["purple3"],
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            fr,
            text="A inicializar o sistema…",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(2, 14))
        self._status = tk.Label(
            fr,
            text="",
            bg=C["bg"],
            fg=C["text2"],
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
            wraplength=380,
        )
        self._status.pack(anchor="w", fill="x", pady=(0, 10))
        self._prog = ttk.Progressbar(fr, mode="determinate", maximum=100, length=368)
        self._prog.pack(anchor="w")
        self.geometry("440x210")
        self.update_idletasks()
        w, h = 440, 210
        x = max(0, (self.winfo_screenwidth() - w) // 2)
        y = max(0, (self.winfo_screenheight() - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def set_progress(self, pct: float, msg: str) -> None:
        self._prog["value"] = max(0, min(100, float(pct)))
        self._status.configure(text=msg)
        self.update_idletasks()

