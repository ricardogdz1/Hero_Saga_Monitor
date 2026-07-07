"""
Testes de parse de preços vindos do site (formatos BR, US e mistos).

Cada formato estranho que o site já apresentou deve virar um caso aqui —
assim uma regressão no parser é detectada antes de chegar na Home/alertas.
"""
import pytest

from gdz_monitor.services.market.price_parse import coerce_price, parse_price_cell


class TestParsePriceCell:
    @pytest.mark.parametrize("texto, esperado", [
        # Milhar BR (ponto)
        ("350.000", 350_000.0),
        ("1.500", 1_500.0),
        ("1.234.567", 1_234_567.0),
        # Milhar US (vírgula)
        ("225,000", 225_000.0),
        ("1,234,567", 1_234_567.0),
        # Decimais
        ("12,5", 12.5),
        ("12.99", 12.99),
        # Mistos (milhar + decimal)
        ("1.234.567,89", 1_234_567.89),
        ("1,234,567.89", 1_234_567.89),
        # Sem separador
        ("350000", 350_000.0),
        ("0", 0.0),
    ])
    def test_formatos_numericos(self, texto, esperado):
        assert parse_price_cell(texto) == esperado

    @pytest.mark.parametrize("texto, esperado", [
        ("R$ 1.500", 1_500.0),
        ("350.000 z", 350_000.0),
        ("  225,000 Hero Points ", 225_000.0),
    ])
    def test_ignora_moeda_e_texto_ao_redor(self, texto, esperado):
        assert parse_price_cell(texto) == esperado

    @pytest.mark.parametrize("texto", ["", "   ", None, "abc", "R$"])
    def test_entrada_vazia_ou_sem_digitos_vira_zero(self, texto):
        assert parse_price_cell(texto) == 0.0


class TestCoercePrice:
    def test_numeros_passam_direto(self):
        assert coerce_price(150) == 150.0
        assert coerce_price(12.5) == 12.5

    def test_strings_usam_o_parser(self):
        assert coerce_price("350.000") == 350_000.0
        assert coerce_price("225,000") == 225_000.0

    def test_vazios_viram_zero(self):
        assert coerce_price(None) == 0.0
        assert coerce_price("") == 0.0
