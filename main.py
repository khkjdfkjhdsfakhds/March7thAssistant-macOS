import os
import sys
import argparse

# 将当前工作目录设置为程序所在的目录（macOS 独立 .app 模式下写入 ~/Library/Application Support/March7thAssistant）。
_APP_ROOT = os.path.dirname(os.path.abspath(__file__))
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)
from utils.runtime_paths import setup_runtime_environment
setup_runtime_environment(__file__)

from utils.console import ensure_utf8_output

ensure_utf8_output()

from utils.dpi import configure_dpi_awareness
from utils.tasks import AVAILABLE_TASKS, CLI_ONLY_TASKS, UNSUPPORTED_TASK, task_is_supported

configure_dpi_awareness()

AFTER_FINISH_CHOICES = ("None", "Exit", "Loop", "Shutdown", "Sleep", "Hibernate", "Restart", "Logoff", "TurnOffDisplay", "RunScript")


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        prog="March7th Assistant",
        description="三月七小助手 - 崩坏：星穹铁道自动化工具 (CLI / macOS PlayCover)",
        epilog='更多信息请访问: https://m7a.top\n'
               '运行自定义流程: ./m7a --workflow-name "流程名称"\n'
               '脚本与 AI Agent 请使用 ./m7a，说明见 README_MACOS.md\n'
               '退出码: 0 成功 / 1 失败 / 2 参数错误 / 3 需先在图形界面完成首次使用确认 / '
               '4 已有任务在运行 / 5 未获得管理员权限 / 6 任务被停止',
        add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    positional = parser.add_argument_group("位置参数")
    positional.add_argument(
        "task",
        nargs="?",
        choices=[*AVAILABLE_TASKS, *CLI_ONLY_TASKS],
        metavar="TASK",
        help="要执行的任务名称（可选，不指定则执行完整运行）",
    )

    optional = parser.add_argument_group("可选参数")
    optional.add_argument("--no-run-immediately", action="store_true", help="禁用立即运行")
    optional.add_argument("-h", "--help", action="help", help="显示此帮助信息并退出")
    optional.add_argument("-l", "--list", action="store_true", help="列出所有可用的任务")
    optional.add_argument("--list-workflows", action="store_true", help="列出所有可用的流程")
    optional.add_argument("--workflow-name", metavar="NAME", help="按名称运行流程（用 --list-workflows 查看可用名称）")
    optional.add_argument("--workflow-step-path", metavar="PATH", help="仅执行指定步骤路径，例如 0/1/2")

    agent = parser.add_argument_group("脚本与 AI Agent")
    agent.add_argument("--status", action="store_true", help="输出安装、配置与运行状态（JSON，无需权限）")
    agent.add_argument("--version", action="store_true", help="显示版本号并退出")
    agent.add_argument("--json", action="store_true", help="以 JSON 输出结果（用于 --list、--list-workflows、--follow、--control 与任务运行）")
    agent.add_argument("--non-interactive", action="store_true", help="非交互模式：任何情况下都不等待按回车")
    agent.add_argument(
        "--after-finish",
        metavar="ACTION",
        choices=AFTER_FINISH_CHOICES,
        help="仅本次运行生效的完成后操作，不修改配置（" + " / ".join(AFTER_FINISH_CHOICES) + "）",
    )
    agent.add_argument("--force", action="store_true", help="已有任务在运行时仍然执行（默认拒绝，避免两个自动化进程同时操作游戏）")
    agent.add_argument("--detach", action="store_true", help="后台启动任务后立即返回运行编号，不等待结束")
    agent.add_argument("--follow", metavar="RUN_ID", help="跟随某次运行的输出直到结束，退出码与该运行一致（RUN_ID 可用 latest）")
    agent.add_argument("--control", nargs=2, metavar=("RUN_ID", "ACTION"), help="向运行中的任务发送 pause / resume / stop（RUN_ID 可用 current）")
    agent.add_argument("--run-id", help=argparse.SUPPRESS)
    agent.add_argument("--minimize-console", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()

    from utils.agent_skill import sync_installed_skills
    if not os.environ.get("MARCH7TH_DESKTOP_TWIN"):
        sync_installed_skills()

    if args.list or args.list_workflows:
        os.environ["MARCH7TH_CONFIG_READONLY"] = "1"

    if args.version:
        from utils.cli_entry import read_version
        print(read_version())
        sys.exit(0)

    if args.list:
        from module.localization import load_language
        from utils.tasks import supported_tasks, task_display_names

        load_language()
        names = task_display_names(supported_tasks(include_cli=True))
        if args.json:
            import json
            print(json.dumps([{"id": task_id, "name": name} for task_id, name in names.items()], ensure_ascii=True))
            sys.exit(0)
        print("\n可用的任务列表:")
        print("-" * 40)
        for task_id, task_name in names.items():
            print(f"  {task_id:<20} {task_name}")
        print("-" * 40)
        print("\n使用示例:")
        print("  启动并执行完整运行:     ./m7a main")
        print("  执行货币战争:           ./m7a currencywars")
        sys.exit(0)

    if args.list_workflows:
        if args.json:
            from contextlib import redirect_stdout
            with redirect_stdout(sys.stderr):
                from module.workflow import list_workflow_names
                names = list_workflow_names()
        else:
            from module.workflow import list_workflow_names
            names = list_workflow_names()
        if args.json:
            import json
            print(json.dumps({"workflows": names}, ensure_ascii=True))
            sys.exit(0)
        print("\n可用的流程列表:")
        print("-" * 40)
        if names:
            for name in names:
                print(f"  {name}")
        else:
            print("  （暂无流程，请先在图形界面的流程编排中创建）")
        print("-" * 40)
        sys.exit(0)

    if args.status:
        from utils.cli_entry import print_status
        sys.exit(print_status())

    if args.follow:
        from utils.cli_entry import follow_command
        sys.exit(follow_command(args.follow, json_output=args.json))

    if args.control:
        from utils.cli_entry import control_command
        sys.exit(control_command(args.control[0], args.control[1], json_output=args.json))

    if args.task and args.workflow_name:
        parser.error("不能同时指定 TASK 和 --workflow-name")

    if args.workflow_step_path and not args.workflow_name:
        parser.error("--workflow-step-path 需要配合 --workflow-name 使用")

    from utils.runs import is_valid_run_id
    if args.run_id is not None and not is_valid_run_id(args.run_id):
        parser.error("--run-id 格式无效")

    return args


args = parse_args()

desktop_twin_context = None
if sys.platform == "win32" and os.environ.get("MARCH7TH_DESKTOP_TWIN"):
    from utils.desktop_twin import SessionContext
    try:
        desktop_twin_context = SessionContext.from_environment()
        desktop_twin_context.check()
    except Exception as error:
        print(f"桌面分身校验失败：{error}", flush=True)
        sys.exit(1)
    if args.force or args.task == "app_update":
        print("请在主桌面执行程序更新或强制运行", flush=True)
        sys.exit(2)

if args.non_interactive:
    os.environ["MARCH7TH_NON_INTERACTIVE"] = "1"
if args.after_finish:
    os.environ["MARCH7TH_AFTER_FINISH"] = args.after_finish

import atexit
import base64
import time

adb_check_only = args.task == "adb_check" and not args.workflow_name
requires_admin = not adb_check_only

if sys.platform == "win32":
    from utils.admin import is_user_admin
    if requires_admin and not is_user_admin():
        from unittest.mock import patch
        with patch.dict(os.environ, {"MARCH7TH_CONFIG_READONLY": "1"}):
            from module.config import cfg
            from module.config.platform import get_control_backend
        requested = "workflow" if args.workflow_name else args.task or "main"
        requires_admin = task_is_supported(requested, cfg) and not (
            requested == "screen_test" and get_control_backend(cfg) == "adb"
        )
    if requires_admin and not is_user_admin() and not args.run_id:
        from utils.cli_entry import run_task_elevated
        sys.exit(run_task_elevated(sys.argv[1:], json_output=args.json, detach=args.detach))
elif args.detach and not args.run_id:
    from utils.cli_entry import run_task_detached
    sys.exit(run_task_detached(sys.argv[1:], json_output=args.json))

if args.minimize_console:
    from utils.console import minimize_console_window
    minimize_console_window()

from utils.cli_entry import read_version
from utils.console import is_gui_started, is_docker_started, is_non_interactive
from utils.runs import (
    RunSession,
    EXIT_OK,
    EXIT_FAILED,
    EXIT_FIRST_RUN_REQUIRED,
    EXIT_BUSY,
    EXIT_ELEVATION_FAILED,
    EXIT_STOPPED,
    STATUS_INTERRUPTED,
    STATUS_STOPPED,
    LOCK_BUSY,
    LOCK_FORCED,
    LOCK_UNAVAILABLE,
    INVOKER_DESKTOP_TWIN,
    describe_run,
    exit_code_of,
)


def _run_invoker():
    if desktop_twin_context:
        return INVOKER_DESKTOP_TWIN
    if is_gui_started():
        return "gui"
    if is_docker_started():
        return "docker"
    if args.run_id:
        return "entry"
    if is_non_interactive():
        return "non_interactive"
    return "cli"


run_session = RunSession.begin(
    run_id=args.run_id,
    task=None if args.workflow_name else (args.task or "main"),
    workflow=args.workflow_name,
    workflow_step_path=args.workflow_step_path,
    argv=sys.argv[1:],
    invoker=_run_invoker(),
    version=read_version(),
)

if sys.platform == "win32" and requires_admin and not is_user_admin():
    _message = "没有获得管理员权限，任务未运行。如果开启了免 UAC 运行，请在图形界面「设置 → 杂项」中关闭后重新开启"
    print(_message, flush=True)
    run_session.note(error=_message)
    run_session.finish(EXIT_ELEVATION_FAILED)
    sys.exit(EXIT_ELEVATION_FAILED)

from module.config import cfg
from module.config.platform import ProfileAssetNotFoundError, TouchProfileInputError, get_control_backend, get_ui_profile
from module.logger import log
import logging

logging.getLogger("March7thAssistant").addHandler(run_session.error_log_handler())
from module.notification import notif
from module.telemetry import telemetry
from module.notification.notification import NotificationLevel
from module.localization import load_language, tr

load_language()
from module.ocr import ocr
from module.workflow import WorkflowRunner, load_workflow_execution_payload, describe_available_workflows
from utils.screenshot_util import save_error_screenshot

import tasks.game as game
from module.game import cloud_game, playcover_game
from module.game.cg_client import CGHelperError
from module.game.cloud import CloudGameZeroDurationError
import tasks.reward as reward
import tasks.challenge as challenge
import tasks.version as version
import tasks.version.app_update as app_update_task

from tasks.daily.daily import Daily
from tasks.daily.fight import Fight
from tasks.power.power import Power
from tasks.weekly.universe import Universe
from tasks.daily.redemption import Redemption
from tasks.weekly.currency_wars import CurrencyWars
from tasks.weekly.divergent_universe import DivergentUniverse
from tasks.base.genshin_starRail_fps_unlocker import Genshin_StarRail_fps_unlocker
from tasks.base import screen_test

from utils.console import pause_on_error, pause_on_success, pause_always
from utils.pause import pause_ctl, RunStopRequested, STOP_GRACE_SECONDS
from module.automation import auto
from utils.tasks import PAUSABLE_TASKS
from utils.temporary_graphics import recover_temporary_graphics, restore_temporary_graphics
from utils.windows_power import task_power_request

telemetry.init(
    enabled=cfg.get_value("telemetry_enable", True),
    telemetry_id=cfg.get_value("telemetry_id", ""),
    telemetry_secret=cfg.get_value("telemetry_secret", ""),
    version=cfg.version,
)
telemetry.track_feature("run_invoker", run_session.record["invoker"])

if not adb_check_only and not is_docker_started():
    try:
        from utils.install_registry import register_install
        register_install(cfg.version)
    except Exception:
        pass

EXCLUSIVE_ACTIONS = PAUSABLE_TASKS | {"game", "game_update", "game_pre_download", "app_update", "adb_check"}


def _force_stop():
    log.error(f"任务未能在 {STOP_GRACE_SECONDS} 秒内停在安全位置，强制结束进程")
    run_session.note(status=STATUS_STOPPED, error="已按停止指令强制结束")
    restore_temporary_graphics(final=True, blocking=False)
    run_session.finish(EXIT_STOPPED)
    os._exit(EXIT_STOPPED)


pause_ctl.on_stop_timeout = _force_stop


def ensure_exclusive_run():
    result = run_session.acquire_lock(force=args.force)
    if result.status == LOCK_BUSY:
        log.error(f"已有任务正在运行：{describe_run(result.holder)}，本次未执行。请等待其结束后再试，确需同时运行请加 --force")
        pause_on_error()
        sys.exit(EXIT_BUSY)
    if result.status == LOCK_UNAVAILABLE:
        if desktop_twin_context:
            log.error(f"无法取得桌面分身运行锁：{result.error}")
            sys.exit(EXIT_FAILED)
        log.warning(f"运行锁不可用（{result.error}），无法确认是否已有其他任务在运行，本次照常执行")
    elif result.status == LOCK_FORCED:
        log.warning(f"已按 --force 继续执行，忽略正在运行的{describe_run(result.holder)}")


def first_run():
    if not is_docker_started() and not cfg.get_value(base64.b64decode("YXV0b191cGRhdGU=").decode("utf-8")):
        log.error("首次使用请先打开图形界面 March7th Launcher，阅读并确认免责声明")
        pause_always()
        sys.exit(EXIT_FIRST_RUN_REQUIRED)


def run_main_actions(no_run_immediately=False):
    is_first_run = no_run_immediately
    while True:
        if is_first_run:
            is_first_run = False
            game.after_finish_is_loop()
            continue
        if cfg.notify_merge:
            notif.start_batch()
        telemetry.track_task_start("main")
        main_start_time = time.time()
        try:
            version.start()
            game.start()
            success = Daily.start()
            telemetry.track_task_complete("main", success is not False, time.time() - main_start_time)
            if success is False:
                notif.flush_batch()
                if cfg.after_finish == "Exit":
                    game.get_game_controller().stop_game()
                return False
            game.stop(True)
        except CloudGameZeroDurationError as e:
            telemetry.track_task_complete("main", False, time.time() - main_start_time)
            if not game.wait_after_cloud_zero_duration(e):
                raise
        except Exception:
            telemetry.track_task_complete("main", False, time.time() - main_start_time)
            notif.flush_batch()
            raise


def run_sub_task(action, task_override=None):
    visible_cloud_tasks = {"fight", "universe"}
    success = True
    backend = get_control_backend(cfg)
    if action in ("currencywars", "currencywarsloop"):
        game.start(headless=None, screen_ready=CurrencyWars.game_screen_ready)
    elif action not in ("currencywarstemp", "divergenttemp"):
        game.start(headless=False if action in visible_cloud_tasks else None)
    else:
        task_power_request.acquire(log)
        if backend == "cloud":
            if not cloud_game.start_game_process():
                raise ConnectionError("启动或连接浏览器失败")
        elif backend == "playcover":
            if not playcover_game.start_game_process():
                raise RuntimeError("启动游戏失败")
            if not playcover_game.wait_ready(360):
                raise TimeoutError("等待 PlayCover 游戏窗口或 MaaTools 就绪超时")
        game.switch_to_game()

    def _run_loop_task_with_telemetry(task_id, task_fn):
        while True:
            telemetry.track_task_start(task_id)
            task_start_time = time.time()
            try:
                ok = bool(task_fn())
                telemetry.track_task_complete(task_id, ok, time.time() - task_start_time)
            except Exception:
                telemetry.track_task_complete(task_id, False, time.time() - task_start_time)
                raise

    def currencywars(mode=None):
        war = CurrencyWars()
        if mode == "loop":
            _run_loop_task_with_telemetry("currencywarsloop", war.start)
        else:
            return war.start(resume=mode == "temp")

    def divergent(mode=None):
        universe = DivergentUniverse()
        if mode == "loop":
            _run_loop_task_with_telemetry("divergentloop", universe.start)
        elif mode == "temp":
            return universe.loop()
        else:
            return universe.start()

    sub_tasks = {
        "routine": Daily.routine,
        "daily": lambda: (Daily.run(), reward.start()),
        "power": Power.run,
        "currencywars": lambda: currencywars(),
        "currencywarsloop": lambda: currencywars("loop"),
        "currencywarstemp": lambda: currencywars("temp"),
        "divergent": lambda: divergent(),
        "divergentloop": lambda: divergent("loop"),
        "divergenttemp": lambda: divergent("temp"),
        "fight": Fight.start,
        "screen_test": screen_test.run,
        "universe": lambda: Universe.start(category="universe"),
        "forgottenhall": lambda: challenge.start("memoryofchaos"),
        "purefiction": lambda: challenge.start("purefiction"),
        "apocalyptic": lambda: challenge.start("apocalyptic"),
        "redemption": Redemption.start,
    }
    task = task_override or sub_tasks.get(action)
    if task:
        if action in ("currencywarsloop", "divergentloop"):
            task()
        else:
            telemetry.track_task_start(action)
            task_start_time = time.time()
            try:
                result = task()
                success = result is not False
                telemetry.track_task_complete(action, success, time.time() - task_start_time)
            except Exception:
                telemetry.track_task_complete(action, False, time.time() - task_start_time)
                raise
    if action != "screen_test":
        if success:
            game.stop(False)
        elif cfg.after_finish == "Exit":
            game.get_game_controller().stop_game()
    return success


def run_sub_task_gui(action):
    gui_tasks = {
        "universe_gui": Universe.gui,
        "fight_gui": Fight.gui,
    }
    task = gui_tasks.get(action)
    if task and not task():
        pause_always()
    sys.exit(0)


def run_sub_task_update(action):
    update_tasks = {
        "universe_update": Universe.update,
        "fight_update": Fight.update,
        "mobileui_update": Genshin_StarRail_fps_unlocker.update,
    }
    task = update_tasks.get(action)
    if task:
        task()
    pause_always()
    sys.exit(0)


def run_notify_action():
    notif.notify(content=cfg.notify_template["TestMessage"], image="./assets/app/images/March7th.jpg", level=NotificationLevel.ALL)
    pause_always()
    sys.exit(0)


def run_workflow_action(workflow_name: str, workflow_step_path=None):
    try:
        workflow = load_workflow_execution_payload(workflow_name, workflow_step_path)
    except ValueError:
        step_hint = f"（步骤路径：{workflow_step_path}）" if workflow_step_path else ""
        log.error(f"运行自定义流程失败: 未找到流程 '{workflow_name}'{step_hint}。{describe_available_workflows()}")
        sys.exit(1)
    if not game.ensure_game_ready():
        sys.exit(1)
    runner = WorkflowRunner(
        log_callback=lambda message: print(message, flush=True),
        mirror_to_project_log=False,
    )
    return runner.run(workflow)


def main(action=None, no_run_immediately=False, workflow_name=None, workflow_step_path=None):
    task_id = "workflow" if workflow_name else action or "main"
    if not task_is_supported(task_id, cfg):
        title = workflow_name or tr((AVAILABLE_TASKS | CLI_ONLY_TASKS).get(task_id, task_id))
        message = f"{tr(UNSUPPORTED_TASK)}（{title}）"
        run_session.note(status="blocked", reason="unsupported_backend", error=message)
        log.warning(message)
        return False

    try:
        recover_temporary_graphics(log)
        try:
            return _run_action(action, no_run_immediately, workflow_name, workflow_step_path)
        finally:
            restore_temporary_graphics(final=True)
    finally:
        task_power_request.release(log)


def _run_action(action=None, no_run_immediately=False, workflow_name=None, workflow_step_path=None):
    first_run()
    pause_ctl.start()
    backend = get_control_backend(cfg)
    telemetry.track_startup(backend)

    if workflow_name:
        return run_workflow_action(workflow_name, workflow_step_path)

    if (action or "main") in EXCLUSIVE_ACTIONS:
        ensure_exclusive_run()

    if action is None or action == "main":
        return run_main_actions(no_run_immediately)
    elif action in [
        "routine", "daily", "power",
        "currencywars", "currencywarsloop", "currencywarstemp",
        "divergent", "divergentloop", "divergenttemp",
        "fight", "universe", "forgottenhall", "purefiction", "apocalyptic",
        "redemption", "screen_test",
    ]:
        return run_sub_task(action)
    elif action in ["universe_gui", "fight_gui"]:
        run_sub_task_gui(action)
    elif action in ["universe_update", "fight_update", "mobileui_update"]:
        run_sub_task_update(action)
    elif action == "game":
        game.start(optimize_graphics=False)
    elif action == "app_update":
        app_update_task.start()
    elif action == "game_update":
        game.update_via_launcher()
    elif action == "game_pre_download":
        game.pre_download_via_launcher()
    elif action == "notify":
        run_notify_action()
    else:
        log.error(f"未知任务: {action}")
        pause_on_error()
        sys.exit(1)


def release_input(close=False):
    try:
        if close:
            auto.close_input()
        elif auto.input_handler is not None:
            auto.input_handler.release_all()
    except Exception as e:
        log.warning(f"输入清理失败: {e}")


def exit_handler():
    release_input(close=True)
    try:
        pause_ctl.stop()
    except Exception as e:
        log.warning(f"输入清理失败: {e}")
    telemetry.shutdown()
    ocr.exit_ocr()
    try:
        auto.shutdown_debug()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        try:
            atexit.register(exit_handler)
            args.no_run_immediately = args.no_run_immediately or cfg.get_value("no_run_immediately", False)
            if args.workflow_name:
                result = main(
                    no_run_immediately=args.no_run_immediately,
                    workflow_name=args.workflow_name,
                    workflow_step_path=args.workflow_step_path,
                )
            elif args.task:
                result = main(action=args.task, no_run_immediately=args.no_run_immediately)
            else:
                result = main(no_run_immediately=args.no_run_immediately)
            if result is False:
                sys.exit(1)
        except KeyboardInterrupt:
            release_input(close=True)
            run_session.note(status=STATUS_INTERRUPTED, error="手动强制停止")
            log.error("发生错误: 手动强制停止")
            pause_on_error()
            sys.exit(1)
        except RunStopRequested:
            release_input(close=True)
            try:
                pause_ctl.stop()
            except Exception as e:
                log.warning(f"输入清理失败: {e}")
            run_session.note(status=STATUS_STOPPED)
            log.warning("任务已按停止指令结束")
            sys.exit(EXIT_STOPPED)
        except (ProfileAssetNotFoundError, TouchProfileInputError, CGHelperError) as e:
            release_input()
            run_session.note(error=str(e))
            log.error(str(e))
            sys.exit(EXIT_FAILED)
        except Exception as e:
            release_input()
            telemetry.track_error(type(e).__name__, str(e))
            log.error(cfg.notify_template["ErrorOccurred"].format(error=e))
            screenshot_path = save_error_screenshot(log)
            run_session.note(error=str(e), screenshot=screenshot_path)
            notif.flush_batch()
            notify_kwargs = {
                "content": cfg.notify_template["ErrorOccurred"].format(error=e),
                "level": NotificationLevel.ERROR,
            }
            if screenshot_path:
                notify_kwargs["image"] = screenshot_path
            notif.notify(**notify_kwargs)
            pause_on_error()
            sys.exit(1)
    except SystemExit as e:
        run_session.finish(exit_code_of(e))
        raise
    except BaseException as e:
        run_session.note(error=f"{type(e).__name__}: {e}")
        run_session.finish(EXIT_FAILED)
        raise
    else:
        run_session.finish(EXIT_OK)
