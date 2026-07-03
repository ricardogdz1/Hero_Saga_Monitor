"""Gera ``data/drop_*`` a partir de ``Instrucoes_calculadora_drop/``."""
from __future__ import annotations

import json
import os
import shutil

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "Instrucoes_calculadora_drop")
_DATA = os.path.join(_ROOT, "data")
_ICONS_SRC = os.path.join(_SRC, "Icones")
_ICONS_DST = os.path.join(_DATA, "drop_buff_icons")


def _find_icon(*prefixes: str) -> str:
    if not os.path.isdir(_ICONS_SRC):
        return ""
    names = os.listdir(_ICONS_SRC)
    for pref in prefixes:
        for name in names:
            if name.lower().startswith(pref.lower()) and name.lower().endswith(".png"):
                return name
    return ""


def main() -> None:
    os.makedirs(_ICONS_DST, exist_ok=True)

    with open(os.path.join(_SRC, "drops_calculadora.json"), encoding="utf-8") as f:
        maps_data = json.load(f)

    maps_data["item_chance_caps"] = [
        {
            "map_id": "cheffenia",
            "item_nome": "Moeda Cheff. Normal",
            "chance_cap_pct": 90,
            "formula": "additive",
            "nota": "Farmável: base + bônus, chance final máx. 90%",
        },
        {
            "map_id": "tumba_da_honra",
            "item_nome": "Essencia de Bio 5 Normal",
            "chance_cap_pct": 90,
            "formula": "additive",
            "nota": "Farmável: base + bônus, chance final máx. 90%",
        },
    ]
    with open(os.path.join(_DATA, "drop_maps.json"), "w", encoding="utf-8") as f:
        json.dump(maps_data, f, ensure_ascii=False, indent=2)

    buff_catalog = {
        "grupos": [
            {
                "id": "itens",
                "label": "Itens",
                "buffs": [
                    {"id": "calice", "nome": "Cálice do Elixir Sagrado", "bonus_pct": 220, "icon_file": "Cálice do Elixir Sagrado.png", "exclusive_group": "mega_drop", "blocks": ["lata_gatos"]},
                    {"id": "chicle", "nome": "Chicle de Bola", "bonus_pct": 200, "icon_file": "Chicle de Bola.png", "exclusive_group": "mega_drop"},
                    {"id": "goma", "nome": "Goma de Mascar", "bonus_pct": 100, "icon_file": "Goma de Mascar.png", "exclusive_group": "mega_drop"},
                    {"id": "drop_pote", "nome": "Drop em Pote", "bonus_pct": 25, "icon_file": "Drop em Pote.png"},
                    {"id": "fusao_pote", "nome": "Fusão em Pote", "bonus_pct": 25, "icon_file": "Fusão em Pote.png"},
                    {"id": "lata_gatos", "nome": "Lata de Comida para Gatos", "bonus_pct": 20, "icon_file": "Lata de Comida para Gatos.png", "blocked_by": ["calice"]},
                    {"id": "manual_mascar", "nome": "Manual de Mascar", "bonus_pct": 20, "icon_file": "Manual de Mascar.png"},
                    {"id": "po_runas", "nome": "Pó de Runas", "bonus_pct": 20, "icon_file": "Pó de Runas.png"},
                    {"id": "pocao_doador", "nome": "Poção do Doador", "bonus_pct": 35, "icon_file": "Poção do Doador.png"},
                ],
            },
            {
                "id": "bonus",
                "label": "Bônus",
                "buffs": [
                    {"id": "fidelizado", "nome": "Fidelizado Hero Academy", "bonus_pct": 20, "icon_file": "Fidelizado Hero Academy.png"},
                    {"id": "premium", "nome": "Premium", "bonus_pct": 10, "icon_file": "Premium.png"},
                    {"id": "bencao_valhalla", "nome": "Benção de Valhalla", "bonus_pct": 10, "icon_file": "Benção de Valhalla.png"},
                ],
            },
            {
                "id": "reputacao",
                "label": "Reputação / Ascensão",
                "buffs": [
                    {"id": "rep_bio", "nome": "Reputação Bio", "icon_file": "Reputação Bio.png", "tier_track": "bio"},
                    {"id": "rep_cheffenia", "nome": "Reputação Cheffênia", "icon_file": "Reputação Cheffenia.png", "tier_track": "cheffenia"},
                    {"id": "rep_temporada", "nome": "Reputação Temporada", "icon_file": "Reputação Temporada.png", "tier_track": "temporada"},
                    {"id": "ascensao", "nome": "Ascensão", "icon_file": _find_icon("Ascen", "Ascens"), "tier_track": "ascensao"},
                ],
            },
            {
                "id": "pet",
                "label": "Pet",
                "buffs": [
                    {"id": f"pet_{pct}", "nome": f"Pet {pct}%", "bonus_pct": pct, "icon_file": f"Pet {pct}%.png", "exclusive_group": "pet", "grade_track": "pet_grade"}
                    for pct in (10, 15, 20, 25, 30, 35, 40, 50)
                ],
            },
        ]
    }
    with open(os.path.join(_DATA, "drop_buff_catalog.json"), "w", encoding="utf-8") as f:
        json.dump(buff_catalog, f, ensure_ascii=False, indent=2)

    rep_tiers = {
        "bio": {
            "nome": "Reputação Bio (Bio 5 Hard)",
            "max_level": 3,
            "bonus_per_level_pct": 2,
            "levels": [
                {"level": 0, "bonus_pct": 0, "label": "Nível 0"},
                {"level": 1, "bonus_pct": 2, "label": "Nível 1 (+2% drop)"},
                {"level": 2, "bonus_pct": 4, "label": "Nível 2 (+4% drop)"},
                {"level": 3, "bonus_pct": 6, "label": "Nível 3 (+6% drop)"},
            ],
        },
        "cheffenia": {
            "nome": "Reputação Cheffênia (Hard)",
            "max_level": 3,
            "bonus_per_level_pct": 2,
            "levels": [
                {"level": 0, "bonus_pct": 0, "label": "Nível 0"},
                {"level": 1, "bonus_pct": 2, "label": "Nível 1 (+2% drop)"},
                {"level": 2, "bonus_pct": 4, "label": "Nível 2 (+4% drop)"},
                {"level": 3, "bonus_pct": 6, "label": "Nível 3 (+6% drop)"},
            ],
        },
        "temporada": {
            "nome": "Reputação Temporada",
            "max_level": 4,
            "bonus_per_level_pct": 2,
            "levels": [
                {"level": 0, "bonus_pct": 0, "label": "Nível 0"},
                {"level": 1, "bonus_pct": 2, "label": "Nível 1 (+2% drop)"},
                {"level": 2, "bonus_pct": 4, "label": "Nível 2 (+4% drop)"},
                {"level": 3, "bonus_pct": 6, "label": "Nível 3 (+6% drop)"},
                {"level": 4, "bonus_pct": 8, "label": "Nível 4 (+8% drop)"},
            ],
        },
        "ascensao": {
            "nome": "Ascensão",
            "max_level": 15,
            "bonus_per_level_pct": 4,
            "levels": [
                {"level": lv, "bonus_pct": lv * 4, "label": f"Nível {lv} (+{lv * 4}% drop)" if lv else "Nível 0"}
                for lv in range(16)
            ],
        },
    }
    with open(os.path.join(_DATA, "drop_reputation_tiers.json"), "w", encoding="utf-8") as f:
        json.dump(rep_tiers, f, ensure_ascii=False, indent=2)

    pet_grades = {
        "pet_grade": {
            "nome": "Grade do Pet",
            "max_level": 4,
            "levels": [
                {"level": 0, "grade": "", "multiplier_pct": 0, "label": "Sem grade"},
                {"level": 1, "grade": "D", "multiplier_pct": 40, "label": "Grade D (+40% sobre o pet)"},
                {"level": 2, "grade": "C", "multiplier_pct": 80, "label": "Grade C (+80% sobre o pet)"},
                {"level": 3, "grade": "B", "multiplier_pct": 100, "label": "Grade B (+100% sobre o pet)"},
                {"level": 4, "grade": "A", "multiplier_pct": 150, "label": "Grade A (+150% sobre o pet)"},
            ],
        },
    }
    with open(os.path.join(_DATA, "drop_pet_grades.json"), "w", encoding="utf-8") as f:
        json.dump(pet_grades, f, ensure_ascii=False, indent=2)

    id_map_path = os.path.join(_DATA, "drop_item_id_map.json")
    if not os.path.isfile(id_map_path):
        with open(id_map_path, "w", encoding="utf-8") as f:
            json.dump({}, f)

    if os.path.isdir(_ICONS_SRC):
        for name in os.listdir(_ICONS_SRC):
            if name.lower().endswith(".png"):
                shutil.copy2(os.path.join(_ICONS_SRC, name), os.path.join(_ICONS_DST, name))

    print("OK:", _DATA)


if __name__ == "__main__":
    main()
