"""
Extrai GIFs MVP do ficheiro HAR ``nn.ai4rei.net.har`` (raiz do projecto),
converte o 1.º frame para PNG em ``data/mvp_sprites_ai4rei/`` e preenche
``data/mvp_sprites/{divine_pride_id}.png`` a partir do catálogo em cache.

Para cruzar com stems ``data/sprite/몬스터/*.spr`` do teu ``data.grf`` e
ganhar mais mapeamentos (ex. ``..._EREMES`` ↔ ``eremes.spr``), corre em seguida::

    python tools/sync_mvp_sprites_grf_ai4rei.py --grf "C:\\Hero Saga v1.3\\data.grf"

Corrida uma vez após colocar/actualizar o HAR:

    python tools/import_mvp_sprites_from_har.py
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import sys
from io import BytesIO
from pathlib import Path
from typing import List, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gdz_monitor.services.mvp_timer import (  # noqa: E402
    MVP_CATALOG_DATA_DIR,
    MVP_CATALOG_PORTABLE_FILE,
    MVP_SPRITES_AI4REI_DIR,
    MVP_SPRITES_DIR,
    load_mvp_catalog_cache,
    mvp_catalog_entry_skipped,
    mvp_display_name_to_ai4rei_sprite_key,
)

_HAR_PATH = _ROOT / "nn.ai4rei.net.har"
_GIF_URL_RE = re.compile(r"/npclist/i/([A-Za-z0-9_]+)\.gif$", re.I)


def _gif_first_frame_to_png(gif_bytes: bytes, out_png: Path) -> None:
    from PIL import Image

    im = Image.open(BytesIO(gif_bytes))
    im.seek(0)
    rgba = im.convert("RGBA")
    out_png.parent.mkdir(parents=True, exist_ok=True)
    rgba.save(out_png, "PNG", optimize=True)


def extract_har_to_ai4rei(har_path: Path) -> int:
    raw = json.loads(har_path.read_text(encoding="utf-8"))
    entries = raw.get("log", {}).get("entries", [])
    n = 0
    seen: set[str] = set()
    out_dir = Path(MVP_SPRITES_AI4REI_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    for ent in entries:
        url = ent.get("request", {}).get("url") or ""
        m = _GIF_URL_RE.search(url)
        if not m:
            continue
        key = m.group(1).upper()
        if key in seen:
            continue
        seen.add(key)
        content = (ent.get("response") or {}).get("content") or {}
        text_b64 = content.get("text") or ""
        if not text_b64:
            continue
        enc = (content.get("encoding") or "").lower()
        if enc == "base64":
            raw_gif = base64.b64decode(text_b64)
        else:
            # alguns HAR guardam dados já decodificados (improvável para GIF)
            raw_gif = text_b64.encode("latin-1")
        if not raw_gif.startswith(b"GIF"):
            continue
        out_png = out_dir / f"{key}.png"
        try:
            _gif_first_frame_to_png(raw_gif, out_png)
            n += 1
            print(f"  OK {key}.png")
        except Exception as ex:
            print(f"  FALHOU {key}: {ex}")
    return n


def write_sprite_id_map(items: list) -> int:
    """Grava ``data/mvp_sprite_id_map.json``: ID Divine Pride → chave PNG ai4rei."""
    by_id: dict[str, str] = {}
    for it in items:
        try:
            mid = int(it.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if not mid:
            continue
        name = str(it.get("name") or "")
        if mvp_catalog_entry_skipped(it):
            continue
        key = mvp_display_name_to_ai4rei_sprite_key(name)
        if not key:
            continue
        src = Path(MVP_SPRITES_AI4REI_DIR) / f"{key}.png"
        if not src.is_file():
            continue
        by_id[str(mid)] = key
    payload = {
        "version": 1,
        "source": "divine_pride_monster_id_to_ai4rei_sprite_key",
        "monster_id_to_sprite_key": by_id,
    }
    path = Path(MVP_CATALOG_DATA_DIR) / "mvp_sprite_id_map.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(by_id)


def bundle_catalog_pngs(items: Optional[List] = None) -> int:
    if items is None:
        items = load_mvp_catalog_cache(max_age_seconds=None) or []
    n = 0
    out_dir = Path(MVP_SPRITES_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    for it in items:
        try:
            mid = int(it.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if not mid:
            continue
        name = str(it.get("name") or "")
        if mvp_catalog_entry_skipped(it):
            continue
        key = mvp_display_name_to_ai4rei_sprite_key(name)
        if not key:
            continue
        src = Path(MVP_SPRITES_AI4REI_DIR) / f"{key}.png"
        if not src.is_file():
            continue
        dst = out_dir / f"{mid}.png"
        try:
            shutil.copy2(src, dst)
            n += 1
        except OSError as ex:
            print(f"  copy {mid} <- {key}: {ex}")
    return n


def main() -> None:
    if not _HAR_PATH.is_file():
        print(f"HAR não encontrado: {_HAR_PATH}")
        sys.exit(1)
    print(f"Ler HAR: {_HAR_PATH}")
    n = extract_har_to_ai4rei(_HAR_PATH)
    print(f"=> {n} PNG em {MVP_SPRITES_AI4REI_DIR}")

    if not Path(MVP_CATALOG_PORTABLE_FILE).is_file():
        print(f"Aviso: sem catálogo {MVP_CATALOG_PORTABLE_FILE} — só ai4rei.")
        return
    items = load_mvp_catalog_cache(max_age_seconds=None) or []
    nb = bundle_catalog_pngs(items)
    nm = write_sprite_id_map(items)
    print(f"=> {nb} PNG por ID em {MVP_SPRITES_DIR}")
    print(f"=> {nm} IDs em {Path(MVP_CATALOG_DATA_DIR) / 'mvp_sprite_id_map.json'}")


if __name__ == "__main__":
    main()
