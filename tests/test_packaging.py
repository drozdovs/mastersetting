# -*- coding: utf-8 -*-
"""Стражи сборки: то, что легко потерять незаметно.

Проверяем, что офлайн-справка попадает в ОБЕ сборки (Windows .exe и macOS .app),
что она самодостаточна (без интернета/CDN), и что в .exe включена проверка
подписи обновлений (cryptography).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC_WIN = os.path.join(ROOT, "deploy", "MasterSetting.spec")
SPEC_MAC = os.path.join(ROOT, "deploy", "MasterSetting-macos.spec")
HELP = os.path.join(ROOT, "docs", "help", "index.html")


def test_help_file_is_self_contained():
    """ТЗ: справка — самодостаточный локальный HTML без CDN/интернета."""
    html = open(HELP, encoding="utf-8").read().lower()
    for bad in ("http://", "https://", "//cdn", "googleapis", "<script src"):
        assert bad not in html, f"справка тянет внешний ресурс: {bad}"


def test_help_uses_canonical_action_names():
    """ТЗ: однозначные названия, без слова «Загрузить» для обоих направлений."""
    html = open(HELP, encoding="utf-8").read()
    assert "Сохранить с карты" in html
    assert "Записать на карту" in html
    assert "Загрузить" not in html


def test_help_is_bundled_on_both_platforms():
    """Офлайн-справка обязана попадать и в Windows, и в macOS сборку."""
    win = open(SPEC_WIN, encoding="utf-8").read()
    mac = open(SPEC_MAC, encoding="utf-8").read()
    assert "docs/help" in win, "справка не включена в Windows .exe"
    assert "docs/help" in mac, "справка не включена в macOS .app"


def test_cryptography_is_bundled_for_signed_updates():
    """ТЗ: проверка подписи обновления. Если cryptography не попадёт в сборку,
    приложение будет отклонять все обновления — это тихий дефект."""
    win = open(SPEC_WIN, encoding="utf-8").read()
    assert "cryptography" in win


def test_requirements_pin_cryptography():
    req = open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
    assert "cryptography" in req


def _load_prepare_module(name):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        name, os.path.join(ROOT, "deploy", "prepare_fx3_card.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _synthetic_samples(tmp_path):
    """Два файла с корректными заголовками Sony (SONY0 + модель)."""
    fx3 = tmp_path / "FX3.DAT"
    fx3a = tmp_path / "FX3A.DAT"
    fx3.write_bytes(b"SONY0ILME-FX3" + b"\x00" * 32 + b"fx3")
    fx3a.write_bytes(b"SONY0ILME-FX3A" + b"\x00" * 32 + b"fx3a")
    return str(fx3), str(fx3a)


def test_prepare_fx3_card_lays_out_native_paths(tmp_path):
    """Скрипт физической проверки кладёт оба образца в нативные пути Sony."""
    mod = _load_prepare_module("prepare_fx3_card")
    fx3, fx3a = _synthetic_samples(tmp_path)

    card = tmp_path / "CARD"
    card.mkdir()
    rc = mod.main(["--card", str(card), "--fx3", fx3, "--fx3a", fx3a])
    assert rc == 0

    from mastersetting.settings_rules import detect_source_model
    got_fx3 = os.path.join(str(card), *mod.TARGETS["fx3"].split("/"))
    got_fx3a = os.path.join(str(card), *mod.TARGETS["fx3a"].split("/"))
    assert detect_source_model(got_fx3) == "ILME-FX3"
    assert detect_source_model(got_fx3a) == "ILME-FX3A"


def test_prepare_fx3_card_swapped_samples_refused(tmp_path, capsys):
    """Перепутанные образцы (FX3 в слот FX3A) должны быть отклонены."""
    mod = _load_prepare_module("prepare_fx3_card2")
    fx3, fx3a = _synthetic_samples(tmp_path)

    card = tmp_path / "CARD"
    card.mkdir()
    # намеренно меняем местами
    rc = mod.main(["--card", str(card), "--fx3", fx3a, "--fx3a", fx3])
    assert rc != 0
    assert not any((card / p).exists() for p in mod.TARGETS.values())


def test_prepare_fx3_card_dry_run_writes_nothing(tmp_path):
    mod = _load_prepare_module("prepare_fx3_card3")
    fx3, fx3a = _synthetic_samples(tmp_path)
    card = tmp_path / "CARD"
    card.mkdir()
    rc = mod.main(["--card", str(card), "--dry-run",
                   "--fx3", fx3, "--fx3a", fx3a])
    assert rc == 0
    assert not any((card / p).exists() for p in mod.TARGETS.values())
