"""settings.json is written safely and a damaged file falls back to the backup."""

import json


def _fresh():
    from clipasso_studio.gui import app_settings as module

    module._instance = None
    return module.app_settings()


def test_save_replaces_the_file_and_keeps_a_backup(user_data):
    from clipasso_studio import paths

    s = _fresh()
    s.set("theme", "light")
    path = paths.app_settings_file()
    assert json.loads(path.read_text(encoding="utf-8"))["theme"] == "light"
    assert not path.with_name(path.name + ".tmp").exists()
    s2 = _fresh()  # a start with a good file writes the backup
    assert s2.get("theme") == "light"
    assert json.loads(path.with_name(path.name + ".bak").read_text(encoding="utf-8"))["theme"] == "light"


def test_a_damaged_file_falls_back_to_the_backup(user_data):
    from clipasso_studio import paths

    s = _fresh()
    s.set("models_dir", "D:/models")
    _fresh()  # backup
    path = paths.app_settings_file()
    path.write_text('{"theme": "li', encoding="utf-8")  # cut off while being written
    assert _fresh().get("models_dir") == "D:/models"
    assert paths._stored_setting("models_dir") == "D:/models"  # worker processes read it too
    from clipasso_studio.gui import app_settings as module

    module._instance = None
