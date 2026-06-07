from __future__ import annotations

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    Image = None
    ImageDraw = None
    ImageTk = None


def tk_widget_bg(widget, *, default_bg: str):
    w = widget
    for _ in range(10):
        if w is None:
            return default_bg
        try:
            return w.cget("bg")
        except Exception:
            pass
        w = getattr(w, "master", None)
    return default_bg


def hex_rgb_tuple(h):
    s = (h or "#000000").strip().lstrip("#")
    if len(s) >= 6:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    return (0, 0, 0)


def pill_corner_radius(w: int, h: int) -> int:
    """Raio de cápsula (semicírculos nas extremidades do eixo maior)."""
    return max(1, min(int(w), int(h)) // 2)


def pil_round_solid(w, h, r, fill_hex, scale=2):
    """Bitmap RGBA com cantos suaves (superamostragem + LANCZOS)."""
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow não disponível")
    w, h = max(1, int(w)), max(1, int(h))
    sw = max(1, int(w * scale))
    sh = max(1, int(h * scale))
    r_cap = min(w, h) // 2
    r_eff = int(min(max(1, r), r_cap))
    rs = int(min(max(1, r_eff * scale), sw // 2, sh // 2))
    im = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    t = hex_rgb_tuple(fill_hex) + (255,)
    dr.rounded_rectangle((0, 0, sw - 1, sh - 1), radius=rs, fill=t)
    if scale > 1 and (sw != w or sh != h):
        resampling = getattr(Image, "Resampling", Image)
        im = im.resize((w, h), resampling.LANCZOS)
    return im


def pil_knockout_near_white_rgba(im, thresh: int = 246):
    """
    Torna transparentes os pixels quase brancos (fundo típico de ícones PNG/JPEG).
    *thresh* 220–255: mais alto = só branco «puro»; mais baixo = remove mais cinza-claro.
    """
    if Image is None:
        return im
    try:
        im = im.convert("RGBA")
    except Exception:
        return im
    t = min(255, max(220, int(thresh)))
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            if r >= t and g >= t and b >= t:
                px[x, y] = (r, g, b, 0)
    return im


def canvas_round_fill_vector(canvas, x1, y1, x2, y2, r, fill, tag="rr"):
    """Fallback vectorial (sem antialiasing)."""
    try:
        x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
    except (TypeError, ValueError):
        return
    if x2 <= x1 + 2 or y2 <= y1 + 2:
        return
    r = int(min(max(2, r), (x2 - x1) // 2 - 1, (y2 - y1) // 2 - 1))
    canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="", width=0, tags=(tag,))
    canvas.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline="", width=0, tags=(tag,))
    canvas.create_arc(
        x1,
        y1,
        x1 + 2 * r,
        y1 + 2 * r,
        start=90,
        extent=90,
        fill=fill,
        outline="",
        style="pieslice",
        tags=(tag,),
    )
    canvas.create_arc(
        x2 - 2 * r,
        y1,
        x2,
        y1 + 2 * r,
        start=0,
        extent=90,
        fill=fill,
        outline="",
        style="pieslice",
        tags=(tag,),
    )
    canvas.create_arc(
        x1,
        y2 - 2 * r,
        x1 + 2 * r,
        y2,
        start=180,
        extent=90,
        fill=fill,
        outline="",
        style="pieslice",
        tags=(tag,),
    )
    canvas.create_arc(
        x2 - 2 * r,
        y2 - 2 * r,
        x2,
        y2,
        start=270,
        extent=90,
        fill=fill,
        outline="",
        style="pieslice",
        tags=(tag,),
    )


def canvas_round_fill_sb(canvas, x1, y1, x2, y2, r, fill, tag="rr", holder=None):
    """Como ``canvas_round_fill``, com superamostragem extra para barras finas."""
    holder = holder if holder is not None else canvas
    try:
        canvas.delete(tag)
    except Exception:
        pass
    try:
        xi0 = int(round(float(x1)))
        yi0 = int(round(float(y1)))
        xi1 = int(round(float(x2)))
        yi1 = int(round(float(y2)))
    except (TypeError, ValueError):
        return
    if xi1 <= xi0:
        xi1 = xi0 + 1
    if yi1 <= yi0:
        yi1 = yi0 + 1
    W = xi1 - xi0
    H = yi1 - yi0
    if W < 2 or H < 2:
        return
    r_cap = pill_corner_radius(W, H)
    r = int(min(max(1, r), r_cap))
    has_pil_round = Image is not None and ImageTk is not None
    if has_pil_round:
        sc = 4 if max(W, H) <= 56 else (3 if max(W, H) <= 130 else 2)
        if max(W, H) * sc > 4800:
            sc = 3
        try:
            img = pil_round_solid(W, H, r, fill, scale=sc)
            ph = ImageTk.PhotoImage(img, master=canvas.winfo_toplevel())
            if not hasattr(holder, "_aa_photos"):
                holder._aa_photos = {}
            holder._aa_photos[tag] = ph
            canvas.create_image(xi0, yi0, anchor="nw", image=ph, tags=(tag,))
            return
        except Exception:
            pass
    canvas_round_fill_vector(canvas, float(xi0), float(yi0), float(xi1), float(yi1), r, fill, tag)


def canvas_round_fill(canvas, x1, y1, x2, y2, r, fill, tag="rr", holder=None):
    """Retângulo com cantos arredondados; usa Pillow com AA quando disponível."""
    holder = holder if holder is not None else canvas
    try:
        canvas.delete(tag)
    except Exception:
        pass
    try:
        x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
    except (TypeError, ValueError):
        return
    W = int(x2 - x1)
    H = int(y2 - y1)
    if W < 3 or H < 3:
        return
    r = int(min(max(2, r), W // 2 - 1, H // 2 - 1))
    has_pil_round = Image is not None and ImageTk is not None
    if has_pil_round and W >= 4 and H >= 4:
        sc = 3 if max(W, H) <= 130 else 2
        if max(W, H) * sc > 3600:
            sc = 2
        try:
            img = pil_round_solid(W, H, r, fill, scale=sc)
            ph = ImageTk.PhotoImage(img, master=canvas.winfo_toplevel())
            if not hasattr(holder, "_aa_photos"):
                holder._aa_photos = {}
            holder._aa_photos[tag] = ph
            canvas.create_image(int(x1), int(y1), anchor="nw", image=ph, tags=(tag,))
            return
        except Exception:
            pass
    canvas_round_fill_vector(canvas, x1, y1, x2, y2, r, fill, tag)
