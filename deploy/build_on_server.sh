#!/usr/bin/env bash
# ============================================================
# Сборка MasterSetting.exe + установщика на своём сервере.
# Linux + Wine. Без Windows-машины и без GitHub Actions.
#
# Проверено на Ubuntu 24.04 / Wine 9.0 / Python 3.12 (embeddable).
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

PY="/root/.wine/drive_c/Python312/python.exe"

# --- Обёртка над wine-python ---
# КРИТИЧНО: Wine ломает stdio Python при перенаправлении вывода в pipe
# ("init_sys_streams ... Invalid handle"). Поэтому запускаем через
# псевдо-терминал (script -qec), который даёт Wine настоящую консоль.
wpy() {
    local args="$*"
    script -qec "xvfb-run -a wine $PY $args" /dev/null
}

echo "==> 1/5 Синхронизация исходников"
mkdir -p "$OUT_DIR"
rsync -a --delete \
    --exclude='.git' --exclude='.venv' --exclude='node_modules' \
    --exclude='dist' --exclude='build' --exclude='__pycache__' \
    "$APP_DIR/" "$OUT_DIR/src/"
cd "$OUT_DIR/src"

echo "==> 2/5 Проверка Windows-Python (embeddable 3.12)"
if ! wpy --version >/dev/null 2>&1; then
    PYD="/root/.wine/drive_c/Python312"
    mkdir -p "$PYD"
    wget -q -O /tmp/pyembed.zip \
        https://www.python.org/ftp/python/3.12.7/python-3.12.7-embed-amd64.zip
    unzip -o -q /tmp/pyembed.zip -d "$PYD"
    PTH="$PYD/python312._pth"
    sed -i "s/#import site/import site/" "$PTH"
    grep -q 'site-packages' "$PTH" || echo 'Lib\site-packages' >> "$PTH"
    wget -q -O "$PYD/get-pip.py" https://bootstrap.pypa.io/get-pip.py
    wpy "$PYD/get-pip.py" --no-warn-script-location
fi

echo "==> 3/5 Зависимости (requirements + pyinstaller)"
wpy -m pip install --upgrade pip
wpy -m pip install -r requirements.txt pyinstaller

echo "==> 4/5 PyInstaller (onedir, без UPX, с иконкой)"
rm -rf build dist
wpy -m PyInstaller --clean --noconfirm "deploy\\MasterSetting.spec"
ls -la dist/MasterSetting/MasterSetting.exe

echo "==> 5/5 Установщик Inno Setup (отдельный win32-префикс)"
ISCC="/root/.wine-inno/drive_c/Program Files/Inno Setup 6/ISCC.exe"
if [ -f "$ISCC" ]; then
    WINEPREFIX=/root/.wine-inno script -qec \
        "xvfb-run -a wine \"$ISCC\" \"deploy\\\\installer.iss\"" /dev/null
    ls -la dist/MasterSetting-Setup-*.exe
else
    echo "   Inno Setup не установлен — пропускаю установщик"
fi

echo "==> Готово. Артефакты в $OUT_DIR/src/dist"
ls -la dist/
