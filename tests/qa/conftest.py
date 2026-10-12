"""Infra da suíte de QA: executa ``_harness.py`` em subprocesso isolado."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).with_name("_harness.py")


def qa_env(home: Path) -> dict:
    """Ambiente do harness: HOME, LOCALAPPDATA e banco SQLite dentro de *home* (nunca os reais)."""
    return {**os.environ, "USERPROFILE": str(home), "HOME": str(home), "LOCALAPPDATA": str(home),
            "GDZ_MONITOR_DB": str(home / "gdz_monitor.db"),
            "GDZ_QA_HOME": str(home), "PYTHONIOENCODING": "utf-8"}


@pytest.fixture(scope="session")
def run_scenario(tmp_path_factory):
    """Roda um cenário do harness com HOME/banco temporários e devolve o JSON resultante."""
    cache: dict = {}

    def _run(name: str) -> dict:
        if name in cache:
            return cache[name]
        home = tmp_path_factory.mktemp(f"qa_home_{name}")
        env = qa_env(home)
        proc = subprocess.run(
            [sys.executable, str(HARNESS), name],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300,
        )
        marker = next((ln for ln in proc.stdout.splitlines() if ln.startswith("@@QA@@")), None)
        if proc.returncode != 0 or marker is None:
            pytest.fail(f"harness '{name}' falhou (exit {proc.returncode}):\n{proc.stderr[-3000:]}")
        cache[name] = json.loads(marker[len("@@QA@@"):])
        return cache[name]

    return _run


def assert_steps(result: dict) -> None:
    """Falha listando todos os passos com problema (não só o primeiro)."""
    failed = [s for s in result.get("steps") or [] if s.get("fail")]
    if failed:
        lines = [f"- {s['label']}: {s['fail']}" + (f"\n{s['trace']}" if s.get("trace") else "") for s in failed]
        pytest.fail(f"{len(failed)} passo(s) de QA falharam:\n" + "\n".join(lines))
