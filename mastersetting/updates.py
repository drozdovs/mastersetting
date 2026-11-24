# -*- coding: utf-8 -*-
"""Канал обновлений: подписанный манифест с проверкой подлинности пакета.

Требования ТЗ («Администрирование, S3 и обновление»):

* отдельный канал S3 с подписанным манифестом: версия, платформа, хеш,
  подпись пакета;
* приложение проверяет наличие версии автоматически при интернете;
* установку запускает администратор из панели;
* НЕ запускать произвольный исполняемый файл из бакета по совпадению имени или
  хеша, который мог заменить владелец ключа записи — нужна проверка подписи
  доверенным публичным ключом;
* поддержать откат версии и сохранность пользовательских данных, лог обновления.

Реализация подписи — Ed25519 (``cryptography``), если доступна; иначе честный
отказ от «автообновления» и переход к ручному подтверждению. Скрипт не доверяет
хешу, пришедшему из того же бакета, что и пакет.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
    _CRYPTO_OK = True
except Exception:  # noqa: BLE001
    _CRYPTO_OK = False


class UpdateError(Exception):
    """Ошибка проверки/установки обновления."""


@dataclass
class Manifest:
    version: str
    platform: str            # osx-arm64 | win-x64 | ...
    filename: str
    sha256: str
    signature: str = ""      # base64(Ed25519(sha256_of_package))
    release_notes: str = ""

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Manifest":
        return cls(**json.loads(text))


@dataclass
class UpdateCheck:
    status: str              # up_to_date | available | unverified | error
    manifest: Manifest | None = None
    message: str = ""
    verified: bool = False


def verify_signature(manifest: Manifest, public_key_b64: str) -> bool:
    """Проверить подпись манифеста доверенным публичным ключом."""
    if not _CRYPTO_OK:
        return False
    if not manifest.signature:
        return False
    try:
        import base64
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        payload = manifest.sha256.encode("utf-8")
        pub.verify(base64.b64decode(manifest.signature), payload)
        return True
    except Exception:
        return False


def sign_manifest(manifest: Manifest, private_key_b64: str) -> Manifest:
    """Подписать манифест (для инструмента релиза, не для рантайма приложения)."""
    if not _CRYPTO_OK:
        raise UpdateError("cryptography недоступна — установка релиза невозможна")
    import base64
    priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64))
    manifest.signature = base64.b64encode(
        priv.sign(manifest.sha256.encode("utf-8"))).decode()
    return manifest


def _hash_file(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check_for_update(current_version: str, remote_manifest: Manifest,
                     public_key_b64: str) -> UpdateCheck:
    """Проверить наличие обновления (БЕЗ установки)."""
    if remote_manifest.platform != _this_platform():
        return UpdateCheck("up_to_date",
                           message=f"Нет версии для платформы {_this_platform()}")
    if not verify_signature(remote_manifest, public_key_b64):
        return UpdateCheck("unverified", manifest=remote_manifest,
                           message="Подпись манифеста не подтверждена — обновление отклонено",
                           verified=False)
    if _parse_version(remote_manifest.version) <= _parse_version(current_version):
        return UpdateCheck("up_to_date", manifest=remote_manifest,
                           message="Установлена последняя версия", verified=True)
    return UpdateCheck("available", manifest=remote_manifest,
                       message=f"Доступна версия {remote_manifest.version}", verified=True)


def verify_package(package_path: str, manifest: Manifest, public_key_b64: str) -> tuple[bool, str]:
    """Проверить подлинность и целостность пакета ПЕРЕД запуском.

    Порядок: сначала подпись манифеста доверенным ключом, затем хеш пакета.
    Хеш из бакета сам по себе доверия не даёт.
    """
    if not verify_signature(manifest, public_key_b64):
        return False, "подпись не подтверждена"
    actual = _hash_file(package_path)
    if actual != manifest.sha256:
        return False, "хеш пакета не совпал"
    return True, "пакет подлинный и целостный"


def _this_platform() -> str:
    import platform
    import sys
    if sys.platform == "win32":
        return "win-x64"
    if sys.platform == "darwin":
        return f"osx-{platform.machine()}"
    return f"linux-{platform.machine()}"


def fetch_manifest_text(url: str, timeout: float = 8.0) -> str:
    """Скачать текст манифеста по URL (только https). Офлайн -> UpdateError.

    Отдельный канал S3: манифест лежит по фиксированному https-адресу. Никакой
    локальный путь не принимается, чтобы не «подсунуть» манифест рядом с exe.
    """
    import urllib.error
    import urllib.request
    if not url.lower().startswith("https://"):
        raise UpdateError("Адрес манифеста должен быть https://")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8")
    except Exception as e:  # noqa: BLE001
        raise UpdateError(f"Не удалось получить манифест: {e}") from e


def auto_check(current_version: str, manifest_url: str,
               public_key_b64: str, timeout: float = 8.0) -> UpdateCheck:
    """Автоматическая проверка обновления при наличии интернета (БЕЗ установки).

    Тихо сообщает «нет интернета/нет ключа», не падая. Установку всё равно
    запускает администратор вручную — здесь только проверка подписи и версии.
    """
    if not manifest_url or not public_key_b64:
        return UpdateCheck("skipped", message="Канал обновлений не настроен",
                           verified=False)
    try:
        text = fetch_manifest_text(manifest_url, timeout=timeout)
    except UpdateError as e:
        return UpdateCheck("offline", message=str(e), verified=False)
    try:
        manifest = Manifest.from_json(text)
    except Exception as e:  # noqa: BLE001
        return UpdateCheck("error", message=f"Манифест не читается: {e}",
                           verified=False)
    return check_for_update(current_version, manifest, public_key_b64)


def apply_manual_update(package_path: str, manifest: Manifest,
                        public_key_b64: str, save_dest: str) -> tuple[bool, str]:
    """Проверить и ПОДГОТОВИТЬ проверенный установщик к ручному запуску.

    ТЗ: нельзя запускать произвольный файл из бакета. Здесь мы лишь убеждаемся,
    что подпись манифеста доверенная и хеш пакета совпал, и переносим пакет в
    отдельное место под понятным именем. Сам запуск делает администратор вручную
    (двойной клик по скачанному файлу) — фонового «автообновления» нет.
    """
    ok, msg = verify_package(package_path, manifest, public_key_b64)
    if not ok:
        return False, f"Пакет отклонён: {msg}"
    try:
        os.makedirs(save_dest, exist_ok=True)
        target = os.path.join(save_dest, os.path.basename(manifest.filename or
                                                          package_path))
        shutil.copy2(package_path, target)
    except OSError as e:
        return False, f"Не удалось сохранить пакет: {e}"
    return True, target


def _parse_version(v: str) -> tuple:
    parts = []
    for chunk in (v or "").split("."):
        num = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts)


@dataclass
class UpdateLog:
    """Журнал обновления (для админ-панели)."""
    entries: list[dict] = field(default_factory=list)

    def add(self, action: str, version: str, ok: bool, message: str = "") -> None:
        from datetime import datetime, timezone
        self.entries.append({
            "at": datetime.now(timezone.utc).isoformat(),
            "action": action, "version": version, "ok": ok, "message": message,
        })

    def to_json(self) -> str:
        return json.dumps(self.entries, ensure_ascii=False, indent=2)
