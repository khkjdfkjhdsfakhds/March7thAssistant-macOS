"""MaaTools 截图超时重连重试、PlayCover auto 回退及报错文案单元测试。"""

import struct
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from module.game.cg_client import CGHelperError
from module.game.maatools_client import MaaToolsClient
from module.game.playcover import PlayCoverGameController


def test_maatools_default_timeout_is_10s():
    client = MaaToolsClient()
    assert client.timeout == 10


def test_maatools_screenshot_silent_reconnect_and_retry_succeeds(monkeypatch):
    import module.game.maatools_client as mt_mod

    mock_log = Mock()
    monkeypatch.setattr(mt_mod, "log", mock_log)

    client = MaaToolsClient()
    client._sock = Mock()
    frame_bytes = bytearray([10, 20, 30] * 4)  # 2x2 BGR
    header = bytearray(struct.pack(">III", 2, 2, len(frame_bytes)))

    connect_calls = 0

    def fake_connect_unlocked():
        nonlocal connect_calls
        connect_calls += 1
        client._sock = Mock()
        return True

    close_calls = 0

    def fake_close_unlocked():
        nonlocal close_calls
        close_calls += 1
        client._sock = None

    monkeypatch.setattr(client, "_connect_unlocked", fake_connect_unlocked)
    monkeypatch.setattr(client, "_close_unlocked", fake_close_unlocked)
    monkeypatch.setattr(client, "_send", Mock())
    monkeypatch.setattr(
        client,
        "_recv",
        Mock(side_effect=[TimeoutError("timed out"), header, frame_bytes]),
    )

    img = client.screenshot()
    assert img is not None
    assert img.shape == (2, 2, 3)
    assert close_calls == 1
    assert connect_calls == 2
    mock_log.error.assert_not_called()
    mock_log.debug.assert_called_once()


def test_maatools_screenshot_consecutive_failure_logs_error_and_returns_none(monkeypatch):
    import module.game.maatools_client as mt_mod

    mock_log = Mock()
    monkeypatch.setattr(mt_mod, "log", mock_log)

    client = MaaToolsClient()
    monkeypatch.setattr(client, "_connect_unlocked", lambda: True)
    monkeypatch.setattr(client, "_close_unlocked", Mock())
    monkeypatch.setattr(client, "_send", Mock())
    monkeypatch.setattr(
        client,
        "_recv",
        Mock(side_effect=[TimeoutError("timed out"), TimeoutError("timed out again")]),
    )

    assert client.screenshot() is None
    mock_log.error.assert_called_once()
    assert "timed out again" in mock_log.error.call_args[0][0]


def test_playcover_auto_falls_back_to_cg_when_maatools_returns_none(monkeypatch):
    cfg = SimpleNamespace(
        script_path=".",
        get_value=lambda key, default=None: {
            "playcover_transport": "auto",
            "playcover_bundle_id": "com.miHoYo.hkrpg",
            "playcover_restore_focus": True,
            "playcover_maatools_host": "127.0.0.1",
            "playcover_maatools_port": 1717,
        }.get(key, default),
    )
    ctrl = PlayCoverGameController(cfg=cfg, logger=Mock())
    monkeypatch.setattr(ctrl, "active_transport", lambda: "maatools")
    monkeypatch.setattr(ctrl.client, "screenshot", lambda: None)
    expected = np.zeros((1080, 1920, 3), dtype=np.uint8)
    monkeypatch.setattr(ctrl.cg_client, "capture_bgr", lambda: expected)

    img = ctrl.screenshot_bgr()
    assert img is expected


def test_playcover_maatools_only_does_not_fallback_to_cg(monkeypatch):
    cfg = SimpleNamespace(
        script_path=".",
        get_value=lambda key, default=None: {
            "playcover_transport": "maatools",
            "playcover_bundle_id": "com.miHoYo.hkrpg",
            "playcover_restore_focus": True,
            "playcover_maatools_host": "127.0.0.1",
            "playcover_maatools_port": 1717,
        }.get(key, default),
    )
    ctrl = PlayCoverGameController(cfg=cfg, logger=Mock())
    monkeypatch.setattr(ctrl, "active_transport", lambda: "maatools")
    monkeypatch.setattr(ctrl.client, "screenshot", lambda: None)
    cg_mock = Mock(side_effect=CGHelperError("should_not_run", "boom"))
    monkeypatch.setattr(ctrl.cg_client, "capture_bgr", cg_mock)

    assert ctrl.screenshot_bgr() is None
    cg_mock.assert_not_called()


@pytest.mark.parametrize(
    ("playcover_enable", "expected_msg"),
    [
        (True, "截图失败：未能获取到 PlayCover 游戏画面（连接超时或窗口未就绪）"),
        (False, "截图失败：没有找到游戏窗口"),
    ],
)
def test_automation_screenshot_error_message_by_platform(monkeypatch, playcover_enable, expected_msg):
    import module.automation.automation as auto_mod

    automation = object.__new__(auto_mod.Automation)
    automation.window_title = "test-game"
    automation.logger = Mock()
    monkeypatch.setattr(automation, "_is_debug_enabled", lambda: False)
    monkeypatch.setattr(
        auto_mod,
        "cfg",
        SimpleNamespace(playcover_enable=playcover_enable, cloud_game_enable=False),
    )
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(
        auto_mod,
        "time",
        SimpleNamespace(
            monotonic=lambda: clock.now,
            sleep=lambda s: setattr(clock, "now", clock.now + s),
        ),
    )
    monkeypatch.setattr(auto_mod.Screenshot, "take_screenshot", Mock(return_value=False))

    with auto_mod.screenshot_retry_timeout(1):
        with pytest.raises(RuntimeError, match="截图超时"):
            automation.take_screenshot()

    automation.logger.error.assert_called_with(expected_msg)
