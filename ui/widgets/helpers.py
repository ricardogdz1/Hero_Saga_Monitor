"""Helpers partilhados pelos widgets Tk customizados."""
from __future__ import annotations

import tkinter as tk

import app_ui_utils
from ui.theme import C

try:
    from PIL import Image, ImageDraw, ImageTk  # noqa: F401

    HAS_PIL_ROUND = True
except ImportError:
    HAS_PIL_ROUND = False

# Alias legado (app.py e código antigo)
_HAS_PIL_ROUND = HAS_PIL_ROUND


def tk_widget_bg(widget, default=None):
    d = default if default is not None else C.get("bg", "#0a0a0a")
    return app_ui_utils.tk_widget_bg(widget, default_bg=d)


def hex_rgb_tuple(h):
    return app_ui_utils.hex_rgb_tuple(h)


def pil_round_solid(w, h, r, fill_hex, scale=2):
    return app_ui_utils.pil_round_solid(w, h, r, fill_hex, scale=scale)


def pill_corner_radius(w: int, h: int) -> int:
    return app_ui_utils.pill_corner_radius(w, h)


def canvas_round_fill_sb(canvas, x1, y1, x2, y2, r, fill, tag="rr", holder=None):
    return app_ui_utils.canvas_round_fill_sb(canvas, x1, y1, x2, y2, r, fill, tag=tag, holder=holder)


def pil_knockout_near_white_rgba(im, thresh: int = 246):
    return app_ui_utils.pil_knockout_near_white_rgba(im, thresh=thresh)


def canvas_round_fill_vector(canvas, x1, y1, x2, y2, r, fill, tag="rr"):
    return app_ui_utils.canvas_round_fill_vector(canvas, x1, y1, x2, y2, r, fill, tag=tag)


def canvas_round_fill(canvas, x1, y1, x2, y2, r, fill, tag="rr", holder=None):
    return app_ui_utils.canvas_round_fill(canvas, x1, y1, x2, y2, r, fill, tag=tag, holder=holder)

