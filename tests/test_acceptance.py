# -*- coding: utf-8 -*-
"""Дополнительные проверки по критериям приёмки ТЗ (п.4).

Здесь собраны сценарии, которые ТЗ требует проверить явно, но которые не были
покрыты основными наборами тестов:

* пропавшая/подменённая карта во время операции;
* нехватка места с понятным сообщением (а не «тихий» успех);
* восстановление данных из резервной копии;
* отклонение пакета с верной длиной, но неверной подписью;
* конфликт путей двух комплектов запрещает двойную запись;
* неполная пара предупреждает, но позволяет записать имеющуюся часть.

Все тесты работают на временных каталогах и НЕ трогают реальные карты и
реальные данные пользователя.
"""

import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mastersetting import fs_ops
from mastersetting.library import PresetLibrary
from mastersetting.pairs import PairStore, PresetPair
from mastersetting.safe_write import SafeWriter, WriteError, plan_required_bytes
from mastersetting.versioning import VersionStore


# ---------------------------------------------------------------------------
# Помощники
# ---------------------------------------------------------------------------

def _dat(payload: bytes = b"A" * 64) -> bytes:
    """Файл с настоящей сигнатурой настроек Sony (SONY0)."""
    return b"SONY0" + payload


def _card(root, *, name="PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT", data=b"OLD"):
    path = os.path.join(root, *name.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def _version(tmp_path, payload=b"NEW-data"):
    """Создать версию и вернуть (store, PresetVersion)."""
    store = VersionStore(base_path=str(tmp_path / "base"))
    src = tmp_path / "src.dat"
    src.write_bytes(_dat(payload))
    rep = store.import_files("Иван", "SonyFX3", "Основные",
                             {"PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT": str(src)})
    versions = store.list_versions("Иван", "SonyFX3", "Основные")
    assert versions, rep
    return store, versions[0]


# ===========================================================================
# 1. Пропавшая карта / подмена носителя
# ===========================================================================

def test_missing_card_reports_error_not_success(tmp_path):
    """Если карты нет — запись падает с понятной ошибкой, а не «успехом»."""
    lib = PresetLibrary(base_path=str(tmp_path / "base"))
    _, version = _version(tmp_path)

    missing = str(tmp_path / "no-such-card")
    with pytest.raises(WriteError):
        lib.write_version_to_card(version, missing)


def test_card_vanishes_mid_write_stops_and_reports(tmp_path):
    """Карта исчезла во время записи — операция останавливается с ошибкой."""
    store, version = _version(tmp_path)
    card = tmp_path / "card"
    card.mkdir()
    writer = SafeWriter(str(card))

    src = tmp_path / "src.dat"
    src.write_bytes(b"SONY0payload")

    calls = {"n": 0}

    def cancel_after_first() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    files = {"A/one.dat": str(src), "B/two.dat": str(src)}
    rep = writer.write(files, verify=True, should_cancel=cancel_after_first)

    assert rep.ok is False, "частичная запись не должна выглядеть успехом"
    assert rep.written, "первый файл должен быть записан"
    assert "отмен" in rep.message.lower() or "cancel" in rep.message.lower()


def test_volume_swap_detected(tmp_path, monkeypatch):
    """Подмена носителя между шагами должна останавливать запись."""
    card = tmp_path / "card"
    card.mkdir()
    src = tmp_path / "src.dat"
    src.write_bytes(b"SONY0payload")

    writer = SafeWriter(str(card))

    seq = {"i": 0}

    def fake_volume_id(path):
        seq["i"] += 1
        return "dev=1" if seq["i"] == 1 else "dev=999"

    monkeypatch.setattr("mastersetting.safe_write.volume_id", fake_volume_id)
    rep = writer.write({"A/one.dat": str(src)}, verify=True, protect_volume=True)
    assert rep.ok is False
    assert "замен" in rep.message.lower()


def test_no_partial_files_left_after_failure(tmp_path):
    """После сбоя на карте не остаётся временных .partial файлов."""
    store, version = _version(tmp_path)
    card = tmp_path / "card"
    card.mkdir()
    writer = SafeWriter(str(card))
    src = tmp_path / "src.dat"
    src.write_bytes(b"SONY0payload")

    rep = writer.write({"A/one.dat": str(src)}, verify=True,
                       should_cancel=lambda: True)
    assert rep.ok is False
    leftovers = [p for _r, _d, fs in os.walk(card) for p in fs
                 if p.endswith(".partial")]
    assert leftovers == [], f"остались временные файлы: {leftovers}"


# ===========================================================================
# 2. Нехватка места
# ===========================================================================

def test_insufficient_space_message_is_clear(tmp_path, monkeypatch):
    """При нехватке места — понятное сообщение, а не «успех»."""
    card = tmp_path / "card"
    card.mkdir()
    src = tmp_path / "src.dat"
    src.write_bytes(b"SONY0" + b"x" * 1024)

    monkeypatch.setattr("mastersetting.safe_write.check_free_space",
                        lambda path, need: False)
    writer = SafeWriter(str(card))
    with pytest.raises(WriteError) as e:
        writer.preflight({"A/one.dat": str(src)})
    assert "мест" in str(e.value).lower()


def test_required_bytes_has_safety_margin():
    """Расчёт места включает запас (ТЗ: место с разумным запасом)."""
    need = plan_required_bytes({"a": 1_000_000})
    assert need > 1_000_000
    # Запас не меньше 8 МБ
    assert need - 1_000_000 >= 8 * 1024 * 1024


def test_zero_free_space_blocks_write(tmp_path, monkeypatch):
    """При нулевом свободном месте запись не выполняется молча-успешно."""
    card = tmp_path / "card"
    card.mkdir()
    src = tmp_path / "src.dat"
    src.write_bytes(b"SONY0data")

    monkeypatch.setattr("mastersetting.safe_write.check_free_space",
                        lambda path, need: False)
    writer = SafeWriter(str(card))

    refused = False
    try:
        rep = writer.write({"A/one.dat": str(src)})
        refused = rep.ok is False
    except WriteError:
        refused = True

    assert refused, "при нехватке места запись обязана быть отклонена"
    # И ничего не должно быть записано
    assert not os.path.exists(card / "A" / "one.dat")


# ===========================================================================
# 3. Восстановление из резервной копии
# ===========================================================================

def test_restore_from_snapshot_returns_files(tmp_path):
    """Восстановление из снимка возвращает данные на место."""
    from mastersetting.s3_backup import BackupManager, build_snapshot

    data = tmp_path / "data"
    (data / "cameraman" / "Иван").mkdir(parents=True)
    (data / "cameraman" / "Иван" / "preset.dat").write_bytes(_dat(b"restored"))

    res = build_snapshot([str(data)], str(tmp_path / "out"))
    assert res.ok

    # Имитируем «потерю» данных и восстановление из копии
    shutil.rmtree(data)
    restore_dir = tmp_path / "restore"

    class FakeS3:
        def upload_file(self, *a, **k):
            pass

        def download_file(self, bucket, key, dest):
            shutil.copy(res.path, dest)

    bm = BackupManager([str(data)], str(tmp_path / "out"),
                       s3_client=FakeS3(), bucket="b")
    bm.restore("mastersetting/backups/" + os.path.basename(res.path),
               str(restore_dir))

    restored = []
    for _r, _d, files in os.walk(restore_dir):
        restored.extend(files)
    assert any("preset.dat" in f for f in restored), restored
    assert any(f == "_snapshot_manifest.json" for f in restored)


def test_restore_rejects_corrupted_snapshot(tmp_path):
    """Повреждённый архив не восстанавливается."""
    from mastersetting.s3_backup import BackupError, BackupManager

    broken = tmp_path / "ms-snapshot-broken.tar.gz"
    broken.write_bytes(b"not a tarball at all")

    class FakeS3:
        def download_file(self, bucket, key, dest):
            shutil.copy(broken, dest)

    bm = BackupManager([str(tmp_path / "nothing")], str(tmp_path / "out"),
                       s3_client=FakeS3(), bucket="b")
    with pytest.raises(BackupError):
        bm.restore("mastersetting/backups/ms-snapshot-broken.tar.gz",
                   str(tmp_path / "restore"))


def test_verify_snapshot_detects_missing_file(tmp_path):
    """Проверка снимка замечает, если обещанный файл отсутствует."""
    import json
    import tarfile

    from mastersetting.s3_backup import verify_snapshot

    path = tmp_path / "ms-snapshot-x.tar.gz"
    manifest = {"files": {"нет-такого.dat": {"sha256": "x"}}}
    with tarfile.open(path, "w:gz") as tar:
        raw = json.dumps(manifest).encode("utf-8")
        info = tarfile.TarInfo("_snapshot_manifest.json")
        info.size = len(raw)
        tar.addfile(info, __import__("io").BytesIO(raw))

    ok, msg = verify_snapshot(str(path))
    assert ok is False
    assert "нет-такого.dat" in msg


# ===========================================================================
# 4. Подпись и обновление
# ===========================================================================

def test_valid_length_but_bad_signature_rejected(tmp_path):
    """Пакет с совпадающим размером, но подделанной подписью — отклоняем.

    Так имитируется сценарий, когда обладатель ключа записи в бакет подменил
    файл: имя и даже хеш совпадают, но подпись неверна.
    """
    from mastersetting.updates import Manifest, verify_package

    pkg = tmp_path / "pkg.bin"
    pkg.write_bytes(b"payload" * 100)
    real_hash = fs_ops.hash_file(str(pkg))

    m = Manifest(version="9.9.9", platform="x", filename="pkg.bin",
                 sha256=real_hash, signature="ПОДДЕЛКА")
    ok, msg = verify_package(str(pkg), m, public_key_b64="ключ")
    assert ok is False
    assert "подпис" in msg.lower() or "signature" in msg.lower()


def test_hash_mismatch_rejected(tmp_path):
    from mastersetting.updates import Manifest, verify_package

    pkg = tmp_path / "pkg.bin"
    pkg.write_bytes(b"payload")
    m = Manifest(version="9.9.9", platform="x", filename="pkg.bin",
                 sha256="заведомо-неверный")
    ok, _ = verify_package(str(pkg), m, "key")
    assert ok is False


# ===========================================================================
# 5. Конфликт путей двух комплектов
# ===========================================================================

def test_same_target_path_means_conflict():
    """Если два комплекта целятся в один путь — это конфликт, писать нельзя.

    Проверяем саму функцию обнаружения конфликта на уровне набора путей.
    """
    from mastersetting.library import find_path_conflicts

    fx3 = {"PRIVATE/SONY/SETTING/CAMSET/FX3.DAT": "/a"}
    fx3a = {"PRIVATE/SONY/SETTING/CAMSET/FX3A.DAT": "/b"}
    assert find_path_conflicts(fx3, fx3a) == []

    clash_a = {"PRIVATE/SONY/SETTING/CAMSET/CAMSET.DAT": "/a"}
    clash_b = {"PRIVATE/SONY/SETTING/CAMSET/CAMSET.DAT": "/b"}
    assert find_path_conflicts(clash_a, clash_b) == [
        "PRIVATE/SONY/SETTING/CAMSET/CAMSET.DAT"]


def test_conflicting_pair_write_is_refused(tmp_path):
    """Парная запись с конфликтом путей запрещена (ТЗ)."""
    from mastersetting.library import PairWriteError, plan_pair_write

    with pytest.raises(PairWriteError):
        plan_pair_write(
            {"PRIVATE/X.DAT": "/a"},
            {"PRIVATE/X.DAT": "/b"},
        )


def test_compatible_pair_write_allowed(tmp_path):
    """Без конфликта парная запись разрешена."""
    from mastersetting.library import plan_pair_write

    plan = plan_pair_write(
        {"PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT": "/a"},
        {"PRIVATE/SONY/SETTING/FX3A/CAMSET/FX3A.DAT": "/b"},
    )
    assert len(plan) == 2


# ===========================================================================
# 6. Неполная пара
# ===========================================================================

def test_incomplete_pair_warns_but_allows_present_part(tmp_path):
    """Неполная пара: предупреждаем и записываем только имеющуюся часть."""
    from mastersetting.library import plan_pair_write

    plan, warnings = plan_pair_write(
        {"PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT": "/a"}, {},
        warn_incomplete=True, with_warnings=True)
    assert plan, "имеющаяся часть должна попасть в план"
    assert any("FX3A" in w for w in warnings), warnings
    assert any("неполн" in w.lower() for w in warnings), warnings


def test_pair_store_missing_slots(tmp_path):
    """У неполной пары явно видно, какого слота не хватает."""
    store = VersionStore(base_path=str(tmp_path / "base"))
    src = tmp_path / "s.dat"
    src.write_bytes(_dat())
    v3 = store.import_files("Иван", "SonyFX3", "П", {"PRIVATE/FX3.DAT": str(src)})
    ps = PairStore(app_data_dir=str(tmp_path / "app"), version_store=store)
    ps.upsert(PresetPair(name="Интервью", operator="Иван",
                         fx3_version_id=v3.version_id))
    pair = ps.get("Интервью", "Иван")
    assert pair.missing_slots() == ["FX3A"]
    assert pair.is_complete is False


# ===========================================================================
# 9. Удаление и экспорт версии (ТЗ: действия над библиотекой)
# ===========================================================================

def test_delete_preset_requires_matching_version_count(tmp_path):
    """Удаление необратимо: подтверждение числом версий обязательно."""
    from mastersetting.library import LibraryError
    lib = PresetLibrary(base_path=str(tmp_path / "base"))
    src = tmp_path / "a.dat"
    src.write_bytes(_dat(b"1"))
    lib.store.import_files("Иван", "SonyFX3", "П",
                           {"PRIVATE/FX3.DAT": str(src)})

    # Неверное число — отказ
    with pytest.raises(LibraryError):
        lib.delete_preset("Иван", "SonyFX3", "П", confirm_versions=99)

    # Верное число — удаляет
    n = lib.delete_preset("Иван", "SonyFX3", "П", confirm_versions=1)
    assert n == 1
    assert lib.store.list_versions("Иван", "SonyFX3", "П") == []


def test_export_version_does_not_change_library(tmp_path):
    """Экспорт даёт копию версии и НЕ меняет библиотеку."""
    lib = PresetLibrary(base_path=str(tmp_path / "base"))
    src = tmp_path / "a.dat"
    src.write_bytes(_dat(b"exported"))
    lib.store.import_files("Иван", "SonyFX3", "П",
                           {"PRIVATE/FX3.DAT": str(src)})
    version = lib.store.list_versions("Иван", "SonyFX3", "П")[0]

    out = lib.export_version(version, str(tmp_path / "out"))
    exported = [f for _r, _d, fs in os.walk(out) for f in fs]
    assert exported, "экспорт ничего не скопировал"
    # Библиотека на месте
    assert len(lib.store.list_versions("Иван", "SonyFX3", "П")) == 1


# ===========================================================================
# 10. Безопасное восстановление: страховочная копия перед заменой
# ===========================================================================

def test_restore_snapshot_makes_pre_restore_backup(tmp_path):
    """ТЗ: восстановление делает предварительную локальную копию текущих данных."""
    from mastersetting.s3_backup import build_snapshot, restore_snapshot

    data = tmp_path / "data"
    (data / "cameraman").mkdir(parents=True)
    (data / "cameraman" / "preset.dat").write_bytes(_dat(b"v1"))

    snap = build_snapshot([str(data)], str(tmp_path / "snaps")).path

    # Меняем данные ПОСЛЕ снимка — восстановление должно это зафиксировать
    (data / "cameraman" / "preset.dat").write_bytes(_dat(b"v2-broken"))

    rep = restore_snapshot(snap, [str(data)], str(tmp_path / "pre"))
    assert rep["ok"] is True
    assert rep["pre_restore_backup"], "не сделана страховочная копия перед восстановлением"
    assert os.path.isfile(rep["pre_restore_backup"])
    # Секреты в снимок не попадают — об этом честно предупреждаем
    assert "Секреты" in rep["warning"]


def test_restore_snapshot_refuses_corrupted(tmp_path):
    """Повреждённая копия не должна восстанавливаться «молча»."""
    from mastersetting.s3_backup import BackupError, restore_snapshot

    bogus = tmp_path / "broken.tar.gz"
    bogus.write_bytes(b"not a real archive")
    with pytest.raises(BackupError):
        restore_snapshot(str(bogus), [str(tmp_path / "d")], str(tmp_path / "pre"))


# ===========================================================================
# 11. Админ-панель: пароль и блокировка перебора (ТЗ, дефект 1.9)
# ===========================================================================

def test_admin_panel_gated_by_password(tmp_path):
    """Панель защищена паролем; без пароля действия недоступны (не «скрытая клавиша»)."""
    from mastersetting.admin_auth import AdminAuth, hash_password

    auth = AdminAuth(state_path=str(tmp_path / "state.json"))
    stored = hash_password("правильный-пароль")

    assert auth.try_login("неверный", stored) is False
    assert auth.try_login("правильный-пароль", stored) is True


def test_admin_lockout_after_repeated_failures(tmp_path):
    """Перебор пароля блокируется на время (ТЗ: защита от перебора)."""
    from mastersetting.admin_auth import (AdminAuth, RateLimited,
                                          hash_password, MAX_FAILED_ATTEMPTS)

    auth = AdminAuth(state_path=str(tmp_path / "state.json"))
    stored = hash_password("секрет-секрет")
    for _ in range(MAX_FAILED_ATTEMPTS):
        auth.try_login("перебор", stored)
    assert auth.locked_for() > 0
    with pytest.raises(RateLimited):
        auth.try_login("секрет-секрет", stored)  # даже верный пароль ждёт


# ===========================================================================
# 12. Имена пресетов: без молчаливых коллизий и потери символов (дефект 1.9)
# ===========================================================================

def test_name_that_cleans_to_same_folder_is_rejected(tmp_path):
    """Разные имена не должны молча слиться в одну папку библиотеки."""
    from mastersetting.versioning import VersionStoreError
    store = VersionStore(base_path=str(tmp_path / "base"))
    src = tmp_path / "s.dat"
    src.write_bytes(_dat())

    store.import_files("Иван", "SonyFX3", "Осн. основные",
                       {"PRIVATE/FX3.DAT": str(src)})
    before = store.list_versions("Иван", "SonyFX3", "Осн. основные")
    assert len(before) == 1

    # «Осн основные» очищается до того же компонента, что и первый пресет
    with pytest.raises(VersionStoreError):
        store.import_files("Иван", "SonyFX3", "Осн основные",
                           {"PRIVATE/FX3.DAT": str(src)})
    # Библиотека не изменилась
    assert len(store.list_versions("Иван", "SonyFX3", "Осн. основные")) == 1


def test_name_with_only_punctuation_is_rejected(tmp_path):
    """Имя, состоящее только из недопустимых символов, отсекаем, а не пишем в «путь»."""
    from mastersetting.versioning import VersionStoreError
    store = VersionStore(base_path=str(tmp_path / "base"))
    src = tmp_path / "s.dat"
    src.write_bytes(_dat())
    with pytest.raises(VersionStoreError):
        store.import_files("Иван", "SonyFX3", "...",
                           {"PRIVATE/FX3.DAT": str(src)})


def test_same_day_import_creates_new_version(tmp_path):
    """ТЗ п.4: повторный импорт в тот же день создаёт НОВУЮ версию, старую не трогает."""
    store = VersionStore(base_path=str(tmp_path / "base"))
    src = tmp_path / "s.dat"
    src.write_bytes(_dat(b"v1"))
    store.import_files("Иван", "SonyFX3", "Основные",
                       {"PRIVATE/FX3.DAT": str(src)})
    src.write_bytes(_dat(b"v2"))
    store.import_files("Иван", "SonyFX3", "Основные",
                       {"PRIVATE/FX3.DAT": str(src)})
    versions = store.list_versions("Иван", "SonyFX3", "Основные")
    assert len(versions) == 2, "второй импорт в тот же день не создал новую версию"
    assert versions[0].version_id != versions[1].version_id


def test_list_presets_returns_display_names(tmp_path):
    """В списке пресетов видно имя с пробелами/точкой, а не «очищенный» компонент пути."""
    store = VersionStore(base_path=str(tmp_path / "base"))
    src = tmp_path / "s.dat"
    src.write_bytes(_dat())
    store.import_files("Иван", "SonyFX3", "Основные",
                       {"PRIVATE/FX3.DAT": str(src)})
    assert store.list_presets("Иван", "SonyFX3") == ["Основные"]


def test_same_preset_name_across_operators_is_allowed(tmp_path):
    """Одноимённые пресеты у разных операторов — это разные папки, не коллизия."""
    store = VersionStore(base_path=str(tmp_path / "base"))
    src = tmp_path / "s.dat"
    src.write_bytes(_dat())
    store.import_files("Иван", "SonyFX3", "Основные",
                       {"PRIVATE/FX3.DAT": str(src)})
    store.import_files("Пётр", "SonyFX3", "Основные",
                       {"PRIVATE/FX3.DAT": str(src)})  # не должно падать
    assert store.list_presets("Иван", "SonyFX3") == ["Основные"]
    assert store.list_presets("Пётр", "SonyFX3") == ["Основные"]


def test_operator_name_collision_is_rejected(tmp_path):
    """Похожее имя оператора, сливающееся в один путь, отсекаем."""
    from mastersetting.versioning import VersionStoreError
    store = VersionStore(base_path=str(tmp_path / "base"))
    src = tmp_path / "s.dat"
    src.write_bytes(_dat())
    store.import_files("Иван", "SonyFX3", "Основные",
                       {"PRIVATE/FX3.DAT": str(src)})
    with pytest.raises(VersionStoreError):
        store.import_files("Иван.", "SonyFX3", "Другой",
                           {"PRIVATE/FX3.DAT": str(src)})


# ===========================================================================
# 13. Не писать в системный диск/папку приложения + безопасное извлечение
# ===========================================================================

def test_system_paths_are_recognised():
    """Системный диск, домашний каталог и папка приложения — не «карта»."""
    from mastersetting.platform import IS_MACOS, is_system_path

    assert is_system_path(os.path.abspath(os.sep)) is True     # корень тома
    assert is_system_path(os.path.expanduser("~")) is True      # домашний каталог
    assert is_system_path("") is True
    if IS_MACOS:
        # «/System» — системный каталог именно macOS (на Windows пути нет).
        assert is_system_path("/System") is True


def test_write_to_system_path_is_refused(tmp_path):
    """ТЗ: запрещено выбирать системный диск/каталог приложения как карту."""
    from mastersetting.library import LibraryError
    lib = PresetLibrary(base_path=str(tmp_path / "base"))
    src = tmp_path / "a.dat"
    src.write_bytes(_dat())
    lib.store.import_files("Иван", "SonyFX3", "П", {"PRIVATE/FX3.DAT": str(src)})
    version = lib.store.list_versions("Иван", "SonyFX3", "П")[0]

    with pytest.raises(LibraryError):
        lib.write_version_to_card(version, os.path.abspath(os.sep))


def test_safe_eject_missing_card_reports(tmp_path):
    """Извлечение требует существующего носителя; без него — понятный отказ."""
    from mastersetting.platform import safe_eject

    ok, msg = safe_eject(str(tmp_path / "нет-такой-карты"))
    assert ok is False and msg


def test_manual_card_folder_rejects_system_and_app_dirs(tmp_path, monkeypatch):
    """ТЗ: вручную выбранную папку проверяем — системный диск/приложение нельзя."""
    from mastersetting.config import Config
    from agent.controllers import AppController

    base = tmp_path / "base"
    cfg = Config()
    cfg.base_path = str(base)
    ctrl = AppController(cfg)

    ok, msg = ctrl.check_card_folder(os.path.abspath(os.sep))
    assert ok is False and msg, "корень тома принят как карта"

    ok, msg = ctrl.check_card_folder("")
    assert ok is False and msg

    ok, msg = ctrl.check_card_folder(str(tmp_path / "нет-папки"))
    assert ok is False and msg

    card = tmp_path / "SDCARD"
    card.mkdir()
    ok, msg = ctrl.check_card_folder(str(card))
    assert ok is True and "SDCARD" in msg, "рабочая папка отклонена без причины"


def test_manual_card_folder_rejects_unwritable_folder(tmp_path):
    """Папка под защитой от записи не принимается как карта (ТЗ)."""
    import stat
    from mastersetting.config import Config
    from agent.controllers import AppController

    if os.name == "nt":
        pytest.skip("права POSIX не применяются на Windows")
    cfg = Config()
    cfg.base_path = str(tmp_path / "base")
    ctrl = AppController(cfg)

    locked = tmp_path / "locked"
    locked.mkdir()
    os.chmod(locked, stat.S_IRUSR | stat.S_IXUSR)  # только чтение
    try:
        ok, msg = ctrl.check_card_folder(str(locked))
        assert ok is False and msg
    finally:
        os.chmod(locked, 0o700)


def test_set_data_path_accepts_writable_folder(tmp_path, monkeypatch):
    """Свой путь данных принимается и сохраняется в конфиг (ТЗ)."""
    from mastersetting.config import Config
    from agent.controllers import AppController

    from mastersetting import platform as plat

    target = tmp_path / "my-library"
    monkeypatch.setattr(plat, "is_install_path", lambda p: False)
    monkeypatch.setattr(Config, "save", lambda self: None)  # не трогаем реальный конфиг

    cfg = Config()
    cfg.base_path = str(tmp_path / "base")
    ctrl = AppController(cfg)
    res = ctrl.set_data_path(str(target))
    assert res["ok"] is True
    assert os.path.isdir(str(target / "cameraman"))


def test_set_data_path_rejects_install_dir(tmp_path, monkeypatch):
    """ТЗ: рабочую базу нельзя хранить в каталоге установки (пропадёт при апдейте)."""
    from mastersetting.config import Config
    from agent.controllers import AppController

    from mastersetting import platform as plat

    monkeypatch.setattr(plat, "is_install_path", lambda p: True)
    cfg = Config()
    cfg.base_path = str(tmp_path / "base")
    ctrl = AppController(cfg)
    res = ctrl.set_data_path(str(tmp_path / "install-like"))
    assert res["ok"] is False and "установ" in res["message"].lower()


def test_set_data_path_rejects_system_root(tmp_path):
    """Корень системы нельзя выбрать как хранилище данных (ТЗ)."""
    from mastersetting.config import Config
    from agent.controllers import AppController

    cfg = Config()
    cfg.base_path = str(tmp_path / "base")
    ctrl = AppController(cfg)
    res = ctrl.set_data_path(os.path.abspath(os.sep))
    assert res["ok"] is False


# ===========================================================================
# 14. Парная запись: технический шлюз и безопасность (ТЗ п.2)
# ===========================================================================

def _version_for(tmp_path, camera, payload=b"X"):
    store = VersionStore(base_path=str(tmp_path / "base"))
    src = tmp_path / f"{camera}.dat"
    src.write_bytes(_dat(payload))
    store.import_files("Иван", camera, "Основные", {"PRIVATE/FX.DAT": str(src)})
    return store, store.list_versions("Иван", camera, "Основные")[0]


def test_pair_write_blocked_without_confirmed_paths(tmp_path):
    """ТЗ п.2: без подтверждённых путей FX3/FX3A парную запись НЕ включаем."""
    from mastersetting.library import PairWriteError
    lib = PresetLibrary(base_path=str(tmp_path / "base"))
    store, v3 = _version_for(tmp_path, "SonyFX3")
    lib.store = store
    _, v3a = _version_for(tmp_path, "SonyFX3A")

    assert lib.pair_write_available() is False
    card = tmp_path / "card"
    card.mkdir()
    with pytest.raises(PairWriteError):
        lib.write_pair_to_card(v3, v3a, str(card))


def test_pair_gate_reads_confirmed_rules(tmp_path, monkeypatch):
    """Шлюз подтверждения путей: файл подтверждения реально включает правила."""
    from mastersetting import settings_rules as sr
    from mastersetting.path_confirm import apply_to_rules, save_confirmation

    confirm_file = tmp_path / "fx3_paths_confirmed.json"
    monkeypatch.setenv("MS_FX3_CONFIRM_FILE", str(confirm_file))
    # Исходное состояние правил — не подтверждены
    monkeypatch.setattr(sr, "RULES", [
        sr.SettingsRule(family="SonyFX3", confirmed=False),
        sr.SettingsRule(family="SonyFX3A", confirmed=False),
    ])

    lib = PresetLibrary(base_path=str(tmp_path / "base"))
    assert lib.pair_paths_confirmed() is False

    # Подтверждаем только FX3 -> шлюз ещё закрыт
    save_confirmation("SonyFX3", ["PRIVATE/SONY/SETTING/FX3/CAMSET"])
    assert lib.pair_paths_confirmed() is False

    # Подтверждаем FX3A -> шлюз открывается
    save_confirmation("SonyFX3A", ["PRIVATE/SONY/SETTING/FX3A/CAMSET"])
    enabled = apply_to_rules()
    assert set(enabled) >= {"SonyFX3", "SonyFX3A"}
    assert lib.pair_paths_confirmed() is True
    assert lib.pair_write_available() is True


def test_save_confirmation_rejects_empty_and_traversal(tmp_path, monkeypatch):
    """Подтверждение не принимает пустые пути и попытку выйти за пределы карты."""
    from mastersetting.path_confirm import PathConfirmError, save_confirmation

    monkeypatch.setenv("MS_FX3_CONFIRM_FILE", str(tmp_path / "c.json"))
    with pytest.raises(PathConfirmError):
        save_confirmation("SonyFX3", [])
    with pytest.raises(PathConfirmError):
        save_confirmation("SonyFX3", ["../etc/passwd"])


def test_pair_write_with_confirmed_paths_writes_and_warns_incomplete(tmp_path, monkeypatch):
    """Если шлюз пройден: неполная пара пишется с предупреждением, отчёт точный."""
    lib = PresetLibrary(base_path=str(tmp_path / "base"))
    store, v3 = _version_for(tmp_path, "SonyFX3")
    lib.store = store
    monkeypatch.setattr(lib, "pair_paths_confirmed", lambda: True)
    monkeypatch.setattr(lib, "pair_write_available", lambda: True)

    card = tmp_path / "card"
    card.mkdir()
    rep = lib.write_pair_to_card(v3, None, str(card))  # нет FX3A — неполная пара
    assert rep.ok is True
    assert "FX3A" in rep.message  # предупреждение о неполной паре


def test_pair_write_conflicting_paths_refused_when_gate_open(tmp_path, monkeypatch):
    """При конфликте путей двойная запись запрещена даже при открытом шлюзе (ТЗ)."""
    from mastersetting.library import PairWriteError
    lib = PresetLibrary(base_path=str(tmp_path / "base"))
    store, v3 = _version_for(tmp_path, "SonyFX3")
    lib.store = store
    monkeypatch.setattr(lib, "pair_paths_confirmed", lambda: True)

    # Версия FX3A с тем же относительным путём, что у FX3 -> конфликт
    _, v3a = _version_for(tmp_path, "SonyFX3A")
    # Приводим пути к совпадению вручную (эмуляция «нативные пути совпали»)
    v3a.files[0].rel_path = v3.files[0].rel_path

    card = tmp_path / "card"
    card.mkdir()
    with pytest.raises(PairWriteError):
        lib.write_pair_to_card(v3, v3a, str(card))


# ===========================================================================
# 15. Офлайн-режим и состав копии (ТЗ п.3, п.4)
# ===========================================================================

def test_snapshot_excludes_media_and_temp(tmp_path):
    """Снимок данных не тащит видео с карты и временные файлы (ТЗ)."""
    from mastersetting.s3_backup import build_snapshot, verify_snapshot

    data = tmp_path / "data"
    (data / "cameraman" / "Иван").mkdir(parents=True)
    (data / "cameraman" / "Иван" / "preset.dat").write_bytes(_dat(b"keep"))
    # «Мусор», который не должен попасть в снимок
    (data / "video.mp4").write_bytes(b"x" * 2048)
    (data / "clip.mxf").write_bytes(b"x" * 2048)
    (data / "movie.mts").write_bytes(b"x" * 2048)
    (data / "card.JPG").write_bytes(b"x")
    (data / "in.partial").write_bytes(b"tmp")

    res = build_snapshot([str(data)], str(tmp_path / "out"))
    assert res.ok
    ok, _ = verify_snapshot(res.path)
    assert ok

    import tarfile
    with tarfile.open(res.path, "r:gz") as tar:
        names = tar.getnames()
    joined = " ".join(names).lower()
    for bad in (".mp4", ".mxf", ".mts", ".jpg", ".partial"):
        assert bad not in joined, f"{bad} попал в снимок данных"
    assert any("preset.dat" in n for n in names)


def test_core_operations_work_without_network(tmp_path, monkeypatch):
    """ТЗ п.4: сохранение/запись/проверка работают полностью офлайн.

    Жёстко блокируем любые попытки выйти в сеть — если бы ядро лезло в сеть,
    операция упала бы.
    """
    import socket

    def no_network(*a, **k):
        raise AssertionError("операция попыталась выйти в сеть")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)

    # Сохранить с карты
    lib = PresetLibrary(base_path=str(tmp_path / "base"))
    card = tmp_path / "card"
    card.mkdir()
    _card(str(card), name="PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT", data=_dat(b"v1"))
    plan = lib.plan_from_media("SonyFX3", str(card))
    rep = lib.save_from_media("Иван", "SonyFX3", "Основные", str(card), plan=plan)
    assert rep.ok, rep.message

    # Записать на карту + проверить
    version = lib.store.list_versions("Иван", "SonyFX3", "Основные")[0]
    target = tmp_path / "card2"
    target.mkdir()
    wrep = lib.write_version_to_card(version, str(target))
    assert wrep.ok, wrep.message
    verified = lib.verify_version_on_card(version, str(target))
    assert verified == [], f"офлайн-проверка не сошлась: {verified}"


# ===========================================================================
# 16. Копия после изменений и раз в сутки (ТЗ п.3)
# ===========================================================================

def test_backup_manager_coalesces_rapid_changes(tmp_path):
    """Быстрые последовательные изменения схлопываются в один снимок (ТЗ)."""
    from mastersetting.s3_backup import BackupManager

    data = tmp_path / "data"
    (data / "cameraman").mkdir(parents=True)
    (data / "cameraman" / "a.dat").write_bytes(b"x")

    bm = BackupManager([str(data)], str(tmp_path / "out"), seal_seconds=3600)
    first = bm.snapshot()
    second = bm.snapshot()  # слишком рано -> должен вернуть тот же снимок
    assert first.ok and second.ok
    assert first.path == second.path
    assert "объедин" in second.message.lower()


def test_flush_pending_sends_deferred_uploads(tmp_path):
    """Отложенные офлайн-снимки уходят, когда интернет вернулся (ТЗ)."""
    from mastersetting.s3_backup import BackupManager, build_snapshot

    data = tmp_path / "data"
    (data / "cameraman").mkdir(parents=True)
    (data / "cameraman" / "a.dat").write_bytes(b"x")

    out = tmp_path / "out"
    build_snapshot([str(data)], str(out))  # локальная копия, «ещё не отправлена»

    uploaded = {"n": 0}
    objects = []

    class FakeS3:
        def list_objects_v2(self, **kw):
            return {"Contents": list(objects)}

        def upload_file(self, path, bucket, key):
            uploaded["n"] += 1
            objects.append({"Key": key, "Size": 1,
                            "LastModified": __import__("datetime").datetime.now()})

    bm = BackupManager([str(data)], str(out), s3_client=FakeS3(), bucket="b")
    assert len(bm.pending_uploads()) == 1
    rep = bm.flush_pending()
    assert rep["sent"] and uploaded["n"] == 1
    assert rep["pending_left"] == 0


def test_trial_restore_does_not_touch_working_data(tmp_path):
    """Пробное восстановление распаковывает в отдельный каталог, данные целы (ТЗ)."""
    from mastersetting.s3_backup import BackupManager, build_snapshot

    data = tmp_path / "data"
    (data / "cameraman").mkdir(parents=True)
    (data / "cameraman" / "a.dat").write_bytes(_dat(b"v1"))
    snap = build_snapshot([str(data)], str(tmp_path / "out")).path

    class FakeS3:
        def download_file(self, bucket, key, dest):
            shutil.copy(snap, dest)

    bm = BackupManager([str(data)], str(tmp_path / "out"),
                       s3_client=FakeS3(), bucket="b")
    res = bm.trial_restore("mastersetting/backups/x.tar.gz",
                           str(tmp_path / "scratch"))
    assert res["ok"] is True and res["restored_files"] >= 1
    # Рабочие данные не тронуты
    assert (data / "cameraman" / "a.dat").read_bytes() == _dat(b"v1")


# ===========================================================================
# 17. Реальные образцы FX3/FX3A: нативные пути и парная запись (ТЗ п.2)
# ===========================================================================

REAL_FX3 = "/Users/sd/Desktop/Sony FX Drozdov/Settings/FX3/FX3.DAT"
REAL_FX3A = "/Users/sd/Desktop/Sony FX Drozdov/Settings/FX3A/FX3A.DAT"

# Нативные пути на карте Sony (подтверждены скриптами load.sh/load.ps1 и разбором образцов).
NATIVE_FX3 = "PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT"
NATIVE_FX3A = "PRIVATE/SONY/SETTING/FX3A/CAMSET/FX3A.DAT"

_has_real = os.path.exists(REAL_FX3) and os.path.exists(REAL_FX3A)


@pytest.mark.skipif(not _has_real, reason="нет реальных образцов FX3/FX3A")
def test_real_samples_accepted_by_signature():
    """Реальные файлы FX3.DAT и FX3A.DAT распознаются как настройки по сигнатуре."""
    from mastersetting.settings_rules import looks_like_settings_file

    assert looks_like_settings_file(REAL_FX3)
    assert looks_like_settings_file(REAL_FX3A)
    # Один и тот же размер, но содержимое различается по идентификатору модели.
    assert open(REAL_FX3, "rb").read() != open(REAL_FX3A, "rb").read()


def test_native_paths_do_not_conflict():
    """Ключевой вывод по п.2: нативные пути FX3 и FX3A не конфликтуют."""
    from mastersetting.library import find_path_conflicts

    assert find_path_conflicts({NATIVE_FX3: "a"}, {NATIVE_FX3A: "b"}) == []


@pytest.mark.skipif(not _has_real, reason="нет реальных образцов FX3/FX3A")
def test_pair_write_with_real_samples_to_native_paths(tmp_path, monkeypatch):
    """Парная запись реальных образцов на нативные пути: пишет оба, без конфликта.

    Это и есть проверка гипотезы ТЗ п.2 «пути совместимы»: два комплекта
    ложатся в РАЗНЫЕ папки и оба остаются на карте одновременно.
    """
    lib = PresetLibrary(base_path=str(tmp_path / "base"))
    lib.store.import_files("Иван", "SonyFX3", "Основные", {NATIVE_FX3: REAL_FX3})
    lib.store.import_files("Иван", "SonyFX3A", "Основные", {NATIVE_FX3A: REAL_FX3A})
    v3 = lib.store.list_versions("Иван", "SonyFX3", "Основные")[0]
    v3a = lib.store.list_versions("Иван", "SonyFX3A", "Основные")[0]

    # Шлюз подтверждён (в реальной работе — командой confirm-fx3-paths)
    monkeypatch.setattr(lib, "pair_paths_confirmed", lambda: True)
    monkeypatch.setattr(lib, "pair_write_available", lambda: True)

    card = tmp_path / "card"
    card.mkdir()
    rep = lib.write_pair_to_card(v3, v3a, str(card))
    assert rep.ok, rep.message

    fx3_on_card = card / "PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT"
    fx3a_on_card = card / "PRIVATE/SONY/SETTING/FX3A/CAMSET/FX3A.DAT"
    assert fx3_on_card.is_file(), "FX3 не записан на нативный путь"
    assert fx3a_on_card.is_file(), "FX3A не записан на нативный путь"
    # Оба файла одновременно и по своим байтам — ничего не затёрто
    assert fx3_on_card.read_bytes() == open(REAL_FX3, "rb").read()
    assert fx3a_on_card.read_bytes() == open(REAL_FX3A, "rb").read()
