# -*- coding: utf-8 -*-
"""Движок копирования с прогрессом, проверкой целостности и откатом.

Ключевые отличия от версии 1.9:
  * прогресс (done/total по файлам и байтам) — можно показывать процент;
  * поддержка отмены (``should_cancel``);
  * после копирования считается SHA-256 манифест и сверяется с источником;
  * атомарная замена: старая папка переименовывается, при ошибке — откат.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass, field
from typing import Callable

from .filters import is_excluded

# Сигнатуры колбэков
ProgressCb = Callable[["Progress"], None]
CancelCb = Callable[[], bool]


@dataclass
class Progress:
    """Прогресс операции копирования."""

    total_files: int = 0
    done_files: int = 0
    total_bytes: int = 0
    done_bytes: int = 0
    current: str = ""

    @property
    def percent(self) -> float:
        if self.total_bytes:
            return min(100.0, self.done_bytes / self.total_bytes * 100.0)
        if self.total_files:
            return min(100.0, self.done_files / self.total_files * 100.0)
        return 100.0


class CopyCancelled(Exception):
    """Операция отменена пользователем."""


@dataclass
class CopyResult:
    files_copied: int = 0
    bytes_copied: int = 0
    skipped: list[str] = field(default_factory=list)
    manifest: dict[str, str] = field(default_factory=dict)  # rel_path -> sha256


# ---------------------------------------------------------------------------
# Манифест и хеши
# ---------------------------------------------------------------------------

def hash_file(path: str, chunk: int = 1 << 20) -> str:
    """SHA-256 файла."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def build_manifest(
    root: str,
    excluded_files: set[str] | list[str],
    excluded_extensions: set[str] | list[str],
    progress: ProgressCb | None = None,
    should_cancel: CancelCb | None = None,
) -> dict[str, str]:
    """Манифест (относительный путь -> sha256) для всех копируемых файлов."""
    result: dict[str, str] = {}
    files = _collect_files(root, excluded_files, excluded_extensions)
    prog = Progress(total_files=len(files))
    for rel in files:
        if should_cancel and should_cancel():
            raise CopyCancelled()
        abs_path = os.path.join(root, rel)
        result[rel.replace(os.sep, "/")] = hash_file(abs_path)
        prog.done_files += 1
        prog.current = rel
        if progress:
            progress(prog)
    return result


def _collect_files(
    root: str,
    excluded_files: set[str] | list[str],
    excluded_extensions: set[str] | list[str],
) -> list[str]:
    """Относительные пути всех подлежащих копированию файлов."""
    out: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if is_excluded(name, excluded_files, excluded_extensions):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            out.append(rel)
    return out


# ---------------------------------------------------------------------------
# Копирование
# ---------------------------------------------------------------------------

def copy_tree(
    src: str,
    dst: str,
    excluded_files: set[str] | list[str],
    excluded_extensions: set[str] | list[str],
    progress: ProgressCb | None = None,
    should_cancel: CancelCb | None = None,
) -> CopyResult:
    """Рекурсивно скопировать содержимое ``src`` в ``dst`` с прогрессом.

    Существующие файлы в ``dst`` перезаписываются. Медиафайлы и
    ``LASTCLIP.TXT`` пропускаются.
    """
    files = _collect_files(src, excluded_files, excluded_extensions)
    total_bytes = 0
    for rel in files:
        try:
            total_bytes += os.path.getsize(os.path.join(src, rel))
        except OSError:
            pass

    prog = Progress(total_files=len(files), total_bytes=total_bytes)
    result = CopyResult()

    os.makedirs(dst, exist_ok=True)

    for rel in files:
        if should_cancel and should_cancel():
            raise CopyCancelled()
        src_file = os.path.join(src, rel)
        dst_file = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(dst_file) or dst, exist_ok=True)
        try:
            _copy_one(src_file, dst_file)
            result.files_copied += 1
            try:
                result.bytes_copied += os.path.getsize(dst_file)
            except OSError:
                pass
        except Exception:
            result.skipped.append(rel)
        prog.done_files += 1
        prog.current = rel
        prog.done_bytes = result.bytes_copied
        if progress:
            progress(prog)

    return result


def _copy_one(src_file: str, dst_file: str) -> None:
    """Копирование одного файла с перезаписью и устойчивостью к атрибутам."""
    if os.path.exists(dst_file):
        try:
            os.remove(dst_file)
        except OSError:
            pass
    try:
        shutil.copy2(src_file, dst_file)
    except Exception:
        # copy2 может упасть на метаданных (напр. на некоторых ФС) — повтор без них
        shutil.copyfile(src_file, dst_file)


# ---------------------------------------------------------------------------
# Атомарная замена с откатом
# ---------------------------------------------------------------------------

def safe_replace_dir(
    dest_path: str,
    copy_fn: Callable[[str], None],
    verify: bool = True,
) -> None:
    """Атомарно заменить папку ``dest_path`` результатом ``copy_fn``.

    Схема: существующая папка -> ``dest_path_OLD``; вызов ``copy_fn(dest)``;
    при успехе ``_OLD`` удаляется, при ошибке происходит откат.
    """
    old_path = None
    if os.path.exists(dest_path):
        old_path = dest_path + "_OLD"
        shutil.rmtree(old_path, ignore_errors=True)
        shutil.move(dest_path, old_path)

    try:
        os.makedirs(dest_path, exist_ok=True)
        copy_fn(dest_path)
        if old_path and os.path.exists(old_path):
            shutil.rmtree(old_path, ignore_errors=True)
    except Exception:
        # Откат
        if old_path and os.path.exists(old_path):
            shutil.rmtree(dest_path, ignore_errors=True)
            shutil.move(old_path, dest_path)
        raise


def verify_copy(
    src_root: str,
    dst_root: str,
    excluded_files: set[str] | list[str],
    excluded_extensions: set[str] | list[str],
) -> list[str]:
    """Сверить копию с источником. Возвращает список расхождений (пусто = ок)."""
    src_manifest = build_manifest(src_root, excluded_files, excluded_extensions)
    mismatches: list[str] = []
    for rel, src_hash in src_manifest.items():
        dst_file = os.path.join(dst_root, rel)
        if not os.path.exists(dst_file):
            mismatches.append(rel)
            continue
        try:
            if hash_file(dst_file) != src_hash:
                mismatches.append(rel)
        except OSError:
            mismatches.append(rel)
    return mismatches
