# check_theme_change.py
from qfluentwidgets import setTheme, Theme, qconfig
from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import os
import subprocess
import sys
import darkdetect
from module.config import cfg

# 自动模式交还给系统（Unknown），其余偏好固定 Qt 配色。
_QT_COLOR_SCHEMES = {'light': Qt.ColorScheme.Light, 'dark': Qt.ColorScheme.Dark,
                     'evernight': Qt.ColorScheme.Dark}


def current_theme_preference(window):
    if window is not None and window._evernight.selected:
        return 'evernight'
    preference = cfg.get_value('ui_theme', 'auto')
    return 'auto' if preference == 'evernight' else preference


def applyTheme(window, theme=None):
    """Apply the current theme preference, following the system in auto mode."""
    preference = current_theme_preference(window)
    if theme is not None:
        if preference != 'auto':
            return
    else:
        # 系统切换深浅色时，Qt 会把所有窗口的 Mica 深色标记和调色板改成系统配色，
        # 而 qfluentwidgets 主题没变就不会重设 Mica。固定主题时要让 Qt 不再跟随系统。
        app = QApplication.instance()
        if app is not None:
            app.styleHints().setColorScheme(_QT_COLOR_SCHEMES.get(preference, Qt.ColorScheme.Unknown))
        theme = {'light': Theme.LIGHT, 'dark': Theme.DARK, 'evernight': Theme.DARK}.get(preference)
        if theme is None:
            theme = Theme.DARK if darkdetect.isDark() else Theme.LIGHT
    # setTheme() 会刷新全部控件的样式，即使传入的主题没有变化。
    if theme == qconfig.theme:
        return

    is_minimized_to_tray = hasattr(window, 'tray_icon') and not window.isVisible() and window.tray_icon.isVisible()
    setTheme(theme, lazy=not is_minimized_to_tray)
    if window is not None:
        if sys.platform == "darwin":
            if hasattr(window, '_syncMacAppearance'):
                QTimer.singleShot(100, window, window._syncMacAppearance)
        else:
            # Refresh Mica after the light-to-dark transition (PyQt-Frameless-Window #158).
            QTimer.singleShot(500, window, lambda: window.setMicaEffectEnabled(True))


class SystemThemeListener(QThread):
    """系统主题监听线程

    darkdetect.listener() 是阻塞调用，会一直运行监听系统主题变化，
    需要在单独的线程中运行。
    """
    systemThemeChanged = Signal(Theme)  # 系统主题变化信号
    initCompleted = Signal(bool)  # 初始化完成信号，参数表示是否支持

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._isSupported = False
        self._stopFlag = False
        self._proc = None

    def run(self):
        try:
            # darkdetect.listener() 是阻塞调用
            # 如果平台不支持会抛出 NotImplementedError
            # 如果支持则会一直阻塞运行
            self._isSupported = True
            self.initCompleted.emit(True)

            if sys.platform == "darwin":
                self._listenMac()
            else:
                # 这个调用会阻塞，直到线程被终止
                darkdetect.listener(self._onThemeChanged)
        except NotImplementedError as e:
            self._isSupported = False
            self.initCompleted.emit(False)
        except Exception as e:
            self._isSupported = False
            self.initCompleted.emit(False)

    def _listenMac(self):
        """macOS 上 darkdetect.listener 会另起监听子进程 主程序退出时不会跟着结束
        这里照它的方式自己启动子进程 停止时能一并结束"""
        if not darkdetect._mac_detect._can_listen:
            raise NotImplementedError()
        python_exe = os.environ.get("M7A_WORKER_PYTHON") or sys.executable
        self._proc = subprocess.Popen(
            (python_exe, "-c", "from darkdetect import _mac_detect as m; m._listen_child()"),
            stdout=subprocess.PIPE,
            universal_newlines=True,
            cwd=os.path.dirname(darkdetect._mac_detect.__file__),
        )
        for line in self._proc.stdout:
            self._onThemeChanged(line.strip())

    def _onThemeChanged(self, theme: str):
        """系统主题变化回调"""
        if self._stopFlag:
            return

        new_theme = Theme.DARK if theme.lower() == "dark" else Theme.LIGHT

        # 避免重复触发
        if new_theme == qconfig.theme:
            return

        self.systemThemeChanged.emit(new_theme)

    def stop(self):
        """停止监听线程"""
        self._stopFlag = True
        # macOS 结束监听子进程后 读取循环会自己结束
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()
            self._proc.wait(1)
            self.wait(500)
        # darkdetect.listener 无法被中断，只能等待或强制终止
        if self.isRunning():
            self.terminate()  # 强制终止线程
            self.wait(500)  # 等待最多500ms


def checkThemeChange(self):
    """初始化系统主题监听

    在 MainWindow 中调用，self 是 MainWindow 实例
    """
    def on_init_completed(is_supported):
        if is_supported:
            pass
        else:
            # 清理不支持的监听器
            if hasattr(self, 'themeListener') and self.themeListener:
                self.themeListener.quit()
                self.themeListener = None

    # 创建监听器
    self.themeListener = SystemThemeListener(self)
    self.themeListener.systemThemeChanged.connect(lambda theme: applyTheme(self, theme))
    self.themeListener.initCompleted.connect(on_init_completed)

    # 启动线程（阻塞调用会在线程中运行）
    self.themeListener.start()

    return self.themeListener
