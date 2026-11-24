#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI агента MasterSetting — для тестов, скриптов и headless-режима.

ВСЕ команды используют новое ядро (неизменяемые версии + безопасная запись).
Ни одна команда не копирует корень карты целиком.

Основные:
    python cli.py versions --operator Иван --camera SonyFX3 --preset Основные
    python cli.py plan-save --camera SonyFX3 --media /Volumes/CARD
    python cli.py save-version --operator Иван --camera SonyFX3 --preset Основные --media /Volumes/CARD
    python cli.py preview-write --operator Иван --camera SonyFX3 --preset Основные --card /Volumes/CARD
    python cli.py write-version --operator Иван --camera SonyFX3 --preset Основные --card /Volumes/CARD
    python cli.py verify --operator Иван --camera SonyFX3 --preset Основные --card /Volumes/CARD
    python cli.py export-version --operator Иван --camera SonyFX3 --preset Основные --dest ~/Выгрузка
    python cli.py delete-preset --operator Иван --camera SonyFX3 --preset Основные --confirm 3

Служебные:
    python cli.py info      — пути данных и статистика
    python cli.py cards     — список подключённых съёмных носителей
    python cli.py stats     — статистика операций
    python cli.py set-path --path ~/MasterSetting/setting  — задать путь данных
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from mastersetting.catalog import Catalog
from mastersetting.config import Config
from mastersetting.library import LibraryError, PairWriteError, PresetLibrary
from mastersetting.path_confirm import (
    PathConfirmError,
    apply_to_rules,
    save_confirmation,
)
from mastersetting.platform import get_removable_drives, is_system_path
from mastersetting.safe_write import WriteError
from mastersetting.versioning import VersionStore, VersionStoreError


def _library() -> PresetLibrary:
    return PresetLibrary(base_path=Config.load().base_path)


def cmd_info(args):
    cfg = Config.load()
    cat = Catalog(config=cfg)
    print(json.dumps({
        "base_path": cfg.base_path,
        "cameraman": cfg.cameraman_path,
        "catalog_db": cfg.catalog_db,
        "stats": cat.stats(),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_cards(args):
    """Список съёмных носителей (кроссплатформенно, без образов дисков)."""
    cfg = Config.load()
    drives = get_removable_drives(cfg.removable_drive_start)
    print(json.dumps({"cards": drives, "count": len(drives)},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_stats(args):
    cat = Catalog(config=Config.load())
    print(json.dumps(cat.stats(), ensure_ascii=False, indent=2))
    return 0


def cmd_set_path(args):
    """Задать настраиваемый путь данных (ТЗ: «путь данных должен настраиваться»).

    Каталог установки запрещён: он перезаписывается при обновлении, и рабочая
    база там потеряется. Создаём каталог с правами владельца и сохраняем конфиг.
    """
    from mastersetting.config import ensure_app_data_dir
    from mastersetting.platform import is_install_path
    from pathlib import Path

    target = os.path.abspath(os.path.expanduser(args.path))
    if is_system_path(target):
        print("Ошибка: системный диск или каталог приложения нельзя "
              "использовать как хранилище данных.", file=sys.stderr)
        return 2
    if is_install_path(target):
        print("Ошибка: нельзя хранить рабочую базу в каталоге установки "
              "(он обновляется, и данные пропадут).", file=sys.stderr)
        return 2
    cfg = Config.load()
    cfg.base_path = target
    Path(cfg.cameraman_path).mkdir(parents=True, exist_ok=True)
    Path(cfg.main_path).mkdir(parents=True, exist_ok=True)
    ensure_app_data_dir()
    cfg.save()
    print(json.dumps({"ok": True, "base_path": cfg.base_path},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_inspect(args):
    """Показать ВСЁ, что есть на карте/в папке, с причиной принять/отклонить.

    Служит «шлюзу FX3/FX3A»: снимите настройки на карту прямо с камеры,
    вставьте карту и выполните эту команду. Вывод покажет реальные пути и
    имена файлов настроек — их нужно передать разработчику, чтобы подтвердить
    правило модели и включить парную запись.
    """
    from mastersetting.settings_rules import discover_in_folder

    root = args.media
    res = discover_in_folder(root)
    items = [{
        "rel_path": c.rel_path,
        "size": c.size,
        "accepted": c.accepted,
        "reason": c.reason,
    } for c in res.candidates]
    print(json.dumps({
        "root": root,
        "exists": os.path.isdir(root),
        "settings_files": [c["rel_path"] for c in items if c["accepted"]],
        "all_files": items,
        "warnings": res.warnings,
    }, ensure_ascii=False, indent=2, default=list))
    return 0


# ---------------------------------------------------------------------------
# Безопасные команды на новом ядре (версии + безопасная запись)
# ---------------------------------------------------------------------------

def cmd_versions(args):
    store = VersionStore(base_path=Config.load().base_path)
    versions = store.list_versions(args.operator, args.camera, args.preset)
    print(json.dumps([
        {"version_id": v.version_id, "created_at": v.created_at,
         "files": v.file_count, "bytes": v.total_bytes, "verified": v.verified,
         "source_model": v.source_model, "source_media": v.source_media,
         "firmware": v.firmware}
        for v in versions
    ], ensure_ascii=False, indent=2))
    return 0


def cmd_plan_save(args):
    lib = _library()
    plan = lib.plan_from_media(args.camera, args.media)
    print(json.dumps({
        "files": list(plan.files.keys()),
        "file_count": plan.file_count,
        "total_bytes": plan.total_bytes,
        "confirmed_format": plan.is_confirmed_format,
        "detected_model": plan.detected_model,
        "warnings": plan.warnings,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_save_version(args):
    lib = _library()

    def on_progress(i, n, rel):
        sys.stderr.write(f"\r{i}/{n}  {rel[:60]}")
        sys.stderr.flush()

    rep = lib.save_from_media(args.operator, args.camera, args.preset, args.media,
                              progress=on_progress)
    sys.stderr.write("\n")
    print(json.dumps(rep.__dict__, ensure_ascii=False, default=list))
    return 0 if rep.ok else 1


def _latest_version(lib: PresetLibrary, args):
    versions = lib.store.list_versions(args.operator, args.camera, args.preset)
    if not versions:
        print("Версий не найдено", file=sys.stderr)
        return None
    if args.version_id:
        for v in versions:
            if v.version_id == args.version_id:
                return v
        print(f"Версия {args.version_id} не найдена", file=sys.stderr)
        return None
    return versions[0]


def cmd_preview_write(args):
    lib = _library()
    version = _latest_version(lib, args)
    if version is None:
        return 2
    rep = lib.preview_write(version, args.card)
    print(json.dumps({"version_id": version.version_id, "changes": rep.written},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_write_version(args):
    lib = _library()
    version = _latest_version(lib, args)
    if version is None:
        return 2

    def on_progress(i, n, rel):
        sys.stderr.write(f"\r{i}/{n}  {rel[:60]}")
        sys.stderr.flush()

    rep = lib.write_version_to_card(version, args.card, progress=on_progress)
    sys.stderr.write("\n")
    print(json.dumps({"ok": rep.ok, "message": rep.message,
                      "written": rep.written, "rolled_back": rep.rolled_back},
                     ensure_ascii=False, indent=2))
    return 0 if rep.ok else 1


def cmd_verify(args):
    lib = _library()
    version = _latest_version(lib, args)
    if version is None:
        return 2
    mismatches = lib.verify_version_on_card(version, args.card)
    print(json.dumps({"version_id": version.version_id,
                      "ok": not mismatches, "mismatches": mismatches},
                     ensure_ascii=False, indent=2))
    return 0 if not mismatches else 1


def cmd_delete_preset(args):
    """Удалить пресет со всеми версиями. Требует --confirm с числом версий."""
    lib = _library()
    n = lib.delete_preset(args.operator, args.camera, args.preset,
                          confirm_versions=args.confirm)
    print(json.dumps({"ok": True, "deleted_versions": n},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_export_version(args):
    """Экспортировать версию в папку, НЕ меняя библиотеку."""
    lib = _library()
    version = _latest_version(lib, args)
    if version is None:
        return 2
    out = lib.export_version(version, args.dest)
    print(json.dumps({"ok": True, "version_id": version.version_id, "into": out},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_confirm_fx3_paths(args):
    """Подтвердить нативные пути FX3/FX3A по образцу с реальной карты (шлюз ТЗ п.2).

    Пути можно передать явно (--fx3-dir/--fx3a-dir) или снять их автоматически
    из ``inspect --media <каталог>`` (--from-sample). Пока это не выполнено,
    парная запись остаётся выключенной.
    """
    fx3_dirs = list(args.fx3_dir or [])
    fx3a_dirs = list(args.fx3a_dir or [])

    if args.from_sample:
        from mastersetting.settings_rules import discover_in_folder
        res = discover_in_folder(args.from_sample)
        for c in res.accepted:
            rel = c.rel_path
            folder = os.path.dirname(rel)
            name = os.path.basename(rel).upper()
            if "FX3A" in rel.upper() or name.startswith("FX3A"):
                fx3a_dirs.append(folder)
            elif "FX3" in rel.upper() or name.startswith("FX3"):
                fx3_dirs.append(folder)

    if not fx3_dirs and not fx3a_dirs:
        print(json.dumps({
            "ok": False,
            "message": "Нечего подтверждать: укажите --from-sample или "
                       "--fx3-dir/--fx3a-dir.",
        }, ensure_ascii=False, indent=2))
        return 2

    saved = []
    if fx3_dirs:
        c = save_confirmation("SonyFX3", sorted(set(fx3_dirs)),
                              sample=args.from_sample or "", 
                              confirmed_by=args.by)
        saved.append({"family": c.family, "settings_dirs": c.settings_dirs})
    if fx3a_dirs:
        c = save_confirmation("SonyFX3A", sorted(set(fx3a_dirs)),
                              sample=args.from_sample or "",
                              confirmed_by=args.by)
        saved.append({"family": c.family, "settings_dirs": c.settings_dirs})

    enabled = apply_to_rules()
    print(json.dumps({
        "ok": True,
        "saved": saved,
        "now_enabled_families": enabled,
        "pair_write_available": set(enabled) >= {"SonyFX3", "SonyFX3A"},
    }, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mastersetting-cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info").set_defaults(func=cmd_info)
    sub.add_parser("cards").set_defaults(func=cmd_cards)
    sub.add_parser("stats").set_defaults(func=cmd_stats)

    sp = sub.add_parser("set-path",
                        help="задать настраиваемый путь данных (вне каталога установки)")
    sp.add_argument("--path", required=True, help="папка для рабочей базы")
    sp.set_defaults(func=cmd_set_path)

    insp = sub.add_parser("inspect")
    insp.add_argument("--media", required=True,
                      help="корень карты/папки для исследования")
    insp.set_defaults(func=cmd_inspect)

    v = sub.add_parser("versions")
    v.add_argument("--operator", required=True)
    v.add_argument("--camera", required=True)
    v.add_argument("--preset", required=True)
    v.set_defaults(func=cmd_versions)

    ps = sub.add_parser("plan-save")
    ps.add_argument("--camera", required=True)
    ps.add_argument("--media", required=True)
    ps.set_defaults(func=cmd_plan_save)

    sv = sub.add_parser("save-version")
    sv.add_argument("--operator", required=True)
    sv.add_argument("--camera", required=True)
    sv.add_argument("--preset", required=True)
    sv.add_argument("--media", required=True)
    sv.set_defaults(func=cmd_save_version)

    pw = sub.add_parser("preview-write")
    pw.add_argument("--operator", required=True)
    pw.add_argument("--camera", required=True)
    pw.add_argument("--preset", required=True)
    pw.add_argument("--card", required=True)
    pw.add_argument("--version-id", dest="version_id", default=None)
    pw.set_defaults(func=cmd_preview_write)

    wv = sub.add_parser("write-version")
    wv.add_argument("--operator", required=True)
    wv.add_argument("--camera", required=True)
    wv.add_argument("--preset", required=True)
    wv.add_argument("--card", required=True)
    wv.add_argument("--version-id", dest="version_id", default=None)
    wv.set_defaults(func=cmd_write_version)

    vf = sub.add_parser("verify")
    vf.add_argument("--operator", required=True)
    vf.add_argument("--camera", required=True)
    vf.add_argument("--preset", required=True)
    vf.add_argument("--card", required=True)
    vf.add_argument("--version-id", dest="version_id", default=None)
    vf.set_defaults(func=cmd_verify)

    dp = sub.add_parser("delete-preset")
    dp.add_argument("--operator", required=True)
    dp.add_argument("--camera", required=True)
    dp.add_argument("--preset", required=True)
    dp.add_argument("--confirm", type=int, required=True,
                    help="точное число версий пресета (защита от случайного удаления)")
    dp.set_defaults(func=cmd_delete_preset)

    ex = sub.add_parser("export-version")
    ex.add_argument("--operator", required=True)
    ex.add_argument("--camera", required=True)
    ex.add_argument("--preset", required=True)
    ex.add_argument("--dest", required=True, help="папка для выгрузки копии")
    ex.add_argument("--version-id", dest="version_id", default=None)
    ex.set_defaults(func=cmd_export_version)

    cf = sub.add_parser("confirm-fx3-paths",
                        help="подтвердить пути FX3/FX3A по образцу с карты")
    cf.add_argument("--from-sample", dest="from_sample", default=None,
                    help="корень образца (как у inspect); пути снимутся автоматически")
    cf.add_argument("--fx3-dir", action="append", default=[],
                    help="относительная папка настроек FX3 (можно несколько раз)")
    cf.add_argument("--fx3a-dir", action="append", default=[],
                    help="относительная папка настроек FX3A (можно несколько раз)")
    cf.add_argument("--by", default="operator", help="кто подтвердил (для журнала)")
    cf.set_defaults(func=cmd_confirm_fx3_paths)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (LibraryError, PairWriteError, WriteError, VersionStoreError,
            PathConfirmError) as e:
        # Понятное сообщение без трассировки: оператор должен увидеть смысл.
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
