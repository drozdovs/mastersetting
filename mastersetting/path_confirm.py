# -*- coding: utf-8 -*-
"""Подтверждение нативных путей FX3/FX3A по образцам с реальной карты.

Шлюз ТЗ п.2: пока пути не подтверждены образцами, парная запись ВЫКЛЮЧЕНА и
программа честно об этом говорит. Подтверждение хранится отдельным файлом
(по умолчанию ``app_data_dir()/fx3_paths_confirmed.json``) и создаётся только
командой ``cli.py confirm-fx3-paths`` — вручную, по результатам ``inspect``.

Файл можно переопределить переменной окружения ``MS_FX3_CONFIRM_FILE``
(используется в тестах, чтобы не трогать реальное состояние пользователя).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


class PathConfirmError(Exception):
    """Ошибка чтения/записи подтверждения путей."""


def _confirm_file() -> Path:
    env = os.environ.get("MS_FX3_CONFIRM_FILE")
    if env:
        return Path(env)
    try:
        from .config import app_data_dir
        return Path(app_data_dir()) / "fx3_paths_confirmed.json"
    except Exception:
        return Path.home() / ".mastersetting" / "fx3_paths_confirmed.json"


@dataclass
class PathConfirmation:
    """Подтверждённые пути для одного семейства."""
    family: str
    settings_dirs: list[str] = field(default_factory=list)
    sample: str = ""            # что именно смотрели (путь/описание образца)
    confirmed_at: str = ""
    confirmed_by: str = "operator"


def load_confirmation() -> dict[str, PathConfirmation]:
    """Прочитать подтверждения. Некорректный/отсутствующий файл -> пустой словарь."""
    path = _confirm_file()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, PathConfirmation] = {}
    for item in data.get("confirmed", []):
        try:
            conf = PathConfirmation(**item)
        except Exception:
            continue
        if conf.family and conf.settings_dirs:
            out[conf.family] = conf
    return out


def save_confirmation(family: str, settings_dirs: list[str], sample: str = "",
                      confirmed_by: str = "operator") -> PathConfirmation:
    """Записать подтверждение путей для семейства (непустые относительные пути)."""
    clean = [d.strip().strip("/") for d in settings_dirs if d and d.strip()]
    clean = [d for d in clean if d and not d.startswith("/") and ".." not in d.split("/")]
    if not family:
        raise PathConfirmError("Не указано семейство камеры")
    if not clean:
        raise PathConfirmError("Нет ни одной папки настроек для подтверждения")

    data = load_confirmation()
    data[family] = PathConfirmation(
        family=family,
        settings_dirs=sorted(set(clean)),
        sample=sample,
        confirmed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        confirmed_by=confirmed_by,
    )
    path = _confirm_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"confirmed": [vars(c) for c in data.values()]}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, path)
    return data[family]


def is_confirmed(family: str) -> bool:
    conf = load_confirmation().get(family)
    return bool(conf and conf.settings_dirs)


def apply_to_rules() -> list[str]:
    """Наложить подтверждения на ``settings_rules.RULES`` (argless, для CLI/UI).

    Возвращает список семейств, для которых правила реально включены.
    """
    from . import settings_rules as sr

    enabled: list[str] = []
    for family, conf in load_confirmation().items():
        rule = sr.rule_for(family)
        if rule is None:
            continue
        rule.settings_dirs = tuple(conf.settings_dirs)
        rule.confirmed = True
        enabled.append(family)
    return enabled
