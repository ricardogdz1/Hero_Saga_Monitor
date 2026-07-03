# Arquitetura — GDZ Monitor

Aplicação desktop **PyWebView** (Python + HTML/CSS/JS). A UI vive em `web_poc/`; a ponte expõe métodos Python ao JavaScript via `window.pywebview.api`.

## Estrutura de pastas

```
herosaga_monitor/
├── web_poc/
│   ├── run.py             # Arranque principal (PyWebView)
│   ├── api.py             # Ponte Python ↔ JS
│   ├── alert_worker.py    # Vigia de alertas em background
│   └── web/               # index.html, app.js, style.css
├── app.py                 # Reexports legados (`from app import api_search`)
├── app_runtime.py         # Logging, API Hero Saga, scraping
├── core/
│   ├── constants.py       # BASE_URL
│   └── theme.py           # Paleta C (tema claro/escuro via settings)
├── adapters/              # Rede, persistência, cliente Hero Saga
├── services/              # Regras de negócio (busca, monitorados, …)
├── loot_manager.py        # Lógica Auto Loot (sem UI)
├── mvp_timer.py           # Timer MVP + catálogo (dados em data/)
├── build_simulator.py     # Builds salvas / slots de equipamento
└── data/                  # Catálogo MVP, mapas, sprites (bundled no .exe)
```

## Fluxo

```
Utilizador → web_poc/web (JS) → web_poc/api.py → services / adapters / app_runtime → site / disco
```

## Como correr

| Modo | Comando |
|------|---------|
| Desenvolvimento | `python web_poc/run.py` ou `run.bat` |
| Executável Windows | `build.bat` → `dist/GDZMonitor.exe` |

## Build PyInstaller

- Spec: `HerosagaMonitor.spec`
- Entry: `web_poc/run.py`
- Dados embutidos: `data/`, `web_poc/web/`

## Onde mexer

| Tarefa | Pasta |
|--------|--------|
| Nova página / comportamento UI | `web_poc/web/` + `web_poc/api.py` |
| Nova regra de negócio | `services/` ou módulos na raiz |
| API / scrape | `adapters/` + `app_runtime.py` |
| Paleta / tema | `core/theme.py` |

## Compatibilidade

Scripts que fazem `from app import api_search, …` continuam a funcionar via `app.py` (reexport de `app_runtime`).
