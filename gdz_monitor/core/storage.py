from __future__ import annotations

import threading
from typing import Any, Dict, List

from gdz_monitor.core import database

DEFAULT_MONITOR_CATEGORIES = (
    "Gerais",
    "Equipamentos",
    "Cartas",
    "Utilitários",
    "Consumíveis",
)

_ALERTS_IO_LOCK = threading.RLock()


def ensure_monitor_structure(data: dict) -> dict:
    """Garante ``monitor_categories`` e ``category`` em cada item monitorado."""
    if not isinstance(data, dict):
        return {"monitored": [], "searches": [], "monitor_categories": list(DEFAULT_MONITOR_CATEGORIES)}
    if "searches" not in data:
        data["searches"] = []
    mc = data.get("monitor_categories")
    if not isinstance(mc, list) or not mc:
        data["monitor_categories"] = list(DEFAULT_MONITOR_CATEGORIES)
    else:
        cleaned: List[str] = []
        seen = set()
        for x in mc:
            s = str(x).strip()
            if not s or s in seen:
                continue
            seen.add(s)
            cleaned.append(s)
        data["monitor_categories"] = cleaned if cleaned else list(DEFAULT_MONITOR_CATEGORIES)
    if "Gerais" not in data["monitor_categories"]:
        data["monitor_categories"].insert(0, "Gerais")
    valid = set(data["monitor_categories"])
    for m in data.get("monitored") or []:
        if not isinstance(m, dict):
            continue
        c = m.get("category")
        if not c or str(c).strip() not in valid:
            m["category"] = "Gerais"
        else:
            m["category"] = str(c).strip()
    return data


def dedupe_monitored_preserve_order(monitored):
    """Mantém a primeira ocorrência de cada ID na lista de monitorados."""
    if not isinstance(monitored, list):
        return []
    seen = set()
    out = []
    for m in monitored:
        if not isinstance(m, dict):
            continue
        try:
            pid = int(m["id"])
        except (TypeError, ValueError, KeyError):
            continue
        if pid in seen:
            continue
        seen.add(pid)
        out.append(m)
    return out


def load_data() -> Dict[str, Any]:
    raw = database.get_document(database.DOC_MONITOR_DATA)
    if not isinstance(raw, dict):
        return ensure_monitor_structure({"monitored": [], "searches": []})
    data = ensure_monitor_structure(raw)
    if isinstance(data.get("monitored"), list):
        data["monitored"] = dedupe_monitored_preserve_order(data["monitored"])
    return data


def save_data(data: Dict[str, Any]) -> None:
    if isinstance(data, dict) and isinstance(data.get("monitored"), list):
        data["monitored"] = dedupe_monitored_preserve_order(data["monitored"])
    database.set_document(database.DOC_MONITOR_DATA, data)


def load_prices_history():
    """Carrega histórico de preços coletados."""
    return database.get_document(database.DOC_PRICES_HISTORY, {})


def save_prices_history(history):
    """Salva histórico de preços."""
    database.set_document(database.DOC_PRICES_HISTORY, history)


def load_alerts():
    """Carrega alertas de preço configurados."""
    with _ALERTS_IO_LOCK:
        return database.get_document(database.DOC_ALERTS, {})


def save_alerts(alerts):
    """Salva alertas de preço."""
    with _ALERTS_IO_LOCK:
        database.set_document(database.DOC_ALERTS, alerts)
