import ast
from io import StringIO
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
import pytest

from module.automation.background_input import GameWindowLost, InputInterrupted
from module.game.cg_client import CGHelperError
from tasks import game as game_mod
from tasks import reward
from tasks.activity import checkInactivity
from tasks.base import task_steps
from tasks.challenge import apocalyptic, memoryofchaos, purefiction
from tasks.daily import redemption
from tasks.reward import mail, quest, srpass
from utils import screenshot_util
from utils.runs import _TeeStream


def _make_button_image(rgb, size=(120, 40)):
    return Image.new("RGB", size, rgb)


class TestOptionalReward:
    def test_local_errors_are_logged_and_do_not_abort(self, monkeypatch):
        logger = Mock()
        monkeypatch.setattr(task_steps, "log", logger)

        with task_steps.optional_reward("邮件奖励"):
            raise RuntimeError("识别失败")

        logger.warning.assert_called_once()
        assert "邮件奖励待核对：识别失败" in logger.warning.call_args.args[0]

    @pytest.mark.parametrize("error_factory", [
        lambda: GameWindowLost("游戏窗口已关闭"),
        lambda: CGHelperError("helper_error", "pc_helper failed"),
        lambda: InputInterrupted("输入已中断"),
        lambda: task_steps.GameRecoveryError("无法恢复主界面"),
    ])
    def test_fatal_errors_propagate(self, error_factory):
        err = error_factory()
        with pytest.raises(type(err)) as raised:
            with task_steps.optional_reward("邮件奖励"):
                raise err
        assert raised.value is err

    def test_frame_only_fatal_error_is_downgraded_to_warning(self, monkeypatch):
        logger = Mock()
        monkeypatch.setattr(task_steps, "log", logger)
        err = GameWindowLost("单帧超时")
        err.frame_only = True

        with task_steps.optional_reward("邮件奖励"):
            raise err

        logger.warning.assert_called_once()
        assert "邮件奖励待核对：单帧超时" in logger.warning.call_args.args[0]

    def test_closed_stderr_does_not_replace_optional_reward_handling(self, monkeypatch):
        original = StringIO()
        original.close()
        tee = _TeeStream(original, StringIO())
        logger = logging.Logger("reward-cleanup-test")
        logger.addHandler(logging.StreamHandler(tee))

        with monkeypatch.context() as patch:
            patch.setattr(sys, "stderr", tee)
            patch.setattr(logging, "raiseExceptions", True)
            patch.setattr(task_steps, "log", logger)
            with task_steps.optional_reward("短信奖励"):
                raise RuntimeError("关闭弹窗时截图失败")


class TestRewardManagerRecovery:
    def _build_manager(self, monkeypatch):
        fake_cfg = SimpleNamespace(
            reward_assist_enable=True,
            reward_mail_enable=True,
            reward_dispatch_enable=True,
            reward_quest_enable=True,
            reward_srpass_enable=True,
            reward_achievement_enable=True,
            reward_message_enable=True,
        )
        monkeypatch.setattr(reward, "cfg", fake_cfg)
        monkeypatch.setattr(reward, "screen", Mock())
        monkeypatch.setattr(reward, "auto", Mock(find_element=Mock(return_value=((10, 10), (20, 20)))))
        return reward.RewardManager()

    def test_continues_collecting_remaining_rewards_after_local_failure(self, monkeypatch):
        manager = self._build_manager(monkeypatch)
        called = []

        def fake_start(name, should_fail=False):
            def _run():
                called.append(name)
                if should_fail:
                    raise RuntimeError(f"{name} 异常")
                return True

            return _run

        for key, instance in manager.reward_instances.items():
            monkeypatch.setattr(instance, "start", fake_start(key, should_fail=(key == "mail")))

        assert manager.check_and_collect_rewards() is True
        assert "mail" in called
        assert "dispatch" in called
        assert "achievement" in called

    def test_stops_immediately_on_fatal_error(self, monkeypatch):
        manager = self._build_manager(monkeypatch)
        called = []
        for key, instance in manager.reward_instances.items():
            if key == "mail":
                monkeypatch.setattr(instance, "start", Mock(side_effect=GameWindowLost("窗口已关闭")))
            else:
                monkeypatch.setattr(instance, "start", lambda k=key: called.append(k) or True)

        with pytest.raises(GameWindowLost, match="窗口已关闭"):
            manager.check_and_collect_rewards()

        assert "achievement" not in called

    def test_specific_reward_handles_local_failure_and_propagates_fatal(self, monkeypatch):
        manager = self._build_manager(monkeypatch)
        monkeypatch.setattr(manager.mail, "start", Mock(side_effect=RuntimeError("临时识别错误")))
        assert manager.check_and_collect_specific_reward("mail") is False

        monkeypatch.setattr(manager.mail, "start", Mock(side_effect=CGHelperError("helper_error", "Helper 崩溃")))
        with pytest.raises(CGHelperError):
            manager.check_and_collect_specific_reward("mail")


class TestMailGrayButtonFix:
    def _setup_mail(self, monkeypatch, image, button=((10, 10), (110, 40))):
        fake_auto = Mock(
            screenshot=image,
            screenshot_pos=(0, 0, image.width, image.height),
            screenshot_scale_factor=1,
            find_element=Mock(return_value=button),
            click_element_with_pos=Mock(return_value=True),
            click_element=Mock(return_value=True),
        )
        monkeypatch.setattr(mail, "auto", fake_auto)
        monkeypatch.setattr(mail, "time", SimpleNamespace(sleep=Mock()))
        monkeypatch.setattr(mail.Base, "send_notification_with_screenshot", Mock())
        return mail.Mail("邮件", True, "mail"), fake_auto

    def test_gray_button_on_bright_background_returns_false_without_clicking(self, monkeypatch):
        # 构造底色很亮、只占 20% 浅灰字的置灰按钮图（旧版 muted_background >= 0.20 会漏判）
        img = _make_button_image((250, 250, 250), size=(140, 60))
        for x in range(10, 40):
            for y in range(10, 35):
                img.putpixel((x, y), (170, 170, 170))
        instance, fake_auto = self._setup_mail(monkeypatch, img)

        assert instance.run() is False
        fake_auto.click_element_with_pos.assert_not_called()

    def test_active_golden_button_clicks_and_returns_true(self, monkeypatch):
        img = _make_button_image((225, 185, 95), size=(140, 60))
        instance, fake_auto = self._setup_mail(monkeypatch, img)

        assert instance.run() is True
        fake_auto.click_element_with_pos.assert_called_once_with(((10, 10), (110, 40)))
        mail.Base.send_notification_with_screenshot.assert_called_once()

    def test_unconfirmed_button_color_raises_runtime_error(self, monkeypatch):
        img = _make_button_image((40, 80, 140), size=(140, 60))
        instance, fake_auto = self._setup_mail(monkeypatch, img)

        with pytest.raises(RuntimeError, match="未确认邮箱的全部领取按钮状态"):
            instance.run()
        fake_auto.click_element_with_pos.assert_not_called()

    def test_no_button_with_empty_mail_text_returns_false(self, monkeypatch):
        img = _make_button_image((0, 0, 0), size=(140, 60))
        instance, fake_auto = self._setup_mail(monkeypatch, img, button=None)
        fake_auto.find_element.side_effect = [None, None, None, True]

        assert instance.run() is False


class TestTaskOptionalRewardIntegration:
    def test_checkin_activity_tolerates_local_error(self, monkeypatch):
        act = checkInactivity.CheckInActivity("巡星之礼", True)
        monkeypatch.setattr(checkInactivity.ActivityTemplate, "start", Mock(side_effect=RuntimeError("截图失败")))
        assert act.start() is True

        monkeypatch.setattr(checkInactivity.ActivityTemplate, "start", Mock(side_effect=GameWindowLost("窗口退出")))
        with pytest.raises(GameWindowLost):
            act.start()

    def test_srpass_continues_to_pass1_when_experience_claim_fails(self, monkeypatch):
        fake_auto = Mock(
            click_element=Mock(side_effect=[RuntimeError("识别失败"), True]),
            find_element=Mock(return_value=False),
        )
        fake_screen = Mock()
        monkeypatch.setattr(srpass, "auto", fake_auto)
        monkeypatch.setattr(srpass, "screen", fake_screen)

        srpass.SRPass("无名勋礼", True, "pass2").run()
        fake_screen.change_to.assert_called_once_with("pass1")

    def test_quest_notifies_under_optional_reward_and_records_completion(self, monkeypatch):
        fake_auto = Mock(
            click_element=Mock(side_effect=[False, RuntimeError("礼盒识别异常")]),
            find_element=Mock(return_value=True),
        )
        fake_cfg = SimpleNamespace(
            set_value=Mock(),
            notify_template={"DailyPracticeCompleted": "完成", "DailyPracticeNotCompleted": "未完成"},
        )
        monkeypatch.setattr(quest, "auto", fake_auto)
        monkeypatch.setattr(quest, "cfg", fake_cfg)
        monkeypatch.setattr(quest.Base, "send_notification_with_screenshot", Mock())

        quest.Quest("每日实训", True, "guide2").run()
        fake_cfg.set_value.assert_called_once_with("daily_tasks", {})

    @pytest.mark.parametrize("mod,cls_name", [
        (apocalyptic, "Apocalyptic"),
        (memoryofchaos, "MemoryOfChaos"),
        (purefiction, "PureFiction"),
    ])
    def test_challenge_collect_rewards_tolerates_local_error(self, monkeypatch, mod, cls_name):
        obj = getattr(mod, cls_name)([], [])
        obj.max_level = 4
        monkeypatch.setattr(obj, "save_timestamp_into_config", Mock())
        monkeypatch.setattr(mod, "time", SimpleNamespace(sleep=Mock()))
        monkeypatch.setattr(mod, "screen", SimpleNamespace(wait_for_screen_change=Mock(side_effect=RuntimeError("等待超时"))))

        obj.collect_rewards()

        monkeypatch.setattr(mod, "screen", SimpleNamespace(wait_for_screen_change=Mock(side_effect=InputInterrupted("停止"))))
        with pytest.raises(InputInterrupted):
            obj.collect_rewards()

    def test_redemption_start_tolerates_mail_or_notify_error(self, monkeypatch):
        fake_cfg = SimpleNamespace(already_used_codes=[], set_value=Mock(), redemption_code=["CODE1"])
        fake_auto = Mock(
            click_element=Mock(return_value=True),
            find_element=Mock(return_value=True),
            press_key=Mock(),
        )
        monkeypatch.setattr(redemption, "cfg", fake_cfg)
        monkeypatch.setattr(redemption, "auto", fake_auto)
        monkeypatch.setattr(redemption, "screen", Mock())
        monkeypatch.setattr(redemption, "get_game_controller", lambda: Mock())
        monkeypatch.setattr(redemption, "time", SimpleNamespace(sleep=Mock()))
        monkeypatch.setattr(redemption.notif, "notify", Mock(side_effect=RuntimeError("通知失败")))
        monkeypatch.setattr(redemption.reward, "start_specific", Mock(side_effect=RuntimeError("领奖失败")))

        assert redemption.Redemption.start(codes=["CODE1"], send_notification=True) is True


class TestErrorScreenshotAndFullRunCompletion:
    def test_save_error_screenshot_propagates_only_non_frame_only_fatal_errors(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("module.config.cfg", SimpleNamespace(cloud_game_enable=False))
        monkeypatch.setattr("module.game.get_game_controller", lambda: SimpleNamespace(is_game_running=lambda: True))
        monkeypatch.setattr("module.automation.auto", SimpleNamespace(
            input_handler=SimpleNamespace(is_background=False),
            take_screenshot=Mock(side_effect=GameWindowLost("窗口丢失")),
            screenshot=None,
        ))
        logger = Mock()

        with pytest.raises(GameWindowLost):
            screenshot_util.save_error_screenshot(logger, propagate_errors=task_steps.FATAL_GAME_ERRORS)

        frame_err = GameWindowLost("单帧超时")
        frame_err.frame_only = True
        monkeypatch.setattr("module.automation.auto", SimpleNamespace(
            input_handler=SimpleNamespace(is_background=False),
            take_screenshot=Mock(side_effect=frame_err),
            screenshot=None,
        ))
        assert screenshot_util.save_error_screenshot(logger, propagate_errors=task_steps.FATAL_GAME_ERRORS) is None

    def test_game_stop_respects_success_flag(self, monkeypatch):
        controller = Mock()
        monkeypatch.setattr(game_mod, "pause_ctl", Mock())
        monkeypatch.setattr(game_mod, "ocr", Mock())
        monkeypatch.setattr(game_mod, "get_game_controller", lambda *_args: controller)
        pause_success = Mock()
        monkeypatch.setattr(game_mod, "pause_on_success", pause_success)
        monkeypatch.setattr(game_mod, "cfg", SimpleNamespace(play_audio=False, after_finish="Shutdown"))

        with pytest.raises(SystemExit) as exc:
            game_mod.stop(False, success=False)
        assert exc.value.code == 1
        controller.shutdown.assert_called_once_with("Shutdown")
        pause_success.assert_not_called()

        controller.reset_mock()
        monkeypatch.setattr(game_mod, "cfg", SimpleNamespace(play_audio=False, after_finish="None"))
        with pytest.raises(SystemExit) as exc_ok:
            game_mod.stop(False, success=True)
        assert exc_ok.value.code == 0
        pause_success.assert_called_once_with()

    @pytest.mark.parametrize("after_finish,gui_started,expect_stop", [
        ("None", False, True),
        ("Shutdown", False, True),
        ("Loop", True, False),
    ])
    def test_run_main_actions_dispatches_completion_on_ordinary_failure(self, after_finish, gui_started, expect_stop):
        main_path = Path(__file__).resolve().parents[2] / "main.py"
        tree = ast.parse(main_path.read_text(encoding="utf-8"), str(main_path))
        func_node = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "run_main_actions"
        )
        mod_ast = ast.Module(body=[func_node], type_ignores=[])
        ns = {
            "cfg": SimpleNamespace(notify_merge=False, after_finish=after_finish),
            "game": Mock(),
            "notif": Mock(),
            "telemetry": Mock(),
            "version": Mock(),
            "Daily": SimpleNamespace(currency_wars_due=lambda: False, start=Mock(return_value=False)),
            "CurrencyWars": Mock(),
            "is_gui_started": lambda: gui_started,
            "log": Mock(),
            "time": SimpleNamespace(time=lambda: 0.0),
            "CloudGameZeroDurationError": type("CloudGameZeroDurationError", (Exception,), {}),
            "ProfileAssetNotFoundError": type("ProfileAssetNotFoundError", (Exception,), {}),
            "TouchProfileInputError": type("TouchProfileInputError", (Exception,), {}),
        }
        exec(compile(mod_ast, str(main_path), "exec"), ns)

        assert ns["run_main_actions"](no_run_immediately=False) is False
        ns["notif"].flush_batch.assert_called_once_with()
        if expect_stop:
            ns["game"].stop.assert_called_once_with(False, success=False)
        else:
            ns["game"].stop.assert_not_called()
            ns["game"].after_finish_is_loop.assert_not_called()
