# -*- coding: utf-8 -*-
"""Безопасная запись файлов на носитель.

Требования ТЗ, которые реализует модуль:

* перед записью — проверка доступности записи, места с запасом и идентификатора тома;
* сначала файлы готовятся во временной области, затем переносятся на место;
* после записи файлы **перечитываются** и сверяются по SHA-256;
* при сбое — точный отчёт: какие файлы записаны, какие нет; безопасный откат
  затронутых файлов, если он возможен;
* никаких разрушающих действий без явного вызова; символические ссылки не
  поддерживаются; ``..`` и абсолютные пути в относительных запрещены.

Модуль не знает о GUI и не извлекает карту автоматически.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import fs_ops
from .platform import check_free_space

# Запас свободного места поверх размера данных (10% + 8 МБ)
SPACE_MARGIN_RATIO = 0.10
SPACE_MARGIN_MIN = 8 * 1024 * 1024

# Префикс временного файла рядом с целевым (скрытый)
_TMP_PREFIX = "."


class WriteError(Exception):
    """Ошибка записи (понятный пользователю текст)."""


@dataclass
class FileOutcome:
    rel_path: str
    ok: bool
    reason: str = ""
    backup_path: str = ""


@dataclass
class WriteReport:
    ok: bool
    message: str
    written: list[str] = field(default_factory=list)
    failed: list[FileOutcome] = field(default_factory=list)
    rolled_back: bool = False
    bytes_: int = 0


def _require_safe_rel(rel: str) -> None:
    if not rel or rel.startswith(("/", "\\")) or "\\" in rel or "\x00" in rel:
        raise WriteError(f"Опасный путь: {rel!r}")
    if len(rel) > 1 and rel[1] == ":":
        raise WriteError(f"Абсолютный путь Windows: {rel!r}")
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise WriteError(f"Недопустимый путь: {rel!r}")


def volume_id(path: str) -> str:
    """Идентификатор тома/носителя для защиты от подмены карты между шагами.

    Возвращает стабильную строку (или "" если определить нельзя). Основной
    смысл — сравнить значение ДО и ПОСЛЕ и заметить подмену носителя.

    На Windows берём серийный номер тома через ``GetVolumeInformationW`` — он
    остаётся прежним у одного носителя и меняется при подмене карты. На macOS и
    Linux опираемся на ``st_dev`` (номер устройства тома) и неизменяемые при
    записи характеристики файловой системы.
    """
    # Windows: серийный номер тома — самый надёжный признак подмены.
    try:
        if os.name == "nt":
            import ctypes
            root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
            serial = ctypes.c_ulong(0)
            ok = ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(root), None, 0, ctypes.byref(serial),
                None, None, None, 0)
            if ok:
                return f"vol={serial.value}"
    except Exception:  # noqa: BLE001
        pass

    try:
        st = os.statvfs(path) if hasattr(os, "statvfs") else None
    except OSError:
        st = None
    try:
        st_dev = os.stat(path).st_dev
    except OSError:
        st_dev = 0
    parts = [f"dev={st_dev}"]
    if st is not None:
        parts.append(f"bsize={st.f_bsize}")
        parts.append(f"blocks={st.f_blocks}")
    return "|".join(parts)


def _hash_ok(path: str, expected: str, expected_size: int | None = None) -> bool:
    try:
        if expected_size is not None and os.path.getsize(path) != expected_size:
            return False
        return fs_ops.hash_file(path) == expected
    except OSError:
        return False


def plan_required_bytes(files: dict[str, int]) -> int:
    """Сколько места нужно с запасом."""
    total = sum(max(0, s) for s in files.values())
    margin = max(SPACE_MARGIN_MIN, int(total * SPACE_MARGIN_RATIO))
    return total + margin


class SafeWriter:
    """Пишет набор файлов на носитель безопасно и проверяемо.

    ``files`` — словарь ``{rel_path: abs_source}``.
    ``dest_root`` — корень носителя (например, ``/Volumes/CARD`` или ``E:\\``).
    """

    def __init__(self, dest_root: str):
        self.dest_root = dest_root

    def preflight(self, files: dict[str, str]) -> None:
        """Проверки ДО записи: не системный/не каталог приложения, доступность, место."""
        root = os.path.realpath(self.dest_root)
        if not os.path.isdir(root):
            raise WriteError(f"Носитель недоступен: {self.dest_root}")

        # Не писать в корень системы или в каталог приложения
        sys_root = os.path.realpath(os.sep)
        if root == sys_root:
            raise WriteError("Нельзя писать в корень системы")
        app_dir = os.path.realpath(str(Path.home() / ".mastersetting"))
        if root == app_dir or root.startswith(app_dir + os.sep):
            raise WriteError("Нельзя писать в каталог приложения")

        for rel in files:
            _require_safe_rel(rel)

        sizes = {}
        for rel, src in files.items():
            if not os.path.isfile(src):
                raise WriteError(f"Исходный файл не найден: {src}")
            if os.path.islink(src):
                raise WriteError(f"Символическая ссылка не поддерживается: {src}")
            sizes[rel] = os.path.getsize(src)

        need = plan_required_bytes(sizes)
        if not check_free_space(self.dest_root, need):
            raise WriteError("Недостаточно свободного места на носителе")

        # Проверка возможности записи реальным пробным файлом
        probe = os.path.join(self.dest_root, f"{_TMP_PREFIX}ms-write-test")
        try:
            with open(probe, "wb") as f:
                f.write(b"ok")
            os.remove(probe)
        except OSError as e:
            raise WriteError(
                "Носитель защищён от записи или недоступен для записи"
            ) from e

    def write(self, files: dict[str, str], verify: bool = True,
              protect_volume: bool = True,
              progress=None, should_cancel=None) -> WriteReport:
        """Записать набор файлов с проверкой и безопасным откатом.

        Алгоритм на каждый файл:
          1. копия существующего целевого файла в ``.bak`` (для отката);
          2. запись во временный ``.<имя>.partial``;
          3. сверка временного с источником по SHA-256;
          4. атомарная замена целевого временным;
          5. повторная сверка целевого;
          6. удаление ``.bak`` при успехе.
        При сбое — откат ВСЕХ уже заменённых файлов из ``.bak``.
        """
        self.preflight(files)

        vol_before = volume_id(self.dest_root) if protect_volume else ""

        order = list(files.items())
        total = len(order)
        report = WriteReport(ok=True, message="")
        backups: dict[str, str] = {}   # dest -> backup abs
        written: list[str] = []

        try:
            for idx, (rel, src) in enumerate(order):
                if should_cancel and should_cancel():
                    raise fs_ops.CopyCancelled()

                dest = os.path.join(self.dest_root, *rel.split("/"))
                dest_dir = os.path.dirname(dest)
                os.makedirs(dest_dir, exist_ok=True)

                # Защита от подмены носителя между шагами
                if protect_volume and volume_id(self.dest_root) != vol_before:
                    raise WriteError("Носитель был заменён во время записи. Остановлено.")

                if os.path.islink(dest):
                    raise WriteError(f"Целевой путь — ссылка, запись запрещена: {dest}")

                # 1. Резервная копия существующего файла (храним до полного успеха)
                if os.path.exists(dest):
                    bak = dest + ".ms-bak"
                    shutil.copy2(dest, bak)
                    backups[dest] = bak

                # 2. Временный файл
                tmp = os.path.join(dest_dir, _TMP_PREFIX + os.path.basename(dest) + ".partial")
                shutil.copy2(src, tmp)

                # 3. Сверка временного с источником
                src_sha = ""
                if verify:
                    src_sha = fs_ops.hash_file(src)
                    if not _hash_ok(tmp, src_sha):
                        os.remove(tmp)
                        raise WriteError(f"Проверка копии не сошлась: {rel}")

                # 4. Атомарная замена
                os.replace(tmp, dest)

                # 5. Повторная сверка целевого
                if verify and not _hash_ok(dest, src_sha):
                    raise WriteError(f"После записи содержимое не совпало: {rel}")

                written.append(rel)
                report.bytes_ += os.path.getsize(dest)
                if progress:
                    progress(idx + 1, total, rel)

        except fs_ops.CopyCancelled:
            self._cleanup_partials(files)
            rolled = self._rollback(backups)
            return WriteReport(ok=False, message="Операция отменена пользователем",
                               written=written, rolled_back=rolled)
        except Exception as e:  # noqa: BLE001
            self._cleanup_partials(files)
            rolled = self._rollback(backups)
            report.ok = False
            report.written = written
            report.rolled_back = rolled
            report.message = str(e)
            report.failed.append(FileOutcome(rel_path="", ok=False, reason=str(e)))
            return report

        # Полный успех: удаляем все резервные копии
        for bak in list(backups.values()):
            try:
                os.remove(bak)
            except OSError:
                pass

        report.written = written
        report.message = f"Записано файлов: {len(written)}"
        return report

    def _rollback(self, backups: dict[str, str]) -> bool:
        """Вернуть целевые файлы из резервных копий. True если всё вернулось."""
        all_ok = True
        for dest, bak in backups.items():
            try:
                if os.path.exists(bak):
                    os.replace(bak, dest)
            except OSError:
                all_ok = False
        return all_ok

    def _cleanup_partials(self, files: dict[str, str]) -> None:
        """Убрать оставшиеся временные ``.<имя>.partial`` с носителя."""
        for rel in files:
            dest = os.path.join(self.dest_root, *rel.split("/"))
            tmp = os.path.join(os.path.dirname(dest),
                               _TMP_PREFIX + os.path.basename(dest) + ".partial")
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
