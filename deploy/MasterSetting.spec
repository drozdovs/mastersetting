# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-спецификация агента MasterSetting.

Сборка: pyinstaller deploy/MasterSetting.spec
Результат: dist/MasterSetting/MasterSetting.exe (onedir).

Важно для антивирусов:
  * ONEDIR (а не onefile) — меньше подозрительного распаковочного поведения;
  * UPX отключён (upx=False) — UPX-упаковка даёт большинство ложных детектов;
  * console=False для GUI;
  * version-файл добавляется на этапе сборки (см. build_agent.bat).
"""

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Данные customtkinter (темы, шрифты, ассеты) обязательны
datas = collect_data_files("customtkinter")
hiddenimports = (
    collect_submodules("customtkinter")
    + ["PIL", "requests", "sqlite3", "tkinter", "tkinter.filedialog"]
)

a = Analysis(
    ["../main.py"],
    pathex=[".."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "matplotlib", "numpy", "fastapi", "uvicorn", "sqlalchemy"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MasterSetting",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # КРИТИЧНО: не использовать UPX
    console=False,           # GUI-приложение
    disable_windowed_traceback=False,
    version="../deploy/version_info.txt",  # при необходимости
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MasterSetting",
)
