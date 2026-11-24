# -*- coding: utf-8 -*-
"""Тест генератора тестовой карты (используется при проверке на Windows)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deploy.make_test_card import make_card


def test_make_card_creates_settings_and_media(tmp_path):
    root = str(tmp_path / "CARD")
    os.makedirs(root)
    created = make_card(root)

    # Файлы настроек обеих моделей на месте
    assert os.path.isfile(os.path.join(root, "PRIVATE", "SONY", "SETTING",
                                       "FX3", "CAMSET", "FX3.DAT"))
    assert os.path.isfile(os.path.join(root, "PRIVATE", "SONY", "SETTING",
                                       "FX3A", "CAMSET", "FX3A.DAT"))

    # Медиа действительно создано (чтобы проверять его исключение)
    assert os.path.isfile(os.path.join(root, "CLIP0001.MP4"))
    assert any(c.endswith(".MXF") for c in created)


def test_make_card_settings_have_sony_magic(tmp_path):
    """Сгенерированные настройки должны распознаваться как файлы настроек."""
    from mastersetting.settings_rules import discover_in_folder

    root = str(tmp_path / "CARD")
    os.makedirs(root)
    make_card(root)

    res = discover_in_folder(root)
    accepted = {c.rel_path for c in res.accepted}
    assert accepted == {
        "PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT",
        "PRIVATE/SONY/SETTING/FX3A/CAMSET/FX3A.DAT",
    }
    # Видео — только в отклонённых
    rejected = {c.rel_path for c in res.rejected}
    assert any(r.endswith(".MP4") for r in rejected)
    assert any(r.endswith(".MXF") for r in rejected)


def test_make_card_refuses_nonempty_dir(tmp_path):
    from deploy.make_test_card import main

    root = tmp_path / "CARD"
    root.mkdir()
    (root / "already.txt").write_text("x")
    assert main([str(root)]) == 3  # отказ, ничего не трогаем
