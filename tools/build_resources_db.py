"""
Empacota a pasta ``data/`` num banco SQLite somente leitura (``resources.db``).

O executável embute este banco em vez dos ficheiros soltos de ``data/``
(lido via ``gdz_monitor/core/resources.py``). O ``HerosagaMonitor.spec`` já
chama isto automaticamente; usar à mão só para inspeccionar o resultado.

Uso::

    python tools/build_resources_db.py                 # → build/resources.db
    python tools/build_resources_db.py --out caminho.db
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gdz_monitor.core.resources import build_resources_db  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Empacotar data/ em resources.db")
    ap.add_argument("--out", type=Path, default=_ROOT / "build" / "resources.db")
    args = ap.parse_args()
    n = build_resources_db(str(args.out))
    size_mb = os.path.getsize(args.out) / (1024 * 1024)
    print(f"=> {n} ficheiros em {args.out} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
