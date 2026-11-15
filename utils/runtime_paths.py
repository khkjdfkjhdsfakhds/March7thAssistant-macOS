# coding:utf-8
"""运行时路径解析：区分源码目录模式与 macOS 独立 .app 包模式。"""
import os
import sys
import tempfile

APP_BUNDLE_MARKER = "/Contents/Resources/app"


def get_app_root() -> str:
    """返回代码与只读资源根目录（源码模式下为仓库根目录，独立包模式下为 Contents/Resources/app）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_bundle_mode(entry_file: str | None = None) -> bool:
    if os.environ.get("M7A_FORCE_BUNDLE_MODE") == "1":
        return True
    probe = os.path.abspath(entry_file) if entry_file else get_app_root()
    return APP_BUNDLE_MARKER in probe.replace("\\", "/")


def get_user_data_dir() -> str:
    """返回可写用户数据目录（config.yaml、logs/、temp/、config/ 等）。"""
    env_dir = os.environ.get("M7A_DATA_DIR")
    if env_dir:
        return os.path.abspath(os.path.expanduser(env_dir))
    if is_bundle_mode():
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "March7thAssistant")
    return get_app_root()


def get_working_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return get_user_data_dir()


def _ensure_symlink(src: str, dst: str) -> None:
    if not os.path.exists(src):
        return
    if os.path.islink(dst):
        try:
            if os.readlink(dst) == src:
                return
        except OSError:
            pass
        fd, tmp_name = tempfile.mkstemp(prefix=".link_", dir=os.path.dirname(dst))
        os.close(fd)
        os.unlink(tmp_name)
        os.symlink(src, tmp_name)
        os.replace(tmp_name, dst)
        return
    if not os.path.exists(dst):
        os.symlink(src, dst)


def setup_runtime_environment(entry_file: str | None = None) -> str:
    """初始化 sys.path 与当前工作目录；独立 .app 模式下将只读资源目录软链至 Application Support。"""
    if getattr(sys, "frozen", False):
        wd = os.path.dirname(os.path.abspath(sys.executable))
        os.chdir(wd)
        return wd

    app_root = get_app_root()
    if app_root not in sys.path:
        sys.path.insert(0, app_root)

    if is_bundle_mode(entry_file):
        data_dir = get_user_data_dir()
        os.makedirs(data_dir, exist_ok=True)
        for rel_name in ("assets", "3rdparty", "tools"):
            _ensure_symlink(os.path.join(app_root, rel_name), os.path.join(data_dir, rel_name))
        os.chdir(data_dir)
        return data_dir

    os.chdir(app_root)
    return app_root
