# -*- coding: utf-8 -*-
"""Тесты миграции старого архива C:/setting в новую библиотеку."""

import json
import os
import sys
from pathlib import Path


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mastersetting.migration import (
    Migrator,
    create_verified_backup,
)
from mastersetting.versioning import VersionStore


def _settings_bytes(tag=b"A"):
    return b"SONY0ILME-FX3" + tag * 50


def _old_archive(tmp_path):
    """Смоделировать старый C:/setting."""
    old = tmp_path / "old"
    # Валидный пресет
    p1 = old / "cameraman" / "Иван" / "SonyFX3" / "20260101_Основные"
    (p1 / "PRIVATE" / "SONY" / "SETTING" / "FX3" / "CAMSET").mkdir(parents=True)
    (p1 / "PRIVATE" / "SONY" / "SETTING" / "FX3" / "CAMSET" / "FX3.DAT").write_bytes(_settings_bytes(b"A"))
    (p1 / "CLIP.MP4").write_bytes(b"video" * 1000)  # медиа не должно импортироваться

    # Папка без настроек — не считаем пресетом
    p2 = old / "cameraman" / "Иван" / "SonyFX3" / "20260102_Пустая"
    p2.mkdir(parents=True)
    (p2 / "readme.txt").write_text("нет настроек", encoding="utf-8")

    # Папка _OLD — обрабатывается отдельно
    p3 = old / "cameraman" / "Иван" / "SonyFX3" / "20251231_Старое_OLD"
    (p3 / "PRIVATE").mkdir(parents=True)
    (p3 / "PRIVATE" / "x.dat").write_bytes(_settings_bytes(b"O"))

    # camera.txt
    (old / "main").mkdir(parents=True)
    (old / "main" / "camera.txt").write_text("SonyFX3\nPanasonic270\n",
                                             encoding="utf-8")
    return old


# ---------------------------------------------------------------------------
# Бэкап
# ---------------------------------------------------------------------------

def test_backup_is_verified(tmp_path):
    old = _old_archive(tmp_path)
    path, verified = create_verified_backup(str(old), str(tmp_path / "bkp"))
    assert verified is True
    assert os.path.isdir(path)
    manifest = json.loads((Path(path) / "_backup_manifest.json").read_text(encoding="utf-8"))
    assert manifest["verified"] is True
    assert manifest["files"]  # не пусто


def test_backup_copies_media_too(tmp_path):
    """Бэкап копирует ВСЁ (в т.ч. медиа) — он про сохранность, а не про фильтр."""
    old = _old_archive(tmp_path)
    path, verified = create_verified_backup(str(old), str(tmp_path / "bkp"))
    assert verified
    assert os.path.exists(os.path.join(path, "cameraman", "Иван", "SonyFX3",
                                       "20260101_Основные", "CLIP.MP4"))


# ---------------------------------------------------------------------------
# Разбор (без записи)
# ---------------------------------------------------------------------------

def test_scan_classifies(tmp_path):
    old = _old_archive(tmp_path)
    m = Migrator(old_base=str(old), new_base=str(tmp_path / "new"))
    entries = m.scan()
    statuses = {(e.operator, e.camera, e.preset): e.status for e in entries}
    assert statuses[("Иван", "SonyFX3", "Основные")] == "imported"
    assert statuses[("Иван", "SonyFX3", "Пустая")] == "incomplete"
    assert ("Иван", "SonyFX3", "Старое") in statuses  # _OLD разобран отдельно
    assert statuses[("Иван", "SonyFX3", "Старое")] == "old_dir"


def test_scan_does_not_write(tmp_path):
    old = _old_archive(tmp_path)
    m = Migrator(old_base=str(old), new_base=str(tmp_path / "new"))
    m.scan()
    assert not os.path.exists(tmp_path / "new" / "cameraman")


# ---------------------------------------------------------------------------
# Миграция
# ---------------------------------------------------------------------------

def test_migrate_imports_only_settings(tmp_path):
    old = _old_archive(tmp_path)
    m = Migrator(old_base=str(old), new_base=str(tmp_path / "new"))
    rep = m.migrate()
    assert rep.backup_verified is True
    assert len(rep.imported) == 1
    assert "SonyFX3" in rep.camera_txt_added
    assert "SonyFX3A" in rep.camera_txt_added  # FX3A добавлен

    store = VersionStore(base_path=str(tmp_path / "new"))
    versions = store.list_versions("Иван", "SonyFX3", "Основные")
    assert len(versions) == 1
    rels = [r.rel_path for r in versions[0].files]
    assert rels == ["PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT"]  # без CLIP.MP4


def test_migrate_skips_old_and_incomplete(tmp_path):
    old = _old_archive(tmp_path)
    m = Migrator(old_base=str(old), new_base=str(tmp_path / "new"))
    rep = m.migrate()
    presets = {e.preset for e in rep.imported}
    assert "Пустая" not in presets
    assert "Старое" not in presets


def test_migrate_is_idempotent(tmp_path):
    """Повторный запуск не создаёт дубликатов."""
    old = _old_archive(tmp_path)
    m1 = Migrator(old_base=str(old), new_base=str(tmp_path / "new"))
    m1.migrate()
    store = VersionStore(base_path=str(tmp_path / "new"))
    assert len(store.list_versions("Иван", "SonyFX3", "Основные")) == 1

    m2 = Migrator(old_base=str(old), new_base=str(tmp_path / "new"))
    rep2 = m2.migrate()
    assert store.list_versions("Иван", "SonyFX3", "Основные")  # существует
    assert len(store.list_versions("Иван", "SonyFX3", "Основные")) == 1
    assert len(rep2.duplicates) == 1


def test_migrate_keeps_old_data_untouched(tmp_path):
    old = _old_archive(tmp_path)
    before = sorted(str(p) for p in Path(old).rglob("*"))
    m = Migrator(old_base=str(old), new_base=str(tmp_path / "new"))
    m.migrate()
    after = sorted(str(p) for p in Path(old).rglob("*"))
    assert before == after  # старый архив не тронут


def test_camera_txt_new_gets_fx3a(tmp_path):
    old = _old_archive(tmp_path)
    m = Migrator(old_base=str(old), new_base=str(tmp_path / "new"))
    m.migrate()
    txt = (tmp_path / "new" / "main" / "camera.txt").read_text(encoding="utf-8")
    assert "SonyFX3A" in txt
    assert "Panasonic270" in txt


def test_default_base_path_is_not_hardcoded_c_setting(monkeypatch):
    """Дефект 1.9: жёсткий C:/setting. Теперь путь настраиваемый и вне установки."""
    from mastersetting import config as cfg

    monkeypatch.setattr(cfg, "IS_WINDOWS", True)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\op\AppData\Local")
    p = cfg.default_base_path().replace("\\", "/").lower()
    assert "c:/setting" not in p, "путь всё ещё жёстко задан как C:/setting"
    assert p.endswith("setting")
    assert "appdata" in p  # внутри каталога данных, а не установки

    # Для миграции старый путь по-прежнему распознаётся
    monkeypatch.delenv("MS_LEGACY_BASE", raising=False)
    assert cfg.legacy_base_path().replace("\\", "/").lower() == "c:/setting"
