# -*- coding: utf-8 -*-
"""Тесты офлайн-справки: файл есть и не тянет внешние ресурсы."""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HELP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "docs", "help", "index.html")


def test_help_file_exists():
    assert os.path.isfile(HELP)


def test_help_has_no_external_resources():
    html = open(HELP, encoding="utf-8").read()
    # Никаких CDN, шрифтов и скриптов извне
    assert "http://" not in html
    assert "https://" not in html
    assert "<script" not in html.lower()
    # Стили только встроенные
    assert "<style>" in html


def test_help_has_no_remote_src_or_href_to_internet():
    html = open(HELP, encoding="utf-8").read()
    for attr in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert not attr.startswith(("http://", "https://", "//")), attr


def test_help_covers_key_topics():
    html = open(HELP, encoding="utf-8").read().lower()
    for topic in ["сохранить с карты", "записать на карту", "верси", "fx3"]:
        assert topic in html, topic


def test_help_is_readable_utf8():
    html = open(HELP, encoding="utf-8").read()
    assert "MasterSetting" in html
