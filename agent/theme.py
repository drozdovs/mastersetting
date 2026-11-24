# -*- coding: utf-8 -*-
"""Визуальные токены тёмной темы (в духе shadcn/ui).

Важно: это НЕ настоящие React-компоненты shadcn/ui. CustomTkinter не умеет
рендерить React. Здесь воспроизведена только визуальная система: строгая
типографика, спокойные поверхности, читаемые статусы.
"""

# Поверхности
BG = "#09090b"
PANEL = "#111114"
PANEL2 = "#18181b"
LINE = "#303036"

# Текст
TEXT = "#fafafa"
MUTED = "#a1a1aa"

# Акценты/статусы
BLUE = "#93c5fd"
OK = "#86efac"
WARN = "#fbbf24"
DANGER = "#fca5a5"
ACCENT = "#e4e4e7"

# Шрифты (системы: SF на macOS, Segoe UI на Windows)
FONT_FAMILY = None  # None -> системный по умолчанию

SIZES = {
    "h1": 22,
    "h2": 16,
    "h3": 13,
    "body": 13,
    "small": 11,
    "tiny": 10,
}


def status_color(kind: str) -> str:
    return {
        "ok": OK,
        "warn": WARN,
        "error": DANGER,
        "muted": MUTED,
        "info": BLUE,
    }.get(kind, MUTED)
