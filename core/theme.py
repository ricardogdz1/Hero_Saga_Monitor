"""
Paleta de cores (tema escuro / claro).
O dict ``C`` é mutável e partilhado pela app (web e legado Tk).
"""

from __future__ import annotations

from app_settings import load_settings

PALETTE_DARK = {
    "bg": "#0a0a0a",
    "bg2": "#111111",
    "bg3": "#1a1a1a",
    "card": "#151515",
    "border": "#2a2a2a",
    "border2": "#3a3a3a",
    "purple": "#8b5cf6",
    "purple2": "#a78bfa",
    "purple3": "#ddd6fe",
    "accent": "#a855f7",
    "text": "#ececec",
    "text2": "#b0b0b0",
    "text3": "#737373",
    "green": "#22c55e",
    "red": "#ef4444",
    "yellow": "#f59e0b",
    "rmt": "#c084fc",
    "zeny": "#fbbf24",
    "rops": "#60a5fa",
    "hero_points": "#f472b6",
    "column_rim": "#2d2d2d",
    "column_face": "#121212",
    "column_hdr": "#181818",
    "column_hdr_fg": "#ddd6fe",
    "btn_danger_bg": "#7f1d1d",
    "btn_danger_fg": "#fecaca",
    "btn_danger_hover": "#991b1b",
    "btn_success_bg": "#14532d",
    "btn_success_fg": "#bbf7d0",
    "btn_success_hover": "#166534",
    "build_slot_bg": "#16142a",
    "build_slot_rim": "#3d2f5c",
    "build_slot_entry_bg": "#120f1d",
    "sb_trough": "#2a2a2a",
    "sb_thumb": "#5c5c5c",
    "sb_thumb_hover": "#707070",
    "sb_thumb_active": "#8b5cf6",
}

PALETTE_LIGHT = {
    "bg": "#f4f4f5",
    "bg2": "#e4e4e7",
    "bg3": "#d4d4d8",
    "card": "#ffffff",
    "border": "#d4d4d8",
    "border2": "#e4e4e7",
    "purple": "#6d28d9",
    "purple2": "#7c3aed",
    "purple3": "#4c1d95",
    "accent": "#7c3aed",
    "text": "#18181b",
    "text2": "#3f3f46",
    "text3": "#71717a",
    "green": "#16a34a",
    "red": "#dc2626",
    "yellow": "#d97706",
    "rmt": "#7c3aed",
    "zeny": "#ca8a04",
    "rops": "#2563eb",
    "hero_points": "#db2777",
    "column_rim": "#d4d4d8",
    "column_face": "#fafafa",
    "column_hdr": "#f4f4f5",
    "column_hdr_fg": "#5b21b6",
    "btn_danger_bg": "#fef2f2",
    "btn_danger_fg": "#b91c1c",
    "btn_danger_hover": "#fee2e2",
    "btn_success_bg": "#ecfdf5",
    "btn_success_fg": "#047857",
    "btn_success_hover": "#d1fae5",
    "build_slot_bg": "#faf8ff",
    "build_slot_rim": "#c4b5fd",
    "build_slot_entry_bg": "#ffffff",
    "sb_trough": "#e4e4e7",
    "sb_thumb": "#909096",
    "sb_thumb_hover": "#71717a",
    "sb_thumb_active": "#6d28d9",
}

C: dict = {}

ITEM_CARD_UI = {
    "bg": "#f5f0e8",
    "border": "#c9a227",
    "title": "#1a1528",
    "desc_bg": "#ffffff",
    "desc_fg": "#3d3550",
    "muted": "#6b5a8a",
    "weight_bg": "#fff8dc",
    "weight_fg": "#5c4a2e",
}


def apply_palette(theme=None) -> None:
    """Actualiza o dict global ``C`` (cores da interface)."""
    t = (theme or "dark").strip().lower()
    chosen = PALETTE_LIGHT if t == "light" else PALETTE_DARK
    C.clear()
    C.update(chosen)


def init_theme_from_settings() -> None:
    apply_palette(load_settings().get("ui_theme", "dark"))


init_theme_from_settings()
