# -*- coding: utf-8 -*-
"""Тесты ядра MasterSetting.

Тесты ниже работают только с новым ядром (версии + безопасное копирование).
Устаревший движок, копировавший корень карты целиком, удалён по ТЗ.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mastersetting import fs_ops
from mastersetting.catalog import Catalog
from mastersetting.filters import is_excluded, sanitize_name, validate_char

EXC_FILES = {"LASTCLIP.TXT", "lastclip.txt"}
EXC_EXT = {".mp4", ".mxf", ".mts", ".jpg"}


# ---------------------------------------------------------------------------
# Фильтры
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("  Ivan  ", "Ivan"),
    ("Иванов-Петров", "ИвановПетров"),
    ("Cam1_2024", "Cam12024"),
    ("a" * 50, "a" * 30),
    ("!!!", ""),
])
def test_sanitize_name(raw, expected):
    assert sanitize_name(raw, max_length=30) == expected


def test_validate_char():
    assert validate_char("A")
    assert validate_char("я")
    assert validate_char("5")
    assert not validate_char("-")
    assert not validate_char(" ")


def test_is_excluded():
    assert is_excluded("LASTCLIP.TXT", EXC_FILES, EXC_EXT)
    assert is_excluded("lastclip.txt", EXC_FILES, EXC_EXT)
    assert is_excluded("clip.MP4", EXC_FILES, EXC_EXT)
    assert is_excluded("shot.mxf", EXC_FILES, EXC_EXT)
    assert not is_excluded("settings.dat", EXC_FILES, EXC_EXT)
    assert not is_excluded("config.txt", EXC_FILES, EXC_EXT)


# ---------------------------------------------------------------------------
# fs_ops: манифест, копирование, проверка
# ---------------------------------------------------------------------------

def _make_card(root):
    """Имитация содержимого SD-карты с настройками и медиа."""
    os.makedirs(os.path.join(root, "PRIVATE", "SONY"), exist_ok=True)
    with open(os.path.join(root, "PRIVATE", "SONY", "SETTING1.DAT"), "wb") as f:
        f.write(b"settings-bytes-1")
    with open(os.path.join(root, "PRIVATE", "SONY", "SETTING2.DAT"), "wb") as f:
        f.write(b"settings-bytes-2" * 100)
    # Медиа — должно быть исключено
    with open(os.path.join(root, "CLIP0001.MP4"), "wb") as f:
        f.write(b"video" * 1000)
    with open(os.path.join(root, "LASTCLIP.TXT"), "w") as f:
        f.write("last")


def test_copy_tree_filters_and_verify(tmp_path):
    src = tmp_path / "card"
    dst = tmp_path / "archive"
    src.mkdir()
    _make_card(str(src))

    res = fs_ops.copy_tree(str(src), str(dst), EXC_FILES, EXC_EXT)

    assert res.files_copied == 2
    assert os.path.exists(dst / "PRIVATE" / "SONY" / "SETTING1.DAT")
    assert not os.path.exists(dst / "CLIP0001.MP4")
    assert not os.path.exists(dst / "LASTCLIP.TXT")

    assert fs_ops.verify_copy(str(src), str(dst), EXC_FILES, EXC_EXT) == []


def test_verify_copy_detects_mismatch(tmp_path):
    src = tmp_path / "card"
    dst = tmp_path / "archive"
    src.mkdir()
    _make_card(str(src))
    fs_ops.copy_tree(str(src), str(dst), EXC_FILES, EXC_EXT)
    # Портим файл в копии
    with open(dst / "PRIVATE" / "SONY" / "SETTING1.DAT", "wb") as f:
        f.write(b"corrupted")
    mism = fs_ops.verify_copy(str(src), str(dst), EXC_FILES, EXC_EXT)
    assert "PRIVATE/SONY/SETTING1.DAT" in mism


def test_safe_replace_dir_rollback(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "old.txt").write_text("old")

    def failing_copy(target):
        new_file = os.path.join(target, "new.txt")
        with open(new_file, "w") as f:
            f.write("new")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        fs_ops.safe_replace_dir(str(dest), failing_copy)

    # Откат: старая папка вернулась
    assert (dest / "old.txt").exists()
    assert not (dest / "new.txt").exists()


def test_cancel_stops_copy(tmp_path):
    src = tmp_path / "card"
    dst = tmp_path / "archive"
    src.mkdir()
    _make_card(str(src))

    with pytest.raises(fs_ops.CopyCancelled):
        fs_ops.copy_tree(
            str(src), str(dst), EXC_FILES, EXC_EXT,
            should_cancel=lambda: True,
        )


# ---------------------------------------------------------------------------
# Каталог
# ---------------------------------------------------------------------------

def test_catalog_events_and_stats(tmp_path):
    cat = Catalog(db_path=str(tmp_path / "c.db"))
    cat.add_operator("Иван")
    cat.add_camera("SonyFX3")
    assert "Иван" in cat.list_operators()
    assert "SonyFX3" in cat.list_cameras()

    cat.log_event("save", "ok", "Иван", "SonyFX3", "Основные", files=2, bytes_=10)
    cat.log_event("load", "ok", "Иван", "SonyFX3", "Основные", files=2, bytes_=10)
    cat.log_event("save", "error", "Пётр", "SonyFX3", "Основные", message="нет места")

    st = cat.stats()
    assert st["saves_ok"] == 1
    assert st["loads_ok"] == 1
    assert st["errors"] == 1

    events = cat.list_events()
    assert len(events) == 3


# ---------------------------------------------------------------------------
# Устаревший движок удалён: проверяем, что копирования корня карты нет
# ---------------------------------------------------------------------------

def test_legacy_root_copy_engine_is_gone():
    """ТЗ: приложение не должно копировать корень карты целиком.

    Раньше это делал ``mastersetting/engine.py``. Он удалён, и в ядре не
    должно остаться модуля, который копирует дерево с карты по расширениям.
    """
    import mastersetting
    here = os.path.dirname(os.path.abspath(mastersetting.__file__))
    assert not os.path.exists(os.path.join(here, "engine.py"))
    assert not os.path.exists(os.path.join(here, "naming.py"))
    # пакет импортируется и без них
    from mastersetting.library import PresetLibrary
    from mastersetting.settings_rules import discover_in_folder
    assert PresetLibrary is not None and discover_in_folder is not None
