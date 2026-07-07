"""Testes do parsing de stats de equipamento a partir das descrições dos itens."""
from gdz_monitor.services.build.stats import (
    normalize_base_stats,
    normalize_item_stats,
    parse_item_stats,
    parse_weapon_base,
)


class TestParseItemStats:
    def test_atributos_em_pt_sao_normalizados(self):
        r = parse_item_stats("FOR +5\nDES +10\nSOR +2")
        assert r["primary"]["STR"] == 5
        assert r["primary"]["DEX"] == 10
        assert r["primary"]["LUK"] == 2

    def test_derivados(self):
        r = parse_item_stats("ATQ +30\nMATK +20\nESQUIVA +15")
        assert r["derived_attr"]["ATK"] == 30
        assert r["derived_attr"]["MATK"] == 20
        assert r["derived_attr"]["FLEE"] == 15

    def test_requerimento_nao_conta_como_bonus(self):
        r = parse_item_stats("Requerimento: FOR 50")
        assert r["primary"]["STR"] == 0

    def test_nivel_base_nao_conta_como_bonus(self):
        r = parse_item_stats("Nível Base: DEX 40")
        assert r["primary"]["DEX"] == 0

    def test_bonus_por_refino(self):
        desc = "A cada 2 níveis de refino: ATQ +10"
        sem_refino = parse_item_stats(desc, refine=0)
        com_refino = parse_item_stats(desc, refine=6)
        # o "ATQ +10" literal conta uma vez; o refino soma 10 por cada 2 níveis
        assert sem_refino["derived_attr"]["ATK"] == 10
        assert com_refino["derived_attr"]["ATK"] == 10 + 3 * 10

    def test_descricao_vazia(self):
        r = parse_item_stats("")
        assert all(v == 0 for v in r["primary"].values())


class TestParseWeaponBase:
    def test_atq_base_e_nivel_da_arma(self):
        r = parse_weapon_base("Espada.\nATQ: 150\nNível da arma: 3", refine=4)
        assert r["base_atk"] == 150
        assert r["weapon_level"] == 3
        assert r["refine_atk"] == 8  # +2 por refino até +10
        assert r["ranged"] is False
        assert r["is_shield"] is False

    def test_refino_acima_de_10_escala_mais(self):
        r = parse_weapon_base("ATQ: 100", refine=12)
        assert r["refine_atk"] == 20 + 2 * 3  # 10×2 + 2×3

    def test_arma_de_longo_alcance(self):
        assert parse_weapon_base("Arco Composto\nATQ: 100")["ranged"] is True

    def test_escudo(self):
        r = parse_weapon_base("Escudo de Madeira\nDEF: 50")
        assert r["is_shield"] is True
        assert r["base_atk"] == 0

    def test_bonus_nao_e_confundido_com_base(self):
        # "ATQ +30" é bónus, não ATQ base (exige dois-pontos)
        assert parse_weapon_base("ATQ +30")["base_atk"] == 0


class TestNormalizeBaseStats:
    def test_converte_strings_e_limita_negativos(self):
        r = normalize_base_stats({"primary": {"STR": "5", "AGI": -3}, "talents": {"POW": 2}})
        assert r["primary"]["STR"] == 5
        assert r["primary"]["AGI"] == 0
        assert r["talents"]["POW"] == 2

    def test_entrada_invalida_vira_zeros(self):
        r = normalize_base_stats(None)
        assert all(v == 0 for v in r["primary"].values())
        assert all(v == 0 for v in r["talents"].values())


class TestNormalizeItemStats:
    def test_formato_legado_secondary(self):
        r = normalize_item_stats({"secondary": {"ATK": 10, "POW": 3}})
        assert r["derived_attr"]["ATK"] == 10
        assert r["talents"]["POW"] == 3
