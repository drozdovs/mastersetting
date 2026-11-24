#!/usr/bin/env bash
# Сборка MasterSetting для macOS (.app).
#
# Использование:
#     ./deploy/build_macos.sh          # только собрать
#     ./deploy/build_macos.sh --dmg    # собрать и упаковать в DMG (если есть hdiutil)
#
# Результат: dist/MasterSetting.app
#
# Почему не «один файл»:
#   ONEDIR-бандл запускается быстрее и меньше похож на подозрительное
#   самораспаковывающееся поведение.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
cd "$ROOT"

PY="${PYTHON:-$ROOT/.venv/bin/python}"
if [ ! -x "$PY" ]; then
  echo "Не найден Python в .venv ($PY). Укажите PYTHON=/путь/к/python" >&2
  exit 1
fi

if [ "$(uname -s)" != "Darwin" ]; then
  echo "Этот скрипт собирает .app и работает только на macOS." >&2
  exit 1
fi

echo "== Проверка зависимостей =="
"$PY" -c "import tkinter, customtkinter, PIL" || {
  echo "Нет tkinter/customtkinter/Pillow. Установите: $PY -m pip install -r requirements.txt" >&2
  exit 1
}
"$PY" -c "import PyInstaller" 2>/dev/null || "$PY" -m pip install pyinstaller

echo "== Иконки (включая .icns для Retina) =="
"$PY" "$HERE/make_icon.py"

echo "== Сборка .app =="
rm -rf "$ROOT/build" "$ROOT/dist"
"$PY" -m PyInstaller --noconfirm --clean "$HERE/MasterSetting-macos.spec"

APP="$ROOT/dist/MasterSetting.app"
echo
echo "Готово: $APP"
echo "Размер: $(du -sh "$APP" | cut -f1)"
echo
echo "Запуск (дважды кликните Find → Приложения, либо):"
echo "    open \"$APP\""

if [ "${1:-}" = "--dmg" ]; then
  echo "== Упаковка в DMG =="
  DMG="$ROOT/dist/MasterSetting.dmg"
  rm -f "$DMG"
  hdiutil create -volname "MasterSetting" -srcfolder "$APP" -ov -format UDZO "$DMG"
  echo "Готово: $DMG"
fi
