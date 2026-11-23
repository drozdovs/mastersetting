#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI агента MasterSetting — для тестов, скриптов и headless-режима.

Примеры:
    python cli.py info
    python cli.py save --operator Иван --camera SonyFX3 --settings Основные --from /Volumes/CARD
    python cli.py load --operator Иван --camera SonyFX3 --settings Основные --to /Volumes/CARD
    python cli.py stats
    python cli.py detect
"""

from __future__ import annotations

import argparse
import json
import sys

from mastersetting import fs_ops
from mastersetting.catalog import Catalog
from mastersetting.config import Config
from mastersetting.engine import ArchiveEngine, EngineError


def _engine() -> tuple[Config, Catalog, ArchiveEngine]:
    cfg = Config.load()
    cat = Catalog(config=cfg)
    return cfg, cat, ArchiveEngine(config=cfg, catalog=cat)


def cmd_info(args):
    cfg, cat, _ = _engine()
    print(json.dumps({
        "base_path": cfg.base_path,
        "cameraman": cfg.cameraman_path,
        "catalog_db": cfg.catalog_db,
        "server_url": cfg.server_url or "(не настроен)",
        "stats": cat.stats(),
    }, ensure_ascii=False, indent=2))


def cmd_detect(args):
    cfg, _, eng = _engine()
    drive, error = eng.detect_drive()
    print(json.dumps({"drive": drive, "error": error}, ensure_ascii=False))


def cmd_save(args):
    _, _, eng = _engine()

    def on_progress(p: fs_ops.Progress):
        sys.stderr.write(f"\r{p.percent:5.1f}%  {p.done_files}/{p.total_files}")
        sys.stderr.flush()

    rep = eng.save(args.operator, args.camera, args.settings,
                   from_path=args.from_path, overwrite=args.overwrite,
                   progress=on_progress)
    sys.stderr.write("\n")
    print(json.dumps(rep.__dict__, ensure_ascii=False, default=list))
    return 0 if rep.ok else 1


def cmd_load(args):
    _, _, eng = _engine()

    def on_progress(p: fs_ops.Progress):
        sys.stderr.write(f"\r{p.percent:5.1f}%  {p.done_files}/{p.total_files}")
        sys.stderr.flush()

    rep = eng.load(args.operator, args.camera, args.settings,
                   to_path=args.to_path, progress=on_progress)
    sys.stderr.write("\n")
    print(json.dumps(rep.__dict__, ensure_ascii=False, default=list))
    return 0 if rep.ok else 1


def cmd_stats(args):
    _, cat, _ = _engine()
    print(json.dumps(cat.stats(), ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mastersetting-cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info").set_defaults(func=cmd_info)
    sub.add_parser("detect").set_defaults(func=cmd_detect)
    sub.add_parser("stats").set_defaults(func=cmd_stats)

    s = sub.add_parser("save")
    s.add_argument("--operator", required=True)
    s.add_argument("--camera", required=True)
    s.add_argument("--settings", required=True)
    s.add_argument("--from", dest="from_path", default=None)
    s.add_argument("--overwrite", action="store_true")
    s.set_defaults(func=cmd_save)

    l = sub.add_parser("load")
    l.add_argument("--operator", required=True)
    l.add_argument("--camera", required=True)
    l.add_argument("--settings", required=True)
    l.add_argument("--to", dest="to_path", default=None)
    l.set_defaults(func=cmd_load)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except EngineError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
