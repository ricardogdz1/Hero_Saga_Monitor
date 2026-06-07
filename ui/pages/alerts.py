"""
Página Alertas e ciclo de monitorização de preços.
Mixin usado por ``HeroSagaMonitor``.
"""
from __future__ import annotations

import logging
import sys
import threading
from datetime import datetime

import tkinter as tk
from tkinter import messagebox

import app_domain
from adapters import herosaga_api
from adapters.persistence import (
    _ALERTS_IO_LOCK,
    load_alerts,
    save_alerts,
)
from alert_monitor import (
    _fmt_price as _alert_fmt_price,
    _price as _alert_store_price,
    _refinement as _alert_store_refinement,
    build_email_body,
    run_alert_pass,
    send_alert_email,
)
from app_settings import load_settings
from build_simulator import (
    build_email_body_build_total,
    run_build_total_alerts,
)
from core.constants import BASE_URL
from item_icon_cache import read_item_icon_png_bytes, resolve_item_icon_url
from mvp_timer import mvp_catalog_matches_search
from services import monitored as monitored_service
from ui.theme import C
from ui.widgets import DarkButton, ScrollableFrame

import app_formatters

logger = logging.getLogger(__name__)

# Rótulos legíveis por moeda (usado no motivo e no preço do pop-up de alerta).
_ALERT_CURRENCY_LABELS = {
    "zeny": "Zeny",
    "rmt": "RMT",
    "rops": "ROPs",
    "hero_points": "Hero Points",
}

from app_runtime import get_stores_from_item_page

_normalize_media_url = herosaga_api.normalize_media_url
fmt_price_stores = app_formatters.fmt_price_stores

item_matches_search = lambda entry, q: monitored_service.item_matches_search(
    entry, q, mvp_catalog_matches_search_fn=mvp_catalog_matches_search
)


def _alert_min_refinement(alert: dict):
    return app_domain.alert_min_refinement(alert)


def _sale_min_prices_from_stores(stores: list, *, min_refinement=None) -> dict:
    return app_domain.sale_min_prices_from_stores(stores, min_refinement=min_refinement)


class AlertsMixin:
    """Lista de alertas e monitorização periódica."""

    def _refresh_alertas_display_prices_worker(self, gen: int):
        """Actualiza min_prices e ícone nos alertas (lista Alertas) e grava JSON."""
        try:
            alerts = load_alerts()
            if not alerts:
                return
            updates = {}
            for key, a in list(alerts.items()):
                if gen != self._alerts_display_refresh_gen:
                    return
                iid = a.get("item_id")
                if not iid:
                    continue
                try:
                    stores, meta = get_stores_from_item_page(int(iid), str(a.get("item_name") or ""))
                except Exception as e:
                    logger.debug("Alertas UI refresh %s: %s", iid, e)
                    continue
                upd = {
                    "min_prices": _sale_min_prices_from_stores(
                        stores, min_refinement=_alert_min_refinement(a)
                    ),
                    "home_prices_updated_at": datetime.now().isoformat(),
                }
                if meta.get("item_icon_url"):
                    upd["item_icon_url"] = _normalize_media_url(meta["item_icon_url"])
                updates[key] = upd
            if not updates or gen != self._alerts_display_refresh_gen:
                return
            with _ALERTS_IO_LOCK:
                cur = load_alerts()
                for k, u in updates.items():
                    if k in cur:
                        cur[k].update(u)
                save_alerts(cur)
            self.after(0, lambda g=gen: self._render_alertas_if_current(g))
        except Exception as e:
            logger.exception("Refresh alertas (UI): %s", e)

    def _render_alertas_if_current(self, gen: int):
        if gen != self._alerts_display_refresh_gen:
            return
        if self.current_page.get() != "alertas":
            return
        self._render_alertas()

    # ── ALERTAS ──────────────────────────────────────────────────────────────
    def _build_alertas(self):
        self.alertas_frame = tk.Frame(self.main, bg=C["bg"])

        hdr = tk.Frame(self.alertas_frame, bg=C["bg"])
        hdr.pack(fill="x", padx=20, pady=(20, 4))
        tk.Label(hdr, text="Alertas de Preço", bg=C["bg"], fg=C["purple3"],
                 font=("Segoe UI", 16, "bold")).pack(anchor="w")
        tk.Label(
            hdr,
            text="Menores preços por moeda de cada item com alerta. Atualiza ao abrir a página.",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 9),
            wraplength=520,
            justify="left",
        ).pack(anchor="w")

        alert_search_row = tk.Frame(self.alertas_frame, bg=C["bg"])
        alert_search_row.pack(fill="x", padx=20, pady=(8, 0))
        self._pack_list_search_bar(alert_search_row, "alertas", "Buscar item (nome ou ID):")

        self.alertas_list_frame = ScrollableFrame(self.alertas_frame)
        self.alertas_list_frame.pack(fill="both", expand=True, padx=20, pady=10)

    def _show_alertas(self):
        self._clear_main()
        self.alertas_frame.pack(fill="both", expand=True)
        self._render_alertas()
        self._alerts_display_refresh_gen += 1
        gen = self._alerts_display_refresh_gen
        threading.Thread(
            target=lambda g=gen: self._refresh_alertas_display_prices_worker(g),
            daemon=True,
        ).start()

    def _render_alertas(self):
        for w in self.alertas_list_frame.inner.winfo_children():
            w.destroy()
        self._alertas_list_photo_refs = []

        alerts_all = load_alerts()
        alert_q = self._list_search_query("alertas")
        alert_items = list(alerts_all.items())
        if alert_q:
            alert_items = [(k, a) for k, a in alert_items if item_matches_search(a, alert_q)]

        if not alert_items:
            if alerts_all and alert_q:
                empty_msg = f"🔍\n\nNenhum alerta corresponde a «{alert_q}»."
            else:
                empty_msg = (
                    "🔊\n\nNenhum alerta configurado.\n\n"
                    "Abra um item e toque em «Alerta» para criar."
                )
            tk.Label(
                self.alertas_list_frame.inner,
                text=empty_msg,
                bg=C["bg"],
                fg=C["text3"],
                font=("Segoe UI", 11),
                justify="center",
            ).pack(pady=60)
            self._list_search_update_hint("alertas", 0, len(alerts_all))
            return

        for key, alert_info in alert_items:
            sale_type = (alert_info.get("sale_type", "") or "").upper().replace("_", " ")
            alert_type = "cair abaixo" if alert_info.get("type") == "below" else "subir acima"
            price = fmt_price_stores(alert_info.get("price", 0))
            notify = (alert_info.get("notify_email") or "").strip()
            bell_color = C["green"] if alert_info.get("type") == "below" else C["red"]

            footer_labels = [
                {
                    "text": f"🔔 {sale_type}  ·  ➞ {alert_type} de {price}",
                    "fg": bell_color,
                    "font": ("Segoe UI", 8, "bold"),
                    "pady": (8, 0),
                },
            ]
            ref_f = alert_info.get("refinement")
            if ref_f is not None and str(ref_f).strip() != "":
                try:
                    footer_labels.append(
                        {
                            "text": f"⚔ Refino +{int(ref_f)} ou superior",
                            "fg": C["yellow"],
                            "font": ("Segoe UI", 8),
                            "pady": (2, 0),
                        }
                    )
                except (TypeError, ValueError):
                    pass
            if notify:
                footer_labels.append(
                    {
                        "text": f"✉ {notify}",
                        "fg": C["text3"],
                        "font": ("Segoe UI", 8),
                        "pady": (2, 0),
                    }
                )

            iid = int(alert_info["item_id"])
            _, row, bind_target = self._pack_item_store_snapshot_row(
                self.alertas_list_frame.inner,
                alert_info,
                self._alertas_list_photo_refs,
                wraplength=480,
                layout="split",
                id_subline=f"ID: {iid}  ·  clique para abrir janela",
                footer_labels=footer_labels,
            )
            btn_frame = tk.Frame(row, bg=C["card"])
            btn_frame.pack(side="right", padx=0)
            DarkButton(
                btn_frame,
                text="Ver preços",
                style="ghost",
                command=lambda x=iid, nm=str(alert_info.get("item_name", "") or ""): self._open_search_by_item_id(
                    x, nm
                ),
            ).pack(side="left", padx=2)
            DarkButton(btn_frame, text="✕ Remover", style="danger",
                       command=lambda k=key: self._remove_alert(k)).pack(side="left", padx=2)
            self._bind_click_open_item_detail(
                bind_target, iid, str(alert_info.get("item_name", "") or "")
            )

        self._list_search_scroll_to_top(self.alertas_list_frame)
        self._list_search_update_hint("alertas", len(alert_items), len(alerts_all))

    def _remove_alert(self, alert_key):
        """Remove um alerta."""
        alerts = load_alerts()
        if alert_key in alerts:
            del alerts[alert_key]
            save_alerts(alerts)
            messagebox.showinfo("Sucesso", "Alerta removido!")
            self._render_alertas()

    def _schedule_alert_monitor_cycle(self):
        """Reagenda verificação periódica de alertas (consulta lojas online)."""
        settings = load_settings()
        sec = max(60, int(settings.get("alert_interval_seconds", 300)))
        ms = sec * 1000
        if self._alert_after_id is not None:
            try:
                self.after_cancel(self._alert_after_id)
            except tk.TclError:
                pass
        self._alert_after_id = self.after(ms, self._alert_monitor_tick)

    def _alert_monitor_tick(self):
        """Executa uma rodada de verificação em thread (evita travar a UI)."""

        def worker():
            try:
                alerts = load_alerts()
                settings = load_settings()
                if alerts:
                    snap = dict(alerts)
                    events, updates = run_alert_pass(snap, settings, get_stores_from_item_page)
                    with _ALERTS_IO_LOCK:
                        cur = load_alerts()
                        for key, u in updates.items():
                            if key in cur:
                                cur[key]["condition_met"] = u["condition_met"]
                                if "notified_listing_keys" in u:
                                    cur[key]["notified_listing_keys"] = u["notified_listing_keys"]
                        save_alerts(cur)
                    if events:
                        st_copy = dict(settings)
                        ev_copy = list(events)
                        self.after(
                            0,
                            lambda ev=ev_copy, st=st_copy: self._dispatch_alert_events(ev, st),
                        )
                try:
                    build_ev = run_build_total_alerts(get_stores_from_item_page)
                except Exception as e:
                    logger.debug("Alertas build total: %s", e)
                    build_ev = []
                if build_ev:
                    st_copy = dict(settings)
                    bev = list(build_ev)
                    self.after(
                        0,
                        lambda ev=bev, st=st_copy: self._dispatch_build_alert_events(ev, st),
                    )
            except Exception as e:
                logger.exception("Monitor de alertas: %s", e)
            finally:
                self.after(0, self._schedule_alert_monitor_cycle)

        threading.Thread(target=worker, daemon=True).start()

    def _dispatch_alert_events(self, events, settings):
        """Pop-up conciso (não-modal) + som; e-mail enviado em segundo plano.

        Nada de bloqueante corre na thread da UI: o SMTP vai para uma thread e
        a imagem do item é carregada de forma assíncrona, por isso fechar um
        pop-up (mesmo com vários alertas em simultâneo) é instantâneo.
        """
        for ev in events:
            alert = ev["alert"]
            store = ev["store"]
            info = self._build_price_alert_popup_info(alert, store)

            to_addr = (alert.get("notify_email") or "").strip() or (
                settings.get("notify_email") or ""
            ).strip()
            smtp_ok = bool((settings.get("smtp_host") or "").strip()) and bool(to_addr)
            if smtp_ok:
                subject = f"[GDZ] Alerta: {info['item_name']} — {info['shop']}"
                body = build_email_body(alert, store, ev.get("extra"))
                self._send_alert_email_async(dict(settings), to_addr, subject, body)

            self._play_alert_beep()
            self._show_price_alert_popup(info)

    def _play_alert_beep(self):
        """Som leve do sistema (Windows); nunca bloqueia."""
        try:
            if sys.platform == "win32":
                import winsound

                winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass

    def _send_alert_email_async(self, settings, to_addr, subject, body):
        """Envia o e-mail detalhado numa thread — não congela a UI ao fechar o pop-up."""

        def work():
            try:
                ok, err = send_alert_email(settings, to_addr, subject, body)
                if not ok:
                    logger.warning("E-mail de alerta: %s", err)
            except Exception as e:
                logger.warning("E-mail de alerta (thread): %s", e)

        threading.Thread(target=work, daemon=True).start()

    def _build_price_alert_popup_info(self, alert, store):
        """Reúne só o essencial pedido para o pop-up de alerta de preço."""
        item_name = (alert.get("item_name") or "Item").strip() or "Item"
        try:
            iid = int(alert.get("item_id") or 0)
        except (TypeError, ValueError):
            iid = 0
        shop = (store.get("char_name") or store.get("seller_name") or "Loja").strip() or "Loja"
        price = _alert_store_price(store)
        ref = _alert_store_refinement(store)
        currency = (alert.get("sale_type") or store.get("sale_type") or "zeny").lower()
        currency_label = _ALERT_CURRENCY_LABELS.get(currency, currency.upper() or "Zeny")
        cond = "abaixo de" if (alert.get("type") or "below") == "below" else "acima de"
        threshold = _alert_fmt_price(alert.get("price", 0))
        icon_url = resolve_item_icon_url(
            iid if iid else None,
            store.get("item_icon_url") or alert.get("item_icon_url") or "",
            base_url=BASE_URL,
        )
        return {
            "item_name": item_name,
            "item_id": iid,
            "shop": shop,
            "refine": ref,
            "price_text": f"{_alert_fmt_price(price)} {currency_label}",
            "reason_text": f"Preço {cond} {threshold} {currency_label}",
            "currency": currency,
            "icon_url": icon_url,
        }

    def _show_price_alert_popup(self, info):
        """Janela compacta, não-modal: nome, ID, imagem, loja, preço, refino, motivo."""
        try:
            top = tk.Toplevel(self)
        except tk.TclError:
            return
        top.title("Alerta de preço")
        top.configure(bg=C["bg"])
        top.resizable(False, False)
        try:
            top.transient(self)
        except tk.TclError:
            pass

        accent = C.get(info.get("currency") or "zeny", C["purple2"])

        outer = tk.Frame(top, bg=C["border"], padx=1, pady=1)
        outer.pack(fill="both", expand=True)
        card = tk.Frame(outer, bg=C["card"], padx=16, pady=14)
        card.pack(fill="both", expand=True)

        tk.Label(
            card,
            text="ALERTA DE PREÇO",
            bg=C["card"],
            fg=C["text3"],
            font=("Segoe UI", 8, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        body = tk.Frame(card, bg=C["card"])
        body.grid(row=1, column=0, columnspan=2, sticky="we", pady=(8, 0))

        img_box = tk.Frame(body, bg=C["bg3"], width=64, height=64)
        img_box.pack_propagate(False)
        img_box.pack(side="left", padx=(0, 14))
        img_label = tk.Label(img_box, bg=C["bg3"], text="…", fg=C["text3"], font=("Segoe UI", 9))
        img_label.pack(fill="both", expand=True)

        details = tk.Frame(body, bg=C["card"])
        details.pack(side="left", fill="both", expand=True)

        tk.Label(
            details,
            text=info["item_name"],
            bg=C["card"],
            fg=C["purple3"],
            font=("Segoe UI", 13, "bold"),
            anchor="w",
            justify="left",
            wraplength=300,
        ).pack(anchor="w")

        meta = (
            f"ID {info['item_id']}" if info["item_id"] else "ID —"
        ) + f"   ·   Refino +{info['refine']}"
        tk.Label(
            details, text=meta, bg=C["card"], fg=C["text3"], font=("Segoe UI", 9), anchor="w"
        ).pack(anchor="w", pady=(2, 0))
        tk.Label(
            details,
            text=f"Loja: {info['shop']}",
            bg=C["card"],
            fg=C["text2"],
            font=("Segoe UI", 10),
            anchor="w",
            wraplength=300,
            justify="left",
        ).pack(anchor="w", pady=(2, 0))

        price_wrap = tk.Frame(card, bg=C["bg3"], padx=12, pady=8)
        price_wrap.grid(row=2, column=0, columnspan=2, sticky="we", pady=(12, 0))
        tk.Label(
            price_wrap,
            text=info["price_text"],
            bg=C["bg3"],
            fg=accent,
            font=("Segoe UI", 18, "bold"),
            anchor="w",
        ).pack(anchor="w")

        tk.Label(
            card,
            text=info["reason_text"],
            bg=C["card"],
            fg=C["text2"],
            font=("Segoe UI", 10),
            anchor="w",
            wraplength=340,
            justify="left",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))

        DarkButton(
            card, text="Fechar", command=top.destroy, style="ghost"
        ).grid(row=4, column=1, sticky="e", pady=(14, 0))
        card.columnconfigure(0, weight=1)

        top.bind("<Escape>", lambda _e: top.destroy())
        top.bind("<Return>", lambda _e: top.destroy())

        self._place_alert_popup(top)
        try:
            top.attributes("-topmost", True)
        except tk.TclError:
            pass
        self._load_alert_icon_async(info, top, img_label)

    def _place_alert_popup(self, top):
        """Posiciona em cascata (canto inferior direito) para vários alertas não se sobreporem."""
        try:
            top.update_idletasks()
            w = max(top.winfo_reqwidth(), 360)
            h = max(top.winfo_reqheight(), 180)
            sw = top.winfo_screenwidth()
            sh = top.winfo_screenheight()
        except tk.TclError:
            return
        idx = getattr(self, "_alert_popup_cascade", 0)
        self._alert_popup_cascade = (idx + 1) % 8
        margin = 24
        step = 30
        x = max(8, sw - w - margin - idx * step)
        y = max(8, sh - h - 64 - idx * step)
        try:
            top.geometry(f"{w}x{h}+{x}+{y}")
        except tk.TclError:
            pass

    def _load_alert_icon_async(self, info, top, img_label):
        """Carrega a imagem do item (disco→rede) numa thread e aplica quando pronta."""
        iid = info.get("item_id") or 0
        url = info.get("icon_url") or ""
        if not iid and not url:
            return

        def work():
            raw = None
            try:
                if iid:
                    raw = read_item_icon_png_bytes(
                        iid, url, self._fetch_icon_url_bytes, base_url=BASE_URL
                    )
                elif url:
                    raw = self._fetch_icon_url_bytes(url)
            except Exception as e:
                logger.debug("Ícone do alerta %s: %s", iid, e)
            if raw:
                self.after(0, lambda r=raw: self._apply_alert_icon(top, img_label, r))

        threading.Thread(target=work, daemon=True).start()

    def _apply_alert_icon(self, top, img_label, raw):
        try:
            if not top.winfo_exists() or not img_label.winfo_exists():
                return
        except tk.TclError:
            return
        ph = self._photoimage_from_icon_bytes(raw, 60)
        if ph is None:
            return
        try:
            img_label.configure(image=ph, text="")
            img_label._alert_icon_ref = ph  # type: ignore[attr-defined]
        except tk.TclError:
            pass

    def _dispatch_build_alert_events(self, events, settings):
        """Notifica quando o custo total (HP equiv. ou Zeny em builds antigas) cai abaixo do limiar."""
        for ev in events:
            body = build_email_body_build_total(ev)
            kind = ev.get("alert_kind") or "zeny"
            if kind == "hp_equiv":
                subject = f"[GDZ] Build «{ev.get('build_name', 'Build')}» — custo total HP (equiv.)"
            else:
                subject = f"[GDZ] Build «{ev.get('build_name', 'Build')}» — custo total Zeny"
            to_addr = (ev.get("notify_email") or "").strip() or (settings.get("notify_email") or "").strip()
            smtp_ok = bool((settings.get("smtp_host") or "").strip()) and bool(to_addr)
            if smtp_ok:
                ok, err = send_alert_email(settings, to_addr, subject, body)
                if not ok:
                    logger.warning("E-mail alerta build: %s", err)
                    body = f"{body}\n\n(Erro ao enviar e-mail: {err})"
            else:
                body = (
                    f"{body}\n\n"
                    "(Configure o e-mail e o SMTP em Configurações para receber alertas por e-mail.)"
                )
            try:
                if sys.platform == "win32":
                    import winsound

                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
            messagebox.showinfo("Alerta de build (custo total)", body, parent=self)
