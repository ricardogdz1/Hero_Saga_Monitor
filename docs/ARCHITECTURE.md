# Arquitetura — GDZ Monitor

Aplicação desktop **PyWebView** (Python + HTML/CSS/JS). Todo o código da aplicação vive no pacote `gdz_monitor/`; a ponte expõe métodos Python ao JavaScript via `window.pywebview.api`.

## Estrutura de pastas

```
herosaga_monitor/
├── run.py                     # Ponto de entrada (python run.py)
├── gdz_monitor/               # Pacote da aplicação
│   ├── app/                   # Camada de aplicação (PyWebView)
│   │   ├── main.py            #   Bootstrap da janela
│   │   ├── api.py             #   Ponte Python ↔ JS (todos os métodos expostos)
│   │   ├── alert_worker.py    #   Vigia de alertas em background
│   │   └── discord_login.py   #   Janela de login Discord (cookie de sessão)
│   ├── web/                   # Frontend (index.html, app.js, style.css)
│   ├── services/              # Regras de negócio (sem UI, sem HTTP direto)
│   │   ├── market/            #   Mercado: busca, histórico, lojas, preços
│   │   ├── build/             #   Simulador de build (personagem, stats, equips)
│   │   ├── mvp_timer.py       #   Timer MVP + catálogo (dados em data/)
│   │   ├── loot_manager.py    #   Grupos de Auto Loot (@alootid2)
│   │   ├── alert_monitor.py   #   Checagem de alertas + e-mail SMTP
│   │   └── drop_calculator.py #   Calculadora de drop (mapas/buffs em data/)
│   ├── adapters/              # Acesso a sistemas externos
│   │   ├── network.py         #   Sessão HTTP (cloudscraper) + headers
│   │   ├── herosaga_session.py#   Autenticação Discord (fluxSessionData)
│   │   ├── herosaga_api.py    #   Endpoints do site Hero Saga
│   │   ├── herosaga_client.py #   Cliente de alto nível
│   │   └── persistence.py     #   Leitura/escrita dos JSON do utilizador (~)
│   ├── external/              # Integrações de terceiros
│   │   ├── divine_pride_api.py#   API Divine Pride (monstros, itens)
│   │   └── item_icon_cache.py #   Cache de ícones em data/item_icons/
│   └── core/                  # Partilhado por todas as camadas
│       ├── constants.py       #   BASE_URL
│       ├── paths.py           #   DATA_DIR / WEB_DIR (dev e .exe)
│       ├── settings.py        #   Configurações do utilizador
│       └── storage.py         #   Helpers de ficheiros JSON
├── data/                      # Catálogo MVP, mapas, sprites (bundled no .exe)
├── tools/                     # Scripts de manutenção de dados (não vão no .exe)
├── docs/                      # Esta documentação + material da calculadora de drop
├── HerosagaMonitor.spec       # Build PyInstaller
├── run.bat / build.bat
└── requirements.txt
```

## Fluxo

```
Utilizador → gdz_monitor/web (JS) → app/api.py → services/ → adapters/ + external/ → site / disco
```

Regras de dependência entre camadas (de cima para baixo, nunca ao contrário):

```
app → services → adapters / external → core
```

## Como correr

| Modo | Comando |
|------|---------|
| Desenvolvimento | `python run.py` ou `run.bat` |
| Executável Windows | `build.bat` → `dist/GDZMonitor.exe` |

## Build PyInstaller

- Spec: `HerosagaMonitor.spec`
- Entry: `run.py`
- Dados embutidos: `data/`, `gdz_monitor/web/`
- Os caminhos para esses recursos são resolvidos em `gdz_monitor/core/paths.py`,
  que funciona igual em dev e dentro do `.exe` (`sys._MEIPASS`).

## Onde mexer

| Tarefa | Pasta |
|--------|--------|
| Nova página / comportamento UI | `gdz_monitor/web/` + `gdz_monitor/app/api.py` |
| Nova regra de negócio | `gdz_monitor/services/` |
| API / scrape do site | `gdz_monitor/adapters/` + `services/market/` |
| Novo dado bundled | `data/` + `HerosagaMonitor.spec` (já cobre a pasta inteira) |
| Script de preparação de dados | `tools/` |

## Notas

- Não há framework JS nem testes automatizados; a UI é HTML/CSS/JS vanilla.
- Dados do utilizador ficam em `~/herosaga_*.json` (ver `adapters/persistence.py`).
- O frontend antigo (Tkinter) foi removido; o histórico está no git
  (`app.py`, `core/theme.py`, `mvp_alert_sound.py` eram resquícios dele).
