"""Persistência dos dados do utilizador (banco SQLite local — ver ``core/database.py``)."""
from __future__ import annotations

from gdz_monitor.core import storage

DEFAULT_MONITOR_CATEGORIES = storage.DEFAULT_MONITOR_CATEGORIES
_ALERTS_IO_LOCK = storage._ALERTS_IO_LOCK

load_data = storage.load_data
save_data = storage.save_data
load_prices_history = storage.load_prices_history
save_prices_history = storage.save_prices_history
load_alerts = storage.load_alerts
save_alerts = storage.save_alerts
ensure_monitor_structure = storage.ensure_monitor_structure
dedupe_monitored_preserve_order = storage.dedupe_monitored_preserve_order
