from PySide6.QtCore import Qt, QSize, QPoint, QRect, QEvent, QTimer, QThread, QFileSystemWatcher, Signal, QObject, QSignalBlocker, QVariantAnimation
from PySide6.QtGui import QIcon, QAction, QPainter, QColor, QKeySequence
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QLabel, QMenu, QMenuBar, QGraphicsEffect, QWidget

from .components.evey_decoration import EveyControlDecoration, EveyTitleDecoration
from .common.accent import MARCH7TH_PINK, EVERNIGHT_RED, set_accent_color

from qfluentwidgets import (NavigationItemPosition, MSFluentWindow, FluentTitleBar, NavigationBarPushButton,
                            NavigationWidget, SplashScreen, MessageBox, setThemeColor, setTheme, Theme,
                            themeColor, qconfig, isDarkTheme)
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import InfoBar, InfoBarPosition, SystemTrayMenu
from qfluentwidgets.common.style_sheet import styleSheetManager
from qfluentwidgets.components.widgets.frameless_window import FramelessWindow
from app.tools.game_starter import GameStartStatus, GameLaunchThread
from .common.icon import UiIcon
from .common.evernight import EvernightEasterEgg
from .common.evernight_artwork import evernight_artwork
from .common.theme_assets import application_icon_path
from .common.window_icon import set_application_icon
from .components.evey_animation import EveyAnimation

from .home_interface import HomeInterface
from .help_interface import HelpInterface
# from .changelog_interface import ChangelogInterface
from .warp_interface import WarpInterface
from .tools_interface import ToolsInterface
from .workflow_interface import WorkflowInterface
from .setting_interface import SettingInterface
from .log_interface import LogInterface
from .common.signal_bus import signalBus

from .card.messagebox_custom import MessageBoxSupport
from .tools.check_update import checkUpdate
from .tools.check_theme_change import checkThemeChange, applyTheme
from .tools.announcement import checkAnnouncement
from .tools.disclaimer import disclaimer

from module.config import cfg
from module.logger import log
from module.game import get_game_controller
from module.localization import tr
import base64
import os
import sys


class ConfigWatcher(QObject):
    """配置文件监视器"""
    config_changed = Signal()

    def __init__(self, config_path, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.watcher = QFileSystemWatcher()
        self.debounce_timer = None

        # 监视配置
        if os.path.exists(self.config_path):
            self.watcher.addPath(self.config_path)
            self.watcher.fileChanged.connect(self._on_config_changed)

    def _on_config_changed(self, path):
        """检测到文件变化，延迟处理避免频繁触发"""
        log.debug(f"[config-watch] 文件变化事件: {path}")

        # 配置保存采用临时文件原子替换，替换后旧的监视句柄可能失效，需要重新挂载
        try:
            if os.path.exists(self.config_path) and self.config_path not in self.watcher.files():
                self.watcher.addPath(self.config_path)
                log.debug("[config-watch] 监视句柄失效，已重新挂载")
        except Exception:
            pass

        # 清除之前的定时器
        if self.debounce_timer:
            self.debounce_timer.stop()
            self.debounce_timer.deleteLater()

        # 创建新的定时器，延迟1秒处理（避免文件写入过程中多次触发）
        self.debounce_timer = QTimer()
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.timeout.connect(self._emit_change)
        self.debounce_timer.start(1000)

    def _emit_change(self):
        """检查文件是否真的改变，然后发送信号"""
        exists = os.path.exists(self.config_path)
        if exists and cfg.is_config_changed():
            log.info("[config-watch] 检测到配置文件被外部修改，准备重载界面")
            self.config_changed.emit()
        else:
            log.debug(f"[config-watch] 无需重载: exists={exists}")


class ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return

        super().mousePressEvent(event)


class LogoShakeEffect(QGraphicsEffect):
    """Rotate only the artwork, keeping the logo's layout and hit area fixed."""
    def __init__(self, parent):
        super().__init__(parent)
        self.angle = 0.0
        self.timeline = QVariantAnimation(self)
        self.timeline.setDuration(440)
        self.timeline.setKeyValues([(0.0, 0.0), (0.16, -14.0), (0.34, 12.0),
                                    (0.54, -8.0), (0.74, 5.0), (1.0, 0.0)])
        self.timeline.valueChanged.connect(self._advance)

    def shake(self):
        self.timeline.stop()
        self.timeline.start()

    def _advance(self, angle):
        self.angle = angle
        self.update()

    def boundingRectFor(self, rect):
        return rect.adjusted(-6, -6, 6, 6)

    def draw(self, painter):
        offset = QPoint()
        pixmap = self.sourcePixmap(Qt.CoordinateSystem.LogicalCoordinates, offset,
                                   QGraphicsEffect.PixmapPadMode.NoPad)
        center = self.sourceBoundingRect().center()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.translate(center)
        painter.rotate(self.angle)
        painter.translate(-center)
        painter.drawPixmap(offset, pixmap)
        painter.restore()


class EasterEggClickFilter(QObject):
    clicked = Signal()

    def __init__(self, logo, target_size=(48, 48)):
        super().__init__(logo)
        self.logo = logo
        self.shake_effect = LogoShakeEffect(logo)
        logo.setGraphicsEffect(self.shake_effect)
        self.hit_target = QWidget(logo.parentWidget())
        self.hit_target.setObjectName('logoClickTarget')
        self.hit_target.setFixedSize(*target_size)
        self.hit_target.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hit_target.installEventFilter(self)
        logo.installEventFilter(self)
        self._position_target()

    def _position_target(self):
        self.hit_target.move(self.logo.x() - (self.hit_target.width() - self.logo.width()) // 2,
                             self.logo.y() - (self.hit_target.height() - self.logo.height()) // 2)
        self.hit_target.raise_()

    def eventFilter(self, obj, event):
        if obj is self.logo and event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
            self._position_target()
        if (event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick,
                             QEvent.Type.MouseButtonRelease)
                and event.button() == Qt.MouseButton.LeftButton):
            # 只记录完整点击；吞掉双击，避免快速连点 LOGO 使窗口最大化。
            if (event.type() == QEvent.Type.MouseButtonRelease
                    and obj.rect().contains(event.position().toPoint())):
                self.shake_effect.shake()
                self.clicked.emit()
            return True
        if event.type() == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.LeftButton:
            return True
        return super().eventFilter(obj, event)


_MAC_SIDEBAR_WIDTH = 74
_K_AE_QUIT_APPLICATION = int.from_bytes(b"quit", "big")


def _is_macos_quit_apple_event() -> bool:
    """判断当前窗口关闭是否来自 macOS 的应用退出 AppleEvent（如 ⌘Q 或 Dock 退出）"""
    if sys.platform != "darwin":
        return False
    try:
        import Cocoa
        ev = Cocoa.NSAppleEventManager.sharedAppleEventManager().currentAppleEvent()
        return bool(ev is not None and int(ev.eventID()) == _K_AE_QUIT_APPLICATION)
    except Exception:
        return False


class MacUnifiedTitleBar(FluentTitleBar):
    """macOS 极简透明顶部拖拽条：隐藏 Windows 图标、标题与三键，留出左侧红绿灯区域"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedHeight(32)
        self.iconLabel.hide()
        self.titleLabel.hide()
        self.minBtn.hide()
        self.maxBtn.hide()
        self.closeBtn.hide()
        self.hBoxLayout.setContentsMargins(_MAC_SIDEBAR_WIDTH + 12, 0, 16, 0)

    def _trafficLightRect(self) -> QRect:
        return QRect(6, 2, _MAC_SIDEBAR_WIDTH - 12, 28)

    def _isDragRegion(self, pos) -> bool:
        if self._trafficLightRect().contains(pos):
            return False
        for child in self.findChildren(QLabel):
            if child.isVisible() and child.cursor().shape() == Qt.CursorShape.PointingHandCursor:
                if child.geometry().contains(pos):
                    return False
        return 0 < pos.x() < self.width()

    def mouseDoubleClickEvent(self, event):
        if self._trafficLightRect().contains(event.pos()):
            return
        super().mouseDoubleClickEvent(event)


class MainWindow(MSFluentWindow):
    def __init__(self, task=None, exit_on_complete=False, start_minimized_to_tray=False):
        super().__init__()
        self._pending_ui_language = None
        self._navigation_animation_running = False
        self.stackedWidget.view.aniStart.connect(lambda: setattr(self, '_navigation_animation_running', True))
        self.stackedWidget.view.aniFinished.connect(lambda: setattr(self, '_navigation_animation_running', False))
        self._language_change_timer = QTimer(self)
        self._language_change_timer.setSingleShot(True)
        self._language_change_timer.timeout.connect(self._rebuild_interfaces_for_language)
        self._config_reload_timer = QTimer(self)
        self._config_reload_timer.setSingleShot(True)
        self._config_reload_timer.timeout.connect(self._on_config_file_changed)
        self.startup_task = task  # 保存启动时要执行的任务
        self.exit_on_complete = exit_on_complete  # 任务完成后是否退出
        self.start_minimized_to_tray = start_minimized_to_tray
        self._defer_startup_checks = False  # 静默启动时推迟的启动检查（检查更新/公告）
        self.detected_update_version = None
        self.updateVersionBadge = None
        self._force_quit = False
        self._quitting = False
        self._allow_dock_reopen = False
        self._macSidebarEffectView = None
        self._macMenuBar = None
        self._macLogoContainer = None
        self._macLogoLabel = None
        self._easter_egg_logo = None
        self._evernight = EvernightEasterEgg()
        self._evernight_active = False
        self._evey_animation = None
        self._evernight.selected = self._load_evernight_selection()

        if sys.platform == 'darwin':
            self._initMacUnifiedChrome()
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self._onAppAboutToQuit)

        self.initWindow()

        self.initInterface()
        self.initNavigation()
        self.initSystemTray()
        if sys.platform == 'darwin':
            self.initMacMenuBar()
        qconfig.themeChanged.connect(self._on_theme_changed)
        qconfig.themeChangedFinished.connect(self._syncMacAppearance)
        if self._evernight.selected:
            self._on_theme_changed()

        if self.start_minimized_to_tray:
            self.hide()

        # 初始化配置文件监视器
        self.config_watcher = ConfigWatcher(os.path.abspath(cfg.config_path), self)
        self.config_watcher.config_changed.connect(self._on_config_file_changed)

        # 如果有启动任务，延迟执行
        if self.startup_task:
            QTimer.singleShot(1000, self._executeStartupTask)
        elif self.start_minimized_to_tray:
            # 最小化到托盘启动：不弹出任何窗口，检查更新与公告推迟到主窗口首次显示
            self._defer_startup_checks = True
        else:
            # 检查更新
            checkUpdate(self, flag=True)
            checkAnnouncement(self)

        if sys.platform == 'darwin':
            QTimer.singleShot(500, lambda: setattr(self, '_allow_dock_reopen', True))

    def _initMacUnifiedChrome(self):
        """配置 macOS 通顶毛玻璃侧边栏与极简无顶栏布局"""
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setTitleBar(MacUnifiedTitleBar(self))
        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)

        self.navigationInterface.setFixedWidth(_MAC_SIDEBAR_WIDTH)
        self.navigationInterface.vBoxLayout.setContentsMargins(0, 38, 0, 8)
        self.navigationInterface.topLayout.setContentsMargins(5, 0, 5, 0)
        self.navigationInterface.scrollLayout.setContentsMargins(5, 0, 5, 0)
        self.navigationInterface.bottomLayout.setContentsMargins(5, 0, 5, 0)

        # 侧边栏红绿灯下方（y=38..70）的低调微缩徽标容器，避免与红绿灯和导航项重叠
        self._macLogoContainer = QWidget(self.navigationInterface)
        self._macLogoContainer.setObjectName('macSidebarLogoContainer')
        self._macLogoContainer.setFixedSize(_MAC_SIDEBAR_WIDTH, 32)
        self._macLogoContainer.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._macLogoLabel = QLabel(self._macLogoContainer)
        self._macLogoLabel.setObjectName('macSidebarLogo')
        self._macLogoLabel.setFixedSize(24, 24)
        self._macLogoLabel.move((_MAC_SIDEBAR_WIDTH - 24) // 2, 4)
        self._macLogoLabel.setScaledContents(True)
        self._macLogoLabel.setToolTip('')
        self.navigationInterface.vBoxLayout.insertWidget(0, self._macLogoContainer)

        # 取消 qfluentwidgets 注册的默认圆角边框样式，防止主题/强调色切换后覆盖透明平铺样式
        self.stackedWidget.setProperty('isTransparent', True)
        styleSheetManager.deregister(self.stackedWidget)
        self.stackedWidget.setStyleSheet(
            "StackedWidget { border: none; border-top-left-radius: 0px; background-color: transparent; }"
        )

        # 允许在侧边栏空白处按住拖动窗口，同时监听 ApplicationActivate 以支持点击 Dock 图标重开窗口
        self.navigationInterface.installEventFilter(self)
        self.navigationInterface.scrollArea.viewport().installEventFilter(self)
        self.navigationInterface.scrollWidget.installEventFilter(self)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def systemTitleBarRect(self, size: QSize) -> QRect:
        """将 macOS 原生红绿灯定位在左侧通顶边栏顶部"""
        if sys.platform == 'darwin':
            return QRect(0, 0 if self.isFullScreen() else 5, _MAC_SIDEBAR_WIDTH, size.height())
        return super().systemTitleBarRect(size)

    def _syncMacAppearance(self):
        """同步 NSWindow 明暗外观与左侧毛玻璃重绘"""
        if sys.platform != 'darwin':
            return
        try:
            import Cocoa
            import objc
            view = objc.objc_object(c_void_p=int(self.winId()))
            nsWindow = view.window()
            if nsWindow is not None:
                name = Cocoa.NSAppearanceNameDarkAqua if isDarkTheme() else Cocoa.NSAppearanceNameAqua
                nsWindow.setAppearance_(Cocoa.NSAppearance.appearanceNamed_(name))
            effect_view = getattr(self, '_macSidebarEffectView', None)
            if effect_view is not None:
                effect_view.setNeedsDisplay_(True)
        except Exception:
            pass
        self.update()

    def _ensureMacSidebarVibrancy(self):
        """在 QNSView 下方挂载 NSVisualEffectMaterialSidebar 实现原生长条毛玻璃侧边栏"""
        if sys.platform != 'darwin':
            return
        try:
            import Cocoa
            import objc
            view = objc.objc_object(c_void_p=int(self.winId()))
            nsWindow = view.window()
            if nsWindow is None:
                return
            nsWindow.setOpaque_(False)
            nsWindow.setBackgroundColor_(Cocoa.NSColor.clearColor())
            name = Cocoa.NSAppearanceNameDarkAqua if isDarkTheme() else Cocoa.NSAppearanceNameAqua
            nsWindow.setAppearance_(Cocoa.NSAppearance.appearanceNamed_(name))

            if self._macSidebarEffectView is None and view.superview() is not None:
                ev = Cocoa.NSVisualEffectView.alloc().initWithFrame_(
                    Cocoa.NSMakeRect(0, 0, _MAC_SIDEBAR_WIDTH, self.height())
                )
                ev.setAutoresizingMask_(Cocoa.NSViewHeightSizable | Cocoa.NSViewMaxXMargin)
                ev.setMaterial_(Cocoa.NSVisualEffectMaterialSidebar)
                ev.setBlendingMode_(Cocoa.NSVisualEffectBlendingModeBehindWindow)
                ev.setState_(Cocoa.NSVisualEffectStateFollowsWindowActiveState)
                view.superview().addSubview_positioned_relativeTo_(ev, Cocoa.NSWindowBelow, view)
                self._macSidebarEffectView = ev
            elif self._macSidebarEffectView is not None:
                self._macSidebarEffectView.setFrame_(
                    Cocoa.NSMakeRect(0, 0, _MAC_SIDEBAR_WIDTH, self.height())
                )
        except Exception:
            pass

    def paintEvent(self, e):
        if sys.platform != 'darwin':
            return super().paintEvent(e)
        FramelessWindow.paintEvent(self, e)
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        dark = isDarkTheme()
        # 左侧边栏保留高透底色以透出原生 NSVisualEffectView 毛玻璃，右侧内容区使用不透明底色并加 1px 分隔线
        sidebar_tint = QColor(24, 24, 28, 50) if dark else QColor(255, 255, 255, 26)
        content_bg = QColor(30, 30, 32, 255) if dark else QColor(248, 249, 251, 255)
        divider_color = QColor(255, 255, 255, 24) if dark else QColor(0, 0, 0, 22)
        painter.fillRect(0, 0, _MAC_SIDEBAR_WIDTH, self.height(), sidebar_tint)
        painter.fillRect(_MAC_SIDEBAR_WIDTH, 0, self.width() - _MAC_SIDEBAR_WIDTH, self.height(), content_bg)
        painter.fillRect(_MAC_SIDEBAR_WIDTH, 0, 1, self.height(), divider_color)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        effect_view = getattr(self, '_macSidebarEffectView', None)
        if sys.platform == 'darwin' and effect_view is not None:
            try:
                import Cocoa
                effect_view.setFrame_(
                    Cocoa.NSMakeRect(0, 0, _MAC_SIDEBAR_WIDTH, self.height())
                )
            except Exception:
                pass

    def eventFilter(self, watched, event):
        if sys.platform == 'darwin':
            app = QApplication.instance()
            if watched is app and event.type() == QEvent.Type.ApplicationActivate:
                if (
                    not getattr(self, '_force_quit', False)
                    and getattr(self, '_allow_dock_reopen', False)
                    and (not self.isVisible() or self.isMinimized())
                ):
                    self._show_main_window()
                return False

            nav = getattr(self, 'navigationInterface', None)
            if nav is not None:
                nav_targets = (
                    nav,
                    nav.scrollArea.viewport(),
                    nav.scrollWidget,
                )
                if watched in nav_targets and event.type() == QEvent.Type.MouseButtonPress:
                    if event.button() == Qt.MouseButton.LeftButton:
                        global_pt = event.globalPosition().toPoint()
                        nav_pos = nav.mapFromGlobal(global_pt)
                        if not QRect(6, 2, _MAC_SIDEBAR_WIDTH - 12, 26).contains(nav_pos):
                            child = nav.childAt(nav_pos)
                            is_nav_btn = False
                            cur = child
                            while cur is not None and cur is not nav:
                                if isinstance(cur, (NavigationWidget, NavigationBarPushButton)):
                                    is_nav_btn = True
                                    break
                                cur = cur.parentWidget()
                            if not is_nav_btn and self.windowHandle() is not None:
                                self.windowHandle().startSystemMove()
                                return True
        return super().eventFilter(watched, event)

    def _executeStartupTask(self):
        """执行启动时指定的任务"""
        if self.startup_task:
            from tasks.base.tasks import start_task
            start_task(self.startup_task)

    def initWindow(self):
        # 开启 “在标题栏和窗口边框上显示强调色” 后，会导致窗口顶部出现异色横条 bug 已经修复
        # https://github.com/zhiyiYo/PyQt-Frameless-Window/pull/186
        # 要求 PySideSix-Frameless-Window>=0.7.0
        # self.setMicaEffectEnabled(False)

        setThemeColor(MARCH7TH_PINK, lazy=True)
        applyTheme(self)

        # 禁用最大化
        # self.titleBar.maxBtn.setHidden(True)
        # self.titleBar.maxBtn.setDisabled(True)
        # self.titleBar.setDoubleClickEnabled(False)
        # self.setResizeEnabled(False)

        # self.setWindowFlags(Qt.WindowCloseButtonHint)
        # self.setWindowFlags(Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)

        # 设置最小尺寸
        min_width = 960
        min_height = 640
        self.setMinimumWidth(min_width)
        self.setMinimumHeight(min_height)

        window_memory = cfg.get_value('window_memory', 'size')
        # 从配置文件读取窗口尺寸，确保不低于最小值
        if window_memory in ('size', 'size_and_position'):
            saved_width = cfg.get_value('window_width', min_width)
            saved_height = cfg.get_value('window_height', min_height)
            window_width = max(saved_width, min_width)
            window_height = max(saved_height, min_height)
            self.resize(window_width, window_height)
        else:
            self.resize(min_width, min_height)

        if sys.platform == 'darwin' and self._macLogoLabel is not None:
            self._easter_egg_logo = self._macLogoLabel
            easter_egg_click = EasterEggClickFilter(self._easter_egg_logo, target_size=(48, 32))
        else:
            self._easter_egg_logo = self.titleBar.iconLabel
            easter_egg_click = EasterEggClickFilter(self._easter_egg_logo)
        easter_egg_click.clicked.connect(self._on_logo_clicked)
        set_application_icon(self, application_icon_path(), 'March7th Assistant')
        self.setWindowTitle("March7th Assistant")
        # 分离系统窗口标题与应用内标题栏文本
        self._refreshWindowTitleBar()

        self._evey_title_decoration = EveyTitleDecoration(self.titleBar)

        # 创建启动画面
        self.splashScreen = SplashScreen(self.windowIcon(), self)
        self.splashScreen.setIconSize(QSize(128, 128))
        self.splashScreen.titleBar.maxBtn.setHidden(True)
        self.splashScreen.raise_()

        primary_screen = QApplication.primaryScreen().availableGeometry()
        w, h = primary_screen.width(), primary_screen.height()

        saved_x = cfg.get_value('window_x', None)
        saved_y = cfg.get_value('window_y', None)

        if window_memory in ('position', 'size_and_position') and saved_x is not None and saved_y is not None:
            # 尝试找到保存位置所在的屏幕，找不到则回退到主屏幕
            target_screen = QApplication.screenAt(QPoint(int(saved_x), int(saved_y)))
            screen = target_screen.availableGeometry() if target_screen else primary_screen
            max_x = max(screen.left(), screen.right() - self.width())
            max_y = max(screen.top(), screen.bottom() - self.height())
            restored_x = max(screen.left(), min(int(saved_x), max_x))
            restored_y = max(screen.top(), min(int(saved_y), max_y))
            self.move(restored_x, restored_y)
        else:
            self.move(w // 2 - self.width() // 2, h // 2 - self.height() // 2)

        # 记录期望的窗口几何（尺寸与位置）
        target_geometry = self.geometry()

        # 根据配置决定窗口显示方式
        if self.start_minimized_to_tray:
            # 最小化到托盘启动：不显示主窗口与启动画面（SplashScreen 是主窗口子控件，随父窗口隐藏），直接进托盘
            self.hide()
        elif window_memory in ('size', 'size_and_position') and cfg.get_value('window_maximized', False):
            self.showMaximized()
        else:
            self.show()

        QApplication.processEvents()

        if self.start_minimized_to_tray:
            # 托盘启动跳过了 show() 的几何同步：构造期堆积的窗口几何事件会在 processEvents 中被处理，
            # 把窗口尺寸打回原生默认值（500x500），导致从托盘恢复后窗口异常变小，需重新应用一次几何
            self.setGeometry(target_geometry)

        if sys.platform == 'darwin':
            self._ensureMacSidebarVibrancy()

    def _baseTitleBarText(self):
        return f"{self._assistant_name()} {cfg.version}"

    def _assistant_name(self):
        return 'Evernight Assistant' if self._evernight_active else 'March7th Assistant'

    def _ensureUpdateVersionBadge(self):
        if self.updateVersionBadge is not None:
            return self.updateVersionBadge

        if not hasattr(self, 'titleBar') or not hasattr(self.titleBar, 'hBoxLayout'):
            return None

        badge = ClickableLabel(self.titleBar)
        badge.hide()
        badge.setStyleSheet(f"color: {themeColor().name()}; font-weight: 700;")
        badge.setCursor(Qt.CursorShape.PointingHandCursor)
        badge.clicked.connect(self._on_update_version_badge_clicked)
        if sys.platform == 'darwin':
            self.titleBar.hBoxLayout.addWidget(badge, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        else:
            try:
                self.titleBar.hBoxLayout.insertWidget(4, badge, 0, Qt.AlignmentFlag.AlignVCenter)
            except Exception:
                self.titleBar.hBoxLayout.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        self.updateVersionBadge = badge
        return badge

    def _refreshWindowTitleBar(self):
        if hasattr(self, 'titleBar') and hasattr(self.titleBar, 'setTitle'):
            self.titleBar.setTitle(self._baseTitleBarText())

        badge = self._ensureUpdateVersionBadge()
        if badge is None:
            return

        badge.setStyleSheet(f"color: {themeColor().name()}; font-weight: 700;")
        if self.detected_update_version:
            badge.setText(tr('检测到新版本：{version}').format(version=self.detected_update_version))
            badge.show()
        else:
            badge.hide()

    def setDetectedUpdateVersion(self, version: str | None):
        self.detected_update_version = version or None
        self._refreshWindowTitleBar()
        if hasattr(self, 'logInterface') and self.logInterface:
            try:
                self.logInterface.setDetectedUpdateVersion(self.detected_update_version)
            except Exception:
                pass

    @staticmethod
    def _prepare_evernight():
        try:
            evernight_artwork()
        except OSError as error:
            log.warning(f'无法加载长夜主题：{error}')
            return False
        return True

    def _load_evernight_selection(self):
        if not self._evernight.unlocked and cfg.get_value('evernight_unlocked') is True:
            self._evernight = EvernightEasterEgg(unlocked=True)
        return (self._evernight.unlocked and cfg.get_value('ui_theme') == 'evernight'
                and self._prepare_evernight())

    def _apply_ui_theme(self, evernight_selected):
        selection_changed = evernight_selected != self._evernight.selected
        previous_palette = qconfig.theme
        self._evernight.selected = evernight_selected
        applyTheme(self)
        # 深色和长夜共用调色板，切换时 Qt 可能不发出 themeChanged。
        if selection_changed and qconfig.theme == previous_palette:
            self._on_theme_changed()

    def set_ui_theme(self, preference, *, unlock_evernight=False):
        if cfg.writes_suspended:
            return False
        selected = preference == 'evernight'
        if selected and (not self._evernight.unlocked or not self._prepare_evernight()):
            return False

        values = {'ui_theme': preference}
        if unlock_evernight:
            values['evernight_unlocked'] = True
        previous = {key: cfg.config[key] for key in values if key in cfg.config}
        try:
            if unlock_evernight:
                cfg.set_values(values)
            else:
                cfg.set_value('ui_theme', preference)
        except OSError as error:
            for key in values.keys() - previous.keys():
                cfg.config.pop(key, None)
            cfg.config.update(previous)
            log.warning(f'无法保存界面主题：{error}')
            return False

        self._apply_ui_theme(selected)
        return True

    def _on_theme_changed(self):
        selected = self._evernight.selected
        if not selected and self._evey_animation is not None:
            self._evey_animation.close()  # closed 回调按当前主题统一刷新。
            return
        # 首次动画到中点时替换角色，动画继续；之后随主题即时切换。
        active = (selected and self._evernight.animation_played
                  and (self._evey_animation is None
                       or self._evey_animation.timeline.currentValue() >= 0.5))
        if active != self._evernight_active:
            self._evernight_active = active
            set_accent_color(EVERNIGHT_RED if active else MARCH7TH_PINK)
            self.setWindowTitle(self._assistant_name())
            if hasattr(self, 'tray_icon'):
                self.tray_icon.setToolTip(self._assistant_name())
            set_application_icon(self, application_icon_path(active), self._assistant_name())
        self._evey_title_decoration.setActive(active)
        self.settingInterface.themeCard.setEvernightMode(active)
        self._evey_settings_decoration.setActive(active)
        self.homeInterface.setEvernightMode(active, animate=self._evey_animation is not None)
        self._refreshWindowTitleBar()
        self._syncMacAppearance()
        # 先让深色三月七界面重绘，再播放首次替换动画。
        if selected and not self._evernight.animation_played:
            QTimer.singleShot(0, self._play_evey_animation)

    def _on_logo_clicked(self):
        result = self._evernight.record_click()
        if result == 'warning':
            self.homeInterface.banner.logoHint.play()
            return
        if result != 'unlocked':
            return
        self.homeInterface.banner.logoHint.dismiss()
        if not self.set_ui_theme('evernight', unlock_evernight=True):
            self._evernight.unlocked = False
            return
        self.settingInterface.themeCard.showEvernightOption()

    def _play_evey_animation(self):
        if not self.isVisible() or self.isMinimized():
            return
        if not self._evernight.consume_animation(self._evernight.selected):
            return
        animation = EveyAnimation(self)
        self._evey_animation = animation
        animation.midpointReached.connect(self._on_theme_changed)
        animation.closed.connect(self._on_evey_animation_closed)
        if animation.sprite.isNull():
            animation.close()  # A missing intro alone need not prevent the prepared theme from working.
        else:
            animation.play()

    def _on_evey_animation_closed(self):
        self._evey_animation = None
        if not self._evernight_active or not self._evernight.selected:
            self._on_theme_changed()

    def _on_update_version_badge_clicked(self):
        if self.detected_update_version:
            checkUpdate(self)

    def initInterface(self):
        self.homeInterface = HomeInterface(self)
        self.helpInterface = HelpInterface(self)
        # self.changelogInterface = ChangelogInterface(self)
        self.warpInterface = WarpInterface(self)
        self.toolsInterface = ToolsInterface(self)
        self.workflowInterface = WorkflowInterface(self)
        self.logInterface = LogInterface(self)
        self.settingInterface = SettingInterface(self)

        # 连接任务启动信号
        signalBus.startTaskSignal.connect(self._onStartTask)
        # 连接热键配置改变信号
        signalBus.hotkeyChangedSignal.connect(self._onHotkeyChanged)
        # 连接 UI 语言改变信号（用于提示重启生效）
        signalBus.uiLanguageChanged.connect(self._on_ui_language_changed)
        # 连接任务完成信号
        self.logInterface.taskFinished.connect(self._onTaskFinished)
        # 连接自动对话切换信号
        self.logInterface.autoplotToggleRequested.connect(self._onAutoplotToggleRequested)

    def initNavigation(self):
        self.addSubInterface(self.homeInterface, FIF.HOME, tr('主页'))
        self.addSubInterface(self.helpInterface, FIF.BOOK_SHELF, tr('帮助'))
        # self.addSubInterface(self.changelogInterface, FIF.UPDATE, '更新日志')
        self.addSubInterface(self.warpInterface, FIF.SHARE, tr('抽卡记录'))
        self.addSubInterface(self.toolsInterface, FIF.DEVELOPER_TOOLS, tr('工具箱'))
        self.addSubInterface(self.workflowInterface, FIF.CODE, tr('流程编排'))

        self.navigationInterface.addWidget(
            'startGameButton',
            NavigationBarPushButton(FIF.PLAY, tr('启动游戏'), isSelectable=False),
            self.startGame,
            NavigationItemPosition.BOTTOM)

        log_icon = UiIcon.TERMINAL if sys.platform == 'darwin' else FIF.COMMAND_PROMPT
        self.addSubInterface(self.logInterface, log_icon, tr('日志'), position=NavigationItemPosition.BOTTOM)

        # self.navigationInterface.addWidget(
        #     'refreshButton',
        #     NavigationBarPushButton(FIF.SYNC, '刷新', isSelectable=False),
        #     self._on_config_file_changed,
        #     NavigationItemPosition.BOTTOM)

        # self.navigationInterface.addWidget(
        #     'themeButton',
        #     NavigationBarPushButton(FIF.BRUSH, '主题', isSelectable=False),
        #     lambda: toggleTheme(lazy=True),
        #     NavigationItemPosition.BOTTOM)

        self.navigationInterface.addWidget(
            'avatar',
            NavigationBarPushButton(FIF.HEART, tr('赞赏'), isSelectable=False),
            lambda: MessageBoxSupport(
                tr('支持作者🥰'),
                tr('此程序为免费开源项目，如果你付了钱请立刻退款\n如果喜欢本项目，可以微信赞赏送作者一杯咖啡☕\n您的支持就是作者开发和维护项目的动力🚀'),
                './assets/app/images/sponsor.jpg',
                self
            ).exec(),
            NavigationItemPosition.BOTTOM
        )

        self.addSubInterface(self.settingInterface, FIF.SETTING, tr('设置'), position=NavigationItemPosition.BOTTOM)
        self._evey_settings_decoration = EveyControlDecoration(
            self.navigationInterface.widget('settingInterface'),
            'evey-decoration-upright.png', (-4, -9, 4, 3))

        self.splashScreen.finish()
        self.themeListener = checkThemeChange(self)

        if not cfg.get_value(base64.b64decode("YXV0b191cGRhdGU=").decode("utf-8")):
            disclaimer(self)

    def _openSettings(self):
        """显示主窗口并切换到设置页面"""
        try:
            self._show_main_window()
            if hasattr(self, 'settingInterface'):
                self.switchTo(self.settingInterface)
        except Exception:
            pass

    def initSystemTray(self):
        """初始化系统托盘"""
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.windowIcon())
        self.tray_icon.setToolTip('March7th Assistant')

        # 创建托盘菜单（macOS 下使用原生 QMenu，避免 Fluent 弹出菜单抢焦点）
        tray_menu = QMenu(self) if sys.platform == 'darwin' else SystemTrayMenu(parent=self)
        if sys.platform == 'win32':
            tray_menu.aboutToShow.connect(self._on_tray_menu_about_to_show)

        # 显示主界面
        show_action = QAction(tr('显示主界面'), self)
        show_action.triggered.connect(self._show_main_window)
        tray_menu.addAction(show_action)

        # 完整运行
        run_action = QAction(tr('完整运行'), self)
        run_action.triggered.connect(self.startFullTask)
        tray_menu.addAction(run_action)

        tray_menu.addSeparator()

        # 打开设置界面
        setting_action = QAction(tr('设置'), self)
        setting_action.triggered.connect(self._openSettings)
        tray_menu.addAction(setting_action)

        # 退出程序
        quit_action = QAction(tr('退出'), self)
        quit_action.triggered.connect(self.quitApp)
        tray_menu.addAction(quit_action)

        self._tray_actions = [show_action, run_action, setting_action, quit_action]

        self.tray_icon.setContextMenu(tray_menu)
        if sys.platform == 'win32':
            self.tray_icon.activated.connect(self.onTrayIconActivated)
        self.tray_icon.show()

    def initMacMenuBar(self):
        """初始化 macOS 全局顶部菜单栏与标准快捷键（⌘, / ⌘W / ⌘M / ⌘0 / ⌘L / ⌘Q）"""
        if sys.platform != 'darwin':
            return
        self._macMenuBar = QMenuBar(None)

        app_menu = self._macMenuBar.addMenu("三月七小助手")
        about_action = QAction(tr("关于三月七小助手"), self._macMenuBar)
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.triggered.connect(self._showMacAboutDialog)
        app_menu.addAction(about_action)

        pref_action = QAction(tr("设置..."), self._macMenuBar)
        pref_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        pref_action.setShortcut(QKeySequence.StandardKey.Preferences)
        pref_action.triggered.connect(self._openSettings)
        app_menu.addAction(pref_action)

        quit_action = QAction(tr("退出三月七小助手"), self._macMenuBar)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.quitApp)
        app_menu.addAction(quit_action)

        win_menu = self._macMenuBar.addMenu(tr("窗口"))
        close_action = QAction(tr("关闭窗口"), self._macMenuBar)
        close_action.setShortcut(QKeySequence("Ctrl+W"))

        def _close_active_window():
            active = QApplication.activeModalWidget() or QApplication.activeWindow()
            if active is not None and active is not self:
                active.close()
            elif self.isVisible():
                self.close()

        close_action.triggered.connect(_close_active_window)
        win_menu.addAction(close_action)

        min_action = QAction(tr("最小化"), self._macMenuBar)
        min_action.setShortcut(QKeySequence("Ctrl+M"))
        min_action.triggered.connect(lambda: self.showMinimized() if self.isVisible() else None)
        win_menu.addAction(min_action)

        zoom_action = QAction(tr("缩放"), self._macMenuBar)
        zoom_action.triggered.connect(
            lambda: (self.showNormal() if self.isMaximized() else self.showMaximized()) if self.isVisible() else None
        )
        win_menu.addAction(zoom_action)

        win_menu.addSeparator()

        main_win_action = QAction(tr("显示主界面"), self._macMenuBar)
        main_win_action.setShortcut(QKeySequence("Ctrl+0"))
        main_win_action.triggered.connect(self._show_main_window)
        win_menu.addAction(main_win_action)

        log_win_action = QAction(tr("任务日志"), self._macMenuBar)
        log_win_action.setShortcut(QKeySequence("Ctrl+L"))
        log_win_action.triggered.connect(lambda: (self._show_main_window(), self.switchTo(self.logInterface)))
        win_menu.addAction(log_win_action)

        help_menu = self._macMenuBar.addMenu(tr("帮助"))
        help_action = QAction(tr("三月七小助手帮助"), self._macMenuBar)
        help_action.triggered.connect(lambda: (self._show_main_window(), self.switchTo(self.helpInterface)))
        help_menu.addAction(help_action)

    def _showMacAboutDialog(self):
        self._show_main_window()
        msg = MessageBox(
            "三月七小助手 (macOS)",
            f"{tr('版本')}: {cfg.version}",
            self
        )
        msg.cancelButton.hide()
        msg.yesButton.setText(tr("确定"))
        msg.exec()

    def is_minimized_to_tray(self) -> bool:
        """是否处于最小化到托盘状态（主窗口隐藏且托盘图标可见）"""
        try:
            return not self.isVisible() and self.tray_icon.isVisible()
        except Exception:
            return False

    def showEvent(self, event):
        """主窗口显示时补做静默启动推迟的启动检查（检查更新/公告）"""
        super().showEvent(event)
        if sys.platform == 'darwin':
            self._ensureMacSidebarVibrancy()
        if self._defer_startup_checks:
            self._defer_startup_checks = False
            checkUpdate(self, flag=True)
            checkAnnouncement(self)
        if self._evernight.unlocked and not self._evernight.animation_played:
            QTimer.singleShot(0, self._play_evey_animation)

    def _show_main_window(self):
        """显示主界面，macOS 下确保窗口置顶"""
        self.showNormal()
        try:
            if sys.platform == 'darwin':
                try:
                    import Cocoa
                    Cocoa.NSApp.activateIgnoringOtherApps_(True)
                except Exception:
                    pass
                self.raise_()
                self.activateWindow()
                QApplication.setActiveWindow(self)
            else:
                self.activateWindow()
        except Exception:
            pass

    def onTrayIconActivated(self, reason):
        """托盘图标被激活时的处理"""
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.showNormal()
                self.activateWindow()

    def handle_external_activate(self, task=None, exit_on_complete=False):
        """响应来自其他实例的激活请求：置顶窗口并根据需要启动任务或设置退出行为"""
        try:
            # 显示并置顶窗口
            self.showNormal()
            self.raise_()
            self.activateWindow()
        except Exception:
            pass

        # 如果指定了任务，延迟执行以保证界面初始化完成
        if task:
            self.startup_task = task
            QTimer.singleShot(200, self._executeStartupTask)

        # 设置任务完成后是否退出的标志
        if exit_on_complete:
            self.exit_on_complete = exit_on_complete

    def _on_tray_menu_about_to_show(self):
        """托盘菜单即将显示时激活窗口，解决 Windows 上点击外部区域无法关闭菜单的问题"""
        self.activateWindow()

    def _onStartTask(self, command):
        """处理任务启动信号"""
        # 检查是否有任务正在运行
        if self.logInterface.isTaskRunning():
            InfoBar.warning(
                title=tr('任务正在运行'),
                content=tr("请先停止当前任务后再启动新任务"),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )
            # 切换到日志界面
            self.switchTo(self.logInterface)
            return
        # 静默检查更新
        checkUpdate(self, silent=True)
        # 切换到日志界面
        self.switchTo(self.logInterface)
        # 启动任务
        self.logInterface.startTask(command)

    def startFullTask(self):
        """启动完整运行任务"""
        from tasks.base.tasks import start_task
        start_task("main")

    def _onHotkeyChanged(self):
        """处理热键配置改变信号"""
        if hasattr(self, 'logInterface'):
            self.logInterface.updateHotkey()
        if hasattr(self, 'toolsInterface'):
            self.toolsInterface.automaticPlotCard.updateHotkeyHint()

    def _onAutoplotToggleRequested(self):
        """处理自动对话切换请求（全局热键触发）"""
        if hasattr(self, 'toolsInterface'):
            self.toolsInterface.toggleAutoPlot()

    def _on_ui_language_changed(self, lang_code: str):
        """合并连续选择；等下拉菜单退出回调后再刷新，不主动导航。"""
        self._pending_ui_language = lang_code
        self._language_change_timer.start(0)

    def _can_replace_settings(self):
        # 导航动画保存的是页面索引，运行期间不能增删页面。
        # 模态编辑和 QQ 绑定回调也必须结束，避免丢失编辑或销毁运行中的 QThread。
        return not (
            self._navigation_animation_running
            or QApplication.activeModalWidget()
            or QApplication.activePopupWidget()
            or getattr(self.settingInterface, '_qqbotBindPending', False)
            or any(thread.isRunning() for thread in self.settingInterface.findChildren(QThread))
        )

    def _replace_settings_interface(self, replacement, state):
        """新页面已成功构建后才替换旧页，期间不发出导航事件。"""
        old = self.settingInterface
        was_current = self.stackedWidget.currentWidget() is old
        replacement.setProperty('isStackedTransparent', False)
        replacement.resize(old.size())
        animation_enabled = self.stackedWidget.isAnimationEnabled()
        try:
            with QSignalBlocker(self.stackedWidget):
                self.stackedWidget.setAnimationEnabled(False)
                self.stackedWidget.addWidget(replacement)
                try:
                    if was_current:
                        # 绕过 Fluent 的 switchTo，它会清零滚动位置。
                        self.stackedWidget.view.setCurrentWidget(replacement)
                    replacement.restoreViewState(state)
                except Exception:
                    if was_current:
                        self.stackedWidget.view.setCurrentWidget(old)
                    self.stackedWidget.removeWidget(replacement)
                    raise
                self.stackedWidget.removeWidget(old)
                self.settingInterface = replacement
            self._updateStackedBackground()
        finally:
            self.stackedWidget.setAnimationEnabled(animation_enabled)
        old.hide()
        old.deleteLater()

    def _retranslate_persistent_interfaces(self):
        for interface in (self.homeInterface, self.helpInterface, self.warpInterface,
                          self.toolsInterface, self.workflowInterface, self.logInterface):
            position = interface.verticalScrollBar().value()
            interface.retranslateUi()
            interface.verticalScrollBar().setValue(position)
        labels = {
            'homeInterface': tr('主页'), 'helpInterface': tr('帮助'),
            'warpInterface': tr('抽卡记录'), 'toolsInterface': tr('工具箱'),
            'workflowInterface': tr('流程编排'), 'logInterface': tr('日志'),
            'settingInterface': tr('设置'), 'startGameButton': tr('启动游戏'), 'avatar': tr('赞赏'),
        }
        for route, text in labels.items():
            self.navigationInterface.widget(route).setText(text)
        for action, text in zip(self._tray_actions, [tr('显示主界面'), tr('完整运行'), tr('设置'), tr('退出')]):
            action.setText(text)
        self._refreshWindowTitleBar()

    def _reinstall_fluent_translator(self, lang_code: str):
        """重新安装 FluentTranslator 以使 Qt 内置组件翻译同步更新"""
        from app.common.translator import create_fluent_translator
        app = QApplication.instance()
        if hasattr(self, '_fluent_translator') and self._fluent_translator:
            try:
                app.removeTranslator(self._fluent_translator)
            except Exception:
                pass
        self._fluent_translator = create_fluent_translator(lang_code)
        app.installTranslator(self._fluent_translator)

    def _rebuild_interfaces_for_language(self):
        """状态型页面原位翻译；设置页先构建，再在原位置无动画替换。"""
        if self._pending_ui_language is None:
            return
        if not self._can_replace_settings():
            self._language_change_timer.start(100)
            return

        from module.localization import load_language, detect_lang, get_current_language
        lang_code = self._pending_ui_language
        self._pending_ui_language = None
        previous_lang = get_current_language()
        previous_setting = cfg.get_value('ui_language', 'auto')
        replacement = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if lang_code != previous_setting:
                cfg.set_value('ui_language', lang_code)
            actual_lang = detect_lang() if lang_code == 'auto' else lang_code
            cfg.ui_language_now = actual_lang
            load_language(actual_lang)
            self._reinstall_fluent_translator(actual_lang)
            state = self.settingInterface.captureViewState()
            # 不提前移除旧页，也不调用 processEvents：构造失败时旧页仍完整可用，
            # 任务/热键/配置回调不会在半替换状态下重入。
            replacement = SettingInterface(self)
            self._retranslate_persistent_interfaces()
            self._replace_settings_interface(replacement, state)
            replacement = None
            InfoBar.success(
                title=tr('更新成功'), content='', orient=Qt.Horizontal,
                isClosable=True, position=InfoBarPosition.TOP, duration=1500, parent=self
            )
        except Exception as e:
            # 原位回滚运行时语言、持久配置及旧页面的选择，允许重选同一语言。
            cfg.ui_language_now = previous_lang
            load_language(previous_lang)
            import traceback
            log.error(f'切换界面语言失败: {e}\n{traceback.format_exc()}')
            try:
                if cfg.get_value('ui_language', 'auto') != previous_setting:
                    cfg.set_value('ui_language', previous_setting)
            except Exception:
                log.error(f'还原界面语言配置失败\n{traceback.format_exc()}')
            combo = self.settingInterface.languageCard.comboBox
            with QSignalBlocker(combo):
                combo.setCurrentIndex(combo.findData(previous_setting))
            try:
                self._reinstall_fluent_translator(previous_lang)
                self._retranslate_persistent_interfaces()
            except Exception:
                log.error(f'还原界面文案失败\n{traceback.format_exc()}')
            InfoBar.warning(
                title=tr('语言切换失败'), content=str(e), orient=Qt.Horizontal,
                isClosable=True, position=InfoBarPosition.TOP, duration=3000, parent=self
            )
        finally:
            if replacement is not None:
                replacement.hide()
                replacement.deleteLater()
            QApplication.restoreOverrideCursor()

    def _onTaskFinished(self, exit_code):
        """处理任务完成信号"""
        # 如果是启动任务且设置了完成后退出，则在任务成功完成时退出程序
        if self.exit_on_complete and self.startup_task and exit_code == 0:
            # 延迟一小段时间让用户看到完成状态
            QTimer.singleShot(5000, self.quitApp)
        else:
            # 任务失败或未指定退出时，清除自动退出标记
            self.exit_on_complete = False

    def quitApp(self):
        """退出应用程序"""
        self._force_quit = True
        self._do_quit()

    def _saveWindowState(self):
        """保存窗口尺寸、位置和最大化状态到配置文件（批量一次落盘）"""
        try:
            is_maximized = self.isMaximized()
            log.debug(f"[config-save] 退出保存窗口状态开始: maximized={is_maximized}")

            # 只在非最大化状态下保存窗口尺寸和位置
            values = {'window_maximized': is_maximized}
            if not is_maximized:
                window_memory = cfg.get_value('window_memory', 'size')
                if window_memory in ('size', 'size_and_position'):
                    values['window_width'] = self.width()
                    values['window_height'] = self.height()
                if window_memory in ('position', 'size_and_position'):
                    values['window_x'] = self.x()
                    values['window_y'] = self.y()
            # 批量一次落盘：逐项 set_value 会保存多次，放大与更新器并发写的冲突窗口
            cfg.set_values(values)
            log.debug("[config-save] 退出保存窗口状态完成")
        except Exception as e:
            import traceback
            log.error(f"[config-save] 退出保存窗口状态失败: {e}\n{traceback.format_exc()}")

    def _on_config_file_changed(self):
        """重新加载配置文件并刷新界面"""
        replacement = None
        try:
            if not self._can_replace_settings() or self._pending_ui_language is not None:
                self._config_reload_timer.start(100)
                return
            self._config_reload_timer.stop()

            # 重新加载配置
            log.info("[config-watch] 重新加载配置文件并刷新界面")
            cfg._load_config(None, save=False)
            self._apply_ui_theme(self._load_evernight_selection())

            # 重新初始化通知器
            try:
                from module.notification import init_notifiers
                init_notifiers()
            except Exception:
                pass

            # 更新日志界面的热键与日志悬浮窗开关
            if hasattr(self, 'logInterface'):
                self.logInterface.reloadConfigState()

            state = self.settingInterface.captureViewState()
            replacement = SettingInterface(self)
            self._replace_settings_interface(replacement, state)
            replacement = None

            # 只有在窗口可见时才显示提示
            if self.isVisible():
                InfoBar.success(
                    title=tr('配置已更新'),
                    content=tr("检测到配置文件变化，已自动重新加载"),
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                    parent=self
                )
        except Exception as e:
            # 只有在窗口可见时才显示提示
            if self.isVisible():
                InfoBar.warning(
                    title=tr('配置加载失败'),
                    content=str(e),
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                    parent=self
                )
        finally:
            if replacement is not None:
                replacement.hide()
                replacement.deleteLater()

    def _stopThemeListener(self):
        """停止主题监听线程"""
        if hasattr(self, 'themeListener') and self.themeListener:
            self.themeListener.stop()
            self.themeListener = None

    def _stopRunningTask(self):
        """停止正在运行的任务"""
        if hasattr(self, 'logInterface') and self.logInterface.isTaskRunning():
            self.logInterface.stopTask()
            # 等待进程结束
            if self.logInterface.process is not None:
                self.logInterface.process.waitForFinished(3000)
                # 如果还没结束，强制结束
                if self.logInterface.process is not None and self.logInterface.process.state() != 0:  # QProcess.NotRunning
                    self.logInterface.process.kill()
                    if self.logInterface.process is not None:
                        self.logInterface.process.waitForFinished(1000)

    def _onAppAboutToQuit(self):
        """应用即将退出时的兜底清理（例如窗口隐藏时通过 Dock 右键退出）"""
        if not self._quitting:
            self._force_quit = True
            self._do_quit(quit_app=False)

    def _do_quit(self, e=None, quit_app=True):
        """执行退出前的清理并退出程序
        e: 可选的 QCloseEvent，用于调用 e.accept()
        """
        if self._quitting:
            if e is not None:
                try:
                    e.accept()
                except Exception:
                    pass
            return
        self._quitting = True

        # 保存窗口尺寸和最大化状态
        log.info(f"[config-save] 主程序退出，保存窗口状态 PID={os.getpid()}（更新期间此处会与更新器并发写配置）")
        self._saveWindowState()

        try:
            self.hide()
            self.tray_icon.hide()
            QApplication.processEvents()
        except Exception:
            pass

        # 停止运行任务、定时器和主题监听
        self._language_change_timer.stop()
        self._config_reload_timer.stop()
        if self._evey_animation is not None:
            try:
                self._evey_animation.close()
            except Exception:
                pass
        self._stopRunningTask()
        self._stopThemeListener()

        # 可选地清理日志界面资源
        if hasattr(self, 'logInterface'):
            try:
                self.logInterface.cleanup()
            except Exception:
                pass

        # 如果传入了事件，接受它
        if e is not None:
            try:
                e.accept()
            except Exception:
                pass

        if quit_app:
            QApplication.quit()

    def closeEvent(self, e):
        """关闭窗口时根据配置执行对应操作"""
        if self._force_quit or _is_macos_quit_apple_event():
            self._do_quit(e)
            return

        from .card.messagebox_custom import MessageBoxCloseWindow

        default_action = 'minimize' if sys.platform == 'darwin' else 'ask'
        close_action = cfg.get_value('close_window_action', default_action)

        if close_action == 'ask':
            # 弹出询问对话框
            dialog = MessageBoxCloseWindow(self)
            dialog.exec()

            if dialog.action == 'minimize':
                # 最小化到托盘 / macOS 隐藏窗口
                e.ignore()
                if sys.platform == 'darwin':
                    self._saveWindowState()
                self.hide()
                if sys.platform != 'darwin':
                    self.tray_icon.showMessage(
                        'March7th Assistant',
                        tr('程序已最小化到托盘'),
                        QSystemTrayIcon.Information,
                        2000
                    )
                # 若用户选择记住，则刷新设置界面以同步显示
                try:
                    if dialog.rememberCheckBox.isChecked():
                        self._on_config_file_changed()
                except Exception:
                    pass
            elif dialog.action == 'close':
                # 关闭程序
                self._do_quit(e)
            else:
                # 用户取消操作（例如点击了 X 按钮）
                e.ignore()
        elif close_action == 'minimize':
            # 直接最小化到托盘 / macOS 隐藏窗口
            e.ignore()
            if sys.platform == 'darwin':
                self._saveWindowState()
            self.hide()
        elif close_action == 'close':
            # 直接关闭程序
            self._do_quit(e)
        else:
            # 默认行为：最小化到托盘 / macOS 隐藏窗口
            e.ignore()
            if sys.platform == 'darwin':
                self._saveWindowState()
            self.hide()
            if sys.platform != 'darwin':
                self.tray_icon.showMessage(
                    'March7th Assistant',
                    tr('程序已最小化到托盘'),
                    QSystemTrayIcon.Information,
                    2000
                )

    def startGame(self):
        start_game_button = self.navigationInterface.widget('startGameButton')
        if start_game_button:
            start_game_button.setEnabled(False)
        try:
            game = get_game_controller()
            if game.is_game_running():
                InfoBar.warning(
                    title=tr('游戏已在运行'),
                    content=tr('无需重复启动游戏'),
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=5000,
                    parent=self
                )
                if start_game_button:
                    start_game_button.setEnabled(True)
                return
            if cfg.cloud_game_enable and cfg.browser_type == "integrated" and not game.is_integrated_browser_downloaded():
                InfoBar.warning(
                    title=tr('正在下载内置浏览器(ง •̀_•́)ง'),
                    content=tr("下载成功后，将自动启动云·星穹铁道"),
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=10000,
                    parent=self
                )
            elif cfg.cloud_game_enable:
                InfoBar.warning(
                    title=tr('正在启动游戏(❁´◡`❁)'),
                    content="",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=5000,
                    parent=self
                )
            elif getattr(cfg, "playcover_enable", False):
                InfoBar.warning(
                    title=tr('正在启动游戏(❁´◡`❁)'),
                    content="",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=5000,
                    parent=self
                )
            elif sys.platform == 'win32':
                from tasks.game.starrailcontroller import StarRailController
                starrail = StarRailController(cfg=cfg, logger=log)
                if cfg.auto_battle_detect_enable:
                    starrail.change_auto_battle(True)
        except Exception as e:
            log.error(f"启动游戏准备失败: {e}")
            InfoBar.warning(
                title=tr('启动失败'),
                content=str(e),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )
            if start_game_button:
                start_game_button.setEnabled(True)
            return

        self.game_launch_thread = GameLaunchThread(game, cfg)
        self.game_launch_thread.finished_signal.connect(self.on_game_launched)
        self.game_launch_thread.start()

    def on_game_launched(self, result):
        if result == GameStartStatus.SUCCESS:
            InfoBar.success(
                title=tr('启动成功(＾∀＾●)'),
                content="",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
        elif result == GameStartStatus.BROWSER_DOWNLOAD_FAIL:
            InfoBar.warning(
                title=tr('浏览器或驱动下载失败 (╥╯﹏╰╥)'),
                content=tr("请检查网络连接是否正常"),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )
        elif result == GameStartStatus.BROWSER_LAUNCH_FAIL:
            InfoBar.warning(
                title=tr('云游戏启动失败(╥╯﹏╰╥)'),
                content=tr("请检查所选浏览器是否存在，网络连接是否正常"),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )
        elif result == GameStartStatus.LOCAL_LAUNCH_FAIL:
            if getattr(cfg, "playcover_enable", False):
                title = tr('PlayCover 游戏启动失败(╥╯﹏╰╥)')
                content = tr("请确认已在 PlayCover 中安装《崩坏：星穹铁道》")
            else:
                title = tr('游戏路径配置错误(╥╯﹏╰╥)')
                content = tr("请在“设置”→“程序”中配置")
            InfoBar.warning(
                title=title,
                content=content,
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )
        else:
            InfoBar.warning(
                title=tr('启动失败'),
                content=str(self.game_launch_thread.error_msg),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )
        start_game_button = self.navigationInterface.widget('startGameButton')
        if start_game_button:
            start_game_button.setEnabled(True)
