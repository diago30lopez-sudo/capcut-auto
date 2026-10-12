# -*- mode: python ; coding: utf-8 -*-
# Empaquetado PyInstaller (onedir): CapCut Auto v2.0.3
# Binario, modelo GGUF y perfiles se empaquetan en el bundle.
# Datos del usuario (config, logs, cache, backups) van junto al .exe.

from PyInstaller.utils.hooks import collect_data_files
import customtkinter, os
from pathlib import Path

_REPO = Path(".").resolve()

def _data_pairs(base, pattern):
    pairs = []
    for p in base.glob(pattern):
        if p.is_file():
            pairs.append((str(p), base.name))
    return pairs

ctk_datas = collect_data_files("customtkinter")
datas = (
    ctk_datas
    + _data_pairs(_REPO / "bin", "*")
    + _data_pairs(_REPO / "models", "*.gguf")
    + _data_pairs(_REPO / "profiles", "*.json")
    + [("README.md", ".")]
)

a = Analysis(
    ["src\\main.py"],
    pathex=[str(_REPO)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "customtkinter",
        "PIL._tkinter_finder",
        "rapidfuzz",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "numpy.tests", "pytest"],
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
    upx=False,
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="CapCutAuto",
)
