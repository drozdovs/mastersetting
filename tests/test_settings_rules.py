# -*- coding: utf-8 -*-
"""Тесты правил: копируем ТОЛЬКО файлы настроек, не весь корень карты.

Используются реальные образцы FX3.DAT / FX3A.DAT (сигнатура SONY0), если они
доступны, иначе — синтетические фикстуры с той же сигнатурой.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mastersetting.settings_rules import (
    MEDIA_EXTENSIONS,
    discover_in_folder,
    looks_like_settings_file,
    rule_for,
    settings_files_map,
)

REAL_FX3 = "/Users/sd/Desktop/Sony FX Drozdov/Settings/FX3/FX3.DAT"
REAL_FX3A = "/Users/sd/Desktop/Sony FX Drozdov/Settings/FX3A/FX3A.DAT"


def _card(tmp_path):
    """Имитация карты: настройки Sony + видео + фото + служебные файлы."""
    card = tmp_path / "card"
    (card / "PRIVATE" / "SONY" / "SETTING" / "FX3" / "CAMSET").mkdir(parents=True)
    (card / "PRIVATE" / "SONY" / "SETTING" / "FX3" / "CAMSET" / "FX3.DAT").write_bytes(
        b"SONY0ILME-FX3" + b"\x00" * 100)
    (card / "PRIVATE" / "SONY").mkdir(parents=True, exist_ok=True)
    (card / "PRIVATE" / "SONY" / "SONYCARD.IND").write_bytes(b"index")
    # Медиа — должно быть исключено
    (card / "CLIP0001.MP4").write_bytes(b"video" * 5000)
    (card / "PHOTO.JPG").write_bytes(b"photo" * 1000)
    (card / "LASTCLIP.TXT").write_text("last")
    # Неизвестный крупный файл без расширения — запрещён
    (card / "MYSTERY.bin").write_bytes(b"\x00" * (9 * 1024 * 1024))
    return card


# ---------------------------------------------------------------------------
# Сигнатура
# ---------------------------------------------------------------------------

def test_looks_like_settings_file_synthetic(tmp_path):
    good = tmp_path / "good.dat"
    good.write_bytes(b"SONY0" + b"\x00" * 50)
    bad = tmp_path / "bad.dat"
    bad.write_bytes(b"NOTSONY" + b"\x00" * 50)
    assert looks_like_settings_file(str(good))
    assert not looks_like_settings_file(str(bad))


@pytest.mark.skipif(not os.path.exists(REAL_FX3), reason="нет реального образца FX3")
def test_real_fx3_sample_is_settings():
    assert looks_like_settings_file(REAL_FX3)


@pytest.mark.skipif(not os.path.exists(REAL_FX3A), reason="нет реального образца FX3A")
def test_real_fx3a_sample_is_settings():
    assert looks_like_settings_file(REAL_FX3A)


def test_empty_and_huge_rejected(tmp_path):
    empty = tmp_path / "e.dat"
    empty.write_bytes(b"")
    assert not looks_like_settings_file(str(empty))
    huge = tmp_path / "h.dat"
    with open(huge, "wb") as f:
        f.write(b"SONY0")
        f.seek(40 * 1024 * 1024)  # в режиме "wb" seek работает: файл станет ~40 МБ
        f.write(b"\x00")
    assert not looks_like_settings_file(str(huge))


# ---------------------------------------------------------------------------
# Просмотр папки: только настройки
# ---------------------------------------------------------------------------

def test_discover_accepts_only_settings(tmp_path):
    card = _card(tmp_path)
    res = discover_in_folder(str(card))
    accepted = {c.rel_path for c in res.accepted}
    assert accepted == {"PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT"}


def test_discover_rejects_media_and_index(tmp_path):
    card = _card(tmp_path)
    res = discover_in_folder(str(card))
    rejected = {c.rel_path: c.reason for c in res.rejected}
    assert "CLIP0001.MP4" in rejected
    assert "PHOTO.JPG" in rejected
    assert "LASTCLIP.TXT" in rejected
    assert "PRIVATE/SONY/SONYCARD.IND" in rejected
    assert "MYSTERY.bin" in rejected


def test_media_never_counted_as_settings(tmp_path):
    for ext in (".MP4", ".mxf", ".MTS", ".jpg", ".MOV"):
        f = tmp_path / f"x{ext}"
        f.write_bytes(b"SONY0")  # даже с сигнатурой медиа не берём
        # медиа отклоняется по расширению, а не принимается
        res = discover_in_folder(str(tmp_path))
        accepted = {c.rel_path for c in res.accepted}
        assert f.name not in accepted


def test_discover_ignores_symlink_outside(tmp_path):
    card = _card(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.dat"
    secret.write_bytes(b"SONY0" + b"\x00" * 20)
    link = card / "link.dat"
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):
        pytest.skip("символические ссылки недоступны")
    res = discover_in_folder(str(card))
    accepted = {c.rel_path for c in res.accepted}
    assert "link.dat" not in accepted


def test_settings_map_prefix(tmp_path):
    card = _card(tmp_path)
    res = discover_in_folder(str(card))
    m = settings_files_map(res)
    assert list(m.keys()) == ["PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT"]
    m2 = settings_files_map(res, root_prefix="EXTRA")
    assert list(m2.keys()) == ["EXTRA/PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT"]


# ---------------------------------------------------------------------------
# Правила моделей: FX3/FX3A пока НЕ подтверждены
# ---------------------------------------------------------------------------

def test_fx3_rules_not_confirmed_yet():
    for fam in ("SonyFX3", "SonyFX3A"):
        rule = rule_for(fam)
        assert rule is not None
        assert rule.confirmed is False, "нельзя включать парную запись без проверки на карте"
        assert rule.settings_dirs == ()


def test_unknown_model_has_no_rule():
    assert rule_for("PanasonicAG-CX350") is None


def test_media_extensions_include_mxf_mts():
    """Исправление бага 1.9: .mxf и .mts реально исключаются."""
    assert ".mxf" in MEDIA_EXTENSIONS
    assert ".mts" in MEDIA_EXTENSIONS
