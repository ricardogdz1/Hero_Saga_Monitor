"""Lista MVPs (catálogo, fora de instância) que ainda não têm imagem em resolve_mob_image."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gdz_monitor.services.mvp_timer import (  # noqa: E402
    load_mvp_catalog_cache,
    mvp_catalog_entry_skipped,
    resolve_mob_image,
)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

    items = load_mvp_catalog_cache(max_age_seconds=None) or []
    miss: list[tuple[int, str]] = []
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
        b, _ = resolve_mob_image(mid, display_name=name)
        if not b:
            miss.append((mid, name))

    print(f"MVPs sem imagem: {len(miss)}")
    for mid, name in sorted(miss, key=lambda x: (x[1].casefold(), x[0])):
        print(f"  {mid}\t{name}")


if __name__ == "__main__":
    main()
