#!/usr/bin/env bash
# Развёртывание MasterSetting на сервере (запускать из /root/mastersettings_app).
# Использование: bash deploy/deploy.sh
set -euo pipefail

APP_DIR="/root/mastersettings_app"
cd "$APP_DIR"

echo "==> Проверка .env"
if [[ ! -f deploy/.env ]]; then
  echo "ОШИБКА: нет deploy/.env (скопируйте deploy/.env.example и заполните)" >&2
  exit 1
fi

echo "==> Сборка и запуск контейнеров"
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build

echo "==> Статус"
docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps

echo "==> Ожидание готовности API"
for i in {1..30}; do
  if curl -sf http://127.0.0.1:8010/api/health >/dev/null 2>&1; then
    echo "API готов: $(curl -s http://127.0.0.1:8010/api/health)"
    break
  fi
  sleep 2
  [[ $i -eq 30 ]] && { echo "API не поднялся" >&2; exit 1; }
done

echo "==> Готово. Проверьте https://mastersettings.app.dsdp.ru"
