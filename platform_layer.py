#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
platform_layer - платформенный слой для MasterSetting.

Изолирует всё, что зависит от операционной системы:
  * базовая папка с настройками (аналог C:/setting);
  * поиск съёмных носителей (Windows — буквы диска, macOS — /Volumes);
  * проверка свободного места;
  * открытие файла системным просмотрщиком.

Благодаря этому логика MasterSetting2.py не зависит от ОС.
"""

import os
import sys
import shutil
import subprocess

IS_WINDOWS = sys.platform == 'win32'
IS_MACOS = sys.platform == 'darwin'
IS_LINUX = sys.platform.startswith('linux')

# На Windows сохраняем прежнее поведение и прежнюю букву начала поиска
REMOVABLE_DRIVE_START = 'E'


def default_base_path():
    """Базовая папка с настройками.

    Windows — как было раньше (C:/setting).
    macOS/Linux — ~/MasterSetting (в домашней папке пользователя).
    Возвращает строку с абсолютным путём и прямыми слэшами.
    """
    if IS_WINDOWS:
        return "C:/setting"
    return str(os.path.join(os.path.expanduser("~"), "MasterSetting"))


# ============================================================
# СЪЁМНЫЕ НОСИТЕЛИ
# ============================================================

def get_removable_drives():
    """Список путей съёмных носителей.

    Windows: 'E:\\', 'F:\\' и т.д. (DRIVE_REMOVABLE).
    macOS:   '/Volumes/<ИМЯ>' для реально съёмных SD/USB.
    Linux:   точки монтирования в /media и /run/media.
    """
    if IS_WINDOWS:
        return _windows_removable_drives()
    if IS_MACOS:
        return _mac_removable_volumes()
    return _linux_removable_drives()


def _windows_removable_drives():
    import string
    try:
        from ctypes import windll
    except ImportError:
        return []

    drives = []
    for letter in string.ascii_uppercase:
        if letter < REMOVABLE_DRIVE_START:
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


def _mac_removable_volumes():
    """Фильтруем /Volumes: оставляем SD-карты и флешки, отбрасываем диски и DMG."""
    result = []
    volumes_root = "/Volumes"
    if not os.path.isdir(volumes_root):
        return result

    for name in sorted(os.listdir(volumes_root)):
        mount_point = os.path.join(volumes_root, name)
        if not os.path.ismount(mount_point):
            continue
        # Корневой (системный) том иногда виден как /Volumes/Macintosh HD -> '/'
        try:
            if os.path.realpath(mount_point) == os.path.realpath("/"):
                continue
        except OSError:
            continue
        if _mac_is_removable(mount_point):
            result.append(mount_point)
    return result


def _mac_is_removable(mount_point):
    """Съёмный ли том (по diskutil -plist)."""
    try:
        import plistlib
        raw = subprocess.run(
            ["diskutil", "info", "-plist", mount_point],
            capture_output=True, check=True,
        ).stdout
        info = plistlib.loads(raw)
    except Exception:
        return False

    if info.get("RemovableMedia") or info.get("Removable"):
        return True
    # Некоторые кардридеры: не внутренний + извлекаемый
    if info.get("Internal") is False and info.get("Ejectable"):
        return True
    return False


def _linux_removable_drives():
    result = []
    for root in ("/media", "/run/media"):
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, _ in os.walk(root):
            # Ограничиваемся двумя уровнями вложенности
            depth = dirpath[len(root):].count(os.sep)
            if depth >= 2:
                dirnames[:] = []
                continue
            if dirpath != root and os.path.ismount(dirpath):
                result.append(dirpath)
                dirnames[:] = []
    return result


# ============================================================
# ПРОЧЕЕ
# ============================================================

def check_free_space(path, required_bytes):
    """Проверка свободного места (кроссплатформенно, вместо GetDiskFreeSpaceExW)."""
    try:
        return shutil.disk_usage(path).free >= required_bytes
    except Exception:
        return True


def open_path(path):
    """Открыть файл системным приложением: os.startfile / open / xdg-open."""
    if IS_WINDOWS:
        os.startfile(path)  # type: ignore[attr-defined]
    elif IS_MACOS:
        subprocess.run(["open", str(path)])
    else:
        subprocess.run(["xdg-open", str(path)])
