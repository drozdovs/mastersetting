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
    """Базовая папка с настройками (настраиваемая, вне каталога установки).

    ТЗ требует НЕ жёстко задавать ``C:/setting`` (дефект 1.9) и не хранить
    рабочую базу внутри каталога установки, который перезаписывается при
    обновлении. Поэтому по умолчанию архив живёт в каталоге данных приложения:

    * Windows — ``%LOCALAPPDATA%\\MasterSetting\\setting``;
    * macOS/Linux — ``~/MasterSetting/setting``.

    Старый ``C:/setting`` (1.9) при первом запуске показывается как «предлагается
    перенести» — но только после проверяемой копии и с согласия оператора.
    """
    if IS_WINDOWS:
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        base = Path(root) if root else Path.home()
        return str(base / "MasterSetting" / "setting")
    return str(Path.home() / "MasterSetting" / "setting")


def legacy_base_path() -> str:
    """Путь архива из версии 1.9 (для миграции). Настраивается через MS_LEGACY_BASE."""
    env = os.environ.get("MS_LEGACY_BASE")
    if env:
        return env
    if IS_WINDOWS:
        return "C:/setting"
    return str(Path.home() / "MasterSetting" / "setting" / "_legacy")


def app_data_dir() -> Path:
    """Папка данных приложения (для БД, логов, конфига)."""
    if IS_WINDOWS:
        root = os.environ.get("APPDATA") or str(Path.home())
        return Path(root) / "MasterSetting"
    return Path.home() / ".mastersetting"


def ensure_app_data_dir() -> Path:
    """Создать каталог данных и ограничить права владельцем (0700).

    Здесь лежат журнал, секреты (файловый фолбэк), конфиг и каталог библиотеки —
    поэтому каталог не должен быть доступен другим пользователям машины (ТЗ).
    """
    d = app_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    if not IS_WINDOWS:
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
    return d


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

    # Версия приложения (для проверки подписанных обновлений)
    app_version: str = "2.0.0"

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
        """Прочитать конфиг из файла и переменных окружения."""
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

        # Переменные окружения имеют приоритет
        env_map = {
            "MS_BASE_PATH": "base_path",
        }
        for env_var, attr in env_map.items():
            if os.environ.get(env_var):
                setattr(cfg, attr, os.environ[env_var])

        # ТЗ: не держать рабочую базу в каталоге установки, который обновляется.
        from .platform import is_install_path
        try:
            if is_install_path(cfg.base_path):
                cfg.base_path = default_base_path()
        except Exception:
            pass
        return cfg

    def save(self) -> None:
        path = self.config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
