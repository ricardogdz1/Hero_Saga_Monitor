"""
Caminhos para recursos empacotados (pasta ``data/`` e frontend ``web/``).

Funciona nos dois modos de execução:
- Desenvolvimento: os caminhos derivam da posição deste ficheiro no repo.
- Executável PyInstaller: ``__file__`` aponta para dentro de ``sys._MEIPASS``,
  onde o .spec embute ``data/`` e ``gdz_monitor/web/`` com a mesma hierarquia.
"""
from __future__ import annotations

import os

_PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT_DIR = os.path.dirname(_PACKAGE_DIR)

# Dados bundled (catálogo MVP, mapas de drop, sprites, ícones de itens)
DATA_DIR = os.path.join(_ROOT_DIR, "data")

# Frontend servido na janela PyWebView
WEB_DIR = os.path.join(_PACKAGE_DIR, "web")
