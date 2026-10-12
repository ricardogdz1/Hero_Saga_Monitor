"""
Recursos somente leitura do programa (conteúdo de ``data/``: mapas de drop, catálogo MVP,
sprites, minimapas, ícones de buff).

No executável, ``data/`` é empacotada num banco SQLite (``data/resources.db``, gerado por
``tools/build_resources_db.py`` no ``build.bat``). Em desenvolvimento, sem esse banco,
os ficheiros são lidos directamente de ``data/`` — assim os scripts de ``tools/``
continuam a editar ficheiros normais versionados no git.

Caminhos são relativos a ``data/`` e usam ``/`` (ex.: ``mvp_sprites/1038.png``).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from typing import Any, List, Optional

from gdz_monitor.core.paths import DATA_DIR

logger = logging.getLogger(__name__)

RESOURCES_DB_NAME = "resources.db"
RESOURCES_DB_FILE = os.path.join(DATA_DIR, RESOURCES_DB_NAME)

# Pastas de data/ que não são recursos do programa (caches locais / debug)
EXCLUDED_DIRS = frozenset({"item_icons", "mvp_detect_debug"})

RESOURCES_SCHEMA = """
CREATE TABLE IF NOT EXISTS resources (
    path TEXT PRIMARY KEY,
    data BLOB NOT NULL
);
"""

_LOCK = threading.RLock()
_conn: Optional[sqlite3.Connection] = None
_conn_checked = False


def _norm(rel_path: str) -> str:
    return str(rel_path or "").replace("\\", "/").strip("/")


def _get_conn() -> Optional[sqlite3.Connection]:
    global _conn, _conn_checked
    with _LOCK:
        if not _conn_checked:
            _conn_checked = True
            if os.path.isfile(RESOURCES_DB_FILE):
                try:
                    uri = "file:" + RESOURCES_DB_FILE.replace("\\", "/") + "?mode=ro"
                    _conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
                except sqlite3.Error as e:
                    logger.warning("Abrir %s: %s — a usar ficheiros de data/", RESOURCES_DB_FILE, e)
                    _conn = None
        return _conn


def read_bytes(rel_path: str) -> Optional[bytes]:
    rel = _norm(rel_path)
    if not rel:
        return None
    conn = _get_conn()
    if conn is not None:
        with _LOCK:
            row = conn.execute("SELECT data FROM resources WHERE path = ?", (rel,)).fetchone()
        return bytes(row[0]) if row else None
    path = os.path.join(DATA_DIR, *rel.split("/"))
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError as e:
        logger.debug("read_bytes %s: %s", path, e)
        return None


def read_json(rel_path: str, default: Any = None) -> Any:
    raw = read_bytes(rel_path)
    if raw is None:
        return default
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        logger.warning("Recurso JSON inválido %s: %s", rel_path, e)
        return default


def exists(rel_path: str) -> bool:
    rel = _norm(rel_path)
    if not rel:
        return False
    conn = _get_conn()
    if conn is not None:
        with _LOCK:
            row = conn.execute("SELECT 1 FROM resources WHERE path = ?", (rel,)).fetchone()
        return row is not None
    return os.path.isfile(os.path.join(DATA_DIR, *rel.split("/")))


def list_dir(rel_dir: str) -> List[str]:
    """Nomes dos ficheiros directamente dentro de *rel_dir* (sem subpastas)."""
    rel = _norm(rel_dir)
    conn = _get_conn()
    if conn is not None:
        prefix = rel + "/" if rel else ""
        with _LOCK:
            rows = conn.execute(
                "SELECT path FROM resources WHERE substr(path, 1, ?) = ?", (len(prefix), prefix)
            ).fetchall()
        return sorted(p[len(prefix):] for (p,) in rows if "/" not in p[len(prefix):])
    folder = os.path.join(DATA_DIR, *rel.split("/")) if rel else DATA_DIR
    try:
        return sorted(n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n)))
    except OSError:
        return []


def iter_source_files(data_dir: str = DATA_DIR):
    """(caminho relativo, caminho absoluto) dos ficheiros de *data_dir* a empacotar."""
    for root, dirs, files in os.walk(data_dir):
        rel_root = os.path.relpath(root, data_dir)
        if rel_root == ".":
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        dirs.sort()
        for name in sorted(files):
            if rel_root == "." and name.startswith(RESOURCES_DB_NAME):
                continue
            rel = name if rel_root == "." else _norm(os.path.join(rel_root, name))
            yield rel, os.path.join(root, name)


def build_resources_db(output_path: str, data_dir: str = DATA_DIR) -> int:
    """Gera o banco de recursos a partir de *data_dir*. Devolve o nº de ficheiros."""
    if os.path.exists(output_path):
        os.remove(output_path)
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(output_path)
    try:
        conn.executescript(RESOURCES_SCHEMA)
        n = 0
        for rel, path in iter_source_files(data_dir):
            with open(path, "rb") as f:
                conn.execute("INSERT INTO resources (path, data) VALUES (?, ?)", (rel, sqlite3.Binary(f.read())))
            n += 1
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()
    return n
