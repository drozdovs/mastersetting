# -*- coding: utf-8 -*-
"""Тесты библиотеки пресетов с неизменяемыми версиями."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mastersetting.versioning import (
    PresetVersion,
    VersionStore,
    VersionStoreError,
    safe_component,
)


def _make_source(tmp_path, name="PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT", data=b"SONY0-settings"):
    """Создать исходный файл настроек и вернуть словарь {rel: abs}."""
    src = tmp_path / "card" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(data)
    return {name.replace("\\", "/"): str(src)}


def _store(tmp_path):
    return VersionStore(base_path=str(tmp_path / "base"))


# ---------------------------------------------------------------------------
# Безопасные компоненты пути
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", ["../etc/passwd", "..\\..\\win", "a/b", "a\\b", ".."])
def test_safe_component_strips_traversal(raw):
    got = safe_component(raw)
    assert "/" not in got and "\\" not in got
    assert got != ".."
    assert ".." not in got or got == ""


def test_safe_component_keeps_case_and_limits():
    assert safe_component("Основные") == "Основные"
    assert len(safe_component("a" * 60, max_length=30)) == 30


# ---------------------------------------------------------------------------
# Неизменяемость версий
# ---------------------------------------------------------------------------

def test_import_creates_version(tmp_path):
    store = _store(tmp_path)
    rep = store.import_files("Иван", "SonyFX3", "Основные",
                             _make_source(tmp_path), source_media="/Volumes/CARD")
    assert rep.ok
    assert rep.files == 1
    versions = store.list_versions("Иван", "SonyFX3", "Основные")
    assert len(versions) == 1
    v = versions[0]
    assert v.files[0].rel_path == "PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT"
    assert len(v.files[0].sha256) == 64
    assert v.source_media == "/Volumes/CARD"
    assert v.verified is True
    assert os.path.exists(os.path.join(rep.path, "files", "PRIVATE", "SONY", "SETTING", "FX3", "CAMSET", "FX3.DAT"))


def test_source_model_detected_from_file_header(tmp_path):
    """Исходная модель берётся из заголовка файла (SONY0ILME-FX3), а не из выбора."""
    from mastersetting.library import PresetLibrary

    src = tmp_path / "FX3.DAT"
    src.write_bytes(b"SONY0ILME-FX3" + b"\x00" * 100)
    lib = PresetLibrary(base_path=str(tmp_path / "base"))
    lib.save_from_media("Иван", "SonyFX3", "Основные",
                        media_root=str(tmp_path),
                        plan=lib.plan_from_media("SonyFX3", str(tmp_path)))
    v = lib.store.list_versions("Иван", "SonyFX3", "Основные")[0]
    assert v.source_model == "ILME-FX3"


def test_same_day_import_creates_new_version(tmp_path):
    """Повторный импорт в тот же день НЕ перезаписывает — создаёт новую версию."""
    store = _store(tmp_path)
    files = _make_source(tmp_path)
    r1 = store.import_files("Иван", "SonyFX3", "Основные", files)
    r2 = store.import_files("Иван", "SonyFX3", "Основные", files)
    assert r1.version_id != r2.version_id
    versions = store.list_versions("Иван", "SonyFX3", "Основные")
    assert len(versions) == 2
    # Обе версии на диске сосуществуют
    assert os.path.isdir(store.version_dir("Иван", "SonyFX3", "Основные", r1.version_id))
    assert os.path.isdir(store.version_dir("Иван", "SonyFX3", "Основные", r2.version_id))


def test_latest_version_is_newest(tmp_path):
    store = _store(tmp_path)
    r1 = store.import_files("Иван", "SonyFX3", "Основные", _make_source(tmp_path))
    r2 = store.import_files("Иван", "SonyFX3", "Основные", _make_source(tmp_path))
    latest = store.latest_version("Иван", "SonyFX3", "Основные")
    assert latest is not None
    assert latest.version_id == max(r1.version_id, r2.version_id)


def test_versions_are_immutable_on_disk(tmp_path):
    """Файлы версии не меняются при последующих импортах."""
    store = _store(tmp_path)
    files = _make_source(tmp_path, data=b"FIRST")
    r1 = store.import_files("Иван", "SonyFX3", "Основные", files)
    v_before = store.load_version("Иван", "SonyFX3", "Основные", r1.version_id)

    # Второй импорт с ДРУГИМ содержимым
    files2 = _make_source(tmp_path, data=b"SECOND-SECOND-SECOND")
    store.import_files("Иван", "SonyFX3", "Основные", files2)

    v_after = store.load_version("Иван", "SonyFX3", "Основные", r1.version_id)
    assert v_before.files[0].sha256 == v_after.files[0].sha256


# ---------------------------------------------------------------------------
# Защита путей
# ---------------------------------------------------------------------------

def test_reject_absolute_and_traversal_paths(tmp_path):
    store = _store(tmp_path)
    src = tmp_path / "f.dat"
    src.write_bytes(b"x")
    with pytest.raises(VersionStoreError):
        store.import_files("Иван", "SonyFX3", "Основные", {"/etc/passwd": str(src)})
    with pytest.raises(VersionStoreError):
        store.import_files("Иван", "SonyFX3", "Основные", {"../evil.dat": str(src)})


def test_reject_symlink_source(tmp_path):
    store = _store(tmp_path)
    real = tmp_path / "real.dat"
    real.write_bytes(b"x")
    link = tmp_path / "link.dat"
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError):
        pytest.skip("символические ссылки недоступны")
    with pytest.raises(VersionStoreError):
        store.import_files("Иван", "SonyFX3", "Основные", {"PRIVATE/link.dat": str(link)})


def test_reject_empty_file_set(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(VersionStoreError):
        store.import_files("Иван", "SonyFX3", "Основные", {})


def test_import_no_partial_on_missing_file(tmp_path):
    """Сбой импорта не оставляет «полупустую» версию и не создаёт мусор."""
    store = _store(tmp_path)
    root = store.preset_dir("Иван", "SonyFX3", "Основные")
    with pytest.raises(VersionStoreError):
        store.import_files("Иван", "SonyFX3", "Основные",
                           {"PRIVATE/x.dat": str(tmp_path / "nonexistent.dat")})
    assert store.list_versions("Иван", "SonyFX3", "Основные") == []
    # Временных папок не осталось
    if root.is_dir():
        assert [p.name for p in root.iterdir() if p.name.startswith(".tmp-")] == []


# ---------------------------------------------------------------------------
# Удаление
# ---------------------------------------------------------------------------

def test_delete_preset_requires_correct_count(tmp_path):
    store = _store(tmp_path)
    store.import_files("Иван", "SonyFX3", "Основные", _make_source(tmp_path))
    store.import_files("Иван", "SonyFX3", "Основные", _make_source(tmp_path))
    with pytest.raises(VersionStoreError):
        store.delete_preset("Иван", "SonyFX3", "Основные", confirm_versions=1)  # неверно
    store.delete_preset("Иван", "SonyFX3", "Основные", confirm_versions=2)
    assert store.list_presets("Иван", "SonyFX3") == []


def test_list_presets(tmp_path):
    store = _store(tmp_path)
    store.import_files("Иван", "SonyFX3", "Основные", _make_source(tmp_path))
    store.import_files("Иван", "SonyFX3", "Интервью", _make_source(tmp_path))
    assert store.list_presets("Иван", "SonyFX3") == ["Интервью", "Основные"]


def test_meta_roundtrip(tmp_path):
    store = _store(tmp_path)
    rep = store.import_files("Иван", "SonyFX3", "Основные", _make_source(tmp_path),
                             firmware="2.00", note="тест")
    v = store.load_version("Иван", "SonyFX3", "Основные", rep.version_id)
    assert v.firmware == "2.00"
    assert v.note == "тест"
    assert PresetVersion.from_json(v.to_json()).version_id == v.version_id
