# Protocolo de QA — obrigatório para qualquer agente (Claude, Codex, Copilot, Cursor, Gemini…) e humanos

Contexto do projeto (stack, arquitetura, convenções): ver `CLAUDE.md`.

## Definição de pronto
Uma mudança só está pronta quando **as quatro etapas abaixo foram feitas e relatadas**.
"Compila" ou "parece certo" não conta.

### 1. Provar o pedido com um teste
Todo pedido de feature ou correção ganha pelo menos um caso de teste que **falharia sem a mudança**:
- regra pura em `services/` → teste unitário em `tests/test_<módulo>.py`;
- método novo/alterado em `gdz_monitor/app/api.py` ou fluxo de página → adicionar passos ao
  cenário `smoke` (ou um cenário novo) em `tests/qa/_harness.py`, usando
  `r.call(...)` / `r.check(...)`;
- bug corrigido → teste de regressão que reproduz o bug (ex.: cenário `concurrency`).

O harness roda a `Api` real em subprocesso com HOME, `LOCALAPPDATA` e banco SQLite
(`GDZ_MONITOR_DB`) temporários e **rede bloqueada** — e recusa rodar sem isso.
Nunca importe `gdz_monitor.app` direto no processo do pytest: o caminho do banco é
resolvido no import e os testes escreveriam no `gdz_monitor.db` real.

### 2. Rodar a suíte inteira
```
pytest
```
Inclui `tests/qa/`: chamadas `window.pywebview.api.*` do `app.js` existem na `Api` com
aridade válida, rotas do menu têm renderizador, `getElementById` aponta para ids existentes,
sintaxe do `app.js` (`node --check`), JSON de `data/` válido, fluxos de todas as páginas e
regressões de concorrência. Tudo precisa passar — não apagar nem pular teste para ficar verde.

### 3. Conferir na UI quando a mudança é visível
```
python tools/qa_server.py --with-my-data
```
Abrir `http://127.0.0.1:8765`, executar o fluxo pedido pela página e conferir no console
`window.__qaErrors` (deve ser `[]`) e `fetch('/__calls')` (sem `exc`, sem `ok:false` inesperado).
HOME e banco isolados (`--with-my-data` usa uma cópia do seu banco): os dados reais não são alterados. Ações que enviam algo para fora
(e-mail de teste, login Discord, alertas) não devem ser disparadas sem o usuário pedir.

### 4. Relatar com evidência
No fim, informar: o que foi testado, o teste que prova o pedido, o resultado do `pytest`
(nº de testes) e o que **não** foi possível verificar (ex.: depende de chave Divine Pride ou login).

## Gates automáticos
- **pre-commit** (`.githooks/pre-commit`): bloqueia commit se o `pytest` falhar.
  Ativar uma vez por clone: `git config core.hooksPath .githooks`
- **build.bat**: não gera o `.exe` se o `pytest` falhar.

`--no-verify` só com pedido explícito do usuário.
