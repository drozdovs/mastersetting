#!/usr/bin/env bash
# Портативная сборка MasterSetting.exe внутри Wine-контейнера.
# Ожидает исходники в /src, результат — /src/dist + zip.
#
# Тот же проверенный подход, что и deploy/build_on_server.sh:
# python-build-standalone (С tkinter) + запуск через псевдо-терминал.
set -euo pipefail

export WINEPREFIX=/root/.wine WINEDEBUG=-all WINEARCH=win64
PY="$WINEPREFIX/drive_c/python/python.exe"

wpy() { script -qec "stty cols 400 2>/dev/null; xvfb-run -a wine $PY $*" /dev/null; }

echo "==> Windows-Python (python-build-standalone, С tkinter)"
if [ ! -f "$PY" ]; then
    wget -q -O /tmp/fullpy.tar.gz \
        "https://github.com/astral-sh/python-build-standalone/releases/download/20261110/cpython-3.12.16+20261110-x86_64-pc-windows-msvc-install_only.tar.gz"
    tar -xzf /tmp/fullpy.tar.gz -C "$WINEPREFIX/drive_c/"
fi
wpy -c "import tkinter, sys; sys.exit(0 if tkinter.TkVersion else 1)" \
    || { echo "ОШИБКА: tkinter недоступен в сборочном Python" >&2; exit 1; }

echo "==> Зависимости"
wpy -m pip install --upgrade pip
wpy -m pip install -r /src/requirements.txt pyinstaller

echo "==> PyInstaller (onedir, без UPX, с иконкой)"
cd /src
rm -rf build dist
wpy -m PyInstaller --clean --noconfirm 'deploy\MasterSetting.spec'
ls -la /src/dist/MasterSetting/MasterSetting.exe

echo "==> Портативный архив (zip)"
VER="$(grep -oE '__version__ = "[^"]+"' mastersetting/__init__.py | head -1 | cut -d'"' -f2)"
VER="${VER:-2.0.0}"
rm -f "/src/MasterSetting-windows-$VER.zip"
python3 - "$VER" <<'PY'
import shutil, sys
ver = sys.argv[1]
shutil.make_archive(f"/src/MasterSetting-windows-{ver}", "zip", "/src/dist", "MasterSetting")
PY
ls -la "/src/MasterSetting-windows-$VER.zip"

echo "==> Готово"
