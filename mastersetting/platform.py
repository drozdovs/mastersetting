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


def install_root() -> str:
    """Каталог установки приложения (куда распакована сборка).

    Для ``.exe``/``.app`` — папка с исполняемым файлом; для запуска из исходников —
    корень проекта. Используется, чтобы НЕ хранить рабочую базу внутри
    обновляемого каталога установки (ТЗ).
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.realpath(base)
    if getattr(sys, "frozen", False):
        return os.path.realpath(os.path.dirname(sys.executable))
    return os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def is_install_path(candidate: str) -> bool:
    """Лежит ли путь внутри каталога установки приложения (ТЗ: нельзя)."""
    if not candidate:
        return True
    real = os.path.realpath(candidate)
    root = install_root()
    return real == root or real.startswith(root + os.sep)


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


def _windows_drive_type(drive: str) -> int:
    """Тип диска по Windows API (2 = DRIVE_REMOVABLE). 0, если недоступно.

    Отдельная функция — чтобы логику выбора носителя можно было проверить
    юнит-тестами без реальной Windows.
    """
    try:
        from ctypes import windll
    except ImportError:
        return 0
    try:
        return int(windll.kernel32.GetDriveTypeW(drive))
    except Exception:
        return 0


def _windows_removable_drives(start_letter: str) -> list[str]:
    import string

    start_letter = (start_letter or "E").upper()
    drives: list[str] = []
    for letter in string.ascii_uppercase:
        if letter < start_letter:
            continue
        drive = f"{letter}:\\"
        if not os.path.exists(drive):
            continue
        if _windows_drive_type(drive) == 2:  # DRIVE_REMOVABLE
            drives.append(drive)
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
    """Настоящий съёмный носитель (SD-карта/флешка), а не образ диска.

    Важные отличия:
      * смонтированный DMG (``Protocol == "Disk Image"``) — НЕ карта, хотя
        система помечает его «Removable»; писать в него нельзя;
      * виртуальные тома (``VirtualOrPhysical == "Virtual"``) — НЕ карта;
      * точка монтирования внутри каталога приложения — не карта.
    """
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

    # Явно исключаем образы дисков и виртуальные тома.
    # ВАЖНО: ключ называется BusProtocol (например 'Disk Image'), не Protocol.
    bus = str(info.get("BusProtocol") or "").strip().lower()
    if "disk image" in bus:
        return False
    if str(info.get("VirtualOrPhysical") or "").strip().lower() == "virtual":
        return False
    # Сетевые/облачные тома — тоже не карта
    if any(x in bus for x in ("network", "smb", "nfs", "http", "apple fabric")):
        return False
    try:
        app_dir = os.path.realpath(str(Path.home() / ".mastersetting"))
        if os.path.realpath(mount_point).startswith(app_dir + os.sep):
            return False
    except OSError:
        pass

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
# Защита от выбора «не той» цели
# ---------------------------------------------------------------------------

def is_system_path(candidate: str) -> bool:
    """True, если путь — системный диск/каталог или папка данных приложения.

    ТЗ запрещает выбирать системный диск или каталог приложения как карту:
    это защищает и от случайной записи в корень системы.
    """
    if not candidate:
        return True
    real = os.path.realpath(candidate)

    # Корень тома (C:\, "/") — всегда системный
    anchor = os.path.realpath(os.path.abspath(os.sep))
    if real.rstrip(os.sep) in (anchor.rstrip(os.sep), ""):
        return True
    drive, tail = os.path.splitdrive(real)
    if tail in ("", os.sep):  # сам корень диска/тома
        return True

    # Системные каталоги ОС
    system_roots = []
    if IS_WINDOWS:
        system_roots = [os.environ.get("SystemRoot", "C:\\Windows")]
        program = os.environ.get("ProgramFiles", "")
        if program:
            system_roots.append(program)
    elif IS_MACOS:
        system_roots = ["/System", "/Library", "/bin", "/sbin", "/usr"]
    else:
        system_roots = ["/bin", "/sbin", "/usr", "/etc", "/boot"]
    for root in system_roots:
        r = os.path.realpath(root)
        if real == r or real.startswith(r + os.sep):
            return True

    # Каталог данных приложения
    try:
        from .config import app_data_dir
        app_dir = os.path.realpath(str(app_data_dir()))
        if real == app_dir or real.startswith(app_dir + os.sep):
            return True
    except Exception:
        pass

    # Домашний каталог целиком (нельзя писать настройки в ~)
    home = os.path.realpath(str(Path.home()))
    return real == home


def safe_eject(mount_point: str) -> tuple[bool, str]:
    """По-безопасному извлечь носитель — ТОЛЬКО по явному действию оператора.

    Возвращает ``(ok, сообщение)``. На Windows используется Shell
    (``SHFileOperation`` с ``FOF_NO_UI``), на macOS — ``diskutil eject``,
    на Linux — ``umount``/``eject``. Никаких «тихих» попыток извлечения нет.
    """
    if not mount_point or not os.path.isdir(mount_point):
        return False, "Носитель не найден"
    try:
        if IS_WINDOWS:
            # Безопасное извлечение: dismount тома (НЕ удаление файлов).
            # ntpath: буква диска — понятие Windows, posix-разбор её не видит.
            import ntpath
            letter = ntpath.splitdrive(mount_point)[0]
            if not letter:
                return False, "Не удалось определить букву диска"
            r = subprocess.run(["mountvol", f"{letter}\\", "/p"],
                               capture_output=True, text=True)
            return r.returncode == 0, (
                "Карту можно вынуть" if r.returncode == 0
                else (r.stderr.strip() or r.stdout.strip() or "Windows не извлёк носитель"))
        if IS_MACOS:
            r = subprocess.run(["diskutil", "eject", mount_point],
                               capture_output=True, text=True)
            return r.returncode == 0, (
                "Карту можно вынуть" if r.returncode == 0
                else (r.stderr.strip() or "macOS не извлёк носитель"))
        for cmd in (["umount", mount_point], ["eject", mount_point]):
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0:
                return True, "Карту можно вынуть"
        return False, "Не удалось извлечь носитель"
    except Exception as e:  # noqa: BLE001
        return False, f"Не удалось извлечь носитель: {e}"


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
