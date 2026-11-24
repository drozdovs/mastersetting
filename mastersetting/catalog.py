# -*- coding: utf-8 -*-
"""Локальный каталог (SQLite) — метаданные, история и статистика.

Хранит записи об операторах, камерах, сохранённых архивах и журнал операций
(save/load). Всё хранится локально и не зависит от сети.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from .config import Config

SCHEMA = """
CREATE TABLE IF NOT EXISTS operators (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cameras (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS archives (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    operator     TEXT NOT NULL,
    camera       TEXT NOT NULL,
    settings     TEXT NOT NULL,
    path         TEXT NOT NULL,
    size_bytes   INTEGER DEFAULT 0,
    manifest     TEXT DEFAULT '',
    created_at   TEXT NOT NULL,
    UNIQUE(operator, camera, settings, path)
);

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,        -- 'save' | 'load'
    operator     TEXT,
    camera       TEXT,
    settings     TEXT,
    drive        TEXT,
    status       TEXT NOT NULL,        -- 'ok' | 'error' | 'cancelled'
    message      TEXT DEFAULT '',
    bytes        INTEGER DEFAULT 0,
    files        INTEGER DEFAULT 0,
    created_at   TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Catalog:
    """Обёртка над SQLite-каталогом."""

    def __init__(self, db_path: str | None = None, config: Config | None = None):
        self.config = config or Config.load()
        self.db_path = db_path or self.config.catalog_db
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(SCHEMA)

    # ------------------------------------------------------------------
    # Операторы / камеры
    # ------------------------------------------------------------------
    def add_operator(self, name: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO operators(name, created_at) VALUES(?, ?)",
                (name, _now()),
            )

    def add_camera(self, name: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO cameras(name, created_at) VALUES(?, ?)",
                (name, _now()),
            )

    def list_operators(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT name FROM operators ORDER BY name").fetchall()
        return [r["name"] for r in rows]

    def list_cameras(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT name FROM cameras ORDER BY name").fetchall()
        return [r["name"] for r in rows]

    # ------------------------------------------------------------------
    # Архивы
    # ------------------------------------------------------------------
    def register_archive(
        self,
        operator: str,
        camera: str,
        settings: str,
        path: str,
        size_bytes: int = 0,
        manifest: str = "",
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO archives
                   (operator, camera, settings, path, size_bytes, manifest, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (operator, camera, settings, path, size_bytes, manifest, _now()),
            )
        self.add_operator(operator)
        self.add_camera(camera)

    def list_archives(self, operator: str | None = None, camera: str | None = None) -> list[dict]:
        query = "SELECT * FROM archives"
        params: list = []
        where = []
        if operator:
            where.append("operator = ?")
            params.append(operator)
        if camera:
            where.append("camera = ?")
            params.append(camera)
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # События / статистика
    # ------------------------------------------------------------------
    def log_event(
        self,
        kind: str,
        status: str,
        operator: str = "",
        camera: str = "",
        settings: str = "",
        drive: str = "",
        message: str = "",
        bytes_: int = 0,
        files: int = 0,
    ) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO events
                   (kind, operator, camera, settings, drive, status, message,
                    bytes, files, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (kind, operator, camera, settings, drive, status, message,
                 bytes_, files, _now()),
            )
            return int(cur.lastrowid)

    def list_events(self, limit: int = 200) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        """Агрегированная статистика для панели/дашборда."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
            saves = conn.execute(
                "SELECT COUNT(*) c FROM events WHERE kind='save' AND status='ok'"
            ).fetchone()["c"]
            loads = conn.execute(
                "SELECT COUNT(*) c FROM events WHERE kind='load' AND status='ok'"
            ).fetchone()["c"]
            errors = conn.execute(
                "SELECT COUNT(*) c FROM events WHERE status='error'"
            ).fetchone()["c"]
            archives = conn.execute("SELECT COUNT(*) c FROM archives").fetchone()["c"]
            by_operator = conn.execute(
                """SELECT operator, COUNT(*) c FROM events
                   WHERE status='ok' AND operator <> ''
                   GROUP BY operator ORDER BY c DESC LIMIT 10"""
            ).fetchall()
        return {
            "events_total": total,
            "saves_ok": saves,
            "loads_ok": loads,
            "errors": errors,
            "archives": archives,
            "top_operators": [dict(r) for r in by_operator],
        }
