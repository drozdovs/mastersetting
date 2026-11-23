#!/usr/bin/env bash
# Сборка MasterSetting.exe внутри Wine-контейнера (Linux).
# Ожидает исходники в /src, результат кладёт в /src/dist.
set -euo pipefail

source /root/.venv-win/bin/activate 2>/dev/null || true

echo "==> Установка зависимостей Windows-Python"
wine python -m pip install --upgrade pip >/dev/null
wine python -m pip install -r /src/requirements.txt pyinstaller >/dev/null

echo "==> Иконка (если нет — генерируем)"
if [ ! -f /src/deploy/icon.ico ]; then
  wine python /src/deploy/make_icon.py || true
fi

echo "==> PyInstaller (onedir, без UPX)"
cd /src
rm -rf build dist
xvfb-run -a wine python -m PyInstaller --clean --noconfirm deploy/MasterSetting.spec

echo "==> Проверка результата"
ls -la /src/dist/MasterSetting/MasterSetting.exe

echo "==> Inno Setup (установщик)"
if command -v wine >/dev/null && [ -f "/root/.wine/drive_c/Program Files (x86)/Inno Setup 6/ISCC.exe" ]; then
  xvfb-run -a wine "/root/.wine/drive_c/Program Files (x86)/Inno Setup 6/ISCC.exe" \
      "/src/deploy/installer.iss" || echo "Inno Setup: пропущено (ошибка)"
  ls -la /src/dist/*.exe 2>/dev/null || true
fi

echo "==> Готово"
