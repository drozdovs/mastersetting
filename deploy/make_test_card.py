#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Создать тестовую «карту» с настройками для проверки — БЕЗОПАСНО.

Делает временную папку, похожую на карту камеры Sony:

    <куда>/PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT   — файл настроек (SONY0)
    <куда>/PRIVATE/SONY/SETTING/FX3A/CAMSET/FX3A.DAT — для второй модели
    <куда>/CLIP0001.MP4                              — «видео» (не должно копироваться)

Использование:
    python deploy/make_test_card.py /tmp/testcard
    python deploy/make_test_card.py %TEMP%\\testcard     (Windows)
"""

from __future__ import annotations

import os
import sys

SKIP = {"LASTCLIP.TXT", "SONYCARD.IND"}


def make_card(root: str) -> list[str]:
    """Создать структуру и вернуть список созданных файлов."""
    created: list[str] = []

    def write(rel: str, data: bytes) -> None:
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        created.append(rel)

    # Файлы настроек двух моделей: сигнатура SONY0 + осмысленный хвост
    write("PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT",
          b"SONY0ILME-FX3" + b"\x00" * 32 + b"FX3-settings")
    write("PRIVATE/SONY/SETTING/FX3A/CAMSET/FX3A.DAT",
          b"SONY0ILME-FX3A" + b"\x00" * 32 + b"FX3A-settings")

    # «Видео» и служебные файлы рядом — они НЕ должны копироваться
    write("CLIP0001.MP4", b"fake video " * 500)
    write("PRIVATE/M4ROOT/CLIP/CLIP0002.MXF", b"fake mxf " * 500)
    write("LASTCLIP.TXT", b"ignore me")
    return created


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    root = argv[0]
    if os.path.exists(root) and os.listdir(root):
        print(f"Отказ: папка не пуста, не буду ничего трогать: {root}")
        return 3
    os.makedirs(root, exist_ok=True)
    created = make_card(root)
    print(f"Тестовая карта создана: {root}")
    for rel in created:
        print(f"  {rel}")
    print("\nНастройки (их и должно найти приложение): "
          "FX3.DAT, FX3A.DAT")
    print("Медиа и служебное (НЕ должно копироваться): "
          "CLIP0001.MP4, CLIP0002.MXF, LASTCLIP.TXT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
