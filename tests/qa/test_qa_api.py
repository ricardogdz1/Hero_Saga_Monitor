"""QA ponta a ponta da camada Api (o que a UI chama), isolado de disco real e rede."""
from conftest import assert_steps


def test_fluxos_de_todas_as_paginas(run_scenario):
    assert_steps(run_scenario("smoke"))


def test_edicoes_durante_atualizacao_longa_nao_se_perdem(run_scenario):
    # Regressão: refresh_prices/my_shops_refresh regravavam o arquivo inteiro
    # após minutos de rede, apagando edições feitas nesse intervalo.
    assert_steps(run_scenario("concurrency"))
