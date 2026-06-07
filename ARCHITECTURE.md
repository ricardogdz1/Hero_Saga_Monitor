# Arquitetura — GDZ Monitor

Aplicação desktop (Tkinter). A separação é por **camadas no mesmo processo**, não por servidor HTTP.

## Estrutura de pastas

```
herosaga_monitor/
├── app.py                 # Arranque (~320 linhas): HeroSagaMonitor + main
├── app_runtime.py         # Logging, API Hero Saga, scraping, helpers reexportados
├── core/
│   └── constants.py       # BASE_URL
├── adapters/
│   ├── network.py         # cloudscraper + HEADERS
│   ├── persistence.py     # JSON do utilizador (via app_storage)
│   ├── herosaga_api.py    # normalização URLs
│   └── herosaga_client.py # Cliente para services/item_search
├── services/
│   ├── item_search.py
│   ├── search_history.py
│   ├── monitored.py
│   └── item_detail.py
├── ui/
│   ├── shell.py           # Sidebar, navegação, filtros de listas
│   ├── theme.py           # Paleta C, apply_palette
│   ├── shared/
│   │   └── item_snapshot.py  # Cartões de item (ícone + preços)
│   ├── widgets/           # DarkButton, ScrollableFrame, …
│   └── pages/             # Uma página / funcionalidade por mixin
├── stores_scraper.py      # (legado) parsing HTML Hero Saga
├── app_services.py        # (legado) lógica HTTP partilhada
├── app_domain.py          # (legado) regras de domínio
└── app_storage.py         # (legado) ficheiros ~
```

## Fluxo

```
Utilizador → ui/pages + ui/shell → services → adapters / app_runtime → site / disco
```

## HeroSagaMonitor (MRO)

`AppShellMixin` → `ItemSnapshotMixin` → `BuscaPageMixin` → `MonitoredHomeMixin` → `ItemDetailMixin` → `MonitorListMixin` → `AlertsMixin` → `ConfigMixin` → `BuildSimMixin` → `MvpTimerMixin` → `LootPageMixin` → `HistPageMixin` → `tk.Tk`

## Estado da migração

- [x] Tema, widgets, adapters, services base
- [x] Home, busca, histórico, monitorados, detalhe, alertas, config
- [x] Simulação de build (`ui/pages/build_sim.py`)
- [x] Timer MVP (`ui/pages/mvp_timer.py`)
- [x] Auto Loot (`ui/pages/loot_page.py`)
- [x] Shell + cartões partilhados (`ui/shell.py`, `ui/shared/item_snapshot.py`)
- [x] `app.py` reduzido a janela + arranque; API em `app_runtime.py`
- [ ] Mover `app_services` / `stores_scraper` por completo para `adapters/` (opcional, incremental)

## Onde mexer

| Tarefa | Pasta |
|--------|--------|
| Novo botão / página | `ui/pages/` |
| Navegação / sidebar | `ui/shell.py` |
| Cartão de item em listas | `ui/shared/item_snapshot.py` |
| Nova regra de negócio | `services/` ou `app_domain.py` |
| Novo endpoint / HTML | `adapters/` + `stores_scraper.py` |
| API / scrape partilhado | `app_runtime.py` |

## Compatibilidade

Scripts e testes que fazem `from app import api_search, get_stores_from_item_page, …` continuam a funcionar: `app.py` reexporta símbolos de `app_runtime.py`.
