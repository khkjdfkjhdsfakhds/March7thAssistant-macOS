from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

from app.tools.game_starter import GameLaunchThread, GameStartStatus
from module.game.cg_client import CN_BUNDLE_ID
from module.game.playcover import PlayCoverGameController
from module.telemetry.events import EventName
from module.telemetry.telemetry import Telemetry
from tasks.game.starrailcontroller import StarRailController
from utils.screenshot_util import save_error_screenshot


class _DictConfig:
    def __init__(self, **values):
        self.script_path = str(Path.cwd())
        self.values = dict(values)

    def get_value(self, key, default=None):
        return self.values.get(key, default)


class _DummyLogger:
    def debug(self, *_args, **_kwargs):
        pass

    info = debug
    warning = debug
    error = debug


def test_telemetry_track_startup_accepts_zero_and_one_arg(monkeypatch):
    tel = Telemetry()
    recorded = []
    monkeypatch.setattr(tel, "track", lambda name, props=None: recorded.append((name, props)))

    tel.track_startup()
    tel.track_startup("playcover")

    assert len(recorded) == 2
    assert recorded[0][0] == EventName.APP_STARTUP
    assert recorded[1][0] == EventName.APP_STARTUP


def test_playcover_start_game_process_flags(monkeypatch, tmp_path):
    fake_app = tmp_path / f"{CN_BUNDLE_ID}.app"
    fake_app.mkdir()

    cfg = _DictConfig(playcover_transport="auto", playcover_bundle_id=CN_BUNDLE_ID)
    monkeypatch.setattr(
        "module.game.playcover.resolve_playcover_bundle",
        lambda preferred, search_dirs=None: (CN_BUNDLE_ID, fake_app),
    )
    controller = PlayCoverGameController(cfg=cfg, logger=_DummyLogger())
    monkeypatch.setattr(controller, "is_game_running", Mock(return_value=False))

    calls = []

    def fake_run(cmd, capture_output=True, text=True):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("module.game.playcover.subprocess.run", fake_run)

    # auto / maatools default to background (-g)
    assert controller.start_game_process() is True
    assert calls[-1][:2] == ["open", "-g"]

    cfg.values["playcover_transport"] = "maatools"
    assert controller.start_game_process() is True
    assert calls[-1][:2] == ["open", "-g"]

    # cg defaults to foreground (-a)
    cfg.values["playcover_transport"] = "cg"
    assert controller.start_game_process() is True
    assert calls[-1][:2] == ["open", "-a"]

    # explicit background=False always forces foreground (-a) even in auto/maatools
    cfg.values["playcover_transport"] = "auto"
    assert controller.start_game_process(background=False) is True
    assert calls[-1][:2] == ["open", "-a"]


def test_game_launch_thread_uses_foreground_for_playcover():
    cfg = _DictConfig()
    cfg.cloud_game_enable = False
    cfg.playcover_enable = True

    game = Mock()
    game.start_game_process = Mock(return_value=True)

    emitted = []
    thread = GameLaunchThread(game, cfg)
    thread.finished_signal.connect(emitted.append)
    thread.run()

    game.start_game_process.assert_called_once_with(background=False)
    assert emitted == [GameStartStatus.SUCCESS]


def test_starrail_controller_no_nameerror_on_non_win32(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    cfg = _DictConfig()
    cfg.game_path = "/tmp/nonexistent/StarRail.exe"
    cfg.game_process_name = "StarRail"
    cfg.game_title_name = "崩坏：星穹铁道"
    controller = StarRailController(cfg=cfg, logger=_DummyLogger())
    assert controller.screen_resolution == (1920, 1080)
    # None of these should hit winreg / undefined win32 symbols on macOS
    controller.change_auto_battle(True)
    controller.change_resolution(1920, 1080)
    controller.restore_resolution()
    controller.change_auto_hdr("disable")
    controller.restore_auto_hdr()


def test_save_error_screenshot_skips_when_game_not_running(monkeypatch):
    import module.automation as auto_mod
    import module.config as cfg_mod
    import module.game as game_mod

    monkeypatch.setattr(cfg_mod.cfg, "cloud_game_enable", False, raising=False)
    fake_controller = Mock()
    fake_controller.is_game_running.return_value = False
    monkeypatch.setattr(game_mod, "get_game_controller", lambda: fake_controller)

    take_mock = Mock()
    monkeypatch.setattr(auto_mod.auto, "take_screenshot", take_mock)

    result = save_error_screenshot(_DummyLogger())
    assert result is None
    take_mock.assert_not_called()
