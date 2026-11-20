"""Shared helpers for GUI tests under tests/test_app/."""
from module import localization


def switch_language(qtbot, window, language):
    old_settings = window.settingInterface
    window._on_ui_language_changed(language)
    qtbot.waitUntil(lambda: window.settingInterface is not old_settings, timeout=15000)
    qtbot.wait(20)
    assert localization.get_current_language() == language
