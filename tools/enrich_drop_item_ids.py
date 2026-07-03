"""Gera ``data/drop_item_id_map.json`` (nome normalizado → item_id) via busca no site."""
from __future__ import annotations

import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from services.drop_calculator import (  # noqa: E402
    filter_mapa_for_display,
    load_drop_item_id_map,
    load_maps_catalog,
    normalize_item_name,
    resolve_drop_items_meta,
)

_OUT = os.path.join(_ROOT, "data", "drop_item_id_map.json")


def _collect_names() -> list[str]:
    names: set[str] = set()
    for c in load_maps_catalog().get("conteudos") or []:
        f = filter_mapa_for_display(c)
        for sec in f.get("secoes") or []:
            for it in sec.get("itens") or []:
                n = str(it.get("nome") or "").strip()
                if n:
                    names.add(n)
    return sorted(names)


def main() -> None:
    from web_poc.api import Api, _fetch_url_bytes

    api = Api()
    names = _collect_names()
    out = dict(load_drop_item_id_map())
    print(f"Itens únicos: {len(names)} (mapa existente: {len(out)})")

    batch = 8
    for i in range(0, len(names), batch):
        chunk = names[i : i + batch]
        resolved = resolve_drop_items_meta(
            chunk,
            api._drop_search_item,
            _fetch_url_bytes,
            dp_search_fn=api._drop_dp_search_item,
            hs_by_id_fn=api._drop_hs_item_by_id,
        )
        for name, meta in resolved.items():
            iid = int(meta.get("item_id") or 0)
            if iid <= 0:
                print(f"  --       {name}")
                continue
            key = normalize_item_name(name)
            out[key] = iid
            via = meta.get("resolve_by") or "?"
            print(f"  OK {iid:>6} ({via})  {name}")
        time.sleep(0.35)

    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"Gravado: {_OUT} ({len(out)} entradas)")


if __name__ == "__main__":
    main()
