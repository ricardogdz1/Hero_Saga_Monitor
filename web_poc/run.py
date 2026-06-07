"""
Runner da prova de conceito (Home em web/pywebview).

Abre uma janela com o webview nativo do sistema (no Windows, Edge WebView2)
e liga o front-end em ``web/`` à ponte Python em ``api.py``.

Como correr:
    python web_poc/run.py
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import webview  # noqa: E402

from web_poc.api import Api  # noqa: E402


def main() -> None:
    index = os.path.join(_HERE, "web", "index.html")
    webview.create_window(
        "GDZ Monitor",
        url=index,
        js_api=Api(),
        width=1240,
        height=780,
        min_size=(900, 600),
        background_color="#0a0a0f",
    )
    webview.start(debug=False)


if __name__ == "__main__":
    main()
