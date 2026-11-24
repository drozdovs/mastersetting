# -*- coding: utf-8 -*-
"""Общая изоляция тестов от реального состояния пользователя.

Тесты НЕ должны читать/писать настоящий файл подтверждения путей FX3/FX3A и
настоящие секреты: иначе результат зависел бы от машины разработчика.
"""

import os
import tempfile

# Отдельное хранилище подтверждения путей на время тестовой сессии.
os.environ.setdefault(
    "MS_FX3_CONFIRM_FILE",
    os.path.join(tempfile.mkdtemp(prefix="ms-fx3-confirm-"), "fx3_paths_confirmed.json"),
)

# Секреты — в файл, а не в системный Keychain/DPAPI.
os.environ.setdefault(
    "MS_SECRETS_FILE",
    os.path.join(tempfile.mkdtemp(prefix="ms-secrets-"), "secrets.enc"),
)

# Каталог данных приложения — во временную папку, чтобы тесты НИКОГДА не писали
# в реальный ~/.mastersetting / %APPDATA%\MasterSetting пользователя.
os.environ.setdefault(
    "MS_APPDATA",
    tempfile.mkdtemp(prefix="ms-appdata-"),
)
