"""
Copia PNGs de uma pasta (ex. «Sprites restantes MVP») para ``data/mvp_sprites/{id}.png``.

Associa cada ficheiro ao MVP pelo nome do ficheiro (sem extensão), alinhado aos nomes
do catálogo ``data/mvp_catalog_cache.json``. Underscores contam como espaço;
comparação sem acentos / case (mesma lógica que a busca MVP na UI).

Se dois MVPs tiverem o mesmo nome, o mesmo PNG é gravado para todos os ids.

Uso (mantenedor / release)::

    python tools/import_mvp_png_folder.py --dir "C:\\Users\\...\\Sprites restantes MVP"

``--dry-run`` só lista o que faria. Depois de importar, os PNGs ficam no repositório;
utilizadores finais não precisam da pasta original — basta instalar o programa / clonar o projecto.

Para forçar um par ficheiro → id (nome ambíguo), edite opcionalmente
``data/mvp_sprite_png_import_overrides.json``::

    { "filename_stem": 12345, "Other_Name": 999 }
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from difflib import get_close_matches
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gdz_monitor.services.mvp_timer import (  # noqa: E402
    MVP_CATALOG_DATA_DIR,
    MVP_SPRITES_DIR,
    load_mvp_catalog_cache,
    mvp_catalog_entry_skipped,
    normalize_text_for_search,
)

OVERRIDES_FILE = Path(MVP_CATALOG_DATA_DIR) / "mvp_sprite_png_import_overrides.json"


def _load_overrides() -> Dict[str, int]:
    if not OVERRIDES_FILE.is_file():
        return {}
    try:
        raw = json.loads(OVERRIDES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, int] = {}
    for k, v in raw.items():
        if k in ("version", "comment"):
            continue
        try:
            ik = int(v)
        except (TypeError, ValueError):
            continue
        if isinstance(k, str) and k.strip() and ik > 0:
            out[normalize_text_for_search(k.replace("_", " ").strip())] = ik
    return out


def _catalog_norm_to_ids() -> Tuple[Dict[str, List[int]], Dict[int, str]]:
    items = load_mvp_catalog_cache(max_age_seconds=None) or []
    norm_to_ids: Dict[str, List[int]] = {}
    id_to_name: Dict[int, str] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()
        if not name or mvp_catalog_entry_skipped(it):
            continue
        try:
            mid = int(it.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if not mid:
            continue
        nn = normalize_text_for_search(name)
        norm_to_ids.setdefault(nn, []).append(mid)
        id_to_name[mid] = name
    return norm_to_ids, id_to_name


def _stem_norm(path: Path) -> str:
    return normalize_text_for_search(path.stem.replace("_", " ").strip())


def _resolve_ids(
    stem_norm: str,
    norm_to_ids: Dict[str, List[int]],
) -> Tuple[Optional[List[int]], str]:
    if not stem_norm:
        return None, "nome vazio"
    if stem_norm in norm_to_ids:
        return norm_to_ids[stem_norm], "exact"
    ovr = _load_overrides()
    if stem_norm in ovr:
        return [ovr[stem_norm]], "override"
    keys = list(norm_to_ids.keys())
    hits = get_close_matches(stem_norm, keys, n=1, cutoff=0.82)
    if hits:
        return norm_to_ids[hits[0]], f"fuzzy~{hits[0]!r}"
    return None, "sem match"


def main() -> None:
    ap = argparse.ArgumentParser(description="Importar PNGs MVP → data/mvp_sprites/{id}.png")
    ap.add_argument(
        "--dir",
        type=Path,
        required=True,
        help="Pasta com ficheiros .png",
    )
    ap.add_argument("--dry-run", action="store_true", help="Não grava; só mostra o plano")
    args = ap.parse_args()
    src: Path = args.dir
    if not src.is_dir():
        print(f"Pasta inexistente: {src}", file=sys.stderr)
        sys.exit(1)

    norm_to_ids, _ = _catalog_norm_to_ids()
    out_dir = Path(MVP_SPRITES_DIR)
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    seen: set = set()
    pngs: List[Path] = []
    for p in sorted(src.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() != ".png":
            continue
        key = str(p.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        pngs.append(p)
    if not pngs:
        print(f"Nenhum .png em {src}")
        sys.exit(0)

    n_ok = 0
    n_skip = 0
    for p in pngs:
        sn = _stem_norm(p)
        ids, how = _resolve_ids(sn, norm_to_ids)
        if not ids:
            print(f"  ?  SKIP {p.name} — {how}")
            n_skip += 1
            continue
        for mid in sorted(set(ids)):
            dest = out_dir / f"{mid}.png"
            if args.dry_run:
                print(f"  >> {p.name} -> {dest.name}  ({how}, id={mid})")
            else:
                shutil.copy2(p, dest)
                print(f"  OK {p.name} -> {dest.name}  ({how})")
            n_ok += 1

    print(f"\nOrigem: {len(pngs)} ficheiros | destinos gravados: {n_ok} | ignorados: {n_skip}")
    if args.dry_run:
        print("(dry-run — nada gravado)")


if __name__ == "__main__":
    main()
