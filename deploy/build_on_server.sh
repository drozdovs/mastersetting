#!/usr/bin/env bash
# ============================================================
# Сборка MasterSetting.exe на своём сервере (Linux + Wine).
# Запускать на сервере: bash deploy/build_on_server.sh
# ============================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/root/mastersettings_app}"
OUT_DIR="${OUT_DIR:-/root/mastersettings_build}"
WINEPREFIX="${WINEPREFIX:-/root/.wine}"

export WINEPREFIX WINEDEBUG=-all
export WINEDLLOVERRIDES="mscoree,mshtml="

echo "==> Подготовка каталога сборки"
mkdir -p "$OUT_DIR"
rsync -a --delete \
  --exclude='.git' --exclude='.venv' --exclude='node_modules' \
  --exclude='dist' --exclude='build' --exclude='__pycache__' \
  "$APP_DIR/" "$OUT_DIR/src/"

cd "$OUT_DIR/src"

echo "==> Windows-Python в Wine"
if ! xvfb-run -a wine python --version >/dev/null 2>&1; then
  echo "Устанавливаю Windows-Python..."
  wget -q -O /tmp/python.exe \
    https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe
  xvfb-run -a wine /tmp/python.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
fi

echo "==> Зависимости"
xvfb-run -a wine python -m pip install --upgrade pip >/dev/null
xvfb-run -a wine python -m pip install -r requirements.txt pyinstaller >/dev/null

echo "==> PyInstaller (onedir, без UPX, с иконкой)"
rm -rf build dist
xvfb-run -a wine python -m PyInstaller --clean --noconfirm deploy/MasterSetting.spec

echo "==> Установщик Inno Setup"
ISCC="$WINEPREFIX/drive_c/Program Files (x86)/Inno Setup 6/ISCC.exe"
if [ -f "$ISCC" ]; then
  xvfb-run -a wine "$ISCC" "deploy/installer.iss" || echo "Inno Setup: ошибка (пропущено)"
else
  echo "Inno Setup не найден — пропускаю установщик"
fi

echo "==> Результат"
ls -la dist/MasterSetting/MasterSetting.exe
ls -la dist/*.exe 2>/dev/null || true

# Копируем артефакты в отдельную папку для выдачи
mkdir -p "$OUT_DIR/artifacts"
cp -r dist/MasterSetting "$OUT_DIR/artifacts/"
cp dist/*.exe "$OUT_DIR/artifacts/" 2>/dev/null || true
echo "==> Артефакты: $OUT_DIR/artifacts"
