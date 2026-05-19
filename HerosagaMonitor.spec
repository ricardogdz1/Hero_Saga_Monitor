# -*- mode: python ; coding: utf-8 -*-
# Build (na raiz do projecto): pyinstaller HerosagaMonitor.spec
# Inclui data/ (catálogo MVP, sprites em mvp_sprites, mapas id) no executável para uso offline.

import os

from PyInstaller.building.datastruct import Tree

block_cipher = None

_root = os.path.normpath(os.path.dirname(os.path.abspath(__file__)))
# Resolves to project root when PyInstaller defines SPEC
_data_tree = Tree(
    os.path.join(_root, "data"),
    prefix="data",
)

a = Analysis(
    ["app.py"],
    pathex=[_root],
    binaries=[],
    datas=_data_tree,
    hiddenimports=["cloudscraper"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HerosagaMonitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
