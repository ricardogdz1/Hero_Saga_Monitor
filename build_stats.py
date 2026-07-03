"""
Atributos e estatísticas de build (modelo IRO / irowiki.org/wiki/Stats).
Apenas atributos primários e talentos são editáveis pelo utilizador;
as restantes estatísticas vêm do equipamento (descrições dos itens).
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

# Editáveis — janela «Atributos»
PRIMARY_STATS: Tuple[str, ...] = ("STR", "AGI", "VIT", "INT", "DEX", "LUK")

# Editáveis — janela «Talentos»
TALENT_STATS: Tuple[str, ...] = ("POW", "STA", "WIS", "SPL", "CON", "CRT")

# Só leitura — derivadas de «Atributos»
DERIVED_ATTR_STATS: Tuple[str, ...] = ("ATK", "MATK", "HIT", "CRIT", "DEF", "MDEF", "FLEE", "ASPD")

# Só leitura — derivadas de «Talentos»
DERIVED_TALENT_STATS: Tuple[str, ...] = ("PATK", "SMATK", "HPLUS", "CRATE", "RES", "MRES")

ALL_EQUIP_KEYS: Tuple[str, ...] = PRIMARY_STATS + TALENT_STATS + DERIVED_ATTR_STATS + DERIVED_TALENT_STATS

PRIMARY_LABELS_PT: Dict[str, str] = {
    "STR": "Str", "AGI": "Agi", "VIT": "Vit", "INT": "Int", "DEX": "Dex", "LUK": "Luk",
}

TALENT_LABELS_PT: Dict[str, str] = {
    "POW": "Pow", "STA": "Sta", "WIS": "Wis", "SPL": "Spl", "CON": "Con", "CRT": "Crt",
}

DERIVED_ATTR_LABELS: Dict[str, str] = {
    "ATK": "Atk", "MATK": "Matk", "HIT": "Hit", "CRIT": "Critical",
    "DEF": "Def", "MDEF": "Mdef", "FLEE": "Flee", "ASPD": "Aspd",
}

DERIVED_TALENT_LABELS: Dict[str, str] = {
    "PATK": "P.Atk", "SMATK": "S.Matk", "HPLUS": "H.Plus", "CRATE": "C.Rate",
    "RES": "Res", "MRES": "Mres",
}

_ALIAS_TO_KEY: Dict[str, str] = {
    "FOR": "STR", "STR": "STR", "AGI": "AGI", "VIT": "VIT", "INT": "INT",
    "DES": "DEX", "DEX": "DEX", "SOR": "LUK", "LUK": "LUK",
    "POW": "POW", "STA": "STA", "WIS": "WIS", "SPL": "SPL", "CON": "CON",
    "CRT": "CRT", "CRIT": "CRT", "CTR": "CRT",
    "ATQ": "ATK", "ATK": "ATK", "ATQM": "MATK", "MATK": "MATK",
    "DEF": "DEF", "DEFM": "MDEF", "MDEF": "MDEF",
    "ESQUIVA": "FLEE", "FLEE": "FLEE", "EVASAO": "FLEE", "EVASÃO": "FLEE",
    "HIT": "HIT", "PRECISAO": "HIT", "PRECISÃO": "HIT",
    "CRITICAL": "CRIT", "CRÍTICO": "CRIT", "CRITICO": "CRIT",
    "ASPD": "ASPD",
    "P.ATK": "PATK", "P ATK": "PATK", "PATK": "PATK",
    "S.MATK": "SMATK", "S MATK": "SMATK", "SMATK": "SMATK",
    "H.PLUS": "HPLUS", "H PLUS": "HPLUS", "HPLUS": "HPLUS",
    "C.RATE": "CRATE", "C RATE": "CRATE", "CRATE": "CRATE",
    "RES": "RES", "MRES": "MRES",
}

_STAT_BONUS_RE = re.compile(
    r"(?P<key>FOR|STR|AGI|VIT|INT|DES|DEX|SOR|LUK|"
    r"POW|STA|WIS|SPL|CON|CRT|CTR|"
    r"ATQ|ATK|ATQM|MATK|DEF|DEFM|MDEF|"
    r"ESQUIVA|FLEE|EVAS[AÃ]O|HIT|PRECIS[AÃ]O|CR[IÍ]TICO?|CRIT|CRITICAL|ASPD|"
    r"RES|MRES|S\.?\s*MATK|H\.?\s*PLUS|C\.?\s*RATE|P\.?\s*ATK)"
    r"\s*(?:[+:\-]|(?:M[aá]ximo\s*))?\s*(?P<val>-?\d+)",
    re.IGNORECASE,
)


def empty_primary() -> Dict[str, int]:
    return {k: 0 for k in PRIMARY_STATS}


def empty_talents() -> Dict[str, int]:
    return {k: 0 for k in TALENT_STATS}


def empty_derived_attr() -> Dict[str, int]:
    return {k: 0 for k in DERIVED_ATTR_STATS}


def empty_derived_talent() -> Dict[str, int]:
    return {k: 0 for k in DERIVED_TALENT_STATS}


def empty_equipment_stats() -> dict:
    return {
        "primary": empty_primary(),
        "talents": empty_talents(),
        "derived_attr": empty_derived_attr(),
        "derived_talent": empty_derived_talent(),
    }


def default_base_stats() -> dict:
    return {"primary": empty_primary(), "talents": empty_talents()}


def stat_schema() -> dict:
    return {
        "primary": [
            {"key": k, "label": PRIMARY_LABELS_PT.get(k, k), "editable": True}
            for k in PRIMARY_STATS
        ],
        "talents": [
            {"key": k, "label": TALENT_LABELS_PT.get(k, k), "editable": True}
            for k in TALENT_STATS
        ],
        "derived_attr": [
            {"key": k, "label": DERIVED_ATTR_LABELS.get(k, k), "editable": False}
            for k in DERIVED_ATTR_STATS
        ],
        "derived_talent": [
            {"key": k, "label": DERIVED_TALENT_LABELS.get(k, k), "editable": False}
            for k in DERIVED_TALENT_STATS
        ],
    }


def _norm_key(raw: str) -> str | None:
    token = (raw or "").strip().upper().replace("  ", " ")
    token = re.sub(r"\s+", " ", token.replace("P. ATK", "P.ATK").replace("S. MATK", "S.MATK"))
    return _ALIAS_TO_KEY.get(token)


def _bucket_for_key(key: str) -> str | None:
    if key in PRIMARY_STATS:
        return "primary"
    if key in TALENT_STATS:
        return "talents"
    if key in DERIVED_ATTR_STATS:
        return "derived_attr"
    if key in DERIVED_TALENT_STATS:
        return "derived_talent"
    return None


def _apply_to_buckets(buckets: dict, key: str, value: int) -> None:
    b = _bucket_for_key(key)
    if not b:
        return
    buckets[b][key] = buckets[b].get(key, 0) + value


def normalize_item_stats(raw) -> dict:
    """Normaliza stats de item (suporta formato antigo primary/secondary)."""
    out = empty_equipment_stats()
    if not isinstance(raw, dict):
        return out
    if isinstance(raw.get("primary"), dict):
        for k in PRIMARY_STATS:
            try:
                out["primary"][k] = int(float(raw["primary"].get(k) or 0))
            except (TypeError, ValueError):
                pass
    if isinstance(raw.get("talents"), dict):
        for k in TALENT_STATS:
            try:
                out["talents"][k] = int(float(raw["talents"].get(k) or 0))
            except (TypeError, ValueError):
                pass
        for leg_key in ("CRATE", "c_rate"):
            try:
                leg_crate = int(float(raw["talents"].get(leg_key) or 0))
                if leg_crate:
                    out["derived_talent"]["CRATE"] = out["derived_talent"].get("CRATE", 0) + leg_crate
            except (TypeError, ValueError):
                pass
    for dk in ("derived_attr", "derived_talent"):
        if isinstance(raw.get(dk), dict):
            keys = DERIVED_ATTR_STATS if dk == "derived_attr" else DERIVED_TALENT_STATS
            for k in keys:
                try:
                    out[dk][k] = int(float(raw[dk].get(k) or 0))
                except (TypeError, ValueError):
                    pass
    # legado: secondary → derived
    leg = raw.get("secondary")
    if isinstance(leg, dict):
        legacy_map = {
            "ATK": "derived_attr", "MATK": "derived_attr", "DEF": "derived_attr",
            "MDEF": "derived_attr", "HIT": "derived_attr", "CRIT": "derived_attr",
            "FLEE": "derived_attr", "ASPD": "derived_attr",
            "POW": "talents", "PATK": "derived_talent", "HP": None, "SP": None,
        }
        for k, v in leg.items():
            ku = str(k).upper()
            target = legacy_map.get(ku)
            if target == "talents" and ku in TALENT_STATS:
                try:
                    out["talents"][ku] += int(float(v or 0))
                except (TypeError, ValueError):
                    pass
            elif target == "derived_attr" and ku in DERIVED_ATTR_STATS:
                try:
                    out["derived_attr"][ku] += int(float(v or 0))
                except (TypeError, ValueError):
                    pass
            elif target == "derived_talent" and ku in DERIVED_TALENT_STATS:
                try:
                    out["derived_talent"][ku] += int(float(v or 0))
                except (TypeError, ValueError):
                    pass
    return out


def parse_item_stats(description: str, *, refine: int = 0) -> dict:
    """Extrai bónus numéricos da descrição do item."""
    buckets = empty_equipment_stats()
    text = (description or "").replace("\r", "\n")
    if not text.strip():
        return buckets

    for m in _STAT_BONUS_RE.finditer(text):
        try:
            val = int(m.group("val"))
        except (TypeError, ValueError):
            continue
        start = max(0, m.start() - 28)
        ctx = text[start : m.start()].lower()
        if "nível base" in ctx or "nivel base" in ctx or "requerimento" in ctx:
            continue
        if re.search(r"nível\s+da\s+armadura|nivel\s+da\s+armadura|n[ií]vel\s+necess", ctx):
            continue
        key = _norm_key(m.group("key"))
        if key:
            _apply_to_buckets(buckets, key, val)

    per_ref = re.finditer(
        r"(?:para\s+cada|a\s+cada)\s+(\d+)\s+n[ií]ve(?:l|is)\s*(?:de\s+)?refino\s*:?\s*[\s\S]{0,48}?"
        r"(ATQ|ATK|ATQM|MATK|DEF|DEFM|MDEF|FOR|STR)\s*\+\s*(\d+)",
        text,
        re.IGNORECASE,
    )
    ref = max(0, min(20, int(refine or 0)))
    for m in per_ref:
        try:
            step = max(1, int(m.group(1)))
            bonus = int(m.group(3))
        except (TypeError, ValueError):
            continue
        mult = ref // step
        if mult <= 0:
            continue
        key = _norm_key(m.group(2))
        if key:
            _apply_to_buckets(buckets, key, mult * bonus)

    return buckets


def normalize_base_stats(raw) -> dict:
    src = raw if isinstance(raw, dict) else {}
    out_p = empty_primary()
    out_t = empty_talents()
    prim = src.get("primary") if isinstance(src.get("primary"), dict) else {}
    tal = src.get("talents") if isinstance(src.get("talents"), dict) else {}
    # migrar POW de secondary antigo
    leg = src.get("secondary") if isinstance(src.get("secondary"), dict) else {}
    if isinstance(prim, dict):
        for k in PRIMARY_STATS:
            try:
                out_p[k] = max(0, int(float(prim.get(k) or 0)))
            except (TypeError, ValueError):
                out_p[k] = 0
    if isinstance(tal, dict):
        for k in TALENT_STATS:
            try:
                out_t[k] = max(0, int(float(tal.get(k) or 0)))
            except (TypeError, ValueError):
                out_t[k] = 0
    if isinstance(leg, dict) and leg.get("POW"):
        try:
            out_t["POW"] = max(0, int(float(leg.get("POW") or 0)))
        except (TypeError, ValueError):
            pass
    return {"primary": out_p, "talents": out_t}


def sum_stat_dicts(dicts: List[dict]) -> dict:
    out = empty_equipment_stats()
    for d in dicts or []:
        norm = normalize_item_stats(d)
        for bk in ("primary", "talents", "derived_attr", "derived_talent"):
            for k, v in (norm.get(bk) or {}).items():
                try:
                    out[bk][k] = out[bk].get(k, 0) + int(v or 0)
                except (TypeError, ValueError):
                    pass
    return out


def sum_equipment_from_cells(cells: dict, *, layers: Tuple[str, ...] = ("equip", "visual")) -> dict:
    parts: List[dict] = []
    if not isinstance(cells, dict):
        return empty_equipment_stats()
    for layer in layers:
        layer_cells = cells.get(layer)
        if not isinstance(layer_cells, dict):
            continue
        for cell in layer_cells.values():
            if not isinstance(cell, dict):
                continue
            try:
                iid = int(cell.get("item_id") or 0)
            except (TypeError, ValueError):
                iid = 0
            if iid <= 0:
                continue
            st = cell.get("item_stats")
            if isinstance(st, dict):
                parts.append(st)
    return sum_stat_dicts(parts)


def _flo(x) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


_WEAPON_BASE_ATK_RE = re.compile(
    r"(?:ATQ|ATK|Ataque|Attack)\s*[:：]\s*(?P<val>\d+)(?!\s*[+\-])",
    re.IGNORECASE,
)
_WEAPON_BASE_MATK_RE = re.compile(
    r"(?:ATQM|MATK|Ataque\s*M[aá]gico|Magic\s*Attack)\s*[:：]\s*(?P<val>\d+)(?!\s*[+\-])",
    re.IGNORECASE,
)
_RANGED_WEAPON_RE = re.compile(
    r"arco\b|bow\b|rifle\b|pistola\b|rev[oó]lver\b|gun\b|instrumento\b|instrument\b|chicote\b|whip\b|fuzil\b",
    re.IGNORECASE,
)
_SHIELD_RE = re.compile(r"escudo\b|shield\b", re.IGNORECASE)


def parse_weapon_base(description: str, *, refine: int = 0) -> dict:
    """Extrai ATQ/MATK base da arma (não bónus +X) e bónus de refino simplificado."""
    text = (description or "").replace("\r", "\n")
    out = {
        "base_atk": 0,
        "base_matk": 0,
        "weapon_level": 0,
        "ranged": bool(_RANGED_WEAPON_RE.search(text)),
        "is_shield": bool(_SHIELD_RE.search(text)),
    }
    m = _WEAPON_BASE_ATK_RE.search(text)
    if m:
        try:
            out["base_atk"] = int(m.group("val"))
        except (TypeError, ValueError):
            pass
    m = _WEAPON_BASE_MATK_RE.search(text)
    if m:
        try:
            out["base_matk"] = int(m.group("val"))
        except (TypeError, ValueError):
            pass
    wl = re.search(r"(?:N[ií]vel\s+da\s+arma|Weapon\s+Level|N[ií]vel\s+de\s+Arma)\s*[:：]\s*(\d+)", text, re.I)
    if wl:
        try:
            out["weapon_level"] = int(wl.group(1))
        except (TypeError, ValueError):
            pass
    ref = max(0, min(20, int(refine or 0)))
    if out["base_atk"] and ref > 0:
        out["refine_atk"] = ref * 2 if ref <= 10 else 20 + (ref - 10) * 3
    else:
        out["refine_atk"] = 0
    if out["base_matk"] and ref > 0:
        out["refine_matk"] = ref * 2 if ref <= 10 else 20 + (ref - 10) * 3
    else:
        out["refine_matk"] = 0
    return out


def weapon_from_build_cells(cells: dict) -> dict:
    """Arma principal montada na build (mão direita; mão esq. se não for escudo)."""
    equip = cells.get("equip") if isinstance(cells, dict) else {}
    if not isinstance(equip, dict):
        return {"slot": None, "item_id": None, "item_name": "", **parse_weapon_base("")}

    def pick(slot_key: str):
        cell = equip.get(slot_key)
        if not isinstance(cell, dict):
            return None
        try:
            iid = int(cell.get("item_id") or 0)
        except (TypeError, ValueError):
            iid = 0
        if iid <= 0:
            return None
        desc = str(cell.get("item_description") or "")
        ref = int(cell.get("refine") or 0)
        info = parse_weapon_base(desc, refine=ref)
        if info.get("is_shield") and slot_key == "weapon_left":
            return None
        if info["base_atk"] or info["base_matk"]:
            return {
                "slot": slot_key,
                "item_id": iid,
                "item_name": str(cell.get("item_name") or iid),
                **info,
            }
        return None

    right = pick("weapon_right")
    if right:
        return right
    left = pick("weapon_left")
    return left or {"slot": None, "item_id": None, "item_name": "", **parse_weapon_base("")}


def compute_derived_display(
    *,
    character: dict,
    base_stats: dict,
    equip_stats: dict,
    weapon: dict,
    class_info: dict | None = None,
) -> dict:
    """
    Calcula estatísticas derivadas para o painel (modelo IRO simplificado).
    ATK/MATK mostram duas partes: base de nível/stats | arma+equipamento.
    """
    from build_classes import SERVER_LIMITS

    prim = normalize_base_stats(base_stats).get("primary") or empty_primary()
    tal = normalize_base_stats(base_stats).get("talents") or empty_talents()
    eq = normalize_item_stats(equip_stats) if equip_stats else empty_equipment_stats()

    bl = max(1, min(SERVER_LIMITS["max_base_level"], int((character or {}).get("base_level") or 1)))
    str_t = prim["STR"] + eq["primary"]["STR"]
    agi_t = prim["AGI"] + eq["primary"]["AGI"]
    vit_t = prim["VIT"] + eq["primary"]["VIT"]
    int_t = prim["INT"] + eq["primary"]["INT"]
    dex_t = prim["DEX"] + eq["primary"]["DEX"]
    luk_t = prim["LUK"] + eq["primary"]["LUK"]
    pow_t = tal["POW"] + eq["talents"]["POW"]
    sta_t = tal["STA"] + eq["talents"]["STA"]
    wis_t = tal["WIS"] + eq["talents"]["WIS"]
    spl_t = tal["SPL"] + eq["talents"]["SPL"]
    con_t = tal["CON"] + eq["talents"]["CON"]
    crt_t = tal["CRT"] + eq["talents"]["CRT"]

    ranged = bool((weapon or {}).get("ranged"))
    if class_info and class_info.get("weapon_type") == "ranged" and not (weapon or {}).get("base_atk"):
        ranged = True

    if ranged:
        status_atk = _flo(bl / 4) + _flo(str_t / 5) + dex_t + _flo(luk_t / 3)
        stat_for_weapon = dex_t
    else:
        status_atk = _flo(bl / 4) + str_t + _flo(dex_t / 5) + _flo(luk_t / 3)
        stat_for_weapon = str_t

    status_atk += pow_t * 5

    base_w = int((weapon or {}).get("base_atk") or 0)
    ref_w = int((weapon or {}).get("refine_atk") or 0)
    stat_bonus = (base_w * stat_for_weapon) // 200 if base_w else 0
    weapon_atk = base_w + ref_w + stat_bonus

    equip_atk = int(eq["derived_attr"].get("ATK") or 0)

    status_matk = int_t + _flo(_flo(int_t / 7) ** 2) + _flo(dex_t / 5) + _flo(luk_t / 3)
    status_matk += spl_t * 5
    base_m = int((weapon or {}).get("base_matk") or 0)
    ref_m = int((weapon or {}).get("refine_matk") or 0)
    weapon_matk = base_m + ref_m
    equip_matk = int(eq["derived_attr"].get("MATK") or 0)

    soft_def = _flo(vit_t / 2) + agi_t // 5
    hard_def = int(eq["derived_attr"].get("DEF") or 0)
    soft_mdef = int_t + _flo(int_t / 7) + _flo(dex_t / 5)
    hard_mdef = int(eq["derived_attr"].get("MDEF") or 0)

    hit = 175 + bl + dex_t + _flo(luk_t / 3) + 2 * con_t + int(eq["derived_attr"].get("HIT") or 0)
    crit = _flo(luk_t / 3) + int(eq["derived_attr"].get("CRIT") or 0)
    flee = 100 + bl + agi_t + _flo(luk_t / 5) + int(eq["derived_attr"].get("FLEE") or 0)

    # ASPD simplificado — teto Hero 193; base depende da classe (3ª+)
    tier = str((class_info or {}).get("tier_label") or "")
    asp_cap = SERVER_LIMITS["max_aspd"]
    asp_base = 150 if tier in ("3ª", "4ª", "Avanç.", "Exp.+") else 146
    aspd = min(asp_cap, asp_base + _flo(agi_t / 4) + _flo(dex_t / 10) + int(eq["derived_attr"].get("ASPD") or 0))

    patk = _flo(con_t / 5) + int(eq["derived_talent"].get("PATK") or 0)
    smatk = _flo(con_t / 5) + int(eq["derived_talent"].get("SMATK") or 0)
    hplus = crt_t + int(eq["derived_talent"].get("HPLUS") or 0)
    crate = _flo(crt_t / 3) + int(eq["derived_talent"].get("CRATE") or 0)
    res = sta_t + int(eq["derived_talent"].get("RES") or 0)
    mres = wis_t + int(eq["derived_talent"].get("MRES") or 0)

    return {
        "derived_attr": {
            "ATK": {"base": status_atk, "bonus": weapon_atk + equip_atk},
            "MATK": {"base": status_matk, "bonus": weapon_matk + equip_matk},
            "HIT": {"base": hit, "bonus": 0},
            "CRIT": {"base": crit, "bonus": 0},
            "DEF": {"base": soft_def, "bonus": hard_def},
            "MDEF": {"base": soft_mdef, "bonus": hard_mdef},
            "FLEE": {"base": flee, "bonus": 0},
            "ASPD": {"base": aspd, "bonus": 0},
        },
        "derived_talent": {
            "PATK": {"base": patk, "bonus": 0},
            "SMATK": {"base": smatk, "bonus": 0},
            "HPLUS": {"base": hplus, "bonus": 0},
            "CRATE": {"base": crate, "bonus": 0},
            "RES": {"base": res, "bonus": 0},
            "MRES": {"base": mres, "bonus": 0},
        },
        "weapon": {
            "slot": (weapon or {}).get("slot"),
            "item_id": (weapon or {}).get("item_id"),
            "item_name": (weapon or {}).get("item_name") or "",
            "base_atk": base_w,
            "refine_atk": ref_w,
            "stat_bonus": stat_bonus,
            "total_weapon_atk": weapon_atk,
            "base_matk": base_m,
            "ranged": ranged,
        },
    }
