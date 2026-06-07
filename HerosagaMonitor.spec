# -*- mode: python ; coding: utf-8 -*-
# Build (na raiz do projecto): pyinstaller HerosagaMonitor.spec
# Inclui data/ no executável para uso offline.

import os

block_cipher = None

# PyInstaller injecta SPEC; __file__ não existe ao executar o .spec
_spec = globals().get("SPEC") or os.path.abspath("HerosagaMonitor.spec")
_root = os.path.normpath(os.path.dirname(_spec))

# PyInstaller 6: lista de (pasta_origem, pasta_destino_relativa) — não usar Tree aqui
_datas = [
    (os.path.join(_root, "data"), "data"),
]

a = Analysis(
    ["app.py"],
    pathex=[_root],
    binaries=[],
    datas=_datas,
    hiddenimports=["cloudscraper", "PIL", "PIL.Image", "PIL.ImageTk"],
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
    name="GDZMonitor",
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
