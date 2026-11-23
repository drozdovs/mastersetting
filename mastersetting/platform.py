# -*- coding: utf-8 -*-
"""Работа с носителями и файловой системой (кроссплатформенно).

Здесь собрано всё, что зависит от ОС:
  * поиск съёмных носителей (Windows — буквы диска, macOS — /Volumes);
  * проверка защиты от записи и свободного места;
  * размер директории;
  * открытие файла системным приложением.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


# ---------------------------------------------------------------------------
# Съёмные носители
# ---------------------------------------------------------------------------

def get_removable_drives(start_letter: str = "E") -> list[str]:
    """Список путей съёмных носителей.

    Windows: ``E:\\``, ``F:\\`` ... (DRIVE_REMOVABLE).
    macOS:   ``/Volumes/<ИМЯ>`` для реально съёмных SD/USB.
    Linux:   точки монтирования в /media и /run/media.
    """
    if IS_WINDOWS:
        return _windows_removable_drives(start_letter)
    if IS_MACOS:
        return _mac_removable_volumes()
    return _linux_removable_drives()


def _windows_removable_drives(start_letter: str) -> list[str]:
    import string

    try:
        from ctypes import windll
    except ImportError:
        return []

    start_letter = (start_letter or "E").upper()
    drives: list[str] = []
    for letter in string.ascii_uppercase:
        if letter < start_letter:
            continue
        drive = f"{letter}:\\"
        if not os.path.exists(drive):
            continue
        try:
            if windll.kernel32.GetDriveTypeW(drive) == 2:  # DRIVE_REMOVABLE
                drives.append(drive)
        except Exception:
            pass
    return drives


def _mac_removable_volumes() -> list[str]:
    result: list[str] = []
    volumes_root = "/Volumes"
    if not os.path.isdir(volumes_root):
        return result

    for name in sorted(os.listdir(volumes_root)):
        mount_point = os.path.join(volumes_root, name)
        if not os.path.ismount(mount_point):
            continue
        try:
            if os.path.realpath(mount_point) == os.path.realpath("/"):
                continue
        except OSError:
            continue
        if _mac_is_removable(mount_point):
            result.append(mount_point)
    return result


def _mac_is_removable(mount_point: str) -> bool:
    try:
        import plistlib

        raw = subprocess.run(
            ["diskutil", "info", "-plist", mount_point],
            capture_output=True,
            check=True,
        ).stdout
        info = plistlib.loads(raw)
    except Exception:
        return False

    if info.get("RemovableMedia") or info.get("Removable"):
        return True
    if info.get("Internal") is False and info.get("Ejectable"):
        return True
    return False


def _linux_removable_drives() -> list[str]:
    result: list[str] = []
    for root in ("/media", "/run/media"):
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, _ in os.walk(root):
            depth = dirpath[len(root):].count(os.sep)
            if depth >= 2:
                dirnames[:] = []
                continue
            if dirpath != root and os.path.ismount(dirpath):
                result.append(dirpath)
                dirnames[:] = []
    return result


def check_usb_drive(start_letter: str = "E") -> tuple[str | None, str | None]:
    """Проверка наличия ровно одной флешки.

    Возвращает ``(путь, None)`` либо ``(None, сообщение_об_ошибке)``.
    """
    drives = get_removable_drives(start_letter)
    if len(drives) == 0:
        return None, "Вставьте карту с настройками!"
    if len(drives) > 1:
        return None, (
            "Обнаружено несколько сменных носителей. "
            "Оставьте только одну флешку в кардридере!"
        )
    return drives[0], None


# ---------------------------------------------------------------------------
# Проверки носителя
# ---------------------------------------------------------------------------

def is_write_protected(drive_path: str) -> bool:
    """True, если на носитель нельзя записывать."""
    test_file = os.path.join(drive_path, ".write_test.tmp")
    try:
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("test")
        os.remove(test_file)
        return False
    except Exception:
        return True


def check_free_space(path: str, required_bytes: int) -> bool:
    """Достаточно ли свободного места (кроссплатформенно)."""
    try:
        return shutil.disk_usage(path).free >= required_bytes
    except Exception:
        return True


def get_directory_size(path: str) -> int:
    """Размер директории в байтах."""
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                if os.path.exists(fp):
                    total += os.path.getsize(fp)
            except OSError:
                pass
    return total


# ---------------------------------------------------------------------------
# Открытие файлов
# ---------------------------------------------------------------------------

def open_path(path: str) -> None:
    """Открыть файл системным приложением: startfile / open / xdg-open."""
    if IS_WINDOWS:
        os.startfile(path)  # type: ignore[attr-defined]
    elif IS_MACOS:
        subprocess.run(["open", str(path)])
    else:
        subprocess.run(["xdg-open", str(path)])
