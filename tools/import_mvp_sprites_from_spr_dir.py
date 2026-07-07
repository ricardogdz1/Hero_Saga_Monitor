"""
Importa ícones MVP a partir de uma pasta com ficheiros .spr do cliente RO.

O ficheiro .act não contém imagens — só descreve animação. Os pixels estão no .spr.

Associação MVP ↔ .spr:
  · mesma lógica ai4rei por nome; variantes «Phantom X» tratam como «X``;
  · colisões (vários .spr) — escolhe-se o ficheiro «mais base» (menos md_/i_/broken);
  · ``data/mvp_sprite_ro_stem_overrides.json`` para casos especiais (id → stem).

Exemplo::

    python tools/import_mvp_sprites_from_spr_dir.py --dir "C:\\Users\\Ricardo\\Desktop\\Gifs"
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from difflib import get_close_matches
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gdz_monitor.services.mvp_timer import (  # noqa: E402
    MVP_CATALOG_DATA_DIR,
    MVP_CATALOG_PORTABLE_FILE,
    MVP_SPRITES_DIR,
    _normalize_mvp_name_for_sprite,
    load_mvp_catalog_cache,
    mvp_catalog_entry_skipped,
    mvp_display_name_to_ai4rei_sprite_key,
    mvp_sprite_norm_candidates,
)

from ro_spr import SprDecodeError, spr_file_to_png_bytes  # noqa: E402

RO_STEM_OVERRIDES_FILE = Path(MVP_CATALOG_DATA_DIR) / "mvp_sprite_ro_stem_overrides.json"


def load_ro_stem_overrides() -> Tuple[Dict[int, str], Dict[str, str]]:
    """(monster_id -> stem, norm_upper -> stem) sem extensão .spr"""
    mid: Dict[int, str] = {}
    norm: Dict[str, str] = {}
    if not RO_STEM_OVERRIDES_FILE.is_file():
        return mid, norm
    try:
        raw = json.loads(RO_STEM_OVERRIDES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return mid, norm
    if not isinstance(raw, dict):
        return mid, norm
    m = raw.get("monster_id_to_stem")
    if isinstance(m, dict):
        for k, v in m.items():
            if isinstance(k, str) and k.isdigit() and isinstance(v, str) and v.strip():
                mid[int(k)] = v.strip()
    n = raw.get("norm_to_stem")
    if isinstance(n, dict):
        for k, v in n.items():
            if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
                norm[k.strip().upper()] = v.strip()
    return mid, norm


def _pick_best_spr(paths: List[Path]) -> Path:
    """Prefere stems «limpos» (evita i_*, md_broken_*, fake_*, etc.)."""

    def score(p: Path) -> Tuple[int, int]:
        s = p.stem.lower()
        pen = 0
        if "broken" in s:
            pen += 50
        if s.startswith("fake_"):
            pen += 40
        if s.startswith("i_") and not s.startswith("i_u_"):
            pen += 30
        if "_bullet" in s or s.endswith("_leg"):
            pen += 20
        if "_egg" in s:
            pen += 18
        if s.startswith("md_"):
            pen += 10
        if s.startswith("ill_"):
            pen += 6
        if len(s) >= 3 and s[:3] == "ep" and "_mm_" in s:
            pen += 5
        return (pen, len(s))

    return min(paths, key=score)


def _pick_spr_by_norm_overlap(normalized_mvp: str, paths: List[Path]) -> Path:
    """Com vários .spr (ex.: sufixo LADY), escolhe o stem com maior prefixo comum ao norm do MVP."""
    if len(paths) <= 1:
        return _pick_best_spr(paths)
    nm = normalized_mvp
    best_p: Optional[Path] = None
    best_i = -1
    for p in paths:
        sn = _normalize_mvp_name_for_sprite(p.stem)
        overlap = 0
        for a, b in zip(nm, sn):
            if a != b:
                break
            overlap += 1
        if overlap > best_i:
            best_i = overlap
            best_p = p
    if best_p is not None and best_i > 0:
        return best_p
    return _pick_best_spr(paths)


def _build_spr_buckets(spr_dir: Path) -> Dict[str, List[Path]]:
    buckets: Dict[str, List[Path]] = defaultdict(list)
    for f in sorted(spr_dir.glob("*.spr")):
        if not f.is_file():
            continue
        ns = _normalize_mvp_name_for_sprite(f.stem)
        if ns:
            buckets[ns].append(f)
    return dict(buckets)


def _unique_stem_map(buckets: Dict[str, List[Path]]) -> Dict[str, Path]:
    return {k: _pick_best_spr(v) for k, v in buckets.items()}


def _paths_for_tail(normalized_mvp_name: str, buckets: Dict[str, List[Path]]) -> List[Path]:
    if "_" not in normalized_mvp_name:
        return []
    tail = normalized_mvp_name.rsplit("_", 1)[-1]
    return _paths_for_tail_token(tail, buckets)


def _paths_for_tail_token(tail: str, buckets: Dict[str, List[Path]]) -> List[Path]:
    if len(tail) < 4:
        return []
    found: List[Path] = []
    for sn, paths in buckets.items():
        st = sn.rsplit("_", 1)[-1] if "_" in sn else sn
        if st == tail:
            found.extend(paths)
    out: List[Path] = []
    seen: set[str] = set()
    for p in found:
        k = str(p.resolve())
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def _fuzzy_path(norm: str, uniq: Dict[str, Path], *, cutoff: float) -> Optional[Path]:
    if len(norm) < 5:
        return None
    pool = list(uniq.keys())
    hits = get_close_matches(norm, pool, n=1, cutoff=cutoff)
    if not hits:
        return None
    return uniq[hits[0]]


def _resolve_spr_path(
    display_name: str,
    buckets: Dict[str, List[Path]],
    uniq: Dict[str, Path],
    *,
    tail_match: bool,
    fuzzy: bool,
    fuzzy_cutoff: float,
) -> Optional[Path]:
    k = mvp_display_name_to_ai4rei_sprite_key(display_name)
    if k:
        ns_key = _normalize_mvp_name_for_sprite(k)
        if ns_key in uniq:
            return uniq[ns_key]
        low = k.lower().replace("_", "")
        for f in uniq.values():
            if f.stem.lower().replace("_", "") == low:
                return f

    for cand in mvp_sprite_norm_candidates(display_name):
        if cand in uniq:
            return uniq[cand]
        if tail_match and cand:
            tails = _paths_for_tail(cand, buckets)
            if tails:
                return _pick_spr_by_norm_overlap(cand, tails)
            for seg in cand.split("_"):
                if len(seg) >= 4:
                    sub = _paths_for_tail_token(seg, buckets)
                    if sub:
                        return _pick_spr_by_norm_overlap(cand, sub)

    if fuzzy:
        for cand in mvp_sprite_norm_candidates(display_name):
            if len(cand) >= 5:
                hit = _fuzzy_path(cand, uniq, cutoff=fuzzy_cutoff)
                if hit:
                    return hit
    return None


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="Importar MVP PNG a partir de .spr locais.")
    ap.add_argument(
        "--dir",
        type=Path,
        required=True,
        help="Pasta com .spr (ex. Gifs extraídos do cliente).",
    )
    ap.add_argument("--frame", type=int, default=0, help="Índice do frame no .spr (defeito: 0).")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-existing", action="store_true", help="Não substituir PNG já existente.")
    ap.add_argument("--no-tail-match", action="store_true")
    ap.add_argument("--fuzzy", action="store_true")
    ap.add_argument("--fuzzy-cutoff", type=float, default=0.9)
    args = ap.parse_args()

    if not args.dir.is_dir():
        print(f"Pasta inválida: {args.dir}")
        sys.exit(1)

    if not Path(MVP_CATALOG_PORTABLE_FILE).is_file():
        print(f"Sem catálogo: {MVP_CATALOG_PORTABLE_FILE}")
        sys.exit(1)

    mid_ov, norm_ov = load_ro_stem_overrides()
    buckets = _build_spr_buckets(args.dir)
    uniq = _unique_stem_map(buckets)
    n_files = sum(len(v) for v in buckets.values())
    print(f".spr: {n_files} ficheiros, {len(uniq)} stems únicos após desambiguação")
    if mid_ov or norm_ov:
        print(f"Overrides {RO_STEM_OVERRIDES_FILE.name}: {len(mid_ov)} id, {len(norm_ov)} norm")

    items = load_mvp_catalog_cache(max_age_seconds=None) or []
    out_dir = Path(MVP_SPRITES_DIR)
    ok = skip = fail = 0
    tail_on = not args.no_tail_match

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

        dst = out_dir / f"{mid}.png"
        if args.skip_existing and dst.is_file():
            skip += 1
            continue

        spath: Optional[Path] = None
        if mid in mid_ov:
            c = args.dir / f"{mid_ov[mid]}.spr"
            if c.is_file():
                spath = c
        if spath is None and norm_ov:
            for c_norm in mvp_sprite_norm_candidates(name):
                stem = norm_ov.get(c_norm)
                if stem:
                    c = args.dir / f"{stem}.spr"
                    if c.is_file():
                        spath = c
                        break

        if spath is None:
            spath = _resolve_spr_path(
                name,
                buckets,
                uniq,
                tail_match=tail_on,
                fuzzy=args.fuzzy,
                fuzzy_cutoff=args.fuzzy_cutoff,
            )
        if not spath:
            continue

        try:
            png = spr_file_to_png_bytes(str(spath), frame_index=args.frame)
        except (SprDecodeError, OSError) as ex:
            print(f"  [{mid}] {spath.name}: {ex}")
            fail += 1
            continue

        if args.dry_run:
            print(f"  [{mid}] {name[:46]!s} <- {spath.name}")
            ok += 1
            continue

        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(png)
            print(f"  OK [{mid}] {spath.name}")
            ok += 1
        except OSError as ex:
            print(f"  [{mid}] gravar: {ex}")
            fail += 1

    print(f"Feito: {ok} gerados, {skip} ignorados (já existiam), {fail} falhas.")


if __name__ == "__main__":
    main()
