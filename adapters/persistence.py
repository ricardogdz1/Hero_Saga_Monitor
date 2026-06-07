"""Persistência em JSON (dados do utilizador)."""
from __future__ import annotations

import app_storage

DATA_FILE = app_storage.DATA_FILE
PRICES_HISTORY_FILE = app_storage.PRICES_HISTORY_FILE
ALERTS_FILE = app_storage.ALERTS_FILE
DEFAULT_MONITOR_CATEGORIES = app_storage.DEFAULT_MONITOR_CATEGORIES
_ALERTS_IO_LOCK = app_storage._ALERTS_IO_LOCK

load_data = app_storage.load_data
save_data = app_storage.save_data
load_prices_history = app_storage.load_prices_history
save_prices_history = app_storage.save_prices_history
load_alerts = app_storage.load_alerts
save_alerts = app_storage.save_alerts
ensure_monitor_structure = app_storage.ensure_monitor_structure
dedupe_monitored_preserve_order = app_storage.dedupe_monitored_preserve_order
