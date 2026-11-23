#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MASTERSETTING - Программа для управления настройками камер
Версия 1.9
"""

import os
import shutil
import threading
import tkinter as tk
from tkinter import messagebox
from datetime import datetime
import re
import sys
from pathlib import Path

import customtkinter as ctk
from PIL import Image

from platform_layer import (
    default_base_path,
    get_removable_drives,
    check_free_space,
    open_path,
)

# Настройка темы Material Black
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

class Config:
    BASE_PATH = default_base_path()
    CAMERAMAN_PATH = f"{BASE_PATH}/cameraman"
    MAIN_PATH = f"{BASE_PATH}/main"
    CAMERA_FILE = f"{MAIN_PATH}/camera.txt"
    INSTRUCTIONS_PATH = f"{BASE_PATH}/instructions"
    HELP_IMAGE = f"{MAIN_PATH}/saveload.jpg"
    
    # Расширения для исключения при сохранении
    EXCLUDED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', 
                          '.mp4', '.avi', '.mov', '.mkv', '.wmv', '.mxf', '.mts'}
    
    # Файлы для исключения при копировании
    EXCLUDED_FILES = {'LASTCLIP.TXT', 'lastclip.txt'}
    
    # Белый список расширений для инструкций
    ALLOWED_INSTRUCTION_EXTENSIONS = {'.txt', '.doc', '.docx', '.pdf', '.html'}
    
    # Ограничения ввода
    MAX_NAME_LENGTH = 30
    
    # Буквы дисков для флешек (начинаем с E:)
    REMOVABLE_DRIVE_START = 'E'


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def init_directories():
    """Создание необходимых директорий при первом запуске"""
    for path in [Config.BASE_PATH, Config.CAMERAMAN_PATH, Config.MAIN_PATH, Config.INSTRUCTIONS_PATH]:
        os.makedirs(path, exist_ok=True)
    
    # Создание camera.txt по умолчанию, если отсутствует
    if not os.path.exists(Config.CAMERA_FILE):
        with open(Config.CAMERA_FILE, 'w', encoding='utf-8') as f:
            f.write("PanasonicAG-CX350\nSonyZ90\nSonyFX3\nSonyFX6\nPanasonicAG-PX5000\nPanasonic270")


def check_usb_drive():
    """Проверка наличия флешки (должна быть ровно одна)"""
    drives = get_removable_drives()
    if len(drives) == 0:
        return None, "Вставьте карту с настройками!"
    elif len(drives) > 1:
        return None, "Обнаружено несколько сменных носителей. Оставьте только одну флешку в кардридере!"
    return drives[0], None


def is_write_protected(drive_path):
    """Проверка защиты карты от записи"""
    try:
        test_file = os.path.join(drive_path, ".write_test.tmp")
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
        return False
    except:
        return True


def get_directory_size(path):
    """Получение размера директории в байтах"""
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.exists(fp):
                total += os.path.getsize(fp)
    return total


def sanitize_name(name):
    """Очистка имени: только буквы и цифры, удаление пробелов по краям, ограничение длины"""
    name = name.strip()
    name = re.sub(r'[^a-zA-Zа-яА-Я0-9]', '', name)
    return name[:Config.MAX_NAME_LENGTH]


def validate_input(char):
    """Проверка вводимого символа (только буквы и цифры)"""
    if char.isalnum() or char in ('а','б','в','г','д','е','ё','ж','з','и','й','к','л','м','н','о','п','р','с','т','у','ф','х','ц','ч','ш','щ','ъ','ы','ь','э','ю','я',
                                   'А','Б','В','Г','Д','Е','Ё','Ж','З','И','Й','К','Л','М','Н','О','П','Р','С','Т','У','Ф','Х','Ц','Ч','Ш','Щ','Ъ','Ы','Ь','Э','Ю','Я'):
        return True
    return False


def should_exclude_file(filename):
    """Проверка, нужно ли исключить файл из копирования"""
    # Проверяем по имени файла
    if filename in Config.EXCLUDED_FILES:
        return True
    # Проверяем по расширению
    ext = os.path.splitext(filename)[1].lower()
    if ext in Config.EXCLUDED_EXTENSIONS:
        return True
    return False


def safe_copy(src, dst):
    """Безопасное копирование файла с обработкой ошибок"""
    try:
        # Если файл существует, удаляем его (перезаписываем)
        if os.path.exists(dst):
            try:
                os.remove(dst)
            except:
                pass
        shutil.copy2(src, dst)
        return True
    except Exception as e:
        # Молча пропускаем ошибки
        return False


def safe_copytree(src, dst):
    """Безопасное копирование папки с перезаписью"""
    try:
        # Создаем папку назначения
        os.makedirs(dst, exist_ok=True)
        
        for item in os.listdir(src):
            src_item = os.path.join(src, item)
            dst_item = os.path.join(dst, item)
            
            # Проверяем, нужно ли исключить файл
            if os.path.isfile(src_item) and should_exclude_file(item):
                continue
            
            if os.path.isdir(src_item):
                safe_copytree(src_item, dst_item)
            else:
                safe_copy(src_item, dst_item)
        return True
    except Exception as e:
        # Молча пропускаем ошибки
        return False


# ============================================================
# КАСТОМНЫЙ КОМБОБОКС С ВОЗМОЖНОСТЬЮ ДОБАВЛЕНИЯ НОВОГО ЗНАЧЕНИЯ
# ============================================================

class EditableComboBox(ctk.CTkFrame):
    """Комбобокс с возможностью добавления нового значения через поле ввода"""
    def __init__(self, master, values=None, command=None, width=250, **kwargs):
        super().__init__(master, fg_color="transparent")
        
        self.original_values = values if values else []
        self.command = command
        self.width = width
        self.is_editing = False
        self.entry_widget = None
        self.combo_widget = None
        
        self.create_combo()
    
    def update_values_list(self):
        """Обновляет список значений с добавлением пункта '+ Добавить новое' в конце"""
        values_with_add = self.original_values.copy()
        if "+ Добавить новое" not in values_with_add:
            values_with_add.append("+ Добавить новое")
        
        if self.combo_widget and self.combo_widget.winfo_exists():
            self.combo_widget.configure(values=values_with_add)
            current = self.combo_widget.get()
            if current and current != "+ Добавить новое" and current in values_with_add:
                self.combo_widget.set(current)
            elif self.original_values:
                self.combo_widget.set(self.original_values[0])
    
    def create_combo(self):
        """Создание обычного комбобокса"""
        if self.combo_widget:
            self.combo_widget.destroy()
        
        values_with_add = self.original_values.copy()
        if "+ Добавить новое" not in values_with_add:
            values_with_add.append("+ Добавить новое")
        
        self.combo_widget = ctk.CTkComboBox(
            self, 
            values=values_with_add, 
            width=self.width, 
            height=35,
            state="readonly",
            command=self.on_select
        )
        self.combo_widget.pack(fill="x")
        self.combo_widget.bind('<KeyPress>', self.on_key_press)
        
        if self.original_values:
            self.combo_widget.set(self.original_values[0])
        elif values_with_add:
            self.combo_widget.set(values_with_add[0])
    
    def create_entry(self):
        """Создание поля ввода для нового значения"""
        if self.entry_widget:
            self.entry_widget.destroy()
        
        if self.combo_widget:
            self.combo_widget.destroy()
        
        self.entry_widget = LimitedEntry(self, placeholder_text="Введите новое значение (макс. 30 симв.)", width=self.width)
        self.entry_widget.pack(fill="x")
        self.entry_widget.bind('<Return>', self.on_entry_confirm)
        self.entry_widget.bind('<Escape>', self.on_entry_cancel)
        self.entry_widget.bind('<FocusOut>', self.on_entry_cancel)
        self.entry_widget.focus()
    
    def on_select(self, choice):
        """Обработка выбора из списка"""
        if choice == "+ Добавить новое":
            self.create_entry()
        else:
            if self.command:
                self.command(choice)
    
    def on_key_press(self, event):
        """Обработка нажатия клавиш на комбобоксе"""
        if event.keysym == 'Return' and self.combo_widget.get() == "+ Добавить новое":
            self.create_entry()
    
    def on_entry_confirm(self, event):
        """Подтверждение ввода нового значения"""
        new_value = sanitize_name(self.entry_widget.get())
        if new_value:
            if new_value not in self.original_values:
                self.original_values.append(new_value)
            self.original_values.sort()
            self.update_values_list()
            self.create_combo()
            self.combo_widget.set(new_value)
            if self.command:
                self.command(new_value)
        else:
            self.create_combo()
    
    def on_entry_cancel(self, event):
        """Отмена ввода нового значения"""
        self.create_combo()
    
    def get(self):
        """Получить текущее значение"""
        if self.entry_widget and self.entry_widget.winfo_exists():
            return self.entry_widget.get()
        if self.combo_widget and self.combo_widget.winfo_exists():
            value = self.combo_widget.get()
            return value if value != "+ Добавить новое" else ""
        return ""
    
    def set(self, value):
        """Установить значение"""
        if self.combo_widget and self.combo_widget.winfo_exists() and value in self.original_values:
            self.combo_widget.set(value)
    
    def configure_values(self, values):
        """Обновить список значений"""
        self.original_values = values.copy()
        self.update_values_list()
        if self.combo_widget and self.combo_widget.winfo_exists() and self.original_values:
            self.combo_widget.set(self.original_values[0])


# ============================================================
# КАСТОМНОЕ ПОЛЕ ВВОДА (ТОЛЬКО БУКВЫ/ЦИФРЫ, МАКСИМУМ 30 СИМВОЛОВ)
# ============================================================

class LimitedEntry(ctk.CTkEntry):
    """Поле ввода с ограничением по символам и длине"""
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(height=35)
        self.bind('<KeyRelease>', self.on_key_release)
        self.bind('<Key>', self.validate_key)
    
    def validate_key(self, event):
        """Проверка вводимого символа (разрешаем Backspace, Delete и специальные клавиши)"""
        if event.keysym in ('BackSpace', 'Delete', 'Left', 'Right', 'Home', 'End'):
            return None
        if event.char:
            if not validate_input(event.char):
                return 'break'
        return None
    
    def on_key_release(self, event):
        """Ограничение длины и удаление недопустимых символов"""
        current = self.get()
        cleaned = ''.join(c for c in current if validate_input(c))
        if cleaned != current:
            self.delete(0, 'end')
            self.insert(0, cleaned)
            current = cleaned
        if len(current) > Config.MAX_NAME_LENGTH:
            self.delete(Config.MAX_NAME_LENGTH, 'end')


# ============================================================
# ГЛАВНОЕ ОКНО
# ============================================================

class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("MasterSetting")
        self.geometry("400x280")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        init_directories()
        self.center_window()
        self.create_widgets()
        self.bind_hotkeys()
    
    def center_window(self):
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (self.winfo_width() // 2)
        y = (self.winfo_screenheight() // 2) - (self.winfo_height() // 2)
        self.geometry(f"{self.winfo_width()}x{self.winfo_height()}+{x}+{y}")
    
    def bind_hotkeys(self):
        self.bind('<F9>', lambda e: self.open_load_window())
        self.bind('<F5>', lambda e: self.open_save_window())
        self.bind('<F12>', lambda e: self.open_instructions_window())
        self.bind('<F1>', lambda e: self.open_help_window())
        self.bind('<Escape>', lambda e: self.on_closing())
    
    def create_widgets(self):
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(padx=30, pady=25, fill="both", expand=True)
        
        self.load_btn = ctk.CTkButton(main_frame, text="Загрузить настройки (F9)", 
                                       width=280, height=45, font=ctk.CTkFont(size=13),
                                       command=self.open_load_window)
        self.load_btn.pack(pady=6)
        
        self.save_btn = ctk.CTkButton(main_frame, text="Сохранить настройки (F5)", 
                                       width=280, height=45, font=ctk.CTkFont(size=13),
                                       command=self.open_save_window)
        self.save_btn.pack(pady=6)
        
        self.instructions_btn = ctk.CTkButton(main_frame, text="Инструкции (F12)", 
                                              width=280, height=45, font=ctk.CTkFont(size=13),
                                              command=self.open_instructions_window)
        self.instructions_btn.pack(pady=6)
        
        self.help_btn = ctk.CTkButton(main_frame, text="Помощь (F1)", 
                                      width=280, height=45, font=ctk.CTkFont(size=13),
                                      command=self.open_help_window)
        self.help_btn.pack(pady=6)
    
    def open_load_window(self):
        LoadWindow(self)
    
    def open_save_window(self):
        SaveWindow(self)
    
    def open_instructions_window(self):
        InstructionsWindow(self)
    
    def open_help_window(self):
        if os.path.exists(Config.HELP_IMAGE):
            try:
                open_path(Config.HELP_IMAGE)
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось открыть изображение: {e}")
        else:
            messagebox.showerror("Ошибка", f"Файл помощи не найден: {Config.HELP_IMAGE}")
    
    def on_closing(self):
        self.destroy()
        sys.exit(0)


# ============================================================
# ОКНО СОХРАНЕНИЯ НАСТРОЕК
# ============================================================

class SaveWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Сохранить настройки")
        self.geometry("400x400")
        self.resizable(False, False)
        self.grab_set()
        self.center_window()
        
        self.create_widgets()
        self.load_operators()
        self.load_cameras()
        self.load_settings_names()
        
        self.bind('<Escape>', lambda e: self.destroy())
    
    def center_window(self):
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (self.winfo_width() // 2)
        y = (self.winfo_screenheight() // 2) - (self.winfo_height() // 2)
        self.geometry(f"{self.winfo_width()}x{self.winfo_height()}+{x}+{y}")
    
    def create_widgets(self):
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(padx=30, pady=20, fill="both", expand=True)
        
        self.operator_label = ctk.CTkLabel(main_frame, text="Фамилия оператора:", 
                                           font=ctk.CTkFont(size=12, weight="bold"))
        self.operator_label.pack(anchor="center", pady=(0, 5))
        
        self.operator_combo = EditableComboBox(main_frame, width=250, command=self.on_operator_change)
        self.operator_combo.pack(anchor="center", pady=(0, 15))
        
        self.camera_label = ctk.CTkLabel(main_frame, text="Камера:", 
                                         font=ctk.CTkFont(size=12, weight="bold"))
        self.camera_label.pack(anchor="center", pady=(0, 5))
        
        self.camera_combo = EditableComboBox(main_frame, width=250, command=self.on_camera_change)
        self.camera_combo.pack(anchor="center", pady=(0, 15))
        
        self.settings_label = ctk.CTkLabel(main_frame, text="Название настроек:", 
                                           font=ctk.CTkFont(size=12, weight="bold"))
        self.settings_label.pack(anchor="center", pady=(0, 5))
        
        self.settings_combo = EditableComboBox(main_frame, width=250, command=self.on_settings_change)
        self.settings_combo.pack(anchor="center", pady=(0, 20))
        
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(pady=(10, 0))
        
        self.save_btn = ctk.CTkButton(button_frame, text="Сохранить", width=120, height=35, 
                                      font=ctk.CTkFont(size=12, weight="bold"),
                                      command=self.save_settings, state="disabled")
        self.save_btn.pack(side="left", padx=10)
        
        self.back_btn = ctk.CTkButton(button_frame, text="Назад (ESC)", width=120, height=35,
                                      font=ctk.CTkFont(size=12), command=self.destroy, fg_color="gray")
        self.back_btn.pack(side="left", padx=10)
    
    def load_operators(self):
        operators = []
        if os.path.exists(Config.CAMERAMAN_PATH):
            for item in os.listdir(Config.CAMERAMAN_PATH):
                item_path = os.path.join(Config.CAMERAMAN_PATH, item)
                if os.path.isdir(item_path):
                    operators.append(item)
        operators.sort()
        self.operator_combo.configure_values(operators)
    
    def load_cameras(self):
        cameras = []
        if os.path.exists(Config.CAMERA_FILE):
            with open(Config.CAMERA_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    cam = line.strip()
                    if cam:
                        cameras.append(cam)
        cameras.sort()
        self.camera_combo.configure_values(cameras)
    
    def load_settings_names(self):
        settings_names = ["Основные"]
        self.settings_combo.configure_values(settings_names)
    
    def on_operator_change(self, choice):
        self.validate_fields()
    
    def on_camera_change(self, choice):
        self.validate_fields()
    
    def on_settings_change(self, choice):
        self.validate_fields()
    
    def validate_fields(self, event=None):
        operator_valid = self.operator_combo.get() != ""
        camera_valid = self.camera_combo.get() != ""
        settings_valid = self.settings_combo.get() != ""
        
        if operator_valid and camera_valid and settings_valid:
            self.save_btn.configure(state="normal")
        else:
            self.save_btn.configure(state="disabled")
    
    def save_settings(self):
        operator = self.operator_combo.get()
        camera = self.camera_combo.get()
        settings_name = self.settings_combo.get()
        
        if camera not in self.camera_combo.original_values:
            with open(Config.CAMERA_FILE, 'a', encoding='utf-8') as f:
                f.write(f"\n{camera}")
            self.load_cameras()
        
        drive, error = check_usb_drive()
        if error:
            retry = messagebox.askretrycancel("Ошибка", error)
            if retry:
                self.save_settings()
            return
        
        if is_write_protected(drive):
            retry = messagebox.askretrycancel("Ошибка", "Карта защищена от записи! Снимите защиту от копирования на носителе!")
            if retry:
                self.save_settings()
            return
        
        source_path = drive
        required_size = get_directory_size(source_path)
        if not check_free_space(Config.CAMERAMAN_PATH, required_size):
            messagebox.showerror("Ошибка", "Недостаточно свободного места на диске C:")
            return
        
        date_str = datetime.now().strftime("%Y%m%d")
        dest_path = os.path.join(Config.CAMERAMAN_PATH, operator, camera, f"{date_str}_{settings_name}")
        
        if os.path.exists(dest_path):
            if not messagebox.askyesno("Подтверждение", "ДАННЫЕ НАСТРОЙКИ СУЩЕСТВУЮТ. ВЫ ХОТИТЕ ИХ ПЕРЕЗАПИСАТЬ?"):
                return
        
        def copy_thread():
            self.after(0, lambda: self.save_btn.configure(state="disabled", text="Копирование..."))
            old_path = None
            try:
                if os.path.exists(dest_path):
                    old_path = dest_path + "_OLD"
                    shutil.move(dest_path, old_path)
                
                os.makedirs(dest_path, exist_ok=True)
                safe_copytree(source_path, dest_path)
                
                if old_path and os.path.exists(old_path):
                    shutil.rmtree(old_path)
                
                # Диалог и закрытие окна — только из главного потока Tk
                self.after(0, lambda: messagebox.showinfo("Успех", "Настройки успешно сохранены на диск"))
                self.after(0, self.destroy)
            except Exception as e:
                if old_path and os.path.exists(old_path) and not os.path.exists(dest_path):
                    shutil.move(old_path, dest_path)
                error_text = str(e)
                self.after(0, lambda: messagebox.showerror("Ошибка", f"Ошибка при копировании: {error_text}"))
            finally:
                self.after(0, lambda: self.save_btn.configure(state="normal", text="Сохранить"))
        
        threading.Thread(target=copy_thread, daemon=True).start()


# ============================================================
# ОКНО ЗАГРУЗКИ НАСТРОЕК
# ============================================================

class LoadWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Загрузить настройки")
        self.geometry("400x350")
        self.resizable(False, False)
        self.grab_set()
        self.center_window()
        
        self.create_widgets()
        self.load_operators()
        
        self.bind('<Escape>', lambda e: self.destroy())
    
    def center_window(self):
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (self.winfo_width() // 2)
        y = (self.winfo_screenheight() // 2) - (self.winfo_height() // 2)
        self.geometry(f"{self.winfo_width()}x{self.winfo_height()}+{x}+{y}")
    
    def create_widgets(self):
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(padx=30, pady=20, fill="both", expand=True)
        
        self.operator_label = ctk.CTkLabel(main_frame, text="Фамилия оператора:", 
                                           font=ctk.CTkFont(size=12, weight="bold"))
        self.operator_label.pack(anchor="center", pady=(0, 5))
        
        self.operator_combo = ctk.CTkComboBox(main_frame, values=[], width=250, height=35, 
                                               state="readonly", command=self.on_operator_change)
        self.operator_combo.pack(anchor="center", pady=(0, 15))
        
        self.camera_label = ctk.CTkLabel(main_frame, text="Камера:", 
                                         font=ctk.CTkFont(size=12, weight="bold"))
        self.camera_label.pack(anchor="center", pady=(0, 5))
        
        self.camera_combo = ctk.CTkComboBox(main_frame, values=[], width=250, height=35,
                                             state="readonly", command=self.on_camera_change)
        self.camera_combo.pack(anchor="center", pady=(0, 15))
        
        self.settings_label = ctk.CTkLabel(main_frame, text="Название настроек:", 
                                            font=ctk.CTkFont(size=12, weight="bold"))
        self.settings_label.pack(anchor="center", pady=(0, 5))
        
        self.settings_combo = ctk.CTkComboBox(main_frame, values=[], width=250, height=35,
                                               state="readonly")
        self.settings_combo.pack(anchor="center", pady=(0, 20))
        
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(pady=(10, 0))
        
        self.load_btn = ctk.CTkButton(button_frame, text="Загрузить", width=120, height=35,
                                      font=ctk.CTkFont(size=12, weight="bold"), command=self.load_settings)
        self.load_btn.pack(side="left", padx=10)
        
        self.back_btn = ctk.CTkButton(button_frame, text="Назад (ESC)", width=120, height=35,
                                      font=ctk.CTkFont(size=12), command=self.destroy, fg_color="gray")
        self.back_btn.pack(side="left", padx=10)
    
    def load_operators(self):
        operators = []
        if os.path.exists(Config.CAMERAMAN_PATH):
            for item in os.listdir(Config.CAMERAMAN_PATH):
                item_path = os.path.join(Config.CAMERAMAN_PATH, item)
                if os.path.isdir(item_path):
                    operators.append(item)
        if not operators:
            operators = ["Настройки отсутствуют"]
        operators.sort()
        self.operator_combo.configure(values=operators)
        if operators:
            self.operator_combo.set(operators[0])
        self.on_operator_change()
    
    def on_operator_change(self, choice=None):
        operator = self.operator_combo.get()
        
        if operator == "Настройки отсутствуют" or not operator:
            self.load_btn.configure(state="normal")
            self.camera_combo.configure(values=[])
            self.camera_combo.set("")
            self.settings_combo.configure(values=[])
            self.settings_combo.set("")
            return
        
        # Загружаем камеры
        cameras = []
        operator_path = os.path.join(Config.CAMERAMAN_PATH, operator)
        if os.path.exists(operator_path):
            for item in os.listdir(operator_path):
                item_path = os.path.join(operator_path, item)
                if os.path.isdir(item_path):
                    cameras.append(item)
        
        if not cameras:
            cameras = ["Настройки отсутствуют"]
        cameras.sort()
        self.camera_combo.configure(values=cameras)
        if cameras:
            self.camera_combo.set(cameras[0])
        
        self.on_camera_change()
    
    def on_camera_change(self, choice=None):
        operator = self.operator_combo.get()
        camera = self.camera_combo.get()
        
        if operator == "Настройки отсутствуют" or camera == "Настройки отсутствуют":
            self.load_btn.configure(state="normal")
            self.settings_combo.configure(values=[])
            self.settings_combo.set("")
            return
        
        # Загружаем настройки
        settings_list = []
        camera_path = os.path.join(Config.CAMERAMAN_PATH, operator, camera)
        if os.path.exists(camera_path):
            for item in os.listdir(camera_path):
                item_path = os.path.join(camera_path, item)
                if os.path.isdir(item_path):
                    settings_list.append(item)
        
        if not settings_list:
            settings_list = ["Настройки отсутствуют"]
        settings_list.sort(reverse=True)
        self.settings_combo.configure(values=settings_list)
        if settings_list:
            self.settings_combo.set(settings_list[0])
        
        self.load_btn.configure(state="normal")
    
    def load_settings(self):
        operator = self.operator_combo.get()
        
        if operator == "Настройки отсутствуют":
            messagebox.showerror("Ошибка", "Указанные настройки не найдены на диске C:")
            return
        
        camera = self.camera_combo.get() if self.camera_combo else ""
        settings_name = self.settings_combo.get() if self.settings_combo else ""
        
        if not camera or not settings_name or camera == "Настройки отсутствуют" or settings_name == "Настройки отсутствуют":
            messagebox.showerror("Ошибка", "Указанные настройки не найдены на диске C:")
            return
        
        drive, error = check_usb_drive()
        if error:
            retry = messagebox.askretrycancel("Ошибка", error)
            if retry:
                self.load_settings()
            return
        
        source_path = os.path.join(Config.CAMERAMAN_PATH, operator, camera, settings_name)
        
        if not os.path.exists(source_path):
            messagebox.showerror("Ошибка", f"Указанные настройки не найдены на диске C:\n{source_path}")
            return
        
        required_size = get_directory_size(source_path)
        if not check_free_space(drive, required_size):
            messagebox.showerror("Ошибка", "Недостаточно свободного места на флешке!")
            return
        
        dest_path = drive
        
        def copy_thread():
            self.after(0, lambda: self.load_btn.configure(state="disabled", text="Копирование..."))
            try:
                # Копирование с исключением LASTCLIP.TXT и перезаписью
                safe_copytree(source_path, dest_path)
                
                # Диалог и закрытие окна — только из главного потока Tk
                self.after(0, lambda: messagebox.showinfo("Успех", "Настройки успешно загружены на флешку"))
                self.after(0, self.destroy)
            except Exception as e:
                error_text = str(e)
                self.after(0, lambda: messagebox.showerror("Ошибка", f"Ошибка при копировании: {error_text}"))
            finally:
                self.after(0, lambda: self.load_btn.configure(state="normal", text="Загрузить"))
        
        threading.Thread(target=copy_thread, daemon=True).start()


# ============================================================
# ОКНО ИНСТРУКЦИЙ
# ============================================================

class InstructionsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Инструкции")
        self.geometry("400x250")
        self.resizable(False, False)
        self.grab_set()
        self.center_window()
        
        self.create_widgets()
        self.load_instructions()
        
        self.bind('<Escape>', lambda e: self.destroy())
    
    def center_window(self):
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (self.winfo_width() // 2)
        y = (self.winfo_screenheight() // 2) - (self.winfo_height() // 2)
        self.geometry(f"{self.winfo_width()}x{self.winfo_height()}+{x}+{y}")
    
    def create_widgets(self):
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(padx=30, pady=25, fill="both", expand=True)
        
        self.instruction_label = ctk.CTkLabel(main_frame, text="Выберите инструкцию:", 
                                              font=ctk.CTkFont(size=12, weight="bold"))
        self.instruction_label.pack(anchor="center", pady=(0, 10))
        
        self.instruction_combo = ctk.CTkComboBox(main_frame, values=[], width=250, height=35,
                                                  state="readonly")
        self.instruction_combo.pack(anchor="center", pady=(0, 25))
        
        self.open_btn = ctk.CTkButton(main_frame, text="Открыть", width=120, height=35,
                                     font=ctk.CTkFont(size=12, weight="bold"), command=self.open_instruction)
        self.open_btn.pack(pady=(5, 10))
        
        self.back_btn = ctk.CTkButton(main_frame, text="Закрыть (ESC)", width=120, height=35,
                                     font=ctk.CTkFont(size=12), command=self.destroy, fg_color="gray")
        self.back_btn.pack(pady=(5, 0))
    
    def load_instructions(self):
        items = []
        if os.path.exists(Config.INSTRUCTIONS_PATH):
            for folder in os.listdir(Config.INSTRUCTIONS_PATH):
                folder_path = os.path.join(Config.INSTRUCTIONS_PATH, folder)
                if os.path.isdir(folder_path):
                    for file in os.listdir(folder_path):
                        file_path = os.path.join(folder_path, file)
                        if os.path.isfile(file_path):
                            name, ext = os.path.splitext(file)
                            if ext.lower() in Config.ALLOWED_INSTRUCTION_EXTENSIONS:
                                items.append(f"{folder.upper()}/{name}")
        
        if not items:
            items = ["Инструкции отсутствуют"]
        items.sort()
        self.instruction_combo.configure(values=items)
        if items:
            self.instruction_combo.set(items[0])
    
    def open_instruction(self):
        selection = self.instruction_combo.get()
        if selection == "Инструкции отсутствуют" or not selection:
            messagebox.showwarning("Внимание", "Выберите инструкцию из списка")
            return
        
        try:
            folder_upper, file_name = selection.split('/')
            found_folder = None
            for folder in os.listdir(Config.INSTRUCTIONS_PATH):
                if folder.upper() == folder_upper:
                    found_folder = folder
                    break
            
            if not found_folder:
                messagebox.showerror("Ошибка", "Файл инструкции не найден")
                return
            
            folder_path = os.path.join(Config.INSTRUCTIONS_PATH, found_folder)
            found_file = None
            for file in os.listdir(folder_path):
                name, ext = os.path.splitext(file)
                if name == file_name:
                    found_file = file
                    break
            
            if not found_file:
                messagebox.showerror("Ошибка", "Файл инструкции не найден")
                return
            
            file_path = os.path.join(folder_path, found_file)
            open_path(file_path)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть файл: {e}")


# ============================================================
# ТОЧКА ВХОДА
# ============================================================

if __name__ == "__main__":
    try:
        app = MainWindow()
        app.mainloop()
    except Exception as e:
        print(f"Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        input("\nНажмите Enter для выхода...")