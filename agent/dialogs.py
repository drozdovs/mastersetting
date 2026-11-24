# -*- coding: utf-8 -*-
"""Свои тёмные диалоги вместо системных.

Системные всплывающие окна (``tkinter.messagebox``) всегда светлые и в тёмном
приложении выглядят как чужая программа. Здесь — такие же простые окна, но в
теме приложения.

Правило текстов: главная строка — простыми словами, технические подробности —
отдельной мелкой строкой, чтобы не пугать оператора.
"""

from __future__ import annotations

import customtkinter as ctk

from agent import theme


class _Dialog(ctk.CTkToplevel):
    """Базовое тёмное модальное окно."""

    def __init__(self, parent, *, title: str, message: str, detail: str = "",
                 color: str = theme.TEXT, yes_text: str = "Понятно",
                 no_text: str | None = None, danger: bool = False):
        super().__init__(parent)
        self.result = False
        self.title("")
        self.configure(fg_color=theme.BG)
        self.resizable(False, False)
        self.transient(parent)

        wrap = 340
        body = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=12)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        if title:
            ctk.CTkLabel(body, text=title, text_color=theme.TEXT,
                         font=ctk.CTkFont(size=theme.SIZES["h3"], weight="bold"),
                         wraplength=wrap, justify="left").pack(
                anchor="w", padx=16, pady=(16, 4))
        ctk.CTkLabel(body, text=message, text_color=color,
                     font=ctk.CTkFont(size=theme.SIZES["body"]),
                     wraplength=wrap, justify="left").pack(
            anchor="w", padx=16, pady=(4 if title else 16, 4))

        if detail:
            ctk.CTkLabel(body, text=detail, text_color=theme.MUTED,
                         font=ctk.CTkFont(size=theme.SIZES["tiny"]),
                         wraplength=wrap, justify="left").pack(
                anchor="w", padx=16, pady=(0, 8))

        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(8, 16))
        if no_text is not None:
            ctk.CTkButton(row, text=no_text, command=self._no,
                          fg_color=theme.PANEL2, hover_color=theme.LINE,
                          text_color=theme.TEXT, corner_radius=8,
                          font=ctk.CTkFont(size=theme.SIZES["body"])).pack(
                side="right")
        ctk.CTkButton(
            row, text=yes_text, command=self._yes,
            fg_color="#7f1d1d" if danger else theme.ACCENT,
            hover_color="#991b1b" if danger else "#c9c9cc",
            text_color=theme.TEXT if danger else theme.BG, corner_radius=8,
            font=ctk.CTkFont(size=theme.SIZES["body"])).pack(
            side="right", padx=(0, 8))

        self.bind("<Return>", lambda e: self._yes())
        self.bind("<Escape>", lambda e: self._no())

        self.after(10, lambda: self._place(parent))
        try:
            self.grab_set()
        except Exception:
            pass

    def _place(self, parent):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        px = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        py = parent.winfo_rooty() + max(40, (parent.winfo_height() - h) // 3)
        self.geometry(f"+{max(0, px)}+{max(0, py)}")
        self.focus_force()

    def _yes(self):
        self.result = True
        self.destroy()

    def _no(self):
        self.result = False
        self.destroy()


def _show(parent, title, message, detail, color, yes_text, danger=False):
    dlg = _Dialog(parent, title=title, message=message, detail=detail,
                  color=color, yes_text=yes_text, danger=danger)
    try:
        parent.wait_window(dlg)
    except Exception:
        pass
    return dlg.result


def info(parent, title, message, detail=""):
    return _show(parent, title, message, detail, theme.TEXT, "Понятно")


def error(parent, title, message, detail=""):
    return _show(parent, title, message, detail, theme.DANGER, "Понятно")


def warn(parent, title, message, detail=""):
    return _show(parent, title, message, detail, theme.WARN, "Понятно")


def confirm(parent, title, message, detail="", *, yes_text="Да", no_text="Отмена",
            danger=False):
    dlg = _Dialog(parent, title=title, message=message, detail=detail,
                  color=theme.TEXT, yes_text=yes_text, no_text=no_text,
                  danger=danger)
    try:
        parent.wait_window(dlg)
    except Exception:
        pass
    return dlg.result


def pick_folder(parent, title="Выберите папку", message="", initialdir=None):
    """Выбрать папку вручную (ТЗ: ручное указание карты/папки).

    Возвращает путь или ``""``. Системный диалог вызывается поверх окна;
    на macOS и Windows это родной выбор папки.
    """
    from tkinter import filedialog
    return filedialog.askdirectory(
        parent=parent, title=title, initialdir=initialdir or None,
        mustexist=True)
