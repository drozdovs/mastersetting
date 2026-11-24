#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Разложить реальные образцы FX3/FX3A на карту для проверки на камерах.

Этот скрипт готовит **физическую** проверку парной записи (ТЗ, п.2): кладёт
оба комплекта настроек на настоящую SD-карту в нативные пути Sony.

    <КАРТА>/PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT
    <КАРТА>/PRIVATE/SONY/SETTING/FX3A/CAMSET/FX3A.DAT

Затем вы вставляете карту в FX3 и в FX3A и проверяете, что каждая камера
видит СВОЙ комплект и не «залипает» от соседнего.

Безопасность (ТЗ: «не выполняй разрушающие действия над реальной картой»):
  * пишем ТОЛЬКО два файла настроек, ничего не удаляем;
  * отказываемся работать с системным диском/каталогом приложения;
  * если файл уже есть и отличается — требуем явный ``--force``;
  * проверяем права на запись и свободное место;
  * по умолчанию НЕ трогаем медиа и прочие файлы карты.

Использование:

    # 1) Посмотреть, что будет записано (ничего не пишет)
    python deploy/prepare_fx3_card.py --card /Volumes/SONY --dry-run

    # 2) Разложить оба образца
    python deploy/prepare_fx3_card.py --card /Volumes/SONY

    # Образцы по умолчанию берутся из папки «Sony FX Drozdov/Settings».
    # Если их нет — укажите свои:
    python deploy/prepare_fx3_card.py --card E:\\ \\
        --fx3 /path/to/FX3.DAT --fx3a /path/to/FX3A.DAT

После проверки на обеих камерах зафиксируйте результат:

    python cli.py confirm-fx3-paths \\
        --fx3-dir  PRIVATE/SONY/SETTING/FX3/CAMSET \\
        --fx3a-dir PRIVATE/SONY/SETTING/FX3A/CAMSET --by "Ваше имя"

Подробный протокол проверки — в docs/WINDOWS_VERIFICATION.md, раздел
«Проверка FX3/FX3A на камерах».
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mastersetting.platform import is_system_path  # noqa: E402
from mastersetting.settings_rules import detect_source_model  # noqa: E402

DEFAULT_SAMPLES = [
    os.path.expanduser("~/Desktop/Sony FX Drozdov/Settings/FX3/FX3.DAT"),
    os.path.expanduser("~/Desktop/Sony FX Drozdov/Settings/FX3A/FX3A.DAT"),
]

# Нативные пути на карте (источник истины — скрипты load.sh/load.ps1)
TARGETS = {
    "fx3": "PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT",
    "fx3a": "PRIVATE/SONY/SETTING/FX3A/CAMSET/FX3A.DAT",
}

# Какая модель должна быть в заголовке файла
EXPECT = {"fx3": "ILME-FX3", "fx3a": "ILME-FX3A"}


def _human(n: int) -> str:
    return f"{n / 1024:.1f} КБ"


def check_sample(path: str, expect: str) -> str | None:
    """Вернуть текст ошибки, если образец не годится, иначе None."""
    if not os.path.isfile(path):
        return f"файл не найден: {path}"
    model = detect_source_model(path)
    if not model:
        return f"это не файл настроек Sony (нет сигнатуры SONY0): {path}"
    if model != expect:
        return (f"в файле модель «{model}», а ожидалась «{expect}»: {path}\n"
                f"  Похоже, FX3 и FX3A перепутаны местами.")
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--card", required=True,
                    help="папка карты (например /Volumes/SONY или E:\\)")
    ap.add_argument("--fx3", default=DEFAULT_SAMPLES[0],
                    help="образец настроек FX3 (.DAT)")
    ap.add_argument("--fx3a", default=DEFAULT_SAMPLES[1],
                    help="образец настроек FX3A (.DAT)")
    ap.add_argument("--dry-run", action="store_true",
                    help="только показать план, ничего не писать")
    ap.add_argument("--force", action="store_true",
                    help="перезаписать уже существующий файл на карте")
    args = ap.parse_args(argv)

    card = os.path.abspath(os.path.expanduser(args.card))

    # --- Проверки безопасности -----------------------------------------
    if not os.path.isdir(card):
        print(f"Ошибка: папки карты нет: {card}", file=sys.stderr)
        return 2
    if is_system_path(card):
        print(f"Ошибка: «{card}» — системный диск или каталог приложения.\n"
              f"Это не карта. Укажите папку съёмного носителя.", file=sys.stderr)
        return 2
    if not os.access(card, os.W_OK):
        print(f"Ошибка: нет прав на запись в {card} (карта защищена?)",
              file=sys.stderr)
        return 2

    plan = {"fx3": args.fx3, "fx3a": args.fx3a}
    errors = []
    sizes = {}
    for key, sample in plan.items():
        err = check_sample(sample, EXPECT[key])
        if err:
            errors.append(err)
        else:
            sizes[key] = os.path.getsize(sample)
    if errors:
        print("Образцы не готовы:\n  - " + "\n  - ".join(errors), file=sys.stderr)
        return 2

    need = sum(sizes.values())
    try:
        free = shutil.disk_usage(card).free
    except OSError:
        free = None
    if free is not None and free < need + 8 * 1024 * 1024:
        print(f"Ошибка: на карте мало места (нужно ≥ {_human(need)} + запас)",
              file=sys.stderr)
        return 2

    print("План записи на карту:")
    for key in ("fx3", "fx3a"):
        rel = TARGETS[key]
        dst = os.path.join(card, *rel.split("/"))
        exists = os.path.exists(dst)
        mark = "уже есть" if exists else "новый"
        print(f"  [{key}] {rel}  ({_human(sizes[key])}, {mark})")
        if exists and not args.force:
            same = False
            try:
                with open(dst, "rb") as a, open(plan[key], "rb") as b:
                    same = a.read() == b.read()
            except OSError:
                pass
            if not same:
                print("    ВНИМАНИЕ: файл на карте отличается. Нужен --force,")
                print("    иначе он не будет перезаписан.")
    print(f"\nСвободно на карте: {_human(free) if free is not None else '—'}")
    print("Медиа и прочие файлы карты не затрагиваются.")

    if args.dry_run:
        print("\n--dry-run: ничего не записано.")
        return 0

    written, skipped = [], []
    for key in ("fx3", "fx3a"):
        rel = TARGETS[key]
        dst = os.path.join(card, *rel.split("/"))
        src = plan[key]
        if os.path.exists(dst) and not args.force:
            with open(dst, "rb") as a, open(src, "rb") as b:
                if a.read() == b.read():
                    skipped.append(rel)
                    continue
            print(f"Пропущено (уже есть другой файл, нет --force): {rel}")
            skipped.append(rel)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        # Контроль: модель в записанном файле должна совпасть
        got = detect_source_model(dst)
        if got != EXPECT[key]:
            print(f"Ошибка после записи: в {rel} модель «{got}»", file=sys.stderr)
            return 3
        written.append(rel)

    print(f"\nЗаписано: {len(written)}")
    for rel in written:
        print(f"  + {rel}")
    if skipped:
        print(f"Пропущено как уже готовое: {len(skipped)}")
        for rel in skipped:
            print(f"  = {rel}")

    print("\nТеперь проверьте на камерах (по протоколу):")
    print("  1. Вставьте карту в FX3 → меню камеры → импорт настроек (SETTING). "
          "Убедитесь, что камера видит СВОЙ комплект и не зависает.")
    print("  2. Вставьте карту в FX3A → то же самое.")
    print("  3. Если обе камеры работают штатно — зафиксируйте результат:")
    print("       python cli.py confirm-fx3-paths \\")
    print("         --fx3-dir  PRIVATE/SONY/SETTING/FX3/CAMSET \\")
    print("         --fx3a-dir PRIVATE/SONY/SETTING/FX3A/CAMSET --by \"Имя\"")
    print("  4. Перед извлечением карты — «Безопасно извлечь» в приложении "
          "или eject в системе.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
