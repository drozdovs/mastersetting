# -*- coding: utf-8 -*-
"""Движок архива: высокоуровневые операции сохранения и загрузки.

Оборачивает низкоуровневый копировальщик (``fs_ops``) и каталог (``catalog``),
добавляя: проверку носителя, проверку целостности, журналирование и статистику.
Это чистое ядро без GUI — его можно использовать из CLI и из тестов.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass

from . import fs_ops
from .catalog import Catalog
from .config import Config
from .naming import settings_dir
from .platform import (
    check_free_space,
    check_usb_drive,
    get_directory_size,
    is_write_protected,
)


class EngineError(Exception):
    """Ошибка операции (с понятным пользователю текстом)."""


@dataclass
class OperationReport:
    ok: bool
    message: str
    files: int = 0
    bytes_: int = 0
    mismatches: list[str] | None = None


class ArchiveEngine:
    """Операции сохранения/загрузки настроек."""

    def __init__(self, config: Config | None = None, catalog: Catalog | None = None):
        self.config = config or Config.load()
        self.catalog = catalog or Catalog(config=self.config)

    # ------------------------------------------------------------------
    # Сохранить настройки с носителя в архив (карта -> C:)
    # ------------------------------------------------------------------
    def save(
        self,
        operator: str,
        camera: str,
        settings_name: str,
        from_path: str | None = None,
        overwrite: bool = False,
        verify: bool = True,
        progress=None,
        should_cancel=None,
    ) -> OperationReport:
        if not operator or not camera or not settings_name:
            raise EngineError("Заполните оператора, камеру и название настроек")

        # 1. Определить источник
        if from_path and os.path.isdir(from_path):
            src = from_path
        else:
            drive, error = check_usb_drive(self.config.removable_drive_start)
            if error:
                raise EngineError(error)
            if is_write_protected(drive):
                raise EngineError(
                    "Карта защищена от записи! Снимите защиту на носителе!"
                )
            src = drive

        # 2. Куда сохраняем
        dest = str(settings_dir(
            self.config.base_path, operator, camera, settings_name
        ))

        # 3. Место и перезапись
        required = get_directory_size(src)
        if not check_free_space(self.config.base_path, required):
            raise EngineError("Недостаточно свободного места на диске архива")
        if os.path.exists(dest) and not overwrite:
            raise EngineError(
                "Настройки с таким именем уже существуют. Разрешите перезапись."
            )

        # 4. Копирование с атомарной заменой
        try:
            result_holder = {}

            def _do_copy(target: str):
                res = fs_ops.copy_tree(
                    src, target,
                    self.config.excluded_files,
                    self.config.excluded_extensions,
                    progress=progress,
                    should_cancel=should_cancel,
                )
                result_holder["res"] = res

            fs_ops.safe_replace_dir(dest, _do_copy)
        except fs_ops.CopyCancelled:
            self.catalog.log_event(
                "save", "cancelled", operator, camera, settings_name,
                drive=src, message="Отменено пользователем",
            )
            raise
        except Exception as e:  # noqa: BLE001
            self.catalog.log_event(
                "save", "error", operator, camera, settings_name,
                drive=src, message=str(e),
            )
            raise EngineError(f"Ошибка при сохранении: {e}") from e

        res = result_holder.get("res", fs_ops.CopyResult())

        # 5. Проверка целостности
        mismatches: list[str] = []
        if verify:
            mismatches = fs_ops.verify_copy(
                src, dest,
                self.config.excluded_files,
                self.config.excluded_extensions,
            )

        # 6. Каталог + событие
        manifest_path = os.path.join(dest, "_manifest.json")
        try:
            manifest = {rel: fs_ops.hash_file(os.path.join(dest, rel))
                        for rel in _relative_files(dest)}
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            manifest_dump = json.dumps(manifest, ensure_ascii=False)
        except Exception:
            manifest_dump = ""

        size = get_directory_size(dest)
        self.catalog.register_archive(
            operator, camera, settings_name, dest,
            size_bytes=size, manifest=manifest_dump,
        )
        status = "ok" if not mismatches else "error"
        self.catalog.log_event(
            "save", status, operator, camera, settings_name,
            drive=src, message="" if not mismatches else "Несовпадение файлов",
            bytes_=res.bytes_copied, files=res.files_copied,
        )

        if mismatches:
            return OperationReport(
                ok=False,
                message=f"Копирование завершено, но {len(mismatches)} файл(ов) не совпали",
                files=res.files_copied, bytes_=res.bytes_copied,
                mismatches=mismatches,
            )
        return OperationReport(
            ok=True, message="Настройки успешно сохранены",
            files=res.files_copied, bytes_=res.bytes_copied,
        )

    # ------------------------------------------------------------------
    # Загрузить настройки из архива на носитель (C: -> карта)
    # ------------------------------------------------------------------
    def load(
        self,
        operator: str,
        camera: str,
        settings_name: str,
        to_path: str | None = None,
        verify: bool = True,
        progress=None,
        should_cancel=None,
    ) -> OperationReport:
        if not operator or not camera or not settings_name:
            raise EngineError("Выберите оператора, камеру и настройки")

        src = str(settings_dir(
            self.config.base_path, operator, camera, settings_name
        ))
        # Пробуем найти фактическую папку (имя может быть с другой датой)
        if not os.path.exists(src):
            src = _find_settings_dir(
                self.config.base_path, operator, camera, settings_name
            )
        if not src or not os.path.exists(src):
            raise EngineError(f"Настройки не найдены:\n{src}")

        if to_path and os.path.isdir(to_path):
            dest = to_path
        else:
            drive, error = check_usb_drive(self.config.removable_drive_start)
            if error:
                raise EngineError(error)
            if is_write_protected(drive):
                raise EngineError("Карта защищена от записи! Снимите защиту на носителе!")
            dest = drive

        required = get_directory_size(src)
        if not check_free_space(dest, required):
            raise EngineError("Недостаточно свободного места на флешке!")

        try:
            res = fs_ops.copy_tree(
                src, dest,
                self.config.excluded_files,
                self.config.excluded_extensions,
                progress=progress,
                should_cancel=should_cancel,
            )
        except fs_ops.CopyCancelled:
            self.catalog.log_event(
                "load", "cancelled", operator, camera, settings_name,
                drive=dest, message="Отменено пользователем",
            )
            raise
        except Exception as e:  # noqa: BLE001
            self.catalog.log_event(
                "load", "error", operator, camera, settings_name,
                drive=dest, message=str(e),
            )
            raise EngineError(f"Ошибка при загрузке: {e}") from e

        mismatches = []
        if verify:
            mismatches = fs_ops.verify_copy(
                src, dest,
                self.config.excluded_files,
                self.config.excluded_extensions,
            )

        status = "ok" if not mismatches else "error"
        self.catalog.log_event(
            "load", status, operator, camera, settings_name,
            drive=dest, message="" if not mismatches else "Несовпадение файлов",
            bytes_=res.bytes_copied, files=res.files_copied,
        )

        if mismatches:
            return OperationReport(
                ok=False,
                message=f"Загрузка завершена, но {len(mismatches)} файл(ов) не совпали",
                files=res.files_copied, bytes_=res.bytes_copied,
                mismatches=mismatches,
            )
        return OperationReport(
            ok=True, message="Настройки успешно загружены на флешку",
            files=res.files_copied, bytes_=res.bytes_copied,
        )

    # ------------------------------------------------------------------
    # Быстрый импорт из подключённого носителя (автопоиск)
    # ------------------------------------------------------------------
    def detect_drive(self) -> tuple[str | None, str | None]:
        return check_usb_drive(self.config.removable_drive_start)


# ---------------------------------------------------------------------------
# Вспомогательное
# ---------------------------------------------------------------------------

def _relative_files(root: str) -> list[str]:
    out = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            out.append(rel.replace(os.sep, "/"))
    return out


def _find_settings_dir(base_path: str, operator: str, camera: str, settings: str) -> str | None:
    """Найти папку настроек по имени, игнорируя префикс даты."""
    cam_dir = os.path.join(base_path, "cameraman", operator, camera)
    if not os.path.isdir(cam_dir):
        return None
    for item in sorted(os.listdir(cam_dir), reverse=True):
        if item == settings or item.endswith("_" + settings):
            full = os.path.join(cam_dir, item)
            if os.path.isdir(full):
                return full
    return None
