# -*- coding: utf-8 -*-
"""MasterSetting Agent — GUI поверх ядра (экраны, тёмная тема).

Экраны:
  * Главный: текущий оператор, статус карты, две крупные операции,
    последние пресеты, статус последней резервной копии.
  * «Сохранить с карты»: карта -> модель -> пресет -> просмотр файлов ->
    новая версия -> результат.
  * «Записать на карту»: оператор -> модель/пара -> версия -> карта ->
    просмотр изменений -> запись и проверка -> результат.
  * Библиотека: поиск, операторы/камеры/пресеты/версии.
  * Пары FX3/FX3A.
  * Помощь (локальный HTML), Админ.

GUI не содержит бизнес-логики: только рисует и вызывает ``AppController``.
Тяжёлые операции идут в фоновом потоке, результат возвращается в главный поток
через ``after`` (в фоновом потоке НЕ трогаем виджеты).
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Callable

import customtkinter as ctk

from agent import dialogs, theme
from agent.controllers import AppController
from agent.local_store import LocalStore
from agent.widgets import EditableComboBox
from agent.wizard import SaveWizard, WriteWizard, _Choice
from mastersetting.platform import open_path

ctk.set_appearance_mode("dark")


def resource_path(relative: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, relative)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, relative)


def center(window: ctk.CTk | ctk.CTkToplevel) -> None:
    window.update_idletasks()
    w, h = window.winfo_width(), window.winfo_height()
    x = (window.winfo_screenwidth() // 2) - (w // 2)
    y = (window.winfo_screenheight() // 2) - (h // 2)
    window.geometry(f"{w}x{h}+{x}+{y}")


class BaseWindow(ctk.CTkToplevel):
    """Общий предок модальных окон: тёмная тема, ESC, центрирование."""

    def __init__(self, parent, title: str, size: tuple[int, int]):
        super().__init__(parent)
        self.app: "MasterSettingApp" = parent
        self.ctrl = parent.ctrl
        self.title(title)
        self.geometry(f"{size[0]}x{size[1]}")
        self.minsize(size[0], size[1])
        self.configure(fg_color=theme.BG)
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(10, lambda: center(self))

    def panel(self, **kw) -> ctk.CTkFrame:
        return ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10, **kw)

    def label(self, master, text, *, size="body", color=None, bold=False, **kw):
        return ctk.CTkLabel(
            master, text=text, text_color=color or theme.TEXT,
            font=ctk.CTkFont(size=theme.SIZES[size],
                             weight="bold" if bold else "normal"), **kw)

    def button(self, master, text, command, *, kind="primary", **kw):
        colors = {
            "primary": (theme.ACCENT, "#c9c9cc", theme.BG),
            "ghost": (theme.PANEL2, theme.PANEL, theme.TEXT),
            "danger": ("#7f1d1d", "#991b1b", theme.TEXT),
        }
        fg, hover, tcol = colors.get(kind, colors["primary"])
        return ctk.CTkButton(master, text=text, command=command,
                             fg_color=fg, hover_color=hover, text_color=tcol,
                             corner_radius=8, **kw)

    def set_status(self, widget, text, kind="muted"):
        widget.configure(text=text, text_color=theme.status_color(kind))

    # ------------------------------------------------------------------
    def run_async(self, work: Callable, on_done: Callable, on_error: Callable,
                  on_progress: Callable | None = None) -> None:
        """Выполнить ``work`` в потоке, вернуть результат в главный поток.

        Виджеты из потока НЕ трогаем: используем ``self.after``.
        """
        def runner():
            try:
                result = work()
            except Exception as e:  # noqa: BLE001
                # ``e`` через default-аргумент: иначе имя удаляется при выходе
                # из except и лямбда падает с NameError вместо показа ошибки.
                self.after(0, lambda err=e: on_error(err))
                return
            self.after(0, lambda res=result: on_done(res))

        threading.Thread(target=runner, daemon=True).start()


# ===========================================================================
# Главное окно
# ===========================================================================

class MasterSettingApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.ctrl = AppController()
        self.store = LocalStore()
        self._drive_poll = None

        self.title("MasterSetting")
        self.geometry("460x560")
        self.minsize(420, 520)          # масштабируемое окно (ТЗ)
        self.configure(fg_color=theme.BG)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self._set_window_icon()
        self._init_dirs()
        self.create_widgets()
        self.bind_hotkeys()
        self.refresh()
        self._start_drive_poll()
        # ТЗ: проверять наличие обновления автоматически при интернете (в фоне,
        # главный поток не трогаем; результат — тихий баннер в админ-панели).
        self.update_notice = ""
        self.after(2500, self._auto_check_update)
        # ТЗ: раз в сутки — фоновая копия рабочих данных (офлайн откладывается).
        self.after(5000, self._daily_backup)

    def _daily_backup(self):
        def work():
            try:
                self.ctrl.auto_backup("daily")
            except Exception:  # noqa: BLE001
                pass

        self._run_bg(work, lambda r: None, lambda e: None)

    def _auto_check_update(self):
        def work():
            try:
                return self.ctrl.auto_check_update()
            except Exception:  # noqa: BLE001
                return {"status": "error", "message": ""}

        def done(res):
            if res.get("status") == "available":
                self.update_notice = res.get("message", "")

        self._run_bg(work, done, lambda e: None)

    def _run_bg(self, work, on_done, on_error):
        """Фон без заморозки окна: результат возвращаем через ``after``.

        Если окно уже закрыто (пользователь вышел во время работы), ``after``
        бросает RuntimeError — это не ошибка работы, тихо выходим.
        """
        def runner():
            try:
                result = work()
            except Exception as e:  # noqa: BLE001
                try:
                    self.after(0, lambda err=e: on_error(err))
                except RuntimeError:
                    pass
                return
            try:
                self.after(0, lambda res=result: on_done(res))
            except RuntimeError:
                pass  # окно закрыто — результат уже некому показать

        threading.Thread(target=runner, daemon=True).start()

    # ------------------------------------------------------------------
    def _init_dirs(self):
        # Каталог данных — только для владельца (там журнал, секреты, конфиг).
        from mastersetting.config import ensure_app_data_dir
        try:
            ensure_app_data_dir()
        except Exception:
            pass
        for path in (self.ctrl.config.base_path, self.ctrl.config.cameraman_path,
                     self.ctrl.config.main_path, self.ctrl.config.instructions_path):
            os.makedirs(path, exist_ok=True)
        if not os.path.exists(self.ctrl.config.camera_file):
            with open(self.ctrl.config.camera_file, "w", encoding="utf-8") as f:
                f.write("PanasonicAG-CX350\nSonyZ90\nSonyFX3\nSonyFX3A\nSonyFX6\n"
                        "PanasonicAG-PX5000\nPanasonic270")

    def _set_window_icon(self):
        try:
            ico = resource_path(os.path.join("deploy", "icon.ico"))
            if os.path.exists(ico):
                self.iconbitmap(ico)
                return
        except Exception:
            pass
        try:
            png = resource_path(os.path.join("deploy", "icon.png"))
            if os.path.exists(png):
                from PIL import Image, ImageTk
                img = ImageTk.PhotoImage(Image.open(png))
                self.iconphoto(True, img)
                self._icon_ref = img
        except Exception:
            pass

    def bind_hotkeys(self):
        self.bind("<F9>", lambda e: self.open_write_window())
        self.bind("<F5>", lambda e: self.open_save_window())
        self.bind("<F12>", lambda e: self.open_instructions_window())
        self.bind("<F1>", lambda e: self.open_help_window())
        self.bind("<F2>", lambda e: self.open_library_window())
        self.bind("<F3>", lambda e: self.open_pairs_window())
        self.bind("<F4>", lambda e: self.open_admin_window())
        self.bind("<Escape>", lambda e: self.on_closing())

    # ------------------------------------------------------------------
    def create_widgets(self):
        root = ctk.CTkFrame(self, fg_color="transparent")
        root.pack(fill="both", expand=True, padx=22, pady=18)

        # Шапка: кто работает
        header = self.panel_root(root)
        header.pack(fill="x", pady=(0, 14))
        self._label(header, "Оператор", size="small", color=theme.MUTED).pack(
            anchor="w", padx=16, pady=(14, 2))
        op_row = ctk.CTkFrame(header, fg_color="transparent")
        op_row.pack(fill="x", padx=16, pady=(0, 14))
        self.operator_label = self._label(op_row, "—", size="h1", bold=True)
        self.operator_label.pack(side="left")
        self._button(op_row, "Сменить", self.change_operator, kind="ghost",
                     width=90, height=30).pack(side="right")

        # Что происходит с картой — одной понятной строкой
        self.drive_label = self._label(root, "", size="small",
                                       color=theme.MUTED)
        self.drive_label.pack(anchor="w", pady=(0, 12))

        # Две большие задачи
        self._label(root, "Что нужно сделать?", size="h3", bold=True).pack(
            anchor="w", pady=(0, 8))
        self.save_btn = self._big_button(
            root, "Сохранить с карты",
            "Скопировать настройки камеры в библиотеку",
            self.open_save_window, primary=True)
        self.write_btn = self._big_button(
            root, "Записать на карту",
            "Взять сохранённый набор и записать на карту",
            self.open_write_window, primary=False)

        # Недавнее
        recent = self.panel_root(root)
        recent.pack(fill="both", expand=True, pady=(14, 10))
        top = ctk.CTkFrame(recent, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(12, 0))
        self._label(top, "Последние сохранённые наборы", size="h3",
                    bold=True).pack(side="left")
        self._button(top, "Все (F2)", self.open_library_window, kind="ghost",
                     width=90, height=28).pack(side="right")
        self.recent_frame = ctk.CTkFrame(recent, fg_color="transparent")
        self.recent_frame.pack(fill="both", expand=True, padx=16,
                               pady=(8, 12))

        # Низ
        footer = ctk.CTkFrame(root, fg_color="transparent")
        footer.pack(fill="x")
        self.backup_label = self._label(footer, "", size="tiny",
                                        color=theme.MUTED)
        self.backup_label.pack(side="left")
        for text, cmd in (("Админ (F4)", self.open_admin_window),
                          ("Помощь (F1)", self.open_help_window),
                          ("Пары FX3/FX3A", self.open_pairs_window)):
            self._button(footer, text, cmd, kind="ghost", width=118,
                         height=28).pack(side="right", padx=(6, 0))

    def _big_button(self, master, title, subtitle, command, *, primary):
        """Крупная карточка-действие: заголовок, пояснение, наведение, клик."""
        card = ctk.CTkFrame(master, fg_color=theme.PANEL2, corner_radius=12)
        card.pack(fill="x", pady=(0, 8))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=12)
        title_lbl = ctk.CTkLabel(
            inner, text=title, text_color=theme.TEXT, anchor="w",
            font=ctk.CTkFont(size=theme.SIZES["h3"], weight="bold"))
        title_lbl.pack(anchor="w")
        sub_lbl = ctk.CTkLabel(
            inner, text=subtitle, text_color=theme.MUTED, anchor="w",
            font=ctk.CTkFont(size=theme.SIZES["tiny"]))
        sub_lbl.pack(anchor="w")

        def on_enter(_=None):
            card.configure(fg_color=theme.LINE)

        def on_leave(_=None):
            card.configure(fg_color=theme.PANEL2)

        for w in (card, inner, title_lbl, sub_lbl):
            w.bind("<Button-1>", lambda e, c=command: c())
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass
        return card

    # --- мини-хелперы для главного окна (без BaseWindow) ---
    def panel_root(self, master):
        return ctk.CTkFrame(master, fg_color=theme.PANEL, corner_radius=10)

    def _label(self, master, text, *, size="body", color=None, bold=False):
        return ctk.CTkLabel(
            master, text=text, text_color=color or theme.TEXT,
            font=ctk.CTkFont(size=theme.SIZES[size],
                             weight="bold" if bold else "normal"),
            justify="left")

    def _button(self, master, text, command, *, kind="primary", **kw):
        colors = {
            "primary": (theme.ACCENT, "#c9c9cc", theme.BG),
            "ghost": (theme.PANEL2, theme.PANEL, theme.TEXT),
        }
        fg, hover, tcol = colors.get(kind, colors["primary"])
        return ctk.CTkButton(master, text=text, command=command, fg_color=fg,
                             hover_color=hover, text_color=tcol, corner_radius=8,
                             font=ctk.CTkFont(size=theme.SIZES["body"]), **kw)

    # ------------------------------------------------------------------
    def refresh(self):
        op = self.ctrl.current_operator()
        self.operator_label.configure(text=op or "не выбран")
        self.backup_label.configure(text=self.ctrl.last_backup_status())
        self._refresh_recent()
        self._poll_drive()

    def change_operator(self):
        """Сменить/выбрать оператора прямо с главного экрана."""
        win = OperatorWindow(self)
        self.wait_window(win)
        self.refresh()

    def _refresh_recent(self):
        for w in self.recent_frame.winfo_children():
            w.destroy()
        items = self.ctrl.recent_versions(limit=6)
        if not items:
            self._label(self.recent_frame,
                        "Здесь появятся сохранённые наборы.\n"
                        "Начните с «Сохранить с карты».",
                        size="small", color=theme.MUTED).pack(
                anchor="w", pady=4)
            return
        for it in items:
            row = ctk.CTkFrame(self.recent_frame, fg_color="transparent")
            row.pack(fill="x", pady=3)
            text = f"{it.operator} · {it.camera} · {it.preset}"
            self._label(row, text, size="small").pack(side="left")
            self._label(row, f"{it.files} файл(ов)", size="tiny",
                        color=theme.MUTED).pack(side="right")

    def _start_drive_poll(self):
        self._poll_drive()

    def _poll_drive(self):
        cards = self.ctrl.list_cards()
        if len(cards) == 1:
            self.drive_label.configure(
                text=f"Карта подключена: {os.path.basename(cards[0])}",
                text_color=theme.OK)
        elif len(cards) == 0:
            self.drive_label.configure(
                text="Карта не подключена. Вставьте карту в кардридер.",
                text_color=theme.MUTED)
        else:
            self.drive_label.configure(
                text=f"Подключено карт: {len(cards)}. Выбор — в мастере.",
                text_color=theme.OK)
        self._drive_poll = self.after(
            int(self.ctrl.config.auto_detect_poll_seconds * 1000), self._poll_drive)

    def on_closing(self):
        if self._drive_poll:
            try:
                self.after_cancel(self._drive_poll)
            except Exception:
                pass
        # CustomTkinter держит таймер масштабирования DPI, который может
        # сработать уже после destroy() и выбросить TclError в консоль.
        # Он не влияет на закрытие, но лучше заглушить его для чистого выхода.
        try:
            from customtkinter.windows.widgets.scaling.scaling_tracker import (
                ScalingTracker,
            )
            ScalingTracker()._check_dpi_scaling = lambda *a, **k: None
        except Exception:
            pass
        try:
            if self.winfo_exists():
                self.destroy()
        except Exception:
            pass

    # ------------------------------------------------------------------
    def open_save_window(self):
        SaveWizard(self)
    def open_write_window(self):
        WriteWizard(self)

    def open_library_window(self):
        LibraryWindow(self)

    def open_pairs_window(self):
        PairsWindow(self)

    def open_instructions_window(self):
        InstructionsWindow(self)

    def open_admin_window(self):
        AdminWindow(self)

    def open_help_window(self):
        help_html = resource_path(os.path.join("docs", "help", "index.html"))
        if not os.path.exists(help_html):
            help_html = resource_path(os.path.join("MASTERSETTING_HELP.html"))
        if os.path.exists(help_html):
            try:
                open_path(help_html)
                return
            except Exception as e:  # noqa: BLE001
                dialogs.error(self, "Не удалось открыть справку", str(e))
        else:
            dialogs.warn(self, "Справка не найдена",
                         "Файл справки не входит в сборку.")


# ===========================================================================
# Смена оператора (прямо с главного экрана)
# ===========================================================================

class OperatorWindow(ctk.CTkToplevel):
    """Быстрый выбор оператора: подсказки в один клик или своё имя."""

    def __init__(self, parent):
        super().__init__(parent)
        self.app = parent
        self.ctrl = parent.ctrl

        self.title("Сменить оператора")
        self.geometry("420x320")
        self.minsize(380, 300)          # масштабируемое окно (ТЗ), не фиксируем
        self.configure(fg_color=theme.BG)
        self.transient(parent)

        box = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=12)
        box.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(box, text="Кто работает?", text_color=theme.TEXT,
                     font=ctk.CTkFont(size=theme.SIZES["h2"], weight="bold")
                     ).pack(anchor="w", padx=16, pady=(16, 4))
        ctk.CTkLabel(box, text="Нажмите на имя или введите новое. Вход не нужен.",
                     text_color=theme.MUTED,
                     font=ctk.CTkFont(size=theme.SIZES["small"])
                     ).pack(anchor="w", padx=16, pady=(0, 12))

        self.box = EditableComboBox(
            box, values=self.ctrl.list_operators(),
            max_length=self.ctrl.config.max_name_length,
            placeholder="Имя оператора")
        self.box.pack(fill="x", padx=16)
        self.box.set(self.ctrl.current_operator())

        ctk.CTkLabel(box,
                     text="Имя — это порядок, а не защита: войти может любой за "
                          "этим компьютером и открыть чужие пресеты.",
                     text_color=theme.WARN, wraplength=360, justify="left",
                     font=ctk.CTkFont(size=theme.SIZES["tiny"])
                     ).pack(anchor="w", padx=16, pady=(10, 0))

        btns = ctk.CTkFrame(box, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=16, side="bottom")
        ctk.CTkButton(btns, text="Сохранить", command=self._save,
                      fg_color=theme.ACCENT, hover_color="#c9c9cc",
                      text_color=theme.BG, corner_radius=8,
                      font=ctk.CTkFont(size=theme.SIZES["body"])).pack(
            side="right")
        ctk.CTkButton(btns, text="Отмена", command=self.destroy,
                      fg_color=theme.PANEL2, hover_color=theme.LINE,
                      text_color=theme.TEXT, corner_radius=8,
                      font=ctk.CTkFont(size=theme.SIZES["body"])).pack(
            side="right", padx=(0, 8))

        self.bind("<Return>", lambda e: self._save())
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(50, self._center)

    def _center(self):
        self.update_idletasks()
        w = self.winfo_width()
        x = self.app.winfo_rootx() + (self.app.winfo_width() - w) // 2
        y = self.app.winfo_rooty() + 120
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.focus_force()

    def _save(self):
        name = self.box.get().strip()
        if not name:
            dialogs.warn(self, "Нужно имя", "Введите или выберите имя оператора.")
            return
        self.ctrl.remember_operator(name)
        self.destroy()


# ===========================================================================
# Библиотека
# ===========================================================================

class LibraryWindow(BaseWindow):
    def __init__(self, parent):
        super().__init__(parent, "Библиотека", (640, 600))
        body = self.panel()
        body.pack(fill="both", expand=True, padx=16, pady=16)
        self.label(body, "Библиотека пресетов", size="h2", bold=True).pack(anchor="w")

        search_row = ctk.CTkFrame(body, fg_color="transparent")
        search_row.pack(fill="x", pady=(10, 8))
        self.query = ctk.CTkEntry(search_row, placeholder_text="Поиск…")
        self.query.pack(side="left", fill="x", expand=True)
        self.query.bind("<KeyRelease>", lambda e: self._refresh())
        self.button(search_row, "Обновить", self._refresh, kind="ghost",
                    width=100, height=30).pack(side="left", padx=(6, 0))

        self.text = ctk.CTkTextbox(body, fg_color=theme.PANEL2,
                                   text_color=theme.TEXT, border_width=0,
                                   corner_radius=8)
        self.text.pack(fill="both", expand=True)
        self._refresh()

        # ТЗ: пресет можно удалить (окончательно, по подтверждению) и выгрузить
        # конкретную версию — без изменения библиотеки. Действия под выбором.
        self.label(body, "Действия с пресетом / версией", size="tiny",
                   color=theme.MUTED).pack(anchor="w", pady=(10, 2))
        action = ctk.CTkFrame(body, fg_color="transparent")
        action.pack(fill="x")
        self.triple = ctk.CTkComboBox(action, values=["—"], state="readonly")
        self.triple.pack(side="left", fill="x", expand=True)
        self.button(action, "Выгрузить версию…", self._export, kind="ghost",
                    width=160, height=30).pack(side="left", padx=(6, 0))
        self.button(action, "Удалить пресет…", self._delete, kind="danger",
                    width=150, height=30).pack(side="left", padx=(6, 0))
        self._fill_triples()

    # ------------------------------------------------------------------
    def _fill_triples(self):
        self._triples = {}
        labels = []
        q = self.query.get().strip().lower()
        for op in self.ctrl.list_operators():
            for cam in self.ctrl.list_cameras():
                for preset in self.ctrl.list_presets(op, cam):
                    label = f"{op} / {cam} / {preset}"
                    if q and q not in label.lower():
                        continue
                    self._triples[label] = (op, cam, preset)
                    labels.append(label)
        self.triple.configure(values=labels or ["—"])
        self.triple.set(labels[0] if labels else "—")

    def _selected_triple(self):
        label = self.triple.get()
        return self._triples.get(label)

    def _export(self):
        sel = self._selected_triple()
        if not sel:
            dialogs.warn(self, "Пресет не выбран", "Выберите пресет из списка.")
            return
        op, cam, preset = sel
        versions = self.ctrl.list_versions(op, cam, preset)
        if not versions:
            dialogs.warn(self, "Нет версий", "У этого пресета нет версий.")
            return
        # Выбираем конкретную версию (первую/самую свежую) и папку выгрузки.
        v = versions[0]
        dest = dialogs.pick_folder(self, title="Куда выгрузить версию")
        if not dest:
            return
        try:
            path = self.ctrl.export_version(v, dest)
        except Exception as e:  # noqa: BLE001
            dialogs.error(self, "Выгрузка не удалась", str(e))
            return
        dialogs.info(self, "Версия выгружена",
                     f"{v.version_id} — {v.file_count} файл(ов).\n"
                     "Библиотека не изменилась.", detail=path)

    def _delete(self):
        sel = self._selected_triple()
        if not sel:
            dialogs.warn(self, "Пресет не выбран", "Выберите пресет из списка.")
            return
        op, cam, preset = sel
        versions = self.ctrl.list_versions(op, cam, preset)
        if not versions:
            dialogs.warn(self, "Нет версий", "У этого пресета нет версий.")
            return
        if not dialogs.confirm(
                self, "Удалить пресет окончательно?",
                f"{op} / {cam} / {preset}\nВерсий: {len(versions)}.\n\n"
                "Восстановить будет можно только из резервной копии.",
                yes_text="Удалить", danger=True):
            return
        try:
            n = self.ctrl.delete_preset(op, cam, preset, confirm_versions=len(versions))
        except Exception as e:  # noqa: BLE001
            dialogs.error(self, "Удаление не удалось", str(e))
            return
        dialogs.info(self, "Пресет удалён", f"Удалено версий: {n}.")
        self._refresh()

    def _refresh(self):
        q = self.query.get().strip().lower()
        lines = []
        for op in self.ctrl.list_operators():
            for cam in self.ctrl.list_cameras():
                presets = self.ctrl.list_presets(op, cam)
                for preset in presets:
                    versions = self.ctrl.list_versions(op, cam, preset)
                    header = f"{op} / {cam} / {preset}  ({len(versions)} версий)"
                    if q and q not in header.lower():
                        continue
                    lines.append(header)
                    for v in versions:
                        rels = ", ".join(r.rel_path for r in v.files[:2])
                        model = f"  ·  модель: {v.source_model}" if v.source_model else ""
                        lines.append(f"    {v.version_id}  ·  {v.file_count} файл(ов)"
                                     f"  ·  {v.total_bytes} Б{model}  ·  {rels}")
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(lines) if lines else "Ничего не найдено.")
        self.text.configure(state="disabled")
        if hasattr(self, "triple"):
            self._fill_triples()


# ===========================================================================
# Пары FX3/FX3A
# ===========================================================================

class PairsWindow(BaseWindow):
    def __init__(self, parent):
        super().__init__(parent, "Пары FX3 / FX3A", (620, 620))
        body = self.panel()
        body.pack(fill="both", expand=True, padx=16, pady=16)
        self.label(body, "Именованные пары FX3 / FX3A", size="h2", bold=True).pack(anchor="w")
        self.label(body, "Пара хранит ЯВНО выбранные версии. Версия не меняется "
                         "сама при появлении новой.",
                   size="tiny", color=theme.MUTED, wraplength=560,
                   justify="left").pack(anchor="w", pady=(2, 6))

        if not self.ctrl.pair_write_available():
            self.label(body,
                       "Парная запись выключена: пути FX3/FX3A ещё не подтверждены "
                       "образцами с реальной карты. Создавать и хранить пары можно "
                       "уже сейчас.",
                       size="tiny", color=theme.WARN, wraplength=560,
                       justify="left").pack(anchor="w", pady=(0, 8))

        # --- Создание пары ---
        form = ctk.CTkFrame(body, fg_color=theme.PANEL2, corner_radius=8)
        form.pack(fill="x", pady=(0, 10), ipady=8)
        self.label(form, "Новая пара / изменить", size="small", bold=True).pack(
            anchor="w", padx=10, pady=(6, 4))

        self.label(form, "Оператор", size="tiny", color=theme.MUTED).pack(
            anchor="w", padx=10)
        self.op_box = _Choice(form, self.ctrl.list_operators(), self._on_op)
        self.op_box.pack(fill="x", padx=10, pady=(2, 6))

        self.label(form, "Название пары (например «Основные»)", size="tiny",
                   color=theme.MUTED).pack(anchor="w", padx=10)
        self.name_box = EditableComboBox(form, values=[], width=520,
                                         max_length=30,
                                         placeholder="Название пары")
        self.name_box.pack(fill="x", padx=10, pady=(2, 6))

        self.label(form, "Версия FX3 (можно не выбирать)", size="tiny",
                   color=theme.MUTED).pack(anchor="w", padx=10)
        self.fx3_box = _Choice(form, ["—"], None)
        self.fx3_box.pack(fill="x", padx=10, pady=(2, 6))

        self.label(form, "Версия FX3A (можно не выбирать)", size="tiny",
                   color=theme.MUTED).pack(anchor="w", padx=10)
        self.fx3a_box = _Choice(form, ["—"], None)
        self.fx3a_box.pack(fill="x", padx=10, pady=(2, 8))

        self.button(form, "Сохранить пару", self._save_pair, width=160).pack(
            anchor="w", padx=10, pady=(0, 8))

        self.list_frame = ctk.CTkScrollableFrame(body, fg_color=theme.PANEL2,
                                                 corner_radius=8, height=180)
        self.list_frame.pack(fill="both", expand=True)
        self.button(body, "Закрыть (ESC)", self.destroy, kind="ghost").pack(
            anchor="e", pady=(10, 0))
        if self.ctrl.list_operators():
            self._on_op(self.ctrl.list_operators()[0])
        self._refresh()

    def _on_op(self, operator):
        self.operator = operator
        self.fx3_box.configure_values(
            ["—"] + [f"{cam} · {preset} · {vid}"
                     for cam, preset, vid in self._iter_family(operator, "FX3")])
        self.fx3a_box.configure_values(
            ["—"] + [f"{cam} · {preset} · {vid}"
                     for cam, preset, vid in self._iter_family(operator, "FX3A")])
        self.name_box.configure_values(
            [p.name for p in self.ctrl.pairs.list_pairs(operator)])

    def _iter_family(self, operator, family):
        for cam in self.ctrl.list_cameras():
            low = cam.lower()
            is_fx3a = "fx3a" in low
            is_fx3 = "fx3" in low and not is_fx3a
            if (family == "FX3A" and is_fx3a) or (family == "FX3" and is_fx3):
                for preset in self.ctrl.list_presets(operator, cam):
                    for v in self.ctrl.list_versions(operator, cam, preset):
                        yield cam, preset, v.version_id

    def _save_pair(self):
        name = self.name_box.get().strip()
        if not name:
            dialogs.warn(self, "Нужно название", "Введите название пары.")
            return
        fx3 = self.fx3_box.get()
        fx3a = self.fx3a_box.get()
        fx3_id = fx3.split(" · ")[-1] if fx3 and fx3 != "—" else ""
        fx3a_id = fx3a.split(" · ")[-1] if fx3a and fx3a != "—" else ""
        if not fx3_id and not fx3a_id:
            dialogs.warn(self, "Пустая пара",
                         "Выберите хотя бы одну версию — FX3 или FX3A.")
            return
        try:
            self.ctrl.save_pair(name, self.operator, fx3_id, fx3a_id)
        except Exception as e:  # noqa: BLE001
            dialogs.error(self, "Пара не сохранена", str(e))
            return
        dialogs.info(self, "Пара сохранена", f"«{name}» для оператора {self.operator}.")
        self._refresh()

    def _refresh(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        pairs = self.ctrl.pairs.list_pairs()
        if not pairs:
            self.label(self.list_frame,
                       "Пар пока нет.",
                       size="small", color=theme.MUTED, wraplength=540,
                       justify="left").pack(anchor="w", padx=8, pady=8)
            return
        for p in pairs:
            row = ctk.CTkFrame(self.list_frame, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=4)
            state = "полная" if p.is_complete else "неполная: нет " + ", ".join(p.missing_slots())
            self.label(row, f"{p.operator} · {p.name} — {state}",
                       size="small").pack(anchor="w")


# ===========================================================================
# Инструкции
# ===========================================================================

class InstructionsWindow(BaseWindow):
    def __init__(self, parent):
        super().__init__(parent, "Инструкции", (440, 300))
        body = self.panel()
        body.pack(fill="both", expand=True, padx=16, pady=16)
        self.label(body, "Выберите инструкцию", size="h3", bold=True).pack(anchor="w",
                                                                          pady=(0, 10))
        self.combo = ctk.CTkComboBox(body, values=[], state="readonly")
        self.combo.pack(fill="x", pady=(0, 12))
        self.button(body, "Открыть", self._open).pack(anchor="w")
        self._load()

    def _load(self):
        items = []
        allowed = {e.lower() for e in self.ctrl.config.instruction_extensions}
        root = self.ctrl.config.instructions_path
        if os.path.isdir(root):
            for folder in os.listdir(root):
                fp = os.path.join(root, folder)
                if not os.path.isdir(fp):
                    continue
                for file in os.listdir(fp):
                    name, ext = os.path.splitext(file)
                    if ext.lower() in allowed:
                        items.append(f"{folder.upper()}/{name}")
        items.sort()
        self.combo.configure(values=items or ["Инструкции отсутствуют"])
        self.combo.set(items[0] if items else "Инструкции отсутствуют")

    def _open(self):
        sel = self.combo.get()
        if sel == "Инструкции отсутствуют":
            dialogs.warn(self, "Инструкций нет", "По этой камере пока нет подсказок.")
            return
        folder_upper, file_name = sel.split("/", 1)
        root = self.ctrl.config.instructions_path
        for folder in os.listdir(root):
            if folder.upper() == folder_upper:
                fp = os.path.join(root, folder)
                for file in os.listdir(fp):
                    name, _ = os.path.splitext(file)
                    if name == file_name:
                        open_path(os.path.join(fp, file))
                        return
        dialogs.warn(self, "Файл не найден", "Нужный файл не входит в сборку.")


# ===========================================================================
# Админ-панель
# ===========================================================================

class AdminWindow(BaseWindow):
    """Админ-панель. Требует пароль администратора (ТЗ).

    Пока пароль не задан — предлагаем его создать. После входа: статистика,
    журнал операций, резервные копии (создать/восстановить), список открытых
    вопросов. Секреты (ключи S3) — в системном хранилище, не в открытом виде.
    """

    def __init__(self, parent):
        super().__init__(parent, "Администрирование", (760, 640))
        self.unlocked = False
        self.body = self.panel()
        self.body.pack(fill="both", expand=True, padx=16, pady=16)
        self._render_gate()

    # ------------------------------------------------------------------
    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _render_gate(self):
        self._clear()
        b = self.body
        self.label(b, "Администрирование", size="h2", bold=True).pack(anchor="w")
        self.label(b, "Действия с данными защищены паролем администратора.",
                   size="tiny", color=theme.MUTED, wraplength=600,
                   justify="left").pack(anchor="w", pady=(2, 12))

        if not self.ctrl.is_password_set():
            self.label(b, "Пароль ещё не задан. Придумайте его сейчас.",
                       size="body", color=theme.WARN).pack(anchor="w", pady=(0, 6))
            self.label(b, "Не короче 8 символов. Пароль нигде не хранится "
                          "в открытом виде.", size="tiny",
                       color=theme.MUTED).pack(anchor="w", pady=(0, 8))
            self.new_pw = ctk.CTkEntry(b, placeholder_text="Новый пароль", show="•")
            self.new_pw.pack(fill="x", pady=(0, 6))
            self.new_pw2 = ctk.CTkEntry(b, placeholder_text="Повторите пароль", show="•")
            self.new_pw2.pack(fill="x", pady=(0, 10))
            self.button(b, "Задать пароль", self._set_password).pack(anchor="w")
            self.button(b, "Закрыть (ESC)", self.destroy, kind="ghost").pack(
                anchor="e", pady=(12, 0))
            return

        self.label(b, "Введите пароль администратора", size="body").pack(
            anchor="w", pady=(0, 6))
        self.pw = ctk.CTkEntry(b, placeholder_text="Пароль", show="•")
        self.pw.pack(fill="x", pady=(0, 6))
        self.pw.bind("<Return>", lambda e: self._login())
        self.gate_status = self.label(b, "", size="tiny", color=theme.MUTED)
        self.gate_status.pack(anchor="w", pady=(0, 8))
        self.button(b, "Войти", self._login).pack(anchor="w")
        self.button(b, "Закрыть (ESC)", self.destroy, kind="ghost").pack(
            anchor="e", pady=(12, 0))

    def _set_password(self):
        pw1, pw2 = self.new_pw.get(), self.new_pw2.get()
        if pw1 != pw2:
            dialogs.warn(self, "Пароли не совпали",
                         "Введите одинаковый пароль дважды.")
            return
        try:
            self.ctrl.set_admin_password(pw1)
        except Exception as e:  # noqa: BLE001
            dialogs.error(self, "Пароль не принят", str(e))
            return
        dialogs.info(self, "Пароль задан",
                     "Теперь панель открывается только по паролю.")
        self.unlocked = True
        self._render_panel()

    def _login(self):
        locked = self.ctrl.admin_locked_for()
        if locked > 0:
            dialogs.warn(self, "Панель временно заблокирована",
                         f"Слишком много попыток. Подождите {int(locked)} с.")
            return
        try:
            ok = self.ctrl.login_admin(self.pw.get())
        except Exception as e:  # noqa: BLE001
            dialogs.warn(self, "Не сейчас", str(e))
            return
        if ok:
            self.unlocked = True
            self._render_panel()
        else:
            dialogs.warn(self, "Неверный пароль",
                         "Проверьте раскладку и Caps Lock и попробуйте снова.")

    # ------------------------------------------------------------------
    def _render_panel(self):
        self._clear()
        b = self.body
        self.label(b, "Администрирование", size="h2", bold=True).pack(anchor="w")
        self.label(b, "Операторы и модели, резервные копии, восстановление, "
                      "журнал операций.",
                   size="tiny", color=theme.MUTED, wraplength=620,
                   justify="left").pack(anchor="w", pady=(2, 10))

        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x", pady=(0, 6))
        self.button(row, "Создать копию", self._backup, width=140).pack(side="left")
        self.button(row, "Восстановить…", self._restore, kind="ghost",
                    width=140).pack(side="left", padx=(6, 0))
        self.button(row, "Пробное восстановление", self._trial_restore,
                    kind="ghost", width=190).pack(side="left", padx=(6, 0))
        self.button(row, "Отправить копии", self._flush_uploads, kind="ghost",
                    width=150).pack(side="left", padx=(6, 0))

        row2 = ctk.CTkFrame(b, fg_color="transparent")
        row2.pack(fill="x", pady=(0, 8))
        self.button(row2, "Хранилище S3…", self._configure_s3, kind="ghost",
                    width=140).pack(side="left")
        self.button(row2, "Правила S3 (90 дней)", self._s3_lifecycle,
                    kind="ghost", width=170).pack(side="left", padx=(6, 0))
        self.button(row2, "Обновление…", self._check_update, kind="ghost",
                    width=130).pack(side="left", padx=(6, 0))
        self.button(row2, "Подготовить пакет…", self._prepare_update,
                    kind="ghost", width=160).pack(side="left", padx=(6, 0))
        self.button(row2, "Канал обновлений…", self._configure_update_channel,
                    kind="ghost", width=160).pack(side="left", padx=(6, 0))

        row3 = ctk.CTkFrame(b, fg_color="transparent")
        row3.pack(fill="x", pady=(0, 8))
        self.button(row3, "Перенос 1.9…", self._migrate, kind="ghost",
                    width=140).pack(side="left")
        self.button(row3, "Путь данных…", self._set_path, kind="ghost",
                    width=140).pack(side="left", padx=(6, 0))
        self.button(row3, "Обновить", self._render_panel, kind="ghost",
                    width=100).pack(side="left", padx=(6, 0))

        self.text = ctk.CTkTextbox(b, fg_color=theme.PANEL2, text_color=theme.TEXT,
                                   border_width=0, corner_radius=8)
        self.text.pack(fill="both", expand=True)
        self._fill()
        self.button(b, "Закрыть (ESC)", self.destroy, kind="ghost").pack(
            anchor="e", pady=(10, 0))

    def _fill(self):
        stats = self.ctrl.catalog.stats()
        bk = self.ctrl.backup_status()
        ops = self.ctrl.list_operators()
        cams = self.ctrl.list_cameras()
        lines = [
            "— Операторы и модели —",
            f"Операторов: {len(ops)}: " + (", ".join(ops[:12]) or "—"),
            f"Моделей камер: {len(cams)}: " + (", ".join(cams[:12]) or "—"),
            "",
            "— Статистика —",
            f"Событий: {stats['events_total']}   "
            f"сохранений: {stats['saves_ok']}   записей: {stats['loads_ok']}   "
            f"ошибок: {stats['errors']}",
            "",
            f"— Резервные копии (храним {bk['retention_days']} дней): {bk['count']} —",
            bk["dir"],
        ]
        for it in bk["items"][:6]:
            from datetime import datetime as _dt
            when = _dt.fromtimestamp(it["mtime"]).strftime("%d.%m.%Y %H:%M")
            lines.append(f"   {it['name']}  ({it['size'] // 1024} КБ, {when})")
        if not bk["items"]:
            lines.append("   (пока нет — нажмите «Создать копию»)")

        lines += ["", "— Последние операции —"]
        for ev in self.ctrl.recent_events(limit=12):
            lines.append(f"   {ev.get('created_at','')}  {ev.get('kind','')}"
                         f"  {ev.get('status','')}  "
                         f"{ev.get('operator','')} {ev.get('camera','')} "
                         f"{ev.get('settings','')}".rstrip())
        if not self.ctrl.recent_events(limit=1):
            lines.append("   (журнал пуст)")

        lines += [
            "", "— Открытые вопросы —",
            "• Парная запись FX3/FX3A заблокирована до подтверждения путей с карты.",
            f"• S3 (Timeweb): {'настроен' if self.ctrl.s3_configured() else 'не настроен'}"
            " — ключи хранятся в системном хранилище и в архив копий не попадают.",
            f"• Канал обновлений: "
            f"{'настроен' if self.ctrl.update_channel_configured() else 'не настроен'}"
            " — нужен адрес https-манифеста и публичный ключ подписи.",
        ]
        notice = getattr(self.app, "update_notice", "")
        if notice:
            lines += ["", "— Обновление —", f"• {notice}"]
        try:
            ulog = self.ctrl.update_log()
        except Exception:
            ulog = []
        if ulog:
            lines += ["", "— Журнал обновлений —"]
            for e in ulog[-5:]:
                mark = "ок" if e.get("ok") else "отказ"
                lines.append(f"   {e.get('at','')}  {e.get('version','')}  "
                             f"{mark}  {e.get('message','')}")
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(lines))
        self.text.configure(state="disabled")

    def _backup(self):
        try:
            rep = self.ctrl.backup_now()
        except Exception as e:  # noqa: BLE001
            dialogs.error(self, "Копия не создалась", str(e))
            return
        if rep["ok"]:
            dialogs.info(self, "Копия создана",
                         f"Файлов: {rep['files']}.", detail=rep["path"])
        else:
            dialogs.warn(self, "Копия не создалась", rep["message"])
        self._render_panel()

    def _restore(self):
        bk = self.ctrl.backup_status()
        if not bk["items"]:
            dialogs.warn(self, "Нет копий", "Сначала создайте резервную копию.")
            return
        # Берём самую свежую копию (список отсортирован по убыванию).
        target = bk["items"][0]["name"]
        path = os.path.join(bk["dir"], target)
        if not dialogs.confirm(self, "Восстановить данные?",
                               f"Текущие данные будут заменены из копии:\n{target}\n\n"
                               "Перед этим приложение сделает страховочную копию.",
                               yes_text="Восстановить", danger=True):
            return
        try:
            rep = self.ctrl.restore_from_snapshot(path)
        except Exception as e:  # noqa: BLE001
            dialogs.error(self, "Восстановление не удалось", str(e))
            return
        dialogs.info(self, "Данные восстановлены",
                     f"Файлов: {rep['restored_files']}.",
                     detail=rep.get("warning", ""))
        self._render_panel()

    def _check_update(self):
        """Выбрать манифест обновления и проверить его подпись (ТЗ п.3)."""
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            parent=self, title="Манифест обновления",
            filetypes=[("Манифест", "*.json"), ("Все файлы", "*.*")])
        if not path:
            return
        try:
            res = self.ctrl.check_update(path)
        except Exception as e:  # noqa: BLE001
            dialogs.error(self, "Проверка не удалась", str(e))
            return
        if res.get("verified"):
            dialogs.info(self, "Обновление подтверждено", res["message"])
        else:
            dialogs.warn(self, "Обновление отклонено", res["message"])

    def _prepare_update(self):
        """Проверить пакет подписью, сделать страховочную копию и подготовить файл."""
        from tkinter import filedialog
        manifest = filedialog.askopenfilename(
            parent=self, title="Манифест обновления",
            filetypes=[("Манифест", "*.json"), ("Все файлы", "*.*")])
        if not manifest:
            return
        package = filedialog.askopenfilename(
            parent=self, title="Файл пакета обновления",
            filetypes=[("Пакет", "*.exe *.dmg *.zip *.pkg"), ("Все файлы", "*.*")])
        if not package:
            return
        if not dialogs.confirm(
                self, "Подготовить обновление?",
                "Приложение проверит подпись и хеш пакета, сохранит рабочие "
                "данные в резервную копию и подготовит проверенный файл.\n\n"
                "Автоматического запуска нет — установщик вы запустите сами, "
                "вручную, когда будет удобно.",
                yes_text="Проверить и подготовить"):
            return
        try:
            res = self.ctrl.prepare_update(manifest, package)
        except Exception as e:  # noqa: BLE001
            dialogs.error(self, "Не получилось", str(e))
            return
        if res.get("ok"):
            dialogs.info(self, "Пакет готов к запуску", res["message"])
        else:
            dialogs.warn(self, "Пакет отклонён", res["message"])
        self._render_panel()

    def _configure_s3(self):
        """Ввод реквизитов S3. Ключи уходят в системное хранилище, не в файл."""
        win = S3ConfigWindow(self, on_saved=self._render_panel)
        self.wait_window(win)

    def _configure_update_channel(self):
        """Адрес канала обновлений и публичный ключ подписи (ТЗ)."""
        win = UpdateChannelWindow(self, on_saved=self._render_panel)
        self.wait_window(win)

    def _s3_lifecycle(self):
        """Поставить в S3 правило: удалять старые версии копий через 90 дней."""
        if not self.ctrl.s3_configured():
            dialogs.warn(self, "S3 не настроен",
                         "Сначала заполните «Хранилище S3…».")
            return
        if not dialogs.confirm(
                self, "Правила хранения в S3",
                "Установить правило: удалять копии старше 90 дней и их старые "
                "версии? Это освобождает место, ни на что локально не влияет.",
                yes_text="Установить"):
            return
        res = self.ctrl.apply_s3_lifecycle(90)
        if res.get("ok"):
            dialogs.info(self, "Правила S3 установлены", res["message"])
        else:
            dialogs.warn(self, "Правила S3 не установлены", res["message"])
        self._render_panel()

    def _flush_uploads(self):
        """Отправить отложенные офлайн-копии, когда интернет вернулся (ТЗ)."""
        res = self.ctrl.flush_pending_uploads()
        if res.get("ok"):
            dialogs.info(self, "Отложенные копии", res["message"])
        else:
            dialogs.warn(self, "Отправка невозможна", res.get("message", ""))
        self._render_panel()

    def _trial_restore(self):
        """Пробное восстановление в отдельный каталог, не трогая рабочие данные."""
        res = self.ctrl.trial_restore_latest()
        if res.get("ok"):
            dialogs.info(self, "Копия восстановима", res.get("message", ""))
        else:
            dialogs.warn(self, "Пробное восстановление не удалось",
                         res.get("message", ""))
        self._render_panel()

    def _migrate(self):
        """Перенос старого архива 1.9 (C:/setting) с проверяемой копией."""
        preview = self.ctrl.scan_migration()
        if not preview["found"]:
            dialogs.warn(self, "Старый архив не найден",
                         f"По пути {preview['legacy']} нет архива версии 1.9.\n\n"
                         "Если он лежит в другом месте, задайте путь переменной "
                         "MS_LEGACY_BASE и откройте панель снова.")
            return
        total = len(preview["entries"])
        sample = "\n".join(
            f"• {e['operator']} / {e['camera']} / {e['preset']} — {e['status']}"
            for e in preview["entries"][:8])
        if not dialogs.confirm(
                self, "Перенести старый архив?",
                f"Найдено папок: {total}\n\n{sample}\n\n"
                "Сначала будет создана проверяемая копия. Старые данные не "
                "удаляются.",
                yes_text="Перенести"):
            return
        try:
            rep = self.ctrl.run_migration()
        except Exception as e:  # noqa: BLE001
            dialogs.error(self, "Перенос не удался", str(e))
            return
        dialogs.info(self, "Перенос завершён",
                     f"{rep['summary']}\nКопия проверена: "
                     f"{'да' if rep['backup_verified'] else 'НЕТ'}",
                     detail=rep["backup_path"])
        self._render_panel()

    def _set_path(self):
        """Сменить папку рабочей базы (ТЗ: путь данных настраивается)."""
        dialogs.info(self, "Текущий путь данных",
                     self.ctrl.config.base_path,
                     detail="Выберите новую папку. Каталог установки не подходит: "
                            "он перезаписывается при обновлении.")
        path = dialogs.pick_folder(self, title="Куда хранить рабочую базу",
                                   initialdir=self.ctrl.config.base_path)
        if not path:
            return
        res = self.ctrl.set_data_path(path)
        if res.get("ok"):
            dialogs.info(self, "Путь данных изменён", res["message"])
        else:
            dialogs.warn(self, "Так нельзя", res["message"])
        self._render_panel()


# ===========================================================================
# Настройка S3 (Timeweb) — ключи в системном хранилище
# ===========================================================================

class S3ConfigWindow(BaseWindow):
    """Форма реквизитов S3. Секретный ключ нигде не показывается после ввода."""

    def __init__(self, parent, on_saved=None):
        super().__init__(parent, "Хранилище S3", (560, 470))
        self.on_saved = on_saved
        b = self.panel()
        b.pack(fill="both", expand=True, padx=16, pady=16)

        self.label(b, "Резервные копии в S3 (Timeweb)", size="h2", bold=True).pack(
            anchor="w")
        self.label(b, "Ключи сохраняются в системном хранилище (Keychain/DPAPI), "
                      "а не в открытом файле. В архив копий они не попадают.",
                   size="tiny", color=theme.MUTED, wraplength=520,
                   justify="left").pack(anchor="w", pady=(2, 12))

        self.endpoint = self._field(b, "Адрес (endpoint), напр. https://s3.timeweb.cloud")
        self.region = self._field(b, "Регион (напр. ru-1)")
        self.bucket = self._field(b, "Имя бакета")
        self.access = self._field(b, "Access Key (логин)")
        self.secret = self._field(b, "Secret Key", secret=True)

        self.status = self.label(b, "", size="tiny", color=theme.MUTED)
        self.status.pack(anchor="w", pady=(4, 6))

        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x", pady=(4, 0))
        self.button(row, "Сохранить", self._save).pack(side="left")
        self.button(row, "Закрыть (ESC)", self.destroy, kind="ghost").pack(
            side="left", padx=(6, 0))

    def _field(self, master, placeholder, *, secret=False):
        self.label(master, placeholder, size="tiny", color=theme.MUTED).pack(
            anchor="w", pady=(4, 0))
        e = ctk.CTkEntry(master, placeholder_text=placeholder,
                         show="•" if secret else "")
        e.pack(fill="x")
        return e

    def _save(self):
        endpoint = self.endpoint.get().strip()
        region = self.region.get().strip()
        bucket = self.bucket.get().strip()
        access = self.access.get().strip()
        secret = self.secret.get().strip()
        if not (bucket and access and secret):
            self.set_status(self.status, "Заполните бакет и оба ключа.", "error")
            return
        try:
            self.ctrl.set_s3_config(endpoint, region, bucket, access, secret)
        except Exception as e:  # noqa: BLE001
            dialogs.error(self, "Не удалось сохранить", str(e))
            return
        self.set_status(self.status,
                       "Сохранено. «Создать копию» отправит снимок в S3.", "ok")
        if self.on_saved:
            self.on_saved()


class UpdateChannelWindow(BaseWindow):
    """Адрес канала обновлений (https) и доверенный публичный ключ подписи (ТЗ).

    Приложение проверяет манифест автоматически при интернете; установку
    запускает администратор вручную. Ключ хранится в системном хранилище.
    """

    def __init__(self, parent, on_saved=None):
        super().__init__(parent, "Канал обновлений", (620, 380))
        self.on_saved = on_saved
        b = self.panel()
        b.pack(fill="both", expand=True, padx=16, pady=16)

        self.label(b, "Подписанные обновления", size="h2", bold=True).pack(anchor="w")
        self.label(b,
                   "Манифест лежит на отдельном https-адресе и подписан Ed25519. "
                   "Приложение сверяет подпись доверенным ключом ниже, затем хеш "
                   "пакета. Совпадение имени файла само по себе не даёт доверия.",
                   size="tiny", color=theme.MUTED, wraplength=580,
                   justify="left").pack(anchor="w", pady=(2, 12))

        self.url = self._field(b, "Адрес манифеста (https://…)")
        self.key = self._field(b, "Публичный ключ подписи (base64)")

        self.status = self.label(b, "", size="tiny", color=theme.MUTED)
        self.status.pack(anchor="w", pady=(4, 6))

        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x", pady=(4, 0))
        self.button(row, "Сохранить", self._save).pack(side="left")
        self.button(row, "Проверить сейчас", self._check, kind="ghost").pack(
            side="left", padx=(6, 0))
        self.button(row, "Закрыть (ESC)", self.destroy, kind="ghost").pack(
            side="left", padx=(6, 0))

        s = self.ctrl._secrets()
        try:
            self.url.insert(0, s.get("update_manifest_url") or "")
            self.key.insert(0, s.get("update_public_key") or "")
        except Exception:
            pass

    def _field(self, master, placeholder):
        self.label(master, placeholder, size="tiny", color=theme.MUTED).pack(
            anchor="w", pady=(4, 0))
        e = ctk.CTkEntry(master, placeholder_text=placeholder)
        e.pack(fill="x")
        return e

    def _save(self):
        url = self.url.get().strip()
        key = self.key.get().strip()
        if url and not url.lower().startswith("https://"):
            self.set_status(self.status, "Адрес должен начинаться с https://", "error")
            return
        try:
            self.ctrl.set_update_channel(url, key)
        except Exception as e:  # noqa: BLE001
            dialogs.error(self, "Не удалось сохранить", str(e))
            return
        self.set_status(self.status, "Сохранено.", "ok")
        if self.on_saved:
            self.on_saved()

    def _check(self):
        res = self.ctrl.auto_check_update()
        kind = "ok" if res.get("verified") else "error"
        self.set_status(self.status, res.get("message", ""), kind)


def main():
    app = MasterSettingApp()
    app.mainloop()


if __name__ == "__main__":
    main()
