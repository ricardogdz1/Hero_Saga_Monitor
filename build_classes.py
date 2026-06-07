"""
Catálogo de classes Hero Saga / IRO (Episode 21).
Referências: https://wiki.herosaga.com.br/index.php/Classes
             https://irowiki.org/wiki/Classes
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

SERVER_LIMITS: Dict[str, int] = {
    "max_base_level": 275,
    "max_job_level": 65,
    "max_primary_stat": 130,
    "max_talent_stat": 110,
    "max_aspd": 193,
}

# (branch_id, branch_name, weapon_type, [(tier_label, name), ...])
_CLASS_ROWS: Tuple[Tuple[str, str, str, Tuple[Tuple[str, str], ...]], ...] = (
    ("swordman", "Espadachim", "melee", (
        ("Inicial", "Aprendiz"),
        ("1ª", "Espadachim"),
        ("2ª", "Cavaleiro"),
        ("Trans.", "Lorde Cavaleiro"),
        ("3ª", "Cavaleiro Rúnico"),
        ("4ª", "Cavaleiro Dragão"),
    )),
    ("merchant", "Mercador", "melee", (
        ("1ª", "Mercador"),
        ("2ª", "Ferreiro"),
        ("Trans.", "Mestre Ferreiro"),
        ("3ª", "Mecânico"),
        ("4ª", "Maestro"),
    )),
    ("mage", "Mago", "melee", (
        ("1ª", "Mago"),
        ("2ª", "Bruxo"),
        ("Trans.", "Arquimag"),
        ("3ª", "Warlock"),
        ("4ª", "Arquimag Arcano"),
    )),
    ("acolyte", "Noviço", "melee", (
        ("1ª", "Noviço"),
        ("2ª", "Sacerdote"),
        ("Trans.", "Sumo Sacerdote"),
        ("3ª", "Arcebispo"),
        ("4ª", "Cardeal"),
    )),
    ("archer", "Arqueiro", "ranged", (
        ("1ª", "Arqueiro"),
        ("2ª", "Caçador"),
        ("Trans.", "Atirador de Elite"),
        ("3ª", "Sentinela"),
        ("4ª", "Caçador de Ventos"),
    )),
    ("thief", "Gatuno", "melee", (
        ("1ª", "Gatuno"),
        ("2ª", "Assassino"),
        ("Trans.", "Assassino da Lâmina"),
        ("3ª", "Sicário"),
        ("4ª", "Shadow Cross"),
    )),
    ("taekwon", "Taekwon", "melee", (
        ("Exp.", "Taekwon"),
        ("2ª", "Taekwon Master"),
        ("3ª", "Star Emperor"),
        ("3ª", "Soul Reaper"),
    )),
    ("ninja", "Ninja", "melee", (
        ("Exp.", "Ninja"),
        ("3ª", "Kagerou"),
        ("3ª", "Oboro"),
        ("4ª", "Shinkiro"),
        ("4ª", "Shiranui"),
    )),
    ("gunslinger", "Atirador", "ranged", (
        ("Exp.", "Atirador"),
        ("2ª", "Rebellion"),
        ("3ª", "Night Watch"),
    )),
    ("super_novice", "Super Aprendiz", "melee", (
        ("Exp.", "Super Aprendiz"),
        ("Exp.+", "Super Aprendiz Expandido"),
        ("4ª", "Hyper Novice"),
    )),
    ("summoner", "Summoner", "melee", (
        ("Inicial", "Summoner"),
        ("Avanç.", "Summoner Avançado"),
        ("4ª", "Spirit Handler"),
    )),
)


def _slug(branch: str, name: str) -> str:
    base = name.lower()
    for ch, rep in (
        ("á", "a"), ("à", "a"), ("ã", "a"), ("â", "a"),
        ("é", "e"), ("ê", "e"), ("í", "i"), ("ó", "o"),
        ("ô", "o"), ("õ", "o"), ("ú", "u"), ("ç", "c"),
    ):
        base = base.replace(ch, rep)
    safe = "".join(c if c.isalnum() else "_" for c in base).strip("_")
    return f"{branch}_{safe}"


def class_catalog() -> List[dict]:
    out: List[dict] = []
    for branch_id, branch_name, weapon_type, rows in _CLASS_ROWS:
        for tier_label, name in rows:
            cid = _slug(branch_id, name)
            out.append({
                "id": cid,
                "name": name,
                "branch": branch_id,
                "branch_name": branch_name,
                "tier_label": tier_label,
                "weapon_type": weapon_type,
                "label": f"{name} ({tier_label} — {branch_name})",
            })
    return out


def class_by_id(class_id: str) -> Optional[dict]:
    cid = str(class_id or "").strip()
    if not cid:
        return None
    for row in class_catalog():
        if row["id"] == cid:
            return row
    return None


def default_character() -> dict:
    rows = class_catalog()
    preferred = "swordman_cavaleiro_dragao"
    cid = preferred if any(r["id"] == preferred for r in rows) else (rows[0]["id"] if rows else "")
    return {"class_id": cid, "base_level": 275, "job_level": 65}


def normalize_character(raw) -> dict:
    out = default_character()
    if not isinstance(raw, dict):
        return out
    cid = str(raw.get("class_id") or "").strip()
    if cid and class_by_id(cid):
        out["class_id"] = cid
    try:
        bl = int(raw.get("base_level") or out["base_level"])
        out["base_level"] = max(1, min(SERVER_LIMITS["max_base_level"], bl))
    except (TypeError, ValueError):
        pass
    try:
        jl = int(raw.get("job_level") or out["job_level"])
        out["job_level"] = max(1, min(SERVER_LIMITS["max_job_level"], jl))
    except (TypeError, ValueError):
        pass
    return out
