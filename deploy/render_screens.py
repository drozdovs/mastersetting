#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Снять экраны приложения в PNG (доказательство к ТЗ п.1: «макеты экранов»).

Запускает РЕАЛЬНЫЕ окна приложения на демонстрационных данных из временного
каталога (реальную карту и рабочий архив не трогает) и сохраняет каждый экран в
``docs/screens/*.png``.

Запуск (macOS):
    python deploy/render_screens.py

Требуется графическая сессия (не по SSH без дисплея).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "screens"


def _demo_library() -> str:
    """Создать демонстрационную библиотеку (оператор/камеры/пресеты/версии)."""
    base = os.path.join(tempfile.mkdtemp(prefix="ms-screens-"), "base")
    from mastersetting.versioning import VersionStore

    store = VersionStore(base_path=base)
    src = os.path.join(tempfile.mkdtemp(), "FX3.DAT")
    with open(src, "wb") as fh:
        fh.write(b"SONY0ILME-FX3" + b"\x00" * 200)
    for operator in ("Иван", "Пётр"):
        for camera in ("SonyFX3", "SonyFX3A", "Panasonic270"):
            for preset in ("Основные", "Интервью"):
                store.import_files(operator, camera, preset,
                                   {"PRIVATE/SONY/SETTING/CAMSET/CAM.DAT": src})
    return base


def _capture(win, name: str) -> None:
    """Снять область окна в файл (по фактическим координатам Tk)."""
    win.update_idletasks()
    win.update()
    x, y = win.winfo_rootx(), win.winfo_rooty()
    w, h = win.winfo_width(), win.winfo_height()
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"{name}.png"
    subprocess.run(["screencapture", "-o", "-x", "-R",
                    f"{x},{y},{w},{h}", str(dest)], check=False)
    print(f"  {name}: {x},{y} {w}x{h} -> {dest}")


def main() -> int:
    if sys.platform != "darwin":
        print("Снимок экранов рассчитан на macOS (screencapture).")
        return 0

    os.environ["MS_BASE_PATH"] = _demo_library()
    home = tempfile.mkdtemp(prefix="ms-screens-home-")
    os.environ["HOME"] = home
    os.environ["MS_SECRETS_FILE"] = os.path.join(home, "secrets.enc")
    os.environ["MS_FX3_CONFIRM_FILE"] = os.path.join(home, "fx3.json")

    import importlib
    from mastersetting import config as cfgmod
    importlib.reload(cfgmod)
    import agent.app as appmod
    import agent.wizard as wizmod

    app = appmod.MasterSettingApp()
    app.withdraw()
    app.update()

    # Главный экран — сам app.
    app.deiconify()
    app.lift()
    app.focus_force()
    app.attributes("-topmost", True)
    app.geometry("+120+80")
    for _ in range(10):
        app.update_idletasks()
        app.update()
        time.sleep(0.1)
    app.attributes("-topmost", False)
    _capture(app, "01_main")
    time.sleep(0.2)

    def shot(name, factory):
        win = factory(app)
        try:
            if name == "03_write_wizard":
                # Показать шаг выбора пары/набора (ТЗ п.1), а не только карту.
                win.go_to(1)
            win.geometry("+120+80")
            win.deiconify()
            win.lift()
            win.focus_force()
            win.attributes("-topmost", True)
            for _ in range(10):
                win.update_idletasks()
                win.update()
                time.sleep(0.1)
            win.attributes("-topmost", False)
            _capture(win, name)
        finally:
            win.destroy()
            app.update()
            time.sleep(0.2)

    shot("02_save_wizard", lambda p: wizmod.SaveWizard(p))
    shot("03_write_wizard", lambda p: wizmod.WriteWizard(p))
    shot("04_library", lambda p: appmod.LibraryWindow(p))
    shot("05_pairs", lambda p: appmod.PairsWindow(p))
    shot("06_admin_gate", lambda p: appmod.AdminWindow(p))
    shot("07_operator", lambda p: appmod.OperatorWindow(p))

    # Админ-панель после входа (пароль задаём только в этом временном хранилище).
    app.ctrl.set_admin_password("demo-password-123")
    admin = appmod.AdminWindow(app)
    admin.pw.insert(0, "demo-password-123")
    admin._login()
    admin.geometry("+120+80")
    admin.deiconify()
    admin.lift()
    admin.focus_force()
    admin.attributes("-topmost", True)
    for _ in range(10):
        admin.update_idletasks()
        admin.update()
        time.sleep(0.1)
    admin.attributes("-topmost", False)
    _capture(admin, "08_admin_panel")
    admin.destroy()

    app.destroy()
    print(f"\nГотово: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
