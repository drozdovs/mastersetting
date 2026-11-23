# -*- coding: utf-8 -*-
"""Тесты ядра MasterSetting."""

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mastersetting.catalog import Catalog
from mastersetting.config import Config
from mastersetting.engine import ArchiveEngine, EngineError
from mastersetting.filters import is_excluded, sanitize_name, validate_char
from mastersetting import fs_ops
from mastersetting.naming import parse_settings_folder, settings_dir, settings_folder_name

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
# Имена и пути
# ---------------------------------------------------------------------------

def test_settings_folder_name():
    from datetime import datetime
    name = settings_folder_name("Основные", datetime(2024, 5, 7))
    assert name == "20240507_Основные"


def test_parse_settings_folder():
    assert parse_settings_folder("20240507_Основные") == ("20240507", "Основные")
    assert parse_settings_folder("БезДаты") == (None, "БезДаты")


def test_settings_dir(tmp_path):
    p = settings_dir(str(tmp_path), "Иван", "SonyFX3", "Основные")
    assert p.parent.name == "SonyFX3"
    assert p.parent.parent.name == "Иван"
    assert p.parent.parent.parent.name == "cameraman"


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

    unsynced = cat.unsynced_events()
    assert len(unsynced) == 3
    cat.mark_synced([e["id"] for e in unsynced])
    assert cat.unsynced_events() == []


# ---------------------------------------------------------------------------
# Движок: полный цикл save -> load через локальные пути
# ---------------------------------------------------------------------------

def _config(tmp_path):
    cfg = Config()
    cfg.base_path = str(tmp_path / "base")
    os.makedirs(cfg.base_path, exist_ok=True)
    return cfg


def test_engine_save_and_load_roundtrip(tmp_path):
    cfg = _config(tmp_path)
    cat = Catalog(db_path=str(tmp_path / "c.db"))
    eng = ArchiveEngine(config=cfg, catalog=cat)

    card = tmp_path / "card"
    card.mkdir()
    _make_card(str(card))

    rep = eng.save("Иван", "SonyFX3", "Основные", from_path=str(card))
    assert rep.ok, rep.message
    assert rep.files == 2

    # Файл настроек лежит в архиве
    archives = cat.list_archives("Иван", "SonyFX3")
    assert len(archives) == 1
    assert os.path.exists(os.path.join(archives[0]["path"], "PRIVATE", "SONY", "SETTING1.DAT"))

    # Загрузка на пустую «флешку»
    card2 = tmp_path / "card2"
    card2.mkdir()
    rep2 = eng.load("Иван", "SonyFX3", "Основные", to_path=str(card2))
    assert rep2.ok, rep2.message
    assert os.path.exists(card2 / "PRIVATE" / "SONY" / "SETTING2.DAT")

    st = cat.stats()
    assert st["saves_ok"] == 1 and st["loads_ok"] == 1


def test_engine_no_overwrite_without_flag(tmp_path):
    cfg = _config(tmp_path)
    cat = Catalog(db_path=str(tmp_path / "c.db"))
    eng = ArchiveEngine(config=cfg, catalog=cat)
    card = tmp_path / "card"
    card.mkdir()
    _make_card(str(card))

    eng.save("Иван", "SonyFX3", "Основные", from_path=str(card))
    with pytest.raises(EngineError):
        eng.save("Иван", "SonyFX3", "Основные", from_path=str(card))
    # С разрешением — ок
    rep = eng.save("Иван", "SonyFX3", "Основные", from_path=str(card), overwrite=True)
    assert rep.ok


def test_engine_validates_input(tmp_path):
    cfg = _config(tmp_path)
    eng = ArchiveEngine(config=cfg, catalog=Catalog(db_path=str(tmp_path / "c.db")))
    with pytest.raises(EngineError):
        eng.save("", "SonyFX3", "Основные", from_path=str(tmp_path))
