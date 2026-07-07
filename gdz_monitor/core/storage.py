from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, List

DATA_FILE = os.path.join(os.path.expanduser("~"), "herosaga_monitor_data.json")
PRICES_HISTORY_FILE = os.path.join(os.path.expanduser("~"), "herosaga_prices_history.json")
ALERTS_FILE = os.path.join(os.path.expanduser("~"), "herosaga_alerts.json")

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
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                if not isinstance(raw, dict):
                    raw = {}
                data = ensure_monitor_structure(raw)
                if isinstance(data.get("monitored"), list):
                    data["monitored"] = dedupe_monitored_preserve_order(data["monitored"])
                return data
        except Exception:
            pass
    return ensure_monitor_structure({"monitored": [], "searches": []})


def save_data(data: Dict[str, Any]) -> None:
    if isinstance(data, dict) and isinstance(data.get("monitored"), list):
        data["monitored"] = dedupe_monitored_preserve_order(data["monitored"])
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_prices_history():
    """Carrega histórico de preços coletados."""
    if os.path.exists(PRICES_HISTORY_FILE):
        try:
            with open(PRICES_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_prices_history(history):
    """Salva histórico de preços."""
    with open(PRICES_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def load_alerts():
    """Carrega alertas de preço configurados."""
    with _ALERTS_IO_LOCK:
        if os.path.exists(ALERTS_FILE):
            try:
                with open(ALERTS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}


def save_alerts(alerts):
    """Salva alertas de preço."""
    with _ALERTS_IO_LOCK:
        with open(ALERTS_FILE, "w", encoding="utf-8") as f:
            json.dump(alerts, f, ensure_ascii=False, indent=2)
