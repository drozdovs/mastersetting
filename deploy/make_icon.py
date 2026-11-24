#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генератор иконки MasterSetting (.ico с несколькими размерами).

Рисует стилизованную SD-карту на тёмном скруглённом фоне — узнаваемый символ
карт памяти, которые использует программа. Результат: deploy/icon.ico
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "icon.ico")

# Тёмный фон в тон приложению (Material Black)
BG = (23, 26, 33, 255)
BG_EDGE = (38, 43, 54, 255)
ACCENT = (79, 124, 255, 255)      # синий акцент приложения
ACCENT_DK = (47, 84, 200, 255)
CARD = (230, 232, 238, 255)       # светлая карта
CARD_EDGE = (180, 186, 200, 255)
TEXT = (79, 124, 255, 255)


def draw_icon(size: int) -> Image.Image:
    """Нарисовать иконку заданного размера с супер-сэмплингом для сглаживания."""
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Скруглённый квадрат-фон с тонкой рамкой
    radius = int(s * 0.22)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius,
                        fill=BG, outline=BG_EDGE, width=max(1, int(s * 0.01)))

    # SD-карта (синяя, скруглённая) со срезанным верхним правым углом
    m = int(s * 0.22)
    left, top = m, m
    right, bottom = s - m, s - m
    notch = int(s * 0.18)
    card_pts = [
        (left, top),
        (right - notch, top),
        (right, top + notch),
        (right, bottom),
        (left, bottom),
    ]
    d.polygon(card_pts, fill=ACCENT)

    # Более тёмная нижняя полоса карты для объёма
    d.rectangle([left, bottom - int(s * 0.10), right, bottom], fill=ACCENT_DK)

    # Контактные «зубцы» сверху карты
    gap = int(s * 0.025)
    tooth_w = int(s * 0.09)
    y0 = top + int(s * 0.045)
    y1 = top + int(s * 0.14)
    x = left + int(s * 0.07)
    for _ in range(3):
        d.rectangle([x, y0, x + tooth_w, y1], fill=CARD)
        x += tooth_w + gap

    # Буквы «MS» по центру карты
    text = "MS"
    font = None
    for candidate in (
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if os.path.exists(candidate):
            try:
                font = ImageFont.truetype(candidate, int(s * 0.28))
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()

    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (s - tw) / 2 - bbox[0]
    ty = (s - th) / 2 - bbox[1] + int(s * 0.03)
    d.text((tx, ty), text, fill=CARD, font=font)

    # Вниз к целевому размеру со сглаживанием
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = draw_icon(256)
    base.save(OUT, format="ICO", sizes=[(x, x) for x in sizes])
    print(f"icon.ico создан: {OUT}")
    # Также сохраним PNG для использования в GUI (окно агента)
    png = os.path.join(HERE, "icon.png")
    base.save(png, format="PNG")
    print(f"icon.png создан: {png}")

    # macOS: .icns с retina-размерами (512/1024 обязательны для Retina)
    try:
        make_icns()
    except Exception as e:  # noqa: BLE001
        print(f"icon.icns не создан ({e}) — для macOS это необязательно")


def make_icns(out_path: str | None = None) -> str:
    """Собрать icon.icns для macOS через временный .iconset и iconutil."""
    import shutil
    import subprocess
    import tempfile

    out_path = out_path or os.path.join(HERE, "icon.icns")
    with tempfile.TemporaryDirectory() as tmp:
        iconset = os.path.join(tmp, "icon.iconset")
        os.makedirs(iconset, exist_ok=True)
        # Пары (пиксельный размер, имя файла в iconset)
        specs = [
            (16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
            (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
            (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
            (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
            (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png"),
        ]
        for px, name in specs:
            draw_icon(px).save(os.path.join(iconset, name), format="PNG")

        if shutil.which("iconutil") is None:
            raise RuntimeError("iconutil недоступен (не macOS)")
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out_path],
                       check=True)
    print(f"icon.icns создан: {out_path}")
    return out_path


if __name__ == "__main__":
    main()
