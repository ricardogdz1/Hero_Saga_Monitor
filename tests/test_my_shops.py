"""Testes das regras puras de "Minhas Lojas" (baseline × snapshot, vendas e lucro)."""

from gdz_monitor.services.market.my_shops import (
    diff_shop,
    item_key,
    parse_vendor_ref,
    shop_summary,
    snapshot_from_shop,
)


def loja(itens) -> dict:
    return {"ok": True, "items": itens}


def linha(item_id=501, nome="Poção Vermelha", qtd=10, preco="1.500", refino=0, **extra) -> dict:
    base = {
        "item_id": item_id,
        "item_name": nome,
        "icon_url": "",
        "refinement": refino,
        "slot1": "",
        "slot2": "",
        "slot3": "",
        "slot4": "",
        "random_options": "",
        "price_text": preco,
        "quantity": qtd,
    }
    base.update(extra)
    return base


class TestParseVendorRef:
    def test_id_puro(self):
        assert parse_vendor_ref("123") == 123
        assert parse_vendor_ref(" 45 ") == 45

    def test_link_viewshop(self):
        url = "https://herosaga.com.br/?module=vending&action=viewshop&id=789"
        assert parse_vendor_ref(url) == 789

    def test_invalido(self):
        assert parse_vendor_ref("") is None
        assert parse_vendor_ref(None) is None
        assert parse_vendor_ref("0") is None
        assert parse_vendor_ref("minha loja") is None
        assert parse_vendor_ref("?module=vending&action=viewshop") is None


class TestItemKey:
    def test_refino_diferente_gera_chave_diferente(self):
        a = linha(refino=0)
        b = linha(refino=7)
        assert item_key(a) != item_key(b)

    def test_preco_diferente_gera_chave_diferente(self):
        a = linha(preco="1.500")
        b = linha(preco="2.000")
        assert item_key(a) != item_key(b)

    def test_carta_diferente_gera_chave_diferente(self):
        a = linha(slot1="Carta Poring")
        b = linha(slot1="Carta Lunatic")
        assert item_key(a) != item_key(b)

    def test_slot_vazio_normalizado(self):
        a = linha(slot1="Nenhum")
        b = linha(slot1="")
        assert item_key(a) == item_key(b)


class TestSnapshotFromShop:
    def test_converte_preco_texto_em_numero(self):
        snap = snapshot_from_shop(loja([linha(preco="350.000", qtd=3)]))
        (entry,) = snap["items"].values()
        assert entry["unit_price"] == 350000.0
        assert entry["quantity"] == 3

    def test_linhas_iguais_somam_quantidade(self):
        snap = snapshot_from_shop(loja([linha(qtd=4), linha(qtd=6)]))
        assert len(snap["items"]) == 1
        (entry,) = snap["items"].values()
        assert entry["quantity"] == 10

    def test_loja_vazia(self):
        snap = snapshot_from_shop(loja([]))
        assert snap["items"] == {}


class TestDiffShop:
    def test_venda_parcial(self):
        base = snapshot_from_shop(loja([linha(qtd=10, preco="1.000")]))
        atual = snapshot_from_shop(loja([linha(qtd=7, preco="1.000")]))
        d = diff_shop(base, atual)
        (row,) = d["rows"]
        assert row["sold_qty"] == 3
        assert row["current_qty"] == 7
        assert row["revenue"] == 3000.0
        assert d["totals"]["pct_sold"] == 0.3

    def test_item_removido_vendeu_tudo(self):
        base = snapshot_from_shop(loja([linha(qtd=5, preco="2.000")]))
        atual = snapshot_from_shop(loja([]))
        d = diff_shop(base, atual)
        (row,) = d["rows"]
        assert row["sold_qty"] == 5
        assert row["current_qty"] == 0
        assert row["revenue"] == 10000.0
        assert d["totals"]["pct_sold"] == 1.0

    def test_reposicao_nao_conta_venda_negativa(self):
        base = snapshot_from_shop(loja([linha(qtd=5)]))
        atual = snapshot_from_shop(loja([linha(qtd=12)]))
        d = diff_shop(base, atual)
        (row,) = d["rows"]
        assert row["sold_qty"] == 0
        assert row["restocked"] is True
        assert d["totals"]["restocked_any"] is True

    def test_item_novo_marcado(self):
        base = snapshot_from_shop(loja([linha(qtd=5)]))
        atual = snapshot_from_shop(loja([linha(qtd=5), linha(item_id=502, nome="Elu", qtd=3)]))
        d = diff_shop(base, atual)
        novo = next(r for r in d["rows"] if r["item_id"] == 502)
        assert novo["new_item"] is True
        assert novo["sold_qty"] == 0
        assert d["totals"]["restocked_any"] is True

    def test_lucro_com_custo(self):
        base = snapshot_from_shop(loja([linha(qtd=10, preco="1.000")]))
        atual = snapshot_from_shop(loja([linha(qtd=4, preco="1.000")]))
        key = next(iter(base["items"]))
        d = diff_shop(base, atual, costs={key: 600})
        (row,) = d["rows"]
        assert row["sold_qty"] == 6
        assert row["cost_spent"] == 3600.0
        assert row["profit"] == 6000.0 - 3600.0
        assert d["totals"]["profit"] == 2400.0
        assert d["totals"]["has_costs"] is True

    def test_sem_custo_lucro_indefinido_na_linha(self):
        base = snapshot_from_shop(loja([linha(qtd=10)]))
        atual = snapshot_from_shop(loja([linha(qtd=8)]))
        d = diff_shop(base, atual)
        (row,) = d["rows"]
        assert row["unit_cost"] is None
        assert row["profit"] is None
        assert d["totals"]["has_costs"] is False
        # sem custos, "lucro" total = arrecadado
        assert d["totals"]["profit"] == d["totals"]["revenue"]

    def test_refinos_diferentes_sao_linhas_distintas(self):
        base = snapshot_from_shop(loja([
            linha(item_id=1101, nome="Espada", qtd=1, refino=7, preco="900.000"),
            linha(item_id=1101, nome="Espada", qtd=1, refino=9, preco="5.000.000"),
        ]))
        atual = snapshot_from_shop(loja([
            linha(item_id=1101, nome="Espada", qtd=1, refino=9, preco="5.000.000"),
        ]))
        d = diff_shop(base, atual)
        assert len(d["rows"]) == 2
        vendida = next(r for r in d["rows"] if r["refinement"] == 7)
        restante = next(r for r in d["rows"] if r["refinement"] == 9)
        assert vendida["sold_qty"] == 1
        assert vendida["revenue"] == 900000.0
        assert restante["sold_qty"] == 0

    def test_baseline_vazio(self):
        d = diff_shop({}, {})
        assert d["rows"] == []
        assert d["totals"]["pct_sold"] == 0.0


class TestShopSummary:
    def test_resumo_usa_ultimo_snapshot(self):
        base = snapshot_from_shop(loja([linha(qtd=10, preco="1.000")]))
        atual = snapshot_from_shop(loja([linha(qtd=2, preco="1.000")]))
        entry = {
            "vendor_id": 42,
            "char_name": "MeuChar",
            "shop_title": "Vendo barato",
            "currency": "zeny",
            "status": "open",
            "baseline": base,
            "last_snapshot": atual,
            "costs": {},
        }
        s = shop_summary(entry)
        assert s["vendor_id"] == 42
        assert s["totals"]["sold_qty"] == 8
        assert s["totals"]["revenue"] == 8000.0
        # o card mostra os itens direto — o resumo tem de trazer as linhas
        assert len(s["items"]) == 1
        assert s["items"][0]["item_name"] == "Poção Vermelha"
        assert s["items"][0]["sold_qty"] == 8
        assert s["items"][0]["current_qty"] == 2

    def test_sem_snapshot_usa_baseline(self):
        base = snapshot_from_shop(loja([linha(qtd=10)]))
        entry = {"vendor_id": 1, "baseline": base, "costs": {}}
        s = shop_summary(entry)
        assert s["totals"]["sold_qty"] == 0
        assert s["totals"]["current_qty"] == 10
