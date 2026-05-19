"""
Adiciona MVPs ao catálogo local e copia sprites a partir de uma pasta.

Cada ficheiro .png deve conter o id Divine Pride no nome (ex. «… id 22422.png»
ou «22422.png»). Opcionalmente obtém nome e spawn_maps via API.

Uso::

    python tools/add_mvps_from_folder.py --dir "C:\\Users\\...\\Desktop\\Novos mvps"
    python tools/add_mvps_from_folder.py --dir "..." --dry-run
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app_settings import load_settings  # noqa: E402
from divine_pride_api import fetch_monster  # noqa: E402
from mvp_timer import (  # noqa: E402
    MVP_SPRITES_DIR,
    load_mvp_catalog_cache,
    monster_api_display_name,
    mvp_catalog_entry_skipped,
    mvp_name_has_asian_script,
    save_mvp_catalog_cache,
    spawn_maps_from_monster,
    summarize_monster_for_timer,
)

_ID_RE = re.compile(r"(?:\bid\s*)?(\d{4,6})\b", re.I)


def _parse_id_from_stem(stem: str) -> Optional[int]:
    m = _ID_RE.search(stem)
    if m:
        try:
            return int(m.group(1))
        except (TypeError, ValueError):
            pass
    if stem.isdigit():
        return int(stem)
    return None


def _name_from_filename_stem(stem: str) -> str:
    """Nome legível a partir do ficheiro (remove sufixo «id 12345»)."""
    base = re.sub(r"\s+id\s+\d+\s*$", "", stem, flags=re.I).strip()
    if not base:
        return ""
    parts = [p for p in re.split(r"[\s_]+", base.replace("_", " ")) if p]
    return " ".join(p.capitalize() for p in parts) if parts else base


def _display_name_from_api(mobj: dict, mid: int, stem: str) -> str:
    fn_name = _name_from_filename_stem(stem)
    raw = monster_api_display_name(mobj)
    if raw and not mvp_name_has_asian_script(raw):
        return raw.strip()
    db = str(mobj.get("dbname") or "").strip()
    # dbname interno (ex. EP21_B_YORTUS_A_H) — preferir nome do ficheiro
    if db and re.match(r"^EP\d+_", db, re.I):
        if fn_name:
            return fn_name
    if fn_name:
        return fn_name
    if db:
        parts = [p for p in re.split(r"_+", db.lower()) if p]
        if parts:
            return " ".join(p.capitalize() for p in parts)
    return raw.strip() or f"MVP {mid}"


def _collect_pngs(src: Path) -> List[Tuple[Path, int]]:
    out: List[Tuple[Path, int]] = []
    seen_ids: set = set()
    for p in sorted(src.iterdir()):
        if not p.is_file() or p.suffix.lower() != ".png":
            continue
        mid = _parse_id_from_stem(p.stem)
        if not mid or mid in seen_ids:
            if not mid:
                print(f"  ?  SKIP {p.name} — id não encontrado no nome")
            continue
        seen_ids.add(mid)
        out.append((p, mid))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Adicionar MVPs (catálogo + sprites) a partir de pasta PNG.")
    ap.add_argument("--dir", type=Path, required=True, help="Pasta com .png (nome contém o id)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    src: Path = args.dir
    if not src.is_dir():
        print(f"Pasta inexistente: {src}", file=sys.stderr)
        sys.exit(1)

    pairs = _collect_pngs(src)
    if not pairs:
        print(f"Nenhum .png com id válido em {src}")
        sys.exit(0)

    cfg = load_settings()
    key = (cfg.get("divine_pride_api_key") or "").strip()
    srv = (cfg.get("divine_pride_server") or "").strip() or None

    items = list(load_mvp_catalog_cache(max_age_seconds=None) or [])
    by_id: Dict[int, Dict[str, Any]] = {}
    for it in items:
        if isinstance(it, dict):
            try:
                by_id[int(it.get("id") or 0)] = it
            except (TypeError, ValueError):
                pass

    out_dir = Path(MVP_SPRITES_DIR)
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    for png_path, mid in pairs:
        mobj: Optional[dict] = None
        if key:
            try:
                mobj = fetch_monster(mid, api_key=key, server=srv)
            except Exception as ex:
                print(f"  !  API {mid}: {ex}")
        if mobj:
            name = _display_name_from_api(mobj, mid, png_path.stem)
            maps = spawn_maps_from_monster(mobj)
            summ = summarize_monster_for_timer(mobj)
            if not summ.get("is_mvp"):
                print(f"  !  {mid} não marcado como MVP na API — a adicionar na mesma")
        else:
            name = _display_name_from_api({}, mid, png_path.stem)
            maps = []
            if not key:
                print(f"  !  {mid}: sem chave API — nome só do ficheiro")

        rec: Dict[str, Any] = {"id": mid, "name": name}
        if maps:
            rec["spawn_maps"] = maps
        if mvp_catalog_entry_skipped(rec):
            print(f"  ?  SKIP catálogo {mid} «{name}» — regras de exclusão (id/nome)")
            continue

        dest = out_dir / f"{mid}.png"
        if args.dry_run:
            action = "atualizar" if mid in by_id else "adicionar"
            print(f"  >> {png_path.name} -> id={mid} «{name}» [{action}] -> {dest.name}")
        else:
            shutil.copy2(png_path, dest)
            by_id[mid] = {**by_id.get(mid, {}), **rec}
            print(f"  OK {png_path.name} -> {dest.name}  «{name}»")

    if args.dry_run:
        print("\n(dry-run — nada gravado)")
        return

    merged = list(by_id.values())
    merged.sort(key=lambda x: (str(x.get("name") or "").casefold(), int(x.get("id") or 0)))
    save_mvp_catalog_cache(merged)
    print(f"\nCatálogo gravado: {len(merged)} MVPs em data/mvp_catalog_cache.json")


if __name__ == "__main__":
    main()
