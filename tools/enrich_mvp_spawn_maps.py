"""
Relatório e enriquecimento de ``spawn_maps`` no catálogo MVP via API Divine Pride.

Lê/grava ``data/mvp_catalog_cache.json``. Chave API: variável de ambiente
DIVINE_PRIDE_API_KEY ou ``divine_pride_api_key`` em
``%USERPROFILE%\\herosaga_monitor_settings.json`` (Configurações da app).

Para actualizar nomes para inglês (campo ``name`` da API, ``Accept-Language: en``)::

    python tools/enrich_mvp_spawn_maps.py --enrich --sync-names

Para actualizar também entradas que já têm ``spawn_maps``, use ``--refresh-all``.

Exemplos::

    python tools/enrich_mvp_spawn_maps.py --report
    python tools/enrich_mvp_spawn_maps.py --enrich
    python tools/enrich_mvp_spawn_maps.py --enrich --sync-names --delay 0.15
    python tools/enrich_mvp_spawn_maps.py --enrich --refresh-all --delay 0.15
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gdz_monitor.external.divine_pride_api import fetch_monster, resolve_api_key  # noqa: E402
from gdz_monitor.services.mvp_timer import (  # noqa: E402
    MVP_CATALOG_PORTABLE_FILE,
    load_mvp_catalog_cache,
    monster_api_display_name,
    mvp_catalog_entry_skipped,
    save_mvp_catalog_cache,
    spawn_maps_from_monster,
)


def _settings_api_key() -> str:
    try:
        from gdz_monitor.core.settings import load_settings

        return str(load_settings().get("divine_pride_api_key") or "").strip()
    except Exception:
        return ""


def _settings_api_server() -> Optional[str]:
    try:
        from gdz_monitor.core.settings import load_settings

        s = str(load_settings().get("divine_pride_server") or "").strip()
        return s or None
    except Exception:
        return None


def _catalog_raw_mvp_list() -> List[Dict[str, Any]]:
    path = Path(MVP_CATALOG_PORTABLE_FILE)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    m = raw.get("mvp")
    return list(m) if isinstance(m, list) else []


def report() -> Tuple[
    int,
    int,
    int,
    List[Tuple[int, str]],
    List[Tuple[int, str, List[str]]],
]:
    """Devolve total não-instância, contagens, sem mapas, e lista dos com mapas (id, nome, mapas)."""
    items = _catalog_raw_mvp_list()
    non: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if mvp_catalog_entry_skipped(it):
            continue
        non.append(it)
    with_m = 0
    without: List[Tuple[int, str]] = []
    with_maps: List[Tuple[int, str, List[str]]] = []
    for it in non:
        sm = it.get("spawn_maps")
        try:
            mid = int(it.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if not mid:
            continue
        if isinstance(sm, list) and any(str(x).strip() for x in sm):
            with_m += 1
            maps_clean = [str(x).strip() for x in sm if str(x).strip()]
            with_maps.append((mid, str(it.get("name") or ""), maps_clean))
        else:
            without.append((mid, str(it.get("name") or "")))
    with_maps.sort(key=lambda t: t[0])
    return len(non), with_m, len(non) - with_m, without, with_maps


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="Catálogo MVP: mapas de spawn (Divine Pride API).")
    ap.add_argument(
        "--report",
        action="store_true",
        help="Estatísticas e listas: MVPs com spawn_maps e sem (amostras).",
    )
    ap.add_argument("--enrich", action="store_true", help="Pedir Monster/:id à API e preencher spawn_maps.")
    ap.add_argument(
        "--sync-names",
        action="store_true",
        help="Com --enrich: actualiza ``name`` de todos os MVPs a partir da API (inglês).",
    )
    ap.add_argument("--delay", type=float, default=0.12, help="Segundos entre pedidos (rate limit).")
    ap.add_argument("--limit", type=int, default=0, help="Máximo de MVPs a enriquecer (0 = sem limite).")
    ap.add_argument("--sample", type=int, default=40, help="Com --report: quantos exemplos sem mapa listar.")
    ap.add_argument(
        "--sample-with",
        type=int,
        default=30,
        help="Com --report: quantos MVPs com mapa listar (id, nome, mapas).",
    )
    args = ap.parse_args()

    total, with_m, without_n, without_list, with_list = report()
    print(
        f"Catálogo MVP (fora de instância): {total} entradas | "
        f"com spawn_maps: {with_m} | sem spawn_maps: {without_n}"
    )

    if args.report or not args.enrich:
        n_with_show = min(args.sample_with, len(with_list))
        print(
            f"\nPrimeiros {n_with_show} MVPs com mapa registado (spawn_maps no catálogo, alinhado com spawn da API DP):"
        )
        for mid, name, maps in with_list[: args.sample_with]:
            print(f"  {mid}\t{name}\t→ {', '.join(maps)}")
        if len(with_list) > args.sample_with:
            print(f"  ... e mais {len(with_list) - args.sample_with} com mapa.")
        print(f"\nPrimeiros {min(args.sample, len(without_list))} MVPs sem mapa registado:")
        for mid, name in without_list[: args.sample]:
            print(f"  {mid}\t{name}")
        if len(without_list) > args.sample:
            print(f"  ... e mais {len(without_list) - args.sample}.")
        if not args.enrich:
            return

    key = resolve_api_key(_settings_api_key() or None)
    if not key:
        print(
            "\nChave Divine Pride em falta. Defina DIVINE_PRIDE_API_KEY ou "
            "divine_pride_api_key em herosaga_monitor_settings.json."
        )
        sys.exit(1)

    items = load_mvp_catalog_cache(max_age_seconds=None)
    if not items:
        print(f"Catálogo vazio ou inválido: {MVP_CATALOG_PORTABLE_FILE}")
        sys.exit(1)

    updated = 0
    failed = 0
    skipped = 0
    done = 0

    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "")
        if mvp_catalog_entry_skipped(it):
            continue
        try:
            mid = int(it.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if not mid:
            continue

        has_maps = isinstance(it.get("spawn_maps"), list) and any(
            str(x).strip() for x in (it.get("spawn_maps") or [])
        )
        need_fetch = args.sync_names or (not has_maps) or args.refresh_all
        if not need_fetch:
            skipped += 1
            continue

        if args.limit and done >= args.limit:
            break
        done += 1

        try:
            mobj = fetch_monster(mid, api_key=key, server=_settings_api_server(), timeout=35.0)
        except Exception as ex:
            print(f"  [{mid}] API: {ex}")
            failed += 1
            time.sleep(max(0.0, args.delay))
            continue

        changed = False
        if args.sync_names and isinstance(mobj, dict):
            nn = monster_api_display_name(mobj)
            if nn:
                it["name"] = nn
                changed = True
        if (not has_maps or args.refresh_all) and isinstance(mobj, dict):
            maps = spawn_maps_from_monster(mobj)
            if maps:
                it["spawn_maps"] = maps
                changed = True
        if changed:
            updated += 1
            nm = monster_api_display_name(mobj) if isinstance(mobj, dict) else ""
            maps_info = spawn_maps_from_monster(mobj) if isinstance(mobj, dict) else []
            bits = [nm[:46] + ("…" if len(nm) > 46 else "")] if nm else []
            if maps_info:
                bits.append(f"{len(maps_info)} mapa(s)")
            print(f"  + [{mid}] {' | '.join(bits) if bits else 'ok'}")
        else:
            skipped += 1
        time.sleep(max(0.0, args.delay))

    try:
        save_mvp_catalog_cache(items, name_display_locale="en")
    except OSError as ex:
        print(f"Erro a gravar catálogo: {ex}")
        sys.exit(1)

    print(f"\nGravado {MVP_CATALOG_PORTABLE_FILE} | actualizados: {updated} | falhas API: {failed} | ignorados: {skipped}")


if __name__ == "__main__":
    main()
