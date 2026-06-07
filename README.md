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
   python web_poc/run.py
   ```

### Método 2 — Gerar o .exe (Windows)

1. Instale o Python 3.10+ em https://python.org
   - **IMPORTANTE:** marque "Add Python to PATH" na instalação
2. Dê duplo clique em `build.bat`
3. Aguarde (pode demorar 1-2 minutos)
4. O executável estará em `dist/GDZMonitor.exe`

## Funcionalidades

- **Busca por nome** — Busca itens na API oficial do Herosaga
- **Histórico de vendas** — Vê o histórico completo de vendas de cada item
- **Gráfico de preço** — Visualiza a variação de preço ao longo do tempo
- **Estatísticas** — Último preço, mínimo, máximo e média
- **Monitorar itens** — Salva itens favoritos para acesso rápido
- **Histórico de buscas** — Rebusca rapidamente itens pesquisados antes

## Dados salvos

O app salva seus dados em:
```
C:\Users\SeuUsuario\herosaga_monitor_data.json
```

## API utilizada

- Busca por nome: `herosaga.com.br/?module=vending&action=search&item_search=NOME`
- Histórico por ID: `herosaga.com.br/?module=item&action=view&id=ID`
"# Hero_Saga_Monitor" 
"# Hero_Saga_Monitor" 
