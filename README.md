# GDZ Monitor

Ferramentas para Hero Saga (herosaga.com.br): mercado, alertas, build, timer MVP e auto loot.

## Como rodar

### Método 1 — Rodar direto com Python

1. Instale o Python 3.10+ em https://python.org
2. Abra o terminal na pasta do projeto
3. Instale as dependências:
   ```
   pip install -r requirements.txt
   ```
4. Rode o app:
   ```
   python run.py
   ```
   Ou dê duplo clique em `run.bat`.

**Requisito Windows:** [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) (já presente na maioria dos PCs com Edge).

### Método 2 — Gerar o .exe (Windows)

1. Instale o Python 3.10+ em https://python.org
   - **IMPORTANTE:** marque "Add Python to PATH" na instalação
2. Dê duplo clique em `build.bat`
3. Aguarde (pode demorar 1–2 minutos)
4. O executável estará em `dist/GDZMonitor.exe`

O `.exe` usa PyWebView (mesma UI que `python run.py`) e inclui a pasta `data/` para catálogo MVP offline. Quem baixa o `.exe` **não precisa ter Python instalado** — só o [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) (já presente na maioria dos PCs com Edge).

### Método 3 — Gerar o instalador (opcional, para distribuição)

1. Instale o [Inno Setup 6](https://jrsoftware.org/isdl.php) (gratuito)
2. Rode `build.bat` (gera o exe) e depois `build_installer.bat`
3. O instalador estará em `dist/GDZMonitor-Setup-v<versão>.exe` — instala por usuário (sem pedir admin), cria atalho e desinstalador

> **Nota para distribuição:** exe sem assinatura digital dispara o aviso do Windows SmartScreen. Instrua os usuários: "Mais informações" → "Executar assim mesmo".

## Funcionalidades

- **Busca por nome** — Busca itens na API oficial do Herosaga
- **Histórico de vendas** — Vê o histórico completo de vendas de cada item
- **Monitorar itens** — Salva itens favoritos para acesso rápido
- **Alertas de preço** — Notificações quando o preço cruza um limiar
- **Simulação de build** — Atributos, equipamentos e stats IRO
- **Timer MVP** — Respawn com mapas e alertas de spawn
- **Auto Loot** — Grupos `@alootid2` com busca de itens

## Dados salvos

O app guarda todos os dados (monitorados, configurações, alertas, histórico de preços,
timers MVP, grupos de auto loot, builds e o cache de imagens) num banco SQLite local:

- Windows: `%LOCALAPPDATA%\GDZMonitor\gdz_monitor.db`
- Outros sistemas: `~/.gdz_monitor/gdz_monitor.db`

Na primeira execução, os antigos `~/herosaga_*.json` (e os ícones/imagens em cache) são
importados automaticamente; os ficheiros originais ficam intocados como backup.

## API utilizada

- Busca por nome: `herosaga.com.br/?module=vending&action=search&item_search=NOME`
- Histórico por ID: `herosaga.com.br/?module=item&action=view&id=ID`

## Testes

As regras de negócio (parse de preços, calculadora de drop, stats de build, vendas) têm testes automatizados:

```
pip install pytest
pytest
```

Rodam em menos de 1 segundo, sem rede e sem abrir janela. Ao corrigir um bug de cálculo/parsing, adicione um caso em `tests/` para ele não voltar.

## Estrutura do projeto

Todo o código da aplicação vive no pacote `gdz_monitor/` (camadas `app` → `services` → `adapters`/`external` → `core`). Detalhes em [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
