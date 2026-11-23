# MasterSetting 2.0

Система управления настройками видеокамер: **десктоп-агент** (Windows-first) +
**сервер** (FastAPI) + **веб-админка** (React).

- Агент сохраняет настройки с SD-карты в локальный архив и заливает их обратно на
  карту перед съёмкой. Офлайн-first: работает без сервера.
- Сервер принимает метаданные и статистику, хранит реестр камер/пользователей и
  публикует обновления агента.
- Веб-админка: дашборд, агенты, журнал, камеры, пользователи, группы, обновления.

---

## Архитектура

```
┌─────────────────────┐   HTTPS/JSON    ┌──────────────────────┐
│  MasterSetting Agent │  ───────────▶  │  MasterSetting Server │
│  (Windows .exe)      │  heartbeat/    │  FastAPI + PostgreSQL │
│  GUI + движок архива │  ◀───────────  │                       │
└─────────────────────┘  sync/update    └──────────┬───────────┘
                                                   │
                                        ┌──────────▼───────────┐
                                        │  Web-админка (React) │
                                        └──────────────────────┘
```

Структура репозитория:

```
mastersetting/      # общее ядро (config, platform, filters, fs_ops, catalog, engine)
agent/              # десктоп-агент: app.py (GUI), widgets.py, sync_client.py, offline_cache.py
server/             # FastAPI: app, models, routers, security
web/                # React-админка (Vite)
tests/              # pytest для ядра и офлайн-кэша
cli.py              # headless-CLI агента
main.py             # точка входа агента
deploy/             # Docker, Caddy, PyInstaller, Inno Setup
.github/workflows/  # CI: сборка .exe на windows-latest
```

---

## Офлайн-режим (работа без сервера)

Ключевой принцип: **агент никогда не зависит от сервера.**

- Все операции сохранения/загрузки выполняются локально и работают без сети.
- Список камер и операторов берётся с сервера, но **кэшируется** в
  `~/.mastersetting/offline_cache.json` (Windows: `%APPDATA%/MasterSetting/`).
- При потере связи агент использует последний успешный кэш — списки не «пропадают».
- События (журнал операций) накапливаются локально (SQLite, флаг `synced=0`) и
  выгружаются на сервер автоматически, как только связь восстановится.
- Если кэша ещё нет — используются значения по умолчанию из `camera.txt`.

Индикатор в главном окне агента показывает состояние: «подключён» или
«нет связи (офлайн-режим, кэш от &lt;дата&gt;)».


---

## Быстрый старт (агент, локально)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
python main.py            # GUI
python cli.py info        # headless: информация и статистика
```

Архив настроек: `C:/setting` (Windows) или `~/MasterSetting` (macOS/Linux).
База каталога: `%APPDATA%/MasterSetting/catalog.db` (Win) или `~/.mastersetting/` (Unix).

### Подключение агента к серверу

Создайте `config.json` в папке данных приложения (или задайте переменные окружения):

```json
{
  "server_url": "https://mastersettings.app.dsdp.ru"
}
```

Либо через окружение:

```bash
export MS_SERVER_URL=https://mastersettings.app.dsdp.ru
```

При запуске агент сам зарегистрируется, получит токен и начнёт heartbeat + sync.

---

## Сервер (продакшн)

Развёрнуто на `207.2.120.95` в `/root/mastersettings_app`.

- **URL:** https://mastersettings.app.dsdp.ru
- **Порт внутри:** `127.0.0.1:8010` (проксируется Caddy с авто-SSL)
- **БД:** PostgreSQL 16 в Docker-томе `deploy_ms_pgdata`
- **Автозапуск:** systemd `mastersettings.service`

### Обновление после правок кода

```bash
# с локальной машины
rsync -az --delete --exclude-from=/tmp/ms_exclude.txt ./ root@207.2.120.95:/root/mastersettings_app/
# на сервере
cd /root/mastersettings_app && sed -i 's/\r$//' deploy/deploy.sh && bash deploy/deploy.sh
```

### Тесты

```bash
pip install pytest
pytest tests/ -q
```

---

## Сборка Windows .exe

### Автоматически (CI)

GitHub Actions workflow `.github/workflows/build-windows.yml` собирает `.exe` на
`windows-latest` при пуше тега `v*` или вручную (workflow_dispatch). Артефакт —
`dist/MasterSetting/**`; на теге прикрепляется к релизу GitHub.

### Вручную (на Windows-машине)

```bat
deploy\build_agent.bat          REM onedir, без UPX
iscc deploy\installer.iss       REM установщик Inno Setup
```

Меры против ложных срабатываний антивируса:

1. **onedir**, не onefile; **UPX выключен**.
2. Version-info и манифест (уже в `deploy/`).
3. **Подпись кода** (`signtool`) — OV/EV сертификат.
4. Отправка сборки в Microsoft Defender как ложное срабатывание.

---

## Переменные окружения сервера

| Переменная | Назначение |
|---|---|
| `MS_DATABASE_URL` | строка подключения (Prod: postgresql+psycopg2://…) |
| `MS_JWT_SECRET` | секрет для JWT (обязательно сменить) |
| `MS_ADMIN_LOGIN` / `MS_ADMIN_PASSWORD` | первый администратор |
| `MS_CORS_ORIGINS` | разрешённые источники (через запятую) |
| `MS_RELEASES_DIR` | папка релизов агента |
