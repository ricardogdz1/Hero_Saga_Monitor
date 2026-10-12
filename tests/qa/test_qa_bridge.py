"""QA estático da UI: app.js ↔ Api, rotas, sintaxe JS e dados bundled."""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from conftest import ROOT

WEB = ROOT / "gdz_monitor" / "web"
APP_JS = (WEB / "app.js").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")


def _split_args(src: str) -> list[str]:
    depth, quote, cur, out = 0, None, "", []
    for ch in src:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append(cur)
            cur = ""
            continue
        cur += ch
    if cur.strip():
        out.append(cur)
    return out


def _js_api_calls() -> list[tuple[str, int, int]]:
    """(método, nº de argumentos, linha) de cada window.pywebview.api.X(...)."""
    calls = []
    for m in re.finditer(r"pywebview\.api\.(\w+)\(", APP_JS):
        i = j = m.end()
        depth = 1
        while depth and j < len(APP_JS):
            depth += {"(": 1, ")": -1}.get(APP_JS[j], 0)
            j += 1
        calls.append((m.group(1), len(_split_args(APP_JS[i:j - 1])), APP_JS.count("\n", 0, m.start()) + 1))
    return calls


def test_toda_chamada_do_js_existe_na_api_com_aridade_valida(run_scenario):
    sigs = run_scenario("signatures")["signatures"]
    problemas = []
    for name, nargs, line in _js_api_calls():
        sig = sigs.get(name)
        if sig is None:
            problemas.append(f"app.js:{line} chama api.{name}() que não existe em Api")
        elif nargs < sig["required"] or (nargs > sig["max"] and not sig["varargs"]):
            problemas.append(f"app.js:{line} api.{name}() com {nargs} args; Python espera "
                             f"{sig['required']}..{sig['max']}")
    assert not problemas, "\n".join(problemas)


def test_rotas_do_menu_tem_renderizador():
    nav = set(re.findall(r'data-route="([\w-]+)"', INDEX))
    block = re.search(r"const ROUTES = \{(.*?)\};", APP_JS, re.S)
    assert block, "objeto ROUTES não encontrado em app.js"
    routes = set(re.findall(r'"?([\w-]+)"?\s*:', block.group(1)))
    assert nav, "nenhum data-route no index.html"
    assert nav <= routes, f"rotas do menu sem renderizador: {sorted(nav - routes)}"
    for fn in re.findall(r":\s*(\w+)\s*,", block.group(1)):
        assert re.search(rf"function {fn}\b", APP_JS), f"renderizador {fn} não definido"


# Ausências conhecidas e aceitas (o JS trata o elemento como opcional).
KNOWN_MISSING_IDS = {
    "nav-badge": "contador do menu removido do HTML no refactor d8cbbe9; updateNavBadge() vira no-op",
}


def test_ids_buscados_por_getElementById_existem_no_html_ou_sao_criados_no_js():
    faltando = []
    for el_id in sorted(set(re.findall(r'getElementById\("([\w-]+)"\)', APP_JS)) - set(KNOWN_MISSING_IDS)):
        if f'id="{el_id}"' in INDEX or f'id="{el_id}"' in APP_JS or f"id = \"{el_id}\"" in APP_JS \
                or f".id = '{el_id}'" in APP_JS or f'.id = "{el_id}"' in APP_JS:
            continue
        faltando.append(el_id)
    assert not faltando, f"getElementById sem elemento correspondente: {faltando}"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js não instalado")
def test_app_js_sem_erro_de_sintaxe():
    proc = subprocess.run(["node", "--check", str(WEB / "app.js")], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_dados_bundled_sao_json_valido():
    erros = []
    for path in sorted((ROOT / "data").glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            erros.append(f"{path.name}: {exc}")
    assert not erros, "\n".join(erros)
