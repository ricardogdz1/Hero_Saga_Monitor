"""
Cache em disco de ícones de itens (home monitorados).
``data/item_icons/{item_id}.png`` — processados 24×24, fundo removido.
"""

from __future__ import annotations

import base64
import logging
import os
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
ITEM_ICONS_DIR = os.path.join(_APP_DIR, "data", "item_icons")

ICON_OUTPUT_SIZE = (24, 24)
ICON_WHITE_BG_TOLERANCE = 20

_reprocess_done = False


def ensure_item_icons_dir() -> None:
    os.makedirs(ITEM_ICONS_DIR, exist_ok=True)
    global _reprocess_done
    if not _reprocess_done:
        _reprocess_done = True
        reprocess_cached_icons_with_white_background()


def item_icon_disk_path(item_id: int) -> str:
    return os.path.join(ITEM_ICONS_DIR, f"{int(item_id)}.png")


from core.constants import BASE_URL as _DEFAULT_BASE_URL


def _processicon_url(item_id: int, *, base_url: str = _DEFAULT_BASE_URL) -> str:
    return f"{base_url.rstrip('/')}/?module=image&action=processicon&id={int(item_id)}"


def resolve_item_icon_url(
    item_id: Optional[int],
    url: Optional[str],
    *,
    base_url: str = _DEFAULT_BASE_URL,
) -> str:
    """URL do ícone (meta do item ou fallback processicon por ID)."""
    norm = (url or "").strip()
    if norm:
        return norm
    if item_id is not None:
        try:
            return _processicon_url(int(item_id), base_url=base_url)
        except (TypeError, ValueError):
            return ""
    return ""


def _pixel_is_background_white(r: int, g: int, b: int, a: int, tolerance: int) -> bool:
    t = max(0, min(255, int(tolerance)))
    return a > 0 and r >= 255 - t and g >= 255 - t and b >= 255 - t


def flood_fill_white_background_rgba(im, tolerance: int = ICON_WHITE_BG_TOLERANCE):
    """Remove pixels brancos conectados às 4 bordas; preserva brancos internos."""
    im = im.convert("RGBA")
    w, h = im.size
    if w < 1 or h < 1:
        return im
    px = im.load()
    visited = bytearray(w * h)
    queue: deque[tuple[int, int]] = deque()

    def pos(x: int, y: int) -> int:
        return y * w + x

    def seed(x: int, y: int) -> None:
        p = pos(x, y)
        if visited[p]:
            return
        r, g, b, a = px[x, y]
        if _pixel_is_background_white(r, g, b, a, tolerance):
            visited[p] = 1
            queue.append((x, y))

    for x in range(w):
        seed(x, 0)
        seed(x, h - 1)
    for y in range(h):
        seed(0, y)
        seed(w - 1, y)

    while queue:
        x, y = queue.pop()
        r, g, b, _a = px[x, y]
        px[x, y] = (r, g, b, 0)
        for nx, ny in ((x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)):
            if nx < 0 or ny < 0 or nx >= w or ny >= h:
                continue
            p = pos(nx, ny)
            if visited[p]:
                continue
            nr, ng, nb, na = px[nx, ny]
            if _pixel_is_background_white(nr, ng, nb, na, tolerance):
                visited[p] = 1
                queue.append((nx, ny))

    return im


def _lanczos_resample():
    from PIL import Image

    try:
        return Image.Resampling.LANCZOS
    except AttributeError:
        return Image.LANCZOS


def process_icon_image(im):
    """Flood fill (bordas) + redimensiona para 24×24."""
    from PIL import Image

    im = im.convert("RGBA")
    im = flood_fill_white_background_rgba(im, tolerance=ICON_WHITE_BG_TOLERANCE)
    im = im.resize(ICON_OUTPUT_SIZE, _lanczos_resample())
    return im


def process_icon_png_bytes(raw: bytes) -> Optional[bytes]:
    """Aplica flood fill + resize 24×24; devolve bytes PNG."""
    try:
        from PIL import Image
    except ImportError:
        return raw
    try:
        im = Image.open(BytesIO(raw))
        im = process_icon_image(im)
        out = BytesIO()
        im.save(out, format="PNG")
        return out.getvalue()
    except Exception as ex:
        logger.debug("Processar ícone: %s", ex)
        return None


def _save_icon_png(item_id: int, im) -> None:
    path = item_icon_disk_path(item_id)
    im.save(path, format="PNG")


def png_has_opaque_white_background(
    raw: bytes,
    tolerance: int = ICON_WHITE_BG_TOLERANCE,
) -> bool:
    """True se bordas têm pixels brancos opacos."""
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        im = Image.open(BytesIO(raw)).convert("RGBA")
        w, h = im.size
        if w < 2 or h < 2:
            return False
        px = im.load()
        samples = []
        for x in range(w):
            samples.append(px[x, 0])
            samples.append(px[x, h - 1])
        for y in range(1, h - 1):
            samples.append(px[0, y])
            samples.append(px[w - 1, y])
        white_opaque = 0
        checked = 0
        for r, g, b, a in samples:
            if a < 128:
                continue
            checked += 1
            if _pixel_is_background_white(r, g, b, a, tolerance):
                white_opaque += 1
        return checked >= 4 and (white_opaque / checked) >= 0.5
    except Exception:
        return False


def _icon_cache_is_ready(raw: bytes) -> bool:
    """Ícone já processado: 24×24 sem fundo branco nas bordas."""
    try:
        from PIL import Image
    except ImportError:
        return True
    try:
        im = Image.open(BytesIO(raw))
        if im.size != ICON_OUTPUT_SIZE:
            return False
        return not png_has_opaque_white_background(raw)
    except Exception:
        return False


def _read_cached_icon_bytes(item_id: int) -> Optional[bytes]:
    path = item_icon_disk_path(item_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError as ex:
        logger.debug("Ler ícone em cache %s: %s", path, ex)
        return None


def reprocess_cached_icons_with_white_background() -> int:
    """Reprocessa PNGs em cache que ainda têm fundo branco (passos b–e)."""
    if not os.path.isdir(ITEM_ICONS_DIR):
        return 0
    fixed = 0
    for name in os.listdir(ITEM_ICONS_DIR):
        if not name.lower().endswith(".png"):
            continue
        try:
            item_id = int(os.path.splitext(name)[0])
        except ValueError:
            continue
        raw = _read_cached_icon_bytes(item_id)
        if not raw:
            continue
        try:
            from PIL import Image

            im = Image.open(BytesIO(raw))
            needs = png_has_opaque_white_background(raw) or im.size != ICON_OUTPUT_SIZE
        except Exception:
            continue
        if not needs:
            continue
        try:
            im = Image.open(BytesIO(raw)).convert("RGBA")
            im = process_icon_image(im)
            _save_icon_png(item_id, im)
            fixed += 1
        except Exception as ex:
            logger.debug("Reprocessar ícone %s: %s", item_id, ex)
    return fixed


def read_item_icon_png_bytes(
    item_id: int,
    url: str,
    fetch_url_bytes: Callable[[str], Optional[bytes]],
    **kwargs,
) -> Optional[bytes]:
    """Disco (se pronto) → download processicon → processar → gravar 24×24."""
    base_url = str(kwargs.get("base_url") or _DEFAULT_BASE_URL)
    ensure_item_icons_dir()
    path = item_icon_disk_path(item_id)

    cached = _read_cached_icon_bytes(item_id)
    if cached and _icon_cache_is_ready(cached):
        return cached

    if cached:
        try:
            from PIL import Image

            im = Image.open(BytesIO(cached)).convert("RGBA")
            im = process_icon_image(im)
            _save_icon_png(item_id, im)
            return _read_cached_icon_bytes(item_id)
        except Exception as ex:
            logger.debug("Reprocessar ícone em cache %s: %s", item_id, ex)

    download_url = _processicon_url(item_id, base_url=base_url)
    try:
        raw = fetch_url_bytes(download_url)
    except Exception as ex:
        logger.debug("Baixar ícone item %s: %s", item_id, ex)
        return cached
    if not raw:
        return cached

    try:
        from PIL import Image

        im = Image.open(BytesIO(raw)).convert("RGBA")
        im = process_icon_image(im)
        _save_icon_png(item_id, im)
        return _read_cached_icon_bytes(item_id) or raw
    except Exception as ex:
        logger.debug("Gravar ícone %s: %s", path, ex)
        return cached


def png_bytes_to_data_uri(raw: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def read_cached_icon_data_uri(item_id: int) -> str:
    """Devolve data URI só se o PNG já existir em ``data/item_icons/`` (sem rede)."""
    try:
        iid = int(item_id)
    except (TypeError, ValueError):
        return ""
    if iid <= 0:
        return ""
    raw = _read_cached_icon_bytes(iid)
    if raw and _icon_cache_is_ready(raw):
        return png_bytes_to_data_uri(raw)
    return ""


def fetch_icons_batch(
    items: list[tuple[int, str]],
    fetch_url_bytes: Callable[[str], Optional[bytes]],
    *,
    base_url: str = _DEFAULT_BASE_URL,
    max_workers: int = 4,
) -> dict[int, str]:
    """Baixa/processa ícones em paralelo (fila controlada). Devolve {item_id: data_uri}."""
    unique: dict[int, str] = {}
    for iid, url in items:
        try:
            nid = int(iid)
        except (TypeError, ValueError):
            continue
        if nid > 0 and nid not in unique:
            unique[nid] = str(url or "")

    if not unique:
        return {}

    def _one(pair: tuple[int, str]) -> tuple[int, str]:
        iid, url = pair
        try:
            raw = read_item_icon_png_bytes(
                iid, url, fetch_url_bytes, base_url=base_url
            )
            if raw:
                return iid, png_bytes_to_data_uri(raw)
        except Exception as ex:  # noqa: BLE001
            logger.debug("Ícone em lote %s: %s", iid, ex)
        return iid, ""

    out: dict[int, str] = {}
    workers = max(1, min(int(max_workers or 4), 8))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for iid, uri in pool.map(_one, unique.items()):
            if uri:
                out[iid] = uri
    return out
