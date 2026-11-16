from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
import pytest

from tasks.base import list_drag


CROP = (0.1, 0.2, 0.3, 0.4)
START, END = (0.2, 0.7), (0.2, 0.3)


class ListScreen:
    def __init__(self, frames, completed=True):
        self.frames = deque(Image.new("RGB", (30, 40), color) for color in frames)
        self.screenshot = None
        self.crops = []
        self.completed = completed
        self.drags = 0

    def drag_mouse(self, *args):
        self.drags += 1
        self.screenshot = Image.new("RGB", (192, 108), "red")
        return self.completed

    def take_screenshot(self, crop):
        self.crops.append(crop)
        if len(self.frames) > 1:
            self.screenshot = self.frames.popleft()
        else:
            self.screenshot = self.frames[0]
        self.screenshot_pos = crop
        return self.screenshot, crop, 1


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(list_drag, "time", SimpleNamespace(sleep=Mock()))


def test_waits_through_inertia_and_restores_cropped_cache():
    auto = ListScreen(["black", "white", "black", "white", "white", "white"])
    assert list_drag.drag_list(auto, START, END, crop=CROP)
    assert len(auto.crops) == 6
    assert auto.screenshot.size == (30, 40)
    assert auto.screenshot.getpixel((0, 0)) == (255, 255, 255)
    assert auto.screenshot_pos == CROP
    assert auto.crops == [CROP] * 6
    assert list_drag.time.sleep.call_args_list[0].args == (1.0,)


def test_fast_list_pause_and_polling_preserve_stability_checks():
    auto = ListScreen(["black"])
    auto.drag_mouse = Mock(wraps=auto.drag_mouse)
    assert list_drag.drag_list(auto, START, END, crop=CROP, duration=0.4, end_pause=0.25,
                              settle=0.05, poll_interval=0.1)
    auto.drag_mouse.assert_called_once_with(START, END, 0.4, 0.25)
    assert [call.args[0] for call in list_drag.time.sleep.call_args_list] == [0.05, 0.1, 0.1]


def test_partial_drag_refreshes_but_never_reports_success_or_replays():
    auto = ListScreen(["black", "white", "white", "white"], completed=False)
    assert list_drag.drag_list(auto, START, END, crop=CROP) is False
    assert auto.drags == 1
    assert auto.screenshot.getpixel((0, 0)) == (255, 255, 255)


def test_scene_that_keeps_moving_stops_at_limit():
    auto = ListScreen(["black", "white"] * 10)
    assert list_drag.drag_list(auto, START, END, crop=CROP) is False
    assert len(auto.crops) == 17


@pytest.mark.parametrize("offsets,expected", [([20, 10, 0, 0, 0], True), ([20, 10] * 8, False), ([None] * 16, False)])
def test_level_numbers_must_settle_even_with_an_animated_background(offsets, expected):
    auto = ListScreen(["black", "white"] * 10)
    positions = iter(offsets)

    def ocr():
        offset = next(positions)
        auto.ocr_result = [] if offset is None else [
            ([(offset, 0), (offset + 4, 0), (offset + 4, 5), (offset, 5)], ("01", 1.0))]

    auto.perform_ocr = ocr
    assert list_drag.drag_list(auto, START, END, crop=CROP, text_pattern=r"\d{2}") is expected


@pytest.mark.parametrize("last_page,limit,expected,drags", [(3, 8, True, 5), (20, 4, False, 4)])
def test_edge_requires_unchanged_pages_and_has_a_limit(last_page, limit, expected, drags):
    auto = ListScreen(["black"])

    def drag(*args):
        auto.drags += 1
        shade = min(auto.drags, last_page) * 40
        auto.frames = deque([Image.new("RGB", (30, 40), (shade, shade, shade))])
        return True

    auto.drag_mouse = drag
    assert list_drag.drag_to_edge(auto, START, END, crop=CROP, max_drags=limit) is expected
    assert auto.drags == drags


def test_interrupted_edge_search_does_not_continue():
    auto = ListScreen(["black", "white"], completed=False)
    assert list_drag.drag_to_edge(auto, START, END, crop=CROP) is False
    assert auto.drags == 1


@pytest.mark.parametrize("target_on_last_page", [True, False])
def test_quick_ornament_checks_page_after_final_drag(monkeypatch, target_on_last_page):
    from tasks.weekly import currency_wars

    drag = Mock(return_value=True)
    auto = Mock()
    auto.click_element.side_effect = lambda target, find_type, *args, **kwargs: (
        find_type != "min_distance_text" or (target_on_last_page and drag.call_count == 5)
    )
    auto.find_element.return_value = ((0, 0), (1, 1))
    monkeypatch.setattr(currency_wars, "auto", auto)
    monkeypatch.setattr(currency_wars, "drag_list", drag)
    monkeypatch.setattr(currency_wars, "screen", SimpleNamespace(change_to=Mock(), check_screen=Mock(return_value=True)))
    monkeypatch.setattr(currency_wars, "time", SimpleNamespace(sleep=Mock()))
    monkeypatch.setattr(currency_wars, "cfg", SimpleNamespace(
        instance_names={"饰品提取": "坚城不倒"}, build_target_enable=False,
    ))

    task = object.__new__(currency_wars.CurrencyWars)
    assert task.process_ornament() is target_on_last_page
    assert drag.call_count == 5
    assert sum(call.args[1] == "min_distance_text" for call in auto.click_element.call_args_list) == 6


def test_quick_ornament_releases_a_held_button_on_stop(monkeypatch):
    from types import MethodType

    from module.automation.automation import Automation
    from tasks.weekly import currency_wars
    from utils.pause import PauseController, RunStopRequested

    controller = PauseController()
    controller._enabled = True
    controller._resume_event.set()
    auto = Mock()
    auto.calculate_click_position.return_value = (100, 200)
    auto.click_element_with_pos = MethodType(Automation.click_element_with_pos, auto)
    auto.input_handler = SimpleNamespace(mouse_up=Mock())
    auto.find_element.side_effect = lambda *_args, **_kwargs: (
        controller.check_stop() or ((95, 195), (105, 205))
    )

    def down(_x, _y):
        controller.request_stop()
        return True

    auto.mouse_down.side_effect = down
    monkeypatch.setattr(currency_wars, "auto", auto)
    monkeypatch.setattr(currency_wars, "screen", Mock())
    monkeypatch.setattr(currency_wars, "time", SimpleNamespace(sleep=Mock()))
    monkeypatch.setattr(currency_wars, "cfg", SimpleNamespace(
        instance_names={"饰品提取": "坚城不倒"}, build_target_enable=False,
    ))

    with pytest.raises(RunStopRequested):
        currency_wars.CurrencyWars().process_ornament()

    auto.mouse_down.assert_called_once_with(100, 200)
    auto.input_handler.mouse_up.assert_called_once_with()
    auto.mouse_move.assert_not_called()
    auto.press_key.assert_not_called()
    assert auto.click_element.call_count == 3
