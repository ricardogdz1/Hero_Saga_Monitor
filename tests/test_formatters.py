"""Testes de formatação de preços e nomes exibidos na UI."""
from gdz_monitor.services.market.formatters import (
    clean_shop_name,
    fmt_price,
    fmt_price_stores,
    item_emoji,
    safe_get,
)


class TestFmtPrice:
    def test_milhar_com_ponto(self):
        assert fmt_price(1_500_000) == "1.500.000"
        assert fmt_price(999) == "999"

    def test_nao_numerico_volta_como_string(self):
        assert fmt_price("abc") == "abc"


class TestFmtPriceStores:
    def test_inteiro_agrupa_milhares(self):
        assert fmt_price_stores(1500) == "1.500"
        assert fmt_price_stores(1500.0) == "1.500"

    def test_decimal_preserva_casas_sem_agrupar(self):
        assert fmt_price_stores(12.5) == "12.5"
        assert fmt_price_stores("12,5") == "12.5"

    def test_none_vira_zero(self):
        assert fmt_price_stores(None) == "0"


class TestItemEmoji:
    def test_categorias_conhecidas(self):
        assert item_emoji("Espada Longa") == "⚔"
        assert item_emoji("Carta Poring") == "🃏"
        assert item_emoji("Poção Vermelha") == "🧪"
        assert item_emoji("Escudo de Madeira") == "🛡"

    def test_vazio_e_desconhecido(self):
        assert item_emoji("") == "📦"
        assert item_emoji("Coisa Aleatória") == "🗡"


class TestCleanShopName:
    def test_remove_caracteres_especiais_e_espacos(self):
        assert clean_shop_name("  Loja   do  Zé!!") == "Loja do Zé"

    def test_nome_invalido_vira_shop(self):
        assert clean_shop_name("") == "Shop"
        assert clean_shop_name("!@#$%") == "Shop"


class TestSafeGet:
    def test_valor_presente(self):
        assert safe_get({"a": 1}, "a") == "1"

    def test_ausente_ou_none_usa_default(self):
        assert safe_get({}, "x") == "N/A"
        assert safe_get({"a": None}, "a") == "N/A"
        assert safe_get({}, "x", "-") == "-"
