# GDZ Monitor (herosaga_monitor)

Você ajuda no desenvolvimento do GDZ Monitor — app desktop Python para o servidor Hero Saga (Ragnarok Online privado: herosaga.com.br).

## Stack
- Python 3.10+, PyWebView (WebView2 no Windows), HTML/CSS/JS vanilla
- Entry point: `run.py` na raiz (→ `gdz_monitor/app/main.py`)
- Build: PyInstaller → `dist/GDZMonitor.exe` via `build.bat` (usa o Python global, não a `.venv`)

## Arquitetura
UI (gdz_monitor/web/) → ponte JS `window.pywebview.api` → gdz_monitor/app/api.py (classe Api) → services/ → adapters/ + external/ → site Hero Saga / disco

Regra de dependência entre camadas (nunca ao contrário): `app → services → adapters/external → core`

Pastas-chave (tudo dentro do pacote `gdz_monitor/`):
- `app/` — camada de aplicação: `api.py` (todos os métodos expostos ao JS), `main.py` (janela), `alert_worker.py`, `discord_login.py`
- `web/` — UI (index.html, app.js ~5k linhas, style.css)
- `services/` — regras de negócio: `mvp_timer.py`, `loot_manager.py`, `alert_monitor.py`, `drop_calculator.py` + subpacotes `market/` (busca, histórico, lojas, preços — `runtime.py` é a fachada usada pela app) e `build/` (simulador: `simulator.py`, `characters.py`, `stats.py`)
- `adapters/` — HTTP (`network.py`), scraping do site (`herosaga_api.py`), sessão Discord (`herosaga_session.py`), persistência (`persistence.py`)
- `external/` — Divine Pride (`divine_pride_api.py`) e cache de ícones (`item_icon_cache.py`)
- `core/` — `constants.py` (BASE_URL), `paths.py` (DATA_DIR/WEB_DIR, dev e .exe), `settings.py`, `storage.py`

Fora do pacote:
- `data/` — dados bundled (MVP, drops, sprites); caminhos resolvidos via `gdz_monitor/core/paths.py`
- `tools/` — scripts de manutenção de dados (não vão no .exe)
- `docs/` — ARCHITECTURE.md + material da calculadora de drop

## Páginas da UI
home | build | mvp | loot | alerts | drop-calc | config

## Regras de desenvolvimento
- Responder em português (BR), salvo se eu pedir outro idioma
- Mudanças mínimas e focadas — não refatorar código não relacionado
- Seguir convenções existentes (naming, estrutura de retorno dict com ok/error)
- Nova UI: editar `gdz_monitor/web/` + expor método em `gdz_monitor/app/api.py`
- Nova regra de negócio: `gdz_monitor/services/` (módulo dedicado ou subpacote existente)
- Ícones sempre via `gdz_monitor/external/item_icon_cache.py` (base64 data URI)
- Autenticação Discord: cookie fluxSessionData; métodos podem retornar discord_auth_required
- Moedas: zeny, rmt, hero_points
- Dados do usuário ficam em ~/herosaga_*.json
- Sem framework JS. Testes: pytest em `tests/` (só funções puras de services/ — nada de UI nem rede); rodar `pytest` na raiz
- Não commitar secrets (.env, senhas SMTP, API keys)
- Não criar arquivos de documentação a menos que eu peça

## Ao implementar
1. Identificar a página/feature afetada
2. Localizar método correspondente em `gdz_monitor/app/api.py`
3. Implementar lógica em `gdz_monitor/services/`
4. Atualizar `gdz_monitor/web/app.js` se necessário
5. Manter compatibilidade com PyInstaller (`data/` e `gdz_monitor/web/` bundled; caminhos via `core/paths.py`)
6. Rodar `pytest` ao mexer em lógica coberta (preços, drop calc, stats de build, domain) e adicionar casos novos quando corrigir bug de parsing/cálculo

## Formato de resposta preferido
- Explicar brevemente o que vai fazer antes de código extenso
- Mostrar apenas trechos relevantes de código
- Indicar arquivos alterados ao final
- Se houver ambiguidade, perguntar antes de grandes mudanças
