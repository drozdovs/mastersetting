#!/usr/bin/env bash
# Запуск автотестов MasterSetting под Windows-Python через Wine (без Windows-машины).
#
# Это НЕ полноценная замена проверке на живой Windows 10/11 (Wine не равно
# Windows), но это честный прогон набора тестов на реальном windows-интерпретаторе
# python-build-standalone — он ловит Windows-специфичные ошибки (пути, os.replace,
# GetVolumeInformationW, отсутствие POSIX-прав, tkinter).
#
# Ожидает исходники в /src, отчёт пишет в /src/deploy/windows-report/.
set -uo pipefail

export WINEPREFIX=/root/.wine WINEDEBUG=-all WINEARCH=win64
PY="$WINEPREFIX/drive_c/python/python.exe"
OUT=/src/deploy/windows-report
mkdir -p "$OUT"

wpy() { script -qec "stty cols 400 2>/dev/null; xvfb-run -a wine $PY $*" /dev/null; }

echo "==> Windows-Python (python-build-standalone, С tkinter)"
if [ ! -f "$PY" ]; then
    wget -q -O /tmp/fullpy.tar.gz \
        "https://github.com/astral-sh/python-build-standalone/releases/download/20261110/cpython-3.12.16+20261110-x86_64-pc-windows-msvc-install_only.tar.gz"
    tar -xzf /tmp/fullpy.tar.gz -C "$WINEPREFIX/drive_c/"
fi
wpy -c "import sys; print(sys.platform, sys.version)" | tee "$OUT/windows-python.txt"
wpy -c "import tkinter; print('tk', tkinter.TkVersion)" >> "$OUT/windows-python.txt" 2>&1 || true

echo "==> Зависимости + pytest"
wpy -m pip install --quiet --upgrade pip
wpy -m pip install --quiet -r 'C:\\src\\requirements.txt' pytest

echo "==> Автотесты под Windows-Python"
cd /src
wpy -m pytest tests/ -q > "$OUT/test-result.txt" 2>&1
RC=$?
echo "код возврата pytest: $RC" | tee -a "$OUT/test-result.txt"
tail -5 "$OUT/test-result.txt"

echo "==> Итог в $OUT/test-result.txt (rc=$RC)"
exit $RC
