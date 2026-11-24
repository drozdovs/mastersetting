# -*- coding: utf-8 -*-
"""Тесты CLI на безопасных командах (новое ядро)."""

import os
import sys

import pytest

import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cli


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Изолированные base_path/каталог, чтобы не трогать реальные данные."""
    base = tmp_path / "base"
    monkeypatch.setenv("MS_BASE_PATH", str(base))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path


def _card(tmp_path, tag=b"A"):
    card = tmp_path / "CARD"
    d = card / "PRIVATE" / "SONY" / "SETTING" / "FX3" / "CAMSET"
    d.mkdir(parents=True)
    (d / "FX3.DAT").write_bytes(b"SONY0" + tag * 40)
    (card / "CLIP.MP4").write_bytes(b"video" * 500)
    return card


def test_parser_has_safe_commands():
    p = cli.build_parser()
    for cmd in ("versions", "plan-save", "save-version", "preview-write",
                "write-version", "verify", "cards", "info", "stats"):
        assert cmd in p._subparsers._group_actions[0].choices  # noqa: SLF001


def test_parser_has_no_legacy_root_copy_commands():
    """Устаревшие команды, копировавшие корень карты, удалены (ТЗ)."""
    p = cli.build_parser()
    choices = p._subparsers._group_actions[0].choices  # noqa: SLF001
    assert "save" not in choices
    assert "load" not in choices
    assert "detect" not in choices


def test_inspect_lists_only_settings_paths(env, capsys):
    """Команда inspect показывает реальные пути — нужна для шлюза FX3/FX3A."""
    card = _card(env)
    rc = cli.main(["inspect", "--media", str(card)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT" in out["settings_files"]
    # Видео не должно попасть в настройки
    assert all(".MP4" not in p for p in out["settings_files"])
    # Но должно быть видно в полном списке с причиной отказа
    rejected = [f for f in out["all_files"] if not f["accepted"]]
    assert any("CLIP.MP4" in f["rel_path"] for f in rejected)


def test_plan_save_json(env, capsys):
    card = _card(env)
    rc = cli.main(["plan-save", "--camera", "SonyFX3", "--media", str(card)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT" in out
    assert ".MP4" not in out


def test_save_version_then_versions(env, capsys):
    card = _card(env)
    rc = cli.main(["save-version", "--operator", "Иван", "--camera", "SonyFX3",
                   "--preset", "Основные", "--media", str(card)])
    assert rc == 0
    capsys.readouterr()
    rc = cli.main(["versions", "--operator", "Иван", "--camera", "SonyFX3",
                   "--preset", "Основные"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "version_id" in out


def test_write_version_and_verify(env, capsys):
    src = _card(env, b"A")
    cli.main(["save-version", "--operator", "Иван", "--camera", "SonyFX3",
              "--preset", "Основные", "--media", str(src)])
    capsys.readouterr()

    target = env / "TARGET"
    target.mkdir()
    rc = cli.main(["write-version", "--operator", "Иван", "--camera", "SonyFX3",
                   "--preset", "Основные", "--card", str(target)])
    assert rc == 0
    capsys.readouterr()

    rc = cli.main(["verify", "--operator", "Иван", "--camera", "SonyFX3",
                   "--preset", "Основные", "--card", str(target)])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"ok": true' in out


def test_preview_write_lists_changes(env, capsys):
    src = _card(env, b"A")
    cli.main(["save-version", "--operator", "Иван", "--camera", "SonyFX3",
              "--preset", "Основные", "--media", str(src)])
    capsys.readouterr()
    target = env / "T2"
    target.mkdir()
    rc = cli.main(["preview-write", "--operator", "Иван", "--camera", "SonyFX3",
                   "--preset", "Основные", "--card", str(target)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "будет создан" in out


def test_verify_missing_version_errors(env, capsys):
    target = env / "T3"
    target.mkdir()
    rc = cli.main(["verify", "--operator", "Никто", "--camera", "SonyFX3",
                   "--preset", "Нет", "--card", str(target)])
    assert rc == 2


def test_write_to_missing_card_has_no_traceback(env, capsys):
    """Пропавшая карта: понятное сообщение, а не трассировка Python (ТЗ)."""
    src = _card(env)
    cli.main(["save-version", "--operator", "Иван", "--camera", "SonyFX3",
              "--preset", "Основные", "--media", str(src)])
    capsys.readouterr()

    gone = env / "GONE"  # карты нет
    rc = cli.main(["write-version", "--operator", "Иван", "--camera", "SonyFX3",
                   "--preset", "Основные", "--card", str(gone)])
    assert rc != 0, "пропавшая карта не должна выглядеть успехом"
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "Ошибка" in err
