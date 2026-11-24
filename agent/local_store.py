# -*- coding: utf-8 -*-
"""Локальное хранилище агента.

Агент работает полностью автономно, без сервера. Этот модуль держит
небольшой набор «подсказок» для интерфейса — какие камеры и операторы
уже встречались — в локальном JSON-файле, чтобы списки не «пропадали»
между запусками и не зависели ни от чего внешнего.

Основной источник данных — локальный каталог (SQLite) и папки архива.
Этот файл лишь дополняет их тем, что пользователь ввёл вручную.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from mastersetting.config import app_data_dir


def _store_file() -> Path:
    return app_data_dir() / "local_data.json"


@dataclass
class LocalData:
    """Снимок известных имён (камеры/операторы) и служебных групп."""

    cameras: list[str] = field(default_factory=list)
    operators: list[str] = field(default_factory=list)
    settings_names: list[str] = field(default_factory=list)
    instruction_groups: list[str] = field(default_factory=list)
    updated_at: float = 0.0
    source: str = "local"  # local | default


class LocalStore:
    """Локальные подсказки с деградацией до значений по умолчанию."""

    def __init__(self, path: str | None = None):
        self.path = Path(path) if path else _store_file()
        self._data: dict = {}
        self._load()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}
        self._data.setdefault("cameras", [])
        self._data.setdefault("operators", [])
        self._data.setdefault("settings_names", [])
        self._data.setdefault("instruction_groups", [])
        self._data.setdefault("updated_at", 0.0)

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    def store_data(self, data: LocalData) -> None:
        """Сохранить снимок известных имён."""
        self._data["cameras"] = list(data.cameras)
        self._data["operators"] = list(data.operators)
        self._data["settings_names"] = list(data.settings_names)
        self._data["instruction_groups"] = list(data.instruction_groups)
        self._data["updated_at"] = data.updated_at or time.time()
        self._save()

    def get_data(self, defaults_cameras: list[str] | None = None) -> LocalData:
        """Вернуть снимок: из файла, либо значения по умолчанию."""
        cameras = self._data.get("cameras") or list(defaults_cameras or [])
        source = "local" if self._data.get("cameras") else "default"
        return LocalData(
            cameras=cameras,
            operators=self._data.get("operators", []),
            settings_names=self._data.get("settings_names", []),
            instruction_groups=self._data.get("instruction_groups", []),
            updated_at=self._data.get("updated_at", 0.0),
            source=source,
        )

    # ------------------------------------------------------------------
    def merge_operator(self, name: str) -> None:
        ops = self._data.setdefault("operators", [])
        if name and name not in ops:
            ops.append(name)
            ops.sort()
            self._save()

    def merge_camera(self, name: str) -> None:
        cams = self._data.setdefault("cameras", [])
        if name and name not in cams:
            cams.append(name)
            cams.sort()
            self._save()

    # ------------------------------------------------------------------
    def last_update_iso(self) -> str:
        updated = self._data.get("updated_at", 0.0)
        if not updated:
            return ""
        from datetime import datetime
        return datetime.fromtimestamp(updated).isoformat(timespec="seconds")

    def has_data(self) -> bool:
        return bool(self._data.get("cameras") or self._data.get("operators"))
