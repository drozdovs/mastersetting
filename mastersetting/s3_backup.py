# -*- coding: utf-8 -*-
"""Резервное копирование рабочих данных в S3 (Timeweb) и безопасное восстановление.

Требования ТЗ («Администрирование, S3 и обновление»):

* копируются рабочие данные и конфигурация, НЕ видео с карты и НЕ бинарник;
* быстрые последовательные изменения можно объединять в одну согласованную копию;
* ежедневная копия;
* открытые S3-ключи и пароль администратора НЕ попадают в обычный архив —
  секреты хранятся в системном хранилище;
* проверяются контрольная сумма, полнота, список и дата копий, сетевые ошибки;
* при отсутствии интернета отправка откладывается;
* хранить копии 90 дней;
* восстановление — только из админ-панели, с предварительной локальной копией.

Модуль не импортирует boto3 на уровне пакета, чтобы работал офлайн без
зависимостей. Клиент S3 передаётся снаружи (dependency injection).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

RETENTION_DAYS = 90

# Что НЕ попадает в снимок данных
EXCLUDED_FROM_SNAPSHOT = (
    ".mastersetting/secrets.enc",
    "secrets.enc",
    "catalog.db-wal",
    "catalog.db-shm",
    "MasterSetting.exe",
    "MasterSetting",
)

# Снимок данных не должен включать видео с карты и временные файлы (ТЗ).
MEDIA_EXCLUDED_EXT = (
    ".mp4", ".mxf", ".mts", ".m2ts", ".mov", ".avi", ".mkv", ".wmv",
    ".r3d", ".braw", ".crm", ".mpg", ".mpeg", ".jpg", ".jpeg", ".png",
    ".tif", ".tiff", ".heic",
)
TEMP_EXCLUDED_EXT = (".partial", ".ms-bak", ".tmp", ".crdownload")

# Секретные имена, которые нельзя класть в архив
SECRET_KEYS = ("password_hash", "server_token", "s3_secret", "s3_access_key", "admin_password")


class BackupError(Exception):
    """Ошибка резервного копирования."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _strip_secrets_from_config(obj):
    """Убрать секретные поля из конфига перед упаковкой."""
    if isinstance(obj, dict):
        return {k: _strip_secrets_from_config(v) for k, v in obj.items()
                if k not in SECRET_KEYS}
    if isinstance(obj, list):
        return [_strip_secrets_from_config(x) for x in obj]
    return obj


@dataclass
class SnapshotResult:
    ok: bool
    path: str = ""
    sha256: str = ""
    size: int = 0
    files: int = 0
    message: str = ""
    skipped: list[str] = field(default_factory=list)


def build_snapshot(data_dirs: list[str], out_dir: str,
                   tag: str | None = None) -> SnapshotResult:
    """Собрать согласованный снимок рабочих данных в один tar.gz.

    Пропускает секреты, бинарник приложения и видео. Возвращает **локальный**
    снимок; отправка в S3 — отдельный шаг (может быть отложена офлайн).
    """
    tag = tag or _now_tag()
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    archive = Path(out_dir) / f"ms-snapshot-{tag}.tar.gz"
    manifest: dict = {"created_at": _now_iso(), "files": {}}
    skipped: list[str] = []
    count = 0

    tmp = archive.with_suffix(".tmp")
    with tarfile.open(tmp, "w:gz") as tar:
        for base in data_dirs:
            base_path = Path(base)
            if not base_path.exists():
                continue
            for root, _dirs, files in os.walk(base_path):
                for name in files:
                    full = Path(root) / name
                    rel = os.path.relpath(full, base_path)
                    rel_posix = rel.replace(os.sep, "/")

                    if any(rel_posix.endswith(x) or name == Path(x).name
                           for x in EXCLUDED_FROM_SNAPSHOT):
                        skipped.append(rel_posix)
                        continue                    # Видео/фото с карты и временные файлы в снимок не кладём (ТЗ).
                    low = name.lower()
                    if (low.endswith(MEDIA_EXCLUDED_EXT)
                            or low.endswith(TEMP_EXCLUDED_EXT)):
                        skipped.append(rel_posix)
                        continue
                    # Никогда не кладём секреты
                    if _looks_secret(full, name):
                        skipped.append(rel_posix)
                        # ТЗ: конфигурацию копируем, но БЕЗ секретов. Раньше
                        # config.json просто выбрасывался, и вместе с ним терялась
                        # настройка (например, путь данных). Кладём очищенную копию.
                        if name.lower() == "config.json":
                            clean = _sanitized_config_bytes(full)
                            if clean is not None:
                                arcname = f"{Path(base).name}/{rel_posix}"
                                info = tarfile.TarInfo(arcname)
                                info.size = len(clean)
                                tar.addfile(info, io.BytesIO(clean))
                                manifest["files"][arcname] = {
                                    "size": len(clean),
                                    "sha256": hashlib.sha256(clean).hexdigest(),
                                }
                                count += 1
                        continue

                    arcname = f"{Path(base).name}/{rel_posix}"
                    tar.add(str(full), arcname=arcname)
                    manifest["files"][arcname] = {
                        "size": full.stat().st_size,
                        "sha256": sha256_file(full),
                    }
                    count += 1

        # Манифест кладём внутрь архива
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        info = tarfile.TarInfo("_snapshot_manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))

    os.replace(tmp, archive)
    return SnapshotResult(ok=True, path=str(archive), sha256=sha256_file(archive),
                          size=archive.stat().st_size, files=count,
                          message=f"Снимок собран: {count} файл(ов)",
                          skipped=skipped)


def _looks_secret(path: Path, name: str) -> bool:
    lname = name.lower()
    if lname.endswith(".enc"):
        return True
    if "secret" in lname:
        return True
    # Конфиг с токеном: перезапишем безопасной версией отдельно
    if lname == "config.json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if any(k in data for k in SECRET_KEYS):
                return True  # исключаем оригинал, положим очищенную копию
        except Exception:
            return False
    return False


def _sanitized_config_bytes(path: Path) -> bytes | None:
    """Версия ``config.json`` без секретов (для снимка). None при ошибке чтения."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    clean = _strip_secrets_from_config(data)
    return json.dumps(clean, ensure_ascii=False, indent=2).encode("utf-8")


@dataclass
class UploadResult:
    ok: bool
    message: str
    remote_key: str = ""
    deferred: bool = False
    attempts: int = 1


def verify_snapshot(path: str) -> tuple[bool, str]:
    """Проверить полноту архива: читаемость + совпадение манифеста."""
    try:
        with tarfile.open(path, "r:gz") as tar:
            names = set(tar.getnames())
            if "_snapshot_manifest.json" not in names:
                return False, "в снимке нет манифеста"
            manifest = json.loads(tar.extractfile("_snapshot_manifest.json").read())
            # Проверяем, что все заявленные файлы есть в архиве
            for arc, meta in manifest.get("files", {}).items():
                if arc not in names:
                    return False, f"в архиве нет файла {arc}"
            return True, "снимок полный и читаемый"
    except Exception as e:  # noqa: BLE001
        return False, f"архив повреждён: {e}"


def _safe_extract(tar: tarfile.TarFile, dest: str) -> None:
    """Распаковать без выхода за пределы ``dest`` (защита от zip-slip)."""
    dest_real = os.path.realpath(dest)
    for member in tar.getmembers():
        target = os.path.realpath(os.path.join(dest, member.name))
        if target != dest_real and not target.startswith(dest_real + os.sep):
            raise BackupError(f"Небезопасный путь в архиве: {member.name}")


def restore_snapshot(snapshot_path: str, data_dirs: list[str],
                     pre_restore_dir: str) -> dict:
    """Восстановить данные из снимка БЕЗОПАСНО.

    ТЗ: восстановление — только из админ-панели, с **предварительной локальной
    копией** текущих данных и подтверждением.

    Порядок:
      1. проверить целостность снимка (иначе — отказ);
      2. сделать локальную копию текущих данных в ``pre_restore_dir``;
      3. распаковать снимок в каталог данных.

    Возвращает отчёт: ``{ok, restored_files, pre_restore_backup, warning}``.
    Исключения-секреты из архива не удаляются с диска (в снимке их и нет).
    """
    ok, msg = verify_snapshot(snapshot_path)
    if not ok:
        raise BackupError(f"Копия повреждена: {msg}")

    # 1. Предварительная локальная копия текущих данных
    existing = [d for d in data_dirs if os.path.isdir(d)]
    pre_report = ""
    if existing:
        res = build_snapshot(existing, pre_restore_dir, tag=f"pre-restore-{_now_tag()}")
        if not res.ok:
            raise BackupError("Не удалось создать страховочную копию перед восстановлением")
        pre_report = res.path

    # 2. Распаковка в первый существующий каталог данных
    into = existing[0] if existing else (data_dirs[0] if data_dirs else pre_restore_dir)
    os.makedirs(into, exist_ok=True)
    imported = 0
    with tarfile.open(snapshot_path, "r:gz") as tar:
        _safe_extract(tar, into)
        members = [m for m in tar.getmembers()
                   if m.isfile() and not m.name.endswith("_snapshot_manifest.json")]
        for m in members:
            tar.extract(m, into)
            imported += 1

    return {
        "ok": True,
        "restored_files": imported,
        "into": into,
        "pre_restore_backup": pre_report,
        "warning": ("Секреты (ключи S3, пароль) в снимок не входят — "
                    "введите их заново в админ-панели."),
    }


def cleanup_local_snapshots(out_dir: str, retention_days: int = RETENTION_DAYS) -> list[str]:
    """Удалить локальные снимки старше срока хранения. Возвращает удалённые."""
    removed: list[str] = []
    cutoff = time.time() - retention_days * 86400
    d = Path(out_dir)
    if not d.is_dir():
        return removed
    for f in d.glob("ms-snapshot-*.tar.gz"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed.append(str(f))
        except OSError:
            pass
    return removed


def make_s3_client(endpoint: str, region: str,
                   access_key: str, secret_key: str):
    """Создать клиент S3 (boto3). Импорт ленивый: офлайн без boto3 работает.

    ТЗ: ключи S3 НЕ хранятся в открытом виде — их передаёт вызывающая сторона
    (в приложении — из системного хранилища секретов).
    """
    try:
        import boto3
    except ImportError as e:  # pragma: no cover - зависит от окружения
        raise BackupError(
            "Модуль boto3 не установлен — S3-копии недоступны. "
            "Установите: pip install boto3") from e
    return boto3.session.Session().client(
        "s3",
        endpoint_url=endpoint or None,
        region_name=region or None,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


class BackupManager:
    """Собирает снимки и отправляет их в S3 (может отложить офлайн)."""

    def __init__(self, data_dirs: list[str], local_dir: str, s3_client=None,
                 bucket: str = "", prefix: str = "mastersetting/backups/",
                 seal_seconds: float = 5.0):
        self.data_dirs = data_dirs
        self.local_dir = local_dir
        self.s3 = s3_client
        self.bucket = bucket
        self.prefix = prefix
        # Объединение быстрых изменений: не собирать снимок чаще, чем раз в seal_seconds
        self.seal_seconds = seal_seconds
        self._last_snapshot_at = 0.0

    # ------------------------------------------------------------------
    def snapshot(self, force: bool = False) -> SnapshotResult:
        """Собрать снимок, объединяя быстрые последовательные изменения."""
        now = time.time()
        if not force and (now - self._last_snapshot_at) < self.seal_seconds:
            # Возвращаем последний снимок (изменения объединены)
            existing = sorted(Path(self.local_dir).glob("ms-snapshot-*.tar.gz"))
            if existing:
                last = existing[-1]
                return SnapshotResult(ok=True, path=str(last), sha256=sha256_file(last),
                                      size=last.stat().st_size,
                                      message="Изменения объединены в последний снимок")
        res = build_snapshot(self.data_dirs, self.local_dir)
        if res.ok:
            self._last_snapshot_at = now
        return res

    def upload(self, snapshot: SnapshotResult, max_attempts: int = 3) -> UploadResult:
        """Отправить снимок в S3. Офлайн — откладываем без ошибки «потери»."""
        if self.s3 is None or not self.bucket:
            return UploadResult(ok=False, message="S3 не настроен",
                                deferred=True)
        ok_verify, msg = verify_snapshot(snapshot.path)
        if not ok_verify:
            return UploadResult(ok=False, message=f"Не отправляю повреждённый снимок: {msg}")

        key = f"{self.prefix}{Path(snapshot.path).name}"
        last_err = ""
        for attempt in range(1, max_attempts + 1):
            try:
                self.s3.upload_file(snapshot.path, self.bucket, key)
                return UploadResult(ok=True, message="Снимок отправлен", remote_key=key,
                                    attempts=attempt)
            except Exception as e:  # noqa: BLE001
                last_err = str(e)
                time.sleep(min(2 ** attempt, 10))
        return UploadResult(ok=False, message=f"Сеть недоступна: {last_err}",
                            remote_key=key, deferred=True, attempts=max_attempts)

    def list_remote(self) -> list[dict]:
        """Список и даты копий в S3."""
        if self.s3 is None or not self.bucket:
            return []
        try:
            resp = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=self.prefix)
            return [{"key": o["Key"], "size": o["Size"],
                     "date": o["LastModified"].isoformat()}
                    for o in resp.get("Contents", [])]
        except Exception:
            return []

    def restore(self, remote_key: str, restore_dir: str) -> str:
        """Скачать и распаковать копию. Перед этим — локальная копия текущего (в UI)."""
        if self.s3 is None or not self.bucket:
            raise BackupError("S3 не настроен")
        Path(restore_dir).mkdir(parents=True, exist_ok=True)
        local = Path(restore_dir) / Path(remote_key).name
        self.s3.download_file(self.bucket, remote_key, str(local))
        ok, msg = verify_snapshot(str(local))
        if not ok:
            raise BackupError(f"Копия повреждена: {msg}")
        with tarfile.open(local, "r:gz") as tar:
            _safe_extract(tar, restore_dir)
            tar.extractall(restore_dir)
        return str(local)

    def pending_uploads(self) -> list[str]:
        """Локальные снимки, ещё не подтверждённые в S3 (отложенная отправка)."""
        if self.s3 is None or not self.bucket:
            return []
        remote = {o["key"].split("/")[-1] for o in self.list_remote()}
        pending = []
        for p in sorted(Path(self.local_dir).glob("ms-snapshot-*.tar.gz")):
            if p.name not in remote:
                pending.append(str(p))
        return pending

    def flush_pending(self, max_attempts: int = 1) -> dict:
        """Отправить отложенные снимки, когда интернет вернулся (ТЗ).

        Отправляем по возрастанию времени; повреждённые — пропускаем, чтобы
        не «застрять» на одном файле.
        """
        pending = self.pending_uploads()
        sent, failed, skipped = [], [], []
        for path in pending:
            ok, msg = verify_snapshot(path)
            if not ok:
                skipped.append(Path(path).name)
                continue
            res = self.upload(SnapshotResult(ok=True, path=path,
                                             sha256=sha256_file(path),
                                             size=os.path.getsize(path)),
                              max_attempts=max_attempts)
            if res.ok:
                sent.append(Path(path).name)
            else:
                # Сеть всё ещё недоступна — останавливаемся, не спамим.
                failed.append(Path(path).name)
                break
        return {"sent": sent, "failed": failed, "skipped": skipped,
                "pending_left": len(self.pending_uploads())}

    def trial_restore(self, remote_key: str, scratch_dir: str) -> dict:
        """Пробное восстановление: скачать и распаковать в отдельный каталог.

        ТЗ: проверяем восстановимость копии, НЕ трогая рабочие данные.
        """
        if self.s3 is None or not self.bucket:
            raise BackupError("S3 не настроен")
        scratch = Path(scratch_dir)
        scratch.mkdir(parents=True, exist_ok=True)
        local = scratch / Path(remote_key).name
        self.s3.download_file(self.bucket, remote_key, str(local))
        ok, msg = verify_snapshot(str(local))
        if not ok:
            return {"ok": False, "message": f"Копия повреждена: {msg}"}
        unpack = scratch / "_unpack"
        unpack.mkdir(parents=True, exist_ok=True)
        with tarfile.open(local, "r:gz") as tar:
            _safe_extract(tar, str(unpack))
            tar.extractall(unpack)
        restored = sum(len(fs) for _r, _d, fs in os.walk(unpack))
        return {"ok": True, "message": f"Копия восстановима, файлов: {restored}",
                "restored_files": restored, "path": str(unpack)}
