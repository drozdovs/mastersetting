# -*- coding: utf-8 -*-
"""Клиент синхронизации агента с сервером.

Отвечает за:
  * регистрацию агента и получение токена;
  * периодический heartbeat (статус подключения);
  * отправку несинхронизированных событий из локального каталога;
  * проверку и скачивание обновлений.
Работает в отдельном потоке, полностью необязателен — агент offline-first.
"""

from __future__ import annotations

import os
import platform
import socket
import threading
import time
from dataclasses import dataclass

import requests

from mastersetting import __version__
from mastersetting.catalog import Catalog
from mastersetting.config import Config, app_data_dir


def _agent_id() -> str:
    """Постоянный идентификатор агента (сохраняется в файле)."""
    path = app_data_dir() / "agent_id.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    import uuid
    aid = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(aid, encoding="utf-8")
    return aid


@dataclass
class SyncState:
    online: bool = False
    last_error: str = ""
    last_sync: float = 0.0
    server_version: str = ""


class SyncClient:
    def __init__(self, config: Config | None = None, catalog: Catalog | None = None):
        self.config = config or Config.load()
        self.catalog = catalog or Catalog(config=self.config)
        self.agent_id = _agent_id()
        self.state = SyncState()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._token = self.config.server_token
        self._session = requests.Session()

    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.config.server_url)

    def _url(self, path: str) -> str:
        return self.config.server_url.rstrip("/") + path

    def _headers(self) -> dict:
        return {"X-Agent-Token": self._token} if self._token else {}

    # ------------------------------------------------------------------
    def register(self) -> bool:
        """Зарегистрировать агента и получить токен."""
        if not self.enabled:
            return False
        try:
            resp = self._session.post(
                self._url("/api/agent/register"),
                json={
                    "agent_id": self.agent_id,
                    "hostname": socket.gethostname(),
                    "os_info": f"{platform.system()} {platform.release()}",
                    "version": __version__,
                },
                timeout=10,
            )
            resp.raise_for_status()
            self._token = resp.json()["token"]
            # Сохраняем токен
            self.config.server_token = self._token
            try:
                self.config.save()
            except Exception:
                pass
            self.state.online = True
            self.state.last_error = ""
            return True
        except Exception as e:  # noqa: BLE001
            self.state.online = False
            self.state.last_error = str(e)
            return False

    def heartbeat(self) -> bool:
        try:
            resp = self._session.post(
                self._url("/api/agent/heartbeat"),
                json={"agent_id": self.agent_id, "version": __version__},
                headers=self._headers(), timeout=10,
            )
            resp.raise_for_status()
            self.state.online = True
            self.state.last_error = ""
            return True
        except Exception as e:  # noqa: BLE001
            self.state.online = False
            self.state.last_error = str(e)
            return False

    def sync_events(self) -> int:
        """Отправить накопленные события на сервер."""
        events = self.catalog.unsynced_events()
        if not events:
            return 0
        payload = {"events": [{
            "kind": e["kind"], "status": e["status"], "operator": e["operator"],
            "camera": e["camera"], "settings_name": e["settings"],
            "drive": e["drive"], "message": e["message"],
            "bytes": e["bytes"], "files": e["files"],
            "created_at": e["created_at"],
        } for e in events]}
        try:
            resp = self._session.post(
                self._url("/api/agent/events"), json=payload,
                headers=self._headers(), timeout=15,
            )
            resp.raise_for_status()
            self.catalog.mark_synced([e["id"] for e in events])
            self.state.last_sync = time.time()
            return len(events)
        except Exception as e:  # noqa: BLE001
            self.state.last_error = str(e)
            return 0

    def push_setting(self, operator: str, camera: str, settings_name: str,
                     path: str, size_bytes: int, manifest: str = "") -> bool:
        try:
            resp = self._session.post(
                self._url("/api/agent/settings"),
                json={"operator": operator, "camera": camera,
                      "settings_name": settings_name, "path_on_agent": path,
                      "size_bytes": size_bytes, "manifest": manifest},
                headers=self._headers(), timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception:
            return False

    def check_update(self) -> dict | None:
        """Вернуть описание доступного обновления или None."""
        try:
            resp = self._session.get(
                self._url("/api/agent/update"),
                params={"current": __version__},
                headers=self._headers(), timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if data.get("update") else None
        except Exception:
            return None

    def download_update(self, info: dict, dest_dir: str | None = None) -> str | None:
        """Скачать файл обновления, вернуть путь к файлу."""
        dest_dir = dest_dir or str(app_data_dir() / "updates")
        os.makedirs(dest_dir, exist_ok=True)
        filename = os.path.basename(info.get("url", "update.bin")) or "update.bin"
        dest = os.path.join(dest_dir, filename)
        try:
            resp = self._session.get(
                self._url(info["url"]), headers=self._headers(),
                timeout=120, stream=True,
            )
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
            return dest
        except Exception as e:  # noqa: BLE001
            self.state.last_error = str(e)
            return None

    # ------------------------------------------------------------------
    # Фоновый цикл
    # ------------------------------------------------------------------
    def start(self) -> None:
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        if not self._token:
            self.register()
        while not self._stop.is_set():
            self.heartbeat()
            self.sync_events()
            self._stop.wait(self.config.heartbeat_seconds)
