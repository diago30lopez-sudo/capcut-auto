# -*- mode: python ; coding: utf-8 -*-
# Empaquetado PyInstaller (onedir): el binario de CrispASR y el modelo espanol
# NO se incluyen; se descargan en la primera ejecucion dentro de bin/ y models/.

a = Analysis(
    ["src\\main.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tests", "pkg_resources", "setuptools"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CapCutAuto",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="CapCutAuto",
)