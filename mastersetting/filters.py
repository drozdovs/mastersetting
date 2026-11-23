# -*- coding: utf-8 -*-
"""Фильтры и очистка имён."""

from __future__ import annotations

import os
import re

# Символы, допустимые в именах (буквы лат/кир + цифры)
_ALLOWED_NAME_RE = re.compile(r"[^a-zA-Zа-яА-ЯёЁ0-9]")


def sanitize_name(name: str, max_length: int = 30) -> str:
    """Очистка имени: только буквы и цифры, обрезка по краям и по длине."""
    name = (name or "").strip()
    name = _ALLOWED_NAME_RE.sub("", name)
    return name[:max_length]


def validate_char(char: str) -> bool:
    """Допустим ли одиночный символ для поля ввода."""
    if not char:
        return True
    return bool(re.match(r"[a-zA-Zа-яА-ЯёЁ0-9]", char))


def is_excluded(
    filename: str,
    excluded_files: set[str] | list[str],
    excluded_extensions: set[str] | list[str],
) -> bool:
    """Нужно ли исключить файл из копирования (по имени или расширению)."""
    excluded_files = {f.lower() for f in excluded_files}
    excluded_extensions = {e.lower() for e in excluded_extensions}
    if filename.lower() in excluded_files:
        return True
    ext = os.path.splitext(filename)[1].lower()
    return ext in excluded_extensions
