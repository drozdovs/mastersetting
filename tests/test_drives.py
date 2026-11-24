# -*- coding: utf-8 -*-
"""Тесты кроссплатформенного определения съёмных носителей.

Ключевой случай (реальный баг): на macOS смонтированный DMG определяется
системой как «Removable» и попадал в список карт — приложение предлагало
записать настройки в Docker.dmg / установщик вместо SD-карты.
"""

import os
import plistlib
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mastersetting import platform as plat


def _fake_diskutil(monkeypatch, info: dict):
    """Подменить вызов diskutil info -plist заданным словарём."""
    def fake_run(cmd, **kwargs):
        class R:
            stdout = plistlib.dumps(info)
        return R()

    monkeypatch.setattr(plat.subprocess, "run", fake_run)


# ---------------------------------------------------------------------------
# macOS: различаем карту и образ диска
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "darwin", reason="только macOS")
def test_disk_image_is_not_a_card(monkeypatch):
    """DMG («BusProtocol = Disk Image») не должен считаться картой."""
    _fake_diskutil(monkeypatch, {
        "RemovableMedia": True, "Removable": True, "Ejectable": True,
        "Internal": False, "BusProtocol": "Disk Image",
    })
    assert plat._mac_is_removable("/Volumes/Docker") is False


@pytest.mark.skipif(sys.platform != "darwin", reason="только macOS")
def test_virtual_volume_is_not_a_card(monkeypatch):
    _fake_diskutil(monkeypatch, {
        "Removable": True, "Internal": False, "Ejectable": True,
        "BusProtocol": "USB", "VirtualOrPhysical": "Virtual",
    })
    assert plat._mac_is_removable("/Volumes/Virtual") is False


@pytest.mark.skipif(sys.platform != "darwin", reason="только macOS")
def test_real_usb_card_is_detected(monkeypatch):
    _fake_diskutil(monkeypatch, {
        "RemovableMedia": True, "Removable": True, "Ejectable": True,
        "Internal": False, "BusProtocol": "USB",
    })
    assert plat._mac_is_removable("/Volumes/NO NAME") is True


@pytest.mark.skipif(sys.platform != "darwin", reason="только macOS")
def test_internal_disk_is_not_a_card(monkeypatch):
    _fake_diskutil(monkeypatch, {
        "Removable": False, "Internal": True, "Ejectable": False,
        "BusProtocol": "PCI-Express",
    })
    assert plat._mac_is_removable("/Volumes/Macintosh HD") is False


@pytest.mark.skipif(sys.platform != "darwin", reason="только macOS")
def test_network_volume_is_not_a_card(monkeypatch):
    _fake_diskutil(monkeypatch, {
        "Removable": True, "Internal": False, "Ejectable": True,
        "BusProtocol": "Apple Fabric",
    })
    assert plat._mac_is_removable("/Volumes/Share") is False


@pytest.mark.skipif(sys.platform != "darwin", reason="только macOS")
def test_diskutil_failure_is_safe(monkeypatch):
    """Если diskutil недоступен/ошибся — не считаем том картой (безопасно)."""
    def boom(*a, **k):
        raise OSError("diskutil недоступен")
    monkeypatch.setattr(plat.subprocess, "run", boom)
    assert plat._mac_is_removable("/Volumes/Whatever") is False


# ---------------------------------------------------------------------------
# Реальный прогон на этой машине
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "darwin", reason="только macOS")
def test_real_system_has_no_disk_images_listed():
    """На текущей машине смонтированы DMG — их быть в списке не должно."""
    drives = plat.get_removable_drives()
    for d in drives:
        raw = subprocess.run(["diskutil", "info", "-plist", d],
                             capture_output=True).stdout
        info = plistlib.loads(raw)
        bus = str(info.get("BusProtocol") or "").lower()
        assert "disk image" not in bus, f"образ диска попал в список карт: {d}"


# ---------------------------------------------------------------------------
# Windows: логика выбора буквы диска (проверяем без реальной Windows)
# ---------------------------------------------------------------------------

def test_windows_counts_only_removable(monkeypatch):
    """Windows: только DRIVE_REMOVABLE(=2) попадает в список карт."""
    monkeypatch.setattr(plat, "IS_WINDOWS", True)
    monkeypatch.setattr(plat.os.path, "exists", lambda p: True)

    def fake_type(drive):
        return {"E:\\": 2, "F:\\": 3, "G:\\": 2, "H:\\": 5}.get(drive, 0)

    monkeypatch.setattr(plat, "_windows_drive_type", fake_type)
    drives = plat.get_removable_drives("E")
    assert drives == ["E:\\", "G:\\"]


def test_windows_respects_start_letter(monkeypatch):
    """Windows: буквы ниже стартовой не перебираются (не трогаем C:/D:)."""
    monkeypatch.setattr(plat, "IS_WINDOWS", True)
    monkeypatch.setattr(plat.os.path, "exists", lambda p: True)
    seen = []

    def fake_type(drive):
        seen.append(drive)
        return 2

    monkeypatch.setattr(plat, "_windows_drive_type", fake_type)
    plat.get_removable_drives("G")
    assert "C:\\" not in seen and "F:\\" not in seen
    assert "G:\\" in seen


def test_windows_missing_drive_skipped(monkeypatch):
    monkeypatch.setattr(plat, "IS_WINDOWS", True)
    monkeypatch.setattr(plat.os.path, "exists", lambda p: p == "E:\\")
    monkeypatch.setattr(plat, "_windows_drive_type", lambda d: 2)
    assert plat.get_removable_drives("E") == ["E:\\"]


def test_windows_api_failure_is_safe(monkeypatch):
    """Сбой WinAPI -> диск не считается картой (безопаснее промолчать)."""
    monkeypatch.setattr(plat, "IS_WINDOWS", True)
    monkeypatch.setattr(plat.os.path, "exists", lambda p: True)
    monkeypatch.setattr(plat, "_windows_drive_type", lambda d: 0)
    assert plat.get_removable_drives("E") == []


def test_safe_eject_uses_mountvol_on_windows(monkeypatch, tmp_path):
    """Windows: безопасное извлечение через mountvol /p по явному действию."""
    monkeypatch.setattr(plat, "IS_WINDOWS", True)
    monkeypatch.setattr(plat, "IS_MACOS", False)
    monkeypatch.setattr(plat.os.path, "isdir", lambda p: True)
    calls = {}

    class R:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        return R()

    monkeypatch.setattr(plat.subprocess, "run", fake_run)
    ok, msg = plat.safe_eject("E:\\")
    assert ok is True
    assert calls["cmd"][0] == "mountvol"
    assert calls["cmd"][-1] == "/p"


def test_safe_eject_missing_media_reports(monkeypatch):
    monkeypatch.setattr(plat.os.path, "isdir", lambda p: False)
    ok, msg = plat.safe_eject("/Volumes/Gone")
    assert ok is False and "не найден" in msg.lower()
