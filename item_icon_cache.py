"""
Cache em disco de ícones de itens (home monitorados).
``data/item_icons/{item_id}.png``
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
ITEM_ICONS_DIR = os.path.join(_APP_DIR, "data", "item_icons")


def ensure_item_icons_dir() -> None:
    os.makedirs(ITEM_ICONS_DIR, exist_ok=True)


def item_icon_disk_path(item_id: int) -> str:
    return os.path.join(ITEM_ICONS_DIR, f"{int(item_id)}.png")


def read_item_icon_png_bytes(
    item_id: int,
    url: str,
    fetch_url_bytes: Callable[[str], Optional[bytes]],
) -> Optional[bytes]:
    """Disco → rede (grava em disco). ``fetch_url_bytes`` só é chamado se não houver ficheiro."""
    ensure_item_icons_dir()
    path = item_icon_disk_path(item_id)
    if os.path.isfile(path):
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError as ex:
            logger.debug("Ler ícone em cache %s: %s", path, ex)
    norm = (url or "").strip()
    if not norm:
        return None
    try:
        raw = fetch_url_bytes(norm)
    except Exception as ex:
        logger.debug("Baixar ícone item %s: %s", item_id, ex)
        return None
    if not raw:
        return None
    try:
        with open(path, "wb") as f:
            f.write(raw)
    except OSError as ex:
        logger.debug("Gravar ícone %s: %s", path, ex)
    return raw
