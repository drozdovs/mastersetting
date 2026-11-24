# -*- coding: utf-8 -*-
"""Правила определения и копирования ТОЛЬКО файлов настроек.

Замена дефекта версии 1.9, где копировался почти весь корень карты. Здесь:

* для **подтверждённой** модели действует точное правило (какие пути и файлы
  относятся к настройкам);
* если проверенного правила нет — предлагается импорт из выбранной папки с
  **предварительным просмотром**, при этом видео, фото и неизвестные крупные
  файлы запрещены;
* никогда не делаем вывод о формате только по расширению;
* не следуем символическим ссылкам за пределы носителя/папки.

ВАЖНО: правила FX3/FX3A пока помечены ``confirmed=False`` — точные пути с
реальной карты ещё не подтверждены пользователем (см. docs/FX3_PAIR_GATEWAY.md).
До подтверждения движок работает в режиме «импорт из папки с просмотром» и НЕ
называет такой импорт проверенным форматом камеры.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Сигнатура начала файла настроек Sony (используется в рабочих скриптах load.sh/.ps1)
SONY_SETTINGS_MAGIC = b"SONY0"

# Медиа и прочие файлы, которые НИКОГДА не являются настройками
MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".heic",
    ".mp4", ".avi", ".mov", ".mkv", ".wmv", ".m2ts", ".mts", ".mxf",
    ".r3d", ".braw", ".crm", ".mpg", ".mpeg", ".wav", ".mp3",
    ".xml",  # служебные индексы Sony (например, SONYCARD.IND рядом, но xml-индексы не настройки)
}

# Имена, которые не являются настройками
NEVER_SETTINGS_NAMES = {"LASTCLIP.TXT", "SONYCARD.IND", ".DS_Store"}

# Разумный предел для файла настроек: больше — почти наверняка не то
MAX_SETTINGS_FILE_BYTES = 32 * 1024 * 1024  # 32 МБ

# Неизвестные крупные файлы запрещаем в «папочном» импорте
UNKNOWN_LARGE_BYTES = 8 * 1024 * 1024  # 8 МБ


@dataclass
class Candidate:
    """Кандидат на файл настроек, найденный при просмотре."""
    abs_path: str
    rel_path: str          # относительно корня просмотра или носителя
    size: int
    accepted: bool
    reason: str            # почему принят/отклонён


@dataclass
class DiscoveryResult:
    """Результат просмотра папки/носителя."""
    root: str
    candidates: list[Candidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> list[Candidate]:
        return [c for c in self.candidates if c.accepted]

    @property
    def rejected(self) -> list[Candidate]:
        return [c for c in self.candidates if not c.accepted]


# ---------------------------------------------------------------------------
# Правила по моделям
# ---------------------------------------------------------------------------

@dataclass
class SettingsRule:
    """Правило модели: как выглядит её набор настроек на носителе."""
    family: str                 # напр. "SonyFX3"
    confirmed: bool             # подтверждено ли на реальной карте
    # Точные относительные папки, где лежат настройки (если подтверждено)
    settings_dirs: tuple[str, ...] = ()
    # Как узнать файл настроек (сигнатура/расширение)
    magic: bytes = b""
    extensions: tuple[str, ...] = ()
    note: str = ""


# Семейство FX3/FX3A. Пути пока НЕ подтверждены — правила выключены (confirmed=False).
# После снятия реальных путей с карты: заполнить settings_dirs и включить confirmed.
RULES: list[SettingsRule] = [
    SettingsRule(
        family="SonyFX3",
        confirmed=False,
        settings_dirs=(),
        magic=SONY_SETTINGS_MAGIC,
        extensions=(".dat",),
        note="Ожидаемые пути ждут подтверждения с реальной карты",
    ),
    SettingsRule(
        family="SonyFX3A",
        confirmed=False,
        settings_dirs=(),
        magic=SONY_SETTINGS_MAGIC,
        extensions=(".dat",),
        note="Ожидаемые пути ждут подтверждения с реальной карты",
    ),
]


def rule_for(family: str) -> SettingsRule | None:
    fam = (family or "").strip().lower()
    for rule in RULES:
        if rule.family.lower() == fam:
            return rule
    return None


# ---------------------------------------------------------------------------
# Проверка одного файла
# ---------------------------------------------------------------------------

def looks_like_settings_file(path: str) -> bool:
    """Файл похож на настройки Sony по сигнатуре ``SONY0`` и разумному размеру.

    Расширение само по себе НЕ является доказательством.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    if size <= 0 or size > MAX_SETTINGS_FILE_BYTES:
        return False
    try:
        with open(path, "rb") as f:
            head = f.read(len(SONY_SETTINGS_MAGIC))
    except OSError:
        return False
    return head == SONY_SETTINGS_MAGIC


def detect_source_model(path: str) -> str:
    """Извлечь исходную модель из заголовка файла настроек Sony.

    Реальные образцы начинаются с ``SONY0ILME-FX3`` / ``SONY0ILME-FX3A``: сразу
    после сигнатуры идёт строка модели. Эта модель — доказательство с самого
    файла, а не выбор оператора в интерфейсе (ТЗ: «исходная модель»). Версия
    прошивки в этих образцах не хранится, поэтому здесь её не выдумываем.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(64)
    except OSError:
        return ""
    if not head.startswith(SONY_SETTINGS_MAGIC):
        return ""
    tail = head[len(SONY_SETTINGS_MAGIC):]
    # Модель — это печатаемые символы до первого непечатаемого байта.
    model = bytearray()
    for b in tail:
        if 0x20 <= b < 0x7f:
            model.append(b)
        else:
            break
    return model.decode("ascii", errors="ignore").strip()


def _is_inside(path: str, root: str) -> bool:
    """Путь (после разрешения ссылок) остаётся внутри корня."""
    try:
        real = os.path.realpath(path)
        real_root = os.path.realpath(root)
        return os.path.commonpath([real, real_root]) == real_root
    except (ValueError, OSError):
        return False


# ---------------------------------------------------------------------------
# Просмотр папки (безопасный, без следования ссылкам наружу)
# ---------------------------------------------------------------------------

def discover_in_folder(root: str) -> DiscoveryResult:
    """Собрать кандидатов-файлы настроек внутри ``root`` с причинами.

    Правила:
    * символические ссылки, ведущие за пределы ``root``, игнорируются;
    * медиа и служебные файлы отклоняются;
    * неизвестные крупные файлы отклоняются (защита от видео без расширения);
    * файлы с сигнатурой ``SONY0`` принимаются.
    """
    result = DiscoveryResult(root=root)
    if not root or not os.path.isdir(root):
        result.warnings.append(f"Папка не найдена: {root}")
        return result

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Не заходим в симлинк-папки, ведущие наружу
        kept = []
        for d in dirnames:
            full = os.path.join(dirpath, d)
            if os.path.islink(full) and not _is_inside(full, root):
                result.warnings.append(f"Пропущена ссылка наружу: {full}")
                continue
            kept.append(d)
        dirnames[:] = kept

        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")

            if os.path.islink(full):
                if not _is_inside(full, root):
                    result.candidates.append(Candidate(
                        full, rel, 0, False, "символическая ссылка наружу"))
                    continue

            try:
                size = os.path.getsize(full)
            except OSError:
                result.candidates.append(Candidate(full, rel, 0, False, "нет доступа"))
                continue

            ext = os.path.splitext(name)[1].lower()
            upper = name.upper()

            if upper in NEVER_SETTINGS_NAMES:
                result.candidates.append(Candidate(full, rel, size, False, "служебный файл"))
                continue
            if ext in MEDIA_EXTENSIONS:
                result.candidates.append(Candidate(full, rel, size, False, "медиа/служебный формат"))
                continue

            if looks_like_settings_file(full):
                result.candidates.append(Candidate(full, rel, size, True, "сигнатура SONY0"))
                continue

            if size > UNKNOWN_LARGE_BYTES:
                result.candidates.append(Candidate(
                    full, rel, size, False, "неизвестный крупный файл"))
                continue

            result.candidates.append(Candidate(full, rel, size, False, "нет сигнатуры настроек"))

    return result


def settings_files_map(result: DiscoveryResult, root_prefix: str = "") -> dict[str, str]:
    """Словарь ``{rel_путь_в_наборе: abs_источник}`` из принятых кандидатов.

    ``root_prefix`` — необязательный префикс относительного пути (например,
    ``PRIVATE/SONY/SETTING/FX3/CAMSET``), если правила модели подтверждены.
    """
    out: dict[str, str] = {}
    for c in result.accepted:
        rel = f"{root_prefix.rstrip('/')}/{c.rel_path}" if root_prefix else c.rel_path
        out[rel] = c.abs_path
    return out
