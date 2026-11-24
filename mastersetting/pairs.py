# -*- coding: utf-8 -*-
"""Именованные пары Sony FX3 / FX3A.

По ТЗ пара содержит ЯВНО выбранную версию FX3 и ЯВНО выбранную версию FX3A.
Версия не должна незаметно «уплывать» на самую новую. Пара может быть неполной.

Хранение — JSON рядом с каталогом приложения. Проверки:

* обе версии должны существовать в библиотеке;
* семейство модели версии должно соответствовать слоту FX3/FX3A;
* при записи пары, если одной части нет, разрешаем записать имеющуюся с
  предупреждением (решение принимает вызывающий код/UI).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .versioning import VersionStore

# Слоты пары
SLOT_FX3 = "FX3"
SLOT_FX3A = "FX3A"


class PairError(Exception):
    """Ошибка работы с парами (понятный пользователю текст)."""


@dataclass
class PresetPair:
    """Именованная пара версий FX3 + FX3A (любая часть может отсутствовать)."""
    name: str
    operator: str
    fx3_version_id: str = ""       # явно выбранная версия (модель SonyFX3)
    fx3a_version_id: str = ""      # явно выбранная версия (модель SonyFX3A)
    fx3_camera: str = "SonyFX3"
    fx3a_camera: str = "SonyFX3A"
    fx3_preset: str = ""
    fx3a_preset: str = ""
    note: str = ""

    @property
    def is_complete(self) -> bool:
        return bool(self.fx3_version_id and self.fx3a_version_id)

    @property
    def is_empty(self) -> bool:
        return not (self.fx3_version_id or self.fx3a_version_id)

    def missing_slots(self) -> list[str]:
        out = []
        if not self.fx3_version_id:
            out.append(SLOT_FX3)
        if not self.fx3a_version_id:
            out.append(SLOT_FX3A)
        return out


def _pairs_file(app_data_dir: str) -> Path:
    return Path(app_data_dir) / "pairs.json"


class PairStore:
    """Хранилище именованных пар."""

    def __init__(self, app_data_dir: str, version_store: VersionStore):
        self.path = _pairs_file(app_data_dir)
        self.version_store = version_store
        self._pairs: dict[str, PresetPair] = {}
        self._load()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for item in data.get("pairs", []):
                pair = PresetPair(**item)
                self._pairs[self._key(pair.name, pair.operator)] = pair
        except Exception:
            self._pairs = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"pairs": [asdict(p) for p in self._pairs.values()]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    @staticmethod
    def _key(name: str, operator: str) -> str:
        # Сравнение имён без учёта регистра
        return f"{operator.strip().lower()}::{name.strip().lower()}"

    # ------------------------------------------------------------------
    def list_pairs(self, operator: str | None = None) -> list[PresetPair]:
        items = self._pairs.values()
        if operator is not None:
            op = operator.strip().lower()
            items = [p for p in items if p.operator.strip().lower() == op]
        return sorted(items, key=lambda p: (p.operator.lower(), p.name.lower()))

    def get(self, name: str, operator: str) -> PresetPair | None:
        return self._pairs.get(self._key(name, operator))

    def upsert(self, pair: PresetPair) -> PresetPair:
        """Создать/обновить пару с проверкой корректности версий."""
        self._validate_slot(pair, SLOT_FX3, pair.fx3_camera, pair.fx3_version_id)
        self._validate_slot(pair, SLOT_FX3A, pair.fx3a_camera, pair.fx3a_version_id)
        self._pairs[self._key(pair.name, pair.operator)] = pair
        self._save()
        return pair

    def delete(self, name: str, operator: str) -> None:
        key = self._key(name, operator)
        if key not in self._pairs:
            raise PairError("Пара не найдена")
        del self._pairs[key]
        self._save()

    def _validate_slot(self, pair: PresetPair, slot: str, camera: str,
                       version_id: str) -> None:
        """Версия, если указана, должна существовать и быть нужного семейства."""
        if not version_id:
            return  # неполная пара допустима
        # Найти версию по id среди пресетов камеры оператора
        found = None
        for preset in self.version_store.list_presets(pair.operator, camera):
            for v in self.version_store.list_versions(pair.operator, camera, preset):
                if v.version_id == version_id:
                    found = v
                    break
            if found:
                break
        if found is None:
            raise PairError(f"Версия {version_id} для {camera} не найдена в библиотеке")

        # Слот FX3A должен ссылаться на FX3A-семейство, и наоборот
        if slot == SLOT_FX3 and not self._is_family(camera, "FX3"):
            raise PairError("Слот FX3 должен ссылаться на модель семейства FX3")
        if slot == SLOT_FX3A and not self._is_family(camera, "FX3A"):
            raise PairError("Слот FX3A должен ссылаться на модель семейства FX3A")

    @staticmethod
    def _is_family(camera: str, family: str) -> bool:
        cam = (camera or "").lower()
        if family == "FX3A":
            return "fx3a" in cam
        # FX3, но НЕ FX3A
        return "fx3" in cam and "fx3a" not in cam
