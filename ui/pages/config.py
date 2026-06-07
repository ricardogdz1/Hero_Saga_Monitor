"""
Página Configurações (SMTP, tema, intervalos).
Mixin usado por ``HeroSagaMonitor``.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from alert_monitor import send_alert_email
from app_settings import load_settings, save_settings, set_windows_autostart
from ui.theme import C
from ui.widgets import (
    DarkButton,
    DarkCheckbutton,
    DarkEntry,
    DarkRadiobutton,
    ScrollableFrame,
)


class ConfigMixin:
    """Formulário de configurações da aplicação."""

    def _build_config(self):
        self.config_frame = tk.Frame(self.main, bg=C["bg"])
        hdr = tk.Frame(self.config_frame, bg=C["bg"])
        hdr.pack(fill="x", padx=20, pady=(20, 6))
        tk.Label(
            hdr,
            text="Configurações",
            bg=C["bg"],
            fg=C["purple3"],
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            hdr,
            text="E-mail, SMTP, tema da interface e início com o Windows",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 9),
        ).pack(anchor="w")

        scroll = ScrollableFrame(self.config_frame)
        self._config_scroll = scroll
        scroll.pack(fill="both", expand=True, padx=20, pady=8)
        inner = scroll.inner

        self._cfg_fields = {}

        def add_row(parent, label, key, password=False, width=44):
            fr = tk.Frame(parent, bg=C["bg"])
            fr.pack(fill="x", pady=4)
            tk.Label(
                fr,
                text=label,
                bg=C["bg"],
                fg=C["text"],
                width=26,
                anchor="w",
                font=("Segoe UI", 9),
            ).pack(side="left", padx=(0, 8))
            e = DarkEntry(fr, width=width)
            if password:
                e.configure(show="*")
            e.pack(side="left", fill="x", expand=True)
            self._cfg_fields[key] = e

        s = load_settings()

        mail_hdr = tk.Frame(inner, bg=C["bg"])
        mail_hdr.pack(fill="x", pady=(0, 8))
        tk.Label(
            mail_hdr,
            text="Notificações por e-mail (SMTP)",
            bg=C["bg"],
            fg=C["text"],
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        tk.Label(
            mail_hdr,
            text="Usados para enviar os alertas de preço por e-mail. Role para ver mais opções.",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 8),
            wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        add_row(inner, "E-mail destino (padrão)", "notify_email")
        self._cfg_fields["notify_email"].insert(0, s.get("notify_email") or "")
        add_row(inner, "SMTP servidor", "smtp_host")
        self._cfg_fields["smtp_host"].insert(0, s.get("smtp_host") or "")
        add_row(inner, "SMTP porta", "smtp_port")
        self._cfg_fields["smtp_port"].insert(0, str(s.get("smtp_port") or 587))
        add_row(inner, "SMTP utilizador", "smtp_user")
        self._cfg_fields["smtp_user"].insert(0, s.get("smtp_user") or "")
        add_row(inner, "SMTP palavra-passe", "smtp_password", password=True)
        self._cfg_fields["smtp_password"].insert(0, s.get("smtp_password") or "")

        tls_fr = tk.Frame(inner, bg=C["bg"])
        tls_fr.pack(fill="x", pady=6)
        self._cfg_tls = tk.BooleanVar(value=bool(s.get("smtp_use_tls", True)))
        DarkCheckbutton(
            tls_fr,
            text="Usar TLS (STARTTLS, porta 587 — recomendado Gmail/Outlook)",
            variable=self._cfg_tls,
            bg=C["bg"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", fill="x")

        tk.Label(
            inner,
            text="A senha fica salva apenas neste computador.",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 8),
            wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(10, 14))

        dp_fr = tk.Frame(inner, bg=C["bg"])
        dp_fr.pack(fill="x", pady=(0, 14))
        tk.Label(
            dp_fr,
            text="Divine Pride (API opcional)",
            bg=C["bg"],
            fg=C["text"],
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        tk.Label(
            dp_fr,
            text="Opcional: traz os nomes dos MVPs em inglês. Peça a chave em divine-pride.net/api. "
            "O servidor (ex.: iRO) define a origem dos dados.",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 8),
            wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        add_row(dp_fr, "Chave API Divine Pride", "divine_pride_api_key", password=True, width=40)
        self._cfg_fields["divine_pride_api_key"].insert(0, s.get("divine_pride_api_key") or "")
        add_row(dp_fr, "Servidor DP (iRO, bRO…)", "divine_pride_server", width=12)
        self._cfg_fields["divine_pride_server"].insert(0, s.get("divine_pride_server") or "iRO")

        theme_fr = tk.Frame(inner, bg=C["bg"])
        theme_fr.pack(fill="x", pady=(0, 14))
        tk.Label(
            theme_fr,
            text="Tema da interface",
            bg=C["bg"],
            fg=C["text"],
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=(0, 6))
        self._cfg_theme = tk.StringVar(value=s.get("ui_theme", "dark"))
        DarkRadiobutton(
            theme_fr,
            text="Escuro (preto e cinza)",
            variable=self._cfg_theme,
            value="dark",
            bg=C["bg"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", fill="x", pady=1)
        DarkRadiobutton(
            theme_fr,
            text="Claro",
            variable=self._cfg_theme,
            value="light",
            bg=C["bg"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", fill="x", pady=1)

        mh_home_fr = tk.Frame(inner, bg=C["bg"])
        mh_home_fr.pack(fill="x", pady=(0, 14))
        tk.Label(
            mh_home_fr,
            text="Colunas dos monitorados (página Buscar)",
            bg=C["bg"],
            fg=C["text"],
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        tk.Label(
            mh_home_fr,
            text="Define quantas colunas de monitorados cabem na página Buscar. "
            "Largura mínima por coluna (160–600 px) e quantas tentar exibir (1–8). "
            "Salve e reabra «Buscar Item» para ver.",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 8),
            wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        add_row(mh_home_fr, "Largura mín. (px)", "monitor_home_col_min_width", width=8)
        self._cfg_fields["monitor_home_col_min_width"].insert(
            0, str(s.get("monitor_home_col_min_width") or 260)
        )
        add_row(mh_home_fr, "Meta cols. visíveis", "monitor_home_min_visible_cols", width=8)
        self._cfg_fields["monitor_home_min_visible_cols"].insert(
            0, str(s.get("monitor_home_min_visible_cols") or 3)
        )

        iv_fr = tk.Frame(inner, bg=C["bg"])
        iv_fr.pack(fill="x", pady=4)
        tk.Label(
            iv_fr,
            text="Intervalo verificação alertas (s)",
            bg=C["bg"],
            fg=C["text"],
            width=26,
            anchor="w",
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(0, 8))
        self._cfg_fields["alert_interval_seconds"] = DarkEntry(iv_fr, width=12)
        self._cfg_fields["alert_interval_seconds"].insert(0, str(s.get("alert_interval_seconds") or 300))

        as_fr = tk.Frame(inner, bg=C["bg"])
        as_fr.pack(fill="x", pady=8)
        self._cfg_autostart = tk.BooleanVar(value=bool(s.get("start_with_windows", False)))
        DarkCheckbutton(
            as_fr,
            text="Iniciar o GDZ Monitor com o Windows",
            variable=self._cfg_autostart,
            bg=C["bg"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", fill="x")

        btn_fr = tk.Frame(self.config_frame, bg=C["bg"])
        btn_fr.pack(fill="x", padx=20, pady=(8, 20))

        def _save_config():
            try:
                port = int(self._cfg_fields["smtp_port"].get().strip() or "587")
            except ValueError:
                messagebox.showerror("Erro", "Porta SMTP inválida.", parent=self)
                return
            try:
                interval = int(self._cfg_fields["alert_interval_seconds"].get().strip() or "300")
            except ValueError:
                messagebox.showerror("Erro", "Intervalo inválido.", parent=self)
                return
            interval = max(60, interval)
            try:
                mhw = int(self._cfg_fields["monitor_home_col_min_width"].get().strip() or "260")
            except ValueError:
                messagebox.showerror(
                    "Erro",
                    "Largura mínima das colunas inválida (use um número).",
                    parent=self,
                )
                return
            mhw = max(160, min(600, mhw))
            try:
                mhv = int(self._cfg_fields["monitor_home_min_visible_cols"].get().strip() or "3")
            except ValueError:
                messagebox.showerror(
                    "Erro",
                    "Meta de colunas visíveis inválida (use um número inteiro).",
                    parent=self,
                )
                return
            mhv = max(1, min(8, mhv))
            data = load_settings()
            prev_theme = data.get("ui_theme", "dark")
            data["notify_email"] = self._cfg_fields["notify_email"].get().strip()
            data["smtp_host"] = self._cfg_fields["smtp_host"].get().strip()
            data["smtp_port"] = port
            data["smtp_user"] = self._cfg_fields["smtp_user"].get().strip()
            data["smtp_password"] = self._cfg_fields["smtp_password"].get()
            data["smtp_use_tls"] = self._cfg_tls.get()
            data["alert_interval_seconds"] = interval
            data["start_with_windows"] = self._cfg_autostart.get()
            data["ui_theme"] = self._cfg_theme.get()
            data["monitor_home_col_min_width"] = mhw
            data["monitor_home_min_visible_cols"] = mhv
            data["divine_pride_api_key"] = self._cfg_fields["divine_pride_api_key"].get().strip()
            data["divine_pride_server"] = self._cfg_fields["divine_pride_server"].get().strip()
            save_settings(data)
            try:
                if self.busca_frame.winfo_exists():
                    self._render_monitored_home()
            except (tk.TclError, AttributeError):
                pass
            if data.get("ui_theme") != prev_theme:
                self._reapply_theme(data.get("ui_theme", "dark"))
            ok, msg = set_windows_autostart(data["start_with_windows"])
            extra = f"\n{msg}" if msg else ""
            if not ok and data["start_with_windows"]:
                messagebox.showwarning("Início automático", f"Não foi possível activar:{extra}", parent=self)
            else:
                messagebox.showinfo("Configurações", f"Guardado.{extra}", parent=self)
            self._schedule_alert_monitor_cycle()

        def _test_email():
            st = load_settings()
            to_addr = self._cfg_fields["notify_email"].get().strip()
            if not to_addr:
                messagebox.showerror("Erro", "Indique o e-mail destino.", parent=self)
                return
            ok, err = send_alert_email(
                {
                    **st,
                    "smtp_host": self._cfg_fields["smtp_host"].get().strip(),
                    "smtp_port": int(self._cfg_fields["smtp_port"].get().strip() or "587"),
                    "smtp_user": self._cfg_fields["smtp_user"].get().strip(),
                    "smtp_password": self._cfg_fields["smtp_password"].get(),
                    "smtp_use_tls": self._cfg_tls.get(),
                },
                to_addr,
                "[GDZ] Teste de e-mail",
                "Se recebeu esta mensagem, o SMTP está configurado correctamente.",
            )
            if ok:
                messagebox.showinfo("Teste", "E-mail de teste enviado.", parent=self)
            else:
                messagebox.showerror("Teste", f"Falhou:\n{err}", parent=self)

        def _test_divine_pride():
            key = self._cfg_fields["divine_pride_api_key"].get().strip()
            srv = self._cfg_fields["divine_pride_server"].get().strip() or None
            if not key:
                messagebox.showerror(
                    "Divine Pride",
                    "Indique a chave API ou use DIVINE_PRIDE_API_KEY.",
                    parent=self,
                )
                return
            try:
                from divine_pride_api import fetch_item

                d = fetch_item(5017, api_key=key, server=srv)
                nm = d.get("name") or "?"
                messagebox.showinfo(
                    "Divine Pride",
                    f"Ligação OK. Item de teste 5017: {nm}",
                    parent=self,
                )
            except Exception as e:
                messagebox.showerror("Divine Pride", str(e), parent=self)

        DarkButton(btn_fr, text="Guardar", style="success", command=_save_config).pack(
            side="left", padx=4
        )
        DarkButton(btn_fr, text="Enviar e-mail de teste", style="primary", command=_test_email).pack(
            side="left", padx=4
        )
        DarkButton(btn_fr, text="Testar Divine Pride", style="ghost", command=_test_divine_pride).pack(
            side="left", padx=4
        )

    def _show_config(self):
        self._clear_main()
        s = load_settings()
        for key, entry in self._cfg_fields.items():
            entry.delete(0, "end")
            if key == "smtp_port":
                entry.insert(0, str(s.get(key) or 587))
            elif key == "alert_interval_seconds":
                entry.insert(0, str(s.get(key) or 300))
            elif key == "monitor_home_col_min_width":
                entry.insert(0, str(s.get(key) or 260))
            elif key == "monitor_home_min_visible_cols":
                entry.insert(0, str(s.get(key) or 3))
            else:
                entry.insert(0, str(s.get(key) or ""))
        self._cfg_tls.set(bool(s.get("smtp_use_tls", True)))
        self._cfg_autostart.set(bool(s.get("start_with_windows", False)))
        self._cfg_theme.set(s.get("ui_theme", "dark"))
        self.config_frame.pack(fill="both", expand=True)

        def _cfg_scroll_top():
            sc = getattr(self, "_config_scroll", None)
            if sc is not None:
                try:
                    sc.inner.update_idletasks()
                except tk.TclError:
                    pass
                sc.yview_top()

        self.after_idle(_cfg_scroll_top)
