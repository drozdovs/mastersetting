# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-спецификация агента MasterSetting для macOS.

Сборка:
    .venv/bin/pyinstaller --noconfirm deploy/MasterSetting-macos.spec
Результат:
    dist/MasterSetting.app

Особенности macOS:
  * собирается .app-бандл (BUNDLE), а не одиночный бинарник;
  * иконка — .icns (обязательна для Retina; .ico на macOS не подходит);
  * внутрь кладётся офлайн-справка docs/help, чтобы «Помощь» работала без сети;
  * UPX отключён (на macOS он всё равно не применяется, но фиксируем явно);
  * сборка НЕ подписывает бандл (для этого нужен Apple Developer ID).
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# --- Страж: tkinter обязателен (CustomTkinter без него не запустится) ---
try:
    import tkinter  # noqa: F401
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "ОШИБКА: в сборочном Python нет tkinter — приложение не запустится.\n"
        "Детали: %s" % exc
    )

_HERE = os.path.dirname(os.path.abspath(SPEC))
_ROOT = os.path.dirname(_HERE)

datas = collect_data_files("customtkinter")
datas += [
    # Иконки для окна (agent/app.py ищет deploy/icon.*)
    (os.path.join(_HERE, "icon.png"), "deploy"),
    (os.path.join(_HERE, "icon.icns"), "deploy"),
]
# Офлайн-справка: кнопка «Помощь» ищет docs/help/index.html
_HELP = os.path.join(_ROOT, "docs", "help")
if os.path.isdir(_HELP):
    for name in os.listdir(_HELP):
        datas.append((os.path.join(_HELP, name), "docs/help"))

hiddenimports = (
    collect_submodules("customtkinter")
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
    excludes=["pytest", "matplotlib", "numpy", "PyInstaller"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MasterSetting",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,               # GUI-приложение (без терминала)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,            # None = архитектура текущего Python (arm64/x86_64)
    codesign_identity=None,      # без подписи: пользователь может разрешить вручную
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MasterSetting",
)

app = BUNDLE(
    coll,
    name="MasterSetting.app",
    icon=os.path.join(_HERE, "icon.icns"),
    bundle_identifier="ru.dsdp.mastersetting",
    info_plist={
        "CFBundleName": "MasterSetting",
        "CFBundleDisplayName": "MasterSetting",
        "CFBundleShortVersionString": "2.0.0",
        "CFBundleVersion": "2.0.0",
        "LSMinimumSystemVersion": "11.0",
        # Приложение не «фон»: показывается в Dock
        "LSApplicationCategoryType": "public.app-category.utilities",
        "NSHighResolutionCapable": True,
        # Доступ к съёмным носителям (SD-карты) — пояснение для пользователя
        "NSRemovableVolumesUsageDescription":
            "MasterSetting читает и записывает файлы настроек на SD-карту камеры.",
        "NSDesktopFolderUsageDescription":
            "MasterSetting открывает документы справки и инструкции.",
    },
)
