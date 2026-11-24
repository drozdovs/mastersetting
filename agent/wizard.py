# -*- coding: utf-8 -*-
"""Пошаговый мастер: одна задача — один экран, простыми словами.

Идея UX:
  * пользователь никогда не видит пустой экран без подсказки;
  * на каждом шаге видно, что делать, и есть кнопка «Дальше»;
  * язык — максимально простой, без технических терминов;
  * ошибки объясняются человеческими фразами с понятным действием.

Мастер умеет две задачи:
  1. «Сохранить настройки с карты» (карта → библиотека);
  2. «Записать настройки на карту» (библиотека → карта).

GUI не содержит бизнес-логики — только шаги и вызовы ``AppController``.
Тяжёлые операции идут в фоне, интерфейс не «замерзает».
"""

from __future__ import annotations

import os
import threading

import customtkinter as ctk

from agent import dialogs, theme
from agent.controllers import AppController
from agent.widgets import EditableComboBox
from mastersetting.platform import safe_eject

# Шаги. Техническое слово «носитель» заменено на понятное «карта».
STEPS = ("Карта", "Оператор", "Название", "Готово")
STEPS_WRITE = ("Карта", "Что записать", "Изменения", "Готово")


class Wizard(ctk.CTkToplevel):
    """Базовое окно мастера: шапка с шагами + область содержимого + низ."""

    def __init__(self, parent, title: str, steps: tuple[str, ...],
                 size=(560, 620)):
        super().__init__(parent)
        self.app = parent
        self.ctrl: AppController = parent.ctrl
        self.steps = steps
        self.step_index = 0

        self.title(title)
        self.geometry(f"{size[0]}x{size[1]}")
        self.minsize(size[0], size[1])
        self.configure(fg_color=theme.BG)
        self.bind("<Escape>", lambda e: self._close())
        # Работа с клавиатуры (ТЗ): Alt+→/Alt+← листают шаги, Ctrl+Enter — главное
        # действие шага (найти/дальше/сохранить/записать), Enter по умолчанию тоже.
        self.bind("<Alt-Right>", lambda e: self._go_next())
        self.bind("<Alt-Left>", lambda e: self._go_back())
        self.bind("<Control-Return>", lambda e: self._go_next())
        self.bind("<Return>", lambda e: self._go_next())

        self.header = ctk.CTkFrame(self, fg_color="transparent")
        self.header.pack(fill="x", padx=22, pady=(18, 6))

        self.body = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=12)
        self.body.pack(fill="both", expand=True, padx=22, pady=(4, 12))

        self.footer = ctk.CTkFrame(self, fg_color="transparent")
        self.footer.pack(fill="x", padx=22, pady=(0, 18))

        self.back_btn = self._btn(self.footer, "Назад", self._go_back, ghost=True)
        self.next_btn = self._btn(self.footer, "Дальше", self._go_next)
        self.next_btn.pack(side="right")
        # Отмена доступна во время долгой операции (ТЗ: определённое поведение —
        # остановка с откатом уже записанных файлов, а не «тихое» убийство окна).
        self.cancel_btn = self._btn(self.footer, "Отмена", self._cancel, ghost=True)
        self._cancel_flag = False

        self.back_btn.pack(side="left")

        self.after(10, lambda: self._center(parent))

    def _cancel(self):
        """Попросить остановить текущую операцию: файлы откатываются (ядро)."""
        if not getattr(self, "_busy", False):
            self._close()
            return
        self._cancel_flag = True
        dialogs.info(self, "Останавливаю…",
                     "Прерываю операцию. Уже записанные файлы будут возвращены "
                     "в прежнее состояние.")

    # ------------------------------------------------------------------
    def _center(self, parent):
        self.update_idletasks()
        w = self.winfo_width()
        x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        y = parent.winfo_rooty() + 40
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _btn(self, master, text, command, ghost=False, danger=False):
        if danger:
            fg, hover, tcol = "#7f1d1d", "#991b1b", theme.TEXT
        elif ghost:
            fg, hover, tcol = theme.PANEL2, theme.LINE, theme.TEXT
        else:
            fg, hover, tcol = theme.ACCENT, "#c9c9cc", theme.BG
        return ctk.CTkButton(master, text=text, command=command, fg_color=fg,
                             hover_color=hover, text_color=tcol, corner_radius=8,
                             height=36, width=120,
                             font=ctk.CTkFont(size=theme.SIZES["body"]))

    # ------------------------------------------------------------------
    def label(self, master, text, *, size="body", color=None, bold=False, wrap=470):
        return ctk.CTkLabel(
            master, text=text, text_color=color or theme.TEXT,
            font=ctk.CTkFont(size=theme.SIZES[size],
                             weight="bold" if bold else "normal"),
            wraplength=wrap, justify="left")

    def render_header(self):
        for w in self.header.winfo_children():
            w.destroy()
        for i, name in enumerate(self.steps):
            done = i < self.step_index
            active = i == self.step_index
            col = theme.OK if done else (theme.TEXT if active else theme.MUTED)
            mark = "✓" if done else str(i + 1)
            chip = ctk.CTkFrame(self.header, fg_color="transparent")
            chip.pack(side="left", padx=(0, 14))
            ctk.CTkLabel(chip, text=f"{mark} {name}", text_color=col,
                         font=ctk.CTkFont(size=theme.SIZES["small"],
                                          weight="bold" if active else "normal")
                         ).pack(side="left")

    def render(self):
        """Перерисовать текущий шаг. Переопределяется в наследниках."""
        raise NotImplementedError

    def go_to(self, index: int):
        self.step_index = max(0, min(index, len(self.steps) - 1))
        self.render_header()
        for w in self.body.winfo_children():
            w.destroy()
        self.render()
        self.back_btn.configure(state="normal" if self.step_index > 0 else "disabled")

    def _go_back(self):
        self.go_to(self.step_index - 1)

    def _pick_manual(self):
        """Ручной выбор папки-карты (ТЗ): кардридер может не определиться съёмным."""
        path = dialogs.pick_folder(
            self, title="Выберите карту (папку с настройками)")
        if not path:
            return
        ok, msg = self.ctrl.check_card_folder(path)
        if not ok:
            dialogs.error(self, "Так нельзя", msg)
            return
        self.card = path
        try:
            self.card_choice.configure(values=[path])
            self.card_choice.set(path)
        except Exception:
            pass
        try:
            self.status_label.configure(text=msg, text_color=theme.OK)
        except Exception:
            pass

    def _go_next(self):
        self.next()

    def next(self):
        """Логика перехода. Переопределяется в наследниках."""
        self.go_to(self.step_index + 1)

    # ------------------------------------------------------------------
    def run_bg(self, work, on_done, on_error):
        """Выполнить работу в фоне, показать результат в главном потоке."""
        def runner():
            try:
                result = work()
            except Exception as e:  # noqa: BLE001
                # ВАЖНО: ``e`` привязываем через default-аргумент, иначе Python
                # удаляет имя при выходе из except и лямбда упадёт с NameError.
                try:
                    self.after(0, lambda err=e: on_error(err))
                except RuntimeError:
                    pass
                return
            try:
                self.after(0, lambda res=result: on_done(res))
            except RuntimeError:
                pass  # окно закрыто во время работы — показывать некому
        threading.Thread(target=runner, daemon=True).start()

    def busy(self, on: bool, text: str = "Работаем…"):
        self._busy = on
        self._cancel_flag = False
        self.next_btn.configure(state="disabled" if on else "normal",
                                text=text if on else self.next_text())
        self.back_btn.configure(state="disabled" if on else "normal")
        try:
            if on:
                self.cancel_btn.pack(side="left", padx=(8, 0))
            else:
                self.cancel_btn.pack_forget()
        except Exception:
            pass

    def _cancelled(self) -> bool:
        return getattr(self, "_cancel_flag", False)

    def _close(self):
        """Закрытие окна. Во время операции — не рвём её (ТЗ: определённое
        безопасное поведение): просим дождаться или явно подтвердить отмену."""
        if getattr(self, "_busy", False):
            ok = dialogs.confirm(
                self, "Операция ещё идёт",
                "Не закрывайте окно, пока идёт запись/сохранение: это может "
                "оставить карту в промежуточном состоянии.\n\n"
                "Закрыть всё равно? Незавершённые файлы будут откатаны, "
                "но лучше дождаться окончания.",
                yes_text="Всё равно закрыть", danger=True)
            if not ok:
                return
        self.destroy()

    def next_text(self) -> str:
        return "Дальше"


# ===========================================================================
# Сохранить настройки с карты
# ===========================================================================

class SaveWizard(Wizard):
    """Карта → библиотека, по шагам и простыми словами."""

    def __init__(self, parent):
        self.card = ""
        self.operator = ""
        self.camera = ""
        self.preset = ""
        self.plan = None
        super().__init__(parent, "Сохранить с карты", STEPS)
        self.go_to(0)

    def next_text(self) -> str:
        return {0: "Найти настройки", 1: "Дальше", 2: "Сохранить",
                3: "Закрыть"}.get(self.step_index, "Дальше")

    # --- Роутер шагов --------------------------------------------------
    def render(self):
        if self.step_index == 0:
            self._render_card()
        elif self.step_index == 1:
            self._render_who()
        elif self.step_index == 2:
            self._render_what()
        else:
            self._render_final()

    # --- Шаг 1: карта --------------------------------------------------
    def _render_card(self):
        b = self.body
        self.label(b, "Шаг 1. Вставьте карту памяти", size="h2", bold=True).pack(
            anchor="w", padx=18, pady=(18, 4))
        self.label(b, "Вставьте карту из камеры в кардридер. Мы посмотрим, "
                      "что на ней есть.", size="small", color=theme.MUTED).pack(
            anchor="w", padx=18, pady=(0, 14))

        status = ctk.CTkFrame(b, fg_color=theme.PANEL2, corner_radius=10)
        status.pack(fill="x", padx=18, pady=(0, 12))
        self.status_label = self.label(status, "", size="body")
        self.status_label.pack(anchor="w", padx=14, pady=14)

        # Выбор носителя: доступен, если подключено несколько (ТЗ).
        self.card_choice = ctk.CTkComboBox(b, values=["—"], state="readonly",
                                           command=self._pick_card)
        self.card_choice.pack(fill="x", padx=18, pady=(0, 10))

        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(10, 0))
        ctk.CTkButton(row, text="Искать карты", command=self._check_card,
                      fg_color=theme.PANEL2, hover_color=theme.LINE,
                      text_color=theme.TEXT, corner_radius=8, height=32).pack(
            side="left")
        ctk.CTkButton(row, text="Выбрать папку вручную", command=self._pick_manual,
                      fg_color=theme.PANEL2, hover_color=theme.LINE,
                      text_color=theme.TEXT, corner_radius=8, height=32).pack(
            side="left", padx=(8, 0))
        self._check_card()

    def _pick_card(self, value):
        if value and value != "—":
            self.card = value
            self.status_label.configure(
                text=f"Выбрана карта: {os.path.basename(self.card)}",
                text_color=theme.OK)

    def _check_card(self):
        cards = self.ctrl.list_cards()
        if len(cards) == 1:
            self.card = cards[0]
            self.card_choice.configure(values=["—"])
            self.card_choice.set("—")
            self.status_label.configure(
                text=f"Карта найдена: {os.path.basename(self.card)}",
                text_color=theme.OK)
        elif len(cards) == 0:
            self.card = ""
            self.card_choice.configure(values=["—"])
            self.card_choice.set("—")
            self.status_label.configure(
                text="Карта не найдена.\nВставьте карту в кардридер и нажмите "
                     "«Искать карты».", text_color=theme.WARN)
        else:
            # Несколько носителей — оператор выбирает сам, а не выдёргивает лишние.
            self.card = ""
            self.card_choice.configure(values=cards)
            self.card_choice.set(cards[0])
            self._pick_card(cards[0])
            self.status_label.configure(
                text="Подключено несколько носителей.\n"
                     "Выберите нужную карту в списке ниже.",
                text_color=theme.WARN)

    # --- Шаг 2: оператор и модель --------------------------------------
    def _render_who(self):
        b = self.body
        self.label(b, "Шаг 2. Чья это камера и какая модель", size="h2",
                   bold=True).pack(anchor="w", padx=18, pady=(18, 4))
        self.label(b, "Начните печатать — появятся подсказки. Если имени нет, "
                      "просто введите своё.", size="small",
                   color=theme.MUTED).pack(anchor="w", padx=18, pady=(0, 14))

        self.label(b, "Оператор", size="small", color=theme.MUTED).pack(
            anchor="w", padx=18)
        self.operator_box = EditableComboBox(
            b, values=self.ctrl.list_operators(),
            max_length=self.ctrl.config.max_name_length,
            placeholder="например, Иван")
        self.operator_box.pack(fill="x", padx=18, pady=(4, 14))
        self.operator_box.set(self.ctrl.current_operator())

        self.label(b, "Модель камеры", size="small", color=theme.MUTED).pack(
            anchor="w", padx=18)
        self.camera_box = EditableComboBox(
            b, values=self.ctrl.list_cameras(),
            max_length=self.ctrl.config.max_name_length,
            placeholder="например, Sony FX3")
        self.camera_box.pack(fill="x", padx=18, pady=(4, 8))

    # --- Шаг 3: просмотр и сохранение ----------------------------------
    def _render_what(self):
        b = self.body
        self.label(b, "Шаг 3. Что сохраняем", size="h2", bold=True).pack(
            anchor="w", padx=18, pady=(18, 4))
        self.label(b, "С карты будут сохранены только настройки камеры. "
                      "Видео и фотографии не копируются.",
                   size="small", color=theme.MUTED).pack(
            anchor="w", padx=18, pady=(0, 12))

        self.label(b, "Название набора", size="small", color=theme.MUTED).pack(
            anchor="w", padx=18)
        self.preset_box = EditableComboBox(
            b, values=self.ctrl.list_presets(self.operator, self.camera),
            max_length=self.ctrl.config.max_name_length,
            placeholder="например, Основные")
        self.preset_box.pack(fill="x", padx=18, pady=(4, 10))

        # ТЗ: показать источник (карта) и цель (библиотека) до сохранения.
        self.label(
            b,
            f"Откуда: карта {os.path.basename((self.card or '').rstrip(os.sep)) or '—'}\n"
            "Куда: личная библиотека оператора (новая неизменяемая версия)",
            size="tiny", color=theme.MUTED, wrap=520).pack(
            anchor="w", padx=18, pady=(0, 8))

        self.found_label = self.label(b, "Смотрю, что есть на карте…",
                                      size="small", color=theme.MUTED)
        self.found_label.pack(anchor="w", padx=18, pady=(0, 8))

        self.files_box = ctk.CTkTextbox(b, height=120, fg_color=theme.PANEL2,
                                        text_color=theme.TEXT, border_width=0,
                                        corner_radius=8)
        self.files_box.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        self.files_box.configure(state="disabled")

    def _load_plan(self):
        try:
            self.plan = self.ctrl.plan_save(self.camera, self.card)
        except Exception as e:  # noqa: BLE001
            self.found_label.configure(text=f"Не удалось посмотреть карту: {e}",
                                       text_color=theme.DANGER)
            return
        n = self.plan.file_count
        if n == 0:
            self.found_label.configure(
                text="На карте не найдено файлов настроек.",
                text_color=theme.WARN)
        else:
            model = getattr(self.plan, "detected_model", "")
            extra = f"  ·  модель в файле: {model}" if model else ""
            self.found_label.configure(
                text=f"Найдено {n} файл(ов) настроек.{extra}", text_color=theme.OK)
        self.files_box.configure(state="normal")
        self.files_box.delete("1.0", "end")
        self.files_box.insert("1.0", "\n".join(self.plan.files.keys())
                              or "— (ничего)")
        self.files_box.configure(state="disabled")

    # --- Навигация -----------------------------------------------------
    def next(self):
        if self.step_index == 0:
            if not self.card:
                dialogs.warn(self, "Сначала карта",
                             "Вставьте карту памяти и нажмите «Проверить карту».")
                return
            self.go_to(1)

        elif self.step_index == 1:
            self.operator = self.operator_box.get().strip()
            self.camera = self.camera_box.get().strip()
            if not self.operator:
                dialogs.warn(self, "Нужен оператор",
                             "Введите имя оператора — так наборы не перепутаются.")
                return
            if not self.camera:
                dialogs.warn(self, "Нужна модель",
                             "Введите модель камеры, например «Sony FX3».")
                return
            self.go_to(2)
            self._load_plan()

        elif self.step_index == 2:
            self.preset = self.preset_box.get().strip()
            if not self.preset:
                dialogs.warn(self, "Нужно название",
                             "Придумайте название набора, например «Основные».")
                return
            if not self.plan or self.plan.file_count == 0:
                dialogs.warn(self, "Сохранять нечего",
                             "На карте не найдено файлов настроек.\n"
                             "Проверьте, что это карта из камеры, с которой "
                             "сохраняли настройки.")
                return
            self._save()

        else:
            self._close()

    def _save(self):
        self.busy(True, "Сохраняю…")

        def work():
            return self.ctrl.save_from_card(
                self.operator, self.camera, self.preset, self.card, plan=self.plan,
                should_cancel=self._cancelled)

        def done(rep):
            self.busy(False)
            if rep.ok:
                self.ctrl.remember_operator(self.operator)
                self.last_report = rep
                self.go_to(3)
                self.app.refresh()
            else:
                dialogs.error(self, "Не получилось сохранить", rep.message)

        def fail(e):
            self.busy(False)
            dialogs.error(self, "Не получилось сохранить", _human_error(e))

        self.run_bg(work, done, fail)

    def _render_final(self):
        b = self.body
        self.label(b, "Готово! Настройки сохранены", size="h2",
                   bold=True, color=theme.OK).pack(anchor="w", padx=18,
                                                   pady=(18, 6))
        self.label(b, f"Оператор: {self.operator}\nМодель: {self.camera}\n"
                      f"Название: {self.preset}", size="small").pack(
            anchor="w", padx=18, pady=(0, 8))
        self.label(b, "Можно сразу сохранить ещё один набор или записать "
                      "этот на карту.", size="small",
                   color=theme.MUTED).pack(anchor="w", padx=18)
        self._btn(b, "Безопасно извлечь карту", self._eject,
                  ghost=True).pack(anchor="w", padx=18, pady=(12, 0))

    def _eject(self):
        if not self.card:
            return
        ok, msg = safe_eject(self.card)
        if ok:
            dialogs.info(self, "Карту можно вынуть",
                         "Система готова к извлечению. Выньте карту из кардридера.")
        else:
            dialogs.warn(self, "Извлечь не удалось",
                         msg or "Извлеките карту вручную только после операции.")


class WriteWizard(Wizard):
    """Библиотека → карта: выбрать набор, посмотреть изменения, записать."""

    def __init__(self, parent):
        self.card = ""
        self.operator = ""
        self.camera = ""
        self.preset = ""
        self.version = None
        self.preview = None
        self.use_pair = False       # записываем именованную пару FX3/FX3A
        self.pair = None
        super().__init__(parent, "Записать на карту", STEPS_WRITE)
        self.go_to(0)

    def next_text(self) -> str:
        # 0 — проверить карту, 1 — перейти к изменениям, 2 — записать, 3 — закрыть
        return {0: "Проверить карту", 1: "Посмотреть, что изменится",
                2: "Записать", 3: "Закрыть"}.get(
            self.step_index, "Дальше")

    def render(self):
        if self.step_index == 0:
            self._render_card()
        elif self.step_index == 1:
            self._render_choice()
        elif self.step_index == 2:
            self._render_changes()
        else:
            self._render_final()

    # --- Шаг 1: карта --------------------------------------------------
    def _render_card(self):
        b = self.body
        self.label(b, "Шаг 1. Вставьте карту, на которую пишем", size="h2",
                   bold=True).pack(anchor="w", padx=18, pady=(18, 4))
        self.label(b, "На карте заменятся только настройки камеры. "
                      "Видео и фотографии останутся как есть.",
                   size="small", color=theme.MUTED).pack(
            anchor="w", padx=18, pady=(0, 14))

        status = ctk.CTkFrame(b, fg_color=theme.PANEL2, corner_radius=10)
        status.pack(fill="x", padx=18, pady=(0, 12))
        self.status_label = self.label(status, "", size="body")
        self.status_label.pack(anchor="w", padx=14, pady=14)

        self.card_choice = ctk.CTkComboBox(b, values=["—"], state="readonly",
                                           command=self._pick_card)
        self.card_choice.pack(fill="x", padx=18, pady=(0, 10))

        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(10, 0))
        ctk.CTkButton(row, text="Искать карты", command=self._check_card,
                      fg_color=theme.PANEL2, hover_color=theme.LINE,
                      text_color=theme.TEXT, corner_radius=8, height=32).pack(
            side="left")
        ctk.CTkButton(row, text="Выбрать папку вручную", command=self._pick_manual,
                      fg_color=theme.PANEL2, hover_color=theme.LINE,
                      text_color=theme.TEXT, corner_radius=8, height=32).pack(
            side="left", padx=(8, 0))
        self._check_card()

    def _pick_card(self, value):
        if value and value != "—":
            self.card = value
            self.status_label.configure(
                text=f"Выбрана карта: {os.path.basename(self.card)}",
                text_color=theme.OK)

    def _check_card(self):
        cards = self.ctrl.list_cards()
        if len(cards) == 1:
            self.card = cards[0]
            self.card_choice.configure(values=["—"])
            self.card_choice.set("—")
            self.status_label.configure(
                text=f"Карта найдена: {os.path.basename(self.card)}",
                text_color=theme.OK)
        elif len(cards) == 0:
            self.card = ""
            self.card_choice.configure(values=["—"])
            self.card_choice.set("—")
            self.status_label.configure(
                text="Карта не найдена.\nВставьте карту в кардридер и нажмите "
                     "«Искать карты».", text_color=theme.WARN)
        else:
            self.card = ""
            self.card_choice.configure(values=cards)
            self.card_choice.set(cards[0])
            self._pick_card(cards[0])
            self.status_label.configure(
                text="Подключено несколько носителей.\n"
                     "Выберите нужную карту в списке ниже.",
                text_color=theme.WARN)

    # --- Шаг 2: что записать -------------------------------------------
    def _render_choice(self):
        b = self.body
        self.label(b, "Шаг 2. Что записать на карту", size="h2", bold=True).pack(
            anchor="w", padx=18, pady=(18, 4))

        # ТЗ: при выборе модели семейства FX3/FX3A показываем выбор ИМЕНОВАННОЙ
        # ПАРЫ, а не одиночную модель. Пары живут у оператора.
        pair_row = ctk.CTkFrame(b, fg_color="transparent")
        pair_row.pack(fill="x", padx=18, pady=(0, 6))
        self.pair_choice = _Choice(pair_row, ["—"], self._on_pair)
        self.pair_choice.pack(side="left", fill="x", expand=True)
        self._btn(pair_row, "Обновить", lambda: self._reload_pairs(),
                  ghost=True).pack(side="left", padx=(6, 0))
        self.pair_note = self.label(
            b, "Пара FX3/FX3A: необязательно. Выберите пару, чтобы записать оба "
               "комплекта сразу.", size="tiny", color=theme.MUTED, wrap=520)
        self.pair_note.pack(anchor="w", padx=18, pady=(0, 8))

        self.label(b, "Оператор", size="small", color=theme.MUTED).pack(
            anchor="w", padx=18)
        self.operator_box = _Choice(b, self.ctrl.list_operators(),
                                    self._on_operator)
        self.operator_box.pack(fill="x", padx=18, pady=(4, 12))

        self.label(b, "Модель", size="small", color=theme.MUTED).pack(
            anchor="w", padx=18)
        self.camera_box = _Choice(b, [], self._on_camera)
        self.camera_box.pack(fill="x", padx=18, pady=(4, 12))

        self.label(b, "Набор", size="small", color=theme.MUTED).pack(
            anchor="w", padx=18)
        self.preset_box = _Choice(b, [], self._on_preset)
        self.preset_box.pack(fill="x", padx=18, pady=(4, 12))

        self.label(b, "Сохранённая версия", size="small", color=theme.MUTED).pack(
            anchor="w", padx=18)
        self.version_box = _Choice(b, [], None)
        self.version_box.pack(fill="x", padx=18, pady=(4, 8))

        self._on_operator(self.operator_box.get() or
                          (self.ctrl.list_operators() or [""])[0])

    def _hint_for_camera(self):
        """Подсказка про пару в зависимости от выбранной модели (ТЗ).

        ТЗ: «При выборе любой модели семейства FX3/FX3A в сценарии записи
        показывай выбор именованной пары, а не одиночную модель.» Пары сейчас
        выключены шлюзом, поэтому вместо ложного выбора пары мы явно объясняем
        это и ведём к одиночной записи — без обещаний, что запись «парная».
        """
        default = ("Пара FX3/FX3A: необязательно. Выберите пару, чтобы записать "
                   "оба комплекта сразу.")
        if self.use_pair:
            return  # активна пара — не перетираем её подпись
        cam = (self.camera or "").lower()
        is_family = "fx3" in cam  # и FX3, и FX3A
        if not is_family:
            self.pair_note.configure(text=default, text_color=theme.MUTED)
            return
        if not self.ctrl.pair_write_available():
            self.pair_note.configure(
                text="Это модель семейства FX3/FX3A. Парная запись (FX3 + FX3A "
                     "сразу) пока выключена: пути ещё не подтверждены на реальной "
                     "карте и камерах. Сейчас будет записан один выбранный набор.",
                text_color=theme.WARN)
        else:
            self.pair_note.configure(
                text="Это модель семейства FX3/FX3A. Чтобы записать оба "
                     "комплекта сразу, выберите пару сверху.",
                text_color=theme.MUTED)

    def _reload_pairs(self):
        """Пары текущего оператора. Заблокированы, пока пути не подтверждены."""
        if not self.ctrl.pair_write_available():
            self.pair_choice.configure_values(["—"])
            self.pair_choice.set("—")
            self.pair_note.configure(
                text="Пары FX3/FX3A временно недоступны для записи: пути этих "
                     "моделей ещё не подтверждены образцами с реальной карты. "
                     "Запись одиночного набора работает как обычно.",
                text_color=theme.WARN)
            return
        op = self.operator_box.get() if hasattr(self, "operator_box") else ""
        names = [p.name for p in self.ctrl.pairs.list_pairs(op)]
        self.pair_choice.configure_values(["—"] + names)
        self.pair_choice.set("—")

    def _on_pair(self, value):
        self.use_pair = bool(value and value != "—")
        self.pair = (self.ctrl.pairs.get(value, self.operator_box.get())
                     if self.use_pair else None)
        if self.pair is not None:
            missing = self.pair.missing_slots()
            tip = ("Пара неполная: нет " + ", ".join(missing) +
                   ". Запишется только имеющаяся часть." if missing
                   else "Пара полная: запишутся оба комплекта.")
            self.pair_note.configure(text=tip,
                                     text_color=(theme.WARN if missing else theme.OK))
        else:
            self._hint_for_camera()

    def _on_operator(self, operator):
        self.operator = operator
        cams = sorted({c for c in self.ctrl.list_cameras()
                       if self.ctrl.list_presets(operator, c)})
        if hasattr(self, "pair_choice"):
            self._reload_pairs()
        self.camera_box.configure_values(cams)
        self._on_camera(cams[0] if cams else "")

    def _on_camera(self, camera):
        self.camera = camera
        presets = self.ctrl.list_presets(self.operator, camera) if camera else []
        self.preset_box.configure_values(presets)
        self._on_preset(presets[0] if presets else "")
        if hasattr(self, "pair_note"):
            self._hint_for_camera()

    def _on_preset(self, preset):
        self.preset = preset
        versions = (self.ctrl.list_versions(self.operator, self.camera, preset)
                    if preset else [])
        labels = [f"{v.version_id} · {v.file_count} файл(ов)" for v in versions]
        self.version_box.configure_values(labels)
        if labels:
            self.version_box.set(labels[0])

    def _selected_version(self):
        label = self.version_box.get()
        if not label:
            return None
        vid = label.split(" · ")[0]
        for v in self.ctrl.list_versions(self.operator, self.camera, self.preset):
            if v.version_id == vid:
                return v
        return None

    # --- Навигация -----------------------------------------------------
    def next(self):
        if self.step_index == 0:
            if not self.card:
                dialogs.warn(self, "Сначала карта",
                             "Вставьте карту и нажмите «Искать карты».")
                return
            self.go_to(1)
        elif self.step_index == 1:
            if self.use_pair:
                if self.pair is None:
                    dialogs.warn(self, "Пара не выбрана", "Выберите пару или набор.")
                    return
                try:
                    self.preview = self.ctrl.preview_pair_write(self.pair, self.card)
                except Exception as e:  # noqa: BLE001
                    dialogs.error(self, "Не удалось посмотреть изменения",
                                  _human_error(e))
                    return
                self.go_to(2)
                return
            version = self._selected_version()
            if version is None:
                dialogs.warn(self, "Нечего записывать",
                             "В библиотеке пока нет сохранённых наборов.\n"
                             "Сначала сохраните настройки с карты.")
                return
            self.version = version
            # ТЗ: перед записью показываем, какие файлы создаются/заменяются,
            # чтобы человек видел последствия и подтвердил их.
            try:
                self.preview = self.ctrl.preview_write(version, self.card)
            except Exception as e:  # noqa: BLE001
                dialogs.error(self, "Не удалось посмотреть изменения", _human_error(e))
                return
            self.go_to(2)
        elif self.step_index == 2:
            self._write()
        else:
            self._close()

    # --- Шаг 3: что именно изменится на карте --------------------------
    def _render_changes(self):
        b = self.body
        self.label(b, "Шаг 3. Что изменится на карте", size="h2", bold=True).pack(
            anchor="w", padx=18, pady=(18, 4))
        self.label(b, "На карте заменятся только файлы настроек. "
                      "Видео и фотографии не трогаем.",
                   size="small", color=theme.MUTED).pack(
            anchor="w", padx=18, pady=(0, 12))

        v = self.version
        if self.use_pair and self.pair is not None:
            missing = self.pair.missing_slots()
            warn = ("Внимание: пара неполная — нет " + ", ".join(missing) +
                    ". Запишется только имеющаяся часть." if missing else
                    "Пара полная: запишутся оба комплекта.")
            self.label(b, f"Пара: {self.pair.name}  ({self.pair.operator})",
                       size="small").pack(anchor="w", padx=18, pady=(0, 4))
            self.label(b, warn, size="small",
                       color=(theme.WARN if missing else theme.OK)).pack(
                anchor="w", padx=18, pady=(0, 10))
        elif v:
            self.label(b, f"Оператор: {v.operator}   Модель: {v.camera}\n"
                          f"Набор: {v.preset}   Версия: {v.version_id}",
                       size="small").pack(anchor="w", padx=18, pady=(0, 10))

        changes = getattr(self.preview, "written", []) if self.preview else []
        self.label(b, f"Файлов к записи: {len(changes)}", size="small",
                   color=(theme.OK if changes else theme.WARN)).pack(
            anchor="w", padx=18, pady=(0, 4))
        # ТЗ: показать источник, цель, модель, пресет, версию и конкретные файлы.
        self.label(
            b,
            f"Откуда: библиотека оператора {self.operator or '—'}\n"
            f"Куда: карта {os.path.basename(self.card.rstrip(os.sep)) or self.card}\n"
            f"Файлы (относительные пути на карте):",
            size="tiny", color=theme.MUTED, wrap=520).pack(
            anchor="w", padx=18, pady=(0, 4))
        warn_text = getattr(self.preview, "message", "") if self.preview else ""
        if warn_text:
            self.label(b, warn_text, size="tiny", color=theme.WARN,
                       wrap=520).pack(anchor="w", padx=18, pady=(0, 6))

        box = ctk.CTkTextbox(b, height=150, fg_color=theme.PANEL2,
                             text_color=theme.TEXT, border_width=0,
                             corner_radius=8)
        box.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        box.insert("1.0", "\n".join(changes) or "— (нечего записывать)")
        box.configure(state="disabled")

    def _write(self):
        self.busy(True, "Записываю…")
        use_pair = self.use_pair and self.pair is not None
        pair = self.pair
        version = self.version

        def work():
            if use_pair:
                return self.ctrl.write_pair_to_card(pair, self.card,
                                                    should_cancel=self._cancelled)
            return self.ctrl.write_to_card(version, self.card,
                                           should_cancel=self._cancelled)

        def done(rep):
            self.busy(False)
            if rep.ok:
                self.go_to(3)
                self.app.refresh()
            else:
                dialogs.error(self, "Запись не завершилась",
                              _human_error(Exception(rep.message)),
                              detail="Если что-то пошло не так, прежние "
                                     "настройки восстановлены.")

        def fail(e):
            self.busy(False)
            dialogs.error(self, "Запись не удалась", _human_error(e))

        self.run_bg(work, done, fail)

    def _render_final(self):
        b = self.body
        self.label(b, "Готово! Настройки записаны на карту", size="h2",
                   bold=True, color=theme.OK).pack(anchor="w", padx=18,
                                                   pady=(18, 6))
        v = self.version
        if self.use_pair and self.pair is not None:
            missing = self.pair.missing_slots()
            tip = ("Записана только часть пары: нет " + ", ".join(missing) + "."
                   if missing else "Записаны оба комплекта пары.")
            self.label(b, f"Пара: {self.pair.name}  ({self.pair.operator})\n{tip}",
                       size="small").pack(anchor="w", padx=18, pady=(0, 8))
        elif v:
            self.label(b, f"Оператор: {v.operator}\nМодель: {v.camera}\n"
                          f"Набор: {v.preset}", size="small").pack(
                anchor="w", padx=18, pady=(0, 8))
        self.label(b, "Теперь карту можно смело вынуть из кардридера.",
                   size="small", color=theme.MUTED).pack(anchor="w", padx=18)

        # ТЗ: после завершения предложить безопасно извлечь карту; извлекаем
        # ТОЛЬКО по явному нажатию, никаких «тихих» попыток.
        self._btn(b, "Безопасно извлечь карту", self._eject,
                  ghost=True).pack(anchor="w", padx=18, pady=(12, 0))

    def _eject(self):
        if not self.card:
            return
        ok, msg = safe_eject(self.card)
        if ok:
            dialogs.info(self, "Карту можно вынуть",
                         "Система готова к извлечению. Выньте карту из кардридера.")
        else:
            dialogs.warn(self, "Извлечь не удалось",
                         msg or "Извлеките карту вручную только после записи.")


class _Choice(ctk.CTkFrame):
    """Простой выпадающий список, который не даёт ввести мусор."""

    def __init__(self, master, values, command):
        super().__init__(master, fg_color="transparent")
        self._command = command
        self.combo = ctk.CTkComboBox(self, values=values or ["—"],
                                     state="readonly",
                                     command=self._on_change)
        self.combo.pack(fill="x")
        if values:
            self.combo.set(values[0])
        else:
            self.combo.set("—")

    def _on_change(self, value):
        if self._command:
            self._command(value)

    def get(self):
        v = self.combo.get()
        return "" if v == "—" else v

    def set(self, value):
        self.combo.set(value)

    def configure_values(self, values):
        self.combo.configure(values=values or ["—"])
        self.combo.set(values[0] if values else "—")


def _human_error(e: Exception) -> str:
    """Перевести техническую ошибку в понятную обычному человеку фразу."""
    text = str(e)
    low = text.lower()
    if "места" in low:
        return ("На диске не хватило места.\n"
                "Освободите немного места и повторите.")
    if "защищ" in low or "read-only" in low or "readonly" in low:
        return ("Карта защищена от записи.\n"
                "Сдвиньте переключатель lock на адаптере карты.")
    if "не найден" in low or "не найдено" in low:
        return ("Не нашёл нужные файлы.\n"
                "Проверьте, что это карта той самой камеры.")
    if "носител" in low:
        return ("Карта не отвечает.\n"
                "Выньте её и вставьте заново, затем нажмите «Проверить карту».")
    if "отмен" in low:
        return "Действие отменено."
    if "не совпал" in low or "проверк" in low:
        return ("Содержимое после записи не совпало.\n"
                "Повторите запись. Если повторится — карта повреждена.")
    return f"Что-то пошло не так.\n{text}"
