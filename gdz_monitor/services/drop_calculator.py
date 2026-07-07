"""
Calculadora de drop — regras de buffs, CAPs e chance final.

Fórmulas:
- Drops comuns (Tier A/B, equipamentos, etc.):
      chance_final = min(chance_base * (1 + bônus / 100), 100)

- Itens farmáveis de moeda (**Moeda Cheff. Normal** / **Essencia de Bio 5 Normal**):
      chance_final = min(chance_base + bônus, 90%)

Regras de cumulatividade (FUCIONAMENTO DOS BUFFS DE DROPS CON.txt):
- Cálice, Chicle e Goma: não cumulativos entre si → usa o MAIOR do grupo.
- Lata de Comida para Gatos não cumula com Cálice do Elixir Sagrado.
- Demais itens/bônus cumulam entre si.
- Reputação Bio + Cheffênia + Temporada somam entre si.
- Ascensão soma com o restante.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional

from gdz_monitor.core.paths import DATA_DIR as _DATA_DIR
_DROP_MAPS_FILE = os.path.join(_DATA_DIR, "drop_maps.json")
_DROP_BUFF_CATALOG_FILE = os.path.join(_DATA_DIR, "drop_buff_catalog.json")
_DROP_REP_TIERS_FILE = os.path.join(_DATA_DIR, "drop_reputation_tiers.json")
_DROP_PET_GRADES_FILE = os.path.join(_DATA_DIR, "drop_pet_grades.json")
_DROP_BUFF_ICONS_DIR = os.path.join(_DATA_DIR, "drop_buff_icons")
_DROP_ITEM_ID_CACHE_FILE = os.path.join(
    os.path.expanduser("~"), "herosaga_drop_item_id_cache.json"
)
_DROP_ITEM_ID_MAP_FILE = os.path.join(_DATA_DIR, "drop_item_id_map.json")

MEGA_DROP_EXCLUSIVE = frozenset({"calice", "chicle", "goma"})
_MIN_NAME_MATCH_SCORE = 5000

# Itens ocultos na UI por mapa (nome normalizado ou substring).
_MAP_HIDDEN_ITEM_PATTERNS: Dict[str, frozenset] = {
    "ascensao_somatologica": frozenset({"bencao do ferreiro"}),
}

# Bônus de buff por mapa/modo (sobrescreve catálogo global).
_MAP_BUFF_BONUS_PCT: Dict[tuple, float] = {
    ("villa_of_zeny", "fidelizado", "Normal"): 10.0,
}

_CONTEXT_LABELS = (
    ("normal", "Normal"),
    ("intermediate", "Intermediate"),
    ("hard", "Hard"),
    ("extreme", "Extreme"),
    ("unreal", "Unreal"),
    ("savage", "Savage"),
    ("elemental", "Elemental"),
    ("advanced", "Advanced"),
)

_catalog_cache: Optional[dict] = None
_maps_cache: Optional[dict] = None
_tiers_cache: Optional[dict] = None
_pet_grades_cache: Optional[dict] = None
_id_cache: Optional[dict] = None
_id_map_cache: Optional[dict] = None


def _load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_maps_catalog() -> dict:
    global _maps_cache
    if _maps_cache is None:
        _maps_cache = _load_json(_DROP_MAPS_FILE)
    return _maps_cache


def load_buff_catalog_raw() -> dict:
    global _catalog_cache
    if _catalog_cache is None:
        _catalog_cache = _load_json(_DROP_BUFF_CATALOG_FILE)
    return _catalog_cache


def load_reputation_tiers() -> dict:
    global _tiers_cache
    if _tiers_cache is None:
        _tiers_cache = _load_json(_DROP_REP_TIERS_FILE)
    return _tiers_cache


def load_pet_grades() -> dict:
    global _pet_grades_cache
    if _pet_grades_cache is None:
        _pet_grades_cache = _load_json(_DROP_PET_GRADES_FILE)
    return _pet_grades_cache


def normalize_item_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().strip()
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _norm_secao(secao: str) -> str:
    s = unicodedata.normalize("NFKD", str(secao or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower().strip()


def resolve_drop_contexto(contexto: str = "", secao: str = "") -> str:
    """Deriva modo/dificuldade a partir de ``contexto`` ou prefixo da ``secao``."""

    def try_match(text: str) -> str:
        low = _norm_secao(text).replace("\u2014", "-").replace("\u2013", "-")
        if not low:
            return ""
        for prefix, label in _CONTEXT_LABELS:
            if low == prefix or low.startswith(f"{prefix} ") or low.startswith(f"{prefix}-"):
                return label
        return ""

    ctx = try_match(str(contexto or "")) or try_match(str(secao or ""))
    if ctx:
        return ctx
    return str(contexto or "").strip()


def _is_album_item(nome: str) -> bool:
    """Drop do mob: o álbum em si (ex. «Álbum Mágico de Cartas [MVP]»)."""
    nl = normalize_item_name(nome)
    return "album" in nl and "carta" in nl


def is_album_card_drop(item: dict, secao_titulo: str = "") -> bool:
    """Cartas listadas no conteúdo do álbum — vêm do álbum, não do mob."""
    nome = str(item.get("nome") or "").strip()
    if _is_album_item(nome):
        return False
    if item.get("extra", {}).get("Carta"):
        return True
    nl = normalize_item_name(nome)
    if nl.startswith("carta "):
        return True
    secao = _norm_secao(secao_titulo or item.get("secao") or "")
    if "conteudo do album" in secao:
        return True
    return False


def _is_summary_section(titulo: str) -> bool:
    return "resumo geral" in _norm_secao(titulo)


def _is_album_content_section(titulo: str) -> bool:
    return "conteudo do album" in _norm_secao(titulo)


def _is_hidden_map_item(map_id: str, item: dict) -> bool:
    patterns = _MAP_HIDDEN_ITEM_PATTERNS.get(str(map_id or ""))
    if not patterns:
        return False
    nl = normalize_item_name(str(item.get("nome") or ""))
    return any(p in nl for p in patterns)


def filter_mapa_for_display(mapa: dict) -> dict:
    """Remove cartas individuais de álbum; mantém o item «Álbum Mágico…»."""
    out = dict(mapa or {})
    map_id = str(mapa.get("id") or "")
    secoes = []
    for sec in mapa.get("secoes") or []:
        titulo = str(sec.get("titulo") or sec.get("secao") or "")
        if _is_summary_section(titulo):
            continue
        if _is_album_content_section(titulo):
            continue
        itens = [
            it for it in (sec.get("itens") or [])
            if isinstance(it, dict)
            and not is_album_card_drop(it, titulo)
            and not _is_hidden_map_item(map_id, it)
        ]
        if itens:
            secoes.append({**sec, "itens": itens})
    out["secoes"] = secoes
    return out


def lookup_farm_moeda_config(map_id: str, item_nome: str) -> Optional[dict]:
    """Regras de CAP/fórmula — só Moeda Cheff. e Essencia de Bio 5 Normal."""
    key = normalize_item_name(item_nome)
    for row in load_maps_catalog().get("item_chance_caps") or []:
        if str(row.get("map_id") or "") != str(map_id or ""):
            continue
        if normalize_item_name(row.get("item_nome") or "") == key:
            return row
    return None


def lookup_item_chance_cap(map_id: str, item_nome: str) -> Optional[float]:
    cfg = lookup_farm_moeda_config(map_id, item_nome)
    if not cfg:
        return None
    val = cfg.get("chance_cap_pct")
    if val is not None:
        return float(val)
    return None


def lookup_drop_formula(map_id: str, item_nome: str, secao: str = "") -> str:
    cfg = lookup_farm_moeda_config(map_id, item_nome)
    if cfg:
        return str(cfg.get("formula") or "additive")
    return "multiplicative"


def _tier_bonus(track: str, level: int) -> float:
    tiers = load_reputation_tiers().get(track) or {}
    levels = tiers.get("levels") or []
    lv = max(0, min(int(level or 0), int(tiers.get("max_level") or 0)))
    for row in levels:
        if int(row.get("level") or 0) == lv:
            return float(row.get("bonus_pct") or 0)
    return 0.0


def _pet_grade_multiplier(grade_level: int) -> float:
    tiers = load_pet_grades().get("pet_grade") or {}
    levels = tiers.get("levels") or []
    lv = max(0, min(int(grade_level or 0), int(tiers.get("max_level") or 0)))
    for row in levels:
        if int(row.get("level") or 0) == lv:
            return float(row.get("multiplier_pct") or 0)
    return 0.0


def compute_pet_effective_bonus(base_pct: float, grade_level: int) -> float:
    """Bônus efetivo do pet: base * (1 + multiplicador_da_grade / 100)."""
    base = float(base_pct or 0)
    mult = _pet_grade_multiplier(grade_level)
    return round(base * (1.0 + mult / 100.0), 4)


def _pet_buff_ids() -> List[str]:
    out: List[str] = []
    for grupo in load_buff_catalog_raw().get("grupos") or []:
        for buff in grupo.get("buffs") or []:
            if str(buff.get("exclusive_group") or "") == "pet":
                bid = str(buff.get("id") or "")
                if bid:
                    out.append(bid)
    return out


def compute_effective_bonus(
    buffs_state: dict,
    rep_levels: Optional[dict] = None,
    pet_grades: Optional[dict] = None,
    *,
    map_id: str = "",
    contexto: str = "",
) -> dict:
    """
    Calcula bônus total de drop (%).

    ``buffs_state``: {buff_id: bool} para toggles de itens/bônus/pet.
    ``rep_levels``: {track: level} — bio, cheffenia, temporada, ascensao.
    ``pet_grades``: {pet_id: grade_level} — 0=sem grade, 1=D … 4=A.
    """
    rep = rep_levels or {}
    grades = pet_grades or {}
    selected = {str(k): bool(v) for k, v in (buffs_state or {}).items() if v}

    parts: List[dict] = []
    raw_total = 0.0

    mega_vals = []
    for bid in MEGA_DROP_EXCLUSIVE:
        if selected.get(bid):
            pct = _buff_bonus_value(bid, map_id, contexto)
            mega_vals.append((bid, pct))
    if mega_vals:
        best_id, best_pct = max(mega_vals, key=lambda x: x[1])
        raw_total += best_pct
        parts.append({"id": best_id, "bonus_pct": best_pct, "kind": "mega_max"})
        for bid, pct in mega_vals:
            if bid != best_id:
                parts.append({"id": bid, "bonus_pct": 0, "kind": "mega_excluded", "excluded_by": best_id})

    has_calice = selected.get("calice")

    cumulative_ids = (
        "drop_pote", "fusao_pote", "manual_mascar", "po_runas", "pocao_doador",
        "fidelizado", "premium", "bencao_valhalla",
    )
    for bid in cumulative_ids:
        if selected.get(bid):
            pct = _buff_bonus_value(bid, map_id, contexto)
            raw_total += pct
            parts.append({"id": bid, "bonus_pct": pct, "kind": "cumulative"})

    if selected.get("lata_gatos"):
        if has_calice:
            parts.append({"id": "lata_gatos", "bonus_pct": 0, "kind": "blocked", "blocked_by": "calice"})
        else:
            pct = _buff_bonus_value("lata_gatos", map_id, contexto)
            raw_total += pct
            parts.append({"id": "lata_gatos", "bonus_pct": pct, "kind": "cumulative"})

    rep_tracks = (
        ("rep_bio", "bio"),
        ("rep_cheffenia", "cheffenia"),
        ("rep_temporada", "temporada"),
    )
    for buff_id, track in rep_tracks:
        lv = int(rep.get(track) or 0)
        if lv <= 0:
            continue
        pct = _tier_bonus(track, lv)
        raw_total += pct
        parts.append({"id": buff_id, "bonus_pct": pct, "kind": "reputation", "level": lv})

    asc_lv = int(rep.get("ascensao") or 0)
    if asc_lv > 0:
        asc_pct = _tier_bonus("ascensao", asc_lv)
        raw_total += asc_pct
        parts.append({"id": "ascensao", "bonus_pct": asc_pct, "kind": "ascension", "level": asc_lv})

    pet_selected = [bid for bid in _pet_buff_ids() if selected.get(bid)]
    if pet_selected:
        best_id = max(
            pet_selected,
            key=lambda bid: compute_pet_effective_bonus(
                _buff_bonus_value(bid, map_id, contexto),
                int(grades.get(bid) or 0),
            ),
        )
        grade_lv = int(grades.get(best_id) or 0)
        base_pct = _buff_bonus_value(best_id, map_id, contexto)
        pet_pct = compute_pet_effective_bonus(base_pct, grade_lv)
        raw_total += pet_pct
        parts.append({
            "id": best_id,
            "bonus_pct": pet_pct,
            "kind": "pet",
            "grade_level": grade_lv,
            "base_pct": base_pct,
        })
        for bid in pet_selected:
            if bid != best_id:
                parts.append({"id": bid, "bonus_pct": 0, "kind": "pet_excluded", "excluded_by": best_id})

    return {
        "bonus_raw_pct": round(raw_total, 4),
        "bonus_effective_pct": round(raw_total, 4),
        "capped": False,
        "cap_pct": None,
        "contexto_resolved": contexto,
        "parts": parts,
    }


def _map_buff_bonus_pct(map_id: str, buff_id: str, contexto: str) -> Optional[float]:
    key = (str(map_id or ""), str(buff_id or ""), str(contexto or ""))
    if key in _MAP_BUFF_BONUS_PCT:
        return float(_MAP_BUFF_BONUS_PCT[key])
    return None


def _buff_bonus_value(buff_id: str, map_id: str = "", contexto: str = "") -> float:
    override = _map_buff_bonus_pct(map_id, buff_id, contexto)
    if override is not None:
        return override
    return _buff_fixed_bonus(buff_id)


def _buff_fixed_bonus(buff_id: str) -> float:
    for grupo in load_buff_catalog_raw().get("grupos") or []:
        for buff in grupo.get("buffs") or []:
            if str(buff.get("id") or "") == buff_id:
                return float(buff.get("bonus_pct") or 0)
    defaults = {
        "calice": 220, "chicle": 200, "goma": 100,
        "drop_pote": 25, "fusao_pote": 25, "lata_gatos": 20,
        "manual_mascar": 20, "po_runas": 20, "pocao_doador": 35,
        "fidelizado": 20, "premium": 10, "bencao_valhalla": 10,
    }
    return float(defaults.get(buff_id, 0))


def compute_final_chance(
    base_pct: float,
    bonus_effective_pct: float,
    *,
    formula: str = "multiplicative",
    item_chance_cap: Optional[float] = None,
) -> float:
    base = float(base_pct or 0)
    bonus = float(bonus_effective_pct or 0)
    if formula == "additive":
        final = base + bonus
    else:
        final = base * (1.0 + bonus / 100.0)
    if item_chance_cap is not None:
        final = min(final, float(item_chance_cap))
    final = min(final, 100.0)
    return round(final, 6)


def compute_drop_row(
    base_pct: float,
    buffs_state: dict,
    rep_levels: Optional[dict],
    pet_grades: Optional[dict] = None,
    *,
    map_id: str = "",
    contexto: str = "",
    item_nome: str = "",
    secao: str = "",
) -> dict:
    ctx = resolve_drop_contexto(contexto, secao)
    bonus_info = compute_effective_bonus(
        buffs_state, rep_levels, pet_grades, map_id=map_id, contexto=ctx,
    )
    formula = lookup_drop_formula(map_id, item_nome, secao)
    item_cap = lookup_item_chance_cap(map_id, item_nome)
    bonus = bonus_info["bonus_raw_pct"]
    base = float(base_pct or 0)
    if formula == "additive":
        uncapped = base + bonus
    else:
        uncapped = base * (1.0 + bonus / 100.0)
    final_pct = compute_final_chance(
        base_pct,
        bonus,
        formula=formula,
        item_chance_cap=item_cap,
    )
    item_capped = item_cap is not None and uncapped > float(item_cap)
    chance_max_capped = uncapped > 100.0 and final_pct >= 100.0
    return {
        **bonus_info,
        "bonus_effective_pct": round(bonus, 4),
        "capped": False,
        "cap_pct": None,
        "base_pct": base,
        "final_pct": final_pct,
        "formula": formula,
        "item_chance_cap_pct": item_cap,
        "item_capped": item_capped,
        "chance_max_capped": chance_max_capped,
        "contexto": ctx,
    }


def load_drop_item_id_map() -> Dict[str, int]:
    """Mapa estático nome normalizado → item_id (``data/drop_item_id_map.json``)."""
    global _id_map_cache
    if _id_map_cache is not None:
        return _id_map_cache
    out: Dict[str, int] = {}
    if os.path.isfile(_DROP_ITEM_ID_MAP_FILE):
        try:
            with open(_DROP_ITEM_ID_MAP_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                for k, v in raw.items():
                    try:
                        iid = int(v)
                    except (TypeError, ValueError):
                        continue
                    if iid > 0:
                        out[str(k).strip()] = iid
        except Exception:
            pass
    _id_map_cache = out
    return out


_meta_index_cache: Optional[dict] = None


def build_drop_item_meta_index() -> dict:
    """Índice local nome normalizado / item_id → metadados (sem rede)."""
    global _meta_index_cache
    if _meta_index_cache is not None:
        return _meta_index_cache
    from gdz_monitor.external.item_icon_cache import read_cached_icon_data_uri

    static = load_drop_item_id_map()
    by_norm: Dict[str, dict] = {}
    by_id: Dict[int, dict] = {}
    for norm, iid_raw in static.items():
        try:
            iid = int(iid_raw)
        except (TypeError, ValueError):
            continue
        if iid <= 0:
            continue
        row = {"item_id": iid, "icon": read_cached_icon_data_uri(iid)}
        nk = str(norm).strip()
        by_norm[nk] = row
        if iid not in by_id:
            by_id[iid] = row
    _meta_index_cache = {"by_norm": by_norm, "by_id": by_id}
    return _meta_index_cache


def resolve_drop_items_meta_local(
    names: List[str],
    id_hints: Optional[dict] = None,
) -> dict:
    """Resolve ID/ícone apenas com ``drop_item_id_map.json`` + PNGs em disco."""
    index = build_drop_item_meta_index()
    by_norm = index["by_norm"]
    by_id = index["by_id"]
    static = load_drop_item_id_map()
    hints = id_hints or {}
    out: Dict[str, dict] = {}
    for raw_name in names or []:
        name = str(raw_name or "").strip()
        if not name:
            continue
        key = normalize_item_name(name)
        iid = 0
        for raw in (name, key):
            if raw in hints:
                try:
                    iid = int(hints[raw])
                    if iid > 0:
                        break
                except (TypeError, ValueError):
                    pass
        if iid <= 0:
            iid = int(static.get(key) or 0)
        row = by_id.get(iid) if iid > 0 else by_norm.get(key)
        if row:
            out[name] = {
                "item_id": int(row["item_id"]),
                "icon": str(row.get("icon") or ""),
                "name": name,
            }
        else:
            out[name] = {"item_id": 0, "icon": "", "name": name, "not_found": True}
    return out


def _cache_entry_from_item_id(
    item_id: int,
    *,
    display_name: str = "",
    base_url: str = "",
) -> dict:
    from gdz_monitor.core.constants import BASE_URL as _BASE
    from gdz_monitor.external.item_icon_cache import item_icon_disk_path

    iid = int(item_id)
    base = (base_url or _BASE).rstrip("/")
    icon_url = f"{base}/?module=image&action=processicon&id={iid}"
    return {
        "item_id": iid,
        "name": str(display_name or f"Item {iid}").strip(),
        "icon_url": icon_url,
        "icon_ok": os.path.isfile(item_icon_disk_path(iid)),
    }


def _lookup_known_item_id(
    name: str,
    id_hints: Optional[dict],
    static_map: Dict[str, int],
    cache: dict,
) -> Optional[int]:
    """Prioridade: hint do JSON → mapa estático → cache persistente."""
    key = normalize_item_name(name)
    hints = id_hints or {}

    for raw in (name, key):
        if raw in hints:
            try:
                iid = int(hints[raw])
                if iid > 0:
                    return iid
            except (TypeError, ValueError):
                pass

    if key in static_map and int(static_map[key]) > 0:
        return int(static_map[key])

    if key in cache:
        cached = cache[key]
        if cached.get("not_found"):
            return None
        try:
            iid = int(cached.get("item_id") or 0)
        except (TypeError, ValueError):
            iid = 0
        if iid > 0:
            return iid
    return None


def buff_icon_path(icon_file: str) -> str:
    return os.path.join(_DROP_BUFF_ICONS_DIR, str(icon_file or ""))


def load_item_id_cache() -> dict:
    global _id_cache
    if _id_cache is not None:
        return _id_cache
    if os.path.isfile(_DROP_ITEM_ID_CACHE_FILE):
        try:
            with open(_DROP_ITEM_ID_CACHE_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                _id_cache = raw
                return _id_cache
        except Exception:
            pass
    _id_cache = {}
    return _id_cache


_CACHE_FIELDS = frozenset({"item_id", "name", "icon_url", "not_found", "icon_ok", "resolve_by"})


def reload_item_id_cache() -> dict:
    """Recarrega cache do disco (útil entre chamadas API)."""
    global _id_cache
    _id_cache = None
    return load_item_id_cache()


def save_item_id_cache(cache: dict) -> None:
    global _id_cache
    cleaned: Dict[str, dict] = {}
    for key, val in (cache or {}).items():
        if not isinstance(val, dict):
            continue
        row = {k: v for k, v in val.items() if k in _CACHE_FIELDS}
        if "item_id" in row:
            try:
                row["item_id"] = int(row["item_id"] or 0)
            except (TypeError, ValueError):
                row["item_id"] = 0
        cleaned[key] = row
    _id_cache = cleaned
    with open(_DROP_ITEM_ID_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(_id_cache, f, ensure_ascii=False, indent=2)


def _pick_best_search_row(query: str, rows: List[dict]) -> Optional[dict]:
    if not rows:
        return None
    nq = normalize_item_name(query)

    def score(row: dict) -> int:
        name = normalize_item_name(row.get("name") or "")
        if not name:
            return 0
        if name == nq:
            return 10_000
        if name.startswith(nq) or nq.startswith(name):
            return 5_000 - abs(len(name) - len(nq))
        q_tokens = set(nq.split())
        n_tokens = set(name.split())
        if q_tokens and q_tokens <= n_tokens:
            return 3_000 + len(q_tokens) * 10
        overlap = len(q_tokens & n_tokens)
        if overlap >= max(2, len(q_tokens) // 2):
            return 1_000 + overlap * 20
        return overlap * 5

    ranked = sorted(rows, key=score, reverse=True)
    best = ranked[0]
    if score(best) >= _MIN_NAME_MATCH_SCORE:
        return best
    return None


def search_name_variants(raw_name: str) -> List[str]:
    """Gera consultas alternativas (sem [MVP], [1], prefixo 50x, etc.)."""
    name = str(raw_name or "").strip()
    if not name:
        return []
    seen: set[str] = set()
    out: List[str] = []

    def add(s: str) -> None:
        s = str(s or "").strip()
        if not s or s in seen:
            return
        seen.add(s)
        out.append(s)

    add(name)
    no_tag = re.sub(r"\s*\[[^\]]*\]\s*$", "", name).strip()
    add(no_tag)
    no_qty = re.sub(r"^\d+x\s+", "", no_tag, flags=re.IGNORECASE).strip()
    add(no_qty)
    no_lt = re.sub(r"-LT\s*$", "", no_tag, flags=re.IGNORECASE).strip()
    add(no_lt)
    no_lt_qty = re.sub(r"-LT\s*$", "", no_qty, flags=re.IGNORECASE).strip()
    add(no_lt_qty)
    core = re.sub(r"\s*\[[^\]]*\]", "", name).strip()
    add(core)
    return out


def resolve_item_ids(names: List[str], search_fn) -> dict:
    """Legado — preferir ``resolve_drop_items_meta``."""
    return resolve_drop_items_meta(names, search_fn, fetch_url_bytes=None)


def resolve_drop_items_meta(
    names: List[str],
    search_fn,
    fetch_url_bytes=None,
    *,
    base_url: str = "",
    id_hints: Optional[dict] = None,
    dp_search_fn=None,
    hs_by_id_fn=None,
) -> dict:
    """
    Resolve ID + ícone para drops.

    Prioridade de ID: hint → mapa estático → cache → Divine Pride (nome) → Hero (nome).
    Com ID conhecido, metadados/ícone vêm do site Hero por ID (processicon).
    """
    from gdz_monitor.core.constants import BASE_URL as _BASE
    from gdz_monitor.external.item_icon_cache import (
        fetch_icons_batch,
        item_icon_disk_path,
        read_cached_icon_data_uri,
    )

    base = (base_url or _BASE).rstrip("/")
    static_map = load_drop_item_id_map()
    cache = reload_item_id_cache()
    out: Dict[str, dict] = {}
    need_icon_pairs: Dict[int, str] = {}
    dirty = False

    def _row(name: str, entry: dict, *, cached_id: bool = False) -> dict:
        iid = int(entry.get("item_id") or 0)
        icon_url = str(entry.get("icon_url") or "")
        icon_uri = read_cached_icon_data_uri(iid) if iid > 0 else ""
        if iid > 0 and icon_uri:
            key = normalize_item_name(name)
            if key in cache and not cache[key].get("icon_ok"):
                cache[key]["icon_ok"] = True
                nonlocal dirty
                dirty = True
        row = {
            "item_id": iid,
            "name": str(entry.get("name") or name),
            "icon_url": icon_url,
            "icon": icon_uri or "",
            "cached_id": cached_id,
            "cached_icon": bool(icon_uri),
            "not_found": bool(entry.get("not_found")),
            "resolve_by": str(entry.get("resolve_by") or ""),
        }
        if iid > 0 and not icon_uri:
            need_icon_pairs[iid] = icon_url or f"{base}/?module=image&action=processicon&id={iid}"
        return row

    to_search: List[str] = []

    for raw_name in names or []:
        name = str(raw_name or "").strip()
        if not name:
            continue
        key = normalize_item_name(name)

        known_id = _lookup_known_item_id(name, id_hints, static_map, cache)
        if known_id:
            if key in cache and int(cache[key].get("item_id") or 0) == known_id:
                entry = dict(cache[key])
                entry.setdefault("resolve_by", "cache")
            else:
                entry = _cache_entry_from_item_id(
                    known_id, display_name=name, base_url=base,
                )
                if (id_hints or {}).get(name) or (id_hints or {}).get(key):
                    entry["resolve_by"] = "hint"
                elif key in static_map:
                    entry["resolve_by"] = "static"
                else:
                    entry["resolve_by"] = "cache"
                cache[key] = entry
                dirty = True
            out[name] = _row(name, entry, cached_id=True)
            continue

        if key in cache and cache[key].get("not_found") and not dp_search_fn:
            entry = dict(cache[key])
            entry["resolve_by"] = "not_found"
            out[name] = _row(name, entry, cached_id=True)
            continue

        to_search.append(name)

    def _entry_from_id_match(
        name: str,
        iid: int,
        *,
        display_name: str = "",
        icon_url: str = "",
        resolve_by: str,
    ) -> dict:
        if not icon_url:
            icon_url = f"{base}/?module=image&action=processicon&id={iid}"
        return {
            "item_id": iid,
            "name": str(display_name or name),
            "icon_url": icon_url,
            "icon_ok": os.path.isfile(item_icon_disk_path(iid)),
            "resolve_by": resolve_by,
        }

    def _hs_meta_for_id(iid: int) -> dict:
        if not hs_by_id_fn or iid <= 0:
            return {}
        try:
            raw = hs_by_id_fn(iid)
        except Exception:
            return {}
        if isinstance(raw, list):
            return raw[0] if raw else {}
        if isinstance(raw, dict):
            return raw
        return {}

    for name in to_search:
        key = normalize_item_name(name)
        best = None
        resolve_by = "not_found"

        if dp_search_fn:
            for variant in search_name_variants(name):
                dp_rows = dp_search_fn(variant) or []
                if not dp_rows:
                    continue
                candidate = _pick_best_search_row(name, dp_rows)
                if candidate and int(candidate.get("id") or candidate.get("item_id") or 0) > 0:
                    best = candidate
                    resolve_by = "divine_pride"
                    break

        if not best:
            for variant in search_name_variants(name):
                rows = search_fn(variant) or []
                if not rows:
                    continue
                candidate = _pick_best_search_row(name, rows)
                if candidate and int(candidate.get("id") or candidate.get("item_id") or 0) > 0:
                    best = candidate
                    resolve_by = "name_search"
                    break

        if best:
            iid = int(best.get("id") or best.get("item_id") or 0)
            hs_meta = _hs_meta_for_id(iid) if resolve_by == "divine_pride" else {}
            if not hs_meta and resolve_by == "name_search":
                hs_meta = best
            icon_url = str(
                hs_meta.get("icon_url")
                or hs_meta.get("item_icon_url")
                or best.get("icon_url")
                or best.get("item_icon_url")
                or ""
            )
            display_name = str(
                hs_meta.get("name")
                or best.get("name")
                or name
            )
            entry = _entry_from_id_match(
                name,
                iid,
                display_name=display_name,
                icon_url=icon_url,
                resolve_by=resolve_by,
            )
            cache[key] = entry
            dirty = True
            out[name] = _row(name, entry, cached_id=False)
        else:
            cache[key] = {
                "item_id": 0,
                "name": name,
                "icon_url": "",
                "not_found": True,
                "icon_ok": False,
                "resolve_by": "not_found",
            }
            dirty = True
            out[name] = _row(name, cache[key], cached_id=False)

    if dirty:
        save_item_id_cache(cache)

    if need_icon_pairs and fetch_url_bytes is not None:
        pairs = [(iid, url) for iid, url in need_icon_pairs.items() if iid > 0]
        icons_map = fetch_icons_batch(
            pairs,
            fetch_url_bytes,
            base_url=base,
            max_workers=6,
        ) if pairs else {}

        dirty_icons = False
        for name, row in out.items():
            iid = int(row.get("item_id") or 0)
            if iid <= 0 or row.get("icon"):
                continue
            uri = icons_map.get(iid) or read_cached_icon_data_uri(iid)
            if uri:
                row["icon"] = uri
                row["cached_icon"] = True
                key = normalize_item_name(name)
                if key in cache:
                    cache[key]["icon_ok"] = True
                    dirty_icons = True
        if dirty_icons:
            save_item_id_cache(cache)

    return out
