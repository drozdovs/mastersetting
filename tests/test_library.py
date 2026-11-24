# -*- coding: utf-8 -*-
"""Тесты сервиса библиотеки: полный цикл карта -> библиотека -> карта."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mastersetting.library import LibraryError, PresetLibrary

REAL_FX3 = "/Users/sd/Desktop/Sony FX Drozdov/Settings/FX3/FX3.DAT"
REAL_FX3A = "/Users/sd/Desktop/Sony FX Drozdov/Settings/FX3A/FX3A.DAT"


def _mock_card(tmp_path, name="CARD1"):
    """Карта с настройкой Sony и видеоматериалом (который копировать нельзя)."""
    card = tmp_path / name
    d = card / "PRIVATE" / "SONY" / "SETTING" / "FX3" / "CAMSET"
    d.mkdir(parents=True)
    (d / "FX3.DAT").write_bytes(b"SONY0ILME-FX3" + b"\x00" * 200)
    (card / "CLIP.MP4").write_bytes(b"video" * 10000)
    (card / "LASTCLIP.TXT").write_text("last")
    return card


def _lib(tmp_path):
    return PresetLibrary(base_path=str(tmp_path / "base"))


# ---------------------------------------------------------------------------
# Планирование
# ---------------------------------------------------------------------------

def test_plan_takes_only_settings(tmp_path):
    card = _mock_card(tmp_path)
    plan = _lib(tmp_path).plan_from_media("SonyFX3", str(card))
    assert plan.file_count == 1
    assert list(plan.files.keys()) == ["PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT"]
    # Видео не попало
    assert not any(k.endswith(".MP4") for k in plan.files)
    # Формат не подтверждён (правила FX3 выключены до снятия путей с карты)
    assert plan.is_confirmed_format is False
    assert plan.detected_model == "ILME-FX3"   # модель прочитана из заголовка файла
    assert plan.warnings


def test_plan_marks_unknown_model_unconfirmed(tmp_path):
    card = _mock_card(tmp_path)
    plan = _lib(tmp_path).plan_from_media("PanasonicAG-CX350", str(card))
    assert plan.is_confirmed_format is False
    assert any("нет проверенного правила" in w for w in plan.warnings)


# ---------------------------------------------------------------------------
# Сохранение -> версия
# ---------------------------------------------------------------------------

def test_save_creates_new_version_only_from_settings(tmp_path):
    card = _mock_card(tmp_path)
    lib = _lib(tmp_path)
    rep = lib.save_from_media("Иван", "SonyFX3", "Основные", str(card))
    assert rep.ok
    versions = lib.store.list_versions("Иван", "SonyFX3", "Основные")
    assert len(versions) == 1
    v = versions[0]
    assert v.file_count == 1
    # В версии только настройка, без видео
    rels = [r.rel_path for r in v.files]
    assert rels == ["PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT"]


def test_save_twice_same_day_two_versions(tmp_path):
    card = _mock_card(tmp_path)
    lib = _lib(tmp_path)
    r1 = lib.save_from_media("Иван", "SonyFX3", "Основные", str(card))
    r2 = lib.save_from_media("Иван", "SonyFX3", "Основные", str(card))
    assert r1.version_id != r2.version_id
    assert len(lib.store.list_versions("Иван", "SonyFX3", "Основные")) == 2


def test_save_empty_media_errors(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    lib = _lib(tmp_path)
    with pytest.raises(LibraryError):
        lib.save_from_media("Иван", "SonyFX3", "Основные", str(empty))


# ---------------------------------------------------------------------------
# Запись на карту
# ---------------------------------------------------------------------------

def test_write_version_to_card_roundtrip(tmp_path):
    source = _mock_card(tmp_path, "SRC")
    lib = _lib(tmp_path)
    rep = lib.save_from_media("Иван", "SonyFX3", "Основные", str(source))
    version = lib.store.load_version("Иван", "SonyFX3", "Основные", rep.version_id)

    target = tmp_path / "TARGET"
    target.mkdir()
    wrep = lib.write_version_to_card(version, str(target))
    assert wrep.ok, wrep.message
    written = target / "PRIVATE" / "SONY" / "SETTING" / "FX3" / "CAMSET" / "FX3.DAT"
    assert written.read_bytes() == (source / "PRIVATE" / "SONY" / "SETTING" / "FX3" / "CAMSET" / "FX3.DAT").read_bytes()
    # Сверка на карте — чисто
    assert lib.verify_version_on_card(version, str(target)) == []


def test_write_does_not_touch_other_complect(tmp_path):
    """Запись FX3 не трогает комплект FX3A на карте."""
    source = _mock_card(tmp_path, "SRC")
    lib = _lib(tmp_path)
    rep = lib.save_from_media("Иван", "SonyFX3", "Основные", str(source))
    version = lib.store.load_version("Иван", "SonyFX3", "Основные", rep.version_id)

    target = tmp_path / "TARGET"
    other = target / "PRIVATE" / "SONY" / "SETTING" / "FX3A" / "CAMSET" / "FX3A.DAT"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"SONY0ILME-FX3A-OLD")

    lib.write_version_to_card(version, str(target))
    assert other.read_bytes() == b"SONY0ILME-FX3A-OLD"


def test_preview_write_reports_create_and_replace(tmp_path):
    source = _mock_card(tmp_path, "SRC")
    lib = _lib(tmp_path)
    rep = lib.save_from_media("Иван", "SonyFX3", "Основные", str(source))
    version = lib.store.load_version("Иван", "SonyFX3", "Основные", rep.version_id)

    empty_card = tmp_path / "EMPTY"
    empty_card.mkdir()
    prev = lib.preview_write(version, str(empty_card))
    assert any("будет создан" in line for line in prev.written)

    same_card = _mock_card(tmp_path, "SAME")
    prev2 = lib.preview_write(version, str(same_card))
    assert any("без изменений" in line for line in prev2.written)


def test_write_detects_missing_version_file(tmp_path):
    source = _mock_card(tmp_path, "SRC")
    lib = _lib(tmp_path)
    rep = lib.save_from_media("Иван", "SonyFX3", "Основные", str(source))
    version = lib.store.load_version("Иван", "SonyFX3", "Основные", rep.version_id)
    # Удаляем файл внутри версии
    root = lib.store.version_dir("Иван", "SonyFX3", "Основные", rep.version_id)
    for p in (root / "files").rglob("*"):
        if p.is_file():
            p.unlink()
    with pytest.raises(LibraryError):
        lib.write_version_to_card(version, str(tmp_path / "T"))
