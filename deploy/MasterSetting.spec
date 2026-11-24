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

# --- Страж: tkinter обязателен ---
# CustomTkinter не запустится без tkinter. Embeddable-Python его не содержит,
# поэтому сборка должна падать громко, а не выпускать нерабочий .exe.
try:
    import tkinter  # noqa: F401
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "ОШИБКА: в сборочном Python нет tkinter — приложение не запустится.\n"
        "Используйте полную сборку Python (python-build-standalone install_only),\n"
        "а не embeddable. Детали: %s" % exc
    )

# Абсолютные пути — spec запускается из корня репозитория в CI
_HERE = os.path.dirname(os.path.abspath(SPEC))
_ROOT = os.path.dirname(_HERE)

# Данные customtkinter (темы, шрифты, ассеты) обязательны
datas = collect_data_files("customtkinter")
# Иконка приложения — кладём рядом, чтобы окно могло её подхватить
datas += [
    (os.path.join(_HERE, "icon.ico"), "deploy"),
    (os.path.join(_HERE, "icon.png"), "deploy"),
]
hiddenimports = (
    collect_submodules("customtkinter")
    + collect_submodules("cryptography")
    + ["PIL", "sqlite3", "tkinter", "tkinter.filedialog"]
)

a = Analysis(
    [os.path.join(_ROOT, "main.py")],
    pathex=[_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "matplotlib", "numpy"],
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
    version=os.path.join(_HERE, "version_info.txt"),
    icon=os.path.join(_HERE, "icon.ico"),
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
