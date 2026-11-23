# -*- coding: utf-8 -*-
"""Кастомные виджеты агента."""

from __future__ import annotations

import customtkinter as ctk

from mastersetting.filters import sanitize_name, validate_char

ADD_NEW_LABEL = "+ Добавить новое"


class LimitedEntry(ctk.CTkEntry):
    """Поле ввода: только буквы/цифры, максимум N символов."""

    def __init__(self, master, max_length: int = 30, **kwargs):
        super().__init__(master, **kwargs)
        self.max_length = max_length
        self.configure(height=35)
        self.bind("<KeyRelease>", self._on_key_release)
        self.bind("<Key>", self._validate_key)

    def _validate_key(self, event):
        if event.keysym in ("BackSpace", "Delete", "Left", "Right", "Home", "End"):
            return None
        if event.char and not validate_char(event.char):
            return "break"
        return None

    def _on_key_release(self, event=None):
        current = self.get()
        cleaned = "".join(c for c in current if validate_char(c))
        if cleaned != current:
            self.delete(0, "end")
            self.insert(0, cleaned)
            current = cleaned
        if len(current) > self.max_length:
            self.delete(self.max_length, "end")


class EditableComboBox(ctk.CTkFrame):
    """Комбобокс с пунктом «+ Добавить новое» и inline-полем ввода."""

    def __init__(self, master, values=None, command=None, width=250,
                 max_length=30, **kwargs):
        super().__init__(master, fg_color="transparent")
        self.original_values = list(values) if values else []
        self.command = command
        self.width = width
        self.max_length = max_length
        self.entry_widget = None
        self.combo_widget = None
        self.create_combo()

    # ------------------------------------------------------------------
    def _values_with_add(self):
        values = list(self.original_values)
        if ADD_NEW_LABEL not in values:
            values.append(ADD_NEW_LABEL)
        return values

    def create_combo(self):
        if self.combo_widget and self.combo_widget.winfo_exists():
            self.combo_widget.destroy()
        self.entry_widget = None

        self.combo_widget = ctk.CTkComboBox(
            self, values=self._values_with_add(), width=self.width,
            height=35, state="readonly", command=self._on_select,
        )
        self.combo_widget.pack(fill="x")
        if self.original_values:
            self.combo_widget.set(self.original_values[0])
        else:
            self.combo_widget.set(ADD_NEW_LABEL)

    def create_entry(self):
        if self.combo_widget and self.combo_widget.winfo_exists():
            self.combo_widget.destroy()
        self.entry_widget = LimitedEntry(
            self, max_length=self.max_length,
            placeholder_text=f"Новое значение (макс. {self.max_length} симв.)",
            width=self.width,
        )
        self.entry_widget.pack(fill="x")
        self.entry_widget.bind("<Return>", self._on_entry_confirm)
        self.entry_widget.bind("<Escape>", self._on_entry_cancel)
        self.entry_widget.focus()

    def _on_select(self, choice):
        if choice == ADD_NEW_LABEL:
            self.create_entry()
        elif self.command:
            self.command(choice)

    def _on_entry_confirm(self, event=None):
        value = sanitize_name(self.entry_widget.get(), self.max_length)
        if value:
            if value not in self.original_values:
                self.original_values.append(value)
            self.original_values.sort()
            self.create_combo()
            self.combo_widget.set(value)
            if self.command:
                self.command(value)
        else:
            self.create_combo()

    def _on_entry_cancel(self, event=None):
        self.create_combo()

    # ------------------------------------------------------------------
    def get(self):
        if self.entry_widget and self.entry_widget.winfo_exists():
            return sanitize_name(self.entry_widget.get(), self.max_length)
        if self.combo_widget and self.combo_widget.winfo_exists():
            value = self.combo_widget.get()
            return value if value != ADD_NEW_LABEL else ""
        return ""

    def set(self, value):
        if self.combo_widget and self.combo_widget.winfo_exists() and value in self.original_values:
            self.combo_widget.set(value)

    def configure_values(self, values):
        self.original_values = list(values)
        self.create_combo()
