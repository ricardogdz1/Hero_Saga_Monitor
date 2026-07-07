"""
Importa nome + ID + ícone de páginas da wiki Hero Saga para a calculadora de drop.

Uso:
    python tools/import_wiki_drop_items.py
    python tools/import_wiki_drop_items.py --dry-run
    python tools/import_wiki_drop_items.py --urls url1 url2 ...
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from html import unescape
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote, urlparse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from gdz_monitor.core.constants import BASE_URL
from gdz_monitor.services.drop_calculator import (
    filter_mapa_for_display,
    load_drop_item_id_map,
    load_maps_catalog,
    normalize_item_name,
    search_name_variants,
)

DEFAULT_WIKI_URLS = [
    "https://wiki.rpgherosaga.com/index.php/Cheff%C3%AAnia",
    "https://wiki.rpgherosaga.com/index.php/Villa_Of_Zeny",
    "https://wiki.rpgherosaga.com/index.php/Caminho_do_Iniciante",
    "https://wiki.rpgherosaga.com/index.php/Jardim_Sagrado",
    "https://wiki.rpgherosaga.com/index.php/Tumba_da_Honra",
    "https://wiki.rpgherosaga.com/index.php/Trilha_do_Her%C3%B3i",
    "https://wiki.rpgherosaga.com/index.php/Legi%C3%A3o",
    "https://wiki.rpgherosaga.com/index.php/Unknow_Blue_Hole",
    "https://wiki.rpgherosaga.com/index.php/Jardim_dos_Elementais",
    "https://wiki.rpgherosaga.com/index.php/Ascens%C3%A3o_Somatol%C3%B3gica",
    "https://wiki.rpgherosaga.com/index.php/Campo_do_Minerador",
]

_OUT_MAP = os.path.join(_ROOT, "data", "drop_item_id_map.json")
_ITEM_ICON_RE = re.compile(
    r"(?:processicon[^\"'&]*(?:&amp;|&)?id=(\d+)|items/item/(\d+)\.(?:png|gif|jpg))",
    re.I,
)
_CHANCE_PREFIX_RE = re.compile(r"^\[\d+(?:[,\.]\d+)?%\]\s*", re.I)
_JUNK_NAME_MARKERS = (
    "npc ", "voce pode", "acesso disponivel", "custos de acesso",
    "os encantos", "nao ha desconto", "mapa que pode",
)


def _is_plausible_item_name(name: str) -> bool:
    s = normalize_item_name(name)
    if not s or len(s) < 2 or len(s) > 80:
        return False
    if any(marker in s for marker in _JUNK_NAME_MARKERS):
        return False
    if s.count(" ") > 12:
        return False
    return True


def _strip_tags(html: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", html or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", unescape(s)).strip()


def _clean_wiki_item_name(raw: str) -> str:
    s = _strip_tags(raw)
    s = _CHANCE_PREFIX_RE.sub("", s)
    s = re.sub(r"^\d+x\s+", "", s, flags=re.I)
    return s.strip()


def _extract_item_ids(fragment: str) -> List[int]:
    ids: List[int] = []
    seen: set[int] = set()
    for m1, m2 in _ITEM_ICON_RE.findall(fragment or ""):
        raw = m1 or m2
        try:
            iid = int(str(raw).split(".")[0])
        except (TypeError, ValueError):
            continue
        if iid <= 0 or iid in seen:
            continue
        seen.add(iid)
        ids.append(iid)
    return ids


def _name_from_row_cells(cells: List[str]) -> str:
    """Nome do item: célula sem ícone, ou texto restante na célula do ícone."""
    candidates: List[str] = []
    for cell in cells:
        without_imgs = re.sub(r"<img[^>]*>", " ", cell or "", flags=re.I)
        candidate = _clean_wiki_item_name(without_imgs)
        if candidate and not re.match(r"^[\d,\.]+%$", candidate):
            candidates.append(candidate)
    if not candidates:
        return ""
    # Prefere o nome mais longo (evita células só com chance/contexto).
    return max(candidates, key=len)


def parse_wiki_page(html: str) -> List[dict]:
    """Extrai pares nome/ID das tabelas e blocos inline da wiki."""
    text = unescape(html or "")
    out: List[dict] = []
    seen: set[tuple[str, int]] = set()

    def add(name: str, iid: int) -> None:
        name = str(name or "").strip()
        if iid <= 0 or not _is_plausible_item_name(name):
            return
        key = (normalize_item_name(name), iid)
        if key in seen:
            return
        seen.add(key)
        out.append({"name": name, "item_id": iid})

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I)
    for row in rows:
        if "processicon" not in row and "items/item/" not in row:
            continue
        ids = _extract_item_ids(row)
        if not ids:
            continue
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)
        name = _name_from_row_cells(cells)
        if not name:
            continue
        for iid in ids:
            add(name, iid)

    inline_img_name = re.compile(
        r'<img[^>]+(?:processicon[^"\']*(?:&amp;|&)?id=(\d+)|items/item/(\d+)\.(?:png|gif|jpg))[^>]*>'
        r"\s*(?:<[^>]+>\s*)*([^<]{2,120}?)(?:\s*\(|<|$)",
        re.I | re.S,
    )
    for m in inline_img_name.finditer(text):
        iid = int(m.group(1) or m.group(2))
        add(_clean_wiki_item_name(m.group(3)), iid)

    inline_name_img = re.compile(
        r"([^<>]{2,80}?)\s*<img[^>]+(?:processicon[^\"\']*(?:&amp;|&)?id=(\d+)"
        r"|items/item/(\d+)\.(?:png|gif|jpg))[^>]*>",
        re.I | re.S,
    )
    for m in inline_name_img.finditer(text):
        iid = int(m.group(2) or m.group(3))
        add(_clean_wiki_item_name(m.group(1)), iid)

    return out


def fetch_wiki_html(url: str) -> str:
    from gdz_monitor.adapters.network import scraper

    resp = scraper.get(url, timeout=25, allow_redirects=True)
    resp.raise_for_status()
    return resp.text


def wiki_page_label(url: str) -> str:
    path = unquote(urlparse(url).path or "")
    title = path.rsplit("/", 1)[-1] if path else url
    return title or url


def collect_wiki_catalog(urls: Iterable[str]) -> Tuple[Dict[str, dict], dict]:
    """Retorna {nome_normalizado: {item_id, name, sources}} e estatísticas."""
    catalog: Dict[str, dict] = {}
    stats = {"pages": 0, "rows": 0, "conflicts": 0}

    for url in urls:
        page = wiki_page_label(url)
        try:
            html = fetch_wiki_html(url)
        except Exception as exc:
            print(f"  ERRO {page}: {exc}")
            continue
        rows = parse_wiki_page(html)
        stats["pages"] += 1
        stats["rows"] += len(rows)
        print(f"  {page}: {len(rows)} entradas")

        for row in rows:
            name = str(row.get("name") or "").strip()
            iid = int(row.get("item_id") or 0)
            if not name or iid <= 0:
                continue
            key = normalize_item_name(name)
            if not key:
                continue
            prev = catalog.get(key)
            if prev and int(prev["item_id"]) != iid:
                stats["conflicts"] += 1
                continue
            catalog[key] = {
                "item_id": iid,
                "name": name,
                "sources": sorted(set((prev or {}).get("sources") or []) | {page}),
            }
        time.sleep(0.2)

    return catalog, stats


def collect_drop_names() -> List[str]:
    names: set[str] = set()
    for cont in load_maps_catalog().get("conteudos") or []:
        filtered = filter_mapa_for_display(cont)
        for sec in filtered.get("secoes") or []:
            for it in sec.get("itens") or []:
                n = str(it.get("nome") or "").strip()
                if n:
                    names.add(n)
    return sorted(names)


def _drop_lookup_variants(drop_name: str) -> List[str]:
    """Variantes extras além de ``search_name_variants``."""
    raw = str(drop_name or "").strip()
    out: List[str] = []
    seen: set[str] = set()

    def add(val: str) -> None:
        val = str(val or "").strip()
        if not val or val in seen:
            return
        seen.add(val)
        out.append(val)

    for variant in search_name_variants(raw):
        add(variant)
        add(re.sub(r"^\d+x\s+", "", variant, flags=re.I))
        add(re.sub(r"\s+ii(\s|$)", r"\1", variant, flags=re.I))
        add(re.sub(r"\s+ii(\s|$)", r"\1", re.sub(r"^\d+x\s+", "", variant, flags=re.I), flags=re.I))

    no_qty = re.sub(r"^\d+x\s+", "", raw, flags=re.I).strip()
    add(no_qty)
    add(re.sub(r"\s+ii(\s|$)", r"\1", no_qty, flags=re.I))
    return out


def match_drop_names(
    drop_names: Iterable[str],
    wiki_catalog: Dict[str, dict],
) -> Tuple[Dict[str, int], List[str]]:
    """Mapeia nome normalizado (drop) → item_id via catálogo wiki."""
    matched: Dict[str, int] = {}
    missing: List[str] = []

    for drop_name in drop_names:
        found_id: Optional[int] = None
        for variant in _drop_lookup_variants(drop_name):
            key = normalize_item_name(variant)
            entry = wiki_catalog.get(key)
            if entry and int(entry["item_id"]) > 0:
                found_id = int(entry["item_id"])
                break
        if found_id:
            matched[normalize_item_name(drop_name)] = found_id
        else:
            missing.append(drop_name)

    return matched, missing


def _fetch_icon_bytes(url: str) -> Optional[bytes]:
    from gdz_monitor.adapters.network import scraper

    try:
        resp = scraper.get(url, timeout=15, allow_redirects=True)
        if getattr(resp, "status_code", 0) == 200:
            return resp.content
    except Exception:
        return None
    return None


def download_icons(item_ids: Iterable[int], *, dry_run: bool = False) -> dict:
    stats = {"requested": 0, "saved": 0, "cached": 0, "failed": 0}

    unique = sorted({int(i) for i in item_ids if int(i) > 0})
    stats["requested"] = len(unique)
    if dry_run:
        return stats

    from gdz_monitor.external.item_icon_cache import ensure_item_icons_dir, item_icon_disk_path, read_item_icon_png_bytes

    ensure_item_icons_dir()

    for iid in unique:
        path = item_icon_disk_path(iid)
        if os.path.isfile(path):
            stats["cached"] += 1
            continue
        url = f"{BASE_URL.rstrip('/')}/?module=image&action=processicon&id={iid}"
        try:
            raw = read_item_icon_png_bytes(iid, url, _fetch_icon_bytes, base_url=BASE_URL)
            if raw and os.path.isfile(path):
                stats["saved"] += 1
            else:
                stats["failed"] += 1
                print(f"    icone falhou: {iid}")
        except Exception as exc:
            stats["failed"] += 1
            print(f"    icone erro {iid}: {exc}")
        time.sleep(0.05)

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa IDs/ícones da wiki para a calculadora de drop")
    parser.add_argument("--dry-run", action="store_true", help="Só mostra o que seria gravado")
    parser.add_argument("--urls", nargs="*", default=None, help="URLs da wiki (padrão: mapas da calculadora)")
    parser.add_argument("--skip-icons", action="store_true", help="Só atualiza drop_item_id_map.json")
    args = parser.parse_args()

    urls = args.urls if args.urls else DEFAULT_WIKI_URLS
    existing = load_drop_item_id_map()

    print("Baixando páginas da wiki…")
    wiki_catalog, wiki_stats = collect_wiki_catalog(urls)
    print(
        f"Catálogo wiki: {len(wiki_catalog)} nomes únicos "
        f"({wiki_stats['rows']} linhas, {wiki_stats['conflicts']} conflitos ignorados)"
    )

    drop_names = collect_drop_names()
    matched, missing = match_drop_names(drop_names, wiki_catalog)
    print(f"Itens da calculadora: {len(drop_names)} | casados: {len(matched)} | sem match: {len(missing)}")

    merged = dict(existing)
    merged.update(matched)

    if missing:
        print("\nSem match na wiki (primeiros 25):")
        for name in missing[:25]:
            print(f"  - {name}")
        if len(missing) > 25:
            print(f"  … e mais {len(missing) - 25}")

    print(f"\nMapa: {len(existing)} existentes -> {len(merged)} entradas")
    if not args.dry_run:
        os.makedirs(os.path.dirname(_OUT_MAP), exist_ok=True)
        with open(_OUT_MAP, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2, sort_keys=True)
        print(f"Gravado: {_OUT_MAP}")

    if not args.skip_icons:
        print("\nBaixando ícones…")
        icon_stats = download_icons(merged.values(), dry_run=args.dry_run)
        print(
            f"Ícones: {icon_stats['requested']} IDs | "
            f"{icon_stats['cached']} já em cache | "
            f"{icon_stats['saved']} baixados | "
            f"{icon_stats['failed']} falhas"
        )


if __name__ == "__main__":
    main()
