"""
Testes da calculadora de drop.

As regras vêm de docs/instrucoes_calculadora_drop/ — estes testes transformam
aquela documentação em verificação executável. Os valores dos buffs vêm de
data/drop_buff_catalog.json (bundled), por isso os testes de exclusividade
verificam a *estrutura* do resultado em vez de percentuais fixos.
"""
from gdz_monitor.services.drop_calculator import (
    compute_effective_bonus,
    compute_final_chance,
    compute_pet_effective_bonus,
    normalize_item_name,
)


class TestNormalizeItemName:
    def test_remove_acentos_pontuacao_e_espacos(self):
        assert normalize_item_name("  Álbum Mágico!  ") == "album magico"
        assert normalize_item_name("Cálice do Elixir Sagrado") == "calice do elixir sagrado"

    def test_vazio(self):
        assert normalize_item_name(None) == ""


class TestComputeFinalChance:
    def test_formula_multiplicativa(self):
        # 10% de base com +50% de bônus → 15%
        assert compute_final_chance(10, 50) == 15.0

    def test_formula_aditiva(self):
        assert compute_final_chance(10, 50, formula="additive") == 60.0

    def test_cap_por_item(self):
        assert compute_final_chance(10, 100, item_chance_cap=15) == 15.0

    def test_nunca_passa_de_100(self):
        assert compute_final_chance(80, 300) == 100.0

    def test_sem_bonus(self):
        assert compute_final_chance(5, 0) == 5.0


class TestComputePetEffectiveBonus:
    def test_sem_grade_mantem_base(self):
        assert compute_pet_effective_bonus(10, 0) == 10.0

    def test_grade_maior_nunca_reduz(self):
        base = 10.0
        anterior = compute_pet_effective_bonus(base, 0)
        for grade in (1, 2, 3, 4):
            atual = compute_pet_effective_bonus(base, grade)
            assert atual >= anterior
            anterior = atual


class TestComputeEffectiveBonus:
    def test_sem_nada_selecionado(self):
        r = compute_effective_bonus({})
        assert r["bonus_raw_pct"] == 0
        assert r["parts"] == []

    def test_mega_drops_sao_exclusivos_vale_o_maior(self):
        # Cálice, Chicle e Goma são exclusivos entre si: só o maior conta
        r = compute_effective_bonus({"calice": True, "chicle": True, "goma": True})
        kinds = [p["kind"] for p in r["parts"]]
        assert kinds.count("mega_max") == 1
        assert kinds.count("mega_excluded") == 2
        vencedor = next(p for p in r["parts"] if p["kind"] == "mega_max")
        assert r["bonus_raw_pct"] == vencedor["bonus_pct"]

    def test_lata_de_gatos_bloqueada_pelo_calice(self):
        r = compute_effective_bonus({"calice": True, "lata_gatos": True})
        lata = next(p for p in r["parts"] if p["id"] == "lata_gatos")
        assert lata["kind"] == "blocked"
        assert lata["bonus_pct"] == 0

    def test_lata_de_gatos_sozinha_conta(self):
        r = compute_effective_bonus({"lata_gatos": True})
        lata = next(p for p in r["parts"] if p["id"] == "lata_gatos")
        assert lata["kind"] == "cumulative"
        assert lata["bonus_pct"] > 0

    def test_buffs_cumulativos_somam(self):
        r = compute_effective_bonus({"drop_pote": True, "premium": True})
        soma = sum(p["bonus_pct"] for p in r["parts"])
        assert r["bonus_raw_pct"] == round(soma, 4)
        assert len(r["parts"]) == 2

    def test_reputacao_entra_no_total(self):
        sem_rep = compute_effective_bonus({})
        com_rep = compute_effective_bonus({}, rep_levels={"bio": 3})
        assert com_rep["bonus_raw_pct"] >= sem_rep["bonus_raw_pct"]
        if com_rep["bonus_raw_pct"] > 0:
            rep_part = next(p for p in com_rep["parts"] if p["kind"] == "reputation")
            assert rep_part["level"] == 3
