# -*- coding: utf-8 -*-
"""Кастомные виджеты агента.

Ключевое решение по UX: вместо неочевидного пункта «+ Добавить новое» —
обычное поле с **кликабельными подсказками** под ним. Пользователь либо
выбирает готовое одним нажатием, либо сразу печатает.
"""

from __future__ import annotations

import customtkinter as ctk

from agent import theme
from mastersetting.filters import sanitize_name, validate_char

# Оставлено для совместимости со старым кодом
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
    """Поле ввода с кликабельными подсказками.

    Заменяет прежний «+ Добавить новое»: подсказки видны сразу и
    заполняются одним нажатием, а поле всегда доступно для печати.
    """

    MAX_CHIPS = 6

    def __init__(self, master, values=None, command=None, width=250,
                 max_length=30, placeholder="", **kwargs):
        super().__init__(master, fg_color="transparent")
        self.original_values = list(values) if values else []
        self.command = command
        self.width = width
        self.max_length = max_length

        self.entry = LimitedEntry(
            self, max_length=max_length, width=width,
            placeholder_text=placeholder)
        self.entry.pack(fill="x")
        self.entry.bind("<Return>", lambda e: self._emit())
        self.entry.bind("<KeyRelease>", lambda e: self._filter_chips())

        self.chips = ctk.CTkFrame(self, fg_color="transparent")
        self.chips.pack(fill="x", pady=(4, 0))
        self._render_chips()

    # ------------------------------------------------------------------
    def _render_chips(self):
        for w in self.chips.winfo_children():
            w.destroy()
        for value in self.original_values[: self.MAX_CHIPS]:
            ctk.CTkButton(
                self.chips, text=value, command=lambda v=value: self._pick(v),
                fg_color=theme.PANEL2, hover_color=theme.LINE,
                text_color=theme.TEXT, corner_radius=999, height=24,
                font=ctk.CTkFont(size=theme.SIZES["tiny"]),
            ).pack(side="left", padx=(0, 6), pady=2)

    def _filter_chips(self, event=None):
        """Подсказки подстраиваются под набранный текст."""
        typed = self.entry.get().strip().lower()
        if not typed:
            wanted = self.original_values[: self.MAX_CHIPS]
        else:
            wanted = [v for v in self.original_values
                      if typed in v.lower() and v.lower() != typed][: self.MAX_CHIPS]
        current = [w.cget("text") for w in self.chips.winfo_children()]
        if current == wanted:
            return
        for w in self.chips.winfo_children():
            w.destroy()
        for value in wanted:
            ctk.CTkButton(
                self.chips, text=value, command=lambda v=value: self._pick(v),
                fg_color=theme.PANEL2, hover_color=theme.LINE,
                text_color=theme.TEXT, corner_radius=999, height=24,
                font=ctk.CTkFont(size=theme.SIZES["tiny"]),
            ).pack(side="left", padx=(0, 6), pady=2)

    def _pick(self, value: str):
        self.entry.delete(0, "end")
        self.entry.insert(0, value)
        self._emit()

    def _emit(self):
        value = self.get()
        if value and self.command:
            self.command(value)

    # ------------------------------------------------------------------
    def get(self):
        return sanitize_name(self.entry.get(), self.max_length)

    def set(self, value):
        self.entry.delete(0, "end")
        if value:
            self.entry.insert(0, value)

    def configure_values(self, values):
        self.original_values = list(values)
        self._render_chips()
