#!/usr/bin/env python3
"""
List entries inside a Gravity GRF/GPF 0x200 archive (same layout as OpenKore grftool).

This reads the header and zlib-compressed file table only. Extracting file *bodies*
requires GRF_Process (broken DES / mixcrypt) then zlib — not implemented here.
See https://github.com/OpenKore/grftool
"""
from __future__ import annotations

import argparse
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

GRF_MAGIC = b"Master of Magic"
GRF_HEADER_LEN = len(GRF_MAGIC)  # 15 — compare without trailing NUL (C sizeof-1)
# C uses sizeof("Master of Magic") which is 16 including NUL
_SIZEOF_HEADER = len(GRF_MAGIC) + 1
GRF_HEADER_MID_LEN = _SIZEOF_HEADER + 0x0E  # 30
GRF_HEADER_FULL_LEN = _SIZEOF_HEADER + 0x1E  # 46

GRFFILE_FLAG_FILE = 0x01
GRFFILE_FLAG_MIXCRYPT = 0x02
GRFFILE_FLAG_0x14_DES = 0x04


@dataclass
class GrfEntry:
    path: str
    compressed_len: int
    compressed_len_aligned: int
    real_len: int
    flags: int
    data_offset: int  # absolute offset in .grf file

    def flag_desc(self) -> str:
        parts = []
        if self.flags & GRFFILE_FLAG_FILE:
            parts.append("file")
        else:
            parts.append("dir?")
        if self.flags & GRFFILE_FLAG_MIXCRYPT:
            parts.append("mixcrypt")
        if self.flags & GRFFILE_FLAG_0x14_DES:
            parts.append("des20")
        return "|".join(parts) if parts else str(self.flags)


def _u32(b: bytes, off: int) -> int:
    return struct.unpack_from("<I", b, off)[0]


def read_grf_entries(path: Path) -> tuple[int, int, bool, list[GrfEntry]]:
    raw = path.read_bytes()
    if len(raw) < GRF_HEADER_FULL_LEN:
        raise ValueError("file too small for GRF header")

    hdr = raw[:GRF_HEADER_FULL_LEN]
    if hdr[:GRF_HEADER_LEN] != GRF_MAGIC:
        raise ValueError("not a GRF: missing 'Master of Magic'")

    wm = hdr[GRF_HEADER_LEN : GRF_HEADER_LEN + 15]
    allow_crypt = wm[1] == 1
    if allow_crypt:
        expected = bytes(range(15))
        if wm != expected:
            raise ValueError("encrypted GRF watermark corrupt")
    else:
        if wm != b"\x00" * 15:
            raise ValueError("non-encrypted GRF watermark corrupt")

    version = _u32(hdr, GRF_HEADER_MID_LEN + 0x0C)
    if (version & 0xFF00) != 0x0200:
        raise ValueError(f"unsupported GRF version 0x{version:04x} (need 0x0200)")

    nfiles = _u32(hdr, GRF_HEADER_MID_LEN + 8) - _u32(hdr, GRF_HEADER_MID_LEN + 4) - 7
    if nfiles < 0 or nfiles > 10_000_000:
        raise ValueError(f"suspicious nfiles={nfiles}")

    table_off = _u32(hdr, GRF_HEADER_MID_LEN) + GRF_HEADER_FULL_LEN
    if table_off + 8 > len(raw):
        raise ValueError("file table offset out of range")

    zsize = _u32(raw, table_off)
    usize = _u32(raw, table_off + 4)
    zdata = raw[table_off + 8 : table_off + 8 + zsize]
    if len(zdata) != zsize:
        raise ValueError("truncated compressed file table")

    table = zlib.decompress(zdata)
    if usize and len(table) != usize:
        # Some archives set usize=0; otherwise lengths should match
        pass

    off = 0
    entries: list[GrfEntry] = []
    for _ in range(nfiles):
        end = table.find(b"\x00", off)
        if end < 0:
            raise ValueError("unterminated path in file table")
        path_bytes = table[off:end]
        try:
            p = path_bytes.decode("cp949")
        except UnicodeDecodeError:
            p = path_bytes.decode("latin-1", errors="replace")
        off = end + 1
        if off +0x11 > len(table):
            raise ValueError("truncated entry metadata")
        clen = _u32(table, off)
        calign = _u32(table, off + 4)
        rlen = _u32(table, off + 8)
        flags = table[off + 0x0C]
        pos = _u32(table, off + 0x0D) + GRF_HEADER_FULL_LEN
        off += 0x11
        entries.append(
            GrfEntry(
                path=p.replace("\\", "/"),
                compressed_len=clen,
                compressed_len_aligned=calign,
                real_len=rlen,
                flags=flags,
                data_offset=pos,
            )
        )

    return version, nfiles, allow_crypt, entries


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="List GRF 0x200 index (OpenKore-compatible).")
    ap.add_argument("grf", type=Path, help="Path to .grf")
    ap.add_argument("--contains", "-c", default="", help="substring filter (case-insensitive)")
    ap.add_argument("--ext", "-e", default="", help="filename extension filter e.g. .gif")
    ap.add_argument("--limit", "-n", type=int, default=100, help="max rows to print (0=all)")
    args = ap.parse_args()

    ver, nfiles, crypt, entries = read_grf_entries(args.grf)
    print(f"version=0x{ver:04x} nfiles={nfiles} allowCrypt={crypt} listed={len(entries)}")

    needle = args.contains.lower()
    ext = args.ext.lower()
    shown = 0
    for ent in entries:
        p = ent.path
        pl = p.lower()
        if needle and needle not in pl:
            continue
        if ext and not pl.endswith(ext):
            continue
        print(
            f"{ent.data_offset:10d} {ent.real_len:10d} {ent.flags:02x} [{ent.flag_desc()}] {p}"
        )
        shown += 1
        if args.limit and shown >= args.limit:
            print(f"... (stopped at {args.limit}, use --limit 0 for all)")
            break


if __name__ == "__main__":
    main()
