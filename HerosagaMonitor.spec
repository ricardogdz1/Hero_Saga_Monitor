# -*- mode: python ; coding: utf-8 -*-
# Build (na raiz do projecto): pyinstaller HerosagaMonitor.spec
# Gera GDZMonitor.exe (PyWebView) com data/ e gdz_monitor/web/ embutidos.

import os

block_cipher = None

_spec = globals().get("SPEC") or os.path.abspath("HerosagaMonitor.spec")
_root = os.path.normpath(os.path.dirname(_spec))

_web_dir = os.path.join(_root, "gdz_monitor", "web")
_entry = os.path.join(_root, "run.py")

_datas = [
    (os.path.join(_root, "data"), "data"),
    (_web_dir, os.path.join("gdz_monitor", "web")),
]

_binaries = []
_hidden = [
    "cloudscraper",
    "PIL",
    "PIL.Image",
    "bottle",
    "webview",
    "gdz_monitor.app.api",
    "gdz_monitor.app.alert_worker",
    "pythonnet",
    "clr_loader",
]

try:
    from PyInstaller.utils.hooks import collect_all

    _wv_datas, _wv_bins, _wv_hidden = collect_all("webview")
    _datas += _wv_datas
    _binaries += _wv_bins
    _hidden += _wv_hidden
except Exception:
    pass

a = Analysis(
    [_entry],
    pathex=[_root],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=list(dict.fromkeys(_hidden)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "customtkinter"],
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
