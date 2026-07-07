"""
Bootstrap da janela PyWebView.

Abre o webview nativo do sistema (no Windows, Edge WebView2), carrega o
frontend de ``gdz_monitor/web/`` e liga-o à ponte Python em ``api.py``.

Como correr (a partir da raiz do projeto):
    python run.py
"""
from __future__ import annotations

import os

import webview

from gdz_monitor import __version__
from gdz_monitor.app.api import Api
from gdz_monitor.core.paths import WEB_DIR


def main() -> None:
    index = os.path.join(WEB_DIR, "index.html")
    if not os.path.isfile(index):
        raise FileNotFoundError(f"Frontend não encontrado: {index}")
    webview.create_window(
        f"GDZ Monitor v{__version__}",
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
