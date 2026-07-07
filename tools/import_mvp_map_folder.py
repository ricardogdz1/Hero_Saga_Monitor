"""
Copia imagens de mapa (minimap) para ``data/mvp_maps/{nome_mapa}.png``.

O nome do ficheiro (sem extensão) deve coincidir com o mapa no catálogo MVP
(ex. ``moc_pryd06.png``, ``jor_sklf1.png``). Usado pelo diálogo «Editar MVP».

Uso::

    python tools/import_mvp_map_folder.py --dir "C:\\Users\\...\\Desktop\\Novas sprites"
    python tools/import_mvp_map_folder.py --dir "..." --dry-run
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gdz_monitor.services.mvp_timer import MVP_MAPS_DIR, _safe_map_name, load_mvp_catalog_cache  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Importar minimapas MVP → data/mvp_maps/")
    ap.add_argument("--dir", type=Path, required=True, help="Pasta com imagens (.png, .jpg, .bmp)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    src: Path = args.dir
    if not src.is_dir():
        print(f"Pasta inexistente: {src}", file=sys.stderr)
        sys.exit(1)

    catalog_maps: set[str] = set()
    for it in load_mvp_catalog_cache(max_age_seconds=None) or []:
        if not isinstance(it, dict):
            continue
        for sm in it.get("spawn_maps") or []:
            s = _safe_map_name(str(sm))
            if s:
                catalog_maps.add(s)

    out_dir = Path(MVP_MAPS_DIR)
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    exts = {".png", ".jpg", ".jpeg", ".bmp"}
    n_ok = n_skip = 0
    in_catalog = 0
    for p in sorted(src.iterdir()):
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        stem = _safe_map_name(p.stem)
        if not stem:
            n_skip += 1
            continue
        dest = out_dir / f"{stem}.png"
        tag = "catálogo" if stem in catalog_maps else "extra"
        if stem in catalog_maps:
            in_catalog += 1
        if args.dry_run:
            print(f"  >> {p.name} -> {dest.name}  ({tag})")
        else:
            if p.suffix.lower() == ".png":
                shutil.copy2(p, dest)
            else:
                try:
                    from PIL import Image

                    im = Image.open(p)
                    im.save(dest, format="PNG")
                except Exception as ex:
                    print(f"  !  {p.name}: {ex}")
                    n_skip += 1
                    continue
            print(f"  OK {p.name} -> {dest.name}  ({tag})")
        n_ok += 1

    print(
        f"\nOrigem: {n_ok} ficheiros | ignorados: {n_skip} | "
        f"com MVP no catálogo: {in_catalog}"
    )
    if args.dry_run:
        print("(dry-run — nada gravado)")


if __name__ == "__main__":
    main()
