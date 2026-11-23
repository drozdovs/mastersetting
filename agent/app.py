# -*- coding: utf-8 -*-
"""MasterSetting Agent — GUI поверх ядра.

Экран:
  * Главное окно: кнопки «Сохранить» / «Загрузить» / «Инструкции» / «Помощь»,
    индикатор подключения к серверу, автопоиск носителя.
  * SaveWindow / LoadWindow — выбор оператора/камеры/настроек + прогресс и отмена.
"""

from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from mastersetting import __version__, fs_ops
from mastersetting.catalog import Catalog
from mastersetting.config import Config
from mastersetting.engine import ArchiveEngine, EngineError
from mastersetting.platform import check_usb_drive, open_path

from .sync_client import SyncClient
from .widgets import EditableComboBox

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


def resource_path(relative: str) -> str:
    """Путь к ресурсу, работающий и в исходниках, и в собранном .exe."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, relative)
    # Рядом с пакетом agent/ лежит корень проекта; иконка в deploy/
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, relative)


class MasterSettingApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.config_obj = Config.load()
        self.catalog = Catalog(config=self.config_obj)
        self.engine = ArchiveEngine(config=self.config_obj, catalog=self.catalog)
        self.sync = SyncClient(config=self.config_obj, catalog=self.catalog)
        self.offline = self.sync.cache
        self._drive_poll_id = None
        self._sync_poll_id = None

        self.title("MasterSetting")
        self._set_window_icon()
        self.geometry("420x340")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self._init_directories()
        self.center_window()
        self.create_widgets()
        self.bind_hotkeys()
        self._start_drive_poll()
        self._start_sync()

    # ------------------------------------------------------------------
    def _init_directories(self):
        for path in (self.config_obj.base_path, self.config_obj.cameraman_path,
                     self.config_obj.main_path, self.config_obj.instructions_path):
            os.makedirs(path, exist_ok=True)
        if not os.path.exists(self.config_obj.camera_file):
            with open(self.config_obj.camera_file, "w", encoding="utf-8") as f:
                f.write("PanasonicAG-CX350\nSonyZ90\nSonyFX3\nSonyFX6\n"
                        "PanasonicAG-PX5000\nPanasonic270")

    def _set_window_icon(self):
        """Установить иконку окна (и панели задач) из встроенного ресурса."""
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
                self._icon_ref = img  # держим ссылку, иначе GC уберёт
        except Exception:
            pass

    def center_window(self):
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (self.winfo_width() // 2)
        y = (self.winfo_screenheight() // 2) - (self.winfo_height() // 2)
        self.geometry(f"{self.winfo_width()}x{self.winfo_height()}+{x}+{y}")

    def bind_hotkeys(self):
        self.bind("<F9>", lambda e: self.open_load_window())
        self.bind("<F5>", lambda e: self.open_save_window())
        self.bind("<F12>", lambda e: self.open_instructions_window())
        self.bind("<F1>", lambda e: self.open_help_window())
        self.bind("<Escape>", lambda e: self.on_closing())

    def create_widgets(self):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(padx=30, pady=20, fill="both", expand=True)

        # Индикатор состояния носителя
        self.drive_label = ctk.CTkLabel(
            frame, text="Проверка носителя…",
            font=ctk.CTkFont(size=11), text_color="gray",
        )
        self.drive_label.pack(pady=(0, 12))

        for text, cmd in (
            ("Загрузить настройки (F9)", self.open_load_window),
            ("Сохранить настройки (F5)", self.open_save_window),
            ("Инструкции (F12)", self.open_instructions_window),
            ("Помощь (F1)", self.open_help_window),
        ):
            ctk.CTkButton(frame, text=text, width=290, height=42,
                          font=ctk.CTkFont(size=13), command=cmd).pack(pady=5)

        # Статус сервера
        self.server_label = ctk.CTkLabel(
            frame, text="Сервер: не подключён (офлайн-режим)",
            font=ctk.CTkFont(size=10), text_color="gray",
        )
        self.server_label.pack(pady=(12, 0))

    # ------------------------------------------------------------------
    def _start_drive_poll(self):
        if not self.config_obj.auto_detect_drive:
            return
        self._poll_drive()

    def _poll_drive(self):
        drive, error = check_usb_drive(self.config_obj.removable_drive_start)
        if drive:
            self.drive_label.configure(text=f"Носитель: {drive}", text_color="#4ade80")
        elif error and "несколько" in error.lower():
            self.drive_label.configure(text="Несколько носителей — оставьте один",
                                       text_color="#fbbf24")
        else:
            self.drive_label.configure(text="Карта не обнаружена", text_color="gray")
        self._drive_poll_id = self.after(
            int(self.config_obj.auto_detect_poll_seconds * 1000), self._poll_drive
        )

    # ------------------------------------------------------------------
    def _start_sync(self):
        if not self.sync.enabled:
            self.server_label.configure(text="Сервер: не настроен (офлайн-режим)")
            return
        self.sync.start()
        self._poll_sync()

    def _poll_sync(self):
        st = self.sync.state
        if st.online:
            self.server_label.configure(
                text=f"Сервер: подключён (v{__version__})", text_color="#4ade80")
        else:
            last = self.offline.last_sync_iso()
            hint = f"офлайн-режим, кэш от {last}" if last else "офлайн-режим"
            self.server_label.configure(
                text=f"Сервер: нет связи ({hint})", text_color="#fbbf24")
        self._sync_poll_id = self.after(3000, self._poll_sync)

    # ------------------------------------------------------------------
    def open_load_window(self):
        OperationWindow(self, mode="load")

    def open_save_window(self):
        OperationWindow(self, mode="save")

    def open_instructions_window(self):
        InstructionsWindow(self)

    def open_help_window(self):
        if os.path.exists(self.config_obj.help_image):
            try:
                open_path(self.config_obj.help_image)
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("Ошибка", f"Не удалось открыть изображение: {e}")
        else:
            messagebox.showerror("Ошибка",
                                 f"Файл помощи не найден: {self.config_obj.help_image}")

    def on_closing(self):
        for poll_id in (self._drive_poll_id, self._sync_poll_id):
            if poll_id:
                try:
                    self.after_cancel(poll_id)
                except Exception:
                    pass
        try:
            self.sync.stop()
        except Exception:
            pass
        self.destroy()


# ===========================================================================
# Окно операции (сохранение или загрузка)
# ===========================================================================

class OperationWindow(ctk.CTkToplevel):
    def __init__(self, parent: MasterSettingApp, mode: str):
        super().__init__(parent)
        self.app = parent
        self.cfg = parent.config_obj
        self.catalog = parent.catalog
        self.engine = parent.engine
        self.mode = mode  # 'save' | 'load'
        self._cancel = False
        self._worker = None

        title = "Сохранить настройки" if mode == "save" else "Загрузить настройки"
        self.title(title)
        self.geometry("420x460")
        self.resizable(False, False)
        self.grab_set()
        self.center_window()
        self.create_widgets()
        self.load_values()
        self.bind("<Escape>", lambda e: self.on_close())

    def center_window(self):
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (self.winfo_width() // 2)
        y = (self.winfo_screenheight() // 2) - (self.winfo_height() // 2)
        self.geometry(f"{self.winfo_width()}x{self.winfo_height()}+{x}+{y}")

    def create_widgets(self):
        frame = ctk.CTkFrame(self)
        frame.pack(padx=30, pady=20, fill="both", expand=True)

        ctk.CTkLabel(frame, text="Фамилия оператора:",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(pady=(0, 4))
        self.operator_combo = EditableComboBox(
            frame, width=260, max_length=self.cfg.max_name_length,
            command=lambda _v: self._reload_settings(),
        )
        self.operator_combo.pack(pady=(0, 12))

        ctk.CTkLabel(frame, text="Камера:",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(pady=(0, 4))
        self.camera_combo = EditableComboBox(
            frame, width=260, max_length=self.cfg.max_name_length,
            command=lambda _v: self._reload_settings(),
        )
        self.camera_combo.pack(pady=(0, 12))

        ctk.CTkLabel(frame, text="Название настроек:",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(pady=(0, 4))
        self.settings_combo = EditableComboBox(
            frame, width=260, max_length=self.cfg.max_name_length,
        )
        self.settings_combo.pack(pady=(0, 14))

        self.progress = ctk.CTkProgressBar(frame, width=260)
        self.progress.set(0)
        self.progress.pack(pady=(0, 6))

        self.progress_label = ctk.CTkLabel(
            frame, text="", font=ctk.CTkFont(size=10), text_color="gray")
        self.progress_label.pack(pady=(0, 10))

        btns = ctk.CTkFrame(frame, fg_color="transparent")
        btns.pack()

        action = "Сохранить" if self.mode == "save" else "Загрузить"
        self.action_btn = ctk.CTkButton(
            btns, text=action, width=130, height=36,
            font=ctk.CTkFont(size=12, weight="bold"), command=self.start)
        self.action_btn.pack(side="left", padx=6)

        self.cancel_btn = ctk.CTkButton(
            btns, text="Отмена (ESC)", width=130, height=36, fg_color="gray",
            font=ctk.CTkFont(size=12), command=self.on_close)
        self.cancel_btn.pack(side="left", padx=6)

    # ------------------------------------------------------------------
    def load_values(self):
        cached = self.app.offline.get_config()

        operators = self.catalog.list_operators()
        # Дополнительно сканируем папки архива и берём из офлайн-кэша
        if os.path.isdir(self.cfg.cameraman_path):
            for item in os.listdir(self.cfg.cameraman_path):
                if os.path.isdir(os.path.join(self.cfg.cameraman_path, item)):
                    if item not in operators:
                        operators.append(item)
        for op in cached.operators:
            if op not in operators:
                operators.append(op)
        operators.sort()
        self.operator_combo.configure_values(operators or [""])

        cameras = self.catalog.list_cameras()
        if os.path.exists(self.cfg.camera_file):
            with open(self.cfg.camera_file, encoding="utf-8") as f:
                for line in f:
                    cam = line.strip()
                    if cam and cam not in cameras:
                        cameras.append(cam)
        for cam in cached.cameras:
            if cam not in cameras:
                cameras.append(cam)
        cameras.sort()
        self.camera_combo.configure_values(cameras or [""])

        self._reload_settings()

    def _operator_camera(self):
        return self.operator_combo.get(), self.camera_combo.get()

    def _reload_settings(self):
        if self.mode != "load":
            self.settings_combo.configure_values(["Основные"])
            return
        operator, camera = self._operator_camera()
        names = []
        cam_dir = os.path.join(self.cfg.cameraman_path, operator, camera)
        if operator and camera and os.path.isdir(cam_dir):
            names = sorted(
                (item for item in os.listdir(cam_dir)
                 if os.path.isdir(os.path.join(cam_dir, item))),
                reverse=True,
            )
        self.settings_combo.configure_values(names or ["Настройки отсутствуют"])

    # ------------------------------------------------------------------
    def start(self):
        operator, camera = self._operator_camera()
        settings = self.settings_combo.get()

        if not operator or not camera or not settings or settings == "Настройки отсутствуют":
            messagebox.showerror("Ошибка", "Заполните все поля")
            return

        # Для save — при новой камере допишем в список и в офлайн-кэш
        if self.mode == "save" and camera not in self.camera_combo.original_values:
            try:
                with open(self.cfg.camera_file, "a", encoding="utf-8") as f:
                    f.write(f"\n{camera}")
            except OSError:
                pass
            self.catalog.add_camera(camera)
            self.app.offline.merge_camera(camera)
        self.catalog.add_operator(operator)
        self.app.offline.merge_operator(operator)

        # Перезапись?
        overwrite = False
        if self.mode == "save":
            from mastersetting.naming import settings_dir
            dest = str(settings_dir(self.cfg.base_path, operator, camera, settings))
            if os.path.exists(dest):
                if not messagebox.askyesno(
                        "Подтверждение",
                        "ДАННЫЕ НАСТРОЙКИ СУЩЕСТВУЮТ. ПЕРЕЗАПИСАТЬ?"):
                    return
                overwrite = True

        self._cancel = False
        self.action_btn.configure(state="disabled", text="Копирование…")
        self.cancel_btn.configure(text="Прервать")
        self.progress.set(0)
        self.progress_label.configure(text="Подготовка…")

        self._worker = threading.Thread(
            target=self._run, args=(operator, camera, settings, overwrite),
            daemon=True,
        )
        self._worker.start()

    def _run(self, operator, camera, settings, overwrite):
        def on_progress(p: fs_ops.Progress):
            self.after(0, lambda: self._update_progress(p))

        try:
            if self.mode == "save":
                report = self.engine.save(
                    operator, camera, settings,
                    overwrite=overwrite,
                    progress=on_progress,
                    should_cancel=lambda: self._cancel,
                )
            else:
                report = self.engine.load(
                    operator, camera, settings,
                    progress=on_progress,
                    should_cancel=lambda: self._cancel,
                )
        except fs_ops.CopyCancelled:
            self.after(0, self._on_cancelled)
            return
        except EngineError as e:
            self.after(0, lambda: self._on_error(str(e)))
            return
        except Exception as e:  # noqa: BLE001
            self.after(0, lambda: self._on_error(f"Непредвиденная ошибка: {e}"))
            return

        self.after(0, lambda: self._on_success(report))

    def _update_progress(self, p: fs_ops.Progress):
        self.progress.set(p.percent / 100.0)
        self.progress_label.configure(
            text=f"{p.percent:.0f}%  •  {p.done_files}/{p.total_files} файлов")

    def _on_success(self, report):
        self.progress.set(1)
        # После успешного сохранения отправляем метаданные на сервер (если есть связь)
        if report.ok and self.mode == "save" and self.app.sync.enabled:
            threading.Thread(target=self._push_setting, daemon=True).start()
        if report.ok:
            messagebox.showinfo("Успех", report.message)
            self.destroy()
        else:
            messagebox.showwarning("Внимание", report.message)
            self._reset_buttons()

    def _push_setting(self):
        from mastersetting.naming import settings_dir
        operator, camera = self._operator_camera()
        settings = self.settings_combo.get()
        path = str(settings_dir(self.cfg.base_path, operator, camera, settings))
        from mastersetting.platform import get_directory_size
        try:
            size = get_directory_size(path)
        except Exception:
            size = 0
        self.app.sync.push_setting(operator, camera, settings, path, size)

    def _on_cancelled(self):
        self.progress.set(0)
        self.progress_label.configure(text="Отменено")
        messagebox.showinfo("Отменено", "Операция прервана пользователем")
        self._reset_buttons()

    def _on_error(self, text):
        self.progress.set(0)
        self.progress_label.configure(text="Ошибка")
        messagebox.showerror("Ошибка", text)
        self._reset_buttons()

    def _reset_buttons(self):
        action = "Сохранить" if self.mode == "save" else "Загрузить"
        self.action_btn.configure(state="normal", text=action)
        self.cancel_btn.configure(text="Отмена (ESC)")

    # ------------------------------------------------------------------
    def on_close(self):
        self._cancel = True
        if self._worker and self._worker.is_alive():
            # Даём потоку завершиться, окно закроем по завершении
            self.after(100, self.on_close)
            return
        self.destroy()


# ===========================================================================
# Окно инструкций
# ===========================================================================

class InstructionsWindow(ctk.CTkToplevel):
    def __init__(self, parent: MasterSettingApp):
        super().__init__(parent)
        self.parent = parent
        self.cfg = parent.config_obj
        self.title("Инструкции")
        self.geometry("420x260")
        self.resizable(False, False)
        self.grab_set()
        self.center_window()
        self.create_widgets()
        self.load_instructions()
        self.bind("<Escape>", lambda e: self.destroy())

    def center_window(self):
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (self.winfo_width() // 2)
        y = (self.winfo_screenheight() // 2) - (self.winfo_height() // 2)
        self.geometry(f"{self.winfo_width()}x{self.winfo_height()}+{x}+{y}")

    def create_widgets(self):
        frame = ctk.CTkFrame(self)
        frame.pack(padx=30, pady=20, fill="both", expand=True)
        ctk.CTkLabel(frame, text="Выберите инструкцию:",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(pady=(0, 10))
        self.combo = ctk.CTkComboBox(frame, values=[], width=260, height=35,
                                     state="readonly")
        self.combo.pack(pady=(0, 20))
        ctk.CTkButton(frame, text="Открыть", width=130, height=36,
                      font=ctk.CTkFont(size=12, weight="bold"),
                      command=self.open_instruction).pack(pady=(0, 8))
        ctk.CTkButton(frame, text="Закрыть (ESC)", width=130, height=36,
                      fg_color="gray", command=self.destroy).pack()

    def load_instructions(self):
        items = []
        allowed = {e.lower() for e in self.cfg.instruction_extensions}
        if os.path.isdir(self.cfg.instructions_path):
            for folder in os.listdir(self.cfg.instructions_path):
                folder_path = os.path.join(self.cfg.instructions_path, folder)
                if not os.path.isdir(folder_path):
                    continue
                for file in os.listdir(folder_path):
                    if os.path.isfile(os.path.join(folder_path, file)):
                        name, ext = os.path.splitext(file)
                        if ext.lower() in allowed:
                            items.append(f"{folder.upper()}/{name}")
        items.sort()
        self.combo.configure(values=items or ["Инструкции отсутствуют"])
        self.combo.set(items[0] if items else "Инструкции отсутствуют")

    def open_instruction(self):
        selection = self.combo.get()
        if selection == "Инструкции отсутствуют" or not selection:
            messagebox.showwarning("Внимание", "Выберите инструкцию из списка")
            return
        try:
            folder_upper, file_name = selection.split("/")
            for folder in os.listdir(self.cfg.instructions_path):
                if folder.upper() != folder_upper:
                    continue
                folder_path = os.path.join(self.cfg.instructions_path, folder)
                for file in os.listdir(folder_path):
                    name, _ = os.path.splitext(file)
                    if name == file_name:
                        open_path(os.path.join(folder_path, file))
                        return
            messagebox.showerror("Ошибка", "Файл инструкции не найден")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Ошибка", f"Не удалось открыть файл: {e}")


def main():
    app = MasterSettingApp()
    app.mainloop()


if __name__ == "__main__":
    main()
