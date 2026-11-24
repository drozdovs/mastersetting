# -*- coding: utf-8 -*-
"""Идемпотентная миграция старого архива ``C:/setting`` в новую библиотеку.

Требования ТЗ («Перенос данных»):

* сначала — **проверяемая** резервная копия существующего архива;
* миграция старых папок и ``camera.txt`` с отчётом: что импортировано,
  пропущено, имеет одинаковые имена/содержимое, выглядит неполным;
* папки ``_OLD`` обрабатываются отдельно;
* папка НЕ считается валидным пресетом только по имени — нужен файл настроек;
* старые данные не удаляются: новое пишется рядом, пока библиотека не проверена.

Миграция безопасна для повторного запуска: уже перенесённые версии не
дублируются (сверка по SHA-256 содержимого).
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import fs_ops
from .settings_rules import discover_in_folder, settings_files_map
from .versioning import VersionStore


@dataclass
class MigrationEntry:
    """Одна старая папка пресета и результат её разбора."""
    operator: str
    camera: str
    preset: str
    source_path: str
    status: str          # imported | skipped | duplicate | incomplete | old_dir
    detail: str = ""
    version_id: str = ""


@dataclass
class MigrationReport:
    entries: list[MigrationEntry] = field(default_factory=list)
    camera_txt_added: list[str] = field(default_factory=list)
    backup_path: str = ""
    backup_verified: bool = False

    @property
    def imported(self) -> list[MigrationEntry]:
        return [e for e in self.entries if e.status == "imported"]

    @property
    def skipped(self) -> list[MigrationEntry]:
        return [e for e in self.entries if e.status in ("skipped", "incomplete", "old_dir")]

    @property
    def duplicates(self) -> list[MigrationEntry]:
        return [e for e in self.entries if e.status == "duplicate"]

    def summary(self) -> str:
        return (
            f"Импортировано: {len(self.imported)}, "
            f"дубликатов: {len(self.duplicates)}, "
            f"пропущено: {len(self.skipped)}"
        )


class MigrationError(Exception):
    """Ошибка миграции."""


def _now_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def create_verified_backup(source_root: str, backup_root: str) -> tuple[str, bool]:
    """Создать и ПРОВЕРИТЬ резервную копию архива.

    Возвращает ``(путь_к_бэкапу, проверено_ли)``. Проверка — сверка SHA-256
    каждого файла исходника и копии + манифест.
    """
    src = Path(source_root)
    if not src.is_dir():
        raise MigrationError(f"Исходный архив не найден: {source_root}")

    dest = Path(backup_root) / f"setting-backup-{_now_tag()}"
    # Уникальность даже при двух запусках в одну секунду
    suffix = 1
    while dest.exists():
        dest = Path(backup_root) / f"setting-backup-{_now_tag()}-{suffix}"
        suffix += 1
    dest.mkdir(parents=True, exist_ok=False)

    manifest: dict[str, dict] = {}
    ok = True
    for dirpath, _dirnames, filenames in os.walk(src):
        for name in filenames:
            full = Path(dirpath) / name
            rel = full.relative_to(src).as_posix()
            try:
                dst = dest / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(full, dst)
                src_sha = fs_ops.hash_file(str(full))
                dst_sha = fs_ops.hash_file(str(dst))
                match = src_sha == dst_sha
                ok = ok and match
                manifest[rel] = {"size": full.stat().st_size, "sha256": src_sha,
                                 "verified": match}
            except OSError as e:
                ok = False
                manifest[rel] = {"error": str(e), "verified": False}

    (dest / "_backup_manifest.json").write_text(
        json.dumps({"created_at": _now_tag(), "verified": ok, "files": manifest},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(dest), ok


def _looks_like_old_dir(name: str) -> bool:
    return name.endswith("_OLD")


def _has_settings_files(root: str) -> bool:
    """Есть ли в папке хотя бы один файл настроек (не судим только по имени)."""
    return bool(discover_in_folder(root).accepted)


class Migrator:
    """Переносит старый архив в новую библиотеку с версиями."""

    def __init__(self, old_base: str, new_base: str, backup_root: str | None = None):
        self.old_base = old_base
        self.new_base = new_base
        self.backup_root = backup_root or str(Path(new_base).parent / "backups")
        self.store = VersionStore(base_path=new_base)

    # ------------------------------------------------------------------
    def run_backup(self) -> tuple[str, bool]:
        return create_verified_backup(self.old_base, self.backup_root)

    # ------------------------------------------------------------------
    def scan(self) -> list[MigrationEntry]:
        """Только разбор старого архива, без записи (предпросмотр миграции)."""
        return self._walk(apply=False)

    def migrate(self) -> MigrationReport:
        """Выполнить миграцию и вернуть отчёт."""
        report = MigrationReport()
        report.backup_path, report.backup_verified = self.run_backup()
        report.entries = self._walk(apply=True)
        report.camera_txt_added = self._migrate_camera_txt()
        return report

    # ------------------------------------------------------------------
    def _walk(self, apply: bool) -> list[MigrationEntry]:
        old_root = Path(self.old_base)
        cameraman = old_root / "cameraman"
        entries: list[MigrationEntry] = []

        if not cameraman.is_dir():
            return entries

        for op_dir in sorted(cameraman.iterdir()):
            if not op_dir.is_dir():
                continue
            operator = op_dir.name
            for cam_dir in sorted(op_dir.iterdir()):
                if not cam_dir.is_dir():
                    continue
                camera = cam_dir.name
                for preset_dir in sorted(cam_dir.iterdir()):
                    if not preset_dir.is_dir():
                        continue
                    folder = preset_dir.name
                    # Дата в имени -> имя пресета
                    preset = folder.split("_", 1)[1] if (
                        len(folder) > 9 and folder[:8].isdigit() and folder[8] == "_"
                    ) else folder

                    if _looks_like_old_dir(folder):
                        clean = preset[:-4] if preset.endswith("_OLD") else preset
                        entries.append(MigrationEntry(
                            operator, camera, clean, str(preset_dir), "old_dir",
                            "папка _OLD — обработана отдельно, не импортирована"))
                        continue

                    if not _has_settings_files(str(preset_dir)):
                        entries.append(MigrationEntry(
                            operator, camera, preset, str(preset_dir), "incomplete",
                            "нет файлов настроек — не считаем пресетом"))
                        continue

                    # Собрать файлы настроек
                    res = discover_in_folder(str(preset_dir))
                    files = settings_files_map(res)

                    if not apply:
                        entries.append(MigrationEntry(
                            operator, camera, preset, str(preset_dir), "imported",
                            f"готово к импорту: {len(files)} файл(ов)"))
                        continue

                    # Дедупликация: если версия с таким же набором хэшей уже есть
                    if self._is_duplicate(operator, camera, preset, files):
                        entries.append(MigrationEntry(
                            operator, camera, preset, str(preset_dir), "duplicate",
                            "такое же содержимое уже импортировано"))
                        continue

                    try:
                        rep = self.store.import_files(operator, camera, preset, files,
                                                      source_media=str(preset_dir),
                                                      note="миграция из старого архива")
                        entries.append(MigrationEntry(
                            operator, camera, preset, str(preset_dir), "imported",
                            f"{rep.files} файл(ов)", version_id=rep.version_id))
                    except Exception as e:  # noqa: BLE001
                        entries.append(MigrationEntry(
                            operator, camera, preset, str(preset_dir), "skipped", str(e)))
        return entries

    # ------------------------------------------------------------------
    def _is_duplicate(self, operator: str, camera: str, preset: str,
                      files: dict[str, str]) -> bool:
        new_hashes = {rel: fs_ops.hash_file(src) for rel, src in files.items()}
        for v in self.store.list_versions(operator, camera, preset):
            old = {r.rel_path: r.sha256 for r in v.files}
            if old == new_hashes:
                return True
        return False

    # ------------------------------------------------------------------
    def _migrate_camera_txt(self) -> list[str]:
        """Перенести список камер из старого ``main/camera.txt``."""
        old_file = Path(self.old_base) / "main" / "camera.txt"
        new_file = Path(self.new_base) / "main" / "camera.txt"
        if not old_file.is_file():
            return []

        existing: list[str] = []
        if new_file.is_file():
            existing = [ln.strip() for ln in new_file.read_text(encoding="utf-8").splitlines()]
        added: list[str] = []
        for line in old_file.read_text(encoding="utf-8").splitlines():
            cam = line.strip()
            if cam and cam not in existing and cam not in added:
                added.append(cam)

        # FX3A добавляем как известную модель, если её нет
        for extra in ("SonyFX3A",):
            if extra not in existing and extra not in added:
                added.append(extra)

        if added:
            new_file.parent.mkdir(parents=True, exist_ok=True)
            merged = existing + added
            new_file.write_text("\n".join(merged), encoding="utf-8")
        return added
