"""Load the optional Long Night artwork, on the GUI thread, only after unlock."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image
from PySide6.QtGui import QIcon, QImage, QPixmap

from .evernight import EVERNIGHT_AVATAR, EVERNIGHT_BANNER
from .theme_assets import application_icon_path


@dataclass(frozen=True)
class EvernightArtwork:
    banner: Image.Image
    avatar: QPixmap
    decorations: dict[str, QPixmap]


def _pixmap(path):
    image = QPixmap(path)
    if image.isNull():
        raise OSError(f'无法读取图片：{path}')
    return image


def _ico_fallback_loadable(path):
    """Decode an existing .ico with Pillow if Qt's ICO imageformat plugin is unavailable."""
    if not Path(path).is_file():
        return False
    try:
        with Image.open(path) as img:
            rgba = img.convert('RGBA')
            raw = rgba.tobytes('raw', 'RGBA')
            qimage = QImage(raw, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888).copy()
        return not qimage.isNull()
    except Exception:
        return False


@lru_cache(maxsize=1)
def evernight_artwork():
    """Publish a complete set or raise OSError, leaving the ordinary theme intact."""
    try:
        with Image.open(EVERNIGHT_BANNER) as image:
            banner = image.convert('RGB')
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise OSError(f'{EVERNIGHT_BANNER}: {error}') from error

    icon = application_icon_path(True)
    if QIcon(icon).pixmap(32, 32).isNull() and not _ico_fallback_loadable(icon):
        raise OSError(f'无法读取图标：{icon}')
    names = ('evey-decoration-folded.png', 'evey-decoration-upright.png', 'evey-decoration-wide.png')
    return EvernightArtwork(banner, _pixmap(EVERNIGHT_AVATAR),
                            {name: _pixmap(f'./assets/app/images/evernight/{name}') for name in names})
