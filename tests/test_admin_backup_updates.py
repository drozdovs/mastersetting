# -*- coding: utf-8 -*-
"""Тесты админ-безопасности, пар, S3-бекапов и обновлений."""

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mastersetting.admin_auth import (
    MAX_FAILED_ATTEMPTS,
    AdminAuth,
    SecretStore,
    hash_password,
    verify_password,
)
from mastersetting.fs_ops import hash_file
from mastersetting.pairs import PairError, PairStore, PresetPair
from mastersetting.s3_backup import (
    BackupManager,
    build_snapshot,
    cleanup_local_snapshots,
    verify_snapshot,
)
from mastersetting.updates import (
    Manifest,
    UpdateLog,
    check_for_update,
    verify_package,
)
from mastersetting.versioning import VersionStore


# ===========================================================================
# Пароль
# ===========================================================================

def test_password_hash_not_plaintext():
    h = hash_password("секрет")
    assert "секрет" not in h
    assert h.startswith("pbkdf2_sha256$")


def test_password_roundtrip():
    h = hash_password("пароль123")
    assert verify_password("пароль123", h)
    assert not verify_password("пароль124", h)


def test_two_hashes_differ_same_password():
    assert hash_password("x") != hash_password("x")  # разные соли


def test_verify_rejects_garbage():
    assert not verify_password("x", "not-a-hash")
    assert not verify_password("x", "")


def test_lockout_after_failures(tmp_path):
    auth = AdminAuth(state_path=str(tmp_path / "state.json"))
    h = hash_password("верно")
    for _ in range(MAX_FAILED_ATTEMPTS):
        assert auth.try_login("неверно", h) is False
    # Теперь блокировка
    from mastersetting.admin_auth import RateLimited
    with pytest.raises(RateLimited):
        auth.try_login("верно", h)
    assert auth.locked_for() > 0


def test_successful_login_resets(tmp_path):
    auth = AdminAuth(state_path=str(tmp_path / "state.json"))
    h = hash_password("верно")
    auth.try_login("неверно", h)
    assert auth.try_login("верно", h) is True
    assert auth.locked_for() == 0


def test_secret_store_roundtrip(tmp_path):
    store = SecretStore(fallback_path=str(tmp_path / "secrets.enc"))
    store._file_set("k", "значение")
    assert store._file_get("k") == "значение"


def test_secret_store_filename_has_no_plaintext(tmp_path, monkeypatch):
    # MS_SECRETS_FILE имеет приоритет над fallback_path — указываем его явно,
    # чтобы тест не зависел от окружения машины.
    target = tmp_path / "secrets.enc"
    monkeypatch.setenv("MS_SECRETS_FILE", str(target))
    store = SecretStore(fallback_path=str(target))
    store._file_set("s3_secret", "ОЧЕНЬ-СЕКРЕТНО")
    content = target.read_text(encoding="utf-8")
    assert "ОЧЕНЬ-СЕКРЕТНО" not in content  # хранится в base64, не открытым текстом


# ===========================================================================
# Пары FX3/FX3A
# ===========================================================================

def _lib_with_versions(tmp_path):
    store = VersionStore(base_path=str(tmp_path / "base"))
    src = tmp_path / "src.dat"
    src.write_bytes(b"SONY0" + b"\x00" * 10)
    v_fx3 = store.import_files("Иван", "SonyFX3", "Основные", {"PRIVATE/FX3.DAT": str(src)})
    v_fx3a = store.import_files("Иван", "SonyFX3A", "Основные", {"PRIVATE/FX3A.DAT": str(src)})
    return store, v_fx3.version_id, v_fx3a.version_id


def test_pair_complete(tmp_path):
    store, v3, v3a = _lib_with_versions(tmp_path)
    ps = PairStore(app_data_dir=str(tmp_path / "app"), version_store=store)
    pair = PresetPair(name="Основные", operator="Иван",
                      fx3_version_id=v3, fx3a_version_id=v3a)
    ps.upsert(pair)
    got = ps.get("Основные", "Иван")
    assert got is not None and got.is_complete


def test_pair_incomplete_is_allowed(tmp_path):
    store, v3, _ = _lib_with_versions(tmp_path)
    ps = PairStore(app_data_dir=str(tmp_path / "app"), version_store=store)
    ps.upsert(PresetPair(name="Интервью", operator="Иван", fx3_version_id=v3))
    got = ps.get("Интервью", "Иван")
    assert got is not None and not got.is_complete
    assert got.missing_slots() == ["FX3A"]


def test_pair_rejects_missing_version(tmp_path):
    store, _, _ = _lib_with_versions(tmp_path)
    ps = PairStore(app_data_dir=str(tmp_path / "app"), version_store=store)
    with pytest.raises(PairError):
        ps.upsert(PresetPair(name="X", operator="Иван", fx3_version_id="нет-такой"))


def test_pair_rejects_wrong_family(tmp_path):
    """FX3A-версия не должна попадать в слот FX3."""
    store, v3, v3a = _lib_with_versions(tmp_path)
    ps = PairStore(app_data_dir=str(tmp_path / "app"), version_store=store)
    with pytest.raises(PairError):
        ps.upsert(PresetPair(name="X", operator="Иван", fx3_version_id=v3a))


def test_pair_version_does_not_drift(tmp_path):
    """При добавлении новой версии FX3 выбранная в паре не меняется."""
    store, v3, v3a = _lib_with_versions(tmp_path)
    ps = PairStore(app_data_dir=str(tmp_path / "app"), version_store=store)
    ps.upsert(PresetPair(name="Основные", operator="Иван",
                         fx3_version_id=v3, fx3a_version_id=v3a))
    # Новая версия FX3
    src = tmp_path / "new.dat"
    src.write_bytes(b"SONY0" + b"NEW" * 10)
    store.import_files("Иван", "SonyFX3", "Основные", {"PRIVATE/FX3.DAT": str(src)})
    got = ps.get("Основные", "Иван")
    assert got.fx3_version_id == v3  # не «уплыла» на новую


def test_pair_persists(tmp_path):
    store, v3, v3a = _lib_with_versions(tmp_path)
    app = str(tmp_path / "app")
    ps = PairStore(app_data_dir=app, version_store=store)
    ps.upsert(PresetPair(name="П1", operator="Иван", fx3_version_id=v3))
    ps2 = PairStore(app_data_dir=app, version_store=store)
    assert ps2.get("П1", "Иван") is not None


# ===========================================================================
# S3-бекапы
# ===========================================================================

def _data_dirs(tmp_path):
    d1 = tmp_path / "base"
    (d1 / "cameraman" / "Иван").mkdir(parents=True)
    (d1 / "cameraman" / "Иван" / "f.dat").write_bytes(b"SONY0data")
    d2 = tmp_path / "appdata"
    d2.mkdir()
    (d2 / "catalog.db").write_bytes(b"sqlite")
    # Секреты и мусор, которые НЕ должны попасть
    (d2 / "config.json").write_text(json.dumps({"server_token": "СЕКРЕТ"}), encoding="utf-8")
    (d2 / "secrets.enc").write_text("keys", encoding="utf-8")
    return [str(d1), str(d2)]


def test_snapshot_excludes_secrets_and_binary(tmp_path):
    dirs = _data_dirs(tmp_path)
    res = build_snapshot(dirs, str(tmp_path / "out"))
    assert res.ok
    import tarfile
    with tarfile.open(res.path, "r:gz") as tar:
        names = tar.getnames()
    assert any("f.dat" in n for n in names)
    assert any("catalog.db" in n for n in names)
    assert not any("secrets.enc" in n for n in names)
    # ТЗ: конфигурацию копируем, но БЕЗ секретов. Конфиг с токеном не выпадает
    # целиком — в снимке лежит его очищенная версия без секретных полей.
    cfg = [n for n in names if n.endswith("config.json")]
    assert cfg, "очищенный config.json должен попадать в снимок"
    with tarfile.open(res.path, "r:gz") as tar:
        data = json.loads(tar.extractfile(cfg[0]).read().decode("utf-8"))
    assert isinstance(data, dict)
    assert "server_token" not in data, "секрет утёк в снимок"


def test_snapshot_keeps_non_secret_config_fields(tmp_path):
    """Путь данных и прочие настройки не теряются при копировании (ТЗ)."""
    d = tmp_path / "appdata"
    d.mkdir()
    (d / "config.json").write_text(json.dumps({
        "base_path": "/data/lib", "app_version": "2.0.0",
        "s3_secret": "TOP-SECRET", "s3_access_key": "AKIA"}),
        encoding="utf-8")
    res = build_snapshot([str(d)], str(tmp_path / "out"))
    import tarfile
    with tarfile.open(res.path, "r:gz") as tar:
        name = [n for n in tar.getnames() if n.endswith("config.json")][0]
        data = json.loads(tar.extractfile(name).read().decode("utf-8"))
    assert data["base_path"] == "/data/lib"
    assert data["app_version"] == "2.0.0"
    assert "s3_secret" not in data and "s3_access_key" not in data


def test_snapshot_verified(tmp_path):
    dirs = _data_dirs(tmp_path)
    res = build_snapshot(dirs, str(tmp_path / "out"))
    ok, msg = verify_snapshot(res.path)
    assert ok, msg


def test_cleanup_retention(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    old = out / "ms-snapshot-20200101-000000.tar.gz"
    old.write_bytes(b"x")
    os.utime(old, (time.time() - 200 * 86400,) * 2)
    fresh = out / "ms-snapshot-20990101-000000.tar.gz"
    fresh.write_bytes(b"x")
    removed = cleanup_local_snapshots(str(out), retention_days=90)
    assert str(old) in removed
    assert fresh.exists()


def test_upload_defers_when_offline(tmp_path):
    """Сеть недоступна -> отправка отложена, без потери локального снимка."""
    dirs = _data_dirs(tmp_path)
    bm = BackupManager(dirs, str(tmp_path / "out"), s3_client=None, bucket="")

    class FailingS3:
        def upload_file(self, *a, **k):
            raise ConnectionError("нет сети")

    bm.s3 = FailingS3()
    bm.bucket = "b"
    res = bm.snapshot(force=True)
    up = bm.upload(res, max_attempts=1)
    assert up.ok is False
    assert up.deferred is True
    assert os.path.exists(res.path)  # локальный снимок сохранён


def test_upload_success_with_fake_s3(tmp_path):
    dirs = _data_dirs(tmp_path)
    uploaded = {}

    class FakeS3:
        def upload_file(self, path, bucket, key):
            uploaded["key"] = key

    bm = BackupManager(dirs, str(tmp_path / "out"), s3_client=FakeS3(), bucket="b")
    res = bm.snapshot(force=True)
    up = bm.upload(res)
    assert up.ok and "ms-snapshot-" in uploaded["key"]


def test_snapshot_merges_fast_changes(tmp_path):
    dirs = _data_dirs(tmp_path)
    bm = BackupManager(dirs, str(tmp_path / "out"), seal_seconds=60)
    r1 = bm.snapshot()
    r2 = bm.snapshot()  # слишком быстро -> объединение
    assert r1.path == r2.path
    assert "объединены" in r2.message


# ===========================================================================
# Обновления
# ===========================================================================

def test_update_requires_valid_signature(tmp_path):
    m = Manifest(version="9.9.9", platform=_this_platform_str(),
                 filename="pkg.zip", sha256="abc")
    check = check_for_update("2.0.0", m, public_key_b64="нет-ключа")
    assert check.status == "unverified"
    assert check.verified is False


def test_package_hash_mismatch_rejected(tmp_path):
    m = Manifest(version="9.9.9", platform="x", filename="p.zip", sha256="неверно")
    ok, msg = verify_package(__file__, m, "ключ")
    assert ok is False


def test_auto_check_offline_is_silent(tmp_path, monkeypatch):
    """Автопроверка без интернета не падает и не выдаёт «обновление есть»."""
    from mastersetting import updates

    # https-адрес, до которого заведомо нет доступа в тесте -> offline
    monkeypatch.setattr(updates, "fetch_manifest_text",
                        lambda url, timeout=8.0: (_ for _ in ()).throw(
                            updates.UpdateError("нет сети")))
    res = updates.auto_check("2.0.0", "https://example.invalid/m.json",
                             public_key_b64="key")
    assert res.status == "offline"
    assert res.verified is False


def test_auto_check_rejects_non_https():
    from mastersetting import updates

    res = updates.auto_check("2.0.0", "http://insecure/m.json", "key")
    assert res.status == "offline"
    assert "https" in res.message.lower()


def test_auto_check_skips_without_channel():
    from mastersetting import updates

    res = updates.auto_check("2.0.0", "", "")
    assert res.status == "skipped"


def test_auto_check_valid_signature_reports_available(monkeypatch):
    """С верной подписью и более новой версией автопроверка видит обновление."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from mastersetting import updates

    sk = Ed25519PrivateKey.generate()
    priv = base64.b64encode(sk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption())).decode()
    pub = base64.b64encode(sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)).decode()

    m = updates.Manifest(version="9.9.9", platform=updates._this_platform(),
                         filename="pkg.zip", sha256="abc123")
    m = updates.sign_manifest(m, priv)
    monkeypatch.setattr(updates, "fetch_manifest_text",
                        lambda url, timeout=8.0: m.to_json())
    res = updates.auto_check("2.0.0", "https://example.invalid/m.json", pub)
    assert res.status == "available"
    assert res.verified is True


def test_newer_version_detected():
    m = Manifest(version="2.5.0", platform=_this_platform_str(),
                 filename="p", sha256="x")
    # без подписи -> unverified (и это ожидаемо безопасно)
    check = check_for_update("2.0.0", m, "key")
    assert check.status == "unverified"


def test_older_version_no_update():
    m = Manifest(version="1.0.0", platform=_this_platform_str(),
                 filename="p", sha256="x")
    check = check_for_update("2.0.0", m, "key")
    # до проверки подписи статус может быть up_to_date или unverified в зависимости от порядка
    assert check.status in ("up_to_date", "unverified")


def test_update_log_records():
    log = UpdateLog()
    log.add("install", "2.1.0", ok=True, message="успешно")
    log.add("rollback", "2.0.0", ok=True)
    assert len(log.entries) == 2
    assert "2.1.0" in log.to_json()


def test_apply_manual_update_rejects_bad_signature(tmp_path):
    """ТЗ: нельзя готовить к запуску пакет без доверенной подписи."""
    from mastersetting import updates

    pkg = tmp_path / "pkg.bin"
    pkg.write_bytes(b"real payload")
    bad = updates.Manifest(version="9.9.9", platform=updates._this_platform(),
                           filename="pkg.bin", sha256=hash_file(str(pkg)),
                           signature="ПОДДЕЛКА")
    ok, msg = updates.apply_manual_update(str(pkg), bad, "pubkey", str(tmp_path / "out"))
    assert ok is False and "отклон" in msg.lower()


def test_apply_manual_update_stages_verified_package(tmp_path):
    """С верной подписью пакет выкладывается в каталог обновлений, но не запускается."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from mastersetting import updates

    sk = Ed25519PrivateKey.generate()
    priv = base64.b64encode(sk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption())).decode()
    pub = base64.b64encode(sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)).decode()

    pkg = tmp_path / "setup.exe"
    pkg.write_bytes(b"installer bytes")
    m = updates.Manifest(version="9.9.9", platform=updates._this_platform(),
                         filename="setup.exe", sha256=hash_file(str(pkg)))
    m = updates.sign_manifest(m, priv)

    out = tmp_path / "updates"
    ok, target = updates.apply_manual_update(str(pkg), m, pub, str(out))
    assert ok is True
    assert os.path.isfile(target)
    assert open(target, "rb").read() == pkg.read_bytes()


def test_sign_must_be_verified_even_if_hash_matches(tmp_path):
    """Обладатель ключа записи подменил файл — хеш совпадает, подпись нет."""
    from mastersetting import updates

    pkg = tmp_path / "p.bin"
    pkg.write_bytes(b"x" * 50)
    m = updates.Manifest(version="9.9.9", platform=updates._this_platform(),
                         filename="p.bin", sha256=hash_file(str(pkg)),
                         signature="")
    ok, msg = updates.verify_package(str(pkg), m, "any")
    assert ok is False and msg


def _this_platform_str() -> str:
    from mastersetting.updates import _this_platform
    return _this_platform()
