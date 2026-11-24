# -*- coding: utf-8 -*-
"""Административная безопасность: пароль, блокировка перебора, хранилище секретов.

Требования ТЗ:

* пароль администратора с безопасным хешированием (PBKDF2-HMAC-SHA256, соль);
* блокировка перебора (счётчик неудач + временная блокировка);
* отсутствие пароля в исходниках и логах;
* секреты (например, ключи S3 и пароль) — в системном хранилище, а не в открытом
  виде в обычном архиве.

Системное хранилище реализовано абстрактно: на macOS используется Keychain через
``security``, на Windows — DPAPI через ``ctypes``, иначе — файл с ограничением прав
(с честным предупреждением, что это не так надёжно).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PBKDF2_ITERATIONS = 200_000
SALT_BYTES = 16

# Параметры блокировки перебора
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 300

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"


class AdminAuthError(Exception):
    """Ошибка аутентификации администратора."""


class RateLimited(AdminAuthError):
    """Слишком много неудачных попыток."""


# ---------------------------------------------------------------------------
# Хеширование пароля
# ---------------------------------------------------------------------------

def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Вернуть строку ``pbkdf2_sha256$iters$salt_b64$hash_b64``."""
    if not password:
        raise AdminAuthError("Пустой пароль недопустим")
    salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    """Проверить пароль по сохранённому хешу (сравнение постоянного времени)."""
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iters))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Хранилище секретов
# ---------------------------------------------------------------------------

class SecretStore:
    """Абстракция над системным хранилищем секретов."""

    SERVICE = "MasterSetting"

    def __init__(self, fallback_path: str | None = None):
        self.fallback_path = fallback_path or str(
            Path.home() / ".mastersetting" / "secrets.enc")
        # Явное переопределение (тесты и развёртывание): не трогаем системное
        # хранилище, если задан MS_SECRETS_FILE.
        self._force_file = bool(os.environ.get("MS_SECRETS_FILE"))
        if os.environ.get("MS_SECRETS_FILE"):
            self.fallback_path = os.environ["MS_SECRETS_FILE"]

    def set(self, key: str, value: str) -> None:
        if self._force_file:
            self._file_set(key, value)
        elif IS_MACOS:
            self._mac_set(key, value)
        elif IS_WINDOWS:
            self._win_set(key, value)
        else:
            self._file_set(key, value)

    def get(self, key: str) -> str | None:
        if self._force_file:
            return self._file_get(key)
        if IS_MACOS:
            return self._mac_get(key)
        if IS_WINDOWS:
            return self._win_get(key)
        return self._file_get(key)

    def delete(self, key: str) -> None:
        if self._force_file:
            data = self._file_read()
            data.pop(key, None)
            self._file_write(data)
        elif IS_MACOS:
            subprocess.run(["security", "delete-generic-password",
                            "-s", self.SERVICE, "-a", key],
                           capture_output=True, check=False)
        elif IS_WINDOWS:
            data = self._file_read()
            data.pop(key, None)
            self._file_write(data)
        else:
            data = self._file_read()
            data.pop(key, None)
            self._file_write(data)

    # --- macOS Keychain ---
    def _mac_set(self, key: str, value: str) -> None:
        subprocess.run(["security", "add-generic-password",
                        "-s", self.SERVICE, "-a", key, "-w", value, "-U"],
                       capture_output=True, check=True)

    def _mac_get(self, key: str) -> str | None:
        res = subprocess.run(["security", "find-generic-password",
                              "-s", self.SERVICE, "-a", key, "-w"],
                             capture_output=True, text=True)
        if res.returncode != 0:
            return None
        return res.stdout.strip() or None

    # --- Windows DPAPI ---
    def _win_set(self, key: str, value: str) -> None:
        import ctypes
        import ctypes.wintypes as wt

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wt.DWORD),
                        ("pbData", ctypes.POINTER(ctypes.c_char))]

        raw = value.encode("utf-8")
        blob_in = DATA_BLOB(len(raw), ctypes.cast(ctypes.create_string_buffer(raw),
                                                  ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        if not ctypes.windll.crypt32.CryptProtectData(
                ctypes.byref(blob_in), None, None, None, None, 0,
                ctypes.byref(blob_out)):
            raise AdminAuthError("DPAPI: не удалось зашифровать секрет")
        try:
            enc = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            data = self._file_read()
            data[key] = base64.b64encode(enc).decode()
            self._file_write(data)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)

    def _win_get(self, key: str) -> str | None:
        import ctypes
        import ctypes.wintypes as wt

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wt.DWORD),
                        ("pbData", ctypes.POINTER(ctypes.c_char))]

        data = self._file_read()
        if key not in data:
            return None
        enc = base64.b64decode(data[key])
        blob_in = DATA_BLOB(len(enc), ctypes.cast(ctypes.create_string_buffer(enc),
                                                  ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(
                ctypes.byref(blob_in), None, None, None, None, 0,
                ctypes.byref(blob_out)):
            return None
        try:
            raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            return raw.decode("utf-8")
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)

    # --- Файл (fallback: Linux/без системного хранилища) ---
    def _file_read(self) -> dict:
        p = Path(self.fallback_path)
        if not p.is_file():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _file_write(self, data: dict) -> None:
        p = Path(self.fallback_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass

    def _file_set(self, key: str, value: str) -> None:
        data = self._file_read()
        data[key] = base64.b64encode(value.encode("utf-8")).decode()
        self._file_write(data)

    def _file_get(self, key: str) -> str | None:
        data = self._file_read()
        if key not in data:
            return None
        try:
            return base64.b64decode(data[key]).decode("utf-8")
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Аутентификация администратора с блокировкой перебора
# ---------------------------------------------------------------------------

@dataclass
class _AttemptState:
    failed: int = 0
    locked_until: float = 0.0


class AdminAuth:
    """Проверка пароля администратора с защитой от перебора."""

    def __init__(self, state_path: str):
        self.state_path = state_path
        self._state = self._load()

    def _load(self) -> _AttemptState:
        p = Path(self.state_path)
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return _AttemptState(int(data.get("failed", 0)),
                                     float(data.get("locked_until", 0.0)))
            except Exception:
                pass
        return _AttemptState()

    def _save(self) -> None:
        p = Path(self.state_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"failed": self._state.failed,
                                 "locked_until": self._state.locked_until}),
                     encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass

    def locked_for(self) -> float:
        """Сколько секунд осталось до разблокировки (0 — не заблокировано)."""
        remain = self._state.locked_until - time.time()
        return max(0.0, remain)

    def try_login(self, password: str, password_hash: str) -> bool:
        """Проверить пароль. Бросает ``RateLimited`` при активной блокировке."""
        if self.locked_for() > 0:
            raise RateLimited(
                f"Слишком много попыток. Подождите {int(self.locked_for())} с.")

        if verify_password(password, password_hash):
            self._state = _AttemptState()
            self._save()
            return True

        self._state.failed += 1
        if self._state.failed >= MAX_FAILED_ATTEMPTS:
            self._state.locked_until = time.time() + LOCKOUT_SECONDS
            self._state.failed = 0
        self._save()
        return False

    def set_password(self, password: str, secrets_store: SecretStore) -> str:
        """Задать пароль: хеш возвращается для хранения в конфиге (НЕ сам пароль)."""
        h = hash_password(password)
        # Сам пароль не храним вообще; хеш — в вызывающем месте.
        return h
