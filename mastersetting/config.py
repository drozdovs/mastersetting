# -*- coding: utf-8 -*-
"""Конфигурация агента MasterSetting.

Настройки можно переопределить через файл ``config.json`` рядом с программой
или через переменные окружения. Класс ``Config`` читается как обычно, а
``Config.load()`` подтягивает значения из файла (если он есть).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Платформенное определение базовой папки (аналог C:/setting из версии 1.9)
# ---------------------------------------------------------------------------

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


def default_base_path() -> str:
    """Базовая папка с настройками.

    Windows — как раньше ``C:/setting``.
    macOS/Linux — ``~/MasterSetting``.
    """
    if IS_WINDOWS:
        return "C:/setting"
    return str(Path.home() / "MasterSetting")


def app_data_dir() -> Path:
    """Папка данных приложения (для БД, логов, конфига)."""
    if IS_WINDOWS:
        root = os.environ.get("APPDATA") or str(Path.home())
        return Path(root) / "MasterSetting"
    return Path.home() / ".mastersetting"


# Расширения, которые НЕ копируются (медиафайлы с карты)
DEFAULT_EXCLUDED_EXTENSIONS = [
    ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".heic",
    ".mp4", ".avi", ".mov", ".mkv", ".wmv", ".mxf", ".mts", ".m2ts",
    ".r3d", ".braw", ".crm", ".mpg", ".mpeg",
]

# Файлы, которые не копируются по имени
DEFAULT_EXCLUDED_FILES = ["LASTCLIP.TXT", "lastclip.txt", "_manifest.json"]

# Разрешённые расширения для инструкций
DEFAULT_INSTRUCTION_EXTENSIONS = [".txt", ".doc", ".docx", ".pdf", ".html"]


@dataclass
class Config:
    """Настройки приложения."""

    base_path: str = field(default_factory=default_base_path)

    # Ограничения ввода
    max_name_length: int = 30

    # Буква, с которой начинаем поиск съёмных дисков в Windows
    removable_drive_start: str = "E"

    # Исключения при копировании
    excluded_extensions: list[str] = field(
        default_factory=lambda: list(DEFAULT_EXCLUDED_EXTENSIONS)
    )
    excluded_files: list[str] = field(
        default_factory=lambda: list(DEFAULT_EXCLUDED_FILES)
    )
    instruction_extensions: list[str] = field(
        default_factory=lambda: list(DEFAULT_INSTRUCTION_EXTENSIONS)
    )

    # Автопоиск съёмного носителя при вставке
    auto_detect_drive: bool = True
    auto_detect_poll_seconds: float = 1.5

    # Сервер (заполняется позже; пусто = offline-режим)
    server_url: str = ""
    server_token: str = ""
    heartbeat_seconds: float = 30.0

    # Автообновление
    auto_update: bool = True

    # ------------------------------------------------------------------
    # Производные пути
    # ------------------------------------------------------------------
    @property
    def cameraman_path(self) -> str:
        return str(Path(self.base_path) / "cameraman")

    @property
    def main_path(self) -> str:
        return str(Path(self.base_path) / "main")

    @property
    def camera_file(self) -> str:
        return str(Path(self.main_path) / "camera.txt")

    @property
    def instructions_path(self) -> str:
        return str(Path(self.base_path) / "instructions")

    @property
    def help_image(self) -> str:
        return str(Path(self.main_path) / "saveload.jpg")

    @property
    def catalog_db(self) -> str:
        return str(app_data_dir() / "catalog.db")

    # ------------------------------------------------------------------
    # Загрузка / сохранение
    # ------------------------------------------------------------------
    @classmethod
    def config_file(cls) -> Path:
        return app_data_dir() / "config.json"

    @classmethod
    def load(cls) -> "Config":
        """Загрузить конфиг из файла и переменных окружения."""
        cfg = cls()
        path = cls.config_file()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                for key, value in data.items():
                    if hasattr(cfg, key) and not key.startswith("_"):
                        try:
                            setattr(cfg, key, value)
                        except Exception:
                            pass
            except Exception:
                pass

        # Переменные окружения имеют приоритет (удобно для сервера)
        env_map = {
            "MS_BASE_PATH": "base_path",
            "MS_SERVER_URL": "server_url",
            "MS_SERVER_TOKEN": "server_token",
        }
        for env_var, attr in env_map.items():
            if os.environ.get(env_var):
                setattr(cfg, attr, os.environ[env_var])
        return cfg

    def save(self) -> None:
        path = self.config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
