"""
Monitor de alertas de preço em background + centro de notificações (web POC).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from adapters.persistence import _ALERTS_IO_LOCK, load_alerts, save_alerts
from alert_monitor import (
    _listing_stats,
    _history_stats_for_alert,
    build_email_body,
    listing_fingerprint,
    pick_store_for_notification,
    qualifying_stores_for_alert,
    run_alert_pass,
    send_alert_email,
)
from app_settings import load_settings

logger = logging.getLogger(__name__)

NOTIFICATIONS_FILE = os.path.join(os.path.expanduser("~"), "herosaga_alert_notifications.json")
_MAX_STORED = 200

FetchStoresFn = Callable[[int, str], Tuple[List[dict], dict]]

_worker: Optional["AlertWorker"] = None
_worker_lock = threading.Lock()


def get_alert_worker(fetch_stores: FetchStoresFn) -> "AlertWorker":
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = AlertWorker(fetch_stores)
        return _worker


class AlertWorker:
    """Verifica alertas periodicamente, envia e-mails e guarda notificações."""

    def __init__(self, fetch_stores: FetchStoresFn) -> None:
        self._fetch = fetch_stores
        self._lock = threading.RLock()
        self._notifications: List[dict] = []
        self._timer: Optional[threading.Timer] = None
        self._running = False
        self._load_notifications()

    def start(self, *, initial_delay: float = 8.0) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._schedule(max(1.0, float(initial_delay)))

    def stop(self) -> None:
        with self._lock:
            self._running = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def _schedule(self, delay_sec: float) -> None:
        if not self._running:
            return
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(delay_sec, self._tick)
        self._timer.daemon = True
        self._timer.name = "alert-worker"
        self._timer.start()

    def _tick(self) -> None:
        try:
            self.run_pass()
        except Exception:
            logger.exception("Monitor de alertas (web): falha no ciclo")
        finally:
            try:
                settings = load_settings()
                sec = max(60, int(settings.get("alert_interval_seconds", 300)))
            except (TypeError, ValueError):
                sec = 300
            with self._lock:
                if self._running:
                    self._schedule(float(sec))

    def run_pass(self) -> List[dict]:
        """Executa uma verificação completa; devolve eventos disparados."""
        alerts = load_alerts()
        if not alerts:
            return []
        settings = load_settings()
        snap = dict(alerts)
        events, updates = run_alert_pass(snap, settings, self._fetch)
        if updates:
            with _ALERTS_IO_LOCK:
                cur = load_alerts()
                for key, u in updates.items():
                    if key in cur:
                        cur[key]["condition_met"] = u["condition_met"]
                        if "notified_listing_keys" in u:
                            cur[key]["notified_listing_keys"] = u["notified_listing_keys"]
                save_alerts(cur)
        if events:
            self._dispatch_events(events, settings)
        return events

    def notify_if_already_met(
        self,
        alert_key: str,
        alert: dict,
        filtered_stores: List[dict],
    ) -> Optional[dict]:
        """Se o critério já se cumpre ao criar o alerta, notifica a melhor oferta."""
        qual = qualifying_stores_for_alert(alert, filtered_stores)
        if not qual:
            return None
        store = pick_store_for_notification(alert, qual)
        if not store:
            return None
        listing_avg, listing_n = _listing_stats(filtered_stores)
        try:
            item_id = int(alert.get("item_id") or 0)
        except (TypeError, ValueError):
            item_id = 0
        hist = _history_stats_for_alert(item_id, alert)
        ev = {
            "key": alert_key,
            "alert": alert,
            "store": store,
            "extra": {
                "listing_avg": listing_avg,
                "listing_n": listing_n,
                "history": hist,
            },
        }
        settings = load_settings()
        self._dispatch_events([ev], settings)
        return ev

    def _dispatch_events(self, events: List[dict], settings: dict) -> None:
        for ev in events:
            self._dispatch_one(ev, settings)

    def _dispatch_one(self, ev: dict, settings: dict) -> dict:
        alert = ev.get("alert") or {}
        store = ev.get("store") or {}
        key = str(ev.get("key") or "")
        try:
            item_id = int(alert.get("item_id") or 0)
        except (TypeError, ValueError):
            item_id = 0
        shop = (store.get("char_name") or store.get("seller_name") or "Loja").strip() or "Loja"
        try:
            price = float(store.get("price") or store.get("sell_price") or store.get("valor") or 0)
        except (TypeError, ValueError):
            price = 0.0
        sale = str(alert.get("sale_type") or "zeny")
        cond = "abaixo de" if str(alert.get("type") or "below") == "below" else "acima de"
        item_name = str(alert.get("item_name") or "Item")
        try:
            threshold = float(alert.get("price") or 0)
        except (TypeError, ValueError):
            threshold = 0.0

        notif = {
            "id": str(uuid.uuid4()),
            "ts": datetime.now().isoformat(timespec="seconds"),
            "read": False,
            "kind": "price",
            "alert_key": key,
            "item_id": item_id,
            "item_name": item_name,
            "shop": shop,
            "price": price,
            "sale_type": sale,
            "alert_type": str(alert.get("type") or "below"),
            "threshold": threshold,
            "item_icon_url": str(alert.get("item_icon_url") or ""),
            "message": f"{item_name} · {price:g} {sale} · alerta {cond} {threshold:g}",
            "email_sent": False,
            "email_error": "",
        }

        to_addr = (alert.get("notify_email") or "").strip() or (settings.get("notify_email") or "").strip()
        smtp_ok = bool((settings.get("smtp_host") or "").strip()) and bool(to_addr)
        if smtp_ok:
            subject = f"[GDZ] Alerta: {item_name} — {shop}"
            body = build_email_body(alert, store, ev.get("extra"))
            ok, err = send_alert_email(dict(settings), to_addr, subject, body)
            notif["email_sent"] = bool(ok)
            notif["email_error"] = "" if ok else str(err)
            if not ok:
                logger.warning("E-mail de alerta (%s): %s", key, err)

        with self._lock:
            self._notifications.insert(0, notif)
            if len(self._notifications) > _MAX_STORED:
                self._notifications = self._notifications[:_MAX_STORED]
            self._save_notifications()
        if key:
            with _ALERTS_IO_LOCK:
                cur = load_alerts()
                if key in cur:
                    cur[key]["last_fired_at"] = datetime.now().isoformat(timespec="seconds")
                    save_alerts(cur)
        return notif

    def get_notifications(self, *, unread_only: bool = False, limit: int = 50) -> dict:
        with self._lock:
            items = list(self._notifications)
        if unread_only:
            items = [n for n in items if not n.get("read")]
        items = items[: max(1, min(int(limit or 50), _MAX_STORED))]
        unread = sum(1 for n in self._notifications if not n.get("read"))
        return {"ok": True, "unread": unread, "items": items}

    def mark_read(self, ids=None) -> dict:
        want = None
        if ids is not None:
            want = {str(x) for x in ids if str(x).strip()}
        with self._lock:
            for n in self._notifications:
                if want is None or n.get("id") in want:
                    n["read"] = True
            self._save_notifications()
            unread = sum(1 for n in self._notifications if not n.get("read"))
        return {"ok": True, "unread": unread}

    def remove_notification(self, notif_id: str) -> dict:
        nid = str(notif_id or "").strip()
        with self._lock:
            before = len(self._notifications)
            self._notifications = [n for n in self._notifications if str(n.get("id") or "") != nid]
            removed = before - len(self._notifications)
            self._save_notifications()
            unread = sum(1 for n in self._notifications if not n.get("read"))
        return {"ok": True, "removed": removed, "unread": unread}

    def clear_all(self) -> dict:
        with self._lock:
            self._notifications = []
            self._save_notifications()
        return {"ok": True, "unread": 0, "total": 0}

    def _load_notifications(self) -> None:
        if not os.path.isfile(NOTIFICATIONS_FILE):
            self._notifications = []
            return
        try:
            with open(NOTIFICATIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("items") if isinstance(data, dict) else data
            self._notifications = [x for x in (raw or []) if isinstance(x, dict)]
        except Exception as e:
            logger.debug("Notificações: leitura falhou: %s", e)
            self._notifications = []

    def _save_notifications(self) -> None:
        try:
            with open(NOTIFICATIONS_FILE, "w", encoding="utf-8") as f:
                json.dump({"items": self._notifications}, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.warning("Notificações: gravação falhou: %s", e)
