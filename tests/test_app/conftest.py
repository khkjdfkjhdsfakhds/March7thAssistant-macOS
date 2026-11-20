"""Shared pytest fixtures for MainWindow and PySide6 GUI tests."""
from contextlib import contextmanager
from copy import deepcopy
from time import monotonic
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import Theme, qconfig, setTheme

from app.common.accent import MARCH7TH_PINK, set_accent_color
from module import localization


class _LocalQtBot:
    """Minimal QTest-backed replacement when pytest-qt is not installed."""

    def __init__(self, app):
        self._app = app
        self._widgets = []

    def addWidget(self, widget):
        self._widgets.append(widget)
        return widget

    def cleanup(self):
        for widget in reversed(self._widgets):
            try:
                widget.hide()
                widget.deleteLater()
            except RuntimeError:
                pass
        self._widgets.clear()
        self._app.processEvents()

    def wait(self, ms):
        QTest.qWait(int(ms))

    def waitUntil(self, callback, *, timeout=5000):
        deadline = monotonic() + timeout / 1000.0
        while True:
            self._app.processEvents()
            if callback():
                return
            if monotonic() >= deadline:
                raise TimeoutError(f'waitUntil timed out after {timeout} ms')
            QTest.qWait(10)

    @contextmanager
    def waitSignal(self, signal, *, timeout=5000):
        with self.waitSignals([signal], timeout=timeout):
            yield

    @contextmanager
    def waitSignals(self, signals, *, check_params_cbs=None, order='none', timeout=5000):
        callbacks = check_params_cbs or [None] * len(signals)
        matched = [False] * len(signals)
        loop = QEventLoop()
        timed_out = [False]
        connections = []

        def _make_slot(idx, cb):
            def _slot(*args):
                if order == 'simple':
                    if idx != sum(1 for m in matched if m):
                        return
                elif matched[idx]:
                    return
                if cb is not None and not cb(*args):
                    return
                matched[idx] = True
                if all(matched) and loop.isRunning():
                    loop.quit()
            return _slot

        for idx, (sig, cb) in enumerate(zip(signals, callbacks)):
            slot = _make_slot(idx, cb)
            sig.connect(slot)
            connections.append((sig, slot))

        timer = QTimer()
        timer.setSingleShot(True)

        def _on_timeout():
            timed_out[0] = True
            if loop.isRunning():
                loop.quit()

        timer.timeout.connect(_on_timeout)
        timer.start(timeout)
        try:
            yield
            if not all(matched):
                loop.exec()
            if timed_out[0] and not all(matched):
                raise TimeoutError(f'waitSignals timed out after {timeout} ms ({matched})')
        finally:
            timer.stop()
            for sig, slot in connections:
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass

    @staticmethod
    def _coerce_pos(pos):
        return QPoint() if pos is None else pos

    def mouseClick(self, widget, button, modifier=Qt.KeyboardModifier.NoModifier, pos=None, delay=-1):
        QTest.mouseClick(widget, button, modifier, self._coerce_pos(pos), delay)

    def mouseDClick(self, widget, button, modifier=Qt.KeyboardModifier.NoModifier, pos=None, delay=-1):
        QTest.mouseDClick(widget, button, modifier, self._coerce_pos(pos), delay)

    def mousePress(self, widget, button, modifier=Qt.KeyboardModifier.NoModifier, pos=None, delay=-1):
        QTest.mousePress(widget, button, modifier, self._coerce_pos(pos), delay)

    def mouseRelease(self, widget, button, modifier=Qt.KeyboardModifier.NoModifier, pos=None, delay=-1):
        QTest.mouseRelease(widget, button, modifier, self._coerce_pos(pos), delay)

    def mouseMove(self, widget, pos=None, delay=-1):
        QTest.mouseMove(widget, self._coerce_pos(pos), delay)

    def keyClick(self, widget, key, modifier=Qt.KeyboardModifier.NoModifier, delay=-1):
        QTest.keyClick(widget, key, modifier, delay)


@pytest.fixture(scope='session')
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def qtbot(qapp):
    bot = _LocalQtBot(qapp)
    yield bot
    bot.cleanup()


@pytest.fixture
def window(qtbot, monkeypatch, tmp_path):
    from app import main_window as module
    from module.config import cfg

    original = localization.get_current_language()
    original_ui = getattr(cfg, 'ui_language_now', 'zh_CN')
    original_theme = qconfig.theme
    monkeypatch.setattr(cfg, 'config', deepcopy(cfg.config))
    monkeypatch.setattr(cfg, 'config_path', str(tmp_path / 'config.yaml'))
    monkeypatch.setattr(cfg, 'set_value', Mock())
    monkeypatch.setattr(cfg, 'set_values', Mock())
    monkeypatch.setattr(module, 'checkThemeChange', lambda _: Mock())
    monkeypatch.setattr(module, 'checkUpdate', lambda *a, **k: None)
    monkeypatch.setattr(module, 'checkAnnouncement', lambda *a, **k: None)
    monkeypatch.setattr(module, 'disclaimer', lambda *a, **k: None)
    monkeypatch.setattr(
        module.MainWindow,
        'initSystemTray',
        lambda self: setattr(self, '_tray_actions', [Mock() for _ in range(4)]),
    )
    monkeypatch.setattr(module.MainWindow, 'closeEvent', lambda self, event: event.accept())
    monkeypatch.setattr(module.LogInterface, '_LogInterface__initShortcut', lambda _: None)
    monkeypatch.setattr(module.LogInterface, '_migrate_legacy_schedule', lambda _: None)
    monkeypatch.setattr(module.LogInterface, '_startScheduleTimer', lambda _: None)
    monkeypatch.setattr(module.LogInterface, '_initOverlayMonitor', lambda _: None)
    localization.load_language('zh_CN')
    cfg.ui_language_now = 'zh_CN'
    page = module.MainWindow(start_minimized_to_tray=True)
    qtbot.addWidget(page)
    page.show()
    qtbot.wait(10)
    yield page
    page._language_change_timer.stop()
    page._config_reload_timer.stop()
    if page._evey_animation is not None:
        try:
            page._evey_animation.close()
        except Exception:
            pass
    for sig, slot in (
        (qconfig.themeChanged, page._on_theme_changed),
        (qconfig.themeChangedFinished, page._syncMacAppearance),
    ):
        try:
            sig.disconnect(slot)
        except (RuntimeError, TypeError):
            pass
    app = QApplication.instance()
    if app is not None:
        app.removeEventFilter(page)
    page.hide()
    if getattr(page, '_macMenuBar', None) is not None:
        page._macMenuBar.deleteLater()
    if page.logInterface._log_overlay:
        page.logInterface._log_overlay.deleteLater()
    if getattr(page, '_fluent_translator', None):
        QApplication.instance().removeTranslator(page._fluent_translator)
    set_accent_color(MARCH7TH_PINK)
    setTheme(original_theme)
    localization.load_language(original)
    cfg.ui_language_now = original_ui
