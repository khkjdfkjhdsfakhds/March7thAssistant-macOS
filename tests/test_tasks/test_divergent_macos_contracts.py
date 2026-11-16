from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from module import mobile
from tasks.daily import daily
from tasks.weekly import divergent_universe, universe


def _mobile_cfg(enabled: bool):
    values = {"playcover_enable": enabled, "cloud_game_enable": False}
    return SimpleNamespace(get_value=lambda key, default=False: values.get(key, default))


@pytest.mark.parametrize(
    "pc_crop,expected_px",
    [
        ((57 / 1920, 15 / 1080, 260 / 1920, 27 / 1080), (60, 10, 330, 50)),
        ((520 / 1920, 118 / 1080, 880 / 1920, 65 / 1080), (460, 100, 1000, 110)),
        ((1540 / 1920, 934 / 1080, 345 / 1920, 75 / 1080), (1430, 925, 450, 95)),
        ((517 / 1920, 242 / 1080, 409 / 1920, 610 / 1080), (492, 230, 432, 634)),
        ((757 / 1920, 242 / 1080, 410 / 1920, 610 / 1080), (745, 230, 433, 634)),
        ((6 / 1920, 8 / 1080, 578 / 1920, 168 / 1080), (6, 100, 740, 90)),
    ],
)
def test_divergent_mobile_crop_mappings_exist(monkeypatch, pc_crop, expected_px):
    mobile.profile.cache_clear()
    monkeypatch.setattr(mobile, "cfg", _mobile_cfg(True))
    mapped = mobile.map_crop(pc_crop)
    expected = (
        expected_px[0] / 1920,
        expected_px[1] / 1080,
        expected_px[2] / 1920,
        expected_px[3] / 1080,
    )
    assert mapped == pytest.approx(expected)


def test_process_save_management_preserves_mobile_layout_slot_ys(monkeypatch):
    from PIL import Image

    mobile.profile.cache_clear()
    monkeypatch.setattr(mobile, "cfg", _mobile_cfg(True))

    clicked_crops = []
    fake_auto = Mock()

    def fake_click_element(target, find_type="text", *args, **kwargs):
        if find_type == "crop":
            clicked_crops.append(target)
        return True

    def fake_take_screenshot():
        img = Image.new("RGB", (1920, 1080), (0, 0, 0))
        active_y = (265, 427, 590, 753)[len(clicked_crops) - 1]
        img.putpixel((100, active_y), (255, 255, 255))
        fake_auto.screenshot = img

    def fake_find_element(target, find_type="text", *args, **kwargs):
        if target == "确认":
            return False
        return len(clicked_crops) == 2

    fake_auto.click_element.side_effect = fake_click_element
    fake_auto.take_screenshot.side_effect = fake_take_screenshot
    fake_auto.find_element.side_effect = fake_find_element

    monkeypatch.setattr(divergent_universe, "auto", fake_auto)
    monkeypatch.setattr(divergent_universe, "time", SimpleNamespace(sleep=Mock()))

    du = divergent_universe.DivergentUniverse()
    assert du.process_save_management(save_current_run=True) is True
    assert clicked_crops == [
        (150 / 1920, (265 - 20) / 1080, 70 / 1920, 40 / 1080),
        (150 / 1920, (427 - 20) / 1080, 70 / 1920, 40 / 1080),
    ]


def test_divergent_save_slot_ys_falls_back_on_desktop(monkeypatch):
    mobile.profile.cache_clear()
    monkeypatch.setattr(mobile, "cfg", _mobile_cfg(False))
    assert tuple(mobile.layout("divergent_save_slot_ys", (240, 372, 503, 634))) == (240, 372, 503, 634)


@pytest.mark.parametrize(
    "universe_bonus,divergent_bonus,expect_ornament",
    [
        (True, False, False),
        (False, True, True),
    ],
)
def test_divergent_bonus_uses_weekly_divergent_bonus_enable_only(
    monkeypatch, universe_bonus, divergent_bonus, expect_ornament
):
    fake_cfg = SimpleNamespace(
        universe_bonus_enable=universe_bonus,
        weekly_divergent_bonus_enable=divergent_bonus,
        weekly_divergent_timestamp=0,
        refresh_hour=4,
        divergent_type="cycle",
    )
    monkeypatch.setattr(divergent_universe, "cfg", fake_cfg)
    monkeypatch.setattr(divergent_universe.Date, "is_next_mon_x_am", lambda *a: False)
    monkeypatch.setattr(divergent_universe.Base, "send_notification_with_screenshot", Mock())

    du = divergent_universe.DivergentUniverse()
    monkeypatch.setattr(du, "run", lambda universe_type=None: True)
    monkeypatch.setattr(du, "get_reward", lambda: True)
    process_ornament = Mock()
    monkeypatch.setattr(du, "process_ornament", process_ornament)

    assert du.start() is True
    assert process_ornament.called is expect_ornament


def test_universe_module_still_keeps_universe_bonus_enable():
    assert universe.Universe.get_reward.__name__ == "get_reward"
    assert "universe_bonus_enable" in universe.Universe.get_reward.__code__.co_names
    assert "weekly_divergent_bonus_enable" not in universe.Universe.get_reward.__code__.co_names


def test_daily_scheduled_divergent_passes_cfg_divergent_type(monkeypatch):
    recorded = []
    counts = iter([0, 1])
    monkeypatch.setattr(
        daily,
        "cfg",
        SimpleNamespace(
            universe_count=1,
            universe_frequency="daily",
            divergent_type="normal",
            save_timestamp=Mock(),
        ),
    )
    monkeypatch.setattr(
        daily.DivergentUniverse,
        "get_recorded_run_count",
        staticmethod(lambda cycle: next(counts)),
    )
    fake_divergent = SimpleNamespace(
        start=lambda **kwargs: recorded.append(kwargs) or True
    )
    daily.Daily._run_scheduled_divergent_universe(fake_divergent)
    assert recorded == [{"universe_type": "normal"}]


def test_guide5_mobile_template_scales_override_stale_learned_scales(monkeypatch):
    mobile.profile.cache_clear()
    monkeypatch.setattr(mobile, "cfg", _mobile_cfg(True))
    monkeypatch.setattr(
        mobile,
        "_learned_scales",
        {
            "./assets/images/screen/guide/guide5.png": 1.05,
            "./assets/images/screen/guide/enter_guide2.png": 1.05,
        },
    )

    assert mobile.template_scales("./assets/images/screen/guide/guide5.png") == (1.15,)
    assert mobile.template_scales("./assets/images/screen/guide/enter_guide2.png") == (1.15,)

    monkeypatch.setattr(mobile, "_learned_scales", None)
    assert mobile._load_learned_scales()["./assets/images/screen/guide/guide5.png"] == 1.15


def test_divergent_enemy_mobile_threshold_override(monkeypatch):
    enemy_target = "./assets/images/screen/divergent_universe/enemy.png"
    mobile.profile.cache_clear()

    monkeypatch.setattr(mobile, "cfg", _mobile_cfg(True))
    assert mobile.template_threshold(enemy_target, 0.9, False, 1.0) == 0.75

    monkeypatch.setattr(mobile, "cfg", _mobile_cfg(False))
    assert mobile.template_threshold(enemy_target, 0.9, False, 1.0) == 0.9


