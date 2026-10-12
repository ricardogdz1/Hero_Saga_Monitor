"""
Banco de dados local (SQLite) com os dados do utilizador.

Ficheiro: ``%LOCALAPPDATA%\\GDZMonitor\\gdz_monitor.db`` no Windows
(``~/.gdz_monitor/gdz_monitor.db`` noutros sistemas; ``GDZ_MONITOR_DB`` sobrepõe).

Tabelas:
- ``documents`` — documentos JSON por chave (substituem os antigos ``~/herosaga_*.json``).
- ``images``    — imagens em BLOB por namespace/chave (ícones de itens, sprites de mob).
- ``meta``      — marcadores internos (ex.: migração dos ficheiros antigos já feita).

Na primeira abertura, os ficheiros JSON/PNG antigos são importados para o banco.
Os originais ficam intocados (backup) e deixam de ser usados.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import threading
from datetime import datetime
from typing import Any, List, Optional

from gdz_monitor.core.paths import DATA_DIR

logger = logging.getLogger(__name__)


def _default_app_data_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") if sys.platform == "win32" else None
    if base:
        return os.path.join(base, "GDZMonitor")
    return os.path.join(os.path.expanduser("~"), ".gdz_monitor")


APP_DATA_DIR = _default_app_data_dir()
DB_FILE = os.environ.get("GDZ_MONITOR_DB") or os.path.join(APP_DATA_DIR, "gdz_monitor.db")

# Chaves de documentos
DOC_MONITOR_DATA = "monitor_data"
DOC_PRICES_HISTORY = "prices_history"
DOC_ALERTS = "alerts"
DOC_SETTINGS = "settings"
DOC_MVP_TIMERS = "mvp_timers"
DOC_MVP_CATALOG = "mvp_catalog"
DOC_LOOT_GROUPS = "loot_groups"
DOC_BUILDS = "builds"
DOC_ALERT_NOTIFICATIONS = "alert_notifications"
DOC_DROP_ITEM_ID_CACHE = "drop_item_id_cache"

# Namespaces de imagens
IMG_ITEM_ICON = "item_icon"
IMG_MOB = "mob"

_HOME = os.path.expanduser("~")

# Ficheiros antigos → documento (importados uma única vez)
LEGACY_DOCUMENT_FILES = (
    (DOC_MONITOR_DATA, os.path.join(_HOME, "herosaga_monitor_data.json")),
    (DOC_PRICES_HISTORY, os.path.join(_HOME, "herosaga_prices_history.json")),
    (DOC_ALERTS, os.path.join(_HOME, "herosaga_alerts.json")),
    (DOC_SETTINGS, os.path.join(_HOME, "herosaga_monitor_settings.json")),
    (DOC_MVP_TIMERS, os.path.join(_HOME, "herosaga_mvp_timers.json")),
    (DOC_LOOT_GROUPS, os.path.join(_HOME, "herosaga_loot_groups.json")),
    (DOC_BUILDS, os.path.join(_HOME, "herosaga_builds.json")),
    (DOC_ALERT_NOTIFICATIONS, os.path.join(_HOME, "herosaga_alert_notifications.json")),
    (DOC_DROP_ITEM_ID_CACHE, os.path.join(_HOME, "herosaga_drop_item_id_cache.json")),
)

# Pastas antigas de imagens → namespace (nome do ficheiro sem extensão = chave)
LEGACY_IMAGE_DIRS = (
    (IMG_ITEM_ICON, os.path.join(DATA_DIR, "item_icons")),
    (IMG_MOB, os.path.join(_HOME, "herosaga_dp_mob_images")),
)

_MIGRATION_MARKER = "legacy_files_migrated_v1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS images (
    namespace  TEXT NOT NULL,
    key        TEXT NOT NULL,
    data       BLOB NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (namespace, key)
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_LOCK = threading.RLock()
_conn: Optional[sqlite3.Connection] = None
_conn_path: Optional[str] = None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect(path: str) -> sqlite3.Connection:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_SCHEMA)
    return conn


def _get_conn() -> sqlite3.Connection:
    """Conexão única partilhada entre threads (acesso serializado por ``_LOCK``)."""
    global _conn, _conn_path
    with _LOCK:
        if _conn is None or _conn_path != DB_FILE:
            if _conn is not None:
                _conn.close()
            _conn = _connect(DB_FILE)
            _conn_path = DB_FILE
            try:
                migrate_legacy_files(_conn)
            except Exception as e:
                logger.warning("Migração dos ficheiros antigos para o banco falhou: %s", e)
        return _conn


def close() -> None:
    global _conn, _conn_path
    with _LOCK:
        if _conn is not None:
            _conn.close()
        _conn = None
        _conn_path = None


# --- documentos JSON ---------------------------------------------------------


def get_document(key: str, default: Any = None) -> Any:
    with _LOCK:
        row = _get_conn().execute("SELECT value FROM documents WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row[0])
    except ValueError as e:
        logger.warning("Documento %s inválido no banco: %s", key, e)
        return default


def set_document(key: str, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False)
    with _LOCK:
        _get_conn().execute(
            "INSERT INTO documents (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, payload, _now()),
        )


def has_document(key: str) -> bool:
    with _LOCK:
        row = _get_conn().execute("SELECT 1 FROM documents WHERE key = ?", (key,)).fetchone()
    return row is not None


# --- imagens -----------------------------------------------------------------


def get_image(namespace: str, key: str) -> Optional[bytes]:
    with _LOCK:
        row = _get_conn().execute(
            "SELECT data FROM images WHERE namespace = ? AND key = ?", (namespace, str(key))
        ).fetchone()
    return bytes(row[0]) if row else None


def put_image(namespace: str, key: str, data: bytes) -> None:
    if not data:
        return
    with _LOCK:
        _get_conn().execute(
            "INSERT INTO images (namespace, key, data, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(namespace, key) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
            (namespace, str(key), sqlite3.Binary(data), _now()),
        )


def has_image(namespace: str, key: str) -> bool:
    with _LOCK:
        row = _get_conn().execute(
            "SELECT 1 FROM images WHERE namespace = ? AND key = ?", (namespace, str(key))
        ).fetchone()
    return row is not None


def list_image_keys(namespace: str) -> List[str]:
    with _LOCK:
        rows = _get_conn().execute(
            "SELECT key FROM images WHERE namespace = ? ORDER BY key", (namespace,)
        ).fetchall()
    return [r[0] for r in rows]


# --- migração dos ficheiros antigos -----------------------------------------


def migrate_legacy_files(conn: sqlite3.Connection) -> dict:
    """Importa os JSON/PNG antigos para o banco (uma vez; não sobrescreve nem apaga nada)."""
    with _LOCK:
        if conn.execute("SELECT 1 FROM meta WHERE key = ?", (_MIGRATION_MARKER,)).fetchone():
            return {"documents": 0, "images": 0, "skipped": True}
        docs = 0
        imgs = 0
        now = _now()
        conn.execute("BEGIN")
        try:
            for key, path in LEGACY_DOCUMENT_FILES:
                if not os.path.isfile(path):
                    continue
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        value = json.load(f)
                except (OSError, ValueError) as e:
                    logger.warning("Migração: ignorado %s (%s)", path, e)
                    continue
                cur = conn.execute(
                    "INSERT OR IGNORE INTO documents (key, value, updated_at) VALUES (?, ?, ?)",
                    (key, json.dumps(value, ensure_ascii=False), now),
                )
                docs += cur.rowcount
            for namespace, folder in LEGACY_IMAGE_DIRS:
                if not os.path.isdir(folder):
                    continue
                for name in sorted(os.listdir(folder)):
                    path = os.path.join(folder, name)
                    stem, ext = os.path.splitext(name)
                    if not os.path.isfile(path) or ext.lower() not in ("", ".png"):
                        continue
                    try:
                        with open(path, "rb") as f:
                            blob = f.read()
                    except OSError:
                        continue
                    if not blob:
                        continue
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO images (namespace, key, data, updated_at) VALUES (?, ?, ?, ?)",
                        (namespace, stem, sqlite3.Binary(blob), now),
                    )
                    imgs += cur.rowcount
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (_MIGRATION_MARKER, now))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        if docs or imgs:
            logger.info("Migração para %s: %d documentos, %d imagens", DB_FILE, docs, imgs)
        return {"documents": docs, "images": imgs, "skipped": False}
