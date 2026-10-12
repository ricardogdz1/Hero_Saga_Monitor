"""Harness de QA: exercita a classe ``Api`` real num processo isolado.

Executado em subprocesso pelos testes de ``tests/qa`` (nunca importar no
processo do pytest): o caminho do banco (``core/database.py``) e os ``~/herosaga_*.json``
antigos (migração) são resolvidos no import, por isso o ambiente temporário precisa
estar definido antes de importar o pacote.

Garantias do ambiente:
- ``USERPROFILE``/``HOME``/``LOCALAPPDATA`` apontam para um diretório temporário (passado pelo teste);
- ``GDZ_MONITOR_DB`` aponta para um banco dentro desse diretório — o banco real nunca é tocado;
- rede bloqueada (``socket.connect`` levanta ``OSError``) — nada sai da máquina;
- worker de alertas não é iniciado (sem e-mails nem threads).

Uso: python tests/qa/_harness.py <cenário>   → imprime JSON após ``@@QA@@``.
"""
from __future__ import annotations

import inspect
import json
import logging
import os
import socket
import sys
import threading
import time
import traceback
from io import BytesIO

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

if not os.environ.get("GDZ_QA_HOME"):
    sys.exit("GDZ_QA_HOME não definido — o harness só roda com HOME isolado.")
_qa_home = os.path.abspath(os.environ["GDZ_QA_HOME"])
_qa_db = os.path.abspath(os.environ.get("GDZ_MONITOR_DB") or "")
if not os.environ.get("GDZ_MONITOR_DB") or os.path.dirname(_qa_db) != _qa_home:
    sys.exit("GDZ_MONITOR_DB deve apontar para um banco dentro de GDZ_QA_HOME — o harness não usa o banco real.")


def _no_network(*_a, **_k):
    raise OSError("rede bloqueada no QA")


socket.socket.connect = _no_network  # type: ignore[assignment]
logging.disable(logging.CRITICAL)

import gdz_monitor.app.api as api_mod  # noqa: E402
from gdz_monitor.core import database as _database  # noqa: E402

if os.path.abspath(_database.DB_FILE) != _qa_db:
    sys.exit(f"banco fora do QA: {_database.DB_FILE}")

_orig_worker = api_mod.get_alert_worker


def _idle_worker(*a, **k):
    w = _orig_worker(*a, **k)
    w.start = lambda *a, **k: None
    return w


api_mod.get_alert_worker = _idle_worker


def _safe_json(value):
    """Garante que a resposta atravessa a ponte JS (JSON estrito, sem NaN)."""
    json.dumps(value, allow_nan=False)
    return value


class Recorder:
    def __init__(self) -> None:
        self.steps: list[dict] = []

    def call(self, label: str, fn, *, expect_ok: bool | None = True):
        entry: dict = {"label": label}
        try:
            res = fn()
            _safe_json(res)
            entry["ok"] = res.get("ok") if isinstance(res, dict) else None
            entry["error"] = res.get("error") if isinstance(res, dict) else None
            if expect_ok is True and entry["ok"] is False:
                entry["fail"] = f"esperado ok, veio erro: {entry['error']}"
            if expect_ok is False and entry["ok"] is not False:
                entry["fail"] = "esperado ok=False (validação), veio sucesso"
            self.steps.append(entry)
            return res
        except Exception as exc:  # noqa: BLE001
            entry["fail"] = f"exceção {type(exc).__name__}: {exc}"
            entry["trace"] = traceback.format_exc()[-1200:]
            self.steps.append(entry)
            return None

    def check(self, label: str, cond: bool, detail: str = "") -> None:
        self.steps.append({"label": label, **({} if cond else {"fail": detail or "condição falsa"})})


# ── Cenários ──────────────────────────────────────────────────────────────


def scenario_signatures() -> dict:
    """Assinaturas públicas da Api (para validar chamadas do app.js)."""
    out = {}
    for name, fn in inspect.getmembers(api_mod.Api, inspect.isfunction):
        if name.startswith("_"):
            continue
        target = inspect.unwrap(fn)
        # decorators sem functools.wraps (ex.: _catch_herosaga_auth): original no closure
        if target.__code__.co_name == "wrapper" and target.__closure__:
            target = next(
                (c.cell_contents for c in target.__closure__ if inspect.isfunction(c.cell_contents)),
                target,
            )
        params = list(inspect.signature(target).parameters.values())[1:]
        positional = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        out[name] = {
            "required": sum(1 for p in positional if p.default is p.empty),
            "max": len(positional),
            "varargs": any(p.kind == p.VAR_POSITIONAL for p in params),
        }
    return {"signatures": out}


def scenario_smoke() -> dict:
    """Fluxos principais de cada página, com dados válidos e inválidos."""
    api = api_mod.Api()
    r = Recorder()

    # Leitura de todas as páginas (o que a UI chama ao abrir cada rota)
    for label in (
        "get_settings", "get_home", "get_monitored_list", "get_searches", "get_alerts",
        "loot_get", "build_meta", "build_list", "mvp_check_spawns", "my_shops_list",
        "drop_calc_get_catalog", "drop_calc_get_buff_catalog", "drop_calc_get_state",
        "drop_calc_get_item_meta",
    ):
        r.call(label, getattr(api, label))
    r.call("get_alert_notifications", lambda: api.get_alert_notifications(False, 50))
    r.call("mvp_cards todos", lambda: api.mvp_cards("todos", ""))
    r.call("mvp_cards ativos", lambda: api.mvp_cards("ativos", ""))
    r.call("mvp_cards busca", lambda: api.mvp_cards("todos", "baphomet"))

    # Home: categorias e itens
    r.call("add_category", lambda: api.add_category("QA Categoria"))
    home = r.call("get_home após add_category", api.get_home)
    r.check("categoria criada aparece na Home", "QA Categoria" in json.dumps(home, ensure_ascii=False))
    r.call("add_category vazia rejeitada", lambda: api.add_category("   "), expect_ok=False)
    r.call("add_item", lambda: api.add_item({"id": 501, "name": "Poção Vermelha", "category": "QA Categoria",
                                            "item_icon_url": "x", "prices": {"zeny": 50}}))
    r.check("item adicionado está monitorado",
            any(int(m.get("id", 0)) == 501 for m in api_mod.load_data().get("monitored") or []))
    r.call("add_item duplicado rejeitado", lambda: api.add_item({"id": 501, "name": "x", "item_icon_url": "x"}),
           expect_ok=False)
    r.call("place_item", lambda: api.place_item(501, "Gerais", 0), expect_ok=None)
    r.call("remove_item", lambda: api.remove_item(501), expect_ok=None)
    r.check("item removido", not any(int(m.get("id", 0)) == 501 for m in api_mod.load_data().get("monitored") or []))
    r.call("remove_category", lambda: api.remove_category("QA Categoria"), expect_ok=None)

    # Alertas (sem rede: cria com preços vazios)
    r.call("add_alert", lambda: api.add_alert({"item_id": 501, "name": "Poção Vermelha", "price": 100,
                                              "sale_type": "zeny"}))
    r.call("add_alert refino inválido", lambda: api.add_alert({"item_id": 501, "price": 1, "refinement": "21"}),
           expect_ok=False)
    r.call("add_alert valor zero", lambda: api.add_alert({"item_id": 501, "price": 0}), expect_ok=False)
    alerts = r.call("get_alerts após add", api.get_alerts) or {}
    r.check("alerta criado", alerts.get("total") == 1, f"total={alerts.get('total')}")
    for it in alerts.get("items") or []:
        r.call(f"remove_alert {it.get('key')}", lambda k=it.get("key"): api.remove_alert(k))
    r.call("mark_alert_notifications_read", lambda: api.mark_alert_notifications_read(None), expect_ok=None)

    # Auto Loot
    g = r.call("loot_add_group", api.loot_add_group) or {}
    num = (g.get("groups") or [{}])[-1].get("number", 1)
    r.call("loot_rename", lambda: api.loot_rename(num, "QA Grupo"))
    r.call("loot_add", lambda: api.loot_add(num, {"id": 4001, "name": "Carta Poring"}))
    r.call("loot_remove", lambda: api.loot_remove(num, 4001))
    r.call("loot_delete_group", lambda: api.loot_delete_group(num))

    # Build
    saved = r.call("build_save", lambda: api.build_save({"name": "QA build", "cells": {}, "stats": {}})) or {}
    bid = saved.get("id")
    r.check("build_save devolve id", bool(bid))
    if bid:
        r.call("build_load", lambda: api.build_load(bid))
        r.call("build_set_primary", lambda: api.build_set_primary(bid))
        r.call("build_delete", lambda: api.build_delete(bid))
    r.call("build_load inexistente", lambda: api.build_load("nao-existe"), expect_ok=False)
    r.call("build_resolve texto rejeitado", lambda: api.build_resolve("Carta Poring", 0), expect_ok=False)
    r.call("build_prices vazio", lambda: api.build_prices({}, 0))

    # Calc. Drop — todos os mapas abrem e todas as linhas calculam
    cat = api.drop_calc_get_catalog() or {}
    for c in cat.get("conteudos") or []:
        mid = c.get("id")
        res = r.call(f"drop_calc_get_map {mid}", lambda m=mid: api.drop_calc_get_map(m)) or {}
        rows = [it for s in (res.get("mapa") or {}).get("secoes") or [] for it in s.get("itens") or []]
        r.check(f"mapa {mid} tem itens", len(rows) > 0)
        for it in rows:
            pct = it.get("chance_pct")
            if pct is None:
                continue
            calc = api.drop_calc_compute(pct, {}, {}, {}, mid, it.get("contexto") or "", it.get("nome") or "", "")
            if not calc.get("ok") or not (0 <= float(calc.get("final_pct", -1)) <= 100):
                r.check(f"drop {mid}/{it.get('nome')}", False, json.dumps(calc, ensure_ascii=False)[:300])
                break
    r.call("drop_calc_compute base inválida", lambda: api.drop_calc_compute("abc", {}, {}, {}), expect_ok=False)
    st = api.drop_calc_get_state()
    r.call("drop_calc_save_state", lambda: api.drop_calc_save_state(st))

    # Minhas Lojas — validações sem rede
    r.call("my_shops_add vazio", lambda: api.my_shops_add(""), expect_ok=False)
    r.call("my_shops_detail inexistente", lambda: api.my_shops_detail("999"), expect_ok=False)
    r.call("my_shops_set_cost inexistente", lambda: api.my_shops_set_cost("999", "k", 10), expect_ok=False)

    r.call("ping", api.ping, expect_ok=None)
    return {"steps": r.steps}


def scenario_concurrency() -> dict:
    """Edições feitas durante atualizações longas (rede lenta) não podem se perder."""
    api = api_mod.Api()
    r = Recorder()

    def slow_stores(iid, name="", force_refresh=False):
        time.sleep(0.05)
        return [{"price": 100, "sale_type": "zeny"}], {}

    api_mod.get_stores_from_item_page = slow_stores
    api_mod._collect_history_if_monitored = lambda iid: None

    data = api_mod.load_data()
    data["monitored"] = [{"id": 900 + i, "name": f"Item QA {i}", "category": "Gerais"} for i in range(10)]
    api_mod.save_data(data)

    t = threading.Thread(target=api.refresh_prices)
    t.start()
    time.sleep(0.15)
    api.add_category("QA Durante Refresh")
    t.join()
    after = api_mod.load_data()
    r.check("categoria criada durante refresh_prices sobrevive",
            "QA Durante Refresh" in (after.get("monitor_categories") or []))
    r.check("refresh_prices gravou os preços",
            all((m.get("min_prices") or {}) for m in after.get("monitored") or []))

    import gdz_monitor.services.market.vendor_shop as vs

    def slow_shop(vid, force_refresh=False):
        time.sleep(0.3)
        return {"ok": True, "vendor_name": "QA", "items": [{"item_id": 501, "name": "Poção", "amount": 3, "price": 10}]}

    vs.fetch_vendor_shop = slow_shop
    data = api_mod.load_data()
    data["my_shops"] = [{"vendor_id": 777, "costs": {}, "baseline": {"items": []}, "last_snapshot": {"items": []}}]
    api_mod.save_data(data)
    t = threading.Thread(target=api.my_shops_refresh)
    t.start()
    time.sleep(0.1)
    api.add_category("QA Durante Lojas")
    t.join()
    r.check("categoria criada durante my_shops_refresh sobrevive",
            "QA Durante Lojas" in (api_mod.load_data().get("monitor_categories") or []))
    return {"steps": r.steps}


def scenario_storage() -> dict:
    """Dados e imagens do programa vão para o banco SQLite; JSON antigos do HOME são migrados."""
    import glob
    import sqlite3

    from PIL import Image

    from gdz_monitor.external import item_icon_cache
    from gdz_monitor.services import mvp_timer

    r = Recorder()
    # Banco novo + ficheiro antigo no HOME → simula a primeira abertura após a atualização
    _database.close()
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(_qa_db + suffix):
            os.remove(_qa_db + suffix)
    with open(os.path.join(_qa_home, "herosaga_monitor_data.json"), "w", encoding="utf-8") as f:
        json.dump({"monitored": [{"id": 909, "name": "Item Antigo", "category": "Gerais"}], "searches": []}, f)

    api = api_mod.Api()
    r.check("JSON antigo migrado para o banco",
            any(int(m.get("id", 0)) == 909 for m in api_mod.load_data().get("monitored") or []))
    r.call("add_category", lambda: api.add_category("QA Banco"))
    r.call("loot_get", api.loot_get)
    r.call("build_list", api.build_list)

    png = BytesIO()
    Image.new("RGBA", (24, 24), (200, 30, 30, 255)).save(png, format="PNG")
    r.call("gravar ícone de item", lambda: item_icon_cache._save_icon_png(501, Image.open(BytesIO(png.getvalue()))))
    r.call("gravar imagem de mob", lambda: mvp_timer.write_mob_image_cache(1038, png.getvalue()))

    conn = sqlite3.connect(_qa_db)
    try:
        docs = dict(conn.execute("SELECT key, value FROM documents").fetchall())
        imgs = set(conn.execute("SELECT namespace, key FROM images").fetchall())
    finally:
        conn.close()
    r.check("monitorados gravados no banco", "QA Banco" in docs.get(_database.DOC_MONITOR_DATA, ""),
            f"documentos: {sorted(docs)}")
    r.check("ícone de item gravado no banco", (_database.IMG_ITEM_ICON, "501") in imgs, f"imagens: {sorted(imgs)}")
    r.check("imagem de mob gravada no banco", (_database.IMG_MOB, "1038") in imgs, f"imagens: {sorted(imgs)}")
    r.check("ícone lido de volta do banco",
            item_icon_cache.read_cached_icon_data_uri(501).startswith("data:image/png;base64,"))
    r.check("mob lido de volta do banco", mvp_timer.read_mob_image_cache(1038) == png.getvalue())
    home_files = sorted(os.path.basename(p) for p in glob.glob(os.path.join(_qa_home, "herosaga_*.json")))
    r.check("nenhum ficheiro de dados novo no HOME (original antigo preservado)",
            home_files == ["herosaga_monitor_data.json"], f"ficheiros: {home_files}")
    return {"steps": r.steps}


SCENARIOS = {
    "signatures": scenario_signatures,
    "smoke": scenario_smoke,
    "concurrency": scenario_concurrency,
    "storage": scenario_storage,
}

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    result = SCENARIOS[name]()
    print("@@QA@@" + json.dumps(result, ensure_ascii=False, default=str))
