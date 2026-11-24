# -*- coding: utf-8 -*-
"""Контроллеры операций для UI — БЕЗ tkinter.

Вся логика, которую вызывает интерфейс, собрана здесь, чтобы её можно было
тестировать headless и переиспользовать из CLI. GUI-слой (``agent.app``) только
рисует и вызывает эти методы, а тяжёлые операции запускает в фоновом потоке,
возвращая результат в главный поток через ``after``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from mastersetting.catalog import Catalog
from mastersetting.config import Config, app_data_dir, legacy_base_path
from mastersetting.library import PresetLibrary, SavePlan
from mastersetting.pairs import PairStore, PresetPair
from mastersetting.platform import get_removable_drives, is_system_path
from mastersetting.safe_write import WriteReport
from mastersetting.versioning import ImportReport, PresetVersion


@dataclass
class CardInfo:
    ok: bool
    path: str = ""
    label: str = ""
    error: str = ""


@dataclass
class RecentItem:
    operator: str
    camera: str
    preset: str
    version_id: str
    created_at: str
    files: int


class AppController:
    """Единая точка входа для UI."""

    def __init__(self, config: Config | None = None):
        self.config = config or Config.load()
        self.catalog = Catalog(config=self.config)
        self.library = PresetLibrary(base_path=self.config.base_path)
        self.pairs = PairStore(app_data_dir=str(app_data_dir()),
                               version_store=self.library.store)
        # Шлюз ТЗ п.2: если пути FX3/FX3A подтверждены ранее, включаем их при
        # старте, чтобы UI честно отражал доступность парной записи.
        try:
            from mastersetting.path_confirm import apply_to_rules
            apply_to_rules()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Носители
    # ------------------------------------------------------------------
    def list_cards(self) -> list[str]:
        """Все съёмные носители. Выбор — за оператором (ТЗ: не заставлять вынимать)."""
        return list(get_removable_drives(self.config.removable_drive_start))

    def check_card_folder(self, path: str) -> tuple[bool, str]:
        """Проверить папку, выбранную оператором вручную как карту (ТЗ).

        Запрещаем системный диск, корень тома и каталог приложения — писать
        туда настройки нельзя. Возвращает ``(можно, сообщение)``.
        """
        if not path or not os.path.isdir(path):
            return False, "Папка не найдена. Выберите папку с настройками."
        if is_system_path(path):
            return False, ("Это системный диск или папка приложения — "
                           "выбрать её как карту нельзя.")
        # Пробуем записать и убрать служебный файл: карта может быть под защитой.
        import tempfile
        try:
            with tempfile.NamedTemporaryFile(dir=path, prefix=".ms-check-",
                                             delete=True):
                pass
        except OSError as e:
            return False, f"В эту папку нельзя писать: {e}"
        name = os.path.basename(path.rstrip(os.sep)) or path
        return True, f"Папка выбрана вручную: {name}"

    # ------------------------------------------------------------------
    # Сохранить с карты
    # ------------------------------------------------------------------
    def plan_save(self, camera_family: str, media_root: str) -> SavePlan:
        return self.library.plan_from_media(camera_family, media_root)

    def save_from_card(self, operator: str, camera: str, preset: str,
                       media_root: str, plan: SavePlan | None = None,
                       progress=None, should_cancel=None) -> ImportReport:
        self.catalog.add_operator(operator)
        self.catalog.add_camera(camera)
        rep = self.library.save_from_media(
            operator, camera, preset, media_root, plan=plan,
            progress=progress, should_cancel=should_cancel)
        self.catalog.log_event("save", "ok" if rep.ok else "error",
                               operator, camera, preset,
                               drive=media_root, message=rep.message,
                               bytes_=rep.bytes_, files=rep.files)
        if rep.ok:
            # ТЗ: копия рабочих данных после изменений (быстрые подряд — одной).
            self.auto_backup("after_save")
        return rep

    # ------------------------------------------------------------------
    # Записать на карту
    # ------------------------------------------------------------------
    def preview_write(self, version: PresetVersion, card_root: str) -> WriteReport:
        return self.library.preview_write(version, card_root)

    def write_to_card(self, version: PresetVersion, card_root: str,
                      progress=None, should_cancel=None) -> WriteReport:
        rep = self.library.write_version_to_card(
            version, card_root, progress=progress, should_cancel=should_cancel)
        self.catalog.log_event(
            "load", "ok" if rep.ok else "error",
            version.operator, version.camera, version.preset,
            drive=card_root, message=rep.message,
            bytes_=rep.bytes_, files=len(rep.written))
        return rep
    def verify_on_card(self, version: PresetVersion, card_root: str) -> list[str]:
        return self.library.verify_version_on_card(version, card_root)

    # ------------------------------------------------------------------
    # Пары FX3/FX3A
    # ------------------------------------------------------------------
    def pair_write_available(self) -> bool:
        """Можно ли включать парную запись (шлюз путей подтверждён)."""
        return self.library.pair_write_available()

    def save_pair(self, name: str, operator: str, fx3_version_id: str = "",
                  fx3a_version_id: str = "") -> PresetPair:
        """Создать/обновить именованную пару (версии выбираются явно)."""
        pair = PresetPair(name=name, operator=operator,
                          fx3_version_id=fx3_version_id,
                          fx3a_version_id=fx3a_version_id)
        return self.pairs.upsert(pair)

    def preview_pair_write(self, pair: PresetPair, card_root: str) -> WriteReport:
        fx3 = self._find_version(pair.operator, "SonyFX3", pair.fx3_version_id)
        fx3a = self._find_version(pair.operator, "SonyFX3A", pair.fx3a_version_id)
        return self.library.preview_pair_write(fx3, fx3a, card_root)

    def write_pair_to_card(self, pair: PresetPair, card_root: str,
                           should_cancel=None) -> WriteReport:
        """Записать пару безопасно. Отказ при конфликте путей; предупреждение —
        если пара неполная (ТЗ разрешает записать имеющуюся часть)."""
        fx3 = self._find_version(pair.operator, "SonyFX3", pair.fx3_version_id)
        fx3a = self._find_version(pair.operator, "SonyFX3A", pair.fx3a_version_id)
        rep = self.library.write_pair_to_card(fx3, fx3a, card_root,
                                              should_cancel=should_cancel)
        self.catalog.log_event("load", "ok" if rep.ok else "error",
                              pair.operator, "FX3+FX3A", pair.name,
                              message=rep.message, files=len(rep.written))
        return rep

    def _find_version(self, operator: str, camera: str,
                      version_id: str) -> PresetVersion | None:
        if not version_id:
            return None
        for preset in self.library.store.list_presets(operator, camera):
            for v in self.library.store.list_versions(operator, camera, preset):
                if v.version_id == version_id:
                    return v
        return None

    def iter_family_versions(self, operator: str, family: str):
        """Обойти (камера, набор, version_id) для семейства FX3 или FX3A."""
        for cam in self.list_cameras():
            low = cam.lower()
            is_fx3a = "fx3a" in low
            is_fx3 = "fx3" in low and not is_fx3a
            if (family == "FX3A" and is_fx3a) or (family == "FX3" and is_fx3):
                for preset in self.list_presets(operator, cam):
                    for v in self.list_versions(operator, cam, preset):
                        yield cam, preset, v.version_id

    def delete_preset(self, operator: str, camera: str, preset: str,
                      confirm_versions: int) -> int:
        """Удалить пресет (окончательно). Пишет в журнал операций."""
        count = self.library.delete_preset(operator, camera, preset, confirm_versions)
        self.catalog.log_event("delete", "ok", operator, camera, preset,
                               message=f"удалено версий: {count}", files=count)
        self.auto_backup("after_delete")
        return count

    def export_version(self, version: PresetVersion, dest_dir: str) -> str:
        """Экспорт конкретной версии без изменения библиотеки. Пишет в журнал."""
        path = self.library.export_version(version, dest_dir)
        self.catalog.log_event("export", "ok", version.operator, version.camera,
                               version.preset, message=f"экспорт в {dest_dir}",
                               files=version.file_count)
        return path

    def recent_events(self, limit: int = 50) -> list[dict]:
        """Журнал операций для админ-панели."""
        return self.catalog.list_events(limit=limit)

    # ------------------------------------------------------------------
    # Администрирование: пароль, резервные копии, восстановление
    # ------------------------------------------------------------------
    def _auth(self):
        from mastersetting.admin_auth import AdminAuth
        return AdminAuth(state_path=str(app_data_dir() / "admin_state.json"))

    def password_hash(self) -> str:
        """Хеш пароля администратора (пусто — пароль ещё не задан)."""
        try:
            return self._secrets().get("admin_password_hash") or ""
        except Exception:
            return ""

    def is_password_set(self) -> bool:
        return bool(self.password_hash())

    def _secrets(self):
        from mastersetting.admin_auth import SecretStore
        return SecretStore(fallback_path=str(app_data_dir() / "secrets.enc"))

    def set_admin_password(self, password: str) -> None:
        """Задать/сменить пароль администратора (хранится только хеш)."""
        from mastersetting.admin_auth import hash_password
        if len(password) < 8:
            from mastersetting.admin_auth import AdminAuthError
            raise AdminAuthError("Пароль слишком короткий (нужно 8+ символов)")
        self._secrets().set("admin_password_hash", hash_password(password))

    def login_admin(self, password: str) -> bool:
        """Проверить пароль администратора с блокировкой перебора."""
        return self._auth().try_login(password, self.password_hash())

    def admin_locked_for(self) -> float:
        return self._auth().locked_for()

    def s3_configured(self) -> bool:
        """Заданы ли реквизиты S3 (ключи — в системном хранилище, не в файле)."""
        s = self._secrets()
        try:
            return bool(s.get("s3_bucket") and s.get("s3_access_key")
                        and s.get("s3_secret_key"))
        except Exception:
            return False

    def set_s3_config(self, endpoint: str, region: str, bucket: str,
                      access_key: str, secret_key: str) -> None:
        """Сохранить реквизиты S3 в системном хранилище (ТЗ: не в открытом виде)."""
        s = self._secrets()
        s.set("s3_endpoint", endpoint)
        s.set("s3_region", region)
        s.set("s3_bucket", bucket)
        s.set("s3_access_key", access_key)
        s.set("s3_secret_key", secret_key)

    def _backup_out_dir(self) -> str:
        return os.path.join(os.path.dirname(self.config.base_path), "backups")

    def _build_backup_manager(self, out_dir: str):
        """BackupManager с клиентом S3, если реквизиты заданы; иначе локальный.

        Экземпляр кэшируется, чтобы ``seal_seconds`` реально схлопывал быстрые
        последовательные изменения в один снимок (ТЗ).
        """
        cache = getattr(self, "_bm_cache", None)
        if cache is not None and cache[0] == out_dir:
            return cache[1]
        bm = self._make_backup_manager(out_dir)
        self._bm_cache = (out_dir, bm)
        return bm

    def _make_backup_manager(self, out_dir: str):
        from mastersetting.s3_backup import BackupManager, make_s3_client
        s = self._secrets()
        try:
            bucket = s.get("s3_bucket") or ""
            if bucket:
                client = make_s3_client(
                    s.get("s3_endpoint") or "", s.get("s3_region") or "",
                    s.get("s3_access_key") or "", s.get("s3_secret_key") or "")
                return BackupManager([self.config.base_path, str(app_data_dir())],
                                     out_dir, s3_client=client, bucket=bucket)
        except Exception:
            pass  # нет boto3 или неполные ключи — работаем локально
        return _make_backup_manager(
            [self.config.base_path, str(app_data_dir())], out_dir)

    # ------------------------------------------------------------------
    # Автопроверка обновлений при интернете (установку запускает админ)
    # ------------------------------------------------------------------
    def update_channel_configured(self) -> bool:
        s = self._secrets()
        try:
            return bool(s.get("update_manifest_url") and s.get("update_public_key"))
        except Exception:
            return False

    def set_update_channel(self, manifest_url: str, public_key_b64: str) -> None:
        """Сохранить адрес канала обновлений и доверенный публичный ключ (ТЗ)."""
        if not public_key_b64.strip():
            raise ValueError("Публичный ключ подписи обязателен")
        s = self._secrets()
        s.set("update_manifest_url", manifest_url.strip())
        s.set("update_public_key", public_key_b64.strip())

    def auto_check_update(self) -> dict:
        """Тихая автопроверка обновления (при интернете). Установку НЕ запускает."""
        from mastersetting import updates
        s = self._secrets()
        try:
            url = s.get("update_manifest_url") or ""
            pub = s.get("update_public_key") or ""
        except Exception:
            url = pub = ""
        if not url or not pub:
            return {"status": "skipped",
                    "message": "Канал обновлений не настроен"}
        try:
            res = updates.auto_check(self.config.app_version, url, pub)
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": str(e)}
        if res.status in ("available", "unverified", "error"):
            self.catalog.log_event("update_check",
                                  "info" if res.status == "available" else "error",
                                  message=res.message)
        return {"status": res.status, "message": res.message,
                "verified": res.verified,
                "version": res.manifest.version if res.manifest else ""}

    # ------------------------------------------------------------------
    # S3: правила жизненного цикла (старые версии не копят место)
    # ------------------------------------------------------------------
    def apply_s3_lifecycle(self, days: int = 90) -> dict:
        """Попросить S3 удалять старые версии снимков через N дней (ТЗ).

        Ставит и версионирование бакета, и правило lifecycle на префикс копий,
        чтобы «90 дней» работало и при включённом versioning.
        """
        s = self._secrets()
        try:
            bucket = s.get("s3_bucket") or ""
            if not bucket:
                return {"ok": False, "message": "S3 не настроен"}
            from mastersetting.s3_backup import make_s3_client
            client = make_s3_client(s.get("s3_endpoint") or "",
                                    s.get("s3_region") or "",
                                    s.get("s3_access_key") or "",
                                    s.get("s3_secret_key") or "")
            try:
                client.put_bucket_versioning(
                    Bucket=bucket,
                    VersioningConfiguration={"Status": "Enabled"})
            except Exception:
                pass  # не все S3-совместимые хранилища поддерживают
            rule = {
                "Rules": [{
                    "ID": "master-setting-90d",
                    "Status": "Enabled",
                    "Filter": {"Prefix": "mastersetting/backups/"},
                    "Expiration": {"Days": days},
                    "NoncurrentVersionExpiration": {"NoncurrentDays": days},
                }]
            }
            client.put_bucket_lifecycle_configuration(
                Bucket=bucket, LifecycleConfiguration=rule)
            self.catalog.log_event("s3_lifecycle", "ok",
                                  message=f"правило {days} дней установлено")
            return {"ok": True, "message": f"Правила S3 на {days} дней установлены"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "message": f"Не удалось задать правила S3: {e}"}

    def backup_now(self) -> dict:
        """Собрать снимок рабочих данных и отправить в S3, если настроен."""
        bm = self._build_backup_manager(self._backup_out_dir())
        res = bm.snapshot()
        uploaded = None
        if res.ok and bm.s3 is not None and bm.bucket:
            up = bm.upload(res)
            uploaded = {"ok": up.ok, "message": up.message,
                        "deferred": up.deferred}
        self.catalog.log_event("backup", "ok" if res.ok else "error",
                              message=res.message, files=res.files)
        return {"ok": res.ok, "path": res.path, "files": res.files,
                "message": res.message, "s3": uploaded}

    def flush_pending_uploads(self) -> dict:
        """Отправить отложенные офлайн-снимки, когда интернет вернулся (ТЗ)."""
        bm = self._build_backup_manager(self._backup_out_dir())
        if bm.s3 is None or not bm.bucket:
            return {"ok": False, "message": "S3 не настроен"}
        rep = bm.flush_pending()
        if rep["sent"]:
            self.catalog.log_event("backup", "ok",
                                  message=f"отправлено отложенных: {len(rep['sent'])}")
        return {"ok": True, "message": (
            f"Отправлено: {len(rep['sent'])}. Осталось: {rep['pending_left']}."),
            **rep}

    def pending_uploads(self) -> int:
        bm = self._build_backup_manager(self._backup_out_dir())
        try:
            return len(bm.pending_uploads())
        except Exception:
            return 0

    def trial_restore_latest(self) -> dict:
        """Пробное восстановление самой свежей копии в отдельный каталог (ТЗ)."""
        bm = self._build_backup_manager(self._backup_out_dir())
        if bm.s3 is None or not bm.bucket:
            # Без S3 пробуем локальную свежую копию
            items = self.backup_status()["items"]
            if not items:
                return {"ok": False, "message": "Нет копий для проверки"}
            from mastersetting.s3_backup import verify_snapshot
            path = os.path.join(self.backup_status()["dir"], items[0]["name"])
            ok, msg = verify_snapshot(path)
            return {"ok": ok, "message": msg}
        remote = bm.list_remote()
        if not remote:
            return {"ok": False, "message": "В S3 нет копий"}
        newest = sorted(remote, key=lambda o: o["date"])[-1]["key"]
        scratch = os.path.join(os.path.dirname(self.config.base_path),
                               "backups", "trial")
        return bm.trial_restore(newest, scratch)

    def _daily_stamp_file(self) -> str:
        return str(app_data_dir() / "last_daily_backup.txt")

    def auto_backup(self, reason: str) -> dict | None:
        """Автоматическая копия после изменений и раз в сутки (ТЗ).

        Быстрые последовательные изменения схлопываются ``BackupManager`` в один
        снимок. Офлайн — отправка откладывается, локальная копия всё равно есть.
        """
        import datetime as _dt
        today = _dt.date.today().isoformat()
        daily_due = True
        try:
            with open(self._daily_stamp_file(), encoding="utf-8") as f:
                daily_due = f.read().strip() != today
        except OSError:
            daily_due = True
        # После изменений — всегда пробуем объединённый снимок; раз в сутки —
        # принудительный «дневной». Иначе не дёргаем лишний раз.
        if reason == "daily" and not daily_due:
            return None
        try:
            rep = self.backup_now()
        except Exception:
            return None
        if rep.get("ok"):
            try:
                with open(self._daily_stamp_file(), "w", encoding="utf-8") as f:
                    f.write(today)
            except OSError:
                pass
        return rep

    def backup_status(self) -> dict:
        """Список локальных копий и срок хранения (90 дней)."""
        out = os.path.join(os.path.dirname(self.config.base_path), "backups")
        items = []
        if os.path.isdir(out):
            for name in sorted(os.listdir(out), reverse=True):
                if name.startswith("ms-snapshot-") and name.endswith(".tar.gz"):
                    p = os.path.join(out, name)
                    try:
                        items.append({"name": name,
                                      "size": os.path.getsize(p),
                                      "mtime": os.path.getmtime(p)})
                    except OSError:
                        pass
        return {"dir": out, "count": len(items), "items": items[:20],
                "retention_days": 90}

    def restore_from_snapshot(self, snapshot_path: str) -> dict:
        """Восстановить данные из копии с предварительной страховочной копией."""
        from mastersetting.s3_backup import restore_snapshot
        out = os.path.join(os.path.dirname(self.config.base_path), "backups")
        pre = os.path.join(out, "pre-restore")
        rep = restore_snapshot(snapshot_path,
                              [self.config.base_path, str(app_data_dir())], pre)
        self.catalog.log_event("restore", "ok",
                              message=f"восстановлено файлов: {rep['restored_files']}",
                              files=rep["restored_files"])
        return rep

    def check_update(self, manifest_path: str) -> dict:
        """Проверить подписанный манифест обновления.

        ТЗ: обновление принимается только с верной подписью доверенным ключом;
        с неверной — отклоняется. Публичный ключ берём из системного хранилища.
        """
        from mastersetting import updates
        try:
            pub = self._secrets().get("update_public_key") or ""
        except Exception:
            pub = ""
        if not pub:
            return {"status": "no_key",
                    "message": "Публичный ключ обновлений не задан в системном хранилище."}
        try:
            manifest = updates.Manifest.from_json(
                open(manifest_path, encoding="utf-8").read())
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": f"Манифест не читается: {e}"}
        res = updates.check_for_update(self.config.app_version, manifest, pub)
        self.catalog.log_event("update", "ok" if res.verified else "error",
                              message=res.message)
        return {"status": res.status, "message": res.message,
                "verified": res.verified,
                "version": manifest.version}

    def update_log(self) -> list[dict]:
        """Журнал обновлений (для админ-панели, ТЗ: «покажи лог обновления»)."""
        try:
            text = (app_data_dir() / "update-log.json").read_text(encoding="utf-8")
        except Exception:
            return []
        try:
            return json.loads(text)
        except Exception:
            return []

    def _append_update_log(self, entry: dict) -> None:
        from mastersetting.updates import UpdateLog
        log = UpdateLog(entries=self.update_log())
        log.add(entry.get("action", ""), entry.get("version", ""),
                bool(entry.get("ok")), entry.get("message", ""))
        try:
            (app_data_dir() / "update-log.json").write_text(
                log.to_json(), encoding="utf-8")
        except OSError:
            pass

    def prepare_update(self, manifest_path: str, package_path: str) -> dict:
        """Проверить пакет подписью и ПОДГОТОВИТЬ к ручному запуску (ТЗ).

        Автоматический запуск исполняемого файла из бакета не делаем: только
        проверка подписи/хеша, страховочная копия данных и выкладка проверенного
        файла. Запуск делает администратор вручную.
        """
        from mastersetting import updates
        try:
            pub = self._secrets().get("update_public_key") or ""
        except Exception:
            pub = ""
        if not pub:
            return {"ok": False, "message":
                    "Публичный ключ обновлений не задан в системном хранилище."}
        try:
            manifest = updates.Manifest.from_json(
                open(manifest_path, encoding="utf-8").read())
        except Exception as e:  # noqa: BLE001
            self._append_update_log({"action": "prepare", "version": "?",
                                     "ok": False, "message": f"манифест: {e}"})
            return {"ok": False, "message": f"Манифест не читается: {e}"}

        ok, msg = updates.verify_package(package_path, manifest, pub)
        if not ok:
            self._append_update_log({"action": "verify", "version": manifest.version,
                                     "ok": False, "message": msg})
            return {"ok": False, "message": f"Пакет отклонён: {msg}"}

        # Страховочная копия рабочих данных перед установкой
        backup = self.backup_now()
        dest = str(Path(self._backup_out_dir()).parent / "updates")
        ok2, target = updates.apply_manual_update(package_path, manifest, pub, dest)
        if not ok2:
            self._append_update_log({"action": "prepare", "version": manifest.version,
                                     "ok": False, "message": target})
            return {"ok": False, "message": target}
        self._append_update_log({
            "action": "prepare", "version": manifest.version, "ok": True,
            "message": f"проверено, файл готов: {target}"})
        self.catalog.log_event("update", "ok", message=f"подготовлено: {manifest.version}")
        return {"ok": True, "message": (
            f"Пакет {manifest.version} проверен. Данные сохранены в резервную копию."
            "\nЗапустите установщик вручную: "
            f"\n{target}"),
            "path": target, "version": manifest.version,
            "backup": backup.get("path", "")}

    def set_data_path(self, path: str) -> dict:
        """Сменить путь данных (ТЗ: путь должен настраиваться, вне каталога установки)."""
        import os as _os
        target = _os.path.abspath(_os.path.expanduser(path))
        if is_system_path(target):
            return {"ok": False, "message":
                    "Системный диск или папка приложения не подходят."}
        from mastersetting.platform import is_install_path
        if is_install_path(target):
            return {"ok": False, "message":
                    "Каталог установки нельзя: при обновлении данные пропадут."}
        self.config.base_path = target
        try:
            for p in (self.config.cameraman_path, self.config.main_path,
                      self.config.instructions_path):
                Path(p).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {"ok": False, "message": f"Не удалось создать папку: {e}"}
        try:
            self.config.save()
        except OSError as e:
            return {"ok": False, "message": f"Не удалось сохранить настройку: {e}"}
        self.catalog.log_event("config", "ok", message=f"путь данных: {target}")
        return {"ok": True, "message": target}

    # ------------------------------------------------------------------
    # Миграция старого архива (C:/setting из 1.9)
    # ------------------------------------------------------------------
    def legacy_archive_present(self) -> bool:
        """Есть ли на этой машине старый архив 1.9, который стоит перенести."""
        legacy = legacy_base_path()
        try:
            if not os.path.isdir(legacy):
                return False
            if os.path.isdir(os.path.join(legacy, "cameraman")):
                return True
            return os.path.isfile(os.path.join(legacy, "main", "camera.txt"))
        except OSError:
            return False

    def _migrator(self):
        from mastersetting.migration import Migrator
        out = os.path.join(os.path.dirname(self.config.base_path), "backups")
        return Migrator(legacy_base_path(), self.config.base_path, out)

    def scan_migration(self) -> dict:
        """Предпросмотр миграции: что найдено, без записи и без изменений."""
        if not self.legacy_archive_present():
            return {"found": False, "legacy": legacy_base_path(), "entries": []}
        entries = self._migrator().scan()
        return {
            "found": True,
            "legacy": legacy_base_path(),
            "entries": [{"operator": e.operator, "camera": e.camera,
                         "preset": e.preset, "status": e.status,
                         "detail": e.detail} for e in entries],
        }

    def run_migration(self) -> dict:
        """Перенести старый архив: проверяемая копия → импорт → отчёт.

        ТЗ: старые данные остаются нетронутыми; сначала копия, затем импорт.
        """
        rep = self._migrator().migrate()
        self.catalog.log_event("migrate", "ok" if rep.backup_verified else "error",
                              message=rep.summary())
        return {
            "ok": True,
            "backup_path": rep.backup_path,
            "backup_verified": rep.backup_verified,
            "imported": len(rep.imported),
            "duplicates": len(rep.duplicates),
            "skipped": len(rep.skipped),
            "summary": rep.summary(),
        }

    # ------------------------------------------------------------------
    # Библиотека
    # ------------------------------------------------------------------
    def list_operators(self) -> list[str]:
        ops = set(self.catalog.list_operators())
        root = self.config.cameraman_path
        if os.path.isdir(root):
            for item in os.listdir(root):
                if os.path.isdir(os.path.join(root, item)):
                    ops.add(item)
        from agent.local_store import LocalStore
        for op in LocalStore().get_data().operators:
            ops.add(op)
        return sorted(ops)

    def list_cameras(self) -> list[str]:
        cams = set(self.catalog.list_cameras())
        if os.path.exists(self.config.camera_file):
            with open(self.config.camera_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        cams.add(line.strip())
        from agent.local_store import LocalStore
        for cam in LocalStore().get_data().cameras:
            cams.add(cam)
        # FX3A — известная модель даже если её нет в camera.txt
        cams.add("SonyFX3A")
        return sorted(cams)

    def list_presets(self, operator: str, camera: str) -> list[str]:
        return self.library.store.list_presets(operator, camera)

    def list_versions(self, operator: str, camera: str, preset: str) -> list[PresetVersion]:
        return self.library.store.list_versions(operator, camera, preset)

    def recent_versions(self, limit: int = 6) -> list[RecentItem]:
        """Последние версии для главного экрана."""
        out: list[RecentItem] = []
        root = self.config.cameraman_path
        if not os.path.isdir(root):
            return out
        for op in os.listdir(root):
            op_dir = os.path.join(root, op)
            if not os.path.isdir(op_dir):
                continue
            for cam in os.listdir(op_dir):
                cam_dir = os.path.join(op_dir, cam)
                if not os.path.isdir(cam_dir):
                    continue
                for preset in os.listdir(cam_dir):
                    if not os.path.isdir(os.path.join(cam_dir, preset)):
                        continue
                    versions = self.list_versions(op, cam, preset)
                    if versions:
                        v = versions[0]
                        out.append(RecentItem(op, cam, preset, v.version_id,
                                              v.created_at, v.file_count))
        out.sort(key=lambda r: r.created_at, reverse=True)
        return out[:limit]

    def last_backup_status(self) -> str:
        """Строка статуса последнего бекапа для главного экрана."""
        backups_dir = os.path.join(os.path.dirname(self.config.base_path), "backups")
        if not os.path.isdir(backups_dir):
            return "Резервных копий ещё не было"
        items = sorted(
            (os.path.join(backups_dir, d) for d in os.listdir(backups_dir)),
            key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0,
            reverse=True,
        )
        if not items:
            return "Резервных копий ещё не было"
        ts = datetime.fromtimestamp(os.path.getmtime(items[0]))
        return f"Последняя копия: {ts.strftime('%d.%m.%Y %H:%M')}"

    # ------------------------------------------------------------------
    def current_operator(self) -> str:
        from agent.local_store import LocalStore
        ops = LocalStore().get_data().operators
        return ops[-1] if ops else ""

    def remember_operator(self, operator: str) -> None:
        from agent.local_store import LocalStore
        LocalStore().merge_operator(operator)


def _make_backup_manager(data_dirs, out_dir, s3_client=None, bucket=""):
    """Собрать BackupManager с ключами S3 из системного хранилища, если есть."""
    from mastersetting.s3_backup import BackupManager
    return BackupManager(list(data_dirs), out_dir,
                         s3_client=s3_client, bucket=bucket)
