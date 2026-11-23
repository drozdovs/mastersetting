# -*- coding: utf-8 -*-
"""Конфигурация сервера (через переменные окружения)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass
class ServerSettings:
    # БД
    database_url: str = field(default_factory=lambda: _env(
        "MS_DATABASE_URL", "sqlite:///./mastersetting_server.db"))

    # JWT
    jwt_secret: str = field(default_factory=lambda: _env(
        "MS_JWT_SECRET", "CHANGE_ME_in_production"))
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 12      # 12 часов
    refresh_token_days: int = 30

    # Первый администратор (создаётся при старте, если БД пустая)
    admin_login: str = field(default_factory=lambda: _env("MS_ADMIN_LOGIN", "admin"))
    admin_password: str = field(default_factory=lambda: _env(
        "MS_ADMIN_PASSWORD", "admin"))

    # CORS
    cors_origins: list[str] = field(default_factory=lambda: [
        o.strip() for o in _env("MS_CORS_ORIGINS", "*").split(",") if o.strip()
    ])

    # Хранилище релизов агента (для автообновления)
    releases_dir: str = field(default_factory=lambda: _env(
        "MS_RELEASES_DIR", "./releases"))


settings = ServerSettings()
