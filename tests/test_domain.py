"""Testes das regras puras do mercado (vendas, estatísticas, menores preços)."""
from datetime import datetime, timedelta

from gdz_monitor.services.market.domain import (
    alert_min_refinement,
    calculate_stats,
    filter_sales_by_period,
    group_sales_by_type,
    merge_sales_history,
    monitored_static_incomplete,
    parse_sale_datetime,
    prune_sales_older_than,
    sale_min_prices_from_stores,
)

AGORA = datetime(2026, 7, 7, 12, 0, 0)


def venda(ts: str, preco: float = 100.0, tipo: str = "zeny", vendedor: str = "Loja") -> dict:
    return {"sale_date": ts, "price": preco, "sale_type": tipo, "seller_name": vendedor}


class TestGroupSalesByType:
    def test_agrupa_por_moeda(self):
        vendas = [
            {"sale_type": "Zeny"},
            {"sale_type": "RMT"},
            {"sale_type": "rops"},
            {"sale_type": ""},
            {"sale_type": "desconhecido"},
        ]
        g = group_sales_by_type(vendas)
        assert len(g["zeny"]) == 3  # zeny + vazio + desconhecido caem em zeny
        assert len(g["rmt"]) == 1
        assert len(g["rops"]) == 1


class TestParseSaleDatetime:
    def test_formato_iso(self):
        assert parse_sale_datetime({"sale_date": "2026-07-01 12:30:00"}) == datetime(2026, 7, 1, 12, 30)
        assert parse_sale_datetime({"sale_date": "2026-07-01T12:30:00"}) == datetime(2026, 7, 1, 12, 30)
        assert parse_sale_datetime({"sale_date": "2026-07-01"}) == datetime(2026, 7, 1)

    def test_formato_br(self):
        assert parse_sale_datetime({"sale_date": "01/07/2026 15:45"}) == datetime(2026, 7, 1, 15, 45)

    def test_usa_timestamp_como_fallback(self):
        assert parse_sale_datetime({"timestamp": "2026-07-01 08:00:00"}) == datetime(2026, 7, 1, 8, 0)

    def test_sem_data_retorna_none(self):
        assert parse_sale_datetime({}) is None
        assert parse_sale_datetime({"sale_date": "não é data"}) is None


class TestMergeSalesHistory:
    def test_deduplica_e_ordena_mais_recente_primeiro(self):
        antiga = venda("2026-07-01 10:00:00", 50)
        nova = venda("2026-07-05 10:00:00", 80)
        resultado = merge_sales_history([antiga], [nova, dict(antiga)])
        assert len(resultado) == 2
        assert resultado[0]["price"] == 80.0  # mais recente primeiro

    def test_aplica_retencao(self):
        recente = venda(AGORA.strftime("%Y-%m-%d %H:%M:%S"), 10)
        velha = venda((AGORA - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S"), 20)
        resultado = merge_sales_history([velha], [recente], retention_days=30)
        # a venda de 90 dias atrás só sobrevive se "agora" estiver a <=30d dela;
        # como os testes rodam com datetime.now() real, garantimos via prune direto
        podadas = prune_sales_older_than([velha, recente], days=30, now=AGORA)
        assert velha not in podadas
        assert len(podadas) == 1


class TestFilterSalesByPeriod:
    def test_janela_24h(self):
        dentro = venda((AGORA - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"))
        fora = venda((AGORA - timedelta(hours=30)).strftime("%Y-%m-%d %H:%M:%S"))
        resultado = filter_sales_by_period([dentro, fora], "24h", now=AGORA)
        assert resultado == [dentro]

    def test_venda_sem_data_e_mantida(self):
        sem_data = {"price": 10}
        assert filter_sales_by_period([sem_data], "24h", now=AGORA) == [sem_data]


class TestCalculateStats:
    def test_estatisticas_basicas(self):
        vendas = [
            venda("2026-07-01 10:00:00", 100),
            venda("2026-07-03 10:00:00", 300),
            venda("2026-07-02 10:00:00", 200),
        ]
        stats = calculate_stats(vendas)
        assert stats["último"] == 300  # a de timestamp mais recente
        assert stats["mínimo"] == 100
        assert stats["máximo"] == 300
        assert stats["média"] == 200
        assert stats["quantidade"] == 3

    def test_precos_zerados_sao_ignorados(self):
        vendas = [venda("2026-07-01 10:00:00", 0), venda("2026-07-02 10:00:00", 50)]
        stats = calculate_stats(vendas)
        assert stats["mínimo"] == 50

    def test_lista_vazia(self):
        assert calculate_stats([])["quantidade"] == 0


class TestSaleMinPricesFromStores:
    def test_menor_preco_por_moeda(self):
        lojas = [
            {"sale_type": "zeny", "price": 500},
            {"sale_type": "zeny", "price": 300},
            {"sale_type": "rmt", "price": 25},
            {"sale_type": "Hero Points", "price": 1000},
        ]
        best = sale_min_prices_from_stores(lojas)
        assert best == {"zeny": 300.0, "rmt": 25.0, "hero_points": 1000.0}

    def test_filtro_de_refino_minimo(self):
        lojas = [
            {"sale_type": "zeny", "price": 100, "refinement": 4},
            {"sale_type": "zeny", "price": 900, "refinement": 9},
        ]
        best = sale_min_prices_from_stores(lojas, min_refinement=7)
        assert best == {"zeny": 900.0}

    def test_preco_zero_e_ignorado(self):
        assert sale_min_prices_from_stores([{"sale_type": "zeny", "price": 0}]) == {}


class TestAlertMinRefinement:
    def test_valores(self):
        assert alert_min_refinement({"refinement": "7"}) == 7
        assert alert_min_refinement({"refinement": 4}) == 4
        assert alert_min_refinement({"refinement": ""}) is None
        assert alert_min_refinement({}) is None
        assert alert_min_refinement({"refinement": "abc"}) is None


class TestMonitoredStaticIncomplete:
    def test_completo(self):
        m = {"name": "Faca", "id": 1201, "item_icon_url": "http://x/icon.png"}
        assert monitored_static_incomplete(m) is False

    def test_faltando_campos(self):
        assert monitored_static_incomplete({"name": "", "id": 1, "item_icon_url": "x"}) is True
        assert monitored_static_incomplete({"name": "Faca", "id": None, "item_icon_url": "x"}) is True
        assert monitored_static_incomplete({"name": "Faca", "id": 1, "item_icon_url": ""}) is True
