"""
Cruza stems de sprites de monstro no GRF (ex.: data/sprite/몬스터/*.spr)
com PNGs ai4rei extraídos dos GIFs do HAR (data/mvp_sprites_ai4rei/*.png).

Actualiza data/mvp_sprite_id_map.json e copia data/mvp_sprites/{id}.png para MVPs
do catálogo que ainda não tinham sprite, quando:
  · o nome Divine Pride já mapeia para uma chave ai4rei (comportamento existente); ou
  · a normalização do nome coincide com a de um stem do GRF que tem PNG; ou
  · (opcional) o último segmento após _ coincide (ex.: ..._EREMES ↔ eremes.spr); ou
  · (opcional --fuzzy) difflib contra stems do GRF.

Requisitos: ter corrido antes ``python tools/import_mvp_sprites_from_har.py``
(ou ter PNGs em mvp_sprites_ai4rei). GRF: só se lê o índice (sem decrypt).

Exemplo:
  python tools/sync_mvp_sprites_grf_ai4rei.py --grf "C:\\Hero Saga v1.3\\data.grf"
  python tools/sync_mvp_sprites_grf_ai4rei.py --grf ... --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from difflib import get_close_matches
from pathlib import Path
from typing import Dict, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from grf_catalog import read_grf_entries  # noqa: E402

from mvp_timer import (  # noqa: E402
    MVP_CATALOG_PORTABLE_FILE,
    MVP_SPRITES_AI4REI_DIR,
    MVP_SPRITES_DIR,
    MVP_SPRITE_ID_MAP_FILE,
    _normalize_mvp_name_for_sprite,
    invalidate_mvp_sprite_id_map_cache,
    load_mvp_catalog_cache,
    mvp_catalog_entry_skipped,
    mvp_display_name_to_ai4rei_sprite_key,
    mvp_sprite_norm_candidates,
)

_MONSTER_SEG = "/sprite/몬스터/"


def _collect_grf_monster_spr_stems(grf_path: Path) -> set[str]:
    _, _, _, entries = read_grf_entries(grf_path)
    stems: set[str] = set()
    for e in entries:
        if not (e.flags & 0x01):
            continue
        if not e.real_len:
            continue
        p = e.path.replace("\\", "/")
        if _MONSTER_SEG not in p:
            continue
        if not p.lower().endswith(".spr"):
            continue
        base = os.path.basename(p)
        stem, ext = os.path.splitext(base)
        if ext.lower() != ".spr":
            continue
        stems.add(stem)
    return stems


def _stem_norm_to_ai4rei_key(stems: set[str]) -> Dict[str, str]:
    """
    Por cada stem do GRF, devolve normalize(stem) -> chave ai4rei
    quando mvp_display_name_to_ai4rei_sprite_key conseguir resolver.
    Se dois stems colidirem no mesmo normalize com chaves diferentes, descarta-se.
    """
    out: Dict[str, str] = {}
    bad: set[str] = set()
    for stem in stems:
        label = stem.replace("_", " ")
        key = mvp_display_name_to_ai4rei_sprite_key(label)
        if not key:
            key = mvp_display_name_to_ai4rei_sprite_key(stem)
        if not key:
            continue
        ns = _normalize_mvp_name_for_sprite(stem)
        if not ns:
            continue
        if ns in bad:
            continue
        prev = out.get(ns)
        if prev is not None and prev != key:
            bad.add(ns)
            del out[ns]
            continue
        out[ns] = key
    return out


def _keys_for_tail_match(
    normalized_mvp_name: str, stem_norm_to_key: Dict[str, str]
) -> list[str]:
    if "_" not in normalized_mvp_name:
        return []
    tail = normalized_mvp_name.rsplit("_", 1)[-1]
    if len(tail) < 5:
        return []
    found: list[str] = []
    for sn, k in stem_norm_to_key.items():
        if "_" in sn:
            st = sn.rsplit("_", 1)[-1]
        else:
            st = sn
        if st == tail:
            found.append(k)
    out: list[str] = []
    seen: set[str] = set()
    for k in found:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _fuzzy_key_for_name(
    normalized_mvp_name: str,
    stem_norm_to_key: Dict[str, str],
    *,
    cutoff: float,
) -> Optional[str]:
    if len(normalized_mvp_name) < 5:
        return None
    pool = list(stem_norm_to_key.keys())
    hits = get_close_matches(normalized_mvp_name, pool, n=1, cutoff=cutoff)
    if not hits:
        return None
    return stem_norm_to_key[hits[0]]


def _resolve_ai4rei_key(
    display_name: str,
    stem_norm_to_key: Dict[str, str],
    *,
    tail_match: bool,
    fuzzy: bool,
    fuzzy_cutoff: float,
) -> Optional[str]:
    k = mvp_display_name_to_ai4rei_sprite_key(display_name)
    if k:
        return k

    for ns in mvp_sprite_norm_candidates(display_name):
        if not ns:
            continue
        k = stem_norm_to_key.get(ns)
        if k:
            return k
        if tail_match:
            cand = _keys_for_tail_match(ns, stem_norm_to_key)
            if len(cand) == 1:
                return cand[0]
    if fuzzy:
        for ns in mvp_sprite_norm_candidates(display_name):
            if len(ns) >= 5:
                fk = _fuzzy_key_for_name(ns, stem_norm_to_key, cutoff=fuzzy_cutoff)
                if fk:
                    return fk
    return None


def _load_base_sprite_id_map() -> Dict[int, str]:
    """Só mvp_sprite_id_map.json (sem overrides)."""
    path = Path(MVP_SPRITE_ID_MAP_FILE)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    inner = raw.get("monster_id_to_sprite_key")
    if not isinstance(inner, dict):
        inner = raw
    meta = {"version", "source", "monster_id_to_sprite_key"}
    out: Dict[int, str] = {}
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
        out[ik] = v.strip().upper()
    return out


def _ai4rei_png_keys() -> frozenset[str]:
    d = Path(MVP_SPRITES_AI4REI_DIR)
    if not d.is_dir():
        return frozenset()
    s: set[str] = set()
    for f in d.iterdir():
        if f.suffix.lower() == ".png":
            s.add(f.stem.upper())
    return frozenset(s)


def _png_path_for_key(key_upper: str) -> Path:
    return Path(MVP_SPRITES_AI4REI_DIR) / f"{key_upper}.png"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="Sincronizar sprites MVP via GRF × ai4rei.")
    ap.add_argument(
        "--grf",
        type=Path,
        default=Path(r"C:\Hero Saga v1.3\data.grf"),
        help="Caminho para data.grf (só índice).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostrar alterações sem gravar ficheiros.",
    )
    ap.add_argument(
        "--no-tail-match",
        action="store_true",
        help="Desactivar correspondência pelo último segmento (_EREMES ↔ eremes).",
    )
    ap.add_argument(
        "--fuzzy",
        action="store_true",
        help="Usar difflib se exact e tail falharem (pode errar; rever saída).",
    )
    ap.add_argument(
        "--fuzzy-cutoff",
        type=float,
        default=0.88,
        help="Cutoff difflib (0–1).",
    )
    args = ap.parse_args()

    png_keys = _ai4rei_png_keys()
    if not png_keys:
        print(f"Sem PNGs em {MVP_SPRITES_AI4REI_DIR}. Corra import_mvp_sprites_from_har.py primeiro.")
        sys.exit(1)

    if not args.grf.is_file():
        print(f"GRF não encontrado: {args.grf}")
        sys.exit(1)

    stems = _collect_grf_monster_spr_stems(args.grf)
    stem_norm_to_key = _stem_norm_to_ai4rei_key(stems)
    print(f"GRF monster .spr: {len(stems)} stems, {len(stem_norm_to_key)} ligam a chave ai4rei")

    if not Path(MVP_CATALOG_PORTABLE_FILE).is_file():
        print(f"Sem catálogo: {MVP_CATALOG_PORTABLE_FILE}")
        sys.exit(1)

    items = load_mvp_catalog_cache(max_age_seconds=None) or []
    prev_map = _load_base_sprite_id_map()

    computed: Dict[int, str] = {}
    tail = not args.no_tail_match
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
        key = _resolve_ai4rei_key(
            name,
            stem_norm_to_key,
            tail_match=tail,
            fuzzy=args.fuzzy,
            fuzzy_cutoff=args.fuzzy_cutoff,
        )
        if not key:
            continue
        ku = key.upper()
        if ku not in png_keys:
            continue
        computed[mid] = ku

    merged: Dict[int, str] = {}
    for k, v in prev_map.items():
        merged[int(k)] = str(v).upper()
    n_new = 0
    n_chg = 0
    for mid, ku in computed.items():
        if mid not in merged:
            merged[mid] = ku
            n_new += 1
        elif merged[mid] != ku:
            merged[mid] = ku
            n_chg += 1

    out_path = Path(MVP_SPRITE_ID_MAP_FILE)
    payload = {
        "version": 1,
        "source": "divine_pride_monster_id_to_ai4rei_sprite_key+grf_stems",
        "monster_id_to_sprite_key": {str(k): v for k, v in sorted(merged.items())},
    }

    bundle_dir = Path(MVP_SPRITES_DIR)
    copies = 0
    for mid, ku in merged.items():
        src = _png_path_for_key(ku)
        if not src.is_file():
            continue
        dst = bundle_dir / f"{mid}.png"
        if args.dry_run:
            copies += 1
            continue
        try:
            bundle_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copies += 1
        except OSError as ex:
            print(f"  copy falhou {mid}: {ex}")

    if not args.dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            invalidate_mvp_sprite_id_map_cache()
        except Exception:
            pass

    print(
        f"Mapeamento: {len(computed)} MVPs com PNG ai4rei resolvido; "
        f"+{n_new} ids novos no mapa, {n_chg} ids alterados (vs cache anterior)."
    )
    print(f"Escrever {out_path}: {'sim' if not args.dry_run else 'dry-run'}")
    print(f"Bundle PNG em {bundle_dir}: {copies} ficheiros ({'previstos' if args.dry_run else 'copiados'})")


if __name__ == "__main__":
    main()
