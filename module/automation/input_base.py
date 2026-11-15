from abc import ABC, abstractmethod
import sys
from module.config.platform import get_control_backend


def background_enabled(config):
    return (
        sys.platform == "win32"
        and config.get_value("local_control_mode", "foreground") == "background"
        and get_control_backend(config) == "local"
    )


class InputBase(ABC):
    handles_pause = False
    is_background = False

    def release_all(self):
        """释放后端持有的输入；无状态后端无需处理。"""

    def close(self):
        self.release_all()

    @abstractmethod
    def mouse_click(self, x, y):
        """在屏幕上的（x，y）位置执行鼠标点击操作"""

    @abstractmethod
    def mouse_down(self, x, y):
        """在屏幕上的（x，y）位置按下鼠标左键"""

    @abstractmethod
    def mouse_up(self):
        """释放鼠标左键"""

    @abstractmethod
    def mouse_move(self, x, y):
        """将鼠标光标移动到屏幕上的（x，y）位置"""

    @abstractmethod
    def mouse_drag(self, start_x, start_y, end_x, end_y, duration=0.5, end_pause=0.0, repeats=1):
        """连续执行相同拖动，仅最后一次在松手前停留 end_pause 秒"""

    @abstractmethod
    def mouse_scroll(self, count, direction=-1, pause=True):
        """在当前光标位置滚动鼠标滚轮"""

    @abstractmethod
    def press_key(self, key, wait_time=0.2):
        """模拟键盘按键，按下后等待一段时间再释放"""

    @abstractmethod
    def press_key_down(self, key):
        """按下键盘上的指定键（不释放）"""

    @abstractmethod
    def press_key_up(self, key):
        """释放键盘上的指定键"""

    @abstractmethod
    def secretly_press_key(self, key, wait_time=0.2):
        """静默地模拟键盘按键（不输出日志）"""

    @abstractmethod
    def press_mouse(self, wait_time=0.2):
        """在当前位置按下鼠标左键并保持指定时间后释放"""

    @abstractmethod
    def secretly_write(self, text, interval=0.1):
        """静默地模拟键盘输入字符串（不输出日志）"""
