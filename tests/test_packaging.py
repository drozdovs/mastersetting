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
