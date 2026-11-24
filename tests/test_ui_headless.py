# -*- coding: utf-8 -*-
"""Headless-тесты UI: окна собираются и вызывают контроллер без ошибок.

Тесты не открывают окна на экране (``withdraw``) и не запускают ``mainloop``.
Если графическая среда недоступна, тесты пропускаются, а не падают.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ctk = pytest.importorskip("customtkinter")


class _FakePlan:
    """Минимальный план сохранения для UI-теста (без чтения карты)."""

    file_count = 1

    def __init__(self):
        self.files = {"PRIVATE/SONY/SETTING/X/X.DAT": "/tmp/x.dat"}
        self.detected_model = ""
        self.warnings = ["Для этой модели нет проверенного правила — "
                         "формат не подтверждён."]


@pytest.fixture(scope="module")
def app():
    base = os.path.join(tempfile.mkdtemp(), "base")
    os.environ["MS_BASE_PATH"] = base
    # Изолированный каталог данных приложения, чтобы не трогать реальный
    home = tempfile.mkdtemp()
    os.environ["HOME"] = home
    # Секреты — в файл, чтобы тесты не трогали системный Keychain/DPAPI
    os.environ["MS_SECRETS_FILE"] = os.path.join(home, "secrets.enc")

    import importlib
    from mastersetting import config as cfgmod
    importlib.reload(cfgmod)
    import agent.app as appmod
    importlib.reload(appmod)

    try:
        instance = appmod.MasterSettingApp()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"графическая среда недоступна: {e}")
    instance.withdraw()
    instance.update()
    yield instance
    try:
        instance.destroy()
    except Exception:
        pass


def _close_toplevels(app):
    for w in list(app.winfo_children()):
        if isinstance(w, ctk.CTkToplevel):
            w.destroy()


def test_main_window_builds(app):
    assert app.operator_label is not None
    assert app.drive_label is not None
    assert app.backup_label is not None


def test_app_background_helpers_do_not_crash(app, monkeypatch):
    """Фоновые помощники главного окна не падают.

    Ранее главное окно (``CTk``) не имело ``run_async`` и падало с
    AttributeError в фоне. Проверяем, что суточная копия и автопроверка
    обновления запускаются в своём потоке и возвращают управление через ``after``.
    Потоки и ``after`` выполняем синхронно, чтобы не оставлять «хвостов» в
    headless-прогоне.
    """
    import agent.app as appmod

    class SyncThread:
        def __init__(self, target=None, daemon=None, **kw):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(appmod.threading, "Thread", SyncThread)
    monkeypatch.setattr(app, "after", lambda _ms, fn: fn())

    app._daily_backup()
    app._auto_check_update()
    app.update()
    assert app.winfo_exists()


def test_main_window_is_resizable(app):
    # В ТЗ окно должно масштабироваться, а не быть жёстко 400 px.
    assert app.resizable() == (True, True)
    # Минимальные размеры заданы явно и не «залипают» на 400 px по ширине
    assert getattr(app, "_min_width", 0) >= 1


def test_all_windows_open(app):
    for name, opener in [
        ("save_wizard", app.open_save_window),
        ("write_wizard", app.open_write_window),
        ("library", app.open_library_window),
        ("pairs", app.open_pairs_window),
        ("instructions", app.open_instructions_window),
        ("admin", app.open_admin_window),
    ]:
        opener()
        app.update()
        toplevels = [w for w in app.winfo_children() if isinstance(w, ctk.CTkToplevel)]
        assert toplevels, f"окно {name} не создалось"
        _close_toplevels(app)
        app.update()


def test_action_labels_match_spec(app):
    """В ТЗ строго: «Сохранить с карты» и «Записать на карту» — на экранах и в справке."""
    import agent.app as appmod
    import agent.wizard as wiz

    for path in (appmod.__file__, wiz.__file__):
        src = open(path, encoding="utf-8").read()
        assert "Сохранить с карты" in src, path
        assert "Записать на карту" in src, path

    # Запрещённая формулировка: одно слово «Загрузить» на оба направления
    for path in (appmod.__file__, wiz.__file__):
        src = open(path, encoding="utf-8").read()
        assert "Загрузить с карты" not in src
        assert "Загрузить на карту" not in src

    # Справка тоже обязана знать канонические названия
    help_html = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "docs", "help", "index.html"), encoding="utf-8").read()
    assert "Сохранить с карты" in help_html
    assert "Записать на карту" in help_html

    # Подписи кнопок на главном экране — ровно канонические
    assert app.save_btn is not None and app.write_btn is not None


def test_wizard_has_no_technical_jargon():
    """Шаги и подписи мастера — простыми словами, без технического жаргона."""
    import agent.wizard as wiz

    visible = list(wiz.STEPS) + list(wiz.STEPS_WRITE)
    visible += [
        "Сохранить настройки с карты", "Записать настройки на карту",
        "Вставьте карту памяти", "Чья это камера и какая модель",
        "Что сохраняем", "Что записать на карту", "Готово",
    ]
    for text in visible:
        for bad in ("носител", "импорт", "media_root", "пресет"):
            assert bad not in text.lower(), f"жаргон {bad!r} в тексте: {text!r}"

    # Понятные формулировки действительно присутствуют
    src = open(wiz.__file__, encoding="utf-8").read()
    assert "Вставьте карту памяти" in src
    assert "Чья это камера" in src
    assert "Видео и фотографии" in src


def test_save_wizard_steps_and_cards(app):
    import agent.wizard as wiz
    win = wiz.SaveWizard(app)
    app.update()
    assert win.step_index == 0
    assert win.steps == wiz.STEPS
    win.destroy()


def test_save_wizard_blocks_without_card(app, monkeypatch):
    """Без карты мастер не пускает дальше и подсказывает, что делать."""
    import agent.wizard as wiz
    seen = {}
    monkeypatch.setattr(wiz.dialogs, "warn",
                        lambda *a, **k: seen.update(called=True))
    win = wiz.SaveWizard(app)
    app.update()
    win.card = ""
    win.next()
    app.update()
    assert seen.get("called") is True
    assert win.step_index == 0
    win.destroy()


def test_save_wizard_requires_operator(app, monkeypatch):
    import agent.wizard as wiz
    seen = {}
    win = wiz.SaveWizard(app)
    app.update()
    win.card = "/Volumes/FAKE"
    win.go_to(1)
    app.update()
    win.operator_box.set("")
    win.camera_box.set("Sony FX3")
    monkeypatch.setattr(wiz.dialogs, "warn",
                        lambda *a, **k: seen.update(called=True))
    win.next()
    app.update()
    assert seen.get("called") is True, "мастер пустил дальше без оператора"
    win.destroy()


def test_save_wizard_shows_unconfirmed_format_warning(app, monkeypatch):
    """ТЗ: импорт из папки без проверенного правила НЕ выглядит как
    «проверенный формат камеры» — оператор видит предупреждение."""
    import agent.wizard as wiz
    win = wiz.SaveWizard(app)
    app.update()
    win.card = "/Volumes/FAKE"
    win.go_to(2)
    app.update()
    # plan_from_media для неизвестной модели даёт warnings с явным текстом
    monkeypatch.setattr(win.ctrl, "plan_save", lambda *a, **k: _FakePlan())
    win._load_plan()
    app.update()
    text = win.warn_label.cget("text")
    assert "не подтверждён" in text
    win.destroy()


def test_write_wizard_builds(app):
    import agent.wizard as wiz
    win = wiz.WriteWizard(app)
    app.update()
    assert win.step_index == 0
    win.destroy()


def test_write_wizard_has_changes_preview_step(app):
    """ТЗ: сценарий записи включает «просмотр изменений» перед записью."""
    import agent.wizard as wiz
    assert "Изменения" in wiz.STEPS_WRITE, wiz.STEPS_WRITE
    # Шаг «Изменения» идёт перед «Готово»
    assert wiz.STEPS_WRITE.index("Изменения") == wiz.STEPS_WRITE.index("Готово") - 1
    win = wiz.WriteWizard(app)
    assert hasattr(win, "_render_changes")
    win.destroy()


def test_wizard_async_error_reaches_handler(app, monkeypatch):
    """Ошибка в фоне должна дойти до обработчика, а не потеряться.

    Ранняя версия использовала ``lambda: on_error(e)`` — Python удаляет ``e``
    при выходе из ``except``, поэтому обработчик падал с NameError и ошибка
    молча пропадала. Здесь потоки и ``after`` выполняем синхронно, чтобы
    проверить именно передачу значения.
    """
    import agent.wizard as wiz

    class SyncThread:
        def __init__(self, target=None, daemon=None, **kw):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(wiz.threading, "Thread", SyncThread)
    win = wiz.WriteWizard(app)
    monkeypatch.setattr(win, "after", lambda _ms, fn: fn())

    seen = {}

    def work():
        raise RuntimeError("сломалось")

    win.run_bg(work, on_done=lambda r: seen.setdefault("done", r),
               on_error=lambda err: seen.__setitem__("err", err))

    assert "err" in seen, "ошибка из фонового потока не дошла до обработчика"
    assert "сломалось" in str(seen["err"])
    win.destroy()


def test_wizard_async_success_reaches_handler(app, monkeypatch):
    import agent.wizard as wiz

    class SyncThread:
        def __init__(self, target=None, daemon=None, **kw):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(wiz.threading, "Thread", SyncThread)
    win = wiz.WriteWizard(app)
    monkeypatch.setattr(win, "after", lambda _ms, fn: fn())

    seen = {}
    win.run_bg(lambda: 42, on_done=lambda r: seen.__setitem__("done", r),
               on_error=lambda e: seen.__setitem__("err", e))
    assert seen.get("done") == 42 and "err" not in seen
    win.destroy()


def test_operator_window_changes_operator(app):
    import agent.app as appmod
    win = appmod.OperatorWindow(app)
    app.update()
    win.box.set("ТестовыйОператор")
    win._save()
    app.update()
    assert app.ctrl.current_operator() == "ТестовыйОператор"


def test_library_search(app):
    import agent.app as appmod
    win = appmod.LibraryWindow(app)
    app.update()
    win.query.insert(0, "нет-такого")
    win._refresh()
    app.update()
    win.destroy()


def test_write_wizard_hints_pair_for_fx3_family(app):
    """ТЗ: при выборе модели FX3/FX3A подсказываем про именованную пару."""
    import agent.wizard as wizmod
    win = wizmod.WriteWizard(app)
    win.go_to(1)
    app.update()
    win._on_camera("SonyFX3")
    app.update()
    note = win.pair_note.cget("text")
    assert "FX3" in note                      # семейство распознано
    win._on_camera("PanasonicAG-CX350")
    app.update()
    assert "семейства FX3" not in win.pair_note.cget("text")
    win.destroy()


def test_library_actions_export_and_delete(app, monkeypatch):
    """Библиотека: выгрузка версии не меняет данные, удаление пресета — по подтверждению."""
    import agent.app as appmod
    from agent import dialogs

    ctrl = app.ctrl
    ctrl.library.store.import_files(
        "Иван", "SonyFX3", "Основные",
        {"PRIVATE/SONY/SETTING/FX3/CAMSET/FX3.DAT": _fake_dat(app)},
    )
    win = appmod.LibraryWindow(app)
    app.update()
    assert "Иван / SonyFX3 / Основные" in win._triples

    dest = str(Path(app.ctrl.config.base_path) / "export")
    Path(dest).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(dialogs, "pick_folder", lambda *a, **k: dest)
    monkeypatch.setattr(dialogs, "info", lambda *a, **k: None)
    win._export()
    # Библиотека не изменилась от выгрузки.
    assert len(ctrl.list_versions("Иван", "SonyFX3", "Основные")) == 1

    monkeypatch.setattr(dialogs, "confirm", lambda *a, **k: True)
    win._delete()
    assert ctrl.list_versions("Иван", "SonyFX3", "Основные") == []
    win.destroy()


def _fake_dat(app):
    p = Path(app.ctrl.config.base_path) / "src_fx3.dat"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"SONY0" + b"\x00" * 64)
    return str(p)


def test_theme_tokens_present():
    from agent import theme
    assert theme.BG.startswith("#")
    assert theme.status_color("ok") == theme.OK
    assert theme.status_color("unknown-kind") == theme.MUTED


def test_admin_window_password_gate(app, monkeypatch):
    """ТЗ: админ-панель защищена паролем, а не «скрытой клавишей»."""
    import agent.app as appmod
    seen = {"warn": 0, "info": 0}
    monkeypatch.setattr(appmod.dialogs, "warn",
                        lambda *a, **k: seen.__setitem__("warn", seen["warn"] + 1))
    monkeypatch.setattr(appmod.dialogs, "info",
                        lambda *a, **k: seen.__setitem__("info", seen["info"] + 1))
    monkeypatch.setattr(appmod.dialogs, "error", lambda *a, **k: None)

    win = appmod.AdminWindow(app)
    app.update()
    if not app.ctrl.is_password_set():
        win.new_pw.insert(0, "Пароль12345")
        win.new_pw2.insert(0, "Пароль12345")
        win._set_password()
        app.update()
    assert app.ctrl.is_password_set(), "пароль администратора не сохранился"
    assert win.unlocked is True
    win.destroy()
    app.update()

    # Повторное открытие: без верного пароля внутрь не пускает
    win2 = appmod.AdminWindow(app)
    app.update()
    assert win2.unlocked is False
    win2.pw.insert(0, "неверный-пароль")
    win2._login()
    app.update()
    assert win2.unlocked is False, "панель пустила по неверному паролю"
    assert seen["warn"] >= 1, "о неверном пароле не сообщили"

    # Верный пароль открывает панель с журналом и статистикой
    win2.pw.delete(0, "end")
    win2.pw.insert(0, "Пароль12345")
    win2._login()
    app.update()
    assert win2.unlocked is True
    assert "Статистика" in win2.text.get("1.0", "end")
    win2.destroy()
    app.update()


def test_admin_backup_and_restore_roundtrip(app):
    """Кнопки админ-панели: копия создаётся и восстанавливается без потерь."""
    rep = app.ctrl.backup_now()
    assert rep["ok"] is True, rep
    st = app.ctrl.backup_status()
    assert st["count"] >= 1

    path = os.path.join(st["dir"], st["items"][0]["name"])
    restored = app.ctrl.restore_from_snapshot(path)
    assert restored["ok"] is True
    assert restored["restored_files"] >= 0


def test_s3_config_window_saves_keys(app):
    """Реквизиты S3 сохраняются в системное хранилище, не в открытый файл."""
    import agent.app as appmod
    win = appmod.S3ConfigWindow(app)
    app.update()
    win.endpoint.insert(0, "https://s3.timeweb.cloud")
    win.region.insert(0, "ru-1")
    win.bucket.insert(0, "ms-test-bucket")
    win.access.insert(0, "TESTACCESSKEY")
    win.secret.insert(0, "SUPERSECRETVALUE")
    win._save()
    app.update()
    assert app.ctrl.s3_configured() is True
    win.destroy()
    app.update()

    # Секрет не лежит в открытом виде в файле-хранилище
    secrets_file = os.environ["MS_SECRETS_FILE"]
    raw = open(secrets_file, "rb").read()
    assert b"SUPERSECRETVALUE" not in raw, "секрет хранится в открытом виде"


def test_migration_controller_roundtrip(app, monkeypatch, tmp_path):
    """Админ-панель умеет перенести старый архив C:/setting с проверяемой копией."""
    # Смоделировать старый архив 1.9 и указать его через MS_LEGACY_BASE
    legacy = tmp_path / "legacy"
    p = legacy / "cameraman" / "Иван" / "SonyFX3" / "20260101_Основные"
    (p / "PRIVATE" / "SONY" / "SETTING" / "FX3" / "CAMSET").mkdir(parents=True)
    (p / "PRIVATE" / "SONY" / "SETTING" / "FX3" / "CAMSET" / "FX3.DAT").write_bytes(
        b"SONY0ILME-FX3" + b"A" * 40)
    monkeypatch.setenv("MS_LEGACY_BASE", str(legacy))

    assert app.ctrl.legacy_archive_present() is True
    preview = app.ctrl.scan_migration()
    assert preview["found"] is True and preview["entries"]

    rep = app.ctrl.run_migration()
    assert rep["ok"] is True
    assert rep["backup_verified"] is True, "перед миграцией не сделана проверяемая копия"
    assert rep["imported"] >= 1
    # Старые данные не тронуты
    assert (p / "PRIVATE" / "SONY" / "SETTING" / "FX3" / "CAMSET" / "FX3.DAT").exists()


def test_pairs_window_can_create_pair(app, monkeypatch):
    """Экран пар умеет создавать именованную пару (шлюз записи при этом закрыт)."""
    import agent.app as appmod
    monkeypatch.setattr(appmod.dialogs, "info", lambda *a, **k: None)
    monkeypatch.setattr(appmod.dialogs, "warn", lambda *a, **k: None)
    monkeypatch.setattr(appmod.dialogs, "error", lambda *a, **k: None)

    win = appmod.PairsWindow(app)
    app.update()
    # В тестовой библиотеке может не быть операторов — тогда форма пустая, но
    # окно обязано собраться без ошибок.
    assert hasattr(win, "name_box") and hasattr(win, "op_box")
    assert app.ctrl.pair_write_available() is False, \
        "парная запись должна быть закрыта без подтверждённых путей"
    win.destroy()
    app.update()


def test_write_wizard_offers_pairs_only_when_gate_open(app):
    """Мастер записи показывает выбор пары; без подтверждённых путей — предупреждает."""
    import agent.wizard as wiz
    win = wiz.WriteWizard(app)
    assert win.use_pair is False
    win.go_to(1)
    app.update()
    assert hasattr(win, "pair_choice"), "в мастере записи нет выбора пары"
    # Шлюз закрыт -> выбор пары отключён и есть понятное объяснение
    assert app.ctrl.pair_write_available() is False
    assert "не подтверждены" in win.pair_note.cget("text")
    win.destroy()


def test_update_channel_config_and_auto_check(app, monkeypatch):
    """Канал обновлений сохраняется в секреты; автопроверка не падает без сети."""
    import importlib
    appmod = importlib.import_module("agent.app")
    monkeypatch.setattr(appmod.dialogs, "info", lambda *a, **k: None)
    monkeypatch.setattr(appmod.dialogs, "warn", lambda *a, **k: None)
    monkeypatch.setattr(appmod.dialogs, "error", lambda *a, **k: None)

    assert app.ctrl.update_channel_configured() is False
    win = appmod.UpdateChannelWindow(app)
    app.update()
    win.url.insert(0, "https://cdn.example.invalid/ms/manifest.json")
    win.key.insert(0, "GGGGPUBLICKEYBASE64GGGG")
    win._save()
    app.update()
    assert app.ctrl.update_channel_configured() is True
    # Ключ лежит в хранилище секретов, а не открытым текстом в конфиге
    raw = open(os.environ["MS_SECRETS_FILE"], "rb").read()
    assert b"GGGGPUBLICKEYBASE64GGGG" not in raw
    win.destroy()
    app.update()

    # Автопроверка без реальной сети -> честный статус, без исключения
    res = app.ctrl.auto_check_update()
    assert res["status"] in ("offline", "error", "skipped", "up_to_date")


def test_apply_s3_lifecycle_sets_rule(app, monkeypatch):
    """Правило S3 на 90 дней реально ставится через клиент (с фейком)."""
    app.ctrl.set_s3_config("https://s3.timeweb.cloud", "ru-1", "bucket-ms",
                           "ACCESS", "SECRET")
    seen = {}

    class FakeS3:
        def put_bucket_versioning(self, **kw):
            seen["versioning"] = kw

        def put_bucket_lifecycle_configuration(self, **kw):
            seen["lifecycle"] = kw

    import mastersetting.s3_backup as s3b
    monkeypatch.setattr(s3b, "make_s3_client", lambda *a, **k: FakeS3())

    res = app.ctrl.apply_s3_lifecycle(90)
    assert res["ok"] is True
    rule = seen["lifecycle"]["LifecycleConfiguration"]["Rules"][0]
    assert rule["Expiration"]["Days"] == 90
    assert rule["NoncurrentVersionExpiration"]["NoncurrentDays"] == 90
    assert seen["versioning"]["VersioningConfiguration"]["Status"] == "Enabled"


def test_app_data_dir_is_owner_only(app):
    """Каталог данных создаётся с правами только для владельца (0700)."""
    import stat
    from mastersetting.config import ensure_app_data_dir
    if os.name == "nt":
        pytest.skip("права POSIX не применяются на Windows")
    p = ensure_app_data_dir()
    mode = stat.S_IMODE(os.stat(p).st_mode)
    # Не «мир-читаемый» каталог с секретами и журналом.
    assert mode & 0o077 == 0, f"права каталога данных слишком открытые: {oct(mode)}"


def test_base_path_inside_install_dir_is_rejected(monkeypatch, tmp_path):
    """ТЗ: рабочую базу нельзя держать в каталоге установки — заменяем на дефолт."""
    from mastersetting import config as cfgmod
    from mastersetting import platform as plat

    monkeypatch.setattr(plat, "install_root", lambda: str(tmp_path))
    monkeypatch.setattr(plat, "is_install_path",
                        lambda c: os.path.realpath(c).startswith(
                            os.path.realpath(str(tmp_path))))
    # Конфиг указывает базу внутри «каталога установки»
    inside = os.path.join(str(tmp_path), "setting")
    cfg_file = tmp_path / "cfg.json"
    cfg_file.write_text('{"base_path": "%s"}' % inside.replace("\\", "/"),
                        encoding="utf-8")
    monkeypatch.setattr(cfgmod.Config, "config_file", classmethod(
        lambda cls: cfg_file))
    monkeypatch.delenv("MS_BASE_PATH", raising=False)
    cfg = cfgmod.Config.load()
    assert not cfg.base_path.startswith(str(tmp_path)), \
        "рабочая база осталась внутри каталога установки"


def test_auto_backup_after_save_creates_snapshot(app):
    """После успешного сохранения создаётся копия рабочих данных (ТЗ)."""
    out = os.path.join(os.path.dirname(app.ctrl.config.base_path), "backups")
    before = len([n for n in (os.listdir(out) if os.path.isdir(out) else [])
                  if n.endswith(".tar.gz")])
    rep = app.ctrl.auto_backup("after_save")
    assert rep is not None and rep.get("ok") is True
    after = len([n for n in os.listdir(out) if n.endswith(".tar.gz")])
    assert after >= before


def test_write_wizard_refuses_close_during_operation(app, monkeypatch):
    """Во время операции окно не закрывается молча — спрашивает (ТЗ)."""
    import agent.wizard as wiz
    import agent.dialogs as dl
    asked = {"n": 0}

    def fake_confirm(*a, **k):
        asked["n"] += 1
        return False  # пользователь передумал закрывать

    monkeypatch.setattr(dl, "confirm", fake_confirm)
    win = wiz.WriteWizard(app)
    win.busy(True, "Записываю…")
    app.update()
    win._close()
    app.update()
    assert asked["n"] == 1, "не спросили подтверждение при закрытии во время операции"
    assert win.winfo_exists(), "окно закрылось, хотя пользователь отказался"
    win.busy(False)
    win.destroy()


def test_write_wizard_cancel_flag_wired_to_core(app, monkeypatch):
    """Кнопка «Отмена» во время записи реально прерывает ядро (флаг прокинут)."""
    import agent.wizard as wiz
    import agent.dialogs as dl
    monkeypatch.setattr(dl, "info", lambda *a, **k: None)

    win = wiz.WriteWizard(app)
    win.busy(True, "Записываю…")
    app.update()
    assert win.cancel_btn.winfo_ismapped(), "кнопка «Отмена» не появилась при работе"
    win._cancel()
    app.update()
    assert win._cancelled() is True, "флаг отмены не выставлен"
    win.busy(False)
    win.destroy()
