# -*- coding: utf-8 -*-
"""Тесты безопасной записи на носитель."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mastersetting import fs_ops
from mastersetting.safe_write import SafeWriter, WriteError, plan_required_bytes, volume_id


def _src(tmp_path, name, data):
    p = tmp_path / "src" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return str(p)


def _card(tmp_path):
    card = tmp_path / "card"
    card.mkdir()
    return card


# ---------------------------------------------------------------------------
# Предварительные проверки
# ---------------------------------------------------------------------------

def test_preflight_rejects_traversal(tmp_path):
    card = _card(tmp_path)
    files = {"../evil.dat": _src(tmp_path, "a.dat", b"x")}
    with pytest.raises(WriteError):
        SafeWriter(str(card)).preflight(files)


def test_preflight_rejects_absolute(tmp_path):
    card = _card(tmp_path)
    files = {"/etc/passwd": _src(tmp_path, "a.dat", b"x")}
    with pytest.raises(WriteError):
        SafeWriter(str(card)).preflight(files)


def test_preflight_rejects_windows_absolute(tmp_path):
    card = _card(tmp_path)
    files = {"C:/Windows/x.dat": _src(tmp_path, "a.dat", b"x")}
    with pytest.raises(WriteError):
        SafeWriter(str(card)).preflight(files)


def test_preflight_rejects_symlink_source(tmp_path):
    card = _card(tmp_path)
    real = tmp_path / "real.dat"
    real.write_bytes(b"x")
    link = tmp_path / "link.dat"
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError):
        pytest.skip("символические ссылки недоступны")
    with pytest.raises(WriteError):
        SafeWriter(str(card)).preflight({"PRIVATE/a.dat": str(link)})


def test_plan_required_bytes_has_margin():
    assert plan_required_bytes({"a": 1000}) > 1000
    assert plan_required_bytes({}) >= 8 * 1024 * 1024


# ---------------------------------------------------------------------------
# Успешная запись
# ---------------------------------------------------------------------------

def test_write_creates_dirs_and_verifies(tmp_path):
    card = _card(tmp_path)
    files = {"PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT": _src(tmp_path, "FX3.DAT", b"SONY0-data")}
    rep = SafeWriter(str(card)).write(files)
    assert rep.ok, rep.message
    assert rep.written == ["PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT"]
    target = card / "PRIVATE" / "SONY" / "SETTING" / "FX3" / "CAMSET" / "FX3.DAT"
    assert target.read_bytes() == b"SONY0-data"


def test_write_replaces_only_named_files(tmp_path):
    """Запись меняет только указанные файлы, остальные данные карты нетронуты."""
    card = _card(tmp_path)
    other = card / "OTHER" / "keep.txt"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"keep me")
    existing = card / "PRIVATE" / "SONY" / "SETTING" / "FX3A" / "CAMSET" / "FX3A.DAT"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"OLD-FX3A")

    files = {"PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT": _src(tmp_path, "FX3.DAT", b"NEW-FX3")}
    rep = SafeWriter(str(card)).write(files)
    assert rep.ok
    assert other.read_bytes() == b"keep me"
    assert existing.read_bytes() == b"OLD-FX3A"  # чужой комплект не тронут


def test_write_overwrites_target_and_removes_backup(tmp_path):
    card = _card(tmp_path)
    target = card / "PRIVATE" / "x.dat"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"OLD")
    files = {"PRIVATE/x.dat": _src(tmp_path, "x.dat", b"NEW")}
    rep = SafeWriter(str(card)).write(files)
    assert rep.ok
    assert target.read_bytes() == b"NEW"
    assert not (card / "PRIVATE" / "x.dat.ms-bak").exists()


# ---------------------------------------------------------------------------
# Частичный сбой: нет ложного успеха, есть откат
# ---------------------------------------------------------------------------

def test_partial_failure_reports_error_not_success(tmp_path, monkeypatch):
    card = _card(tmp_path)
    files = {
        "PRIVATE/a.dat": _src(tmp_path, "a.dat", b"AAA"),
        "PRIVATE/b.dat": _src(tmp_path, "b.dat", b"BBB"),
    }

    real_hash = fs_ops.hash_file

    def flaky_hash(path, *a, **k):
        # Ломаем сверку целевого файла b.dat после записи
        if str(path).endswith("b.dat") and "a.dat" not in str(path):
            return "неверный-хеш"
        return real_hash(path, *a, **k)

    monkeypatch.setattr(fs_ops, "hash_file", flaky_hash)

    rep = SafeWriter(str(card)).write(files)
    assert rep.ok is False
    assert rep.message  # точный отчёт, не пусто


def test_rollback_restores_previous_content(tmp_path, monkeypatch):
    """При сбое на втором файле первый возвращается к прежнему содержимому."""
    card = _card(tmp_path)
    first = card / "PRIVATE" / "a.dat"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"ORIGINAL-A")
    second = card / "PRIVATE" / "b.dat"
    second.write_bytes(b"ORIGINAL-B")

    files = {
        "PRIVATE/a.dat": _src(tmp_path, "a.dat", b"NEW-A"),
        "PRIVATE/b.dat": _src(tmp_path, "b.dat", b"NEW-B"),
    }

    real_replace = os.replace

    def failing_replace(src, dst, *a, **k):
        # Проваливаем именно ЗАПИСЬ второго файла (из .partial), но не откат из .ms-bak
        if str(dst) == str(second) and str(src).endswith(".partial"):
            raise OSError("диск отвалился")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", failing_replace)
    rep = SafeWriter(str(card)).write(files)

    assert rep.ok is False
    assert rep.rolled_back is True
    # a.dat вернулся к прежнему содержимому (а не остался NEW-A)
    assert first.read_bytes() == b"ORIGINAL-A"
    assert second.read_bytes() == b"ORIGINAL-B"
    # Временные/бэкап-файлы не остались
    leftovers = [p.name for p in (card / "PRIVATE").iterdir()
                 if p.name.endswith(".partial") or p.name.endswith(".ms-bak")]
    assert leftovers == []


# ---------------------------------------------------------------------------
# Отмена и подмена тома
# ---------------------------------------------------------------------------

def test_cancel_stops_write(tmp_path):
    card = _card(tmp_path)
    files = {"PRIVATE/a.dat": _src(tmp_path, "a.dat", b"AAA")}
    rep = SafeWriter(str(card)).write(files, should_cancel=lambda: True)
    assert rep.ok is False
    assert "тмен" in rep.message  # "отменена"


def test_volume_id_is_stable(tmp_path):
    card = _card(tmp_path)
    assert volume_id(str(card)) == volume_id(str(card))
    assert volume_id(str(card)) != ""
