# -*- coding: utf-8 -*-
"""Высокоуровневый сервис библиотеки: сохранение с карты и запись на карту.

Связывает три части ядра:

* ``settings_rules`` — найти ТОЛЬКО файлы настроек (или предложить импорт из
  папки с предварительным просмотром);
* ``versioning``      — сохранить их как неизменяемую версию пресета;
* ``safe_write``      — записать выбранную версию на носитель безопасно.

Модуль не знает о GUI и не извлекает карту сам. Все «разрушающие» действия
запускаются только явными вызовами. По ТЗ для FX3/FX3A до подтверждения путей
парная запись запрещена — см. ``docs/FX3_PAIR_GATEWAY.md``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import fs_ops
from .platform import is_system_path
from .safe_write import SafeWriter, WriteReport
from .settings_rules import (
    DiscoveryResult,
    detect_source_model,
    discover_in_folder,
    rule_for,
    settings_files_map,
)
from .versioning import ImportReport, PresetVersion, VersionStore, VersionStoreError


@dataclass
class SavePlan:
    """Предварительный просмотр перед сохранением с карты."""
    discovery: DiscoveryResult
    files: dict[str, str] = field(default_factory=dict)   # {rel: abs}
    total_bytes: int = 0
    settings_dir_prefix: str = ""
    is_confirmed_format: bool = False   # подтверждён ли формат модели
    detected_model: str = ""            # модель из заголовка файла (напр. ILME-FX3)
    warnings: list[str] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.files)


class LibraryError(Exception):
    """Ошибка операции библиотеки."""


class PairWriteError(Exception):
    """Парная запись невозможна (конфликт путей или нет ни одной части)."""


def find_path_conflicts(files_a: dict[str, str], files_b: dict[str, str]) -> list[str]:
    """Пути, в которые метят ОБА набора настроек (сравнение без учёта регистра).

    ТЗ запрещает писать один комплект поверх другого: если нативные пути двух
    моделей совпадают, двойная запись невозможна — нужно сообщить о конфликте.
    """
    seen: dict[str, str] = {}
    for rel in files_a:
        seen.setdefault(rel.replace("\\", "/").lower(), rel)
    clashes: list[str] = []
    for rel in files_b:
        key = rel.replace("\\", "/").lower()
        if key in seen:
            clashes.append(seen[key])
    return sorted(set(clashes))


def plan_pair_write(files_fx3: dict[str, str], files_fx3a: dict[str, str],
                    *, warn_incomplete: bool = False,
                    with_warnings: bool = False):
    """План парной записи FX3 + FX3A с проверкой конфликта путей.

    Возвращает объединённый набор ``{rel: abs}``. При ``with_warnings=True``
    возвращает кортеж ``(план, предупреждения)``.

    * конфликт путей -> ``PairWriteError`` (писать нельзя);
    * пустой один из комплектов -> предупреждение «пара неполная», но
      имеющаяся часть записывается (ТЗ разрешает с заметным предупреждением).
    """
    clashes = find_path_conflicts(files_fx3, files_fx3a)
    if clashes:
        raise PairWriteError(
            "Пути комплектов совпадают, запись обоих запрещена: "
            + ", ".join(clashes)
        )

    warnings: list[str] = []
    if warn_incomplete:
        if not files_fx3 and not files_fx3a:
            raise PairWriteError("Пара пустая: нечего записывать")
        if not files_fx3:
            warnings.append("Пара неполная: нет комплекта FX3 — будет записан только FX3A.")
        if not files_fx3a:
            warnings.append("Пара неполная: нет комплекта FX3A — будет записан только FX3.")

    plan: dict[str, str] = {}
    plan.update(files_fx3)
    plan.update(files_fx3a)
    if with_warnings:
        return plan, warnings
    return plan


class PresetLibrary:
    """Сервис библиотеки пресетов."""

    def __init__(self, base_path: str):
        self.base_path = base_path
        self.store = VersionStore(base_path=base_path)

    # ------------------------------------------------------------------
    # Сохранить с карты (карта -> библиотека)
    # ------------------------------------------------------------------
    def plan_from_media(self, camera_family: str, media_root: str) -> SavePlan:
        """Что именно будет сохранено с носителя/папки (до самого копирования).

        Если для модели есть ПОДТВЕРЖДЁННОЕ правило — берём только её файлы
        настроек. Иначе предлагаем импорт из папки с просмотром и честно
        помечаем, что формат не подтверждён.
        """
        rule = rule_for(camera_family)
        warnings: list[str] = []

        def _detect(files_map: dict[str, str]) -> str:
            for abs_src in files_map.values():
                found = detect_source_model(abs_src)
                if found:
                    return found
            return ""

        if rule and rule.confirmed and rule.settings_dirs:
            # Точный режим: смотрим только заданные папки
            files: dict[str, str] = {}
            for sub in rule.settings_dirs:
                folder = os.path.join(media_root, *sub.split("/"))
                res = discover_in_folder(folder) if os.path.isdir(folder) else DiscoveryResult(folder)
                for rel, abs_path in settings_files_map(res, root_prefix=sub).items():
                    files[rel] = abs_path
            total = sum(os.path.getsize(p) for p in files.values())
            discovery = DiscoveryResult(root=media_root)
            return SavePlan(discovery=discovery, files=files, total_bytes=total,
                            settings_dir_prefix=rule.settings_dirs[0],
                            is_confirmed_format=True, detected_model=_detect(files),
                            warnings=warnings)

        # Режим «импорт из папки с просмотром»
        discovery = discover_in_folder(media_root)
        files = settings_files_map(discovery)
        total = sum(os.path.getsize(p) for p in files.values())
        if rule is None:
            warnings.append("Для этой модели нет проверенного правила — формат не подтверждён.")
        else:
            warnings.append(
                "Пути настроек для этой модели ещё не подтверждены на реальной карте — "
                "формат не подтверждён."
            )
        if discovery.rejected:
            warnings.append(f"Пропущено файлов: {len(discovery.rejected)} (медиа/служебные/неизвестные).")
        return SavePlan(discovery=discovery, files=files, total_bytes=total,
                        is_confirmed_format=False, detected_model=_detect(files),
                        warnings=warnings)

    def save_from_media(
        self,
        operator: str,
        camera: str,
        preset: str,
        media_root: str,
        plan: SavePlan | None = None,
        source_media: str = "",
        source_model: str = "",
        firmware: str = "",
        note: str = "",
        progress=None,
        should_cancel=None,
    ) -> ImportReport:
        """Сохранить настройки с носителя как НОВУЮ версию пресета."""
        plan = plan or self.plan_from_media(camera, media_root)
        if not plan.files:
            raise LibraryError("Не найдено ни одного файла настроек на носителе")
        # Исходная модель — из заголовка самого файла (доказательство), а не из
        # выбора оператора. Если оператор указал модель явно — уважаем её.
        if not source_model:
            for abs_src in plan.files.values():
                detected = detect_source_model(abs_src)
                if detected:
                    source_model = detected
                    break
        return self.store.import_files(
            operator, camera, preset, plan.files,
            source_media=source_media or media_root,
            source_model=source_model, firmware=firmware, note=note,
            progress=progress, should_cancel=should_cancel,
        )

    # ------------------------------------------------------------------
    # Записать на карту (библиотека -> карта)
    # ------------------------------------------------------------------
    def preview_write(self, version: PresetVersion, card_root: str) -> WriteReport:
        """Что изменится на карте при записи версии (без самой записи)."""
        if is_system_path(card_root):
            raise LibraryError(
                "Нельзя писать в системный диск или папку приложения. "
                "Выберите карту памяти.")
        plan = self._write_map(version)
        report = WriteReport(ok=True, message="")
        for rel in plan:
            target = os.path.join(card_root, *rel.split("/"))
            if os.path.exists(target):
                try:
                    same = fs_ops.hash_file(target) == self._version_hash(version, rel)
                except OSError:
                    same = False
                kind = "без изменений" if same else "будет заменён"
            else:
                kind = "будет создан"
            report.written.append(f"{rel} — {kind}")
        return report

    def write_version_to_card(
        self,
        version: PresetVersion,
        card_root: str,
        verify: bool = True,
        progress=None,
        should_cancel=None,
    ) -> WriteReport:
        """Записать конкретную версию на карту безопасно (temp + verify + откат)."""
        if is_system_path(card_root):
            raise LibraryError(
                "Нельзя писать в системный диск или папку приложения. "
                "Выберите карту памяти.")
        plan = self._write_map(version)
        if not plan:
            raise LibraryError("У версии нет файлов")
        writer = SafeWriter(card_root)
        return writer.write(plan, verify=verify, progress=progress,
                            should_cancel=should_cancel)

    # ------------------------------------------------------------------
    # Запись пары FX3 + FX3A (шлюз: только подтверждённые пути)
    # ------------------------------------------------------------------
    def pair_paths_confirmed(self) -> bool:
        """Подтверждены ли пути FX3/FX3A с реальной карты (технический шлюз ТЗ)."""
        try:
            from mastersetting.path_confirm import apply_to_rules
            apply_to_rules()
        except Exception:
            pass
        try:
            f3 = rule_for("SonyFX3")
            f3a = rule_for("SonyFX3A")
        except Exception:
            return False
        return bool(f3 and f3a and f3.confirmed and f3a.confirmed
                    and f3.settings_dirs and f3a.settings_dirs)

    def pair_write_available(self) -> bool:
        """Можно ли включать парную запись (шлюз пройден и есть хотя бы один пресет).

        ТЗ: без образцов с реальной карты парную запись НЕ заявляем и не запускаем.
        """
        if not self.pair_paths_confirmed():
            return False
        return True

    def preview_pair_write(self, fx3_version: PresetVersion | None,
                           fx3a_version: PresetVersion | None,
                           card_root: str) -> WriteReport:
        """Что изменится при парной записи (без записи). Показывает конфликт путей."""
        if is_system_path(card_root):
            raise LibraryError("Нельзя писать в системный диск или папку приложения.")
        files_fx3 = self._write_map(fx3_version) if fx3_version else {}
        files_fx3a = self._write_map(fx3a_version) if fx3a_version else {}
        plan, warnings = plan_pair_write(files_fx3, files_fx3a,
                                         warn_incomplete=True, with_warnings=True)
        report = WriteReport(ok=True, message="")
        for rel in plan:
            target = os.path.join(card_root, *rel.split("/"))
            exists = os.path.exists(target)
            report.written.append(
                ("заменится: " if exists else "создастся: ") + rel)
        report.message = "\n".join(warnings)
        return report

    def write_pair_to_card(self, fx3_version: PresetVersion | None,
                           fx3a_version: PresetVersion | None, card_root: str,
                           verify: bool = True, progress=None,
                           should_cancel=None) -> WriteReport:
        """Записать пару (или имеющуюся часть) безопасно, с предупреждением.

        Отказ (``PairWriteError``) — если нативные пути комплектов конфликтуют:
        писать один поверх другого нельзя (ТЗ).
        """
        if not self.pair_write_available():
            raise PairWriteError(
                "Парная запись выключена: пути FX3/FX3A ещё не подтверждены "
                "образцами с реальной карты.")
        if is_system_path(card_root):
            raise LibraryError("Нельзя писать в системный диск или папку приложения.")
        files_fx3 = self._write_map(fx3_version) if fx3_version else {}
        files_fx3a = self._write_map(fx3a_version) if fx3a_version else {}
        plan, warnings = plan_pair_write(files_fx3, files_fx3a,
                                         warn_incomplete=True, with_warnings=True)
        writer = SafeWriter(card_root)
        rep = writer.write(plan, verify=verify, progress=progress,
                           should_cancel=should_cancel)
        if warnings:
            rep.message = (rep.message + "  " + " ".join(warnings)).strip()
        return rep

    # ------------------------------------------------------------------
    # Вспомогательное
    # ------------------------------------------------------------------
    def _write_map(self, version: PresetVersion) -> dict[str, str]:
        """{rel_путь_на_карте: abs_источник_в_версии}."""
        version_root = self.store.version_dir(
            version.operator, version.camera, version.preset, version.version_id)
        files_root = version_root / "files"
        out: dict[str, str] = {}
        for rec in version.files:
            src = files_root / Path(rec.rel_path)
            if not src.is_file():
                raise LibraryError(f"Файл версии пропал: {rec.rel_path}")
            out[rec.rel_path] = str(src)
        return out

    @staticmethod
    def _version_hash(version: PresetVersion, rel: str) -> str:
        for rec in version.files:
            if rec.rel_path == rel:
                return rec.sha256
        return ""

    def verify_version_on_card(self, version: PresetVersion, card_root: str) -> list[str]:
        """Сверить, что на карте лежит именно эта версия. Возвращает расхождения."""
        mismatches: list[str] = []
        for rec in version.files:
            target = os.path.join(card_root, *rec.rel_path.split("/"))
            if not os.path.exists(target):
                mismatches.append(rec.rel_path)
                continue
            try:
                if fs_ops.hash_file(target) != rec.sha256:
                    mismatches.append(rec.rel_path)
            except OSError:
                mismatches.append(rec.rel_path)
        return mismatches

    # ------------------------------------------------------------------
    # Удаление и экспорт
    # ------------------------------------------------------------------
    def delete_preset(self, operator: str, camera: str, preset: str,
                      confirm_versions: int) -> int:
        """Окончательно удалить пресет со всеми версиями.

        ТЗ: удаление необратимо и требует явного подтверждения с названием и
        числом версий. Возвращает число удалённых версий (для журнала).
        """
        versions = self.store.list_versions(operator, camera, preset)
        if not versions:
            raise LibraryError("Пресет не найден")
        try:
            self.store.delete_preset(operator, camera, preset, confirm_versions)
        except VersionStoreError as e:
            raise LibraryError(str(e)) from e
        return len(versions)

    def export_version(self, version: PresetVersion, dest_dir: str,
                       should_cancel=None) -> str:
        """Скопировать конкретную версию в папку, НЕ меняя её в библиотеке.

        ТЗ: экспорт позволяет получить конкретную версию без её изменения.
        Возвращает путь папки, куда скопировано.
        """
        files = self._write_map(version)   # {rel: abs_source в версии}
        if not files:
            raise LibraryError("У версии нет файлов")
        target_root = os.path.join(dest_dir, f"{version.preset}_{version.version_id}")
        os.makedirs(target_root, exist_ok=True)
        for rel, src in files.items():
            if should_cancel and should_cancel():
                raise fs_ops.CopyCancelled()
            dst = os.path.join(target_root, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            from shutil import copy2
            copy2(src, dst)
        return target_root
