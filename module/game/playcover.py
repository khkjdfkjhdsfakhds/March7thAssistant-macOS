import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Optional

import cv2
import psutil
from PIL import Image

from module.config.config import Config
from module.game.base import GameControllerBase
from module.game.cg_client import (
    CGHelperError,
    CGPlayCoverClient,
    CN_BUNDLE_ID,
    resolve_playcover_bundle,
)
from module.game.maatools_client import MaaToolsClient
from utils.logger.logger import Logger

STANDARD_WIDTH = 1920
STANDARD_HEIGHT = 1080
VALID_TRANSPORTS = {"auto", "maatools", "cg"}


class PlayCoverGameController(GameControllerBase):
    """
    macOS PlayCover iOS 客户端控制器（双传输后端）：
    - maatools: hguandl/PlayCover 内置 MaaTools TCP 服务（默认 127.0.0.1:1717），全程纯后台截图与多指触控
    - cg: Official PlayCover 3.1.0 CoreGraphics + screencapture 通道，按 16:9 剥离标题栏并自动激活窗口防止 PlayTools brk #0x1 崩溃
    - auto（默认）: 150ms 探测 MaaTools；可达优先走 MaaTools，否则自动回退 cg
    """

    PLAYCOVER_APPS_DIR = os.path.expanduser("~/Library/Containers/io.playcover.PlayCover/Applications")

    def __init__(self, cfg: Config, logger: Optional[Logger] = None) -> None:
        super().__init__(script_path=cfg.script_path, logger=logger)
        self.cfg = cfg
        self.client = MaaToolsClient(
            host=cfg.get_value("playcover_maatools_host", "127.0.0.1"),
            port=int(cfg.get_value("playcover_maatools_port", 1717)),
        )
        self.cg_client = CGPlayCoverClient(
            bundle_id=CN_BUNDLE_ID,
            restore_focus=bool(cfg.get_value("playcover_restore_focus", True)),
        )
        self.bundle_id: str = CN_BUNDLE_ID
        self._resolved_app_path: Optional[Path] = None
        self._input_handler = None
        self._lock = threading.Lock()
        self.reload_config()

    def reload_config(self) -> None:
        preferred = self.cfg.get_value("playcover_bundle_id", CN_BUNDLE_ID)
        bundle_id, app_path = resolve_playcover_bundle(
            preferred,
            search_dirs=[Path(self.PLAYCOVER_APPS_DIR), Path("/Applications")],
        )
        self.bundle_id = bundle_id
        self._resolved_app_path = app_path
        self.cg_client.bundle_id = bundle_id
        self.cg_client.restore_focus = bool(self.cfg.get_value("playcover_restore_focus", True))
        self.client.host = self.cfg.get_value("playcover_maatools_host", "127.0.0.1")
        self.client.port = int(self.cfg.get_value("playcover_maatools_port", 1717))

    @property
    def transport_mode(self) -> str:
        raw = str(self.cfg.get_value("playcover_transport", "auto") or "auto").strip().lower()
        return raw if raw in VALID_TRANSPORTS else "auto"

    @property
    def app_path(self) -> str:
        if self._resolved_app_path is not None:
            return str(self._resolved_app_path)
        return os.path.join(self.PLAYCOVER_APPS_DIR, f"{self.bundle_id}.app")

    def probe_maatools(self, timeout: float = 0.15) -> bool:
        if self.client.is_connected:
            return True
        old_timeout = self.client.timeout
        self.client.timeout = float(timeout)
        try:
            return self.client.connect()
        finally:
            self.client.timeout = old_timeout

    def active_transport(self, probe_timeout: float = 0.15) -> str:
        self.cg_client.bundle_id = self.bundle_id
        self.cg_client.restore_focus = bool(self.cfg.get_value("playcover_restore_focus", True))
        mode = self.transport_mode
        if mode == "maatools":
            return "maatools"
        if mode == "cg":
            return "cg"
        return "maatools" if self.probe_maatools(timeout=probe_timeout) else "cg"

    def _find_process(self) -> Optional[psutil.Process]:
        exe_dir = self.app_path + os.sep
        for proc in psutil.process_iter(attrs=["pid", "exe"]):
            try:
                exe = proc.info["exe"] or ""
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if exe.startswith(exe_dir):
                return proc
        return None

    def is_game_running(self) -> bool:
        if self._find_process() is not None:
            return True
        if self.transport_mode != "maatools":
            try:
                return self.cg_client.window_info(include_all=True) is not None
            except CGHelperError:
                return False
        return False

    def start_game_process(self, *, background: bool | None = None) -> bool:
        self.reload_config()
        if not os.path.exists(self.app_path):
            self.log_error(f"未找到 PlayCover 游戏：{self.app_path}")
            return False
        if self.is_game_running():
            return True
        mode = self.transport_mode
        use_bg = (mode in ("auto", "maatools")) if background is None else bool(background)
        open_flag = "-g" if use_bg else "-a"
        result = subprocess.run(["open", open_flag, self.app_path], capture_output=True, text=True)
        if result.returncode != 0:
            self.log_error(f"启动游戏失败：{result.stderr.strip()}")
            return False
        self.log_info(f"游戏启动（{open_flag}, {mode}）：{self.app_path}")
        return True

    def stop_game(self) -> bool:
        try:
            if self._input_handler is not None:
                self._input_handler.release_all()
            proc = self._find_process()
            if proc is None:
                return True
            self.client.close()
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except psutil.TimeoutExpired:
                proc.kill()
            self.log_info(f"游戏终止：{self.bundle_id}")
            return True
        except Exception as e:
            self.log_error(f"终止游戏时发生错误：{e}")
            return False

    def get_window_handle(self) -> int:
        """maatools 返回进程 PID，cg 返回 CGWindowID；未就绪返回 0。"""
        transport = self.active_transport()
        if transport == "maatools":
            proc = self._find_process()
            if proc is None or not self.client.connect():
                return 0
            return proc.pid
        try:
            info = self.cg_client.window_info()
            return int(info.wid) if info is not None and info.wid > 0 else 0
        except CGHelperError:
            return 0

    def switch_to_game(self) -> bool:
        transport = self.active_transport()
        if transport == "maatools":
            if self.get_window_handle() == 0:
                self.log_debug("游戏未运行或 MaaTools 未连接")
                return False
            return True
        try:
            self.cg_client.activate()
            return True
        except CGHelperError as e:
            self.log_debug(f"激活 PlayCover 窗口失败：{e}")
            return False

    def get_resolution(self):
        return STANDARD_WIDTH, STANDARD_HEIGHT

    def get_input_handler(self):
        if self._input_handler is None:
            from module.automation.playcover_input import PlayCoverInput
            self._input_handler = PlayCoverInput(self, self.logger)
        return self._input_handler

    def copy(self, text: str) -> None:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=False)

    def screenshot_bgr(self):
        """标准 1920x1080 分辨率的 BGR 截图，失败返回 None。"""
        transport = self.active_transport()
        if transport == "maatools":
            image = self.client.screenshot()
        else:
            try:
                image = self.cg_client.capture_bgr()
            except CGHelperError as e:
                self.log_error(f"CG 截图失败：{e}")
                return None
        if image is None:
            return None
        if image.shape[1] != STANDARD_WIDTH or image.shape[0] != STANDARD_HEIGHT:
            image = cv2.resize(image, (STANDARD_WIDTH, STANDARD_HEIGHT), interpolation=cv2.INTER_AREA)
        return image

    def take_screenshot(self, crop=(0, 0, 1, 1)):
        """
        截图并按比例裁剪

        Returns:
            (PIL RGB 图像, (left, top, width, height), 缩放比例) 坐标为标准坐标；失败返回 None
        """
        image = self.screenshot_bgr()
        if image is None:
            return None
        left = min(max(int(STANDARD_WIDTH * crop[0]), 0), STANDARD_WIDTH - 1)
        top = min(max(int(STANDARD_HEIGHT * crop[1]), 0), STANDARD_HEIGHT - 1)
        width = max(min(int(STANDARD_WIDTH * crop[2]), STANDARD_WIDTH - left), 1)
        height = max(min(int(STANDARD_HEIGHT * crop[3]), STANDARD_HEIGHT - top), 1)
        image = image[top:top + height, left:left + width]
        screenshot = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        return screenshot, (left, top, width, height), 1

    def to_touch(self, x: float, y: float) -> tuple[int, int]:
        """标准坐标转 MaaTools 触控坐标"""
        if not self.client.is_connected:
            self.client.connect()
        tw = self.client.touch_width or STANDARD_WIDTH
        th = self.client.touch_height or STANDARD_HEIGHT
        return round(x * tw / STANDARD_WIDTH), round(y * th / STANDARD_HEIGHT)

    def wait_maatools(self, timeout: float = 120) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.client.connect():
                return True
            time.sleep(2)
        return False

    def wait_ready(self, timeout: float = 120) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            mode = self.transport_mode
            if mode == "maatools":
                if self.probe_maatools(timeout=0.5):
                    return True
            elif mode == "cg":
                if self.cg_client.is_window_ready():
                    return True
            else:
                if self.probe_maatools(timeout=0.15) or self.cg_client.is_window_ready():
                    return True
            time.sleep(1.0)
        return False
