# -*- coding: utf-8 -*-
"""Схема имён и путей архива настроек.

Иерархия: ``<base>/cameraman/<оператор>/<камера>/<YYYYMMDD>_<название>``.
Дата в имени — день сохранения (для сортировки «сначала свежие»).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def settings_folder_name(
    settings_name: str,
    when: datetime | None = None,
    date_fmt: str = "%Y%m%d",
) -> str:
    """Имя папки настроек: ``YYYYMMDD_Название``."""
    when = when or datetime.now()
    return f"{when.strftime(date_fmt)}_{settings_name}"


def settings_dir(
    base_path: str,
    operator: str,
    camera: str,
    settings_name: str,
    when: datetime | None = None,
) -> Path:
    """Полный путь к папке настроек в архиве."""
    return (
        Path(base_path)
        / "cameraman"
        / operator
        / camera
        / settings_folder_name(settings_name, when)
    )


def parse_settings_folder(folder: str) -> tuple[str | None, str]:
    """Разобрать имя папки настроек ``YYYYMMDD_Название``.

    Возвращает ``(дата_или_None, название)``.
    """
    if "_" in folder:
        date_part, _, name_part = folder.partition("_")
        if len(date_part) == 8 and date_part.isdigit():
            return date_part, name_part
    return None, folder
