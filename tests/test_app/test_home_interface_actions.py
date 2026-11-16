from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import QUrl

from app import home_interface


def test_home_extra_homepage_actions_use_qdesktopservices(monkeypatch):
    opened = []
    monkeypatch.setattr(home_interface.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)

    home_interface.HomeInterface._get_extra_task_action("_open_universe_homepage")()
    home_interface.HomeInterface._get_extra_task_action("_open_fight_homepage")()

    assert opened == [
        "https://github.com/CHNZYX/Auto_Simulated_Universe",
        "https://github.com/linruowuyin/Fhoe-Rail",
    ]


def test_home_extra_dir_actions_open_existing_and_warn_when_missing(monkeypatch, tmp_path):
    universe_dir = tmp_path / "universe"
    universe_dir.mkdir()
    missing_fight_dir = tmp_path / "missing_fight"

    monkeypatch.setattr(
        home_interface,
        "cfg",
        SimpleNamespace(universe_path=str(universe_dir), fight_path=str(missing_fight_dir)),
    )
    opened = []
    warnings = []
    monkeypatch.setattr(home_interface, "open_path", lambda path: opened.append(path) or True)
    monkeypatch.setattr(home_interface, "log", SimpleNamespace(warning=lambda msg: warnings.append(msg)))

    home_interface.HomeInterface._get_extra_task_action("_open_universe_dir")()
    home_interface.HomeInterface._get_extra_task_action("_open_fight_dir")()

    assert opened == [str(universe_dir)]
    assert len(warnings) == 1
    assert "锄大地" in warnings[0]
