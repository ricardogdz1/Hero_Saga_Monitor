"""
Timer de MVP — dados persistidos e auxiliares Divine Pride.

Usa API database Monster/Map (chave em Configurações ou DIVINE_PRIDE_API_KEY).
O catálogo MVP (lista + mapas de spawn) grava-se em ``data/mvp_catalog_cache.json``
na pasta do programa — carrega de imediato sem nova rede até actualizar manualmente.
Imagens de mapa tentam URLs habituais do divine-pride.net.
Sprites MVP: PNG em ``data/mvp_sprites/{id}.png`` (rápido; importar com
``tools/import_mvp_png_folder.py``), ou ``data/mvp_sprites_ai4rei/*.png``
(exportados do HAR nn.ai4rei.net — ver ``tools/import_mvp_sprites_from_har.py``). Cache legacy em ``herosaga_dp_mob_images``.
Em builds PyInstaller, a pasta ``data/`` deve ser incluída (ver ``HerosagaMonitor.spec``).
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
import unicodedata
import uuid
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from divine_pride_api import DEFAULT_MONSTER_ACCEPT_LANGUAGE

logger = logging.getLogger(__name__)

# Pasta do módulo (raiz do projecto quando corre a partir da pasta herosaga_monitor)
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
MVP_CATALOG_DATA_DIR = os.path.join(_APP_DIR, "data")
MVP_CATALOG_PORTABLE_FILE = os.path.join(MVP_CATALOG_DATA_DIR, "mvp_catalog_cache.json")
# Cache antigo no perfil do utilizador (ainda lido para migração)
MVP_CATALOG_CACHE_FILE_LEGACY = os.path.join(os.path.expanduser("~"), "herosaga_dp_mvp_catalog.json")
MVP_CATALOG_CACHE_FILE = MVP_CATALOG_CACHE_FILE_LEGACY

MVP_DATA_FILE = os.path.join(os.path.expanduser("~"), "herosaga_mvp_timers.json")
MVP_MOB_IMAGE_CACHE_DIR = os.path.join(os.path.expanduser("~"), "herosaga_dp_mob_images")
MVP_SPRITES_DIR = os.path.join(MVP_CATALOG_DATA_DIR, "mvp_sprites")
MVP_SPRITES_AI4REI_DIR = os.path.join(MVP_CATALOG_DATA_DIR, "mvp_sprites_ai4rei")
# Minimapas por nome de mapa (ex. moc_pryd06.png) — importar com tools/import_mvp_map_folder.py
MVP_MAPS_DIR = os.path.join(MVP_CATALOG_DATA_DIR, "mvp_maps")
# Mapa ID Divine Pride → stem PNG ai4rei (ex. 1038 → OSIRIS). Gerado por tools/import_mvp_sprites_from_har.py
MVP_SPRITE_ID_MAP_FILE = os.path.join(MVP_CATALOG_DATA_DIR, "mvp_sprite_id_map.json")
MVP_SPRITE_ID_MAP_OVERRIDES_FILE = os.path.join(MVP_CATALOG_DATA_DIR, "mvp_sprite_id_map_overrides.json")

DIVINE_MONSTER_LIST_URL = "https://www.divine-pride.net/database/monster"

# Lista MVP (HTML): Accept-Language explícito em inglês.
DIVINE_PRIDE_LIST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": DEFAULT_MONSTER_ACCEPT_LANGUAGE,
}

MAP_IMAGE_CANDIDATES = (
    "https://www.divine-pride.net/img/maps/{map}.png",
    "https://www.divine-pride.net/img/maps/{map}.bmp",
    "https://www.divine-pride.net/img/maps/{map}.jpg",
    "https://static.divine-pride.net/images/maps/{map}.png",
)


def _safe_map_name(mapname: str) -> str:
    return (mapname or "").strip().lower().replace(" ", "_")


def fetch_url_bytes(url: str, timeout: float = 15.0) -> Optional[bytes]:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "HerosagaMonitor/1.0"})
        if r.status_code == 200 and r.content:
            return r.content
    except Exception as e:
        logger.debug("fetch_url_bytes %s: %s", url, e)
    return None


def _local_map_image_candidates(mapname: str) -> List[str]:
    """Caminhos locais possíveis para o nome de mapa (variante com/sem underscore final)."""
    m = _safe_map_name(mapname)
    if not m:
        return []
    stems = [m]
    if m.endswith("_"):
        alt = m.rstrip("_")
        if alt:
            stems.append(alt)
    else:
        stems.append(m + "_")
    seen: set = set()
    paths: List[str] = []
    for stem in stems:
        for ext in (".png", ".jpg", ".jpeg", ".bmp"):
            p = os.path.join(MVP_MAPS_DIR, stem + ext)
            if p not in seen:
                seen.add(p)
                paths.append(p)
    return paths


def resolve_map_image(mapname: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Devolve (bytes, origem) — primeiro ``data/mvp_maps/``, depois URLs Divine Pride."""
    m = _safe_map_name(mapname)
    if not m:
        return None, None
    for path in _local_map_image_candidates(mapname):
        if os.path.isfile(path):
            try:
                with open(path, "rb") as f:
                    data = f.read()
                if data:
                    return data, f"local:{path}"
            except OSError as e:
                logger.debug("resolve_map_image local %s: %s", path, e)
    for tpl in MAP_IMAGE_CANDIDATES:
        url = tpl.format(map=m)
        data = fetch_url_bytes(url)
        if data:
            return data, url
    return None, None


def mob_image_cache_path(monster_id: int) -> str:
    return os.path.join(MVP_MOB_IMAGE_CACHE_DIR, str(int(monster_id)))


def read_mob_image_cache(monster_id: int) -> Optional[bytes]:
    path = mob_image_cache_path(monster_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError as e:
        logger.debug("read_mob_image_cache %s: %s", path, e)
        return None


def write_mob_image_cache(monster_id: int, data: bytes) -> None:
    if not data:
        return
    try:
        os.makedirs(MVP_MOB_IMAGE_CACHE_DIR, exist_ok=True)
        path = mob_image_cache_path(monster_id)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError as e:
        logger.debug("write_mob_image_cache %s: %s", monster_id, e)


def mob_image_is_cached(monster_id: int) -> bool:
    return os.path.isfile(mob_image_cache_path(monster_id))


def _normalize_mvp_name_for_sprite(name: str) -> str:
    """Nome de exibição Divine Pride → chave estilo ai4rei (MAIÚSCULAS, underscores)."""
    n = (name or "").strip()
    if not n:
        return ""
    n = re.sub(r"\s*\([^)]*\)", " ", n)
    n = unicodedata.normalize("NFKD", n)
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    n = n.replace("-", "_")
    n = re.sub(r"[^\w\s]+", " ", n, flags=re.UNICODE)
    n = re.sub(r"[\s_]+", "_", n).strip("_").upper()
    return n


def mvp_sprite_norm_candidates(display_name: str) -> List[str]:
    """
    Possíveis chaves normalizadas para cruzar com stems .spr / ai4rei.
    Inclui remoção do prefixo «Phantom » (variantes usam o sprite do boss base).
    """
    raw = (display_name or "").strip()
    if not raw:
        return []
    seen: set[str] = set()
    out: List[str] = []

    def add(n: str) -> None:
        if n and n not in seen:
            seen.add(n)
            out.append(n)

    add(_normalize_mvp_name_for_sprite(raw))
    low = raw.casefold()
    if low.startswith("phantom "):
        add(_normalize_mvp_name_for_sprite(raw[8:].strip()))
    first = out[0] if out else ""
    if first.startswith("PHANTOM_") and len(first) > len("PHANTOM_"):
        add(first[len("PHANTOM_") :])
    return out


# Nomes normalizados Divine Pride → nome base do ficheiro ai4rei (sem .png), quando != normalização directa.
_MVP_SPRITE_NORM_TO_AI4REI_KEY: Dict[str, str] = {
    "ORC_HERO": "ORK_HERO",
    "MOONLIGHT_FLOWER": "MOONLIGHT",
    "GOLDEN_THIEF_BUG": "GOLDEN_BUG",
    "LORD_KNIGHT_SEYREN": "SEYREN",
    "RUNE_KNIGHT_SEYREN": "SEYREN",
    "ASSASSIN_CROSS_EREMES": "EREMES",
    "GUILLOTINE_CROSS_EREMES": "EREMES",
    "HIGH_WIZARD_KATHRYNE": "KATRINN",
    "HIGH_WIZARD_OF_ILLUSION": "KATRINN",
    "HIGH_PRIEST_MARGARETHA": "MAGALETA",
    "ARCHBISHOP_MARGARETHA": "MAGALETA",
    "RANGER_CECIL": "SHECIL",
    "SNIPER_CECIL": "SHECIL",
    "WHITESMITH_HOWARD": "HARWORD",
    "PHANTOM_RSX_0806": "RSX_0806",
    "EGNIGEM_CENIA": "YGNIZEM",
    "EVIL_SNAKE_LORD": "DARK_SNAKE_LORD",
    "PHANTOM_EVIL_SNAKE_LORD": "DARK_SNAKE_LORD",
    "SAMURAI_SPECTER": "INCANTATION_SAMURAI",
    "STORMY_KNIGHT": "KNIGHT_OF_WINDSTORM",
}


def _mvp_ai4rei_png_stems() -> frozenset:
    if not os.path.isdir(MVP_SPRITES_AI4REI_DIR):
        return frozenset()
    out: set = set()
    try:
        for f in os.listdir(MVP_SPRITES_AI4REI_DIR):
            if f.lower().endswith(".png"):
                out.add(os.path.splitext(f)[0].upper())
    except OSError as e:
        logger.debug("list %s: %s", MVP_SPRITES_AI4REI_DIR, e)
        return frozenset()
    return frozenset(out)


def mvp_display_name_to_ai4rei_sprite_key(display_name: str) -> Optional[str]:
    """
    Devolve o stem do PNG em ``mvp_sprites_ai4rei`` que corresponde ao nome do MVP, ou None.
    """
    if not (display_name or "").strip():
        return None
    stems = _mvp_ai4rei_png_stems()
    if not stems:
        return None

    def _try(n: str) -> Optional[str]:
        if not n:
            return None
        k = _MVP_SPRITE_NORM_TO_AI4REI_KEY.get(n, n)
        if k in stems:
            return k
        return None

    suffixes = (
        "_THE_ILLUSION",
        "_ILLUSION",
        "_OF_ILLUSION",
        "_OF_THE_ILLUSIO",
        "_NIGHTMARE",
    )
    for norm in mvp_sprite_norm_candidates(display_name):
        hit = _try(norm)
        if hit:
            return hit
        for suffix in suffixes:
            if norm.endswith(suffix):
                shorter = norm[: -len(suffix)].strip("_")
                hit = _try(shorter)
                if hit:
                    return hit
    return None


_mvp_sprite_id_map_cache: Optional[Dict[int, str]] = None


def invalidate_mvp_sprite_id_map_cache() -> None:
    global _mvp_sprite_id_map_cache
    _mvp_sprite_id_map_cache = None


def load_mvp_sprite_id_map() -> Dict[int, str]:
    """
    ID Divine Pride → stem PNG em ``mvp_sprites_ai4rei`` (ex. 1038 → OSIRIS).

    Lê ``mvp_sprite_id_map.json`` (gerado na importação) e opcionalmente
    ``mvp_sprite_id_map_overrides.json`` (entradas manuais sobrepõem).
    """
    global _mvp_sprite_id_map_cache
    if _mvp_sprite_id_map_cache is not None:
        return _mvp_sprite_id_map_cache
    merged: Dict[int, str] = {}
    for path in (MVP_SPRITE_ID_MAP_FILE, MVP_SPRITE_ID_MAP_OVERRIDES_FILE):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError, TypeError) as e:
            logger.debug("load_mvp_sprite_id_map %s: %s", path, e)
            continue
        if not isinstance(raw, dict):
            continue
        inner = raw.get("monster_id_to_sprite_key")
        if not isinstance(inner, dict):
            inner = raw
        meta = {"version", "source", "monster_id_to_sprite_key"}
        for k, v in inner.items():
            sk = str(k)
            if sk in meta:
                continue
            if not isinstance(v, str) or not v.strip():
                continue
            try:
                ik = int(k)
            except (TypeError, ValueError):
                continue
            merged[ik] = v.strip().upper()
    _mvp_sprite_id_map_cache = merged
    return merged


def resolve_mob_image(
    monster_id: int,
    *,
    display_name: str = "",
    allow_network: bool = True,
) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Sprite local: (1) ``data/mvp_sprites/{id}.png``; (2) mapa JSON id→chave ai4rei;
    (3) nome → ai4rei; (4) ``herosaga_dp_mob_images/{id}``. allow_network ignorado.
    """
    _ = allow_network
    mid = int(monster_id)
    p_bundle = os.path.join(MVP_SPRITES_DIR, f"{mid}.png")
    if os.path.isfile(p_bundle):
        try:
            with open(p_bundle, "rb") as f:
                return f.read(), "bundle"
        except OSError as e:
            logger.debug("resolve_mob_image bundle %s: %s", p_bundle, e)
    key = load_mvp_sprite_id_map().get(mid)
    if key:
        p_ai = os.path.join(MVP_SPRITES_AI4REI_DIR, f"{key}.png")
        if os.path.isfile(p_ai):
            try:
                with open(p_ai, "rb") as f:
                    return f.read(), "id_map"
            except OSError as e:
                logger.debug("resolve_mob_image id_map %s: %s", p_ai, e)
    key = mvp_display_name_to_ai4rei_sprite_key(display_name or "")
    if key:
        p_ai = os.path.join(MVP_SPRITES_AI4REI_DIR, f"{key}.png")
        if os.path.isfile(p_ai):
            try:
                with open(p_ai, "rb") as f:
                    return f.read(), "ai4rei"
            except OSError as e:
                logger.debug("resolve_mob_image ai4rei %s: %s", p_ai, e)
    cached = read_mob_image_cache(mid)
    if cached:
        return cached, "cache"
    return None, None


def respawn_ms_to_seconds(ms: Any) -> int:
    try:
        v = float(ms)
    except (TypeError, ValueError):
        return 0
    if v <= 0:
        return 0
    # API Divine Pride usa milissegundos nos exemplos (ex.: 5000, 120000, 7200000).
    s = int(round(v / 1000.0))
    return max(1, s)


def spawn_maps_from_monster(data: Dict[str, Any]) -> List[str]:
    """Extrai nomes de mapa das entradas ``spawn`` da API Divine Pride (Monster)."""
    out: List[str] = []
    raw = data.get("spawn")
    if raw is None:
        raw = data.get("Spawn")
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return out
    for s in raw:
        if not isinstance(s, dict):
            continue
        mn = (
            s.get("mapname")
            or s.get("mapName")
            or s.get("map")
            or s.get("Map")
            or s.get("map_name")
            or ""
        )
        mn = str(mn).strip()
        if mn and mn not in out:
            out.append(mn)
    return out


def default_respawn_seconds(data: Dict[str, Any]) -> int:
    """Maior respawnTime entre entradas de spawn (útil quando há vários mapas)."""
    best = 0
    for s in data.get("spawn") or []:
        if not isinstance(s, dict):
            continue
        sec = respawn_ms_to_seconds(s.get("respawnTime"))
        best = max(best, sec)
    return best if best > 0 else 7200


def monster_is_mvp(data: Dict[str, Any]) -> bool:
    st = data.get("stats")
    if isinstance(st, dict):
        try:
            return int(st.get("mvp") or 0) != 0
        except (TypeError, ValueError):
            pass
    return False


def monster_api_display_name(data: Dict[str, Any]) -> str:
    """Campo ``name`` do JSON da API Monster (inglês com ``Accept-Language: en``)."""
    if not isinstance(data, dict):
        return ""
    return str(data.get("name") or data.get("Name") or "").strip()


def summarize_monster_for_timer(data: Dict[str, Any]) -> Dict[str, Any]:
    """Metadados para a UI (sem guardar ainda o timer)."""
    mid = int(data.get("id") or 0)
    name = monster_api_display_name(data) or str(data.get("name") or f"Monster {mid}").strip()
    maps = spawn_maps_from_monster(data)
    resp = default_respawn_seconds(data)
    is_mvp = monster_is_mvp(data)
    return {
        "monster_id": mid,
        "name": name,
        "spawn_maps": maps,
        "respawn_seconds": resp,
        "is_mvp": is_mvp,
    }


def load_mvp_storage() -> Dict[str, Any]:
    raw: Dict[str, Any] = {"version": 1, "entries": []}
    if os.path.exists(MVP_DATA_FILE):
        try:
            with open(MVP_DATA_FILE, "r", encoding="utf-8") as f:
                o = json.load(f)
            if isinstance(o, dict) and isinstance(o.get("entries"), list):
                raw = o
        except Exception as e:
            logger.warning("load_mvp_storage: %s", e)
    raw.setdefault("version", 1)
    if not isinstance(raw.get("entries"), list):
        raw["entries"] = []
    return raw


def save_mvp_storage(data: Dict[str, Any]) -> None:
    out = {"version": 1, "entries": list(data.get("entries") or [])}
    with open(MVP_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


def new_timer_entry(
    monster_id: int,
    name: str,
    spawn_maps: List[str],
    respawn_seconds: int,
    *,
    death_map: str = "",
    death_x: Optional[int] = None,
    death_y: Optional[int] = None,
    death_at_iso: Optional[str] = None,
) -> Dict[str, Any]:
    # None → agora (compat). "" → ainda por configurar na janela de edição (timer não corre).
    if death_at_iso is None:
        death_at_iso = datetime.now().isoformat(timespec="seconds")
    return {
        "entry_id": str(uuid.uuid4()),
        "monster_id": int(monster_id),
        "name": name,
        "spawn_maps": list(spawn_maps or []),
        "respawn_seconds": max(60, int(respawn_seconds)),
        "death_map": (death_map or (spawn_maps[0] if spawn_maps else "")) or "",
        "death_x": death_x,
        "death_y": death_y,
        "death_at": death_at_iso,
        "alert_fired": False,
    }


def parse_user_datetime(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")[:19])
    except ValueError:
        return None


def mvp_map_pixel_is_walkable(r: int, g: int, b: int, a: int, *, min_alpha: int = 16, min_luma: int = 24) -> bool:
    """True se o pixel pertence ao desenho do mapa (não fundo preto/transparente)."""
    if a < min_alpha:
        return False
    return (int(r) + int(g) + int(b)) >= min_luma


def build_mvp_map_click_mask_from_image(im) -> Tuple[int, int, bytes]:
    """
    Máscara row-major (1 = clicável) com as mesmas dimensões da imagem do minimapa.
    *im* deve ser PIL Image em modo RGBA.
    """
    try:
        from PIL import Image
    except ImportError:
        return 0, 0, b""
    if not isinstance(im, Image.Image):
        return 0, 0, b""
    rgba = im.convert("RGBA")
    w, h = rgba.size
    if w <= 0 or h <= 0:
        return 0, 0, b""
    px = rgba.load()
    mask = bytearray(w * h)
    for y in range(h):
        row = y * w
        for x in range(w):
            r, g, b, a = px[x, y]
            if mvp_map_pixel_is_walkable(r, g, b, a):
                mask[row + x] = 1
    return w, h, bytes(mask)


def _game_y_to_image_row(gy: int, img_h: int) -> int:
    """Converte Y de jogo (origem no canto inferior esquerdo) para linha da imagem (topo = 0)."""
    return img_h - 1 - int(gy)


def is_mvp_map_coord_clickable(gx: int, gy: int, mask_w: int, mask_h: int, mask: bytes) -> bool:
    """*gx*/*gy* em coordenadas de jogo (origem no canto inferior esquerdo)."""
    if mask_w <= 0 or mask_h <= 0 or len(mask) < mask_w * mask_h:
        return False
    if gx < 0 or gy < 0 or gx >= mask_w or gy >= mask_h:
        return False
    iy = _game_y_to_image_row(gy, mask_h)
    return mask[iy * mask_w + gx] != 0


def mvp_map_display_layout(
    native_w: int, native_h: int, box_w: int, box_h: int
) -> Tuple[int, int, int, int]:
    """
    Escala uniforme para o maior lado do mapa preencher a caixa (*box_w*×*box_h*),
    mantendo a grelha nativa 1:1 nas conversões de coordenadas.
    Devolve ``(display_w, display_h, offset_x, offset_y)`` para centrar na caixa.
    """
    if native_w <= 0 or native_h <= 0 or box_w <= 0 or box_h <= 0:
        return 0, 0, 0, 0
    fit_side = min(box_w, box_h)
    long_side = max(native_w, native_h)
    scale = fit_side / float(long_side)
    dw = max(1, int(round(native_w * scale)))
    dh = max(1, int(round(native_h * scale)))
    if dw > box_w:
        scale = box_w / float(native_w)
        dw = box_w
        dh = max(1, int(round(native_h * scale)))
    if dh > box_h:
        scale = box_h / float(native_h)
        dh = box_h
        dw = max(1, int(round(native_w * scale)))
    off_x = max(0, (box_w - dw) // 2)
    off_y = max(0, (box_h - dh) // 2)
    return dw, dh, off_x, off_y


def _scale_display_to_native(
    px: float, py: float, native_w: int, native_h: int, display_w: int, display_h: int
) -> Tuple[float, float]:
    if display_w <= 0 or display_h <= 0:
        return px, py
    if display_w == native_w and display_h == native_h:
        return px, py
    return px * native_w / float(display_w), py * native_h / float(display_h)


def pixel_to_game_coords(
    px: float,
    py: float,
    img_w: int,
    img_h: int,
    *,
    display_w: Optional[int] = None,
    display_h: Optional[int] = None,
) -> Tuple[int, int]:
    """
    Coordenadas de jogo 1:1 com o minimapa: 1 célula = 1 pixel.
    Origem (0, 0) no canto **inferior esquerdo**; Y cresce para cima.
    *px*/*py* são coordenadas de ecrã/imagem (origem no canto superior esquerdo).
    """
    if img_w <= 0 or img_h <= 0:
        return 0, 0
    dw = int(display_w) if display_w is not None else img_w
    dh = int(display_h) if display_h is not None else img_h
    nx, ny = _scale_display_to_native(px, py, img_w, img_h, dw, dh)
    ix = int(max(0, min(img_w - 1, math.floor(nx))))
    iy = int(max(0, min(img_h - 1, math.floor(ny))))
    gx = ix
    gy = img_h - 1 - iy
    return gx, gy


def game_to_pixel_coords(
    gx: int,
    gy: int,
    img_w: int,
    img_h: int,
    *,
    display_w: Optional[int] = None,
    display_h: Optional[int] = None,
) -> Tuple[float, float]:
    """Centro do pixel na imagem (inverso de ``pixel_to_game_coords``; origem de jogo em baixo à esquerda)."""
    if img_w <= 0 or img_h <= 0:
        return 0.0, 0.0
    ggx = max(0, min(img_w - 1, int(gx)))
    ggy = max(0, min(img_h - 1, int(gy)))
    iy = img_h - 1 - ggy
    px = float(ggx) + 0.5
    py = float(iy) + 0.5
    dw = int(display_w) if display_w is not None else img_w
    dh = int(display_h) if display_h is not None else img_h
    if dw != img_w or dh != img_h:
        px = px / float(img_w) * float(dw)
        py = py / float(img_h) * float(dh)
    return px, py


def next_spawn_at(entry: Dict[str, Any]) -> Optional[datetime]:
    dt = parse_user_datetime(str(entry.get("death_at") or ""))
    if not dt:
        return None
    try:
        sec = int(entry.get("respawn_seconds") or 0)
    except (TypeError, ValueError):
        sec = 0
    if sec <= 0:
        return None
    return dt + timedelta(seconds=sec)


def seconds_until_spawn(entry: Dict[str, Any]) -> Optional[float]:
    n = next_spawn_at(entry)
    if not n:
        return None
    return (n - datetime.now()).total_seconds()


def format_countdown(sec: Optional[float]) -> str:
    if sec is None:
        return "—"
    if sec <= 0:
        return "Nasceu (actualize a morte)"
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d > 0:
        return f"{d}d {h:02d}:{m:02d}:{s:02d}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_countdown_clock(sec: Optional[float]) -> str:
    """Relógio «HH : MM : SS»; valores negativos = tempo desde o respawn esperado (MVP possivelmente vivo)."""
    if sec is None:
        return "-- : -- : --"
    if sec > 0:
        s = int(sec)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        d, h = divmod(h, 24)
        if d > 0:
            return f"{d}d {h:02d} : {m:02d} : {s:02d}"
        return f"{h:02d} : {m:02d} : {s:02d}"
    if sec == 0:
        return "00 : 00 : 00"
    s_abs = int(abs(sec))
    m, s = divmod(s_abs, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d > 0:
        return f"-{d}d {h:02d} : {m:02d} : {s:02d}"
    return f"-{h:02d} : {m:02d} : {s:02d}"


def mvp_dashboard_status_text(ent: Optional[Dict[str, Any]]) -> str:
    if not ent:
        return "NÃO REGISTRADO"
    su = seconds_until_spawn(ent)
    if su is None:
        return "NÃO REGISTRADO"
    if su > 0:
        return "RESPAWN PENDENTE"
    return "DISPONÍVEL"


_INSTANCE_MVP_NAME_SNIPPETS = (
    "instance",
    "instância",
    "instancia",
)


def mvp_name_is_instance_variant(name: str) -> bool:
    """True se o nome indicar MVP de masmorra de instância (Divine Pride / RO)."""
    n = (name or "").casefold()
    return any(s in n for s in _INSTANCE_MVP_NAME_SNIPPETS)


def mvp_name_has_asian_script(name: str) -> bool:
    """
    True se o nome contém sílabas Hangul, ideogramas CJK ou kana (hiragana/katakana).
    Exclui estes MVPs do catálogo visível para evitar nomes só em japonês/coreano/chinês.
    """
    for ch in str(name or ""):
        o = ord(ch)
        # Hangul
        if 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F or 0xAC00 <= o <= 0xD7AF:
            return True
        # CJK Unified + ext. A
        if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:
            return True
        # Hiragana / Katakana
        if 0x3040 <= o <= 0x309F or 0x30A0 <= o <= 0x30FF:
            return True
        # Kana supplement, CJK compat (sinais comuns em nomes JP)
        if 0x1B000 <= o <= 0x1B16F:
            return True
        if 0x3300 <= o <= 0x33FF:
            return True
    return False


def mvp_name_is_placeholder_monster_name(name: str) -> bool:
    """
    Nome genérico do Divine Pride (placeholders sem monstro real definido).
    Ex.: «Monster Name», «[PH] Monster Name» (remove-se prefixos entre colchetes),
    ou «Unidentified Creature» (entrada sem nome útil na API).
    """
    s = (name or "").strip().casefold()
    if not s:
        return False
    t = s
    while True:
        nxt = re.sub(r"^\[[^\]]+\]\s*", "", t).strip()
        if nxt == t:
            break
        t = nxt
    if t == "monster name":
        return True
    return t == "unidentified creature"


def mvp_name_skipped_in_catalog(name: str) -> bool:
    """MVP omitido da lista local: instância, nome CJK/kana/Hangul, placeholders ou lista explícita."""
    return (
        mvp_name_is_instance_variant(name)
        or mvp_name_has_asian_script(name)
        or mvp_name_is_placeholder_monster_name(name)
        or mvp_name_is_blocked_from_catalog(name)
    )


# IDs excluídos explicitamente da lista MVP (instâncias / eventos).
_MVP_CATALOG_BLOCKED_IDS = frozenset(
    {
        1518,
        1646,
        1647,
        1648,
        1649,
        1650,
        1651,
        1779,
        1980,
        20260,
        20346,
        20642,
        2194,
        22179,
        3190,
        3220,
        3221,
        3222,
        3223,
        3224,
        3225,
        3240,
        3241,
        3242,
        3243,
        3244,
        3245,
        3246,
        3628,
        3659,
        1956,
        20061,
        20181,
        20182,
        20183,
        20184,
        20185,
        20186,
        20187,
        20189,
        20190,
        20192,
        20194,
        20196,
        20198,
        20202,
        20203,
        20204,
        20205,
        20209,
        20216,
        20217,
        20223,
        20227,
        20229,
        20230,
        20247,
        20273,
        20277,
        20419,
        20421,
        20423,
        20424,
        20425,
        20520,
        20536,
        20573,
        20621,
        20648,
        20659,
        20667,
        20668,
        20785,
        20811,
        20843,
        21531,
        21533,
        21555,
        21571,
        21579,
        21904,
        21927,
        21935,
        21943,
        21981,
        21982,
        22177,
        22178,
        22180,
        2255,
        2319,
        2341,
        2442,
        2475,
        2476,
        2483,
        2564,
        3000,
        3029,
        3073,
        3097,
        3150,
        3151,
        3188,
        3426,
        3427,
        3428,
        3429,
        3430,
        3450,
        3633,
        3658,
        3757,
        3758,
        3796,
        3804,
        3810,
    }
)


def mvp_id_skipped_in_catalog(mid: int) -> bool:
    try:
        return int(mid) in _MVP_CATALOG_BLOCKED_IDS
    except (TypeError, ValueError):
        return False


def mvp_catalog_entry_skipped(it: Dict[str, Any]) -> bool:
    """MVP omitido: id na lista de bloqueio ou regras de nome em ``mvp_name_skipped_in_catalog``."""
    if not isinstance(it, dict):
        return True
    try:
        mid = int(it.get("id") or 0)
    except (TypeError, ValueError):
        mid = 0
    if mid and mvp_id_skipped_in_catalog(mid):
        return True
    return mvp_name_skipped_in_catalog(str(it.get("name") or ""))


def normalize_text_for_search(s: str) -> str:
    """Minúsculas e sem acentos — comparação tolerante para busca na UI."""
    if not s:
        return ""
    t = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in t if not unicodedata.combining(c)).casefold()


# Nomes excluídos da lista MVP (instâncias, eventos, placeholders de dados) — chave normalizada como na busca.
_MVP_CATALOG_BLOCKED_RAW = (
    "B Alphoccio",
    "B Celia",
    "B Chen",
    "B Flamel",
    "B Gertie",
    "B Randel",
    "B Trentini",
    "Bring it on!",
    "Curse-swallowed King",
    "Ditardeurs of Fire",
    "EL1_A17T#boss",
    "Faceworm Queen",
    "Lost Dragon",
    "Pet child",
    "Phantom Clown",
    "Phantom Ifrit",
    "Tao Gunka of Welcome",
    "the	Last one",
    "Welcome Hati",
    "Welcome Moonlight",
    "Welcome Orc Hero",
    "Welcome Turtle General",
    "Celine Kimi",
    "Coelacanth H A",
    "Charleston 3",
    "Coelacanth H M",
    "Coelacanth N A",
    "Coelacanth N M",
    "Entweihen Crothen",
    "Illusion Lord Knight",
    "Evil Believer",
    "Fenrir",
    "Mistress of Prairie",
    "Morocc Necromancer",
    "Phantom Atroce",
    "Phantom Amdarais",
    "Phantom Charleston No.3",
    "Phantom Champion",
    "Phantom Creator",
    "Phantom Detardeurus",
    "Phantom Entweihen Crothen",
    "Phantom Evil Snake Lord",
    "Phantom Fallen Bishop",
    "Phantom General Daehyun",
    "Phantom Gioia",
    "Phantom Gopinich",
    "Phantom Guardian Kades",
    "Phantom Gypsy",
    "Phantom Heart Hunter Evil",
    "Phantom Himmelmez",
    "Phantom Kiel-D-01",
    "Phantom Kraken",
    "Phantom Ktullanux",
    "Phantom Lady Tanee",
    "Phantom Leak",
    "Phantom Lord of the Dead",
    "Phantom Naght Sieger",
    "Phantom Nidhogg's Shadow",
    "Phantom Paladin",
    "Phantom Pharaoh",
    "Phantom Professor",
    "Phantom Queen Scaraba",
    "Phantom Randgris",
    "Phantom Rejected Pyuriel",
    "Phantom RSX-0806",
    "Phantom Seyren Windsor",
    "Phantom Sniper",
    "Phantom Spider Mech",
    "Phantom Stalker",
    "Phantom Thanatos",
    "Phantom Time Holder",
    "Phantom Toxic Chimera",
    "Phantom Vesper",
    "Phantom White Lady",
    "Phantom Wraith Samurai",
    "S Nydhog",
    "Stefan.J.E.Wolf",
    "T_W_O",
    "Thanatos Phantom",
    "Welcome Maya",
)
_MVP_CATALOG_BLOCKED_NORMALIZED = frozenset(
    normalize_text_for_search(re.sub(r"\s+", " ", x.strip())) for x in _MVP_CATALOG_BLOCKED_RAW
)


def mvp_name_is_blocked_from_catalog(name: str) -> bool:
    """MVP omitido por lista fixa (mesma normalização de acentos/case que a busca)."""
    s = re.sub(r"\s+", " ", (name or "").strip())
    if not s:
        return False
    return normalize_text_for_search(s) in _MVP_CATALOG_BLOCKED_NORMALIZED


def mvp_catalog_matches_search(it: Dict[str, Any], query: str) -> bool:
    """
    Filtro de busca MVP: vazio passa tudo; várias palavras = todas devem casar
    (subcadeia no nome normalizado ou palavra semelhante para erros de digitação).
    Se a consulta for só dígitos, também procura no id do monstro.
    """
    q_raw = (query or "").strip()
    if not q_raw:
        return True
    if mvp_catalog_entry_skipped(it):
        return False
    try:
        mid = int(it.get("id") or 0)
    except (TypeError, ValueError):
        mid = 0
    if q_raw.isdigit() and mid and q_raw in str(mid):
        return True
    n = normalize_text_for_search(str(it.get("name") or ""))
    qn = normalize_text_for_search(q_raw)
    if not qn:
        return True

    def _token_matches(part: str) -> bool:
        if not part:
            return True
        if part in n:
            return True
        words = [w for w in n.split() if w]
        for w in words:
            if part in w or w in part:
                return True
        if len(part) >= 3:
            for w in words:
                if len(w) >= 3 and SequenceMatcher(None, part, w).ratio() >= 0.72:
                    return True
        return False

    for part in qn.split():
        if not _token_matches(part):
            return False
    return True


def _last_monster_list_page(html: str) -> int:
    # Com server=bRO a query fica tipo monster?server=bRO&Page=N (ordem varia).
    m = re.search(r'href="/database/monster\?[^"]*Page=(\d+)[^"]*">Last</a>', html)
    if not m:
        return 1
    try:
        return max(1, int(m.group(1)))
    except (TypeError, ValueError):
        return 1


def parse_mvp_rows_from_monster_search_html(html: str) -> List[Dict[str, Any]]:
    """
    Extrai (id, nome) dos MVPs numa página de pesquisa do site Divine Pride.
    O site aplica ``class=\"mvp\"`` à célula do nome para monstros classificados como MVP.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []
    for tr in soup.find_all("tr"):
        if not tr.find("td", class_="mvp"):
            continue
        a = tr.find("a", href=re.compile(r"^/database/monster/\d+/"))
        if not a or not a.get("href"):
            continue
        mm = re.search(r"/database/monster/(\d+)/", str(a["href"]))
        if not mm:
            continue
        try:
            mid = int(mm.group(1))
        except (TypeError, ValueError):
            continue
        name = (a.get_text() or "").strip()
        if mid and name and not mvp_catalog_entry_skipped({"id": mid, "name": name}):
            out.append({"id": mid, "name": name})
    return out


def _divine_monster_list_page_url(list_url: str, page: int, server: Optional[str]) -> str:
    base = list_url.rstrip("/")
    q: Dict[str, str] = {"Page": str(int(page))}
    if server and str(server).strip():
        q["server"] = str(server).strip()
    return f"{base}?{urlencode(q)}"


def fetch_mvp_catalog_from_divine_pride(
    session: Any,
    *,
    list_url: str = DIVINE_MONSTER_LIST_URL,
    list_server: Optional[str] = None,
    delay_s: float = 0.12,
    timeout: float = 35.0,
) -> List[Dict[str, Any]]:
    """
    Percorre todas as páginas da lista geral de monstros e devolve MVPs (site, não API).
    *session* deve ter ``.get(url, timeout=...)`` (ex. ``cloudscraper`` ou ``requests.Session``).

    *list_server*: região opcional na query (ex. ``"bRO"``). ``None`` ou string vazia omitem ``server=``.
    """
    if list_server is None:
        srv: Optional[str] = None
    else:
        srv = str(list_server).strip() or None

    url1 = _divine_monster_list_page_url(list_url, 1, srv)
    r = session.get(url1, headers=DIVINE_PRIDE_LIST_HEADERS, timeout=timeout)
    r.raise_for_status()
    last = _last_monster_list_page(r.text)
    by_id: Dict[int, str] = {}
    for row in parse_mvp_rows_from_monster_search_html(r.text):
        if mvp_catalog_entry_skipped(row):
            continue
        by_id[int(row["id"])] = str(row["name"])
    for p in range(2, last + 1):
        time.sleep(max(0.0, float(delay_s)))
        r = session.get(
            _divine_monster_list_page_url(list_url, p, srv),
            headers=DIVINE_PRIDE_LIST_HEADERS,
            timeout=timeout,
        )
        r.raise_for_status()
        for row in parse_mvp_rows_from_monster_search_html(r.text):
            if mvp_catalog_entry_skipped(row):
                continue
            by_id.setdefault(int(row["id"]), str(row["name"]))
    items = [{"id": i, "name": n} for i, n in by_id.items()]
    items.sort(key=lambda x: (str(x.get("name") or "").casefold(), int(x.get("id", 0))))
    return items


def _mvp_catalog_rows_to_items(rows: Any) -> List[Dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        return []
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            mid = int(row.get("id", 0))
        except (TypeError, ValueError):
            continue
        name = str(row.get("name") or "").strip()
        if mid and name and not mvp_catalog_entry_skipped(row):
            rec: Dict[str, Any] = {"id": mid, "name": name}
            sm = row.get("spawn_maps")
            if isinstance(sm, list) and sm:
                rec["spawn_maps"] = [str(x).strip() for x in sm if str(x).strip()]
            out.append(rec)
    return out


def _load_mvp_catalog_file(fp: str, max_age_seconds: Optional[float]) -> Optional[List[Dict[str, Any]]]:
    if not os.path.isfile(fp):
        return None
    try:
        with open(fp, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        logger.warning("load mvp catalog %s: %s", fp, e)
        return None
    if not isinstance(raw, dict):
        return None
    ts = raw.get("fetched_at")
    if max_age_seconds is not None and ts:
        try:
            fetched = datetime.fromisoformat(str(ts)[:19])
            if (datetime.now() - fetched).total_seconds() > float(max_age_seconds):
                return None
        except ValueError:
            return None
    items = _mvp_catalog_rows_to_items(raw.get("mvp"))
    return items if items else None


def load_mvp_catalog_cache(
    *,
    max_age_seconds: Optional[float] = 7 * 24 * 3600,
    path: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Catálogo em disco: primeiro ``data/mvp_catalog_cache.json`` (sem expiração); depois cache legado no perfil (TTL)."""
    if path is not None:
        return _load_mvp_catalog_file(path, max_age_seconds)

    try:
        os.makedirs(MVP_CATALOG_DATA_DIR, exist_ok=True)
    except OSError:
        pass

    data = _load_mvp_catalog_file(MVP_CATALOG_PORTABLE_FILE, max_age_seconds=None)
    if data:
        return data

    data = _load_mvp_catalog_file(MVP_CATALOG_CACHE_FILE_LEGACY, max_age_seconds)
    if data:
        try:
            save_mvp_catalog_cache(data, name_display_locale="pending")
        except Exception as ex:
            logger.debug("migração catálogo MVP para pasta do programa: %s", ex)
        return data
    return None


def mvp_catalog_names_are_english_marked(path: Optional[str] = None) -> bool:
    """True se ``mvp_catalog_cache.json`` foi gravado após sincronizar nomes via API (inglês)."""
    fp = path or MVP_CATALOG_PORTABLE_FILE
    if not os.path.isfile(fp):
        return False
    try:
        with open(fp, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return False
        return str(raw.get("name_display_locale") or "").lower() == "en"
    except Exception:
        return False


def save_mvp_catalog_cache(
    items: List[Dict[str, Any]],
    *,
    path: Optional[str] = None,
    name_display_locale: Optional[str] = None,
) -> None:
    """Grava o catálogo; por defeito em ``data/mvp_catalog_cache.json`` junto ao programa.

    *name_display_locale*: ``\"en\"`` após nomes vindos da API (inglês); ``\"pending\"`` após
    só HTML; ``None`` mantém o valor já gravado no ficheiro.
    """
    mvp_out: List[Dict[str, Any]] = []
    for x in items:
        if not x.get("id") or not x.get("name"):
            continue
        if mvp_catalog_entry_skipped(x):
            continue
        d: Dict[str, Any] = {"id": int(x["id"]), "name": str(x["name"])}
        sm = x.get("spawn_maps")
        if isinstance(sm, list) and sm:
            d["spawn_maps"] = [str(s).strip() for s in sm if str(s).strip()]
        mvp_out.append(d)

    fp = path or MVP_CATALOG_PORTABLE_FILE
    prev_locale: Optional[str] = None
    if name_display_locale is None and os.path.isfile(fp):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                prev_raw = json.load(f)
            if isinstance(prev_raw, dict) and prev_raw.get("name_display_locale") is not None:
                prev_locale = str(prev_raw.get("name_display_locale") or "").strip() or None
        except Exception:
            pass
    locale_tag = name_display_locale if name_display_locale is not None else prev_locale

    payload: Dict[str, Any] = {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "source": DIVINE_MONSTER_LIST_URL,
        "mvp": mvp_out,
    }
    if locale_tag:
        payload["name_display_locale"] = locale_tag

    def write_to(wfp: str) -> None:
        parent = os.path.dirname(wfp)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(wfp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    if path is not None:
        write_to(path)
        return
    try:
        write_to(MVP_CATALOG_PORTABLE_FILE)
    except OSError as e:
        logger.warning("gravar catálogo MVP local: %s — a usar perfil do utilizador", e)
        write_to(MVP_CATALOG_CACHE_FILE_LEGACY)
