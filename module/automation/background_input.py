"""跨平台后台输入异常与等待常量。macOS 不依赖 Win32 后台输入模块。"""

WINDOW_WAIT_SECONDS = 30


class InputInterrupted(RuntimeError):
    """输入被中断或窗口持续不可用（不触发关闭重启游戏）。"""


class GameWindowLost(RuntimeError):
    """游戏进程已退出或窗口丢失。"""
