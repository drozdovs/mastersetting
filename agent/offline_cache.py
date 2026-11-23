# -*- coding: utf-8 -*-
"""Офлайн-кэш агента.

Агент должен работать полностью без сервера. Этот модуль:
  * сохраняет данные, полученные от сервера (камеры, операторы, конфиг),
    в локальный JSON-файл;
  * отдаёт закэшированные данные, когда сервер недоступен;
  * помнит время последней успешной синхронизации.

Благодаря этому при обрыве связи список камер и операторов не «пропадает»,
а интерфейс работает на последних известных данных.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from mastersetting.config import app_data_dir


def _cache_file() -> Path:
    return app_data_dir() / "offline_cache.json"


@dataclass
class ServerConfig:
    """Конфиг, полученный с сервера (может быть закэширован)."""

    cameras: list[str] = field(default_factory=list)
    operators: list[str] = field(default_factory=list)
    settings_names: list[str] = field(default_factory=list)
    instruction_groups: list[str] = field(default_factory=list)
    fetched_at: float = 0.0
    source: str = "server"  # server | cache | default


class OfflineCache:
    """Локальный кэш серверных данных с деградацией до значений по умолчанию."""

    def __init__(self, path: str | None = None):
        self.path = Path(path) if path else _cache_file()
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
        self._data.setdefault("fetched_at", 0.0)
        self._data.setdefault("server_version", "")

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
    def store_config(self, config: ServerConfig) -> None:
        """Сохранить конфиг, полученный с сервера."""
        self._data["cameras"] = list(config.cameras)
        self._data["operators"] = list(config.operators)
        self._data["settings_names"] = list(config.settings_names)
        self._data["instruction_groups"] = list(config.instruction_groups)
        self._data["fetched_at"] = config.fetched_at or time.time()
        self._save()

    def get_config(self,
                   defaults_cameras: list[str] | None = None) -> ServerConfig:
        """Вернуть конфиг: из кэша, либо значения по умолчанию."""
        cameras = self._data.get("cameras") or list(defaults_cameras or [])
        source = "cache" if self._data.get("cameras") else "default"
        return ServerConfig(
            cameras=cameras,
            operators=self._data.get("operators", []),
            settings_names=self._data.get("settings_names", []),
            instruction_groups=self._data.get("instruction_groups", []),
            fetched_at=self._data.get("fetched_at", 0.0),
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
    def is_stale(self, max_age_seconds: float = 24 * 3600) -> bool:
        fetched = self._data.get("fetched_at", 0.0)
        return (time.time() - fetched) > max_age_seconds

    def last_sync_iso(self) -> str:
        fetched = self._data.get("fetched_at", 0.0)
        if not fetched:
            return ""
        from datetime import datetime
        return datetime.fromtimestamp(fetched).isoformat(timespec="seconds")

    def has_data(self) -> bool:
        return bool(self._data.get("cameras") or self._data.get("operators"))
