# -*- coding: utf-8 -*-
"""Extrai drops dos .md e gera drops_calculadora.json."""

from __future__ import annotations

import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).parent

MD_FILES = [
    "Cheffenia.md",
    "Tumba_da_Honra.md",
    "Caminho_do_Iniciante.md",
    "Villa_Of_Zeny.md",
    "Ascensao_Somatologica.md",
    "Campo_do_Minerador.md",
    "Jardim_dos_Elementais.md",
    "Jardim_Sagrado.md",
    "Legiao.md",
    "Trilha_do_Heroi.md",
    "Unknow_Blue_Hole.md",
]


def parse_pct(value: str) -> float | None:
    pct, _qty = parse_floor_cell(value)
    return pct


def parse_floor_cell(value: str) -> tuple[float | None, int | None]:
    value = value.strip()
    if not value or value in ("—", "-", "RNG"):
        return None, None
    m = re.search(r"([\d,]+)\s*%", value)
    if m:
        return float(m.group(1).replace(",", ".")), None
    m = re.match(r"^([\d,]+)\s*x\s*$", value, re.I)
    if m:
        return 100.0, int(float(m.group(1).replace(",", ".")))
    if re.match(r"^[\d,]+$", value):
        return float(value.replace(",", ".")), None
    return None, None


def parse_table(lines: list[str]) -> tuple[list[str], list[list[str]]] | None:
    rows = []
    for line in lines:
        line = line.strip()
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(re.match(r"^:?-+:?$", c) for c in cells if c):
            continue
        rows.append(cells)
    if len(rows) < 2:
        return None
    return rows[0], rows[1:]


def parse_chance_columns(headers: list[str]) -> list[str]:
    return [h for h in headers if h.lower() in ("chance",) or "andar" in h.lower()]


def extract_from_md(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    nome = lines[0].lstrip("# ").strip() if lines else path.stem
    conteudo = {"id": path.stem.lower(), "nome": nome, "secoes": []}
    secao_atual = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("## ") or line.startswith("### "):
            secao_atual = line.lstrip("#").strip()
            i += 1
            continue
        if line.strip().startswith("|"):
            if not secao_atual:
                secao_atual = "Geral"
            block = []
            while i < len(lines):
                stripped = lines[i].strip()
                if not stripped:
                    i += 1
                    continue
                if not stripped.startswith("|"):
                    break
                block.append(stripped)
                i += 1
            parsed = parse_table(block)
            if not parsed:
                continue
            headers, data_rows = parsed
            itens = []
            for row in data_rows:
                item = {"secao": secao_atual}
                for j, h in enumerate(headers):
                    if j >= len(row):
                        continue
                    val = row[j]
                    hl = h.lower()
                    if hl == "item":
                        item["nome"] = val
                    elif hl in ("modo", "mapa", "mvp", "tipo do monstro", "tipo"):
                        item["contexto"] = val
                    elif hl == "chance":
                        item["chance_pct"] = parse_pct(val)
                    elif "andar" in hl or hl.endswith("º andar"):
                        pct, qty = parse_floor_cell(val)
                        if pct is not None:
                            item.setdefault("chances_por_andar", {})[h] = pct
                        if qty is not None:
                            item.setdefault("quantidades_por_andar", {})[h] = qty
                    elif j == 0 and "item" not in [x.lower() for x in headers]:
                        item.setdefault("extra", {})[h] = val
                    else:
                        item.setdefault("extra", {})[h] = val
                if "nome" in item or any(k.startswith("chance") for k in item):
                    if "nome" not in item and row:
                        item["nome"] = row[0]
                    for h in headers:
                        if "andar" in h.lower() and h in item.get("extra", {}):
                            pass
                    for j, h in enumerate(headers):
                        if ("andar" in h.lower() or h.lower().endswith("º andar")) and j < len(row):
                            pct, qty = parse_floor_cell(row[j])
                            if pct is not None:
                                item.setdefault("chances_por_andar", {})[h] = pct
                            if qty is not None:
                                item.setdefault("quantidades_por_andar", {})[h] = qty
                    itens.append(item)
            if itens:
                conteudo["secoes"].append({"titulo": secao_atual, "itens": itens})
            continue
        i += 1
    return conteudo


def main() -> None:
    dados = []
    for name in MD_FILES:
        path = BASE_DIR / name
        if path.exists():
            dados.append(extract_from_md(path))
    out = BASE_DIR / "drops_calculadora.json"
    out.write_text(json.dumps({"conteudos": dados}, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(s["itens"]) for c in dados for s in c["secoes"])
    print(f"JSON gerado: {out} ({len(dados)} conteudos, {total} entradas de drop)")


if __name__ == "__main__":
    main()
