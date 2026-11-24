# -*- coding: utf-8 -*-
"""Тесты локального хранилища агента."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.local_store import LocalData, LocalStore


def test_store_and_get(tmp_path):
    store = LocalStore(path=str(tmp_path / "c.json"))
    data = LocalData(cameras=["SonyFX3", "PanasonicCX"], operators=["Иван"],
                     updated_at=time.time(), source="local")
    store.store_data(data)

    got = store.get_data()
    assert got.cameras == ["SonyFX3", "PanasonicCX"]
    assert got.operators == ["Иван"]
    assert got.source == "local"


def test_persists_across_instances(tmp_path):
    path = str(tmp_path / "c.json")
    LocalStore(path=path).store_data(
        LocalData(cameras=["A"], operators=["B"], updated_at=time.time()))
    # Новый экземпляр читает с диска
    again = LocalStore(path=path)
    assert again.get_data().cameras == ["A"]
    assert again.get_data().operators == ["B"]


def test_defaults_when_empty(tmp_path):
    store = LocalStore(path=str(tmp_path / "empty.json"))
    got = store.get_data(defaults_cameras=["Default1"])
    assert got.cameras == ["Default1"]
    assert got.source == "default"


def test_merge_names(tmp_path):
    store = LocalStore(path=str(tmp_path / "c.json"))
    store.merge_operator("Пётр")
    store.merge_camera("NewCam")
    store.merge_operator("Пётр")  # дубликат игнорируется
    got = store.get_data()
    assert got.operators == ["Пётр"]
    assert got.cameras == ["NewCam"]


def test_last_update(tmp_path):
    store = LocalStore(path=str(tmp_path / "c.json"))
    assert store.last_update_iso() == ""  # пустое хранилище
    store.store_data(LocalData(updated_at=time.time()))
    assert store.last_update_iso() != ""


def test_corrupt_store_recovers(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{ this is not valid json ", encoding="utf-8")
    store = LocalStore(path=str(path))
    got = store.get_data(defaults_cameras=["Fallback"])
    assert got.cameras == ["Fallback"]
