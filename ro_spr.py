"""
Descodifica sprites .spr (Ragnarok Online) para imagem RGBA / PNG.

Pixels RGBA em ordem top-down (origem canto superior esquerdo), compatível com PIL / Tk;
não se aplica flip vertical do RoBrowser (WebGL).

Se PIL estiver disponível, spr_to_png_bytes() gera PNG com canal alpha.
"""
from __future__ import annotations

import struct
from io import BytesIO
from typing import List, Tuple


class SprDecodeError(ValueError):
    pass


def _read_u16_le(b: BytesIO) -> int:
    return struct.unpack("<H", b.read(2))[0]


def _read_i16_le(b: BytesIO) -> int:
    return struct.unpack("<h", b.read(2))[0]


def _decode_indexed_rle(b: BytesIO, width: int, height: int) -> bytearray:
    size = width * height
    out = bytearray(size)
    index = 0
    chunk_len = _read_u16_le(b)
    end = b.tell() + chunk_len
    while b.tell() < end:
        c = b.read(1)[0]
        if index >= size:
            break
        out[index] = c
        index += 1
        if c == 0:
            count = b.read(1)[0]
            if count == 0:
                if index < size:
                    out[index] = 0
                    index += 1
            else:
                for _ in range(1, count):
                    if index >= size:
                        break
                    out[index] = 0
                    index += 1
    return out


def _decode_indexed_raw(b: BytesIO, width: int, height: int) -> bytearray:
    n = width * height
    return bytearray(b.read(n))


def _palette_to_rgba_u32(pal: bytes) -> List[int]:
    pal32: List[int] = []
    for i in range(256):
        r = pal[i * 4 + 0]
        g = pal[i * 4 + 1]
        b = pal[i * 4 + 2]
        a = 0 if i == 0 else 255
        pal32.append((a << 24) | (b << 16) | (g << 8) | r)
    return pal32


def _indexed_to_rgba(width: int, height: int, indices: bytes, pal: bytes) -> bytes:
    pal32 = _palette_to_rgba_u32(pal)
    out = bytearray(width * height * 4)
    out32 = memoryview(out).cast("I")
    for y in range(height):
        row = y * width
        for x in range(width):
            idx = indices[row + x]
            out32[row + x] = pal32[idx]
    return bytes(out)


def _rgba_frame_to_rgba(width: int, height: int, abgr: bytes) -> bytes:
    out = bytearray(width * height * 4)
    out32 = memoryview(out).cast("I")
    in32 = memoryview(abgr).cast("I")
    for y in range(height):
        row = y * width
        for x in range(width):
            pixel = int(in32[row + x])
            a = pixel & 0xFF
            r = (pixel >> 24) & 0xFF
            g = (pixel >> 16) & 0xFF
            b = (pixel >> 8) & 0xFF
            if a == 0:
                out32[row + x] = 0
            else:
                out32[row + x] = (a << 24) | (b << 16) | (g << 8) | r
    return bytes(out)


def decode_spr(data: bytes, *, frame_index: int = 0) -> Tuple[int, int, bytes]:
    """Devolve (width, height, pixels RGBA) para o frame indicado."""
    if len(data) < 16:
        raise SprDecodeError("ficheiro demasiado pequeno")
    b = BytesIO(data)
    sig = b.read(2)
    if sig != b"SP":
        raise SprDecodeError(f"cabeçalho inválido: {sig!r}")
    vb0 = b.read(1)[0]
    vb1 = b.read(1)[0]
    version = vb0 / 10.0 + vb1
    n_indexed = _read_u16_le(b)
    n_rgba = 0
    if version > 1.1:
        n_rgba = _read_u16_le(b)

    indexed_frames: List[Tuple[int, int, bytes]] = []
    for _ in range(n_indexed):
        w = _read_u16_le(b)
        h = _read_u16_le(b)
        if w == 0xFFFF and h == 0xFFFF:
            indexed_frames.append((0, 0, b""))
            continue
        if version < 2.1:
            raw = bytes(_decode_indexed_raw(b, w, h))
        else:
            raw = bytes(_decode_indexed_rle(b, w, h))
        indexed_frames.append((w, h, raw))

    rgba_frames: List[Tuple[int, int, bytes]] = []
    for _ in range(n_rgba):
        w = _read_i16_le(b)
        h = _read_i16_le(b)
        nbytes = w * h * 4
        pix = b.read(nbytes)
        if len(pix) != nbytes:
            raise SprDecodeError("truncado no segmento RGBA")
        rgba_frames.append((w, h, pix))

    pal = data[-1024:] if version > 1.0 else b"\x00" * 1024
    if len(pal) < 1024:
        raise SprDecodeError("palette em falta")

    total = n_indexed + n_rgba
    if not total:
        raise SprDecodeError("sprite sem frames")
    if frame_index < 0 or frame_index >= total:
        raise SprDecodeError(f"frame_index {frame_index} fora do intervalo [0,{total})")

    if frame_index < n_indexed:
        w, h, idxb = indexed_frames[frame_index]
        if w <= 0 or h <= 0 or not idxb:
            raise SprDecodeError("frame indexado vazio")
        rgba = _indexed_to_rgba(w, h, idxb, pal)
        return w, h, rgba

    w, h, abgr = rgba_frames[frame_index - n_indexed]
    if w <= 0 or h <= 0:
        raise SprDecodeError("frame RGBA vazio")
    rgba = _rgba_frame_to_rgba(w, h, abgr)
    return w, h, rgba


def spr_to_png_bytes(data: bytes, *, frame_index: int = 0) -> bytes:
    """Devolve PNG RGBA a partir dos bytes de um .spr."""
    w, h, rgba = decode_spr(data, frame_index=frame_index)
    try:
        from io import BytesIO as BIO

        from PIL import Image

        im = Image.frombytes("RGBA", (w, h), rgba)
        buf = BIO()
        im.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except ImportError as e:
        raise SprDecodeError("instale Pillow para gerar PNG: pip install Pillow") from e


def spr_file_to_png_bytes(path: str, *, frame_index: int = 0) -> bytes:
    with open(path, "rb") as f:
        return spr_to_png_bytes(f.read(), frame_index=frame_index)
