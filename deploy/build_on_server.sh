#!/usr/bin/env bash
# ============================================================
# Сборка MasterSetting.exe + установщика на своём сервере.
# Linux + Wine. Без Windows-машины и без GitHub Actions.
#
# Проверено на Ubuntu 24.04 / Wine 9.0 / Python 3.12 (python-build-standalone).
# Запуск на сервере:  bash deploy/build_on_server.sh
#
# Зависимости (устанавливаются один раз):
#   dpkg --add-architecture i386
#   apt-get update
#   apt-get install -y --no-install-recommends \
#       wine64 wine32:i386 winbind cabextract xvfb unzip wget
# ============================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/root/mastersettings_app}"   # исходники проекта
OUT_DIR="${OUT_DIR:-/root/msbuild}"              # рабочая папка сборки
WINEPREFIX="${WINEPREFIX:-/root/.wine}"
export WINEPREFIX WINEDEBUG=-all WINEARCH=win64

PY="$WINEPREFIX/drive_c/python/python.exe"

# --- Обёртка над wine-python ---
# КРИТИЧНО: Wine ломает stdio Python при перенаправлении вывода в pipe
# ("init_sys_streams ... Invalid handle"). Поэтому запускаем через
# псевдо-терминал (script -qec), который даёт Wine настоящую консоль.
# Широкий терминал — чтобы длинные Windows-пути не переносились.
wpy() {
    local args="$*"
    script -qec "stty cols 400 2>/dev/null; xvfb-run -a wine $PY $args" /dev/null
}

echo "==> 1/5 Синхронизация исходников"
mkdir -p "$OUT_DIR"
rsync -a --delete \
    --exclude='.git' --exclude='.venv' --exclude='node_modules' \
    --exclude='dist' --exclude='build' --exclude='__pycache__' \
    "$APP_DIR/" "$OUT_DIR/src/"
cd "$OUT_DIR/src"

echo "==> 2/5 Проверка Windows-Python (python-build-standalone, С tkinter)"
# ВАЖНО: embeddable-Python НЕ содержит tkinter, из-за чего .exe падал при
# старте (CustomTkinter без tkinter). Используем полную сборку
# python-build-standalone (install_only) — там tkinter/tcl/tk есть.
PYD="$WINEPREFIX/drive_c/python"
PY="$PYD/python.exe"
if [ ! -f "$PY" ]; then
    wget -q -O /tmp/fullpy.tar.gz \
        "https://github.com/astral-sh/python-build-standalone/releases/download/20261110/cpython-3.12.16+20261110-x86_64-pc-windows-msvc-install_only.tar.gz"
    tar -xzf /tmp/fullpy.tar.gz -C "$WINEPREFIX/drive_c/"
fi

# Жёсткая проверка: без tkinter сборка бессмысленна
wpy -c "import tkinter, sys; sys.exit(0 if tkinter.TkVersion else 1)" \
    || { echo "ОШИБКА: tkinter недоступен в сборочном Python" >&2; exit 1; }

echo "==> 3/5 Зависимости (requirements + pyinstaller)"
wpy -m pip install --upgrade pip
wpy -m pip install -r requirements.txt pyinstaller

echo "==> 4/5 PyInstaller (onedir, без UPX, с иконкой)"
rm -rf build dist
wpy -m PyInstaller --clean --noconfirm "deploy\\MasterSetting.spec"
ls -la dist/MasterSetting/MasterSetting.exe

echo "==> 5/5 Портативный архив (zip)"
# Только portable-версия: распаковать и запустить MasterSetting.exe.
VER="$(grep -oE '__version__ = "[^"]+"' mastersetting/__init__.py | head -1 | cut -d'"' -f2)"
VER="${VER:-2.0.0}"
rm -f "$OUT_DIR/MasterSetting-windows-$VER.zip"
python3 - "$OUT_DIR" "$VER" <<'PY'
import shutil, sys
out, ver = sys.argv[1], sys.argv[2]
shutil.make_archive(f"{out}/MasterSetting-windows-{ver}", "zip", f"{out}/src/dist", "MasterSetting")
PY
ls -la "$OUT_DIR/MasterSetting-windows-$VER.zip"
sha256sum "$OUT_DIR/MasterSetting-windows-$VER.zip"

echo "==> Готово. Артефакт: $OUT_DIR/MasterSetting-windows-$VER.zip"
