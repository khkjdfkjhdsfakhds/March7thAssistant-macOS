# coding:utf-8
"""命令行/定时任务更新入口：托盘最小化状态应传递给更新器的回归测试。

GUI 处于托盘最小化状态时通过环境变量 MARCH7TH_START_MINIMIZED_TO_TRAY
告知任务子进程，更新完成后应保持最小化到托盘。
"""
from tasks.version import app_update


class TestStartMinimizedToTray:
    def test_env_one(self, monkeypatch):
        monkeypatch.setenv("MARCH7TH_START_MINIMIZED_TO_TRAY", "1")
        assert app_update.start_minimized_to_tray() is True

    def test_env_true(self, monkeypatch):
        monkeypatch.setenv("MARCH7TH_START_MINIMIZED_TO_TRAY", "true")
        assert app_update.start_minimized_to_tray() is True

    def test_env_true_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("MARCH7TH_START_MINIMIZED_TO_TRAY", "TRUE")
        assert app_update.start_minimized_to_tray() is True

    def test_env_zero(self, monkeypatch):
        monkeypatch.setenv("MARCH7TH_START_MINIMIZED_TO_TRAY", "0")
        assert app_update.start_minimized_to_tray() is False

    def test_env_missing(self, monkeypatch):
        monkeypatch.delenv("MARCH7TH_START_MINIMIZED_TO_TRAY", raising=False)
        assert app_update.start_minimized_to_tray() is False


class TestMacOSAppUpdate:
    def test_darwin_logs_release_page_without_launching_exe_updater(self, monkeypatch):
        from unittest.mock import Mock
        from module.update.version_check import UpdateInfo

        monkeypatch.setattr(app_update.sys, "platform", "darwin")
        monkeypatch.setattr(
            app_update, "check_for_update",
            Mock(return_value=UpdateInfo(
                source="GitHub",
                url="https://example.com/app.dmg",
                file_name="app.dmg",
                version="v2026.11.20",
                html_url="https://github.com/moesnow/March7thAssistant/releases/tag/v2026.11.20",
            )),
        )
        popen = Mock(side_effect=AssertionError("darwin must not spawn Windows updater"))
        monkeypatch.setattr(app_update.subprocess, "Popen", popen)
        exit_mock = Mock(side_effect=AssertionError("darwin must not sys.exit(0) after spawning updater"))
        monkeypatch.setattr(app_update.sys, "exit", exit_mock)

        messages = []
        monkeypatch.setattr(app_update.log, "info", messages.append)

        app_update.start()

        popen.assert_not_called()
        exit_mock.assert_not_called()
        assert any("https://github.com/moesnow/March7thAssistant/releases/tag/v2026.11.20" in m for m in messages)
