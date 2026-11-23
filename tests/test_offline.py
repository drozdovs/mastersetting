# -*- coding: utf-8 -*-
"""Тесты офлайн-кэша агента."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.offline_cache import OfflineCache, ServerConfig


def test_store_and_get(tmp_path):
    cache = OfflineCache(path=str(tmp_path / "c.json"))
    cfg = ServerConfig(cameras=["SonyFX3", "PanasonicCX"], operators=["Иван"],
                       fetched_at=time.time(), source="server")
    cache.store_config(cfg)

    got = cache.get_config()
    assert got.cameras == ["SonyFX3", "PanasonicCX"]
    assert got.operators == ["Иван"]
    assert got.source == "cache"


def test_persists_across_instances(tmp_path):
    path = str(tmp_path / "c.json")
    OfflineCache(path=path).store_config(
        ServerConfig(cameras=["A"], operators=["B"], fetched_at=time.time()))
    # Новый экземпляр читает с диска
    again = OfflineCache(path=path)
    assert again.get_config().cameras == ["A"]
    assert again.get_config().operators == ["B"]


def test_defaults_when_empty(tmp_path):
    cache = OfflineCache(path=str(tmp_path / "empty.json"))
    got = cache.get_config(defaults_cameras=["Default1"])
    assert got.cameras == ["Default1"]
    assert got.source == "default"


def test_merge_offline_entries(tmp_path):
    cache = OfflineCache(path=str(tmp_path / "c.json"))
    cache.merge_operator("Пётр")
    cache.merge_camera("NewCam")
    cache.merge_operator("Пётр")  # дубликат игнорируется
    got = cache.get_config()
    assert got.operators == ["Пётр"]
    assert got.cameras == ["NewCam"]


def test_is_stale_and_last_sync(tmp_path):
    cache = OfflineCache(path=str(tmp_path / "c.json"))
    assert cache.is_stale(max_age_seconds=10)  # пустой кэш — устаревший
    cache.store_config(ServerConfig(fetched_at=time.time()))
    assert not cache.is_stale(max_age_seconds=60)
    assert cache.last_sync_iso() != ""


def test_corrupt_cache_recovers(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{ this is not valid json ", encoding="utf-8")
    cache = OfflineCache(path=str(path))
    got = cache.get_config(defaults_cameras=["Fallback"])
    assert got.cameras == ["Fallback"]


def test_agent_id_is_persistent(tmp_path, monkeypatch):
    import agent.sync_client as sc

    monkeypatch.setattr(sc, "app_data_dir", lambda: tmp_path)
    aid1 = sc._agent_id()
    aid2 = sc._agent_id()
    assert aid1 == aid2
    assert (tmp_path / "agent_id.txt").exists()
