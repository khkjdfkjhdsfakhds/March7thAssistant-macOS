"""Keep Qt and the platform taskbar/dock icon on the same application artwork."""
import hashlib
from pathlib import Path
import subprocess
import sys

from PIL import Image
from PySide6.QtCore import QEvent, QObject, QSize, Slot
from PySide6.QtGui import QIcon, QImage, QPixmap, QPlatformSurfaceEvent
from PySide6.QtWidgets import QApplication

from module.logger import log
from .theme_assets import application_icon_fallback_png


_ROOT = Path(__file__).resolve().parents[2]
# Separate source checkouts/installations must not inherit a taskbar group from
# the shared Python runtime. Windows 11 caches a group's artwork at creation,
# so each icon below gets a stable visual identity within this installation.
_APP_ID = 'March7thAssistant.' + hashlib.sha256(str(_ROOT).casefold().encode()).hexdigest()[:16]


def load_application_icon(icon_path, fallback_path=None):
    """Load an application QIcon, decoding .ico via Pillow or PNG fallback if needed."""
    icon = QIcon(icon_path)
    if not icon.isNull() and not icon.pixmap(32, 32).isNull():
        return icon

    if Path(icon_path).is_file():
        try:
            with Image.open(icon_path) as img:
                rgba = img.convert('RGBA')
                raw = rgba.tobytes('raw', 'RGBA')
                qimage = QImage(raw, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888).copy()
                if not qimage.isNull():
                    return QIcon(QPixmap.fromImage(qimage))
        except Exception:
            pass

    if fallback_path is None:
        is_evernight = 'evernight' in Path(icon_path).as_posix().lower()
        fallback_path = application_icon_fallback_png(is_evernight)
    if fallback_path and Path(fallback_path).is_file():
        fb = QIcon(fallback_path)
        if not fb.isNull() and not fb.pixmap(32, 32).isNull():
            return fb
    return icon


class _TaskbarProperties(QObject):
    """Release the shell-owned values before the native window is destroyed."""
    def __init__(self, window, store, keys):
        super().__init__(window)
        self.store = store
        self.keys = keys
        window.windowHandle().installEventFilter(self)
        QApplication.instance().aboutToQuit.connect(self.clear)

    @Slot()
    def clear(self):
        from pythoncom import VT_EMPTY
        from pywintypes import com_error
        from win32com.propsys import propsys
        if self.store is not None:
            try:
                for key in self.keys:
                    self.store.SetValue(key, propsys.PROPVARIANTType(None, VT_EMPTY))
            except com_error as error:
                log.debug(f'清理任务栏窗口属性失败：{error}')
            self.store = None

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.PlatformSurface and
                event.surfaceEventType() == QPlatformSurfaceEvent.SurfaceEventType.SurfaceAboutToBeDestroyed):
            self.clear()
        return False


def set_application_icon(window, icon_path, display_name):
    icon = load_application_icon(icon_path)
    QApplication.setWindowIcon(icon)
    window.setWindowIcon(icon)
    if hasattr(window, 'tray_icon'):
        window.tray_icon.setIcon(icon)
    sidebar_logo = getattr(window, '_macLogoLabel', None)
    if sidebar_logo is not None:
        size = sidebar_logo.size()
        if size.width() > 0 and size.height() > 0:
            sidebar_logo.setPixmap(icon.pixmap(QSize(size.width() * 2, size.height() * 2)))

    if sys.platform != 'win32':
        return
    from pywintypes import com_error
    from win32com.propsys import propsys, pscon

    try:
        store = propsys.SHGetPropertyStoreForWindow(int(window.winId()))
        icon_file = Path(icon_path).resolve()
        visual_id = _APP_ID + '.Icon' + hashlib.sha256(icon_file.read_bytes()).hexdigest()[:12]
        command = [sys.executable]
        if not getattr(sys, 'frozen', False):
            command.append(str(_ROOT / 'app.py'))
        properties = (
            (pscon.PKEY_AppUserModel_RelaunchCommand, subprocess.list2cmdline(command)),
            (pscon.PKEY_AppUserModel_RelaunchDisplayNameResource, display_name),
            (pscon.PKEY_AppUserModel_RelaunchIconResource, str(icon_file) + ',0'),
            # A different visual identity makes Explorer create a fresh button;
            # re-stamping the same ID leaves its cached tile unchanged on Win11.
            # Restoring an icon restores its ID; no random IDs accumulate.
            (pscon.PKEY_AppUserModel_ID, visual_id),
        )
        state = getattr(window, '_taskbar_properties', None)
        if state is None:
            window._taskbar_properties = _TaskbarProperties(window, store, [key for key, _ in properties])
        else:
            state.store = store
            window.windowHandle().installEventFilter(state)
        for key, value in properties:
            store.SetValue(key, propsys.PROPVARIANTType(value))
    except com_error as error:
        log.warning(f'同步 Windows 任务栏图标失败：{error}')
