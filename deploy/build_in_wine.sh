#!/usr/bin/env bash
# Сборка MasterSetting.exe внутри Wine-контейнера.
# Ожидает исходники в /src, результат — в /src/dist.
#
# Использует тот же проверенный подход, что и deploy/build_on_server.sh:
# embeddable Python + запуск через псевдо-терминал (иначе Wine ломает stdio).
set -euo pipefail

export WINEPREFIX=/root/.wine WINEDEBUG=-all WINEARCH=win64
PY="$WINEPREFIX/drive_c/Python312/python.exe"

wpy() { script -qec "xvfb-run -a wine $PY $*" /dev/null; }

echo "==> Windows-Python (embeddable 3.12)"
if [ ! -f "$PY" ]; then
    PYD="$WINEPREFIX/drive_c/Python312"
    mkdir -p "$PYD"
    wget -q -O /tmp/py.zip \
        https://www.python.org/ftp/python/3.12.7/python-3.12.7-embed-amd64.zip
    unzip -o -q /tmp/py.zip -d "$PYD"
    sed -i "s/#import site/import site/" "$PYD/python312._pth"
    grep -q 'site-packages' "$PYD/python312._pth" || echo 'Lib\site-packages' >> "$PYD/python312._pth"
    wget -q -O "$PYD/get-pip.py" https://bootstrap.pypa.io/get-pip.py
    wpy "$PYD/get-pip.py" --no-warn-script-location
    xvfb-run -a wine wineboot --init >/dev/null 2>&1 || true
fi

echo "==> Зависимости"
wpy -m pip install --upgrade pip
wpy -m pip install -r /src/requirements.txt pyinstaller

echo "==> PyInstaller (onedir, без UPX, с иконкой)"
cd /src
rm -rf build dist
wpy -m PyInstaller --clean --noconfirm 'deploy\MasterSetting.spec'
ls -la /src/dist/MasterSetting/MasterSetting.exe

echo "==> Inno Setup (установщик)"
ISCC="/root/.wine-inno/drive_c/Program Files/Inno Setup 6/ISCC.exe"
if [ -f "$ISCC" ]; then
    WINEPREFIX=/root/.wine-inno script -qec \
        "xvfb-run -a wine \"$ISCC\" \"deploy\\\\installer.iss\"" /dev/null
    ls -la /src/dist/*.exe
fi

echo "==> Готово"
