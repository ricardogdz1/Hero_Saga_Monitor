"""QA do armazenamento: dados e imagens no banco SQLite, sempre isolado do banco real."""
import subprocess
import sys

from conftest import HARNESS, ROOT, assert_steps, qa_env


def test_dados_e_imagens_ficam_no_banco(run_scenario):
    assert_steps(run_scenario("storage"))


def test_harness_recusa_rodar_sem_banco_isolado(tmp_path):
    # Regressão: com só HOME isolado, a QA criava o banco real em %LOCALAPPDATA% e
    # marcava a migração como feita — os ~/herosaga_*.json reais nunca seriam importados.
    env = qa_env(tmp_path)
    del env["GDZ_MONITOR_DB"]
    proc = subprocess.run([sys.executable, str(HARNESS), "signatures"], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode != 0
    assert "GDZ_MONITOR_DB" in proc.stderr
    assert not list(tmp_path.rglob("*.db"))
