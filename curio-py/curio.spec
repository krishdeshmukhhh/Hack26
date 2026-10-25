# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

pyside6_data = collect_data_files("PySide6", includes=["plugins/platforms/**", "plugins/imageformats/**", "plugins/multimedia/**", "plugins/texttospeech/**"])
pyside6_libs = collect_dynamic_libs("PySide6")

a = Analysis(
    ["curio/__main__.py"],
    pathex=[],
    binaries=pyside6_libs,
    datas=[
        ("config.example.toml", "."),
        ("curio/assets/pets", "curio/assets/pets"),
        ("curio/skills/concepts.json", "curio/skills"),
        ("curio/map_sync/assets", "curio/map_sync/assets"),
        *pyside6_data,
    ],
    hiddenimports=[
        "PySide6.QtMultimedia",
        "PySide6.QtTextToSpeech",
        "PySide6.QtWidgets",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "sounddevice",
        "numpy",
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
        "mss.windows",
        "qasync",
        "websockets",
        "httpx",
        "PIL",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Curio",
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
    name="curio",
)
