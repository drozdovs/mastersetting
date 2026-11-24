# -*- coding: utf-8 -*-
"""Библиотека пресетов с неизменяемыми версиями.

Модель данных (ТЗ, «Основная модель данных»):

    Оператор -> модель камеры -> пресет -> неизменяемые версии

Ключевое отличие от версии 1.9: каждый импорт создаёт **новую версию**, даже
если он сделан в тот же день. Существующие версии никогда не перезаписываются
и не удаляются молча.

Схема на диске::

    <base>/cameraman/<оператор>/<камера>/<пресет>/<version_id>/
        _version.json          # метаданные версии
        files/...              # сами файлы настроек с относительными путями

``version_id`` — сортируемый идентификатор ``YYYYMMDD-HHMMSS-xxxx`` (UTC + короткий
хеш), уникальный даже при нескольких импортах в одну секунду.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import fs_ops
from .filters import sanitize_name

# Папка с версиями пресета внутри архива: files/ + _version.json
VERSION_FILES_DIR = "files"
VERSION_META_FILE = "_version.json"

# Маркер неполного (незавершённого) импорта — защита от «полупустой» версии
INCOMPLETE_MARKER = ".incomplete"

_UNSAFE_PATH_RE = re.compile(r"[/\\]|\.\.")


def is_safe_rel_path(rel: str) -> bool:
    """Безопасен ли относительный путь внутри набора.

    Разрешаем подкаталоги (разделитель ``/``), но запрещаем абсолютные пути,
    выходы через ``..``, диски Windows, NUL-байты и обратные слэши.
    """
    if not rel or rel.startswith(("/", "\\")) or "\x00" in rel:
        return False
    if "\\" in rel:
        return False
    if re.match(r"^[A-Za-z]:", rel):
        return False
    parts = rel.split("/")
    return all(part not in ("", ".", "..") for part in parts)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def safe_component(name: str, max_length: int = 30) -> str:
    """Безопасный компонент пути (имя пресета/оператора/камеры).

    Отображаемое имя никогда не должно попадать в путь «как есть»: убираем
    разделители и ``..``, ограничиваем длину. Регистр НЕ меняем — но сравнение
    имён на уровне вызывающего кода должно быть без учёта регистра.
    """
    cleaned = sanitize_name(name, max_length=max_length)
    cleaned = _UNSAFE_PATH_RE.sub("", cleaned)
    return cleaned


def _version_id(when: datetime, seed: str) -> str:
    """Сортируемый уникальный идентификатор версии."""
    stamp = when.strftime("%Y%m%d-%H%M%S")
    digest = hashlib.sha1(f"{stamp}:{seed}:{os.urandom(8).hex()}".encode()).hexdigest()
    return f"{stamp}-{digest[:4]}"


@dataclass
class FileRecord:
    """Один файл версии."""
    rel_path: str          # относительный путь от корня набора, напр. PRIVATE/SONY/.../FX3.DAT
    size: int = 0
    sha256: str = ""


@dataclass
class _DisplayNames:
    """Отображаемые имена, найденные в библиотеке (для защиты от коллизий)."""
    operators: list[str]
    cameras: list[str]
    presets: list[str]


@dataclass
class PresetVersion:
    """Неизменяемая версия пресета."""
    version_id: str
    operator: str
    camera: str
    preset: str
    created_at: str                     # ISO-8601 UTC
    files: list[FileRecord] = field(default_factory=list)
    total_bytes: int = 0
    verified: bool = False
    source_media: str = ""              # с какого носителя сделана версия
    source_model: str = ""              # модель из заголовка файла (напр. ILME-FX3)
    firmware: str = ""                  # если удалось определить
    note: str = ""

    @property
    def file_count(self) -> int:
        return len(self.files)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "PresetVersion":
        data = json.loads(text)
        data["files"] = [FileRecord(**f) for f in data.get("files", [])]
        return cls(**data)


@dataclass
class ImportReport:
    """Результат импорта новой версии."""
    ok: bool
    version_id: str = ""
    message: str = ""
    files: int = 0
    bytes_: int = 0
    mismatches: list[str] = field(default_factory=list)
    path: str = ""


class VersionStoreError(Exception):
    """Ошибка работы с библиотекой версий (понятный пользователю текст)."""


class VersionStore:
    """Хранилище пресетов с неизменяемыми версиями.

    Работает с файловой системой и ничего не знает о GUI. Все операции,
    меняющие диск, безопасны: запись идёт во временную папку и лишь затем
    атомарно переносится на место; при сбое временные данные удаляются.
    """

    def __init__(self, base_path: str):
        self.base_path = base_path

    # ------------------------------------------------------------------
    # Пути
    # ------------------------------------------------------------------
    def preset_dir(self, operator: str, camera: str, preset: str) -> Path:
        return (
            Path(self.base_path)
            / "cameraman"
            / safe_component(operator)
            / safe_component(camera)
            / safe_component(preset)
        )

    def version_dir(self, operator: str, camera: str, preset: str,
                    version_id: str) -> Path:
        # version_id приходит от нас, но защищаемся и здесь
        if _UNSAFE_PATH_RE.search(version_id):
            raise VersionStoreError(f"Недопустимый id версии: {version_id!r}")
        return self.preset_dir(operator, camera, preset) / version_id

    # ------------------------------------------------------------------
    # Чтение
    # ------------------------------------------------------------------
    def list_versions(self, operator: str, camera: str, preset: str) -> list[PresetVersion]:
        root = self.preset_dir(operator, camera, preset)
        if not root.is_dir():
            return []
        out: list[PresetVersion] = []
        for item in root.iterdir():
            if not item.is_dir():
                continue
            meta_path = item / VERSION_META_FILE
            if not meta_path.is_file():
                continue
            try:
                out.append(PresetVersion.from_json(meta_path.read_text(encoding="utf-8")))
            except Exception:
                continue
        # Свежие версии — первыми (id сортируется лексикографически)
        out.sort(key=lambda v: v.version_id, reverse=True)
        return out

    def latest_version(self, operator: str, camera: str, preset: str) -> PresetVersion | None:
        versions = self.list_versions(operator, camera, preset)
        return versions[0] if versions else None

    def list_presets(self, operator: str, camera: str) -> list[str]:
        """Отображаемые имена пресетов оператора и камеры."""
        return sorted(self._display_presets(operator, camera))

    def _display_presets(self, operator: str, camera: str) -> list[str]:
        """Отображаемые имена пресетов (из метаданных версий, а не из папок).

        Папки хранят безопасный компонент, поэтому исходное имя берём из
        ``_version.json`` — иначе потеряли бы регистр/различие имён.
        """
        root = Path(self.base_path) / "cameraman" / safe_component(operator) / safe_component(camera)
        if not root.is_dir():
            return []
        names: list[str] = []
        for d in sorted(root.iterdir()):
            if not d.is_dir():
                continue
            found = None
            for vdir in sorted(d.iterdir()):
                meta = vdir / VERSION_META_FILE
                if meta.is_file():
                    try:
                        found = PresetVersion.from_json(
                            meta.read_text(encoding="utf-8")).preset
                        break
                    except Exception:
                        continue
            names.append(found if found is not None else d.name)
        return names

    def _display_names(self) -> "_DisplayNames":
        """Все отображаемые имена операторов, камер и пресетов в библиотеке.

        Нужны, чтобы не допустить молчаливого слияния разных имён в один путь
        (дефект 1.9 «потеря символов и коллизии»). Имена берём из метаданных
        версий, поэтому регистр и «лишние» символы сохраняются.
        """
        ops: set[str] = set()
        cams: set[str] = set()
        presets: set[str] = set()
        root = Path(self.base_path) / "cameraman"
        if not root.is_dir():
            return _DisplayNames([], [], [])
        for op_dir in sorted(root.iterdir()):
            if not op_dir.is_dir():
                continue
            for cam_dir in sorted(op_dir.iterdir()):
                if not cam_dir.is_dir():
                    continue
                for preset_dir in sorted(cam_dir.iterdir()):
                    if not preset_dir.is_dir():
                        continue
                    for vdir in sorted(preset_dir.iterdir()):
                        meta = vdir / VERSION_META_FILE
                        if not meta.is_file():
                            continue
                        try:
                            v = PresetVersion.from_json(meta.read_text(encoding="utf-8"))
                        except Exception:
                            continue
                        ops.add(v.operator)
                        cams.add(v.camera)
                        presets.add(v.preset)
                        break
        return _DisplayNames(sorted(ops), sorted(cams), sorted(presets))

    def load_version(self, operator: str, camera: str, preset: str,
                     version_id: str) -> PresetVersion:
        meta = self.version_dir(operator, camera, preset, version_id) / VERSION_META_FILE
        if not meta.is_file():
            raise VersionStoreError(f"Версия не найдена: {version_id}")
        return PresetVersion.from_json(meta.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Импорт (новая версия)
    # ------------------------------------------------------------------
    def import_files(
        self,
        operator: str,
        camera: str,
        preset: str,
        source_files: dict[str, str],
        source_media: str = "",
        source_model: str = "",
        firmware: str = "",
        note: str = "",
        progress=None,
        should_cancel=None,
    ) -> ImportReport:
        """Создать новую версию из набора файлов.

        ``source_files`` — словарь ``{rel_path_в_наборе: абсолютный_путь_источника}``.
        Всегда создаёт НОВУЮ версию; одинаковое имя версии невозможно.
        """
        if not operator or not camera or not preset:
            raise VersionStoreError("Заполните оператора, камеру и название пресета")
        if not source_files:
            raise VersionStoreError("Нет файлов для импорта")

        # Имя — отображаемое поле, а в путь идёт безопасный компонент. Защищаемся
        # от дефекта 1.9 («очистка имён с потерей символов и коллизиями»):
        # пустое имя недопустимо, а разные имена не должны молча слиться в папку.
        for label, value in (("оператора", operator), ("камеры", camera),
                             ("пресета", preset)):
            if not safe_component(value):
                raise VersionStoreError(
                    f"Имя {label} состоит только из недопустимых символов. "
                    "Оставьте буквы или цифры.")
        names = self._display_names()
        # Пресет может совпадать по названию у разных операторов/камер — это
        # разные папки. Проверяем только внутри одной группы.
        target = safe_component(preset).casefold()
        for existing in self._display_presets(operator, camera):
            if existing == preset:
                continue  # тот же пресет — новая версия это норма
            if safe_component(existing).casefold() == target:
                raise VersionStoreError(
                    f"Название уже занято похожим: «{existing}». "
                    "Выберите другое, чтобы пресеты не смешались.")
        for label, value, existing in (("оператора", operator, names.operators),
                                       ("камеры", camera, names.cameras)):
            target2 = safe_component(value).casefold()
            for other in existing:
                if other == value:
                    continue
                if safe_component(other).casefold() == target2:
                    raise VersionStoreError(
                        f"Имя {label} уже занято похожим: «{other}». "
                        "Выберите другое, чтобы данные не смешались.")

        for rel in source_files:
            if not is_safe_rel_path(rel):
                raise VersionStoreError(f"Опасный относительный путь: {rel!r}")

        # Убедимся, что файлы существуют и не пустые
        for rel, abs_src in source_files.items():
            if not os.path.isfile(abs_src):
                raise VersionStoreError(f"Файл не найден: {abs_src}")
            if os.path.islink(abs_src):
                raise VersionStoreError(f"Символические ссылки не поддерживаются: {abs_src}")

        now = _now_utc()
        vid = _version_id(now, f"{operator}/{camera}/{preset}")
        final_dir = self.version_dir(operator, camera, preset, vid)

        if final_dir.exists():  # практически невозможно, но защищаемся
            raise VersionStoreError(f"Версия уже существует: {vid}")

        preset_root = self.preset_dir(operator, camera, preset)
        tmp_dir = preset_root / f".tmp-{vid}"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        files_root = tmp_dir / VERSION_FILES_DIR
        files_root.mkdir(parents=True, exist_ok=True)
        (tmp_dir / INCOMPLETE_MARKER).write_text("1", encoding="utf-8")

        records: list[FileRecord] = []
        total = 0
        try:
            items = list(source_files.items())
            for idx, (rel, abs_src) in enumerate(items):
                if should_cancel and should_cancel():
                    raise fs_ops.CopyCancelled()
                dst = files_root / Path(rel)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(abs_src, dst)
                sha = fs_ops.hash_file(str(dst))
                size = os.path.getsize(dst)
                records.append(FileRecord(rel_path=rel.replace(os.sep, "/"),
                                          size=size, sha256=sha))
                total += size
                if progress:
                    progress(idx + 1, len(items), rel)
        except fs_ops.CopyCancelled:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
        except Exception as e:  # noqa: BLE001
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise VersionStoreError(f"Ошибка импорта: {e}") from e

        version = PresetVersion(
            version_id=vid, operator=operator, camera=camera, preset=preset,
            created_at=now.isoformat(), files=records, total_bytes=total,
            verified=True, source_media=source_media, source_model=source_model,
            firmware=firmware, note=note,
        )
        (tmp_dir / VERSION_META_FILE).write_text(version.to_json(), encoding="utf-8")
        (tmp_dir / INCOMPLETE_MARKER).unlink(missing_ok=True)

        # Атомарный перенос на место
        tmp_dir.rename(final_dir)

        return ImportReport(
            ok=True, version_id=vid, files=len(records), bytes_=total,
            message=f"Создана версия {vid} ({len(records)} файл(ов))",
            path=str(final_dir),
        )

    # ------------------------------------------------------------------
    # Удаление пресета (окончательное, по явному подтверждению)
    # ------------------------------------------------------------------
    def delete_preset(self, operator: str, camera: str, preset: str,
                      confirm_versions: int) -> None:
        """Удалить пресет со всеми версиями.

        Требует передачи фактического числа версий как подтверждения, чтобы
        исключить случайное удаление. Регистр имени не важен.
        """
        versions = self.list_versions(operator, camera, preset)
        if len(versions) != confirm_versions:
            raise VersionStoreError(
                f"Число версий не совпало ({len(versions)} != {confirm_versions}); удаление отменено"
            )
        root = self.preset_dir(operator, camera, preset)
        if not root.is_dir():
            raise VersionStoreError("Пресет не найден")
        shutil.rmtree(root)
